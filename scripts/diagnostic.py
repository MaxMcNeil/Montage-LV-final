#!/usr/bin/env python3
"""Diagnostic des clés de Montage LV final — à lancer à la main (onglet Actions → Diagnostic).

Économe : AU PLUS une toute petite demande par clé d'IA (« réponds OK »), le reste en vérifications gratuites
(liste des modèles, quota restant). Aucune clé n'est jamais affichée : seulement « clé 1, clé 2… ».
Écrit un tableau lisible dans le résumé du run (et sur la sortie standard)."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from montage.ai import gemini_models, keys  # noqa: E402

T = 25
rows: list[tuple[str, str, str]] = []


def add(what: str, ok: str, detail: str) -> None:
    rows.append((what, ok, detail))
    print(f"{ok} {what} — {detail}", flush=True)


def short(r) -> str:
    try:
        j = r.json()
        msg = (j.get("error") or {}).get("message") if isinstance(j.get("error"), dict) else j.get("error") or j.get("message")
        return f"HTTP {r.status_code} {str(msg or '')[:90]}"
    except ValueError:
        return f"HTTP {r.status_code}"


def gemini() -> None:
    groups = [("GEMINI_API_KEYS", "GEMINI_API_KEY", "GEMINI_API_KEYS_PLUS"), ("GEMINI_API_KEYS_PARTAGE",)]
    for label, names in (("Gemini", groups[0]), ("Gemini réserve (PARTAGE)", groups[1])):
        ks = keys(*names)
        if not ks:
            add(label, "➖", "aucune clé")
            continue
        for n, k in enumerate(ks, 1):
            what = f"{label} clé {n}"
            try:
                r = requests.get("https://generativelanguage.googleapis.com/v1beta/models", params={"key": k, "pageSize": 200},
                                 timeout=T)
            except requests.RequestException as e:
                add(what, "⚠", f"Google injoignable ({type(e).__name__})")
                continue
            if r.status_code != 200:
                add(what, "❌", f"clé refusée : {short(r)}")
                continue
            models = gemini_models(k)
            ok_m, last = None, ""
            for m in models[:4]:          # une seule demande réussie suffit ; on n'essaie que si le modèle refuse
                try:
                    g = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent",
                                      params={"key": k}, timeout=60,
                                      json={"contents": [{"role": "user", "parts": [{"text": "Réponds seulement : OK"}]}],
                                            "generationConfig": {"maxOutputTokens": 5, "temperature": 0}})
                except requests.RequestException as e:
                    last = type(e).__name__
                    continue
                if g.status_code == 200:
                    ok_m = m
                    break
                last = short(g)
                if g.status_code == 429:
                    continue          # quota de CE modèle : les autres modèles ont chacun le leur
                if g.status_code >= 500:
                    time.sleep(2)
            if ok_m:
                add(what, "✅", f"répond ({ok_m}) — {len(models) - 2} modèle(s) Flash disponibles")
            elif "429" in last:
                add(what, "⚠", f"clé valide, mais quota du moment atteint sur les modèles essayés ({last}) — repart à 9 h")
            elif re.search(r"50\d", last):
                add(what, "⚠", f"clé valide, Google surchargé en ce moment ({last}) — pas un problème de clé")
            else:
                add(what, "❌", f"clé valide mais aucune réponse ({last})")


def openai_like(label: str, names: tuple, base: str, model_pref: str = "") -> None:
    ks = keys(*names)
    if label == "Groq":
        ks += [k for k in keys("FALLBACK_LLM_KEYS") if k.startswith("gsk_") and k not in ks]
    if label == "Cerebras":
        ks += [k for k in keys("FALLBACK_LLM_KEYS") if k.startswith("csk-") and k not in ks]
    if label == "OpenRouter":
        ks += [k for k in keys("FALLBACK_LLM_KEYS") if k.startswith("sk-or-") and k not in ks]
    if not ks:
        add(label, "➖", "aucune clé (facultatif : relais si Gemini ne répond pas)")
        return
    for n, k in enumerate(ks, 1):
        what = f"{label} clé {n}"
        h = {"authorization": f"Bearer {k}"}
        try:
            if label == "OpenRouter":      # gratuit : quota restant de la clé, sans aucune demande d'IA
                r = requests.get(f"{base}/key", headers=h, timeout=T)
                if r.status_code == 200:
                    d = r.json().get("data") or {}
                    add(what, "✅", f"valide — limite : {d.get('limit') or 'modèles :free'} ; utilisé : {d.get('usage', 0)}")
                else:
                    add(what, "❌", f"clé refusée : {short(r)}")
                continue
            r = requests.get(f"{base}/models", headers=h, timeout=T)
            if r.status_code != 200:
                add(what, "❌", f"clé refusée : {short(r)}")
                continue
            ids = [m.get("id", "") for m in r.json().get("data") or []]
            m = next((x for x in ids if model_pref and model_pref in x), None) or next(
                (x for x in ids if re.search(r"llama|gpt-oss|qwen", x) and not re.search(r"whisper|guard|tts", x)), None)
            if not m:
                add(what, "⚠", f"clé valide, aucun modèle de texte trouvé ({len(ids)} modèles)")
                continue
            c = requests.post(f"{base}/chat/completions", headers=h, timeout=60,
                              json={"model": m, "messages": [{"role": "user", "content": "Réponds seulement : OK"}],
                                    "max_tokens": 5, "temperature": 0})
            if c.status_code == 200:
                add(what, "✅", f"répond ({m})")
            elif c.status_code == 429:
                add(what, "⚠", f"clé valide, limite du moment atteinte ({short(c)})")
            else:
                add(what, "❌", f"clé valide mais refus : {short(c)}")
        except requests.RequestException as e:
            add(what, "⚠", f"service injoignable ({type(e).__name__})")


def groq_whisper() -> None:
    ks = keys("GROQ_API_KEYS", "GROQ_API_KEY", "GROQ_API_KEYS_PLUS") + [
        k for k in keys("FALLBACK_LLM_KEYS") if k.startswith("gsk_")]
    if not ks:
        return
    try:
        r = requests.get("https://api.groq.com/openai/v1/models", headers={"authorization": f"Bearer {ks[0]}"}, timeout=T)
        ids = [m.get("id", "") for m in r.json().get("data") or []] if r.status_code == 200 else []
        w = [x for x in ids if "whisper" in x]
        add("Transcription (Groq Whisper)", "✅" if w else "⚠",
            f"disponible ({', '.join(w[:2])})" if w else "modèle de transcription introuvable : transcription sur la "
                                                       "machine GitHub (plus lente, aussi fiable)")
    except requests.RequestException as e:
        add("Transcription (Groq Whisper)", "⚠", f"injoignable ({type(e).__name__}) : transcription sur la machine GitHub")


def search_keys() -> None:
    yk = keys("YOUTUBE_API_KEYS", "YOUTUBE_API_KEYS_PLUS")
    for n, k in enumerate(yk, 1):     # 1 unité sur 10 000 par jour
        try:
            r = requests.get("https://www.googleapis.com/youtube/v3/videos",
                             params={"part": "id", "id": "jNQXAC9IVRw", "key": k}, timeout=T)
            add(f"YouTube clé {n}", "✅" if r.status_code == 200 else "❌",
                "répond (1 unité utilisée sur 10 000)" if r.status_code == 200 else short(r))
        except requests.RequestException as e:
            add(f"YouTube clé {n}", "⚠", f"injoignable ({type(e).__name__})")
    for n, k in enumerate(keys("GUARDIAN_API_KEYS"), 1):
        try:
            r = requests.get("https://content.guardianapis.com/search", params={"q": "europe", "page-size": 1, "api-key": k},
                             timeout=T)
            add(f"Guardian clé {n}", "✅" if r.status_code == 200 else "❌", "répond" if r.status_code == 200 else short(r))
        except requests.RequestException as e:
            add(f"Guardian clé {n}", "⚠", f"injoignable ({type(e).__name__})")
    for n, k in enumerate(keys("NYT_API_KEYS"), 1):
        try:
            r = requests.get("https://api.nytimes.com/svc/search/v2/articlesearch.json", params={"q": "europe", "api-key": k},
                             timeout=T)
            add(f"NYT clé {n}", "✅" if r.status_code == 200 else ("⚠" if r.status_code == 429 else "❌"),
                "répond" if r.status_code == 200 else short(r))
        except requests.RequestException as e:
            add(f"NYT clé {n}", "⚠", f"injoignable ({type(e).__name__})")
    if not yk:
        add("YouTube", "➖", "aucune clé (recherche seulement)")
    tg = all(os.environ.get(x) for x in ("TG_API_ID", "TG_API_HASH", "TG_SESSION"))
    add("Telegram", "✅" if tg else "➖", "les 3 secrets sont présents (connexion testée par le Diagnostic du Finder)"
        if tg else "secrets absents (recherche seulement)")


def drive() -> None:
    conf = os.environ.get("RCLONE_CONF") or ""
    if not conf.strip():
        add("Google Drive (RCLONE_CONF)", "➖", "absent : nécessaire seulement pour la chaîne et les gros fichiers")
        return
    os.makedirs(os.path.expanduser("~/.config/rclone"), exist_ok=True)
    with open(os.path.expanduser("~/.config/rclone/rclone.conf"), "w", encoding="utf-8") as f:
        f.write(conf + "\n")
    remote = (re.findall(r"^\[([^\]]+)\]", conf, re.M) or [""])[0]
    try:
        r = subprocess.run(["rclone", "about", f"{remote}:", "--json"], capture_output=True, text=True, timeout=90)
        if r.returncode == 0:
            import json
            free = (json.loads(r.stdout).get("free") or 0) / 1e9
            add("Google Drive (RCLONE_CONF)", "✅" if free > 5 else "⚠",
                f"connecté — {free:.1f} Go libres" + (" (peu de place : vide aussi la corbeille)" if free <= 5 else ""))
        else:
            add("Google Drive (RCLONE_CONF)", "❌", f"refusé : {(r.stderr or '').strip().splitlines()[-1][:120] if r.stderr else '?'}"
                " — jeton expiré ? refais la config rclone")
    except (OSError, subprocess.SubprocessError) as e:
        add("Google Drive (RCLONE_CONF)", "⚠", f"test impossible ({type(e).__name__})")


def chaine() -> None:
    tok = os.environ.get("CHAINE_GH_TOKEN") or ""
    if not tok:
        add("Chaîne → Shorts (jeton)", "➖", "aucun jeton (CHAINE_APP_KEY / CHAINE_TOKEN) : Shorts enchaînés impossibles")
        return
    try:
        r = requests.get("https://api.github.com/repos/MaxMcNeil/Push-overlay",
                         headers={"authorization": f"Bearer {tok}", "accept": "application/vnd.github+json"}, timeout=T)
        add("Chaîne → Shorts (jeton)", "✅" if r.status_code == 200 else "❌",
            "accès à Push-overlay OK" if r.status_code == 200 else f"refusé ({r.status_code}) : droits du jeton à revoir")
    except requests.RequestException as e:
        add("Chaîne → Shorts (jeton)", "⚠", f"GitHub injoignable ({type(e).__name__})")


def main() -> int:
    print("Diagnostic Montage LV final — au plus 1 petite demande par clé d'IA\n", flush=True)
    gemini()
    openai_like("Groq", ("GROQ_API_KEYS", "GROQ_API_KEY", "GROQ_API_KEYS_PLUS"), "https://api.groq.com/openai/v1",
                "gpt-oss-120b")
    groq_whisper()
    openai_like("Cerebras", ("CEREBRAS_API_KEYS",), "https://api.cerebras.ai/v1")
    openai_like("OpenRouter", ("OPENROUTER_API_KEYS",), "https://openrouter.ai/api/v1")
    search_keys()
    drive()
    chaine()
    bad = [r for r in rows if r[1] == "❌"]
    ia_ok = any(r[1] == "✅" and (r[0].startswith("Gemini") or r[0].startswith("Groq clé")) for r in rows)
    verdict = ("✅ Tout l'essentiel fonctionne" if ia_ok and not bad else
               "⚠ Le montage marchera, mais regarde les lignes ❌ / ⚠" if ia_ok else
               "❌ Aucune IA ne répond : le montage se fera SANS IA (placement simple, pas de chapitres)")
    md = [f"# {verdict}", "", "| Service | État | Détail |", "|---|---|---|"]
    md += [f"| {a} | {b} | {c} |" for a, b, c in rows]
    md += ["", "Coût de ce diagnostic : au plus 1 petite demande par clé d'IA, 1 unité YouTube par clé. "
           "Les quotas Gemini gratuits repartent à zéro à 9 h (heure de Paris)."]
    out = "\n".join(md)
    print("\n" + out)
    s = os.environ.get("GITHUB_STEP_SUMMARY")
    if s:
        with open(s, "a", encoding="utf-8") as f:
            f.write(out + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
