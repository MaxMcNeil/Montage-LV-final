"""Pendant un extrait tu « écoutes » (vrai silence, jamais figé) ; jamais de générique / jingle en extrait."""
from montage.assets import choose_bounds
from montage.render import Ctx, listen_clip


def test_choose_bounds_saute_le_jingle():
    sents = [{"t0": 0.5, "t1": 2.0, "text": "Top Tendance"},
             {"t0": 4.0, "t1": 9.0, "text": "Le président a annoncé ce matin un plan"},
             {"t0": 9.5, "t1": 14.0, "text": "qui prévoit des économies importantes cette année"}]
    a, b = choose_bounds(sents, 0.0, 30.0, 20.0, 40.0)
    assert a >= 3.5 and b > 9


def test_listen_sans_silence(tmp_path):
    c = Ctx(tmp_path / "v.mp4", {"w": 1920, "h": 1080, "quiet": [(1.0, 1.4)]}, {"cx": .5, "cy": .4}, "h", tmp_path,
            None, None)
    assert listen_clip(c, 5.0, tmp_path / "l.mp4") is None    # silence trop court → repli image fixe (comme avant)
