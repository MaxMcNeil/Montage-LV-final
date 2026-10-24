"""Tests rapides (sans réseau ni IA) : python -m pytest -q"""
from montage.assets import choose_bounds
from montage.config import FPS
from montage.timeline import keep_ranges, out_time, schedule
from montage.transcribe import sentences


def _words(spans):
    out = []
    for a, b, text in spans:
        ws = text.split()
        st = (b - a) / len(ws)
        out += [{"t0": a + i * st, "t1": a + (i + 0.85) * st, "w": w} for i, w in enumerate(ws)]
    return out


W = _words([(0.5, 5, "Bonjour à tous, on parle de la Suisse."), (8, 13, "Le ministre annonce 54 000 postes."),
            (14, 20, "Une décision historique pour la souveraineté."), (22, 30, "Écoutez maintenant ce discours du ministre.")])
SIL = [(0, 0.5), (5, 8), (13, 14), (20, 22), (30, 33)]


def test_keep_ranges_cuts_only_real_silences():
    k = keep_ranges(W, SIL, 33, "doux")
    assert len(k) == 4                       # 4 pauses > 1 s raccourcies
    assert len(keep_ranges(W, [], 33, "doux")) == 4
    assert len(keep_ranges(W, [(5, 6)], 33, "doux")) == 1   # le son ne confirme pas les silences : on ne coupe pas
    assert all(abs(round(x * FPS) - x * FPS) < 1e-3 for r in k for x in r)
    assert keep_ranges(W, SIL, 33, "non")[0][0] < 0.5


def test_sentences():
    s = sentences(W)
    assert [x["text"][-1] for x in s] == ["."] * 4


def test_choose_bounds_never_cuts_a_sentence():
    ss = [{"t0": 0, "t1": 6}, {"t0": 6.2, "t1": 14}, {"t0": 14.3, "t1": 30}]
    a, b = choose_bounds(ss, 0, 30, 15, 30)
    assert a == 0 and abs(b - 14.35) < 1e-6


def test_schedule_insert_in_silence_and_panel():
    s = sentences(W)
    keep = keep_ranges(W, SIL, 33, "doux")
    vis = [{"kind": "figure", "s0": 1, "s1": 1, "trigger": "54", "priority": 1, "asset": {"frame": "x"}}]
    ins = [{"after": 3, "asset": {"duration": 6.0}}]
    segs, chosen = schedule(W, s, keep, vis, ins, [], 33, {"fin": "non"}, "h")
    kinds = [x.kind for x in segs]
    assert "split" in kinds and kinds[-1] == "insert"
    total = sum(x.n for x in segs) / FPS
    assert sum(b - a for a, b in keep) + 6.0 - 1.0 < total <= sum(b - a for a, b in keep) + 6.0 + 0.05  # silence final retiré
    t54 = next(w for w in W if w["w"] == "54")["t0"]
    split = next(x for x in segs if x.kind == "split")
    assert abs(split.out0 - out_time(segs, t54 - 0.12)) < 0.1   # le chiffre apparaît quand il est prononcé
