"""Voix studio : améliore sans jamais casser — repli sur la voix normale au moindre doute."""
import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest

from montage import voix_studio as V
from montage.render import extract_main_audio

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg absent")


def _wav(p: Path, sig: np.ndarray, sr=48000):
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(sig, -1, 1) * 32767).astype(np.int16).tobytes())


def _speechlike(sec=12, noise=0.01, sr=48000, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(int(sec * sr)) / sr
    env = (np.sin(2 * np.pi * 0.7 * t) > 0).astype(float)          # « phrases » et silences
    voice = env * 0.3 * (np.sin(2 * np.pi * 180 * t) + 0.5 * np.sin(2 * np.pi * 360 * t) + 0.2 * np.sin(2 * np.pi * 3200 * t))
    return voice + noise * rng.standard_normal(len(t))


def test_chain_choices():
    assert "afftdn" not in V.chain(-90, -20)[0]                      # pièce silencieuse : pas de débruitage
    af, dn = V.chain(-50, -22)
    assert "afftdn=nr=12" in af and "agate" in af and "moyen" in dn and "f=130" in af
    assert "afftdn=nr=8" in V.chain(-60, -22)[0]
    assert "afftdn=nr=8" in V.chain(None, None)[0]
    assert "loudnorm" not in V.chain(-50, -22)[0]                    # volume réglé à part (2 passes)


@pytest.mark.parametrize("noise", [0.0005, 0.01, 0.05])
def test_apply_keeps_length_and_no_clipping(tmp_path, noise):
    src = tmp_path / "moi.wav"
    _wav(src, _speechlike(noise=noise))
    normal = extract_main_audio(src, {"audio": True}, tmp_path / "main.wav")
    out, note = V.apply(src, normal, tmp_path)
    assert out.name == "main_studio.wav", note
    with wave.open(str(normal)) as a, wave.open(str(out)) as b:
        assert a.getnframes() == b.getnframes() and b.getnchannels() == 2
    pk, _ = V._levels(out)
    assert pk <= -0.5


def test_broken_source_falls_back(tmp_path):
    src = tmp_path / "moi.wav"
    _wav(src, _speechlike())
    normal = extract_main_audio(src, {"audio": True}, tmp_path / "main.wav")
    bad = tmp_path / "abime.mp4"
    bad.write_bytes(b"pas une video")
    out, note = V.apply(bad, normal, tmp_path)
    assert out == normal and note.startswith("⚠")


def test_length_mismatch_falls_back(tmp_path, monkeypatch):
    src = tmp_path / "moi.wav"
    _wav(src, _speechlike())
    normal = tmp_path / "main.wav"
    _wav(normal, np.zeros(48000 * 3))                                 # 3 s au lieu de 12 : écart énorme
    out, note = V.apply(src, normal, tmp_path)
    assert out == normal and "durée" in note


def test_near_silent_source_falls_back_or_stays_sane(tmp_path):
    src = tmp_path / "moi.wav"
    _wav(src, 0.0002 * np.random.default_rng(1).standard_normal(48000 * 8))   # que du souffle
    normal = extract_main_audio(src, {"audio": True}, tmp_path / "main.wav")
    out, note = V.apply(src, normal, tmp_path)
    pk, _ = V._levels(out)
    assert pk <= -0.5


def _band_db(x, sr, lo, hi):
    F = np.abs(np.fft.rfft(x)) ** 2
    f = np.fft.rfftfreq(len(x), 1 / sr)
    return 10 * np.log10(F[(f >= lo) & (f < hi)].sum() + 1e-12)


def test_deess_cuts_sibilance_only():
    sr = 48000
    rng = np.random.default_rng(3)
    t = np.arange(sr * 2) / sr
    voice = 0.3 * np.sin(2 * np.pi * 200 * t)
    hiss = np.zeros_like(t)
    hiss[sr // 2: sr] = 0.4 * np.convolve(rng.standard_normal(sr // 2), [1, -1], "same")   # un « s » appuyé
    x = (voice + hiss).astype(np.float32)
    y = V.deess(x, sr)
    assert y.shape == x.shape
    s0, s1 = _band_db(x[sr // 2: sr], sr, 4500, 12000), _band_db(y[sr // 2: sr], sr, 4500, 12000)
    assert s0 - s1 > 4                                                # le « s » est nettement adouci
    v0, v1 = _band_db(x[sr + 4800:], sr, 100, 400), _band_db(y[sr + 4800:], sr, 100, 400)
    assert abs(v0 - v1) < 0.3                                         # la voix sans « s » n'est pas touchée


def test_deess_file_keeps_length_and_survives_bad_file(tmp_path):
    p = tmp_path / "v.wav"
    _wav(p, _speechlike(sec=65))                                      # plus d'un bloc de 30 s
    n0 = V._frames(p)
    assert V.deess_file(p) == "anti-« s »"
    assert V._frames(p) == n0
    bad = tmp_path / "abime.wav"
    bad.write_bytes(b"rien")
    assert "sauté" in V.deess_file(bad) and bad.read_bytes() == b"rien"


def test_no_air_boost_anymore():
    af = V.chain(-60, -22)[0]
    assert "highshelf" not in af and "f=3200:t=q:w=1.3:g=1.5" in af
