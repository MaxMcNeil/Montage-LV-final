"""Une coupe ne mange jamais le début d'un mot : un « s » faible avant la voyelle est gardé (vérifié à l'oreille)."""
import shutil
import subprocess
import wave

import numpy as np
import pytest

from montage.pauses import guard_cuts, sound_env

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg absent")
SR = 48000


def _word(rng, dur_s=0.18, dur_v=0.35):
    """« s » (souffle aigu, faible) puis voyelle (forte)."""
    s = rng.standard_normal(int(dur_s * SR))
    s = np.diff(np.diff(s, prepend=0), prepend=0) * 0.012          # très aigu, bas niveau
    t = np.arange(int(dur_v * SR)) / SR
    v = 0.25 * np.sin(2 * np.pi * 160 * t) * np.hanning(len(t)) ** 0.3
    return np.concatenate([s, v])


def _make(tmp_path):
    rng = np.random.default_rng(0)
    floor = lambda d: 0.0015 * rng.standard_normal(int(d * SR))   # noqa: E731 - bruit de pièce
    parts, onsets = [floor(1.0)], []
    for k in range(4):
        onsets.append(sum(len(p) for p in parts) / SR)
        parts += [_word(rng), floor(1.4)]
    x = np.concatenate(parts)
    x[:] += 0.0015 * rng.standard_normal(len(x))
    p = tmp_path / "voix.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
    return p, onsets


def test_cut_never_eats_a_soft_s(tmp_path):
    p, onsets = _make(tmp_path)
    env = sound_env(p, tmp_path)
    assert env is not None
    # la transcription place chaque mot sur la VOYELLE (0,18 s trop tard) et la coupe laisse 0,1 s de marge :
    # sans garde, le « s » serait mangé
    keep = [(max(0.0, o + 0.18 - 0.10), o + 0.18 + 0.40) for o in onsets]
    new, moved = guard_cuts(keep, env)
    assert moved >= len(onsets) - 1
    for (a, b), o in zip(new, onsets):
        assert a <= o + 0.01, (a, o)                              # le « s » est gardé en entier
        assert a >= o - 0.6                                      # jamais un grand bout de silence réintroduit
    for (a1, b1), (a2, b2) in zip(new, new[1:]):
        assert b1 <= a2 + 1e-9                                   # aucun chevauchement


def test_guard_is_neutral_on_clean_cuts(tmp_path):
    p, onsets = _make(tmp_path)
    env = sound_env(p, tmp_path)
    keep = [(o - 0.30, o + 0.18 + 0.40 + 0.25) for o in onsets]  # marges déjà bonnes
    new, moved = guard_cuts(keep, env)
    assert all(abs(a - na) < 0.06 for (a, _), (na, _) in zip(keep, new))


def test_no_env_changes_nothing():
    keep = [(1.0, 2.0), (3.0, 4.0)]
    assert guard_cuts(keep, None) == (keep, 0)
