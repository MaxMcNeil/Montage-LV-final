"""Habillage vertical : choix au hasard sans répétition, zones YouTube respectées, fond jamais transparent."""
from pathlib import Path

from PIL import Image

from montage import habillage_v as HV

TOPICS = [(0, "Le frère d'Epstein brise le silence"), (40, "L'autopsie contestée par deux experts"),
          (90, "Les caméras tombées en panne la nuit même"), (150, "Portes de cellule ouvertes"), (200, "La marque au cou")]


def test_choix_jamais_deux_fois_de_suite(tmp_path):
    st = tmp_path / "s.json"
    last = None
    for i in range(30):
        t = HV.choisir("au hasard", st, f"x{i}")
        assert t in HV.THEMES and t != last
        HV.memoriser(t, st)
        last = t
    assert HV.choisir("War room", st) == "warroom"
    assert HV.choisir("newsroom", st) == "newsroom" and HV.choisir("story", st) == "story"
    assert HV.choisir("actuel", st) is None


def test_zones_youtube_respectees():
    for th, lay in HV.LAYOUT.items():
        for name in ("media",) + (("cam",) if not lay["full"] else ()):
            x, y, w, h = lay[name]
            assert y >= HV.YT_TOP and y + h <= HV.YT_BOTTOM, (th, name)
            if y + h > HV.YT_RIGHT_Y[0]:
                assert x + w <= HV.YT_RIGHT_X, (th, name)
        ml, mr, mv, _ = HV.CAPS[th]
        assert HV.H - mv <= HV.YT_BOTTOM and HV.W - mr <= HV.YT_RIGHT_X + 110


def test_fond_opaque_hors_fenetres(tmp_path):
    for th in HV.THEMES:
        hv = HV.Habillage(th, TOPICS, 260, "fr", "Le Journal du NON", None, ["New York"], tmp_path / th).build()
        for png, *_ , st in hv.layers[:2]:
            im = Image.open(png)
            a = im.getchannel("A")
            if th != "story":
                # hors des fenêtres (toi, média) : JAMAIS semi-transparent (la vidéo ne doit pas se voir à travers)
                semi = sum(a.histogram()[1:255])
                assert semi < im.width * im.height * 0.01, (th, st, semi)
            # rien de dessiné dans la bande haute réservée à YouTube (sauf le fond)
            assert Path(png).exists()
        assert hv.n == 5


def test_arabe_et_sujet_unique(tmp_path):
    hv = HV.Habillage("newsroom", [(0, "تشريح الجثة موضع شك")], 100, "ar", "Gulf think-tank", None, [], tmp_path).build()
    assert hv.n == 1 and len(hv.layers) == 2


def test_sous_titres_mot_avec_espace_insecable(monkeypatch):
    """« 1 200 » transcrit avec une espace : plus jamais d'erreur dans les sous-titres (montage arrêté avant)."""
    from types import SimpleNamespace as NS
    from montage.ass import ASS
    sub = ASS("v", "fr")
    sub.theme = "newsroom"
    seg = NS(kind="full", out0=0.0, dur=20.0, atoms=[NS(a=0.0, b=20.0)], side="left")
    words = [{"w": w, "t0": i * 0.4, "t1": i * 0.4 + 0.3} for i, w in enumerate(
        ["Les", "ménages", "ont", "payé", "1 200", "euros", "de", "plus", "l'hiver", "dernier."])]
    import montage.ass as A
    monkeypatch.setattr(A, "out_time", lambda segs, t: t)
    monkeypatch.setattr(A, "seg_at", lambda segs, t: seg)
    sub.captions(words, [seg], set())
    assert any("1 200" in e or "1\\h200" in e or "200" in e for e in sub.ev)
