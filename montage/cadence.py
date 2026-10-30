"""Rythme (rétention d'audience) — option « rythme », activée par défaut.

ÉLÉMENT = extrait vidéo inséré, article ou photo à côté de toi : les trois comptent pareil.
Règle : 5 premières minutes → au moins un élément toutes les 60 s ; ensuite → un élément environ toutes les 2 min
(jamais plus de 2 min 15 sans rien) et pas d'élément AUTOMATIQUE à moins de 1 min 30 du précédent (rythme régulier).
Passent toujours, même rapprochés : tes « écoutez ça » et tes pièces jointes (vidéos et photos).
Pour remplir un trou, dans cet ordre : 1) un passage de tes vidéos jointes ; 2) un article (Finder / presse / Telegram
/ Reddit) pas encore utilisé ; 3) une photo (tes photos jointes, sinon photo libre Wikimedia de la personne ou du lieu
dont tu parles). Toujours COHÉRENT avec ce que tu dis là, confirmé par une 2e lecture indépendante.
Détail de l'étape 1 (vidéos) : Là où ta vidéo n'en a pas assez (plan de l'IA, « écoutez ça », Vid-o-presse-finder…), un passage est
ajouté — mais seulement s'il est COHÉRENT avec ce que tu dis à ce moment-là :
  - point d'insertion = un vrai silence confirmé par le son, à la fin d'une de tes phrases (jamais pendant que tu parles) ;
  - passage choisi par l'IA d'après ce que tu dis juste avant et juste après, puis 2e lecture indépendante qui vérifie ;
  - phrases complètes, 6 à 15 s, jamais un passage déjà utilisé (ouverture choc comprise), au moins 25 s entre deux
    extraits ;
  - aucun passage cohérent → on n'en met pas (mieux vaut un trou qu'un extrait hors sujet) : PLAN.md dit où et pourquoi.

Aussi : légende propre à CHAQUE passage (ce que montre / dit ce passage), au lieu d'une légende unique par vidéo."""
from __future__ import annotations

import logging
from pathlib import Path

from .util import tc

log = logging.getLogger("montage.cadence")

FIRST = 300.0       # les 5 premières minutes…
GAP1 = 60.0         # … un extrait au moins toutes les 60 s
GAP2 = 120.0        # ensuite toutes les 2 min (cible)…
GAP2_MAX = 135.0    # … jamais plus de 2 min 15 sans rien
AUTO_SEP = 90.0     # après 5 min : pas d'élément automatique à moins de 1 min 30 du précédent
QC_HOLE = 150.0     # contrôle qualité : ⚠ si un trou de plus de 2 min 30 reste après 5 min
MIN_SEP = 25.0      # jamais deux extraits à moins de 25 s
DMIN, DMAX = 6, 15  # durée d'un extrait de rythme
MAX_ROUNDS = 6
MAX_SLOTS = 16      # créneaux traités par question à l'IA

FILL = """Tu es le monteur d'une vidéo face caméra (langue « {lang} ») pour un public de 40 ans et plus. Pour garder
l'attention, on insère régulièrement un court passage d'une des vidéos jointes, pendant un silence de l'auteur
(il disparaît le temps du passage, puis reprend). Pour chaque CRÉNEAU ci-dessous, choisis le passage qui illustre le
mieux CE QUE L'AUTEUR DIT À CE MOMENT-LÀ (même sujet, même fait, même personne, même chiffre), et le point d'insertion.

CRÉNEAUX (ce que dit l'auteur dans la fenêtre, et les points d'insertion possibles = fins de phrases suivies d'un vrai
silence) :
{slots}

VIDÉOS JOINTES (transcription horodatée, en secondes) :
{videos}

PASSAGES DÉJÀ UTILISÉS (interdits, ne les reprends pas même en partie) : {used}

Règles :
- passage de {dmin} à {dmax} secondes, qui commence au début d'une phrase et finit à la fin d'une phrase (bornes
  [début-fin] ci-dessus), compréhensible seul ;
- il doit être en rapport DIRECT avec ce que dit l'auteur juste avant le point d'insertion, et s'enchaîner avec ce qu'il
  dit juste après ;
- deux créneaux n'utilisent jamais le même passage ;
- si AUCUN passage n'est vraiment cohérent pour un créneau, réponds "video": null pour ce créneau (ne force jamais).
Réponds en JSON : {{"fills": [{{"slot": numéro, "after": numéro du point d'insertion choisi, "video": "id" ou null,
"start": secondes, "end": secondes, "why": "en une phrase : le lien avec ce que dit l'auteur"}}]}}"""

