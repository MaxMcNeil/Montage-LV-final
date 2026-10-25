"""Construction de la ligne de temps : quels morceaux de ta vidéo on garde (silences raccourcis), où s'insèrent les
extraits vidéo (toujours dans un silence, entre deux phrases), quand apparaissent les médias à côté de toi, et
les zooms de relance. Tout est calé à l'image près (30 i/s)."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from .config import FPS
from .util import frames, norm, q

log = logging.getLogger("montage.timeline")

CUT = {"doux": (1.0, 0.28, 0.32), "dynamique": (0.6, 0.16, 0.22)}  # pause min, marge avant, marge après


def keep_ranges(words: list, sil: list, duration: float, mode: str, skip_start: float = 0.0) -> list[tuple[float, float]]:
    """Plages gardées de la vidéo source. Une pause n'est raccourcie que si les mots ET le son confirment le silence."""
    if not words:
        return [(q(skip_start), q(duration))]
    start = max(0.0, words[0]["t0"] - 0.15)   # on démarre sur ta parole : chaque dixième compte pour l'audience
    end = min(duration, words[-1]["t1"] + 0.9)
    if skip_start > start:  # images noires au début de la source : jamais montrées
        start = min(skip_start, max(start, words[0]["t0"] - 0.02))
    if mode not in CUT:
        return [(q(start), q(end))]
    gap_min, before, after = CUT[mode]
    cuts = []
    for w1, w2 in zip(words, words[1:]):
        g0, g1 = w1["t1"] + after, w2["t0"] - before
        if w2["t0"] - w1["t1"] < gap_min or g1 - g0 < 0.25:
            continue
        if sil:  # le silence doit être réel (sinon : mot non reconnu, on ne coupe pas)
            cover = sum(max(0.0, min(g1, b) - max(g0, a)) for a, b in sil)
            if cover < 0.8 * (g1 - g0):
                continue
        cuts.append((g0, g1))
    out, t = [], start
    for a, b in cuts:
        if a > t + 0.2:
            out.append((q(t), q(a)))
        t = b
    if end > t + 0.2:
        out.append((q(t), q(end)))
    return [(a, b) for a, b in out if b - a >= 2 / FPS]


@dataclass
class Atom:
    a: float                 # début dans la source
    b: float                 # fin dans la source
    layout: int | None = None  # index du panneau (média à côté) ou None = plein cadre
    zoom: float = 1.0


@dataclass
class Segment:
    kind: str                # full | split | insert
    out0: float = 0.0        # début dans la vidéo finale
    n: int = 0               # nombre d'images
    atoms: list = field(default_factory=list)
    panel: dict | None = None
    insert: dict | None = None
    side: str = "left"

    @property
    def dur(self) -> float:
        return self.n / FPS


def trigger_time(words: list, s: dict, trig: str) -> float:
    """Instant où le mot déclencheur est prononcé dans la phrase (sinon : début de phrase)."""
    toks = [t for t in norm(trig).split() if len(t) > 1]
    if toks:
        for k in range(s["w0"], s["w1"] + 1):
            nw = norm(words[k]["w"])
            if nw and (nw == toks[0] or (len(toks[0]) > 4 and (nw.startswith(toks[0][:5]) or toks[0].startswith(nw)))):
                return words[k]["t0"]
    return s["t0"]


def find_pause(words: list, sents: list, sil: list, after: int, look: int = 3) -> float | None:
    """Instant d'insertion GARANTI dans un vrai silence (jamais pendant que tu parles).
    On cherche, à partir de la fin de la phrase « after » et sur les `look` phrases suivantes, un trou entre deux mots
    d'au moins 0,35 s CONFIRMÉ par le son (silencedetect) ; priorité aux fins de phrase. Le point d'insertion est le
    milieu du silence. Rien de sûr → None (l'extrait n'est pas inséré plutôt que de te couper la parole)."""
    if not words or after >= len(sents):
        return None
    k0 = sents[after]["w1"]
    k1 = sents[min(after + look, len(sents) - 1)]["w1"]
    best = None
    for k in range(k0, k1 + 1):
        a = words[k]["t1"]
        b = words[k + 1]["t0"] if k + 1 < len(words) else a + 1.5
        if b - a < 0.35:
            continue
        if sil:  # le silence doit être réel : on prend la partie vraiment silencieuse du trou
            ov = [(max(a, x), min(b, y)) for x, y in sil if min(b, y) - max(a, x) >= 0.25]
            if not ov:
                continue
            x, y = max(ov, key=lambda o: o[1] - o[0])
        else:
            if b - a < 0.6:
                continue
            x, y = a, b
        t = (x + y) / 2
        end_sentence = bool(re.search(r"[.!?…؟]['\"»”)]*$", words[k]["w"])) or k == len(words) - 1
        cand = (0 if end_sentence else 1, k, t)
        if end_sentence:
            return q(t)
        if best is None:
            best = cand
    return q(best[2]) if best else None


