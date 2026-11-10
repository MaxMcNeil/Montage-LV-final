"""Défauts vus le 10/11 : titre sur la bouche, page « blocked » affichée, carte-titre de chaîne au début d'un extrait."""
import shutil
import subprocess
from pathlib import Path

import pytest

from montage.ass import ASS
from montage.render import face_in_output

HERE = Path(__file__).resolve().parent


@pytest.mark.parametrize("face,info,o,caps", [
    ({"cy": 0.41, "fh": 0.13}, {"w": 1080, "h": 1920}, "h", True),    # ta vidéo verticale montée en horizontal
    ({"cy": 0.41, "fh": 0.13}, {"w": 1080, "h": 1920}, "h", False),
    ({"cy": 0.40, "fh": 0.30}, {"w": 1920, "h": 1080}, "h", False),   # gros plan horizontal
    ({"cy": 0.40, "fh": 0.30}, {"w": 1920, "h": 1080}, "v", False),
    ({"cy": 0.38, "fh": 0.14}, {"w": 1080, "h": 1920}, "v", True)])
def test_titre_jamais_sur_la_bouche(face, info, o, caps):
    f = face_in_output(face, info, o)
    a = ASS(o, "fr", f)
    a.no_caps = not caps
    for half in (100, 149, 200):
        y = a.text_band_y(half)
        mouth, chin = (f["cy"] + 0.15 * f["fh"]) * a.H, (f["cy"] + 0.8 * f["fh"]) * a.H
        assert y + half < mouth or y - half > chin


def test_page_bloquee_jamais_montee():
    if not shutil.which("tesseract"):
        pytest.skip("tesseract absent")
    from montage.assets import error_page
    assert error_page(str(HERE / "data_capture_bloquee.png"))


def test_carte_titre_sautee(tmp_path):
    from montage.assets import static_edges
    v = tmp_path / "c.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x334455:s=320x180:d=5",
                    "-f", "lavfi", "-i", "testsrc2=s=320x180:d=20", "-filter_complex",
                    "[0][1]concat=n=2:v=1:a=0,format=yuv420p", str(v)], check=True)
    head, tail = static_edges(str(v), 25.0)
    assert 4.5 < head < 6.0 and tail == 25.0


@pytest.mark.parametrize("img,refus", [("data_cookies_publicsenat.png", True), ("data_cookies_euronews.png", True),
                                       ("data_capture_bloquee.png", True), ("data_article_sur_cookies.png", False)])
def test_captures_cookies_ou_erreur(img, refus):
    if not shutil.which("tesseract"):
        pytest.skip("tesseract absent")
    from montage.assets import error_page
    assert bool(error_page(str(HERE / img))) is refus


def test_meme_regle_dans_preparer_les_medias():
    if not shutil.which("tesseract"):
        pytest.skip("tesseract absent")
    root = HERE.parent
    for img, refus in (("data_cookies_publicsenat.png", True), ("data_cookies_euronews.png", True),
                       ("data_article_sur_cookies.png", False)):
        r = subprocess.run(["bash", "-c", f"source <(sed -n '/^page_erreur()/,/^}}/p' {root}/scripts/recup_medias.sh); "
                           f"page_erreur {HERE / img}"])
        assert (r.returncode == 0) is refus, img
