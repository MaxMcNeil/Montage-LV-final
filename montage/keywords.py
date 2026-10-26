"""Montage par mots-clés (option « mots_cles », désactivée par défaut).

Chaque fois que tu prononces EXACTEMENT l'une de ces phrases :
    écoutez ça · écoutez-moi ça · écoutez ce qu'il dit · écoutez ce qu'elle dit · écoutez ce qu'ils disent
un passage de ta (tes) vidéo(s) jointe(s) est inséré juste après, dans ton silence (jamais pendant que tu parles).

Fiabilité :
- détection sur la transcription mot à mot, phrase EXACTE (une formule voisine ne déclenche rien) ;
- point d'insertion = le premier vrai silence (confirmé par le son) dans les 8 s qui suivent la phrase ;
- le passage est choisi par l'IA d'après ce que tu dis AVANT et APRÈS l'annonce, en lisant la transcription des
  vidéos jointes ; puis une 2e lecture indépendante VÉRIFIE la cohérence (et fait rechoisir si besoin) ;
- coupe sur des phrases complètes ; deux annonces n'utilisent pas le même passage ;
- chaque annonce est listée dans PLAN.md (inséré / non inséré et pourquoi) et vérifiée par le contrôle qualité."""
from __future__ import annotations

import logging

from .util import norm, q, tc

log = logging.getLogger("montage.keywords")

PHRASES = {
    ("ecoutez", "ca"): "écoutez ça",
    ("ecoutez", "moi", "ca"): "écoutez-moi ça",
    ("ecoutez", "ce", "qu", "il", "dit"): "écoutez ce qu'il dit",
    ("ecoutez", "ce", "qu", "elle", "dit"): "écoutez ce qu'elle dit",
    ("ecoutez", "ce", "qu", "ils", "disent"): "écoutez ce qu'ils disent",
    ("ecoutez", "ce", "qu", "elles", "disent"): "écoutez ce qu'ils disent",   # même prononciation que « ils disent »
}
MAX_WAIT = 8.0      # « écoutez ce qu'il dit (à propos de…) » : la pause peut venir un peu plus loin
MAX_WAIT_CA = 1.2   # « écoutez ça » : la pause suit tout de suite (sinon « écoutez ça va… » n est pas une annonce)
PUNCT = __import__("re").compile(r"[,;:.!?…]['\"»”)]*$")


def find_occurrences(words: list) -> list[dict]:
    """Occurrences exactes des phrases, dans l'ordre. Une occurrence plus longue l'emporte (« écoutez-moi ça »)."""
    toks = []  # (token, index du mot)
    for k, w in enumerate(words):
        for t in norm(w["w"]).split():
            toks.append((t, k))
    seq = [t for t, _ in toks]
    out, i = [], 0
    pats = sorted(PHRASES, key=len, reverse=True)
    while i < len(seq):
        hit = next((p for p in pats if tuple(seq[i:i + len(p)]) == p), None)
        if hit:
            k0, k1 = toks[i][1], toks[i + len(hit) - 1][1]
            # une ponctuation à l'intérieur casse la phrase (« Écoutez, ça va changer » n'est pas une annonce)
            if any(PUNCT.search(words[k]["w"]) for k in range(k0, k1)):
                i += 1
                continue
            out.append({"phrase": PHRASES[hit], "w0": k0, "w1": k1, "t0": words[k0]["t0"], "t1": words[k1]["t1"],
                        "wait": MAX_WAIT_CA if hit[-1] == "ca" else MAX_WAIT})
            i += len(hit)
        else:
            i += 1
    return out


def pause_after(words: list, sil: list, k_end: int, max_wait: float = MAX_WAIT) -> float | None:
    """Premier vrai silence (≥ 0,35 s entre deux mots, confirmé par le son) après le mot k_end, dans max_wait s."""
    t_end = words[k_end]["t1"]
    for k in range(k_end, len(words)):
        a = words[k]["t1"]
        if a - t_end > max_wait:
            return None
        b = words[k + 1]["t0"] if k + 1 < len(words) else a + 1.5
        if b - a < 0.35:
            continue
        if sil:
            ov = [(max(a, x), min(b, y)) for x, y in sil if min(b, y) - max(a, x) >= 0.25]
            if not ov:
                continue
            x, y = max(ov, key=lambda o: o[1] - o[0])
        else:
            if b - a < 0.6:
                continue
            x, y = a, b
        return q((x + y) / 2)
    return None