def schedule(words, sents, keep, visuals, inserts, chapters, total_src, opts, orient, opener=None,
             sil=None) -> tuple[list, list]:
    """visuals : [{..., "asset": panneau}], inserts : [{"after": i, "asset": extrait}].
    Retourne (segments, panneaux_retenus)."""
    if not keep:
        return [], []
    speech = sum(b - a for a, b in keep)
    # 1) points d'insertion : juste après la fin d'une phrase, dans le silence
    pts = []
    for ins in sorted(inserts, key=lambda i: i["after"]):
        t = find_pause(words, sents, sil or [], ins["after"])
        if t is None:
            log.warning("pas de vrai silence après la phrase %d : extrait non inséré (pour ne pas te couper)", ins["after"])
            continue
        t = _snap(t, keep)
        if t is None or any(abs(t - p["t"]) < 8 for p in pts):
            continue
        # sécurité ultime : aucun mot prononcé ne chevauche le point d'insertion
        if any(w["t0"] - 0.05 < t < w["t1"] + 0.05 for w in words):
            log.warning("point d'insertion %.2f s sur un mot : extrait non inséré", t)
            continue
        pts.append({"t": t, **ins})
    # 2) médias à côté de toi : fenêtre calée sur le mot déclencheur
    chap_t = [sents[c["s"]]["t0"] for c in chapters if c["s"] < len(sents)]
    first_t = keep[0][0]
    last_t = keep[-1][1]
    cands = []
    for v in visuals:
        if not v.get("asset"):
            continue
        s0, s1 = sents[v["s0"]], sents[min(v["s1"], len(sents) - 1)]
        st = trigger_time(words, s0, v.get("trigger", "")) - 0.12
        en = max(s1["t1"] + 0.45, st + 3.8)  # au moins ~4 s à l'écran (temps de lecture), au plus 7,5 s
        en = min(en, st + (7.5 if v["kind"] != "article" else 8.5))
        rank = (0 if v["kind"] == "attachment" else 1, v.get("priority", 2), st)
        cands.append({"v": v, "st": st, "en": en, "rank": rank})
    cands.sort(key=lambda c: c["rank"])
    chosen, cover = [], 0.0
    for c in cands:
        st, en = c["st"], c["en"]
        if st < first_t + 4.0 or en > last_t - (7.0 if opts.get("fin") == "oui" else 1.0):
            continue
        for t in chap_t:  # un titre de chapitre ne partage jamais l'écran avec un média
            if t <= first_t + 1:
                continue
            if t - 4.9 < st < t + 4.9 and t - st < 1.5:   # chapitre au début du média : le média attend la fin du titre
                st = t + 4.9
            elif st < t < en + 0.5:                          # chapitre pendant le média : le média s'arrête avant
                en = t - 0.5
        for p in pts:  # jamais à cheval sur un extrait inséré
            if st - 1.0 < p["t"] < en + 0.6:
                en = p["t"] - 0.6
        if en - st < 3.0:
            continue
        if any(not (en + 2.2 <= o["st"] or st >= o["en"] + 2.2) for o in chosen):
            continue
        if c["v"]["kind"] != "attachment" and cover + (en - st) > 0.6 * speech:
            continue
        chosen.append({"v": c["v"], "st": q(st), "en": q(en)})
        cover += en - st
    chosen.sort(key=lambda c: c["st"])
    for i, c in enumerate(chosen):
        c["side"] = "left" if i % 2 == 0 else "right"
    # extrait inséré après ta dernière phrase : la vidéo se termine sur l'extrait (pas de retour muet de 1 s)
    if pts and words and pts[-1]["t"] >= words[-1]["t1"]:
        tend = pts[-1]["t"]
        keep = [(a, min(b, tend)) for a, b in keep if a < tend - 1e-6]
    # 3) atomes : plages gardées découpées à chaque frontière
    bounds = sorted({p["t"] for p in pts} | {c["st"] for c in chosen} | {c["en"] for c in chosen})
    atoms = []
    for a, b in keep:
        cur = a
        for t in bounds:
            if a < t < b and t - cur >= 1 / FPS:
                atoms.append(Atom(cur, t))
                cur = t
        atoms.append(Atom(cur, b))
    for at in atoms:
        mid = (at.a + at.b) / 2
        at.layout = next((i for i, c in enumerate(chosen) if c["st"] <= mid < c["en"]), None)
    # 4) segments
    segs: list[Segment] = []
    ins_at = {p["t"]: p for p in pts}
    cur = None
    for at in atoms:
        if ins_at and cur is not None and at.a in ins_at and cur.kind != "insert":
            p = ins_at.pop(at.a)
            segs.append(Segment("insert", insert=p))
            cur = None
        kind = "full" if at.layout is None else "split"
        if cur is None or cur.kind != kind or (kind == "split" and cur.atoms[-1].layout != at.layout):
            cur = Segment(kind, panel=chosen[at.layout] if at.layout is not None else None,
                          side=chosen[at.layout]["side"] if at.layout is not None else "left")
            segs.append(cur)
        cur.atoms.append(at)
    for t, p in sorted(ins_at.items()):  # insertion en toute fin
        if t >= atoms[-1].b - 1e-6:
            segs.append(Segment("insert", insert=p))
    # 5) zooms de relance dans les plans pleins : changement à chaque coupe et toutes les ~7 s
    _zooms(segs, sents, orient)
    # plans pleins très longs : découpés en blocs (≤ 10 morceaux) pour garder chaque rendu léger — invisible à l'écran
    split_segs = []
    for s in segs:
        if s.kind == "full" and len(s.atoms) > 10:
            for k in range(0, len(s.atoms), 10):
                split_segs.append(Segment("full", atoms=s.atoms[k:k + 10]))
        else:
            split_segs.append(s)
    segs = split_segs
    if opener:  # ouverture choc : le passage le plus fort de l'extrait joint, avant que tu apparaisses
        segs.insert(0, Segment("insert", insert={"t": keep[0][0], "after": -1, "asset": opener, "opener": True}))
    # 6) durées en images
    t = 0.0
    for s in segs:
        s.n = frames(s.insert["asset"]["duration"]) if s.kind == "insert" else sum(frames(x.b - x.a) for x in s.atoms)
        s.out0 = t
        t += s.n / FPS
    segs = [s for s in segs if s.n > 0]
    return segs, chosen


