"""Ouverture choc sans vidéo jointe : déclaration vidéo trouvée par la recherche (jamais bloquant)."""
from pathlib import Path

import montage.__main__ as M


class FakeAI:
    ok = True

    def __init__(self, ans):
        self.ans = ans
        self.prompts = []

    def json(self, prompt):
        self.prompts.append(prompt)
        return self.ans


def _pool():
    return [
        {"source_url": "https://v/1", "quote": "phrase banale", "start": 10, "end": 20, "speaker": "A"},
        {"source_url": "https://v/2", "quote": "phrase CHOC", "start": 30, "end": 42, "speaker": "B"},
        {"source_url": "https://v/3", "quote": "", "start": 0, "end": 9},            # sans citation : écartée
        {"source_url": "https://v/4", "quote": "trop court", "start": 0, "end": 2},  # < 3 s : écartée
    ]


def test_prend_la_plus_forte_et_la_telecharge(monkeypatch):
    got = []

    def fake_clip(cands, *a, **k):
        got.append(cands[0]["source_url"])
        return {"video": "x.mp4", "credit": {"url": cands[0]["source_url"], "source": "Chaîne", "title": "T"}}
    monkeypatch.setattr(M, "clip_insert", fake_clip)
    ai = FakeAI({"order": [1, 0], "why": "la plus choquante"})
    asset, note = M.pick_found_opener(ai, _pool(), [], "fr", "vertical", Path("/tmp"), "sujet")
    assert got == ["https://v/2"] and asset["opener_found"]
    assert "OUVERTURE CHOC" in asset["source"] and "https://v/2" in note
    assert "phrase banale" in ai.prompts[0] and "trop court" not in ai.prompts[0]


def test_repli_sur_la_suivante_si_bloquee(monkeypatch):
    def fake_clip(cands, *a, **k):
        return None if cands[0]["source_url"] == "https://v/2" else {"video": "x", "credit": {"url": cands[0]["source_url"]}}
    monkeypatch.setattr(M, "clip_insert", fake_clip)
    asset, note = M.pick_found_opener(FakeAI({"order": [1, 0]}), _pool(), [], "fr", "vertical", Path("/tmp"), "s")
    assert asset["credit"]["url"] == "https://v/1"


def test_rien_de_pertinent_debut_normal(monkeypatch):
    monkeypatch.setattr(M, "clip_insert", lambda *a, **k: (_ for _ in ()).throw(AssertionError("pas de téléchargement")))
    asset, note = M.pick_found_opener(FakeAI({"order": []}), _pool(), [], "fr", "vertical", Path("/tmp"), "s")
    assert asset is None and "pas d'ouverture choc" in note


def test_jamais_la_meme_video_qu_un_extrait_deja_place(monkeypatch):
    seen = []
    monkeypatch.setattr(M, "clip_insert", lambda c, *a, **k: seen.append(c[0]["source_url"]) or None)
    ins = [{"asset": {"credit": {"url": "https://v/2"}}}]
    M.pick_found_opener(FakeAI({"order": [0, 1]}), _pool(), ins, "fr", "vertical", Path("/tmp"), "s")
    assert "https://v/2" not in seen


def test_aucune_trouvee():
    asset, note = M.pick_found_opener(FakeAI({}), [], [], "fr", "vertical", Path("/tmp"), "s")
    assert asset is None and "aucune" in note
