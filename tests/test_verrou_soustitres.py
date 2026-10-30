"""Verrou : en chaîne, la vidéo montée n'a jamais de sous-titres."""
import json

import montage.__main__ as M


def test_chain_forces_no_subtitles(monkeypatch, tmp_path):
    f = tmp_path / "o.json"
    f.write_text(json.dumps({"sous_titres": "oui"}), encoding="utf-8")
    monkeypatch.delenv("CHAINE_ID", raising=False)
    monkeypatch.delenv("MONTAGE_CHAINE_SHORTS", raising=False)
    monkeypatch.setenv("MONTAGE_SOUS_TITRES", "oui")
    assert M.options(str(f))["sous_titres"] == "oui"                  # hors chaîne : ton choix
    monkeypatch.setenv("CHAINE_ID", "20261030-0913-v1")
    assert M.options(str(f))["sous_titres"] == "non"                  # chaîne depuis le fond vert
    monkeypatch.delenv("CHAINE_ID")
    monkeypatch.setenv("MONTAGE_CHAINE_SHORTS", "oui")
    assert M.options(str(f))["sous_titres"] == "non"                  # Montage à la main + Shorts enchaînés


def test_default_is_no_subtitles(monkeypatch):
    for k in ("CHAINE_ID", "MONTAGE_CHAINE_SHORTS", "MONTAGE_SOUS_TITRES"):
        monkeypatch.delenv(k, raising=False)
    assert M.options(None)["sous_titres"] == "non"
