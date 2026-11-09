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
écrits). Pour CHAQUE phrase qui peut faire une citation forte et compréhensible seule, donne une version courte
(6 à 16 mots), fidèle (même sens, mêmes mots autant que possible, aucun ajout), avec l'orthographe et les noms propres
corrigés. Ignore les phrases vagues, incomplètes ou incompréhensibles.

PHRASES :
{phrases}

Réponds en JSON : {{"quotes": [{{"i": numéro, "q": "citation courte"}}]}}"""


def _num(text: str) -> str | None:
    """Le chiffre clé d'une phrase (avec son unité), ou None. Les années seules (1981, 2017) ne comptent pas."""
    for m in NUM.finditer(text or ""):
        n, unit = m.group(1), (m.group(2) or "").strip()
        digits = re.sub(r"\D", "", n)
        if not digits or (len(digits) == 4 and digits.startswith(("19", "20")) and not unit):
            continue
        if len(digits) == 1 and not unit:
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
        j = ai.json(PROMPT.format(lang=lang, phrases=txt))
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
            if n and ("n", n) not in used:
                used.add(("n", n))
                lab = quotes.get(i) or ""          # jamais la transcription brute (noms mal écrits possibles)
                count[0] += 1
                asset = render("figure", {"text": n, "label": (lab or chapter_at(chapters, i))[:90],
                                         "sublabel": chapter_at(chapters, i) if lab else ""},
                               f"amb{count[0]:03d}")
                return {"kind": "figure", "s0": idx[0], "s1": idx[-1], "label": f"chiffre clé : {n}",
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
