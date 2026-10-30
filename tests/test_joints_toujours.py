"""Tes pièces jointes paraissent TOUJOURS : photo déplacée vers la place libre la plus proche, vidéo glissée dans le
plus petit blanc entre deux mots (jamais sur un mot)."""
from montage.timeline import schedule


def build(n=30, gap=0.05):
    words, sents, t = [], [], 0.0
    for i in range(n):
        w0 = len(words)
        for k in range(8):
            words.append({"t0": round(t, 3), "t1": round(t + 0.45, 3), "w": f"m{i}{k}" + ("." if k == 7 else "")})
            t += 0.45 + gap
        sents.append({"i": i, "w0": w0, "w1": len(words) - 1, "t0": words[w0]["t0"], "t1": words[-1]["t1"],
                      "text": f"phrase {i}"})
    return words, sents


def test_video_without_any_silence_still_inserted_between_words():
    words, sents = build(gap=0.06)                 # on enchaîne tout, aucun silence nulle part
    keep = [(0.0, sents[-1]["t1"] + 0.5)]
    asset = {"duration": 5.0, "video": "x.mp4"}
    segs, _ = schedule(words, sents, keep, [], [{"after": 10, "asset": asset, "attachment": "a1"}], [], 200.0,
                       {"fin": "non"}, "h", sil=[])
    ins = [s for s in segs if s.kind == "insert"]
    assert len(ins) == 1
    t = ins[0].insert["t"]
    assert not any(w["t0"] < t < w["t1"] for w in words)          # jamais sur un mot
    k = next(i for i, w in enumerate(words) if w["t1"] <= t <= words[i + 1]["t0"])
    assert words[k]["w"].endswith(".")                              # de préférence en fin de phrase
    # extrait qui n'est PAS à toi : jamais forcé
    segs2, _ = schedule(words, sents, keep, [], [{"after": 10, "asset": asset}], [], 200.0, {"fin": "non"}, "h", sil=[])
    assert not [s for s in segs2 if s.kind == "insert"]


def test_photos_all_placed_even_on_same_moment_chapter_and_insert():
    words, sents = build(n=40)
    keep = [(0.0, sents[-1]["t1"] + 0.5)]
    vis = [{"kind": "attachment", "attachment": f"p{k}", "s0": 12, "s1": 12, "trigger": "", "priority": 1,
            "asset": {"frame": "x"}} for k in range(4)]                   # 4 photos annoncées sur la même phrase
    vis += [{"kind": "article", "s0": 12, "s1": 12, "trigger": "", "priority": 1, "asset": {"frame": "a"}}]
    chapters = [{"s": 12, "title": "Chapitre"}]
    ins = [{"after": 12, "asset": {"duration": 5.0, "video": "x.mp4"}, "attachment": "v1"}]
    segs, chosen = schedule(words, sents, keep, vis, ins, chapters, 200.0, {"fin": "oui"}, "v", sil=[])
    got = {c["v"].get("attachment") for c in chosen}
    assert {"p0", "p1", "p2", "p3"} <= got
    for a in chosen:
        for b in chosen:
            if a is not b:
                assert a["en"] <= b["st"] or b["en"] <= a["st"]      # jamais deux médias en même temps
    pt = next(s for s in segs if s.kind == "insert").insert["t"]
    assert all(not (c["st"] - 1.0 < pt < c["en"] + 0.6) for c in chosen)


def test_photo_at_very_start_moves_after_intro():
    words, sents = build(n=20)
    keep = [(0.0, sents[-1]["t1"] + 0.5)]
    vis = [{"kind": "attachment", "attachment": "p0", "s0": 0, "s1": 0, "trigger": "", "priority": 1,
            "asset": {"frame": "x"}}]
    _, chosen = schedule(words, sents, keep, vis, [], [], 100.0, {"fin": "non"}, "h", sil=[])
    assert [c["v"]["attachment"] for c in chosen] == ["p0"] and chosen[0]["st"] >= 4.0
