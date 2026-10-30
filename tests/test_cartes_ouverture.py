"""Nappe discrète sous les cartes ; ouverture choc jamais en plein écran (toi visible à côté)."""
import shutil
import subprocess
from types import SimpleNamespace as NS

import numpy as np
import pytest

from montage import render as R


def test_bed_is_quiet_and_soft_edges():
    b = R.sfx_bed(6.0, 0)
    assert b.shape == (int(6.0 * 48000), 2)
    rms = 20 * np.log10(np.sqrt((b[48000:-48000] ** 2).mean()))
    assert -46 < rms < -36                                   # discrète : ~20 dB sous la voix
    assert np.abs(b[:200]).max() < 1e-3 and np.abs(b[-200:]).max() < 1e-3   # ni clic d'entrée ni de sortie
    assert R.sfx_bed(0.2, 1).shape[0] == int(0.2 * 48000)  # très court : pas d'erreur


def test_card_spans_groups_same_card():
    p1, p2 = object(), object()
    S = lambda k, o, d, p=None: NS(kind=k, out0=o, dur=d, panel=p)   # noqa: E731
    segs = [S("full", 0, 5), S("split", 5, 2, p1), S("split", 7, 3, p1), S("full", 10, 4), S("insert", 14, 6),
            S("split", 20, 0.5, p2), S("full", 20.5, 9.5), S("split", 30, 5, p2)]
    assert R.card_spans(segs) == [(5, 10), (30, 35)]           # trop court (< 1 s) ignoré


pytestmark_ff = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg absent")


@pytestmark_ff
@pytest.mark.parametrize("o", ["h", "v"])
def test_opener_never_full_screen(tmp_path, o):
    from montage.config import SIZE
    from montage.timeline import Segment
    from montage.util import probe
    W, H = SIZE[o]
    src, clip = tmp_path / "src.mp4", tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x204080:s=1280x720:r=30:d=3",
                    "-pix_fmt", "yuv420p", src], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=red:s={W}x{H}:r=30:d=2",
                    "-pix_fmt", "yuv420p", clip], check=True)
    ctx = R.Ctx(src, probe(src), {"cx": 0.5, "cy": 0.4}, o, tmp_path, None, None)
    seg = Segment("insert", insert={"asset": {"video": str(clip), "duration": 2.0}, "opener": True, "t": 0.5},
                  n=60, out0=0.0)
    R.OPENER_NOTES.clear()
    out = tmp_path / "op.mp4"
    R.render_insert(seg, ctx, out, 0.5, 0.5, 0)
    assert "jamais en plein écran" in R.OPENER_NOTES[-1]
    fr = subprocess.run(["ffmpeg", "-v", "error", "-ss", "1", "-i", out, "-frames:v", "1", "-f", "rawvideo",
                         "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    img = np.frombuffer(fr, np.uint8).reshape(H, W, 3).astype(int)
    red = (img[..., 0] > 180) & (img[..., 1] < 80) & (img[..., 2] < 80)
    assert 0.08 < red.mean() < 0.6                             # l'extrait est là, mais loin du plein écran
    blue = (img[..., 2] > img[..., 0] + 30)
    assert blue.mean() > 0.15                                  # toi (ton image) bien visible à côté