def _ctx(words: list, k0: int, k1: int, before: int = 90, after: int = 45) -> tuple[str, str]:
    a = " ".join(w["w"] for w in words[max(0, k0 - before):k0])
    b = " ".join(w["w"] for w in words[k1 + 1:k1 + 1 + after])
    return a, b


def _videos_text(vids: list) -> str:
    L = []
    for x in vids:
        ss = x.get("sentences") or []
        if x.get("cut"):
            a, b = x["cut"]
            ss = [s for s in ss if s["t1"] > a and s["t0"] < b]
            L.append(f'- id "{x["id"]}" « {x["name"]} » — PASSAGE IMPOSÉ PAR L\'AUTEUR : {a:.0f}-{b:.0f} s '
                     f'(n\'utilise que ce passage de cette vidéo)')
        else:
            L.append(f'- id "{x["id"]}" « {x["name"]} » ({x.get("duration", 0):.0f} s) — {x.get("description") or ""}')
        if ss:
            L += [f'    [{s["t0"]:.1f}-{s["t1"]:.1f}] {s["text"]}' for s in ss[:260]]
        else:
            L.append("    (aucune parole dans cette vidéo)")
    return "\n".join(L)


PICK = """Tu es le monteur d'une vidéo face caméra (langue « {lang} »). À plusieurs reprises, l'auteur annonce un extrait
avec une phrase comme « écoutez ça » ou « écoutez ce qu'elle dit » : juste après, on doit entendre un passage d'une des
vidéos jointes qui correspond EXACTEMENT à ce qu'il annonce (la personne, le propos, le fait dont il parle).

ANNONCES (contexte avant, la phrase d'annonce, puis ce qu'il dit après l'extrait) :
{annonces}

VIDÉOS JOINTES (transcription horodatée, en secondes) :
{videos}

Pour CHAQUE annonce, choisis le passage le plus juste :
- il illustre précisément ce que l'auteur vient de dire / annonce, et s'enchaîne avec ce qu'il dit après ;
- « ce qu'il dit » / « ce qu'elle dit » / « ce qu'ils disent » : la personne / les personnes dont il parle doivent
  être celles qui parlent dans le passage ;
- de {dmin} à {dmax} secondes, commence au début d'une phrase et finit à la fin d'une phrase (bornes [début-fin]
  ci-dessus) ;
- deux annonces différentes n'utilisent pas le même passage (sauf si l'auteur annonce clairement la même chose) ;
- {exclude}
Réponds en JSON : {{"choices": [{{"n": numéro d'annonce, "video": "id", "start": secondes, "end": secondes,
"confidence": 0 à 10, "why": "en une phrase"}}]}}"""

CHECK = """Vérification indépendante d'un montage (langue « {lang} »). Pour chaque cas, l'auteur annonce un extrait
puis on insère le passage indiqué. Le passage correspond-il EXACTEMENT à ce qu'il annonce et à ce qu'il dit ensuite
(même sujet, même personne, même fait) ? Sois exigeant.

{cases}

Réponds en JSON : {{"checks": [{{"n": numéro, "ok": true/false, "score": 0 à 10, "reason": "une phrase"}}]}}"""


def _sents_in(x: dict, a: float, b: float) -> str:
    return " ".join(s["text"] for s in (x.get("sentences") or []) if s["t1"] > a + 0.2 and s["t0"] < b - 0.2)


