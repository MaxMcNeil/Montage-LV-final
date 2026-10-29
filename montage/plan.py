"""Plan éditorial : l'IA lit ta transcription (phrase par phrase, avec l'heure) et décide QUOI montrer, OÙ et QUAND.

Chaque élément visuel est rattaché à des phrases précises et à un mot déclencheur (« Macron », « 54 000 »…) :
il apparaît à l'instant où tu le prononces, jamais parachuté. Sans IA disponible : plan minimal (tes pièces jointes
réparties sur la vidéo), le montage se fait quand même."""
from __future__ import annotations

import logging
import re

from .util import tc

log = logging.getLogger("montage.plan")

KINDS = ("person", "place", "thing", "event", "article", "figure", "quote", "attachment")

PROMPT = """Tu es le monteur vidéo d'une chaîne d'actualité et d'analyse dont le public a 40 ans et plus.
Tu prépares le montage d'une vidéo où l'auteur parle face caméra. Ton but : une rétention d'audience maximale,
avec un montage élégant, sérieux et lisible — jamais racoleur, jamais d'emoji.

LANGUE DE LA VIDÉO : {lang}. Tous les textes que tu écris (hook, titres, légendes, chiffres, citations) sont dans
cette langue{lang_note}, courts, justes, adaptés au sujet et au contexte. N'invente aucun fait.

TRANSCRIPTION (numéro de phrase, heure, texte) :
{sentences}

PIÈCES JOINTES DE L'AUTEUR (à placer au bon moment) :
{attachments}

CONSIGNES DE L'AUTEUR : {notes}

Décide :
1. "hook" : une phrase d'accroche de 4 à 9 mots affichée pendant les 3 premières secondes, fidèle au propos, qui
   donne envie de rester (question ou enjeu), pas de mensonge.
2. "title" : titre YouTube conseillé (max 70 caractères). "description" : 2 phrases pour la description YouTube.
3. "chapters" : {chapters_rule} — [{{"s": numéro de la 1re phrase, "title": "2 à 5 mots"}}]. La 1re commence à la phrase 0.
4. "visuals" : ce qui apparaît À CÔTÉ de l'auteur pendant qu'il parle. UNIQUEMENT quand ce qui est dit l'appelle
   précisément (un nom prononcé, un lieu, une institution, un chiffre, un article de presse évoqué).
   Jusqu'à un visuel toutes les {every} secondes de parole — mais UNIQUEMENT en totale concordance avec la phrase
   (mieux vaut moins de visuels qu'un visuel approximatif) —, jamais deux à moins de 6 secondes d'écart, aucun dans les
   3 premières secondes. Chaque visuel :
   {{"kind": "person|place|thing|event|figure|quote|attachment",
     "s0": première phrase concernée, "s1": dernière phrase concernée (s1-s0 <= 2),
     "trigger": "le ou les mots EXACTS de la phrase s0 à l'instant desquels le visuel doit apparaître",
     "query": "pour person/place/thing/event : le titre exact de l'article Wikipédia",
     "wiki_lang": "langue de Wikipédia la plus sûre pour ce titre (fr, en, it, ar...)",
     "label": "légende (2 à 6 mots) : nom de la personne / du lieu / de la chose",
     "sublabel": "précision (2 à 6 mots) : fonction, date, contexte",
     "text": "pour figure : le chiffre ou la date mis en valeur (1 à 5 mots) ; pour quote : l'idée forte de l'auteur reformulée fidèlement en 4 à 10 mots",
     "attachment": "pour attachment : l'identifiant de la pièce jointe (images uniquement)",
     "priority": 1 (indispensable) à 3 (bonus)}}
   - person : seulement une personnalité publique nommée ou désignée sans ambiguïté.
   - place / thing / event : uniquement quelque chose de CONCRET et photographiable (un lieu, un bâtiment, une
     organisation connue avec son logo, un objet, un événement célèbre). JAMAIS un concept, un dispositif, une loi, une
     aide sociale, un sigle administratif (RSA, RQTH…) : pour ceux-là, utilise plutôt "figure" ou "quote", ou rien.
   - figure : un chiffre, un pourcentage, une somme ou une date importante que l'auteur prononce.
   - quote : 1 à 3 maximum dans toute la vidéo, sur les phrases les plus fortes.
   - attachment : place CHAQUE image jointe au moment où l'auteur parle de ce qu'elle montre (sinon ne la place pas).
5. "inserts" : des passages des VIDÉOS jointes, insérés pendant un silence de l'auteur (il disparaît le temps de
   l'extrait). Une même vidéo jointe peut fournir PLUSIEURS passages (jusqu'à {per_video}), chacun placé là où l'auteur parle
   précisément de ce que dit ou montre ce passage ; au moins 3 phrases d'écart entre deux insertions :
   [{{"attachment": "id", "after": numéro de la phrase après laquelle on l'insère (quand l'auteur vient d'en parler ou
   de l'annoncer), "clip_start": seconde de début dans la vidéo jointe, "clip_end": seconde de fin}}]. L'extrait dure
   au plus {max_insert} s, commence et finit sur une phrase complète de la vidéo jointe.
6. "press" : TOUT ce que dit l'auteur dont on peut chercher la trace en vidéo, dans la presse ou sur les réseaux
   (au plus {max_press}, les plus importants d'abord ; moins s'il y en a moins) : déclarations qu'il cite, faits,
   chiffres, décisions, mais AUSSI soupçons, rumeurs, accusations, révélations, thèses dont beaucoup de vidéos ou
   d'articles parlent — même non confirmés : c'est du journalisme citoyen, AUCUN tri sur le fond, aucune censure.
   Le but est de retrouver ceux qui en parlent (pour appuyer ce qu'il dit) et ceux qui le contestent (pour qu'il
   puisse y répondre). Seules les pures opinions personnelles sans objet précis sont exclues. "type" : "personne"
   UNIQUEMENT si on cherche les propres paroles de cette personne ; un soupçon, une rumeur ou une accusation qui
   la VISE = "sujet" (on cherche alors tous ceux qui en parlent) :
   [{{"target": "personne, pays, entité ou sujet", "claim": "ce qui aurait été dit ou fait (quelques mots)",
   "type": "personne|pays|entite|sujet", "after": phrase après laquelle insérer l'extrait vidéo trouvé,
   "s0": première phrase où l'auteur en parle, "langs": "codes de langues des sources probables, ex. fr,en"}}].
   Liste vide si rien ne s'y prête vraiment.
7. "emphasis" : pour les phrases clés, 1 à 3 mots à mettre en couleur dans les sous-titres :
   [{{"s": numéro, "words": ["mot", "mot"]}}] (une vingtaine au maximum).
8. "outro" : une courte phrase de fin (max 8 mots) qui remercie et invite à s'abonner, dans le ton de la chaîne.

Réponds en JSON : {{"hook", "title", "description", "chapters", "visuals", "inserts", "press", "emphasis", "outro"}}."""


