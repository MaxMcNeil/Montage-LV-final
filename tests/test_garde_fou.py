"""Garde-fous : aucune étape essentielle du montage supprimée par erreur, aucun nom indéfini dans le code."""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_etapes_essentielles_presentes():
    src = (ROOT / "montage" / "__main__.py").read_text(encoding="utf-8")
    for step in ("render_video(", "extract_main_audio(", "build_audio(", "mux(", "_vertical_version(",
                 "write_report(", "schedule(", "transcribe(", "from . import render as R"):
        assert step in src, f"étape essentielle absente du montage : {step}"


def test_aucun_nom_indefini():
    try:
        import pyflakes  # noqa: F401
    except ImportError:
        pytest.skip("pyflakes non installé")
    r = subprocess.run([sys.executable, "-m", "pyflakes", str(ROOT / "montage"), *map(str, (ROOT / "scripts").glob("*.py"))],
                       capture_output=True, text=True)
    bad = [l for l in r.stdout.splitlines() if "undefined name" in l or "referenced before assignment" in l]
    assert not bad, "\n".join(bad)