def _clamp(x: dict, a: float, b: float, maxd: float) -> tuple[float, float]:
    from .assets import choose_bounds
    dur = float(x.get("duration") or 0)
    lo, hi = (x["cut"] if x.get("cut") else (0.0, dur))
    a, b = max(lo, min(a, hi)), max(lo, min(b, hi))
    ss = [s for s in (x.get("sentences") or []) if s["t0"] >= lo - 0.5 and s["t1"] <= hi + 0.5]
    if b <= a + 1:
        b = min(hi, a + maxd)
    a2, b2 = choose_bounds(ss, a, b, maxd, min(dur, hi + 0.35))
    if b2 - a2 < 2.0:   # sécurité : jamais un extrait vide
        a2, b2 = a, min(hi, max(b, a + 4.0))
    return round(a2, 2), round(b2, 2)


def _lexical(occ: list, words: list, vids: list, maxd: float, taken: list) -> list[dict]:
    """Sans IA : passage (1 à 3 phrases) dont le vocabulaire ressemble le plus à ce que tu dis autour de l'annonce
    (les mots juste avant l'annonce comptent double). Un passage déjà pris n'est réutilisé qu'en dernier recours."""
    stop = set("alors avec aussi avant comme dans donc elle elles encore entre etre fait faut mais meme nous parce "
               "plus pour quand quel quelle sans sont tout tous tres vous cette celle ceux leur leurs notre votre "
               "ecoutez voila cela".split())
    out = []
    for n, o in enumerate(occ):
        near, aft = _ctx(words, o["w0"], o["w1"], 12, 25)
        mid = " ".join(w["w"] for w in words[max(0, o["w0"] - 30):max(0, o["w0"] - 12)])
        far = " ".join(w["w"] for w in words[max(0, o["w0"] - 90):max(0, o["w0"] - 30)])
        wt: dict[str, float] = {}
        for txt, k in ((far, 0.3), (mid, 1.0), (aft, 1.0), (near, 3.0)):
            for w in norm(txt).split():
                if len(w) > 3 and w not in stop:
                    wt[w] = max(wt.get(w, 0.0), k)
        best = None   # (libre, score, -nb phrases, vidéo, a, b)
        for x in vids:
            ss = x.get("sentences") or []
            if x.get("cut"):
                ss = [s_ for s_ in ss if s_["t1"] > x["cut"][0] and s_["t0"] < x["cut"][1]]
            for i in range(len(ss)):
                for m in (1, 2, 3):
                    if i + m > len(ss) or ss[i + m - 1]["t1"] - ss[i]["t0"] > maxd * 1.6:
                        break
                    a, b = ss[i]["t0"], ss[i + m - 1]["t1"]
                    sc = sum(wt.get(w, 0.0) for w in set(norm(" ".join(t["text"] for t in ss[i:i + m])).split()))
                    sc = sc / (1 + 0.6 * (m - 1))   # à score égal, le passage le plus court (le plus précis) gagne
                    free = not any(t[0] == x["id"] and min(b, t[2]) - max(a, t[1]) > 0.3 * min(b - a, t[2] - t[1])
                                   for t in taken)
                    key = (free, sc, -m)
                    if best is None or key > best[:3]:
                        best = (free, sc, -m, x, a, b)
            if not ss:  # vidéo sans parole : morceaux successifs
                k = sum(1 for t in taken if t[0] == x["id"])
                lo, hi = (x["cut"] if x.get("cut") else (0.0, float(x.get("duration") or 0)))
                a = lo + k * maxd if lo + k * maxd + 3 < hi else lo
                if best is None:
                    best = (True, 0.0, 0, x, a, min(hi, a + maxd))
        if best:
            x, a, b = best[3], best[4], best[5]
            out.append({"n": n, "video": x["id"], "start": a, "end": b, "confidence": 3,
                        "why": "choix par mots communs (IA indisponible)"})
            taken.append((x["id"], a, b))
    return out


