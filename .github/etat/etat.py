"""ETAT.md générique : état des workflows du dépôt, cause des échecs en clair, quand ça se débloque, quoi faire.

Lit l'API GitHub (jeton du workflow, lecture seule des Actions), classe l'erreur du journal de l'étape en échec,
écrit ETAT.md (ou seulement le bloc entre <!-- workflows:start --> et <!-- workflows:end --> s'il existe déjà).
Bibliothèque standard Python uniquement : rien à installer, rien qui puisse casser avec le temps.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

try:
    from zoneinfo import ZoneInfo
    ROME, PACIFIC = ZoneInfo("Europe/Rome"), ZoneInfo("America/Los_Angeles")
except Exception:  # noqa: BLE001
    ROME, PACIFIC = dt.timezone(dt.timedelta(hours=1)), dt.timezone(dt.timedelta(hours=-8))

API = os.environ.get("GITHUB_API_URL", "https://api.github.com")
REPO = os.environ.get("GITHUB_REPOSITORY", "")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
SELF = os.environ.get("ETAT_WORKFLOW_NAME", "État")
START, END = "<!-- workflows:start -->", "<!-- workflows:end -->"


class _NoAuthRedirect(urllib.request.HTTPRedirectHandler):
    """Les journaux sont servis par un stockage externe : on ne lui envoie pas le jeton GitHub."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            new.headers.pop("Authorization", None)
            new.unredirected_hdrs.pop("Authorization", None)
        return new


_opener = urllib.request.build_opener(_NoAuthRedirect)


