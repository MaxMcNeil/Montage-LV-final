"""Décor (chaîne fond vert) : jamais appliqué si le fond reçu n'est pas celui de ta vidéo."""
import subprocess

from montage.decor import build


def test_fond_different_refuse(tmp_path):
    v = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=6", "-pix_fmt",
                    "yuv420p", str(v)], check=True)
    bg = tmp_path / "bg.jpg"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x224466:s=640x360", "-frames:v", "1",
                    str(bg)], check=True)
    d, note = build(bg, "chaines/fr/logo.png", v, {"w": 640, "h": 360, "duration": 6.0}, {"cx": 0.5}, tmp_path)
    assert d is None and "non reconnu" in note


def test_sans_fond(tmp_path):
    d, note = build(tmp_path / "absent.jpg", "chaines/fr/logo.png", tmp_path / "v.mp4", {"w": 640, "h": 360,
                                                                                         "duration": 6.0}, {}, tmp_path)
    assert d is None
