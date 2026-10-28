"""Sans source ni release : la vidéo « moi… » du dossier Drive montage-joints est prise."""
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
F = importlib.import_module("fetch_inputs")


def test_joints_mine(monkeypatch):
    monkeypatch.setattr(F, "rclone_remote", lambda: "gdrive")
    monkeypatch.setattr(F, "sh", lambda *a, **k: NS(stdout="extrait.mp4\nmoins.mp4\nsous/Moi_live.MOV\nphoto.jpg\nmoi.txt\n"))
    assert F.joints_mine() == "sous/Moi_live.MOV"
    monkeypatch.setattr(F, "sh", lambda *a, **k: NS(stdout="extrait.mp4\nmoins.mp4\n"))
    assert F.joints_mine() is None
    monkeypatch.setattr(F, "rclone_remote", lambda: None)            # pas de Drive configuré
    assert F.joints_mine() is None
    monkeypatch.setenv("JOINTS_DRIVE", "non")
    assert F.joints_mine() is None