VERIFY = """Vérification indépendante d'un montage (langue « {lang} »). Pour chaque cas, on insère un passage d'une
vidéo jointe pendant un silence de l'auteur. Le passage est-il en rapport DIRECT avec ce que l'auteur dit juste avant
(même sujet / fait / personne), et s'enchaîne-t-il naturellement avec ce qu'il dit après ? Sois exigeant : un passage
seulement « dans le thème général » ne suffit pas.

{cases}

Réponds en JSON : {{"checks": [{{"n": numéro, "ok": true/false, "score": 0 à 10, "reason": "une phrase"}}]}}"""

LABEL = """Image tirée d'un passage de la vidéo « {name} ». Ce qui est dit dans ce passage : « {text} ».
Donne une légende de 2 à 6 mots en langue « {lang} » qui décrit CE PASSAGE précisément (qui parle / ce qu'on voit /
de quoi il s'agit), sans rien inventer. Réponds en JSON : {{"label": "…"}}"""


def rule_count(speech_s: float) -> int:
    """Nombre d'éléments que demande la règle de rythme pour cette durée : un par minute sur les 5 premières
    minutes, puis un toutes les 2 minutes. Sert à dimensionner les limites (jamais un chiffre fixe)."""
    d = max(0.0, float(speech_s or 0))
    return max(1, int(min(d, FIRST) // GAP1) + int(max(0.0, d - FIRST) // GAP2))


def overlap(a: tuple, b: tuple) -> float:
    return max(0.0, min(a[1], b[1]) - max(a[0], b[0]))


def clashes(clip: tuple, used: list) -> bool:
    """Passage qui reprend (même en partie notable) un passage déjà utilisé de la même vidéo."""
    return any(overlap(clip, u) > 0.5 for u in used)   # au plus une demi-seconde en commun (fondu)


def passage_label(ai, x: dict, a: float, b: float, lang: str, work: Path, fallback: str) -> str:
    """Légende propre au passage [a, b] de la vidéo jointe x (image du milieu du passage + ce qui y est dit)."""
    if not ai or not ai.ok:
        return fallback
    from .assets import _jpeg_bytes
    from .keywords import _sents_in
    from .panels import open_image
    from .util import run
    try:
        fr = work / f"{x['id']}_{int(a * 10)}_{int(b * 10)}_label.jpg"
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{(a + b) / 2:.2f}", "-i", x["path"], "-frames:v", "1", fr])
        img = open_image(fr)
        text = (_sents_in(x, a, b) or "(pas de paroles)")[:600]
        j = ai.json(LABEL.format(name=x["name"], text=text, lang=lang),
                    image=("image/jpeg", _jpeg_bytes(img)) if img is not None else None,
                    media_key=f"label|{x['name']}|{a:.1f}|{b:.1f}")
        lab = str((j or {}).get("label") or "").strip() if isinstance(j, dict) else ""
        return lab[:60] or fallback
    except Exception as e:  # noqa: BLE001 - une légende ratée ne bloque jamais le montage
        log.info("légende du passage %s %.0f-%.0f s : %s", x["name"], a, b, e)
        return fallback


def insert_time(ins: dict, words, sents, sil) -> float | None:
    """Instant (vidéo source) où l'extrait sera réellement placé (même calcul que la ligne de temps)."""
    from .timeline import find_pause
    if ins.get("forced_t") is not None:
        return float(ins["forced_t"])
    try:
        return find_pause(words, sents, sil or [], int(ins["after"]))
    except Exception:  # noqa: BLE001
        return None


def fill(ai, words: list, sents: list, att: list, inserts: list, used: dict, sil: list, lang: str, orient: str,
         work: Path, opener: bool, prepare, others: list | None = None) -> dict:
    """Ajoute des extraits de rythme dans `inserts`. `used` : {id vidéo: [(a, b), …]} passages déjà pris (mis à jour).
    `prepare(x, a, b, name)` prépare l'extrait (asset) ou renvoie None."""
    from .keywords import _ctx, _sents_in, _videos_text
    from .timeline import find_pause
    info = {"added": [], "holes": [], "cards": [], "thinned": [],
            "rule": "5 premières minutes : un élément (extrait, article ou photo) au moins toutes les 60 s ; ensuite un "
                    "environ toutes les 2 min (2 min 15 max), pas d'ajout automatique à moins de 1 min 30 du précédent"}
    vids = [x for x in att if x["kind"] == "video" and x.get("duration", 0) >= 3]
    if not sents or not words:
        return info
    if not vids:
        info["why"] = "aucune vidéo jointe"
        return info
    if not ai or not ai.ok:
        info["why"] = "IA indisponible (la cohérence ne peut pas être garantie : rien ajouté)"
        return info
    by = {x["id"]: x for x in vids}
    t_start, t_end = sents[0]["t0"], sents[-1]["t1"]
    # points d'insertion possibles : fin de phrase + vrai silence (calcul identique à la ligne de temps)
    cand = []
    for s in sents[:-1]:
        t = find_pause(words, sents, sil or [], s["i"], look=0)
        if t is not None:
            cand.append({"i": s["i"], "t": t})
    lim = lambda t: GAP1 if t - t_start < FIRST else GAP2  # noqa: E731
    sep = lambda t: MIN_SEP if t - t_start < FIRST else AUTO_SEP  # noqa: E731
    others = sorted(others or [])
    failed: list[tuple] = []
    for rnd in range(MAX_ROUNDS):
        pts = sorted([t for t in (insert_time(i, words, sents, sil) for i in inserts) if t is not None] + others)
        pts = [t_start] + pts if opener else pts
        # créneaux : premier endroit de chaque trou où il faudrait un extrait
        slots = []
        prev = t_start if not pts or pts[0] > t_start else pts[0]
        for t in pts + [t_end]:
            cur = prev
            while t - cur > lim(cur) + (5.0 if cur - t_start < FIRST else GAP2_MAX - GAP2):
                lo, hi = cur + sep(cur), cur + lim(cur)   # trou trop long : premier créneau encore possible
                if any(abs(lo - f0) < 1 and abs(hi - f1) < 1 for f0, f1 in failed):
                    cur = hi                             # créneau déjà tenté sans succès : on regarde plus loin
                    continue
                c = [p for p in cand if lo <= p["t"] <= hi and t - p["t"] >= MIN_SEP - 5]
                if c:
                    slots.append({"lo": lo, "hi": hi, "cand": c})
                    cur = lo + 0.7 * (hi - lo)           # créneau suivant du même trou (vérifié au tour suivant)
                    continue
                failed.append((lo, hi))
                info["holes"].append({"t0": cur, "t1": hi, "why": "aucun vrai silence en fin de phrase à cet endroit"})
                cur = hi
            prev = t
        if not slots:
            break
        slots = slots[:MAX_SLOTS]
        txt = []
        for n, sl in enumerate(slots):
            ss = [s for s in sents if s["t1"] >= sl["lo"] - 25 and s["t0"] <= sl["hi"] + 20]
            body = " ".join(s["text"] for s in ss)[:1500]
            pts_txt = " ; ".join(f'[{p["i"]}] à {tc(p["t"])} après « …{sents[p["i"]]["text"][-70:]} »' for p in sl["cand"][:12])
            txt.append(f"Créneau {n} ({tc(sl['lo'])} → {tc(sl['hi'])}) — l'auteur dit : « {body} »\n"
                       f"   points d'insertion possibles : {pts_txt}")
        used_txt = "; ".join(f'{by[k]["name"]} {a:.0f}-{b:.0f} s' for k, lst in used.items() if k in by
                             for a, b in lst) or "aucun"
        j = ai.json(FILL.format(lang=lang, slots="\n".join(txt), videos=_videos_text(vids), used=used_txt,
                                dmin=DMIN, dmax=DMAX))
        picks = (j or {}).get("fills") if isinstance(j, dict) else None
        if not isinstance(picks, list):
            log.warning("Rythme : réponse IA inexploitable (tour %d)", rnd + 1)
            for sl in slots:
                failed.append((sl["lo"], sl["hi"]))
                info["holes"].append({"t0": sl["lo"] - MIN_SEP, "t1": sl["hi"], "why": "IA indisponible"})
            continue
        from .keywords import _clamp
        chosen = []
        taken_now: list[tuple] = []
        for p in picks:
            if not isinstance(p, dict):   # réponse IA mal formée : élément ignoré
                continue
            try:
                n = int(p.get("slot"))
                sl = slots[n]
            except (TypeError, ValueError, IndexError):
                continue
            if any(c["slot"] == n for c in chosen):
                continue
            x = by.get(str(p.get("video") or ""))
            if x is None:
                continue
            try:
                after = int(p.get("after"))
                a, b = float(p.get("start")), float(p.get("end"))
            except (TypeError, ValueError):
                continue
            cp = next((c for c in sl["cand"] if c["i"] == after), None)
            if cp is None:
                continue
            a, b = _clamp(x, a, b, DMAX)
            prise = used.get(x["id"], []) + [(u0, u1) for k, u0, u1 in taken_now if k == x["id"]]
            if clashes((a, b), prise) and not x.get("cut"):
                # passage déjà utilisé : on prend la suite libre de la même vidéo (la 2e lecture vérifie la cohérence)
                nxt = max(u1 for u0, u1 in prise if min(u1, b) - max(u0, a) > 0)
                if nxt < float(x.get("duration") or 0) - DMIN:
                    a, b = _clamp(x, nxt + 0.2, nxt + 0.2 + max(DMIN + 2.0, b - a), DMAX)
            if b - a < 3.0 or clashes((a, b), prise):
                continue
            chosen.append({"slot": n, "after": after, "t": cp["t"], "x": x, "a": a, "b": b,
                           "why": str(p.get("why") or "")[:200]})
            taken_now.append((x["id"], a, b))
        # 2e lecture indépendante
        if chosen:
            cases = []
            for k, c in enumerate(chosen):
                w1 = sents[c["after"]]["w1"]
                bef, aft = _ctx(words, sents[c["after"]]["w0"], w1, 70, 35)
                cases.append(f"[{k}] AVANT : … {bef} {sents[c['after']]['text']}\n    PASSAGE INSÉRÉ ({c['x']['name']} "
                             f"{c['a']:.0f}-{c['b']:.0f} s) : « {_sents_in(c['x'], c['a'], c['b'])[:700]} »\n    APRÈS : {aft} …")
            chk = ai.json(VERIFY.format(lang=lang, cases="\n\n".join(cases)))
            for ck in ((chk or {}).get("checks") or []) if isinstance(chk, dict) else []:
                if not isinstance(ck, dict):   # réponse IA mal formée : élément ignoré
                    continue
                try:
                    k = int(ck.get("n"))
                except (TypeError, ValueError):
                    continue
                if 0 <= k < len(chosen):
                    chosen[k]["check"] = {"ok": bool(ck.get("ok")), "score": ck.get("score"),
                                          "reason": str(ck.get("reason") or "")[:200]}
        done, retry = set(), set()
        placed = sorted(t for t in (insert_time(i, words, sents, sil) for i in inserts) if t is not None)
        for c in sorted(chosen, key=lambda c: c["t"]):
            if any(abs(c["t"] - t) < MIN_SEP - 5 for t in placed):
                retry.add(c["slot"])          # trop près d'un autre extrait : recalculé au tour suivant
                continue
            ck = c.get("check")
            if ck is not None and not ck["ok"]:
                info["holes"].append({"t0": slots[c["slot"]]["lo"] - MIN_SEP, "t1": slots[c["slot"]]["hi"],
                                      "why": f"passage proposé refusé à la vérification ({ck['reason']})"})
                continue
            asset = prepare(c["x"], c["a"], c["b"], f"insert_rythme{rnd}_{c['slot']}")
            if not asset:
                continue
            asset["source"] = (f"RYTHME — pièce jointe « {c['x']['name']} » ({tc(c['a'])} → {tc(c['b'])}) — {c['why']}"
                               + (f" — vérifié ✅ ({ck.get('score')}/10)" if ck else ""))
            inserts.append({"after": c["after"], "asset": asset, "attachment": c["x"]["id"], "clip": (c["a"], c["b"]),
                            "forced_t": c["t"], "rythme": True})
            used.setdefault(c["x"]["id"], []).append((c["a"], c["b"]))
            info["added"].append({"t": c["t"], "video": c["x"]["name"], "a": c["a"], "b": c["b"], "why": c["why"],
                                  "check": ck})
            done.add(c["slot"])
            placed.append(c["t"])
        for n, sl in enumerate(slots):
            if n not in done and n not in retry:
                failed.append((sl["lo"], sl["hi"]))
                if not any(h["t1"] == sl["hi"] for h in info["holes"]):
                    info["holes"].append({"t0": sl["lo"] - MIN_SEP, "t1": sl["hi"],
                                          "why": "aucun passage des vidéos jointes vraiment cohérent avec ce que tu dis là "
                                                 "(ou passages déjà tous utilisés)"})
    log.info("Rythme : %d extrait(s) ajouté(s), %d créneau(x) laissé(s) sans extrait", len(info["added"]),
             len(info["holes"]))
    return info


# ------------------------------------------------------------------ éléments : extraits + articles + photos
CARDS = """Tu es le monteur d'une vidéo face caméra (langue « {lang} ») pour un public de 40 ans et plus. Pour garder
l'attention, il faut un élément visuel à certains moments. Pour chaque CRÉNEAU, choisis UN élément qui illustre
précisément CE QUE L'AUTEUR DIT À CE MOMENT-LÀ (même fait, même personne, même lieu, même chiffre), et la phrase sur
laquelle l'afficher (il apparaît à côté de l'auteur pendant qu'il parle).

Ordre de préférence : 1) un ARTICLE / message de la liste ; 2) une PHOTO jointe ; 3) {wiki_rule}

CRÉNEAUX :
{slots}

ARTICLES ET MESSAGES DISPONIBLES :
{articles}

PHOTOS JOINTES DISPONIBLES :
{photos}

Règles : un élément ne sert qu'une fois ; jamais hors sujet ; si rien n'est vraiment cohérent pour un créneau,
"item": null (ne force jamais).
Réponds en JSON : {{"fills": [{{"slot": n, "s": numéro de phrase, "item": "A3" | "P1" | "W" | null,
"query": "pour W : nom exact de la personne / du lieu / de l'objet (sinon vide)", "why": "le lien, en une phrase"}}]}}"""

VERIFY_CARD = """Vérification indépendante (langue « {lang} »). Chaque élément s'affiche à côté de l'auteur pendant qu'il
dit la phrase indiquée. Est-il en rapport DIRECT avec ce qu'il dit (même fait / personne / lieu / chiffre) ? Sois
exigeant : « dans le thème général » ne suffit pas.

{cases}

Réponds en JSON : {{"checks": [{{"n": numéro, "ok": true/false, "score": 0 à 10, "reason": "une phrase"}}]}}"""


def visual_time(v: dict, sents: list) -> float | None:
    try:
        return float(sents[int(v["s0"])]["t0"])
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def elements(inserts: list, visuals: list, words: list, sents: list, sil: list) -> list[dict]:
    """Tous les éléments prévus, triés : {"t", "kind" (video|card), "obj", "protected"}.
    Protégés (jamais retirés) : tes « écoutez ça », tes vidéos jointes, tes photos jointes, l'ouverture choc."""
    out = []
    for i in inserts:
        t = insert_time(i, words, sents, sil)
        if t is not None:
            out.append({"t": t, "kind": "video", "obj": i,
                        "protected": i.get("kw") is not None or bool(i.get("attachment")) or bool(i.get("opener"))})
    for v in visuals:
        if not v.get("asset"):
            continue
        t = visual_time(v, sents)
        if t is not None:
            out.append({"t": t, "kind": "card", "obj": v, "protected": v.get("kind") == "attachment"})
    return sorted(out, key=lambda e: e["t"])


def holes(times: list, t_start: float, t_end: float, opener: bool) -> list[tuple[float, float]]:
    """Fenêtres [lo, hi] où un élément manque (même règle que le remplissage vidéo)."""
    pts = sorted(times)
    prev = t_start
    out = []
    for t in pts + [t_end]:
        cur = prev
        while True:
            first = cur - t_start < FIRST
            lim, tol, sp = (GAP1, 5.0, MIN_SEP) if first else (GAP2, GAP2_MAX - GAP2, AUTO_SEP)
            if t - cur <= lim + tol:
                break
            out.append((cur + sp, cur + lim))
            cur = cur + lim
        prev = max(prev, t)
    return out


def fill_cards(ai, words, sents, inserts, visuals, sil, lang, opener, pool: dict, make_visual, info: dict,
               wiki: bool = True, rounds: int = 3) -> None:
    """Étapes 2 et 3 : articles puis photos dans les trous restants. pool = {"articles": [...], "photos": [...]}
    (chaque article : {"titre", "source", "url", …} ; chaque photo : pièce jointe image). make_visual(choix, s) crée
    le visuel (avec son panneau) ou renvoie None. Jamais bloquant."""
    if not sents:
        return
    t_start, t_end = sents[0]["t0"], sents[-1]["t1"]
    arts = list(pool.get("articles") or [])
    photos = list(pool.get("photos") or [])
    used_a, used_p = set(), set()
    tried: set = set()
    for rnd in range(rounds):
        times = [e["t"] for e in elements(inserts, visuals, words, sents, sil)]
        hs = [h for h in holes(times, t_start, t_end, opener) if (round(h[0]), round(h[1])) not in tried]
        if not hs:
            return
        if not ai or not getattr(ai, "ok", False):
            for lo, hi in hs:
                info["holes"].append({"t0": lo, "t1": hi, "why": "IA indisponible : aucun article ni photo ajouté"})
            return
        free_a = [k for k in range(len(arts)) if k not in used_a]
        free_p = [k for k in range(len(photos)) if k not in used_p]
        if not free_a and not free_p and not wiki:
            for lo, hi in hs:
                info["holes"].append({"t0": lo, "t1": hi, "why": "plus aucun article ni photo disponible"})
            return
        taken_s = {v.get("s0") for v in visuals}
        slots = []
        for lo, hi in hs[:MAX_SLOTS]:
            ss = [x for x in sents if lo <= x["t0"] <= hi and x["i"] not in taken_s]
            tried.add((round(lo), round(hi)))
            if not ss:
                info["holes"].append({"t0": lo, "t1": hi, "why": "aucune phrase libre à cet endroit"})
                continue
            slots.append({"lo": lo, "hi": hi, "ss": ss})
        if not slots:
            continue
        txt = "\n".join(f"Créneau {n} ({tc(sl['lo'])} → {tc(sl['hi'])}) : " +
                        " ".join(f"[{x['i']}] {x['text']}" for x in sl["ss"])[:1500] for n, sl in enumerate(slots))
        a_txt = "\n".join(f"[A{k}] {arts[k].get('source') or ''} : {arts[k].get('titre') or ''}"[:260]
                          for k in free_a[:60]) or "(aucun)"
        p_txt = "\n".join(f"[P{k}] {photos[k].get('description') or photos[k].get('name')}"[:220]
                          for k in free_p[:30]) or "(aucune)"
        wiki_rule = ("une PHOTO LIBRE (Wikimedia) d'une personne, d'un lieu ou d'un objet NOMMÉ dans le créneau : "
                     "item \"W\" + query" if wiki else "rien d'autre (pas de photo libre)")
        j = ai.json(CARDS.format(lang=lang, wiki_rule=wiki_rule, slots=txt, articles=a_txt, photos=p_txt))
        picks = (j or {}).get("fills") if isinstance(j, dict) else None
        if not isinstance(picks, list):
            for sl in slots:
                info["holes"].append({"t0": sl["lo"], "t1": sl["hi"], "why": "IA indisponible"})
            continue
        chosen, seen_slot = [], set()
        for p in picks:
            if not isinstance(p, dict):   # réponse IA mal formée : élément ignoré
                continue
            try:
                n, si = int(p.get("slot")), int(p.get("s"))
                sl = slots[n]
            except (TypeError, ValueError, IndexError):
                continue
            item = str(p.get("item") or "").strip().upper()
            if n in seen_slot or not item or si not in {x["i"] for x in sl["ss"]}:
                continue
            c = {"slot": n, "s": si, "why": str(p.get("why") or "")[:200]}
            if item.startswith("A") and item[1:].isdigit() and int(item[1:]) in free_a \
                    and int(item[1:]) not in {x.get("a") for x in chosen}:
                c.update(kind="article", a=int(item[1:]), label=arts[int(item[1:])].get("titre", ""))
            elif item.startswith("P") and item[1:].isdigit() and int(item[1:]) in free_p \
                    and int(item[1:]) not in {x.get("p") for x in chosen}:
                c.update(kind="photo", p=int(item[1:]), label=photos[int(item[1:])].get("description") or "")
            elif item == "W" and wiki and str(p.get("query") or "").strip():
                c.update(kind="wiki", query=str(p["query"]).strip()[:80], label=str(p["query"]).strip()[:80])
            else:
                continue
            seen_slot.add(n)
            chosen.append(c)
        if chosen:   # 2e lecture indépendante
            cases = "\n\n".join(f"[{k}] PHRASE : « {sents[c['s']]['text'][:400]} »\n    ÉLÉMENT ({c['kind']}) : "
                                f"« {c['label'][:300]} »" for k, c in enumerate(chosen))
            chk = ai.json(VERIFY_CARD.format(lang=lang, cases=cases))
            for ck in ((chk or {}).get("checks") or []) if isinstance(chk, dict) else []:
                if not isinstance(ck, dict):   # réponse IA mal formée : élément ignoré
                    continue
                try:
                    k = int(ck.get("n"))
                except (TypeError, ValueError):
                    continue
                if 0 <= k < len(chosen):
                    chosen[k]["check"] = {"ok": bool(ck.get("ok")), "score": ck.get("score"),
                                          "reason": str(ck.get("reason") or "")[:200]}
        for c in chosen:
            sl = slots[c["slot"]]
            ck = c.get("check")
            if ck is None:
                info["holes"].append({"t0": sl["lo"], "t1": sl["hi"], "why": "vérification indisponible : rien ajouté"})
                continue
            if not ck["ok"]:
                info["holes"].append({"t0": sl["lo"], "t1": sl["hi"],
                                      "why": f"élément proposé refusé à la vérification ({ck['reason']})"})
                continue
            src = arts[c["a"]] if c["kind"] == "article" else photos[c["p"]] if c["kind"] == "photo" else None
            try:
                v = make_visual(c["kind"], src, c.get("query", ""), c["s"])
            except Exception as e:  # noqa: BLE001
                log.warning("élément de rythme abandonné : %s", e)
                v = None
            if not v:
                info["holes"].append({"t0": sl["lo"], "t1": sl["hi"],
                                      "why": f"{'photo libre introuvable' if c['kind'] == 'wiki' else 'image impossible'}"
                                             f" pour « {c['label'][:60]} »"})
                continue
            v["rythme"] = True
            v["source"] = f"RYTHME — {v.get('source', '')} — {c['why']} — vérifié ✅ ({ck.get('score')}/10)"
            visuals.append(v)
            if c["kind"] == "article":
                used_a.add(c["a"])
            elif c["kind"] == "photo":
                used_p.add(c["p"])
            info["cards"].append({"t": sents[c["s"]]["t0"], "kind": c["kind"], "label": c["label"][:90],
                                  "why": c["why"], "check": ck})
        for n, sl in enumerate(slots):
            if n not in seen_slot and not any(abs(h["t1"] - sl["hi"]) < 1 for h in info["holes"]):
                info["holes"].append({"t0": sl["lo"], "t1": sl["hi"],
                                      "why": "aucun article ni photo vraiment cohérent avec ce que tu dis là"})


def thin(inserts: list, visuals: list, words, sents, sil, info: dict) -> None:
    """Après 5 min : pas d'élément AUTOMATIQUE à moins de 1 min 30 du précédent (rythme régulier, sans paquets).
    Les éléments protégés (tes « écoutez ça », tes pièces jointes) passent toujours. Les retraits sont listés."""
    if not sents:
        return
    t_start = sents[0]["t0"]
    last = None
    drop_ins, drop_vis = [], []
    for e in elements(inserts, visuals, words, sents, sil):
        if e["t"] - t_start < FIRST:
            last = e["t"]
            continue
        if e["protected"] or last is None or e["t"] - last >= AUTO_SEP:
            last = e["t"]
            continue
        (drop_ins if e["kind"] == "video" else drop_vis).append(e["obj"])
        o = e["obj"]
        lab = (o.get("asset") or {}).get("source") if e["kind"] == "video" else (o.get("label") or o.get("source"))
        info.setdefault("thinned", []).append({"t": e["t"], "kind": e["kind"], "label": str(lab or "")[:100],
                                               "gap": e["t"] - last})
    if drop_ins:
        inserts[:] = [i for i in inserts if not any(i is d for d in drop_ins)]
    if drop_vis:
        visuals[:] = [v for v in visuals if not any(v is d for d in drop_vis)]
    if drop_ins or drop_vis:
        log.info("Rythme : %d élément(s) automatique(s) retiré(s) (moins de 1 min 30 après le précédent)",
                 len(drop_ins) + len(drop_vis))


def qc_holes(segs: list, total: float, outro: float = 0.0) -> list[tuple[float, float]]:
    """Trous de plus de 2 min 30 sans élément après les 5 premières minutes (vidéo finale)."""
    starts, prev_panel = [], None
    for s in segs:
        if s.kind == "insert":
            starts.append(s.out0)
            prev_panel = None
        elif s.kind == "split":
            if s.panel is not prev_panel:
                starts.append(s.out0)
            prev_panel = s.panel
        else:
            prev_panel = None
    end = max(0.0, total - outro)
    out = []
    prev = 0.0
    for t in sorted(starts) + [end]:
        if t > FIRST and t - max(prev, FIRST - GAP1) > QC_HOLE:
            out.append((prev, t))
        prev = max(prev, t)
    return out
