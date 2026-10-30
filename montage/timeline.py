"""Construction de la ligne de temps : quels morceaux de ta vidéo on garde (silences raccourcis), où s'insèrent les
extraits vidéo (toujours dans un silence, entre deux phrases), quand apparaissent les médias à côté de toi, et
les zooms de relance. Tout est calé à l'image près (30 i/s)."""
from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field

from .config import FPS
from .util import frames, norm, q

log = logging.getLogger("montage.timeline")

CUT = {"doux": (1.0, 0.28, 0.32), "dynamique": (0.6, 0.16, 0.22)}  # pause min, marge avant, marge après


def keep_ranges(words: list, sil: list, duration: float, mode: str, skip_start: float = 0.0,
                long_gap: float | None = None, voice_free=None) -> list[tuple[float, float]]:
    """Plages gardées de la vidéo source. Une pause n'est raccourcie que si les mots ET le son confirment le silence.
    long_gap (ex. 2.0) : toute pause plus longue est raccourcie à ~0,6 s, même si couper_silences = non."""
    if not words:
        return [(q(skip_start), q(duration))]
    start = max(0.0, words[0]["t0"] - 0.15)   # on démarre sur ta parole : chaque dixième compte pour l'audience
    end = min(duration, words[-1]["t1"] + 0.9)
    if skip_start > start:  # images noires au début de la source : jamais montrées
        start = min(skip_start, max(start, words[0]["t0"] - 0.02))
    if mode not in CUT and not long_gap:
        return [(q(start), q(end))]
    cuts = []
    for w1, w2 in zip(words, words[1:]):
        gap = w2["t0"] - w1["t1"]
        if mode in CUT and gap >= CUT[mode][0]:
            _, before, after = CUT[mode]
        elif long_gap and gap >= long_gap:
            _, before, after = CUT["doux"]
        else:
            continue
        g0, g1 = w1["t1"] + after, w2["t0"] - before
        if g1 - g0 < 0.25:
            continue
        if sil:  # le silence doit être réel (sinon : mot non reconnu, on ne coupe pas)
            cover = sum(max(0.0, min(g1, b) - max(g0, a)) for a, b in sil)
            if cover < 0.8 * (g1 - g0) and long_gap and gap >= long_gap and voice_free and voice_free(g0, g1):
                cuts.append((g0, g1))   # pause longue avec seulement respiration / bruit de fond (aucune voix) : coupée
                continue
            if cover < 0.8 * (g1 - g0):
                # pause de plus de 2 s avec un petit bruit (respiration, chaise…) : on ne touche JAMAIS au bruit (ce
                # pourrait être un mot non reconnu), mais on retire les parties vraiment silencieuses avant et après.
                if gap >= 2.0:
                    parts = sorted((max(g0, a), min(g1, b)) for a, b in sil if min(g1, b) - max(g0, a) >= 0.4)
                    if parts and parts[0][0] <= g0 + 0.05:                     # silence au début de la pause
                        cuts.append((g0, parts[0][1] - 0.12))
                    if parts and parts[-1][1] >= g1 - 0.05 and \
                            not (cuts and cuts[-1][0] == g0 and parts[-1] == parts[0]):   # silence à la fin
                        cuts.append((parts[-1][0] + 0.12, g1))
                    cuts[:] = [c for c in cuts if c[1] - c[0] >= 0.25]
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
    xin: float = 0.0           # fondu doux depuis le morceau précédent (silence long supprimé), en secondes
    xfrom: object = None       # morceau précédent (pour le fondu)


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


def _cut_keep(keep: list, a: float, b: float) -> list:
    """Retire [a, b] des plages gardées."""
    out = []
    for x, y in keep:
        if y <= a or x >= b:
            out.append((x, y))
            continue
        if x < a - 1 / FPS:
            out.append((x, q(a)))
        if y > b + 1 / FPS:
            out.append((q(b), y))
    return [(x, y) for x, y in out if y - x >= 2 / FPS]


