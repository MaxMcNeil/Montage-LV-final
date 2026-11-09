"""HABILLAGE (vidéo horizontale) : là où aucun média n'est prévu, tu passes dans ton cadre avec, à côté, une carte
sobre tirée de CE QUE TU DIS — jamais inventée :
  - « chiffre clé » quand ta phrase contient un nombre (105 000 €, 2 300 enfants, 45 ans…) ;
  - « citation » de ta phrase forte (orthographe des noms propres corrigée par l'IA, sens inchangé), avec le titre du
    chapitre ou « À RETENIR » en légende.
Une seule demande à l'IA pour toute la vidéo (sans IA : seulement les chiffres clés). Jamais bloquant."""
from __future__ import annotations

import logging
import re

log = logging.getLogger("montage.habillage")

NUM = re.compile(r"(?<![\w])(\d{1,3}(?:[  .]\d{3})+|\d+(?:[.,]\d+)?)\s*(%|pour ?cent|€|euros?|dollars?|\$|millions?|"
                 r"milliards?|mille|ans|années|enfants|personnes|morts|propositions|fois)?", re.I)

PROMPT = """Tu prépares des cartes de citation pour le montage d'une vidéo YouTube d'information (langue « {lang} »).
Voici des phrases dites par l'auteur, transcrites automatiquement (des noms propres ou des mots peuvent être mal
écrits). Il en faut BEAUCOUP (au moins {want}) : pour chaque phrase qui peut faire une citation compréhensible seule,
donne une version courte
(6 à 16 mots), fidèle (même sens, mêmes mots autant que possible, aucun ajout), avec l'orthographe et les noms propres
corrigés. Ignore les phrases vagues, incomplètes ou incompréhensibles.

PHRASES :
{phrases}

Réponds en JSON : {{"quotes": [{{"i": numéro, "q": "citation courte"}}]}}"""


def _num(text: str) -> str | None:
    """Le chiffre clé d'une phrase (avec son unité), ou None. Jamais une année seule (1981, 2017, « en 81 ») ni un
    nombre nu sans unité ; « 4 promesses sur 10 » → « 4 sur 10 »."""
    t = text or ""
    m = re.search(r"(?<![\w])(\d{1,3})\s+(?:[a-zà-ÿ]+\s+){0,2}sur\s+(\d{1,3})(?![\w])", t, re.I)
    if m:
        return f"{m.group(1)} sur {m.group(2)}"
    for m in NUM.finditer(t):
        n, unit = m.group(1), (m.group(2) or "").strip()
        digits = re.sub(r"\D", "", n)
        if not digits or not unit:          # nombre nu (« 81 », « 10 ») : jamais seul sur une carte
            continue
        if len(digits) == 4 and digits.startswith(("19", "20")) and unit.lower() in ("ans", "années"):
            continue
        return f"{n} {unit}".strip()
    return None


def clean_quotes(ai, sents: list, lang: str) -> dict:
    """{indice de phrase: citation courte corrigée} — une seule demande à l'IA ; {} si IA indisponible."""
    if not ai or not getattr(ai, "ok", False):
        return {}
    cand = [(i, s["text"]) for i, s in enumerate(sents) if 6 <= len(str(s.get("text", "")).split()) <= 40]
    if not cand:
        return {}
    txt = "\n".join(f"[{i}] {t[:300]}" for i, t in cand[:260])
    try:
        speech = max(60.0, sents[-1]["t1"] - sents[0]["t0"])
        j = ai.json(PROMPT.format(lang=lang, phrases=txt, want=min(len(cand), max(12, int(speech / 14)))))
    except Exception as e:  # noqa: BLE001
        log.warning("habillage : citations indisponibles (%s) → chiffres clés seulement", e)
        return {}
    out = {}
    for x in ((j or {}).get("quotes") or []) if isinstance(j, dict) else []:
        if not isinstance(x, dict):
            continue
        try:
            i = int(x.get("i"))
        except (TypeError, ValueError):
            continue
        qt = " ".join(str(x.get("q") or "").split())
        if 0 <= i < len(sents) and 3 <= len(qt.split()) <= 22:
            out[i] = qt
    return out


def chapter_at(chapters: list, i: int) -> str:
    t = ""
    for c in sorted(chapters or [], key=lambda c: c.get("s", 0)):
        if c.get("s", 0) <= i:
            t = str(c.get("title") or "")
    return t


def make_ambient(sents: list, quotes: dict, chapters: list, render, lang: str):
    """Fabrique la fonction appelée par le planning : ambient([indices de phrases]) → visuel {kind, asset…} ou None.
    render(kind, data, name) → asset du panneau. Chaque citation / chiffre n'est utilisé qu'une fois."""
    used: set = set()
    count = [0]
    retenir = {"fr": "À RETENIR", "ar": "للتذكّر", "it": "DA RICORDARE", "en": "KEY POINT"}.get(lang, "À RETENIR")

    def ambient(idx: list):
        for i in idx:                       # 1) chiffre clé prononcé
            n = _num(sents[i]["text"])
            if n and ("n", n) not in used and quotes.get(i):   # jamais un chiffre sans sa phrase (contexte)
                used.add(("n", n))
                lab = quotes[i]                    # phrase corrigée (jamais la transcription brute)
                count[0] += 1
                asset = render("figure", {"text": n, "label": lab[:90], "sublabel": chapter_at(chapters, i)},
                               f"amb{count[0]:03d}")
                return {"kind": "figure", "s0": idx[0], "s1": idx[-1], "label": n,
                        "source": "ta phrase (habillage)", "asset": asset, "ambient": True} if asset else None
        for i in idx:                       # 2) ta phrase forte, corrigée
            qt = quotes.get(i)
            if qt and ("q", i) not in used:
                used.add(("q", i))
                count[0] += 1
                lab = retenir if count[0] % 2 else (chapter_at(chapters, i) or retenir)
                asset = render("quote", {"text": qt, "label": lab},
                               f"amb{count[0]:03d}")
                return {"kind": "quote", "s0": idx[0], "s1": idx[-1], "label": qt[:80],
                        "source": "ta phrase (habillage)", "asset": asset, "ambient": True} if asset else None
        return None

    return ambient
