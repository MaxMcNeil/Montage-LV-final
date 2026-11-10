"""Deux vidéos jointes prévues après la même phrase : les DEUX paraissent (jamais une perdue sans bruit)."""
from montage.timeline import schedule


def test_deux_extraits_meme_phrase():
    sents, words = [], []
    for i in range(12):
        t0 = 1.0 + i * 5.0
        w0 = len(words)
        words += [{"w": f"m{i}{k}" + ("." if k == 5 else ""), "t0": t0 + k * 0.6, "t1": t0 + k * 0.6 + 0.5}
                  for k in range(6)]
        sents.append({"i": i, "t0": t0, "t1": words[-1]["t1"], "w0": w0, "w1": len(words) - 1,
                      "text": f"phrase {i} assez longue pour le test"})
    keep = [(0.0, 62.0)]
    asset = {"video": "x.mp4", "duration": 4.0, "frames": 120}
    ins = [{"attachment": "a", "after": 5, "asset": dict(asset)}, {"attachment": "b", "after": 5, "asset": dict(asset)}]
    segs, _ = schedule(words, sents, keep, [], ins, [], 62.0, {"fin": "non", "couper_silences": "non"}, "h",
                       sil=[(s["t1"], s["t1"] + 1.2) for s in sents])
    got = {s.insert.get("attachment") for s in segs if s.kind == "insert"}
    assert got == {"a", "b"}