def tighten_inserts(pts: list, keep: list, words: list, sil: list, voice_free=None) -> list:
    """Autour d'un extrait inséré, ta pause est ramenée à une respiration naturelle : ~0,3 s après ta phrase, puis
    l'extrait, puis ~0,25 s avant ton mot suivant. Plus jamais 2 ou 3 secondes de vide avant / après un extrait.
    Seulement si la pause ne contient aucune voix (silence confirmé par le son, ou seulement souffle / bruit)."""
    if not words:
        return keep
    for p in sorted(pts, key=lambda p: p["t"]):
        t = p["t"]
        k = next((i for i in range(len(words)) if words[i]["t1"] <= t + 1e-6 and
                  (i + 1 == len(words) or words[i + 1]["t0"] >= t - 1e-6)), None)
        if k is None:
            continue
        a = q(words[k]["t1"] + 0.30)
        last = k + 1 >= len(words)
        b = q(words[k + 1]["t0"] - 0.25) if not last else None
        if last:   # extrait après ta dernière phrase : la vidéo finit sur l'extrait
            if keep and keep[-1][1] > a:
                keep = _cut_keep(keep, a, keep[-1][1] + 1)
                p["t"] = keep[-1][1] if keep else t
            continue
        if b - a < 0.3:
            continue
        cover = sum(max(0.0, min(b, y) - max(a, x)) for x, y in (sil or []))
        if cover < 0.8 * (b - a) and not (voice_free and voice_free(a, b)):
            continue   # du son au niveau de ta voix dans la pause : on n'y touche pas
        keep = _cut_keep(keep, a, b)
        nxt = next((x for x, y in keep if x >= b - 1e-6), None)
        if nxt is not None:
            p["t"] = nxt
    return keep


