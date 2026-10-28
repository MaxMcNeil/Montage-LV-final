"""Synchro avec Vid-o-presse-finder : reprend un lot de résultats (par défaut le DERNIER, celui que tu as lancé avant
d'enregistrer ta vidéo) — extraits vidéo horodatés + articles — et l'IA décide lesquels correspondent à ce que tu
dis, et à quel moment. Réglage « finder » : dernier (défaut) | non | nom d'un lot (ex. 2026-10-24_2144_n16)."""
from __future__ import annotations

import csv
import datetime as dt
import json
import logging
import re
from pathlib import Path

from .util import tc

log = logging.getLogger("montage.finder")
LOT_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})_(\d{2})(\d{2})")


def load_lot(vpf: Path, which: str = "dernier", max_clips: int = 24, max_articles: int = 40) -> dict | None:
    res = vpf / "results"
    if not res.is_dir():
        log.info("Vid-o-presse-finder : dossier results introuvable")
        return None
    lots = sorted([d for d in res.iterdir() if d.is_dir() and LOT_RE.match(d.name)], key=lambda d: d.name)
    which = (which or "dernier").strip()
    if which.lower() in ("dernier", "oui", "yes", "last", "latest", "auto", ""):
        lot = lots[-1] if lots else None
    elif which.lower() == "osint":     # dernier lot lancé automatiquement par OSINT-teleprompter-
        lot = next((d for d in reversed(lots) if _origine(d)), None)
    else:
        lot = next((d for d in lots if d.name.lower() == which.lower()), None) \
            or next((d for d in reversed(lots) if d.name.lower().startswith(which.lower())), None) \
            or _by_subject(lots, which)
    if not lot:
        log.info("Vid-o-presse-finder : aucun lot « %s »", which)
        return None
    clips = []
    try:
        clips = json.loads((lot / "montage.json").read_text(encoding="utf-8")).get("clips", [])
    except (OSError, ValueError):
        for f in sorted(lot.glob("*/montage.json")):
            try:
                clips += json.loads(f.read_text(encoding="utf-8")).get("clips", [])
            except (OSError, ValueError):
                continue
    clips = [c for c in clips if c.get("source_url") and c.get("verdict") != "denial"]
    clips.sort(key=lambda c: -float(c.get("score") or 0))
    arts, seen = [], set()
    for f in sorted(lot.glob("*/articles.csv")):
        try:
            with open(f, encoding="utf-8-sig") as fh:
                for r in csv.DictReader(fh):
                    if r.get("titre") and r.get("url") and r["url"] not in seen:
                        seen.add(r["url"])
                        arts.append(r)
        except OSError:
            continue
    arts.sort(key=lambda r: -_f(r.get("autorite")))
    posts, contre = read_posts(lot.glob("*/posts.csv")), []
    contre = [a for a in arts if (a.get("position") or "").strip() == "contre"] + [p for p in posts if p.get("position") == "contre"]
    arts = [a for a in arts if (a.get("position") or "").strip() != "contre"]
    # messages Telegram / Reddit : après les articles de presse (moins d'autorité), présentés comme des articles
    arts += [p for p in posts if p.get("position") != "contre"][:4]
    m = LOT_RE.match(lot.name)
    age = None
    try:
        when = dt.datetime(*map(int, m.groups()), tzinfo=dt.timezone.utc)
        age = (dt.datetime.now(dt.timezone.utc) - when).days
    except (TypeError, ValueError):
        pass
    searches = sorted({" | ".join(x for x in (c.get("target", ""), c.get("claim", "")) if x) for c in clips} - {""})
    origine = _origine(lot)
    if origine:     # lot lancé par OSINT-teleprompter- : le sujet et la thèse du live guident le choix des extraits
        live = f"live « {(origine.get('sujet') or origine.get('court') or '')[:300]} »"
        if origine.get("demontrer"):
            live += f" (thèse : {origine['demontrer'][:250]})"
        searches = [live] + searches
    log.info("Vid-o-presse-finder : lot %s (%s jour(s)) — %d extrait(s), %d article(s) — %s", lot.name, age, len(clips),
             len(arts), "; ".join(searches))
    return {"lot": lot.name, "age_days": age, "clips": clips[:max_clips], "articles": arts[:max_articles],
            "searches": searches, "origine": origine, "contre": contre[:12]}


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def read_posts(files) -> list[dict]:
    """posts.csv (Telegram / Reddit) → lignes au format des articles (titre, source, url, date, autorite, position)."""
    out, seen = [], set()
    for f in sorted(files):
        try:
            with open(f, encoding="utf-8-sig") as fh:
                for r in csv.DictReader(fh):
                    url, txt = (r.get("url") or "").strip(), " ".join((r.get("texte") or "").split())
                    if not url or not txt or url in seen:
                        continue
                    seen.add(url)
                    plat = (r.get("plateforme") or "").strip().lower()
                    out.append({"titre": txt[:150] + ("…" if len(txt) > 150 else ""), "url": url,
                                "source": f"{'Telegram' if plat == 'telegram' else 'Reddit'} · {r.get('chaine') or ''}".strip(" ·"),
                                "domaine": "t.me" if plat == "telegram" else "reddit.com", "date": r.get("date") or "",
                                "autorite": "0.3", "position": (r.get("position") or "").strip(), "social": plat,
                                "audience": _f(r.get("audience"))})
        except (OSError, csv.Error):
            continue
    out.sort(key=lambda r: -r["audience"])
    return out


def _origine(lot: Path) -> dict:
    """ORIGINE.json d'un lot lancé par OSINT-teleprompter- ({} si lancé à la main)."""
    try:
        o = json.loads((lot / "ORIGINE.json").read_text(encoding="utf-8"))
        return o if isinstance(o, dict) else {}
    except (OSError, ValueError):
        return {}


