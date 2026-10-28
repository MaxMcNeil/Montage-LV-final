"""Vidéo jointe : pas de silence juste après la phrase prévue → silence d'une phrase voisine (jamais sur un mot)."""
from montage.timeline import schedule


def build():
    # phrases de 4 s ; vrai silence (1,5 s) seulement après la phrase 3 ; partout ailleurs, on enchaîne sans pause
    words, sents, t = [], [], 0.0
    for i in range(10):
        w0 = len(words)
        for k in range(8):
            words.append({"t0": round(t, 2), "t1": round(t + 0.45, 2), "w": f"m{i}{k}" + ("." if k == 7 else "")})
            t += 0.5
        sents.append({"i": i, "w0": w0, "w1": len(words) - 1, "t0": words[w0]["t0"], "t1": words[-1]["t1"],
                      "text": f"phrase {i}"})
        t += 1.5 if i == 3 else 0.05
    sil = [(sents[3]["t1"] + 0.05, sents[4]["t0"] - 0.05)]
    return words, sents, sil


def test_neighbor_silence_for_attachment_only():
    words, sents, sil = build()
    keep = [(0.0, sents[-1]["t1"] + 0.5)]
    asset = {"duration": 5.0, "video": "x.mp4"}
    opts = {"fin": "non"}
    segs, _ = schedule(words, sents, keep, [], [{"after": 5, "asset": asset, "attachment": "a1"}], [], 60.0, opts, "h",
                       sil=sil)
    ins = [s for s in segs if s.kind == "insert"]
    assert len(ins) == 1                                     # placée au silence de la phrase 3 (voisine)
    t = ins[0].insert["t"]
    assert sents[3]["t1"] < t < sents[4]["t0"]
    assert not any(w["t0"] - 0.05 < t < w["t1"] + 0.05 for w in words)
    # extrait de presse (pas une pièce jointe) : pas de repli, on ne force jamais
    segs2, _ = schedule(words, sents, keep, [], [{"after": 6, "asset": asset}], [], 60.0, opts, "h", sil=sil)
    assert not [s for s in segs2 if s.kind == "insert"]