def schedule(words, sents, keep, visuals, inserts, chapters, total_src, opts, orient, opener=None,
             sil=None, voice_free=None, energy=None, stats=None, outro=None, outro_dur: float = 5.5) -> tuple[list, list]:
    """visuals : [{..., "asset": panneau}], inserts : [{"after": i, "asset": extrait}].
    Retourne (segments, panneaux_retenus)."""
    if not keep:
        return [], []
    speech = sum(b - a for a, b in keep)
    # 1) points d'insertion : juste après la fin d'une phrase, dans le silence
    pts = []
    # extraits « mot-clé » (écoutez ça…) : instant déjà fixé (silence juste après ta phrase), prioritaires
    for ins in sorted([i for i in inserts if i.get("forced_t") is not None], key=lambda i: i["forced_t"]):
        t = _snap(ins["forced_t"], keep)
        if t is None or any(abs(t - p["t"]) < 1.0 for p in pts) \
                or any(w["t0"] - 0.05 < t < w["t1"] + 0.05 for w in words):
            log.warning("mot-clé : point d'insertion %.2f s refusé (sur un mot ou déjà pris)", ins["forced_t"])
            ins["refused"] = True
            continue
        pts.append({"t": t, **ins})
    def _ok_point(t):
        if t is None:
            return None
        t = _snap(t, keep)
        if t is None or any(abs(t - p["t"]) < 8 for p in pts):
            return None
        # sécurité ultime : aucun mot prononcé ne chevauche le point d'insertion
        if any(w["t0"] - 0.05 < t < w["t1"] + 0.05 for w in words):
            return None
        return t
    for ins in sorted([i for i in inserts if i.get("forced_t") is None], key=lambda i: i["after"]):
        a = ins["after"]
        t = _ok_point(find_pause(words, sents, sil or [], a))
        if t is None and ins.get("attachment"):
            # TA vidéo jointe : avant d'abandonner, silences des phrases voisines (juste avant, puis un peu plus loin)
            for alt, look in ((a - 1, 0), (a - 2, 0), (a, 6), (a - 3, 0)):
                if 0 <= alt < len(sents):
                    t = _ok_point(find_pause(words, sents, sil or [], alt, look=look))
                    if t is not None:
                        log.info("vidéo jointe : pas de silence juste après la phrase %d → placée au silence voisin "
                                 "(%.1f s)", a, t)
                        break
        if t is None and ins.get("attachment"):
            # TA vidéo jointe doit TOUJOURS paraître : le plus petit blanc entre deux mots suffit (jamais sur un mot) ;
            # l'extrait met ta vidéo en pause à cet endroit, donc ta parole n'est jamais coupée
            t = any_gap(words, sents, keep, a, [p["t"] for p in pts])
            if t is not None:
                log.info("vidéo jointe : aucun vrai silence autour de la phrase %d → placée dans le petit blanc entre "
                         "deux mots à %.2f s (ta phrase n'est pas coupée)", a, t)
        if t is None:
            log.warning("pas de vrai silence sûr autour de la phrase %d : extrait non inséré (pour ne pas te couper)", a)
            ins["refused"] = True
            continue
        pts.append({"t": t, **ins})
    # 1b) pas de vide autour des extraits : pause ramenée à une respiration avant et après
    keep = tighten_inserts(pts, keep, words, sil or [], voice_free)
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
    t_lo, t_hi = first_t + 4.0, last_t - (7.0 if opts.get("fin") == "oui" else 1.0)

    def fit(st, en, gap=2.2, dmin=3.0):
        """Fenêtre [st, en] ajustée (chapitres, extraits, autres médias) ou None si elle ne tient pas."""
        if st < t_lo or en > t_hi:
            return None
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
        if en - st < dmin or en > t_hi:
            return None
        if any(not (en + gap <= o["st"] or st >= o["en"] + gap) for o in chosen):
            return None
        return st, en

    def shifts(mine):
        # tes photos : la place libre la plus proche, avant ou après (jusqu'à 2 min) ; médias automatiques : un peu
        # plus tard seulement (toujours dans le même sujet)
        if mine:
            for d in (3, 6, 10, 15, 20, 30, 45, 60, 90, 120):
                yield d
                yield -d
        else:
            yield from (3, 6, 10, 15)

    for c in cands:
        st, en = c["st"], c["en"]
        mine = c["v"]["kind"] == "attachment"
        w = fit(st, en)
        if w is None:
            dur = max(4.0, en - st)
            for d in shifts(mine):
                w = fit(st + d, st + d + dur)
                if w is not None:
                    break
        if w is None and mine:   # dernier recours pour TA photo : écart réduit entre deux médias, 2,5 s à l'écran
            for d in (0,) + tuple(x for d_ in (3, 6, 10, 15, 20, 30, 45, 60, 90, 120) for x in (d_, -d_)):
                w = fit(st + d, st + d + 4.0, gap=0.4, dmin=2.5)
                if w is not None:
                    break
        if w is None:
            if mine:
                log.warning("ta photo %s : aucune place à l'écran sur toute la vidéo", c["v"].get("attachment"))
            continue
        st, en = w
        if not mine and cover + (en - st) > 0.6 * speech:
            continue
        if abs(st - c["st"]) > 0.5:
            c["v"]["moved"] = round(st - c["st"], 1)
        chosen.append({"v": c["v"], "st": q(st), "en": q(en)})
        cover += en - st
    # carte de fin : toi dans ton cadre + « merci / abonnez-vous » et le logo dans la carte à côté (jamais sur ton
    # visage) pendant tes dernières secondes ; elle a priorité sur tout autre média à cet endroit
    if outro is not None:
        en = last_t
        for p in pts:   # extrait tout à la fin : la carte se place juste avant
            if en - outro_dur - 1.0 < p["t"] < en + 0.6:
                en = min(en, p["t"] - 0.6)
        st = max(first_t + 4.0, en - outro_dur)
        if en - st >= 3.0:
            chosen = [c for c in chosen if c["en"] + 1.0 <= st]
            chosen.append({"v": outro, "st": q(st), "en": q(en)})
            outro["placed"] = True
    chosen.sort(key=lambda c: c["st"])
    for i, c in enumerate(chosen):
        c["side"] = "left" if i % 2 == 0 else "right"
    # extrait inséré après ta dernière phrase : la vidéo se termine sur l'extrait (pas de retour muet de 1 s)
    if pts and words and max(p["t"] for p in pts) >= words[-1]["t1"]:
        tend = max(p["t"] for p in pts)
        keep = [(a, min(b, tend)) for a, b in keep if a < tend - 1e-6]
    # point d'insertion à moins de 2 images d'une coupe : calé exactement sur la coupe (sinon il ne pourrait pas être
    # placé et l'extrait serait perdu)
    for p in pts:
        for i, (a, b) in enumerate(keep):
            if a - 1e-6 <= p["t"] <= b + 1e-6:
                if p["t"] - a < 2 / FPS:
                    p["t"] = a
                elif b - p["t"] < 2 / FPS and i + 1 < len(keep):
                    p["t"] = keep[i + 1][0]
                break
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
        else:
            log.warning("extrait prévu à %.2f s non placé (aucune frontière à cet instant)", t)
    # 5) zooms de relance dans les plans pleins : changement à chaque coupe et toutes les ~7 s
    zs = _zooms(segs, sents, orient, energy)
    if stats is not None:
        stats.update(zs)
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


def any_gap(words: list, sents: list, keep: list, after: int, taken: list, look_back: int = 3,
            look_ahead: int = 6) -> float | None:
    """Dernier recours pour TA vidéo jointe : le blanc entre deux mots le plus adapté autour de la phrase « after »,
    même tout petit (l'extrait met ta vidéo en pause : rien n'est coupé). Priorité : fin de phrase, puis le blanc le
    plus long, puis le plus proche. Jamais sur un mot, jamais à moins de 3 s d'un autre extrait."""
    if not words or not sents or not keep:
        return None
    after = max(0, min(after, len(sents) - 1))
    k0 = sents[max(0, after - look_back)]["w0"]
    k1 = sents[min(len(sents) - 1, after + look_ahead)]["w1"]
    target = sents[after]["t1"]
    best = None
    for k in range(max(0, k0), min(k1, len(words) - 2) + 1):
        a, b = words[k]["t1"], words[k + 1]["t0"]
        if b - a < 0.02:           # mots collés : on ne s'y glisse pas
            continue
        t = None
        for c in (q((a + b) / 2), math.ceil(a * FPS - 1e-6) / FPS, math.floor(b * FPS + 1e-6) / FPS):
            c = _snap(round(c, 6), keep)                 # instant pile sur une image, entre les deux mots
            if c is not None and a - 1e-6 <= c <= b + 1e-6:
                t = c
                break
        if t is None:
            continue
        if any(w["t0"] < t < w["t1"] for w in words) or any(abs(t - x) < 3.0 for x in taken):
            continue
        end_sentence = bool(re.search(r"[.!?…؟,;:]['\"»”)]*$", words[k]["w"]))
        key = (0 if end_sentence else 1, -round(b - a, 2), abs(t - target))
        if best is None or key < best[0]:
            best = (key, t)
    return best[1] if best else None


