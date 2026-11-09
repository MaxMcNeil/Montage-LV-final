#!/usr/bin/env python3
"""Ton script de live → liste de médias pour « Préparer les médias » (même format que medias/*.txt).

  python3 scripts/liste_depuis_script.py <script.txt|.md|.docx|.pdf> <liste_sortie.txt>

UNE seule demande à l'IA (Gemini, sinon Groq) : elle lit ton script et propose, par sujet, des vidéos (recherche
YouTube précise), des photos libres (titre exact de l'article Wikipédia) et des articles. Les adresses d'articles ne
sont JAMAIS inventées : seulement celles écrites dans ton script ; sinon l'article est cherché sur Bing Actualités
(gratuit, sans clé) et le premier résultat est gardé.
Code 0 : liste écrite. Code 1 : impossible (script illisible, IA indisponible) → le workflow garde la liste du dépôt."""
from __future__ import annotations

import html
import os
import re
import subprocess
import sys
import urllib.parse

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

UA = "Mozilla/5.0 (X11; Linux x86_64) JournalDuNON-medias/1.0"
MAX_MEDIAS = 30

PROMPT = """Tu prépares les médias du montage d'une vidéo YouTube d'information (chaîne de journalisme citoyen, public
de 40 ans et plus). Voici le SCRIPT que l'auteur va dire (langue « {lang} »). Repère ses SUJETS dans l'ordre, et pour
chacun les médias qui illustrent PRÉCISÉMENT ce qui est dit : la personne citée, l'événement, la déclaration, le chiffre.

SCRIPT :
{script}

ADRESSES PRÉSENTES DANS LE SCRIPT (les seules utilisables telles quelles) :
{urls}

Règles :
- au plus {maxm} médias en tout, les plus parlants d'abord ; rien de décoratif ou de vague ;
- "video" : une recherche YouTube TRÈS précise pour retrouver l'archive ou la déclaration exacte (qui, quoi, date,
  média ou chaîne si connu : INA, France 24, BFMTV, Al Jazeera…) + durée max en secondes (300 à 900) ;
- "photo" : seulement une personne connue, un lieu ou un bâtiment célèbre : "wiki" = "langue:Titre_exact_de_l_article"
  (ex : "fr:Emmanuel_Macron") ;
- "article" : "url" UNIQUEMENT si elle figure dans la liste d'adresses ci-dessus ; sinon "recherche" = titre probable
  ou mots-clés précis de l'article (jamais d'adresse inventée) ;
- "nom" : court, minuscules, chiffres et _ seulement, préfixé v / p / a + numéro (ex : v101_macron_orleans_2017).
Réponds en JSON : {{"sujets": [{{"n": 1, "titre": "…", "medias": [{{"type": "video", "nom": "…", "recherche": "…",
"duree": 600}}, {{"type": "photo", "nom": "…", "wiki": "fr:…"}}, {{"type": "article", "nom": "…", "url": "…"}},
{{"type": "article", "nom": "…", "recherche": "…"}}]}}]}}"""