def _snap(t: float, keep: list) -> float | None:
    for i, (a, b) in enumerate(keep):
        if a <= t <= b:
            if t > b - 2 / FPS and i + 1 < len(keep):  # pile sur une coupe : début de la plage suivante (toujours un silence)
                return keep[i + 1][0]
            return t
        if t < a:  # dans un silence coupé : on prend le point de coupe
            return a
    return None


def _zooms(segs, sents, orient):
    zin = 1.12 if orient == "h" else 1.08
    ends = [s["t1"] for s in sents]
    for si, s in enumerate(segs):
        if s.kind != "full":
            continue
        # sous-découpe aux fins de phrase toutes les ~7 s (en plus des coupes de silence)
        new = []
        for at in s.atoms:
            cur, last = at.a, at.a
            for e in ends:
                if cur + 6.5 < e < at.b - 2.5 and e - last >= 6.5:
                    t = q(e + 0.1)
                    new.append(Atom(cur, t))
                    cur = last = t
            new.append(Atom(cur, at.b))
        s.atoms = new
        n = len(new)
        for k, at in enumerate(new):
            at.zoom = zin if k % 2 == 1 else 1.0
        # bords collés à un média ou un extrait : plan large (transition propre)
        if si > 0 and segs[si - 1].kind != "full":
            new[0].zoom = 1.0
        if si + 1 < len(segs) and segs[si + 1].kind != "full" and n:
            new[-1].zoom = 1.0
            if n >= 2 and new[-2].zoom == 1.0 and new[-1].b - new[-1].a < 2.0:
                new[-2].zoom = zin


def out_time(segs: list, t_src: float) -> float | None:
    """Temps dans la vidéo finale d'un instant de la source (None s'il a été coupé)."""
    for s in segs:
        if s.kind == "insert":
            continue
        acc = s.out0
        for at in s.atoms:
            d = frames(at.b - at.a) / FPS
            if at.a - 1e-6 <= t_src <= at.b + 1e-6:
                return acc + min(d, t_src - at.a)
            acc += d
    return None


def seg_at(segs: list, t_out: float):
    for s in segs:
        if s.out0 - 1e-6 <= t_out < s.out0 + s.dur:
            return s
    return segs[-1] if segs else None