def _snap(t: float, keep: list) -> float | None:
    for i, (a, b) in enumerate(keep):
        if a <= t <= b:
            if t > b - 2 / FPS and i + 1 < len(keep):  # pile sur une coupe : début de la plage suivante (toujours un silence)
                return keep[i + 1][0]
            return t
        if t < a:  # dans un silence coupé : on prend le point de coupe
            return a
    return None


def _zooms(segs, sents, orient, energy=None):
    """Plans (zooms) des passages plein cadre. Sans analyse de la voix : alternance large / serré aux fins de phrase
    toutes les ~7 s. Avec (energy, voir voix.py) : plan serré quand le ton monte (coupe au début de la phrase), large
    quand il est posé, moyen sinon ; coupes plus fréquentes quand le débit s'accélère. Retourne des statistiques."""
    zin = 1.12 if orient == "h" else 1.08
    stats = {"serre": 0, "large": 0, "moyen": 0, "punch": 0}
    ends = [s["t1"] for s in sents]
    if energy and len(energy) != len(sents):
        energy = None
    tight = 1.18 if orient == "h" else 1.12
    mids = (1.08, 1.12) if orient == "h" else (1.05, 1.08)

    def sent_at(t):
        for k, x in enumerate(sents):
            if x["t0"] - 0.05 <= t <= x["t1"] + 0.05:
                return k
        return None
    for si, s in enumerate(segs):
        if s.kind != "full":
            continue
        new = []
        for at in s.atoms:
            cur, last = at.a, at.a
            if energy:
                cuts = []
                for k, x in enumerate(sents):
                    gap = 4.5 if energy[k]["fast"] else 6.5
                    e = x["t1"]
                    if cur + gap < e < at.b - 2.5 and e - last >= gap:
                        cuts.append(q(e + 0.1))
                        last = q(e + 0.1)
                    st = x["t0"]   # ton qui monte : coupe (plan serré) au début de la phrase
                    if energy[k]["z"] >= 1.2 and cur + 2.5 < st < at.b - 2.0 and st - last >= 2.5:
                        cuts.append(q(st - 0.05))
                        last = q(st - 0.05)
                        stats["punch"] += 1
                for t in sorted(set(cuts)):
                    if t - cur >= 1.2:
                        new.append(Atom(cur, t))
                        cur = t
            else:
                for e in ends:
                    if cur + 6.5 < e < at.b - 2.5 and e - last >= 6.5:
                        t = q(e + 0.1)
                        new.append(Atom(cur, t))
                        cur = last = t
            new.append(Atom(cur, at.b))
        s.atoms = new
        n = len(new)
        if energy:
            prev, mi = None, 0
            for at in new:
                k = sent_at(at.a + 0.2)
                z = energy[k]["z"] if k is not None else 0.0
                if z >= 1.2:
                    zz, kind = tight, "serre"
                elif z <= -0.9:
                    zz, kind = 1.0, "large"
                else:
                    zz, kind = mids[mi % 2], "moyen"
                    mi += 1
                if prev is not None and abs(zz - prev) < 0.03:   # jamais deux fois le même plan de suite
                    zz, kind = (1.0, "large") if zz > 1.0 else (mids[mi % 2], "moyen")
                at.zoom = zz
                stats[kind] += 1
                prev = zz
        else:
            for k, at in enumerate(new):
                at.zoom = zin if k % 2 == 1 else 1.0
        # bords collés à un média ou un extrait : plan large (transition propre)
        if si > 0 and segs[si - 1].kind != "full":
            new[0].zoom = 1.0
        if si + 1 < len(segs) and segs[si + 1].kind != "full" and n:
            new[-1].zoom = 1.0
            if n >= 2 and abs(new[-2].zoom - 1.0) < 0.03 and new[-1].b - new[-1].a < 2.0:
                new[-2].zoom = zin
    return stats


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
