"""Rythme des extraits (rétention d'audience) — option « rythme », activée par défaut.

Règle : pendant les 5 premières minutes, jamais plus de 60 s sans un extrait de tes vidéos jointes ; ensuite, jamais
plus de 2 min. Là où ta vidéo n'en a pas assez (plan de l'IA, « écoutez ça », Vid-o-presse-finder…), un passage est
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
GAP2 = 120.0        # ensuite toutes les 2 min
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
         work: Path, opener: bool, prepare) -> dict:
    """Ajoute des extraits de rythme dans `inserts`. `used` : {id vidéo: [(a, b), …]} passages déjà pris (mis à jour).
    `prepare(x, a, b, name)` prépare l'extrait (asset) ou renvoie None."""
    from .keywords import _ctx, _sents_in, _videos_text
    from .timeline import find_pause
    info = {"added": [], "holes": [], "rule": "5 premières minutes : 60 s max entre deux extraits ; ensuite 2 min max"}
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
    failed: list[tuple] = []
    for rnd in range(MAX_ROUNDS):
        pts = sorted(t for t in (insert_time(i, words, sents, sil) for i in inserts) if t is not None)
        pts = [t_start] + pts if opener else pts
        # créneaux : premier endroit de chaque trou où il faudrait un extrait
        slots = []
        prev = t_start if not pts or pts[0] > t_start else pts[0]
        for t in pts + [t_end]:
            cur = prev
            while t - cur > lim(cur) + 5.0:          # un trou trop long : premier créneau encore possible
                lo, hi = cur + MIN_SEP, cur + lim(cur)
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
