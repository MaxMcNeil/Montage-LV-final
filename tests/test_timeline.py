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
    # le son ne confirme qu'une partie de la pause de 3 s : seul le début VRAIMENT silencieux est retiré,
    # le reste (bruit, peut-être un mot non reconnu) est gardé intact ; les autres pauses ne sont pas touchées
    k1 = keep_ranges(W, [(5, 6)], 33, "doux")
    assert len(k1) == 2
    assert k1[1][0] <= 6.0 - 0.1 + 1e-6 and k1[0][1] <= 5.0 + 0.4
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


def test_insert_never_cuts_speech():
    from montage.timeline import find_pause
    # phrase 0 finie mais la suivante enchaîne sans pause (0,1 s) : l'extrait attend la vraie pause suivante
    w = _words([(0.0, 4.0, "Première phrase ici."), (4.1, 8.0, "Je continue sans respirer."), (9.0, 12.0, "Nouvelle idée.")])
    s = sentences(w)
    sil = [(8.05, 8.95)]
    t = find_pause(w, s, sil, 0)
    assert t is not None and 8.0 < t < 9.0
    assert not any(x["t0"] - 0.05 < t < x["t1"] + 0.05 for x in w)
    # aucun silence confirmé par le son : pas d'insertion du tout
    assert find_pause(w, s, [(20, 21)], 0) is None


def test_long_silences_cut_even_without_silence_mode():
    k = keep_ranges(W, SIL, 33, "non", long_gap=2.0)
    # pauses : 3 s (5→8) et 2 s (20→22) raccourcies ; 1 s (13→14) gardée
    assert len(k) == 3
    removed = 33 - sum(b - a for a, b in k)
    assert removed > 3.0
    assert len(keep_ranges(W, SIL, 33, "non")) == 1          # option désactivée : comportement d'avant


def test_quiet_detection_and_word_repair(tmp_path):
    import subprocess
    from montage.pauses import quiet_intervals, repair_words
    # voix (sinus fort) 0-2 s, bruit de pièce (-34 dB, non détecté par un seuil fixe) 2-5 s, voix 5-7 s
    f = tmp_path / "a.wav"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "aevalsrc='if(lt(t,2)+gt(t,5),0.5*sin(2*PI*220*t),0.02*(random(0)-0.5))':s=16000:d=7", str(f)],
                   check=True)
    q_ = quiet_intervals(f, tmp_path)
    assert any(a < 2.2 and b > 4.8 for a, b in q_)
    w = [{"t0": 1.0, "t1": 4.6, "w": "mot"}, {"t0": 5.0, "t1": 5.5, "w": "suite"}]   # mot « étiré » sur la pause
    assert repair_words(w, q_) == 1 and w[0]["t1"] < 2.4


def test_phantom_words_dropped_only_in_silence():
    from montage.pauses import drop_phantoms
    w = [{"t0": 0.0, "t1": 0.4, "w": "Bonjour"}, {"t0": 0.5, "t1": 0.9, "w": "à"}, {"t0": 1.0, "t1": 1.4, "w": "tous."},
         {"t0": 3.0, "t1": 3.4, "w": "Sous-titres"}, {"t0": 3.5, "t1": 3.9, "w": "par"}, {"t0": 4.0, "t1": 4.4, "w": "Amara.org"},
         {"t0": 6.0, "t1": 6.3, "w": "euh"}, {"t0": 8.0, "t1": 8.4, "w": "Suite."}]
    quiet = [(1.6, 4.8), (5.8, 6.5)]
    assert drop_phantoms(w, quiet) == 3
    assert [x["w"] for x in w] == ["Bonjour", "à", "tous.", "euh", "Suite."]   # un mot isolé calme est gardé


def test_long_pause_with_noise_keeps_the_noise():
    """Pause de 4 s : silence 1,5 s, bruit 1 s (respiration ?), silence 1,5 s → les deux silences sont retirés, le bruit
    reste entier (jamais coupé)."""
    w = _words([(0.0, 4.0, "Voici le prix du poulet."), (8.0, 12.0, "Vingt-sept euros pour un poulet.")])
    gap0, gap1 = w[4]["t1"], 8.0
    sil = [(gap0, gap0 + 1.5), (gap1 - 1.5, gap1)]
    k = keep_ranges(w, sil, 12.5, "non", long_gap=2.0)
    assert len(k) == 3                                      # avant la pause / le bruit seul / après la pause
    kept_gap = sum(min(b, gap1) - max(a, gap0) for a, b in k if min(b, gap1) > max(a, gap0))
    assert kept_gap < 2.0                                   # la pause gardée passe sous les 2 s
    noise = (gap0 + 1.5, gap1 - 1.5)
    assert any(a <= noise[0] and b >= noise[1] for a, b in k)   # le bruit est gardé en entier


def test_no_blank_around_inserts():
    from montage.timeline import tighten_inserts
    w = _words([(0.0, 4.0, "Première phrase ici."), (7.0, 10.0, "Suite de la vidéo.")])   # pause de 3 s
    keep = [(0.0, 10.5)]
    pts = [{"t": 5.5}]
    # pause avec seulement du souffle : silence non confirmé, mais aucune voix → resserrée
    k2 = tighten_inserts(pts, list(keep), w, [], voice_free=lambda a, b: True)
    gap = [(a, b) for a, b in zip([x[1] for x in k2], [x[0] for x in k2[1:]])]
    assert gap and 2.0 < gap[0][1] - gap[0][0] < 3.0 and abs(pts[0]["t"] - k2[1][0]) < 1e-6
    # voix possible dans la pause : on n'y touche pas
    pts2 = [{"t": 5.5}]
    assert tighten_inserts(pts2, list(keep), w, [], voice_free=lambda a, b: False) == keep and pts2[0]["t"] == 5.5