def describe_attachments(att: list) -> str:
    if not att:
        return "(aucune)"
    lines = []
    for a in att:
        if a["kind"] == "image":
            lines.append(f'- id "{a["id"]}" — IMAGE « {a["name"]} » : {a.get("description") or "(non décrite)"}')
        else:
            sents = a.get("sentences") or []
            body = " / ".join(f'[{s["t0"]:.0f}-{s["t1"]:.0f}s] {s["text"]}' for s in sents[:60])
            cut = (f' | PASSAGE IMPOSÉ PAR L\'AUTEUR : {a["cut"][0]:.0f}-{a["cut"][1]:.0f} s (garde ces bornes)'
                   if a.get("cut") else "")
            lines.append(f'- id "{a["id"]}" — VIDÉO « {a["name"]} » ({a.get("duration", 0):.0f} s) : '
                         f'{a.get("description") or ""}{cut} | paroles : {body or "(aucune parole)"}')
    return "\n".join(lines)


def _chapters_rule(speech: float) -> str:
    """Chapitres dès 2 min de parole (le 1er est couvert par l'accroche : 3 prévus = 2 bandeaux visibles)."""
    if speech > 240:
        return "3 à 7 chapitres"
    if speech >= 120:
        return "exactement 3 chapitres, bien répartis (le 1er à la phrase 0)"
    return "aucun chapitre (liste vide)"