def gh(path: str, raw: bool = False):
    req = urllib.request.Request(path if path.startswith("http") else f"{API}{path}",
                                 headers={"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json",
                                          "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "etat"})
    for attempt in range(3):
        try:
            with _opener.open(req, timeout=60) as r:
                data = r.read()
                return data.decode("utf-8", "replace") if raw else json.loads(data)
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return "" if raw else {}
            if attempt == 2:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2:
                raise
        time.sleep(3 * (attempt + 1))
    return "" if raw else {}


def next_pacific_midnight() -> float:
    now = dt.datetime.now(PACIFIC)
    return (now + dt.timedelta(days=1)).replace(hour=0, minute=1, second=0, microsecond=0).timestamp()


def hm(t: float) -> str:
    d, now = dt.datetime.fromtimestamp(t, ROME), dt.datetime.now(ROME)
    h = f"{d.hour} h {d.minute:02d}"
    if d.date() == now.date():
        return f"aujourd'hui à {h}"
    if d.date() == (now + dt.timedelta(days=1)).date():
        return f"demain à {h}"
    return f"le {d.strftime('%d/%m')} à {h}"


def when(iso: str) -> str:
    try:
        t = dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(ROME)
    except (ValueError, AttributeError):
        return "?"
    return t.strftime("%d/%m à %H:%M")


# ---------------------------------------------------------------- reconnaissance des erreurs
APIS = [  # (motif dans le journal, nom lisible, remise à zéro du quota)
    (r"generativelanguage|gemini", "Gemini (Google IA)", "pacific"),
    (r"youtube\.googleapis|youtube/v3|youtubeAnalytics|liveBroadcast|liveStream", "YouTube (API Google)", "pacific"),
    (r"googleapis\.com/drive|drive\.google|rclone|googleapi: Error", "Google Drive", "pacific"),
    (r"api\.groq\.com|groq", "Groq", "24h"),
    (r"api\.cerebras|cerebras", "Cerebras", "24h"),
    (r"openrouter", "OpenRouter", "24h"),
    (r"api\.anthropic\.com|anthropic|claude-", "Anthropic (Claude)", "credit"),
    (r"api\.twitter\.com|api\.x\.com|x_bearer|tweepy", "X / Twitter", "15min"),
    (r"oauth2\.googleapis|accounts\.google", "Connexion Google (OAuth)", "pacific"),
    (r"ollama", "Ollama", "none"),
]


def which_api(text: str) -> tuple[str, str]:
    low = text.lower()
    for rx, name, reset in APIS:
        if re.search(rx, low):
            return name, reset
    return "une API externe", "unknown"


def unblock(reset: str, per_minute: bool) -> str:
    if per_minute:
        return "se débloque seul en quelques minutes : relance le workflow un peu plus tard"
    return {"pacific": f"se débloque {hm(next_pacific_midnight())} (remise à zéro des quotas Google)",
            "24h": "se débloque d'ici 24 h maximum (quota glissant)",
            "15min": "se débloque d'ici 15 min (fenêtre de X/Twitter)",
            "credit": "ne se débloque pas seul : recharge le crédit sur console.anthropic.com",
            }.get(reset, "se débloque généralement d'ici quelques heures")


RULES = [  # (motif, catégorie, explication, action)  — l'ordre compte : du plus précis au plus général
    (r"credit balance is too low|insufficient.?(credit|funds|balance)|billing", "credit",
     "crédit ou facturation insuffisant chez {api}", "recharge le crédit ou active la facturation du compte {api}"),
    (r"invalid_grant|token has been expired or revoked|refresh token|oauth.*(expired|revoked)", "auth",
     "la connexion Google (jeton de rafraîchissement) a expiré ou a été révoquée",
     "régénère le jeton (secret GOOGLE_REFRESH_TOKEN, RCLONE_CONF/RCLONE_CONFIG…) puis mets à jour le secret"),
    (r"api key not valid|invalid api key|invalid x-api-key|incorrect api key|api_key_invalid|unauthorized|\b401\b|bad credentials",
     "auth", "clé ou jeton refusé par {api} (invalide, expiré ou supprimé)", "vérifie / renouvelle le secret de {api} dans Settings → Secrets"),
    (r"sign in to confirm you.?re not a bot|confirm you.?re not a bot", "youtube_bot",
     "YouTube bloque les serveurs de GitHub (vérification anti-robot)",
     "rien à corriger dans le code : contournement nécessaire (analyse par Gemini, téléphone, ou cookies d'un compte secondaire)"),
    (r"resource_exhausted|quota ?exceeded|exceeded your current quota|ratelimitexceeded|userratelimitexceeded|dailylimitexceeded|"
     r"too many requests|\b429\b|rate.?limit", "quota", "quota ou limite atteint chez {api}", "{unblock}"),
    (r"storagequotaexceeded|storage quota", "storage", "espace de stockage plein ({api})", "libère de la place sur le Drive ou les Releases"),
    (r"permission_denied|\b403\b|forbidden|access denied", "forbidden", "accès refusé par {api}",
     "vérifie que l'API est activée sur le projet Google / que le compte a les droits ; sinon renouvelle le secret"),
    (r"no space left on device", "disk", "disque du serveur GitHub plein pendant le travail",
     "fichier trop gros pour le runner : réduire la taille ou découper le traitement"),
    (r"exceeded the maximum execution time|timed? ?out after", "timeout",
     "le travail a dépassé le temps maximum", "relance ; si ça se répète, la vidéo/le traitement est trop long"),
    (r"\b50[234]\b|service unavailable|high demand|overloaded|bad gateway", "busy",
     "{api} était surchargé ou en panne au moment du lancement", "passager : relance le workflow un peu plus tard"),
    (r"could not resolve host|name or service not known|connection (reset|refused)|temporary failure in name resolution|read timed out",
     "network", "problème réseau temporaire vers {api}", "passager : relance le workflow"),
    (r"\[rejected\]|non-fast-forward|failed to push some refs", "git",
     "deux lancements ont voulu enregistrer en même temps", "passager : relance (ou évite deux lancements simultanés)"),
    (r"no such file or directory|file not found|not found:|404", "missing", "un fichier, une Release ou une ressource attendue est introuvable",
     "vérifie le nom / le lien du fichier fourni au workflow"),
]


ANSI = re.compile(r"\x1b\[[0-9;]*m|\[[0-9;]*m")


def classify(log: str) -> dict:
    lines = [l for l in log.splitlines() if l.strip()]
    # retire l'horodatage GitHub ; ignore les commandes réaffichées par GitHub (en couleur) et les en-têtes de groupe
    clean = []
    for l in lines:
        echoed = "\x1b[36;1m" in l or "[36;1m" in l
        l = ANSI.sub("", re.sub(r"^\S+Z\s", "", l))
        if echoed or l.startswith(("##[group]", "##[endgroup]", "shell:", "env:")):
            continue
        clean.append(l)
    tail = "\n".join(clean[-400:])
    low = tail.lower()
    api, reset = which_api(tail)
    per_minute = bool(re.search(r"per.?minute|perminute|retry in \d+(\.\d+)?s|retrydelay|userratelimitexceeded|ratelimitexceeded", low))
    for rx, cat, expl, action in RULES:
        m = re.search(rx, low)
        if m:
            line = next((l for l in reversed(clean) if re.search(rx, l.lower())), "")
            a, r = which_api(line) if which_api(line)[0] != "une API externe" else (api, reset)
            u = unblock(r, per_minute)
            return {"cat": cat, "explication": expl.format(api=a), "action": action.format(api=a, unblock=u),
                    "ligne": line.strip()[:220], "api": a}
    err = next((l for l in reversed(clean) if re.search(r"(error|erreur|exception|traceback|failed|échec|fatal|invalid|no such)", l.lower())
                and "##[" not in l and "exit code" not in l), "")
    # un message « QUOI FAIRE » écrit par le programme lui-même est la meilleure explication possible
    quoi = next((l.split(":", 1)[1].strip() for l in clean if l.strip().upper().startswith("QUOI FAIRE")), "")
    if quoi:
        idx = next(i for i, l in enumerate(clean) if l.strip().upper().startswith("QUOI FAIRE"))
        quoi = " ".join([quoi] + [l.strip() for l in clean[idx + 1: idx + 3] if l.strip() and not l.startswith("##[")])
        head = next((l for l in reversed(clean[:idx]) if re.search(r"erreur|error", l.lower())), err)
        return {"cat": "explique", "explication": head.replace("ERREUR :", "").strip()[:200] or "erreur expliquée par le programme",
                "action": quoi[:300], "ligne": "", "api": ""}
    exc = next((l for l in reversed(clean) if re.match(r"^\s*[A-Za-z_.]+(Error|Exception):", l)), "")
    return {"cat": "bug", "explication": "erreur dans le programme (pas un problème de quota ni de clé)",
            "action": "à corriger dans le code : transmets la ligne d'erreur ci-dessous", "ligne": (exc or err).strip()[:220], "api": ""}


# ---------------------------------------------------------------- collecte
def cron_interval_h(path: str) -> float | None:
    """Intervalle approximatif d'une tâche planifiée (pour repérer une tâche qui ne tourne plus)."""
    try:
        txt = gh(f"/repos/{REPO}/contents/{urllib.request.quote(path)}").get("content", "")
        import base64
        y = base64.b64decode(txt).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return None
    m = re.search(r"cron:\s*['\"]([^'\"]+)['\"]", y)
    if not m:
        return None
    f = m.group(1).split()
    if len(f) < 5:
        return None
    if f[1].startswith("*/"):
        return float(f[1][2:])
    if f[1] == "*":
        return 1.0
    if f[4] not in ("*", "?"):
        return 24 * 7.0
    return 24.0 / max(1, len(f[1].split(",")))


def collect() -> list[dict]:
    out = []
    for w in gh(f"/repos/{REPO}/actions/workflows?per_page=100").get("workflows", []):
        if w.get("name") == SELF or w.get("path", "").endswith("etat.yml") or "pages-build" in w.get("path", ""):
            continue
        runs = gh(f"/repos/{REPO}/actions/workflows/{w['id']}/runs?per_page=15").get("workflow_runs", [])
        done = [r for r in runs if r.get("status") == "completed" and r.get("conclusion") not in ("skipped",)]
        item = {"name": w.get("name"), "path": w.get("path"), "state": w.get("state"), "runs": len(runs)}
        if w.get("state", "active") != "active":
            item["icon"], item["texte"] = "❌", ("désactivé par GitHub (60 jours sans activité sur le dépôt)" if "inactivity" in w.get("state", "")
                                                else f"désactivé ({w.get('state')})")
            item["action"] = "Actions → ce workflow → « Enable workflow »"
            out.append(item)
            continue
        if not done:
            item["icon"], item["texte"] = "ℹ️", "jamais lancé (ou en cours)"
            out.append(item)
            continue
        last = done[0]
        item["last"] = when(last.get("updated_at", ""))
        item["url"] = last.get("html_url", "")
        ok = last.get("conclusion") == "success"
        last_ok = next((r for r in done if r.get("conclusion") == "success"), None)
        fails = 0
        for r in done:
            if r.get("conclusion") == "success":
                break
            if r.get("conclusion") != "cancelled":
                fails += 1
        if ok:
            item["icon"], item["texte"] = "✅", f"dernier lancement réussi ({item['last']})"
        elif last.get("conclusion") == "cancelled":
            item["icon"], item["texte"] = "ℹ️", (f"dernier lancement annulé ({item['last']}) — à la main ou remplacé par un plus récent"
                                                + (f" ; dernier succès le {when(last_ok['updated_at'])}" if last_ok else ""))
        else:
            item["icon"] = "❌" if fails >= 2 or last.get("conclusion") == "failure" else "⚠️"
            item["texte"] = (f"dernier lancement en échec ({item['last']}, {last.get('conclusion')})"
                             + (f", {fails} échecs d'affilée" if fails > 1 else "")
                             + (f" — dernier succès le {when(last_ok['updated_at'])}" if last_ok else ""))
            jobs = gh(f"/repos/{REPO}/actions/runs/{last['id']}/jobs?per_page=50").get("jobs", [])
            bad = next((j for j in jobs if j.get("conclusion") in ("failure", "timed_out", "cancelled")), None)
            if bad:
                step = next((s.get("name") for s in bad.get("steps", []) if s.get("conclusion") in ("failure", "timed_out", "cancelled")), "")
                item["etape"] = f"{bad.get('name')} → {step}" if step else bad.get("name")
                try:
                    log = gh(f"/repos/{REPO}/actions/jobs/{bad['id']}/logs", raw=True)
                except Exception as e:  # noqa: BLE001
                    log = f"(journal illisible : {e})"
                c = classify(log or "")
                if last.get("conclusion") == "cancelled":
                    c = {"cat": "cancelled", "explication": "lancement annulé (à la main, ou remplacé par un lancement plus récent)",
                         "action": "rien à faire si c'était voulu", "ligne": "", "api": ""}
                item.update(c)
        iv = cron_interval_h(w.get("path", ""))
        if iv and runs:
            try:
                age_h = (time.time() - dt.datetime.fromisoformat(runs[0]["created_at"].replace("Z", "+00:00")).timestamp()) / 3600
            except (KeyError, ValueError):
                age_h = 0
            if os.environ.get("ETAT_CRON_CHECK") == "1" and age_h > max(3 * iv, iv + 6):
                item["icon"] = "⚠️"
                item["texte"] += f" — ⚠️ tâche planifiée toutes les ~{iv:g} h mais aucun lancement depuis {age_h:.0f} h"
                item.setdefault("action", "GitHub retarde ou suspend parfois les tâches planifiées ; vérifie qu'elle est active "
                                          "(Actions → workflow) et lance-la à la main une fois")
        out.append(item)
    return out


def render(items: list[dict]) -> str:
    now = dt.datetime.now(ROME).strftime("%d/%m/%Y à %H:%M")
    todo = [i for i in items if i.get("icon") in ("❌", "⚠️")]
    L = [START, "## Workflows", "",
         f"_Vérifié le {now} (heure italienne), automatiquement à la fin de chacun de tes lancements (aucune exécution planifiée)._", ""]
    if not todo:
        L.append("✅ **Tout fonctionne** : aucun workflow en échec.")
        L.append("")
    for i in items:
        L.append(f"- {i.get('icon', 'ℹ️')} **{i['name']}** : {i.get('texte', '')}" + (f" · [voir]({i['url']})" if i.get("url") else ""))
        if i.get("explication"):
            L.append(f"  - **Cause** : {i['explication']}" + (f" (étape « {i['etape']} »)" if i.get("etape") else ""))
        if i.get("action") and i.get("icon") in ("❌", "⚠️"):
            L.append(f"  - **Quoi faire** : {i['action']}")
        if i.get("ligne") and i.get("icon") in ("❌", "⚠️"):
            L.append(f"  - Message : `{i['ligne'].replace('`', ' ')}`")
    L += ["", END]
    return "\n".join(L)


def signature(block: str) -> str:
    """Contenu sans dates : un commit seulement si l'état change vraiment."""
    return re.sub(r"_Vérifié le [^_]*_|\(\d\d/\d\d à \d\d:\d\d[^)]*\)|le \d\d/\d\d à \d\d:\d\d|aujourd'hui à \d+ h \d\d|"
                  r"demain à \d+ h \d\d|depuis \d+ h|\[voir\]\([^)]*\)", "", block)


def main() -> int:
    items = collect()
    block = render(items)
    path = os.environ.get("ETAT_FILE", "ETAT.md")
    try:
        old = open(path, encoding="utf-8").read()
    except OSError:
        old = ""
    if START in old and END in old:
        before, rest = old.split(START, 1)
        after = rest.split(END, 1)[1]
        old_block = START + rest.split(END, 1)[0] + END
        new = before + block + after
    else:
        old_block = ""
        title = f"# État — {REPO.split('/')[-1]}\n\nCe qui bloque, pourquoi, quand ça se débloque et quoi faire.\n\n"
        new = (old.rstrip() + "\n\n" + block + "\n") if old.strip() else title + block + "\n"
    changed = signature(old_block) != signature(block) or not old
    if changed:
        open(path, "w", encoding="utf-8").write(new)
    summ = os.environ.get("GITHUB_STEP_SUMMARY")
    if summ:
        open(summ, "a", encoding="utf-8").write(block + "\n")
    print(block)
    print("CHANGED" if changed else "UNCHANGED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