def _norm(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", str(s or "").lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _by_subject(lots: list, which: str):
    """Réglage « finder: suisse microsoft » : dernier lot OSINT dont le sujet contient tous ces mots."""
    words = [w for w in _norm(which).split() if len(w) > 2]
    if not words:
        return None
    for d in reversed(lots):
        o = _origine(d)
        hay = _norm(" ".join(str(o.get(k) or "") for k in ("sujet", "court", "dossier")))
        if o and all(w in hay for w in words):
            return d
    return None


PROMPT = """Tu es le monteur d'une vidéo face caméra (langue « {lang} »). Avant d'enregistrer, l'auteur a lancé une
recherche de presse ({searches}). Voici ce qu'elle a trouvé, puis ce que dit l'auteur, phrase par phrase.

DÉCLARATIONS EN VIDÉO (horodatées) :
{clips}

ARTICLES :
{articles}

CE QUE DIT L'AUTEUR :
{sentences}

Choisis UNIQUEMENT ce qui correspond à ce que dit l'auteur (même fait, même déclaration, même personne, même sujet) :
- "inserts" : au plus {max_ins} déclarations vidéo, insérées pendant un silence de l'auteur, juste APRÈS la phrase où il
  en parle ou l'annonce : [{{"clip": numéro, "after": numéro de phrase, "s0": première phrase où il en parle,
  "quote": "la déclaration traduite si besoin en « {lang} », fidèle, 12 à 30 mots"}}]. Jamais deux après la même phrase,
  au moins 3 phrases d'écart entre deux insertions, aucune avant la phrase 2. Une déclaration longue peut être
  utilisée en PLUSIEURS morceaux si l'auteur en commente plusieurs parties : répète le même numéro avec des
  "part" différents (1, 2…). UNIQUEMENT ce qui est en totale concordance avec ce que dit l'auteur à cet endroit.
- "articles" : au plus {max_art} articles affichés à côté de l'auteur quand il évoque ce qu'ils racontent :
  [{{"article": numéro, "s0": numéro de phrase, "headline": "titre traduit en « {lang} » si besoin (sinon le titre)"}}].
  Pas deux articles sur la même phrase ni sur la phrase d'une insertion. Prends TOUS ceux qui correspondent vraiment.
Si rien ne correspond, renvoie des listes vides. Réponds en JSON : {{"inserts": [...], "articles": [...]}}."""


def max_articles_for(sents: list) -> int:
    """Articles affichables selon la durée de parole : ~1 par minute et demie, entre 6 et 30."""
    speech = (sents[-1]["t1"] - sents[0]["t0"]) / 60 if sents else 0
    return int(max(6, min(30, round(speech / 1.5))))


def match(ai, sents: list, lot: dict, lang: str, max_ins: int) -> dict:
    """L'IA associe chaque déclaration / article du lot au moment où tu en parles."""
    out = {"inserts": [], "articles": []}
    if not sents or not (lot.get("clips") or lot.get("articles")) or not ai or not ai.ok:
        return out
    clips = "\n".join(f'[{i}] {c.get("speaker") or "?"} — {c.get("channel") or c.get("platform") or ""} '
                      f'{c.get("uploaded") or ""} ({c.get("duration", 0):.0f} s) : « {(c.get("quote") or "")[:350]} »'
                      for i, c in enumerate(lot["clips"])) or "(aucune)"
    arts = "\n".join(f'[{i}] {a.get("source") or a.get("domaine")} {a.get("date") or ""} : {a.get("titre")}'
                     for i, a in enumerate(lot["articles"])) or "(aucun)"
    text = "\n".join(f'[{s["i"]}] ({tc(s["t0"])}) {s["text"]}' for s in sents)
    if len(text) > 100_000:
        text = "\n".join(f'[{s["i"]}] ({tc(s["t0"])}) {s["text"][:150]}' for s in sents)
    max_art = max_articles_for(sents)
    j = ai.json(PROMPT.format(lang=lang, searches="; ".join(lot.get("searches") or []) or "même sujet", clips=clips,
                              articles=arts, sentences=text, max_ins=max(1, max_ins), max_art=max_art))
    if not isinstance(j, dict):
        return out
    n = len(sents)

    def ii(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None
    afters = []
    for x in j.get("inserts") or []:
        c, after = ii(x.get("clip")), ii(x.get("after"))
        if c is None or not 0 <= c < len(lot["clips"]) or after is None or not 1 <= after < n:
            continue
        if sum(1 for y in out["inserts"] if y["clip"] == c) >= 3:   # au plus 3 morceaux d'une même déclaration
            continue
        if any(abs(after - a) < 3 for a in afters) or len(afters) >= max(1, max_ins):
            continue
        s0 = ii(x.get("s0"))
        s0 = s0 if s0 is not None and 0 <= s0 <= after else after
        afters.append(after)
        out["inserts"].append({"clip": c, "after": after, "s0": s0, "quote": str(x.get("quote") or "").strip()[:300]})
    taken = set(afters)
    for x in j.get("articles") or []:
        a, s0 = ii(x.get("article")), ii(x.get("s0"))
        if a is None or not 0 <= a < len(lot["articles"]) or s0 is None or not 0 <= s0 < n or s0 in taken:
            continue
        if a in {y["article"] for y in out["articles"]} or len(out["articles"]) >= max_art:
            continue
        taken.add(s0)
        out["articles"].append({"article": a, "s0": s0, "headline": str(x.get("headline") or "").strip()[:200]})
    log.info("Vid-o-presse-finder : %d déclaration(s) et %d article(s) en rapport avec ta vidéo",
             len(out["inserts"]), len(out["articles"]))
    return out