def ask(ai, lang: str, sents: list, att: list, notes: str, opts: dict) -> dict:
    speech = sents[-1]["t1"] - sents[0]["t0"] if sents else 0
    text = "\n".join(f'[{s["i"]}] ({tc(s["t0"])}) {s["text"]}' for s in sents)
    if len(text) > 120_000:  # vidéo très longue : on abrège les phrases pour rester dans la limite de l'IA
        text = "\n".join(f'[{s["i"]}] ({tc(s["t0"])}) {s["text"][:160]}' for s in sents)
    every = 15 if speech < 600 else 20
    prompt = PROMPT.format(
        lang=lang, lang_note=" (arabe littéraire simple)" if lang == "ar" else "", sentences=text,
        attachments=describe_attachments(att), notes=(notes or "(aucune)")[:2000],
        chapters_rule=_chapters_rule(speech), every=every,
        max_insert=opts.get("duree_max_insert", 25),
        max_press=_max_press(opts, speech), per_video=opts.get("_per_video", 5))
    if not ai or not ai.ok:
        return fallback(sents, att)
    j = ai.json(prompt)
    if not isinstance(j, dict):
        # 2e chance avec une version compacte (phrases abrégées, paroles des vidéos jointes réduites) : passe aussi
        # chez les sources qui refusent les requêtes longues — plutôt qu'un montage sans IA
        log.warning("Plan IA sans réponse → nouvel essai en version compacte")
        short = [dict(x, sentences=(x.get("sentences") or [])[:25]) for x in att]
        prompt = PROMPT.format(
            lang=lang, lang_note=" (arabe littéraire simple)" if lang == "ar" else "",
            sentences="\n".join(f'[{s["i"]}] ({tc(s["t0"])}) {s["text"][:110]}' for s in sents),
            attachments=describe_attachments(short), notes=(notes or "(aucune)")[:800],
            chapters_rule=_chapters_rule(speech), every=every,
            max_insert=opts.get("duree_max_insert", 25),
            max_press=_max_press(opts, speech), per_video=opts.get("_per_video", 5))
        j = ai.json(prompt)
    if not isinstance(j, dict):
        log.warning("Plan IA indisponible → plan minimal")
        return fallback(sents, att)
    return clean(j, sents, att)


def _max_press(opts: dict, speech_s: float = 0.0) -> int:
    """« auto » (défaut) : selon la durée de parole — ~1 affirmation par minute, au moins 4, au plus 30 ; l'IA n'en
    garde que les vraies affirmations vérifiables (moins si la vidéo en contient moins)."""
    if opts.get("recherche_presse") == "non":
        return 0
    v = str(opts.get("affirmations") or "auto").strip().lower()
    if v.isdigit():
        return max(0, min(30, int(v)))
    return int(max(4, min(30, round(speech_s / 60))))