def choose(ai, occ: list, words: list, vids: list, lang: str, maxd: float) -> list[dict]:
    """Passage choisi pour chaque annonce : {"n", "video", "a", "b", "confidence", "why", "check"}."""
    by = {x["id"]: x for x in vids}
    ann = []
    for n, o in enumerate(occ):
        bef, aft = _ctx(words, o["w0"], o["w1"])
        ann.append(f"[{n}] ({tc(o['t0'])}) … {bef} « {o['phrase'].upper()} » → (extrait) → {aft} …")
    res: dict[int, dict] = {}
    excluded: dict[int, list] = {}
    for attempt in range(2):
        todo = [n for n in range(len(occ)) if n not in res]
        if not todo:
            break
        j = None
        if ai and ai.ok:
            ex = "; ".join(f"annonce {n} : ne reprends pas {v} {a:.0f}-{b:.0f} s (refusé à la vérification)"
                           for n, lst in excluded.items() for v, a, b in lst) or "—"
            j = ai.json(PICK.format(lang=lang, annonces="\n".join(ann[n] for n in todo), videos=_videos_text(vids),
                                    dmin=4, dmax=int(maxd), exclude=ex))
        picks = (j or {}).get("choices") if isinstance(j, dict) else None
        if not isinstance(picks, list):
            taken = [(r["video"], r["a"], r["b"]) for r in res.values()]
            picks = _lexical([occ[n] for n in todo], words, vids, maxd, taken)
            picks = [dict(p, n=todo[p["n"]]) for p in picks]
        cand = {}
        for p in picks:
            try:
                n, x = int(p.get("n")), by.get(str(p.get("video")))
                a, b = float(p.get("start")), float(p.get("end"))
            except (TypeError, ValueError):
                continue
            if n not in todo or x is None or n in cand:
                continue
            a, b = _clamp(x, a, b, maxd)
            cand[n] = {"n": n, "video": x["id"], "a": a, "b": b, "confidence": p.get("confidence"),
                       "why": str(p.get("why") or "")[:200]}
        # vérification indépendante
        if cand and ai and ai.ok and any(by[c["video"]].get("sentences") for c in cand.values()):
            cases = []
            for n, c in cand.items():
                bef, aft = _ctx(words, occ[n]["w0"], occ[n]["w1"], 60, 35)
                cases.append(f"[{n}] AVANT : … {bef}\n    ANNONCE : « {occ[n]['phrase']} »\n"
                             f"    PASSAGE INSÉRÉ ({by[c['video']]['name']} {c['a']:.0f}-{c['b']:.0f} s) : "
                             f"« {_sents_in(by[c['video']], c['a'], c['b'])[:900]} »\n    APRÈS : {aft} …")
            chk = ai.json(CHECK.format(lang=lang, cases="\n\n".join(cases)))
            for ck in ((chk or {}).get("checks") or []) if isinstance(chk, dict) else []:
                try:
                    n = int(ck.get("n"))
                except (TypeError, ValueError):
                    continue
                if n in cand:
                    cand[n]["check"] = {"ok": bool(ck.get("ok")), "score": ck.get("score"),
                                        "reason": str(ck.get("reason") or "")[:200]}
        for n, c in cand.items():
            ok = (c.get("check") or {}).get("ok", True)
            if ok or attempt == 1:
                res[n] = c
            else:
                excluded.setdefault(n, []).append((c["video"], c["a"], c["b"]))
                c["rejected"] = True
                res.setdefault(-1 - n, c)  # garde le 1er choix en réserve si la 2e tentative échoue
    # annonce restée sans passage (IA partielle) : choix par mots communs, pour ne jamais en laisser une vide
    miss = [n for n in range(len(occ)) if n not in res and -1 - n not in res]
    if miss:
        taken = [(r["video"], r["a"], r["b"]) for r in res.values()]
        for p in _lexical([occ[n] for n in miss], words, vids, maxd, taken):
            x = by[p["video"]]
            a, b = _clamp(x, p["start"], p["end"], maxd)
            res[miss[p["n"]]] = {"n": miss[p["n"]], "video": x["id"], "a": a, "b": b, "confidence": 3, "why": p["why"]}
    out = []
    for n in range(len(occ)):
        c = res.get(n) or res.get(-1 - n)
        if c:
            c["n"] = n
            out.append(c)
    return out
