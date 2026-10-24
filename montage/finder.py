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


def load_lot(vpf: Path, which: str = "dernier", max_clips: int = 16, max_articles: int = 12) -> dict | None:
    res = vpf / "results"
    if not res.is_dir():
        log.info("Vid-o-presse-finder : dossier results introuvable")
        return None
    lots = sorted([d for d in res.iterdir() if d.is_dir() and LOT_RE.match(d.name)], key=lambda d: d.name)
    which = (which or "dernier").strip()
    if which.lower() in ("dernier", "oui", "yes", "last", "latest", "auto", ""):
        lot = lots[-1] if lots else None
    else:
        lot = next((d for d in lots if d.name.lower() == which.lower()), None) \
            or next((d for d in reversed(lots) if d.name.lower().startswith(which.lower())), None)
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
    arts.sort(key=lambda r: -float(r.get("autorite") or 0))
    m = LOT_RE.match(lot.name)
    age = None
    try:
        when = dt.datetime(*map(int, m.groups()), tzinfo=dt.timezone.utc)
        age = (dt.datetime.now(dt.timezone.utc) - when).days
    except (TypeError, ValueError):
        pass
    searches = sorted({" | ".join(x for x in (c.get("target", ""), c.get("claim", "")) if x) for c in clips} - {""})
    log.info("Vid-o-presse-finder : lot %s (%s jour(s)) — %d extrait(s), %d article(s) — %s", lot.name, age, len(clips),
             len(arts), "; ".join(searches))
    return {"lot": lot.name, "age_days": age, "clips": clips[:max_clips], "articles": arts[:max_articles],
            "searches": searches}


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
  au moins 4 phrases d'écart entre deux insertions, aucune avant la phrase 2.
- "articles" : au plus 4 articles affichés à côté de l'auteur quand il évoque ce qu'ils racontent :
  [{{"article": numéro, "s0": numéro de phrase, "headline": "titre traduit en « {lang} » si besoin (sinon le titre)"}}].
  Pas deux articles sur la même phrase ni sur la phrase d'une insertion.
Si rien ne correspond, renvoie des listes vides. Réponds en JSON : {{"inserts": [...], "articles": [...]}}."""


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
    j = ai.json(PROMPT.format(lang=lang, searches="; ".join(lot.get("searches") or []) or "même sujet", clips=clips,
                              articles=arts, sentences=text, max_ins=max(1, max_ins)))
    if not isinstance(j, dict):
        return out
    n = len(sents)

    def ii(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None
    afters, used_clips = [], set()
    for x in j.get("inserts") or []:
        c, after = ii(x.get("clip")), ii(x.get("after"))
        if c is None or not 0 <= c < len(lot["clips"]) or c in used_clips or after is None or not 1 <= after < n:
            continue
        if any(abs(after - a) < 4 for a in afters) or len(afters) >= max(1, max_ins):
            continue
        s0 = ii(x.get("s0"))
        s0 = s0 if s0 is not None and 0 <= s0 <= after else after
        afters.append(after)
        used_clips.add(c)
        out["inserts"].append({"clip": c, "after": after, "s0": s0, "quote": str(x.get("quote") or "").strip()[:300]})
    taken = set(afters)
    for x in j.get("articles") or []:
        a, s0 = ii(x.get("article")), ii(x.get("s0"))
        if a is None or not 0 <= a < len(lot["articles"]) or s0 is None or not 0 <= s0 < n or s0 in taken:
            continue
        if a in {y["article"] for y in out["articles"]} or len(out["articles"]) >= 4:
            continue
        taken.add(s0)
        out["articles"].append({"article": a, "s0": s0, "headline": str(x.get("headline") or "").strip()[:200]})
    log.info("Vid-o-presse-finder : %d déclaration(s) et %d article(s) en rapport avec ta vidéo",
             len(out["inserts"]), len(out["articles"]))
    return out