def _int(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def clean(j: dict, sents: list, att: list) -> dict:
    n = len(sents)
    ids = {a["id"]: a for a in att}
    ok = lambda i: i is not None and 0 <= i < n  # noqa: E731
    out = {"hook": str(j.get("hook") or "").strip()[:90], "title": str(j.get("title") or "").strip()[:100],
           "description": str(j.get("description") or "").strip()[:600], "outro": str(j.get("outro") or "").strip()[:80],
           "chapters": [], "visuals": [], "inserts": [], "press": [], "emphasis": {}}
    seen = set()
    for c in j.get("chapters") or []:
        s = _int(c.get("s"))
        if ok(s) and s not in seen and str(c.get("title") or "").strip():
            seen.add(s)
            out["chapters"].append({"s": s, "title": str(c["title"]).strip()[:48]})
    out["chapters"].sort(key=lambda c: c["s"])
    for v in j.get("visuals") or []:
        k = str(v.get("kind") or "").lower()
        s0, s1 = _int(v.get("s0")), _int(v.get("s1"), _int(v.get("s0")))
        if k not in KINDS or not ok(s0):
            continue
        s1 = s1 if ok(s1) and s1 >= s0 else s0
        d = {"kind": k, "s0": s0, "s1": min(s1, s0 + 2), "trigger": str(v.get("trigger") or "").strip()[:60],
             "query": str(v.get("query") or "").strip()[:120], "wiki_lang": str(v.get("wiki_lang") or "").strip()[:3],
             "label": str(v.get("label") or "").strip()[:60], "sublabel": str(v.get("sublabel") or "").strip()[:70],
             "text": str(v.get("text") or "").strip()[:90], "attachment": str(v.get("attachment") or "").strip(),
             "priority": _int(v.get("priority"), 2) or 2}
        if k == "attachment" and (d["attachment"] not in ids or ids[d["attachment"]]["kind"] != "image"):
            continue
        if k in ("figure", "quote") and not d["text"]:
            continue
        if k in ("person", "place", "thing", "event") and not d["query"]:
            continue
        out["visuals"].append(d)
    for i in j.get("inserts") or []:
        a, after = str(i.get("attachment") or ""), _int(i.get("after"))
        if a in ids and ids[a]["kind"] == "video" and ok(after):
            out["inserts"].append({"attachment": a, "after": after, "clip_start": float(i.get("clip_start") or 0),
                                   "clip_end": float(i.get("clip_end") or 0)})
    for p in j.get("press") or []:
        after = _int(p.get("after"))
        if str(p.get("target") or "").strip() and ok(after):
            out["press"].append({"target": str(p["target"]).strip()[:80], "claim": str(p.get("claim") or "").strip()[:120],
                                 "type": str(p.get("type") or "auto").strip().lower(), "after": after,
                                 "s0": _int(p.get("s0"), after) if ok(_int(p.get("s0"), after)) else after,
                                 "langs": str(p.get("langs") or "").strip()[:20]})
    for e in j.get("emphasis") or []:
        s = _int(e.get("s"))
        if ok(s):
            out["emphasis"][s] = [str(w).strip() for w in (e.get("words") or []) if str(w).strip()][:3]
    # pièces jointes oubliées par l'IA : elles sont quand même placées (au mieux)
    _place_forgotten(out, sents, att)
    return out


def fallback(sents: list, att: list) -> dict:
    out = {"hook": "", "title": "", "description": "", "outro": "", "chapters": [], "visuals": [], "inserts": [],
           "press": [], "emphasis": {}, "fallback": True}
    _place_forgotten(out, sents, att)
    return out


def _place_forgotten(out: dict, sents: list, att: list) -> None:
    """Chaque pièce jointe est placée : à défaut d'indication de l'IA, là où un mot de son nom ou de sa description est
    prononcé, sinon répartie régulièrement."""
    from .util import norm
    if not sents:
        return
    used_img = {v["attachment"] for v in out["visuals"] if v["kind"] == "attachment"}
    used_vid = {i["attachment"] for i in out["inserts"]}
    todo = [a for a in att if (a["kind"] == "image" and a["id"] not in used_img) or (a["kind"] == "video" and a["id"] not in used_vid)]
    if not todo:
        return
    stop = set("le la les de des du un une et en au aux pour par sur dans avec img image photo video vid jpg png mp4 the of and "
               "il lo gli di da con per".split())
    for n, a in enumerate(todo):
        words = [w for w in norm(re.sub(r"\.[a-z0-9]+$", "", a["name"]) + " " + (a.get("description") or "")).split()
                 if len(w) > 3 and w not in stop and not w.isdigit()]
        best, score = None, 0
        for s in sents:
            ns = set(norm(s["text"]).split())
            sc = sum(1 for w in words if w in ns)
            if sc > score:
                best, score = s["i"], sc
        if best is None:  # réparti sur la vidéo
            best = min(len(sents) - 1, int(len(sents) * (n + 1) / (len(todo) + 1)))
        if a["kind"] == "image":
            out["visuals"].append({"kind": "attachment", "s0": best, "s1": min(best + 1, len(sents) - 1), "trigger": "",
                                   "query": "", "wiki_lang": "", "label": a.get("label") or "", "sublabel": "",
                                   "text": "", "attachment": a["id"], "priority": 1, "auto": True})
        else:
            out["inserts"].append({"attachment": a["id"], "after": best, "clip_start": 0.0, "clip_end": 0.0, "auto": True})
