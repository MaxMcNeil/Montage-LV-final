"""Format de sortie : auto (= ta vidéo), horizontal ou vertical forcés ; vertical → horizontal sans recadrage flou."""
from montage.__main__ import options
from montage.render import Ctx


def test_format_options(monkeypatch, tmp_path):
    for env, want in (("", "auto"), ("auto", "auto"), ("horizontal", "h"), ("vertical", "v"), ("Portrait", "v"),
                      ("16:9", "h"), ("n'importe", "auto")):
        monkeypatch.setenv("MONTAGE_FORMAT", env)
        assert options(None)["format"] == want, env


def test_vertical_en_horizontal(tmp_path):
    c = Ctx(tmp_path / "v.mp4", {"w": 1080, "h": 1920}, {"cx": 0.5, "cy": 0.35}, "h", tmp_path, None, None)
    assert c.pillar
    a, b = c.full_chain(1.0), c.full_chain(1.1)
    assert "overlay" in a and "[pa1]" in a and "[pa2]" in b          # étiquettes uniques à chaque appel
    crop = c.card_crop(760, 888)                                     # le cadre ne prend que ta vidéo, pas le fond flou
    w, h, x, y = map(int, crop.split(",")[0][5:].split(":"))
    fw, _, x0 = c._pillar_geom()
    assert x0 <= x and x + w <= x0 + fw


def test_horizontal_inchange(tmp_path):
    c = Ctx(tmp_path / "h.mp4", {"w": 1920, "h": 1080}, {"cx": 0.5, "cy": 0.4}, "v", tmp_path, None, None)
    assert not c.pillar and c.full_chain(1.0).startswith("scale=")
    c = Ctx(tmp_path / "h.mp4", {"w": 1920, "h": 1080}, {"cx": 0.5, "cy": 0.4}, "h", tmp_path, None, None)
    assert not c.pillar