def read_script(p: str) -> str:
    low = p.lower()
    try:
        if low.endswith(".docx"):
            import zipfile
            with zipfile.ZipFile(p) as z:
                xml = z.read("word/document.xml").decode("utf-8", "replace")
            xml = re.sub(r"</w:p>", "\n", xml)
            return html.unescape(re.sub(r"<[^>]+>", "", xml))
        if low.endswith(".pdf"):
            return subprocess.run(["pdftotext", "-layout", p, "-"], capture_output=True, text=True, timeout=120).stdout
        with open(p, encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception as e:  # noqa: BLE001
        print(f"::warning::script illisible ({type(e).__name__}: {e})")
        return ""


def guess_lang(t: str) -> str:
    if re.search(r"[؀-ۿ]", t):
        return "ar"
    low = f" {t.lower()} "
    score = {"fr": sum(low.count(w) for w in (" le ", " la ", " les ", " est ", " des ", " et ")),
             "it": sum(low.count(w) for w in (" il ", " che ", " della ", " sono ", " gli ")),
             "en": sum(low.count(w) for w in (" the ", " and ", " is ", " of ", " that "))}
    return max(score, key=score.get)


def clean_name(n: str, prefix: str, k: int) -> str:
    n = re.sub(r"[^a-z0-9_]+", "_", (n or "").lower()).strip("_")[:50]
    if not n or n[0] not in "vpa":
        n = f"{prefix}{k:02d}_{n}".strip("_")
    return n


def bing_article(query: str, lang: str) -> str:
    """1er article de Bing Actualités (RSS public, sans clé) ; '' si rien."""
    mkt = {"fr": "fr-FR", "it": "it-IT", "ar": "ar-XA", "en": "en-US"}.get(lang, "fr-FR")
    try:
        r = requests.get("https://www.bing.com/news/search", params={"q": query, "format": "rss", "mkt": mkt},
                         headers={"User-Agent": UA}, timeout=25)
        for link in re.findall(r"<link>(.*?)</link>", r.text)[1:6]:
            link = html.unescape(link)
            q = urllib.parse.parse_qs(urllib.parse.urlparse(link).query)
            u = (q.get("url") or [link])[0]
            if u.startswith("http") and "bing.com" not in urllib.parse.urlparse(u).netloc:
                return u
    except requests.RequestException:
        pass
    return ""


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 1
    src, out = sys.argv[1], sys.argv[2]
    txt = read_script(src).strip()
    if len(txt) < 80:
        print("::warning::script vide ou trop court : liste non écrite")
        return 1
    lang = guess_lang(txt)
    urls = list(dict.fromkeys(re.findall(r"https?://[^\s<>\"')\]]+", txt)))
    from montage.ai import AI
    ai = AI()
    if not ai.ok:
        print("::warning::aucune IA disponible (GEMINI_API_KEYS / GROQ_API_KEYS) : liste non écrite")
        return 1
    j = ai.json(PROMPT.format(lang=lang, script=txt[:24000], urls="\n".join(urls[:60]) or "(aucune)", maxm=MAX_MEDIAS))
    sujets = (j or {}).get("sujets") if isinstance(j, dict) else None
    if not isinstance(sujets, list) or not sujets:
        print("::warning::réponse de l'IA inexploitable : liste non écrite")
        return 1
    lines = [f"# Liste écrite automatiquement depuis « {os.path.basename(src)} » ({lang}) — 1 demande IA",
             "# sujet | type | nom | url ou recherche | durée max (s, vidéos)"]
    n_tot, seen, kept = 0, set(), {"video": 0, "photo": 0, "article": 0}
    for si, s in enumerate(sujets, 1):
        if not isinstance(s, dict):
            continue
        try:
            num = int(s.get("n") or si)
        except (TypeError, ValueError):
            num = si
        lines.append(f"# Sujet {num} : {str(s.get('titre') or '')[:90]}")
        for k, m in enumerate(s.get("medias") or [], 1):
            if not isinstance(m, dict) or n_tot >= MAX_MEDIAS:
                continue
            t = str(m.get("type") or "").strip().lower()
            if t not in kept:
                continue
            nom = clean_name(str(m.get("nom") or ""), t[0], num * 100 + k)
            if nom in seen:
                nom = f"{nom}_{k}"
            if t == "video":
                q = " ".join(str(m.get("recherche") or "").replace("|", " ").split())[:200]
                if not q:
                    continue
                try:
                    d = int(m.get("duree") or 600)
                except (TypeError, ValueError):
                    d = 600
                lines.append(f"{num} | video | {nom} | {q} | {max(120, min(1200, d))}")
            elif t == "photo":
                w = str(m.get("wiki") or "").strip().replace(" ", "_")
                if not re.match(r"^[a-z]{2}:[^|]{2,120}$", w):
                    continue
                lines.append(f"{num} | photo | {nom} | {w}")
            else:
                u = str(m.get("url") or "").strip()
                if u and u not in urls:      # adresse absente de ton script : jamais utilisée (risque d'invention)
                    u = ""
                if not u and str(m.get("recherche") or "").strip():
                    u = bing_article(str(m["recherche"]).strip()[:200], lang)
                if not u:
                    continue
                lines.append(f"{num} | article | {nom} | {u}")
            seen.add(nom)
            kept[t] += 1
            n_tot += 1
    if not n_tot:
        print("::warning::aucun média proposé : liste non écrite")
        return 1
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Liste écrite : {n_tot} média(s) — {kept['video']} vidéo(s), {kept['photo']} photo(s), "
          f"{kept['article']} article(s) — {ai.usage_line()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
