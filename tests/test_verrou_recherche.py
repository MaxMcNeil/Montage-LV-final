"""Verrou : aucune recherche automatique (Gemini réservé au plan / placement de TES pièces jointes)."""
import json

import montage.__main__ as M


def test_search_always_off_whatever_asked(monkeypatch, tmp_path):
    monkeypatch.delenv("MONTAGE_RECHERCHE_AUTORISEE", raising=False)
    f = tmp_path / "o.json"
    f.write_text(json.dumps({"recherche_presse": "oui", "finder": "dernier", "images_web": "oui"}), encoding="utf-8")
    monkeypatch.setenv("MONTAGE_RECHERCHE_PRESSE", "oui")
    monkeypatch.setenv("MONTAGE_FINDER", "oui")
    o = M.options(str(f))
    assert (o["recherche_presse"], o["finder"], o["images_web"]) == ("non", "non", "non") and o["_sans_recherche"]
    assert M.options(None)["finder"] == "non"                         # défaut aussi
    monkeypatch.setenv("MONTAGE_RECHERCHE_AUTORISEE", "oui")          # seul moyen de réactiver
    assert M.options(str(f))["recherche_presse"] == "oui"
