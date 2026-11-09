"""Recherche légère par défaut (une seule clé Gemini) ; « non » la coupe ; la complète seulement par variable de dépôt."""
import json

import montage.__main__ as M
from montage import config as C


def test_light_search_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("MONTAGE_RECHERCHE_AUTORISEE", raising=False)
    for k in ("MONTAGE_RECHERCHE_PRESSE", "MONTAGE_FINDER"):
        monkeypatch.delenv(k, raising=False)
    o = M.options(None)
    assert o["recherche_presse"] == "oui" and o.get("_recherche_legere") and not o.get("_sans_recherche")
    assert o["finder"] == "non" and o["images_web"] == "oui"
    assert C.LIGHT_CLAIMS <= 4 and C.LIGHT_BUDGET <= 10


def test_non_turns_search_off(monkeypatch, tmp_path):
    monkeypatch.delenv("MONTAGE_RECHERCHE_AUTORISEE", raising=False)
    f = tmp_path / "o.json"
    f.write_text(json.dumps({"recherche_presse": "non", "finder": "dernier"}), encoding="utf-8")
    o = M.options(str(f))
    assert o["recherche_presse"] == "non" and o.get("_sans_recherche") and o["finder"] == "non"


def test_full_search_only_with_repo_variable(monkeypatch):
    monkeypatch.setenv("MONTAGE_RECHERCHE_AUTORISEE", "oui")
    o = M.options(None)
    assert not o.get("_recherche_legere") and not o.get("_sans_recherche")
