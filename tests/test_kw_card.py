"""« écoutez ça » sans vidéo jointe : une carte (ta photo, sinon photo libre, sinon texte) est toujours insérée."""
from pathlib import Path

from PIL import Image

import montage.__main__ as M


def _words(txt, t0=0.0):
    return [{"w": w, "t0": t0 + k * 0.4, "t1": t0 + k * 0.4 + 0.3} for k, w in enumerate(txt.split())]


def _setup(tmp_path):
    words = _words("Trump a parlé à Carlson dans le Bureau ovale écoutez ça on meurt tous de toute façon donc ça "
                   "n'a pas d'importance selon lui")
    w1 = next(k for k, w in enumerate(words) if w["w"] == "ça")
    kw_info = {"items": [{"n": 0, "phrase": "écoutez ça", "t0": 3.6, "t1": 4.0, "inserted": False,
                          "pending_t": 4.2, "w1": w1, "why": "aucune vidéo jointe (release ou Drive)"}]}
    sents = [{"i": 0, "w0": 0, "w1": len(words) - 1}]
    return words, sents, kw_info


class FakeAI:
    ok = True

    def __init__(self, ans):
        self.ans = ans

    def json(self, _prompt):
        return self.ans


def test_carte_texte_sans_ia(tmp_path):
    words, sents, kw = _setup(tmp_path)
    inserts, plan = [], {}
    M.kw_card_fallback(None, words, sents, kw, inserts, [], plan, "h", tmp_path, "fr", wiki=False)
    it = kw["items"][0]
    assert it["inserted"] and it["card_kw"] and "carte texte" in it["video"]
    assert len(inserts) == 1 and inserts[0]["forced_t"] == 4.2 and inserts[0]["kw"] == 0
    assert Path(inserts[0]["asset"]["video"]).exists()


def test_photo_jointe_choisie(tmp_path):
    words, sents, kw = _setup(tmp_path)
    p = tmp_path / "trump.jpg"
    Image.new("RGB", (800, 600), (120, 60, 40)).save(p)
    att = [{"id": "ph1", "kind": "image", "name": "trump.jpg", "path": str(p), "label": "Donald Trump"}]
    inserts, plan = [], {}
    ai = FakeAI({"photo": "ph1", "sujet": "Donald Trump", "titre": "Trump à Carlson",
                 "texte": "Selon Carlson, Trump lui aurait répondu que de toute façon tout le monde meurt"})
    M.kw_card_fallback(ai, words, sents, kw, inserts, att, plan, "h", tmp_path, "fr", wiki=False)
    assert "ta photo" in kw["items"][0]["video"]
    assert plan["_kw_photos"] == ["ph1"]   # la photo ne sera pas remontée une 2e fois par le rythme
