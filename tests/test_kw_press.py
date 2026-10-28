"""« écoutez ça » sans passage de tes vidéos : déclaration trouvée par le Finder / la presse (vérifiée)."""
import montage.__main__ as M


def words_sents():
    words = [{"t0": i * 0.5, "t1": i * 0.5 + 0.4, "w": w} for i, w in enumerate(
        "le ministre a dit hier que le chômage baisse écoutez ça".split())]
    sents = [{"i": 0, "w0": 0, "w1": len(words) - 1, "t0": 0.0, "t1": words[-1]["t1"], "text": "…"}]
    return words, sents


class AI:
    ok = True

    def __init__(self, ok_check=True):
        self.ok_check = ok_check

    def json(self, prompt, **k):
        if "Vérification indépendante" in prompt:
            return {"ok": self.ok_check, "score": 9, "reason": "même propos"}
        return {"picks": [{"n": 0, "clips": [1, 0], "why": "le ministre parle du chômage"}]}


def kw_info():
    return {"items": [{"n": 0, "phrase": "écoutez ça", "t0": 4.5, "t1": 5.4, "inserted": False, "pending_t": 6.0,
                       "w1": 9, "why": "aucune vidéo jointe (release ou Drive)"}]}


POOL = [{"source_url": "https://y/1", "start": 10, "end": 20, "speaker": "X", "quote": "autre chose"},
        {"source_url": "https://y/2", "start": 30, "end": 40, "speaker": "Le ministre", "quote": "le chômage baisse"}]


def test_inserted_after_check(monkeypatch, tmp_path):
    w, s = words_sents()
    monkeypatch.setattr(M, "clip_insert", lambda c, *a, **k: {"duration": 8, "credit": {"url": c[0]["source_url"]}})
    info, ins = kw_info(), []
    M.kw_press_fallback(AI(), w, s, info, ins, POOL, "h", tmp_path, "fr", 25)
    it = info["items"][0]
    assert it["inserted"] and ins[0]["forced_t"] == 6.0 and ins[0]["kw"] == 0
    assert ins[0]["asset"]["credit"]["url"] == "https://y/2"        # le 1er choix de l'IA


def test_refused_or_download_fail_leaves_it_out(monkeypatch, tmp_path):
    w, s = words_sents()
    monkeypatch.setattr(M, "clip_insert", lambda *a, **k: {"duration": 8, "credit": {}})
    info, ins = kw_info(), []
    M.kw_press_fallback(AI(ok_check=False), w, s, info, ins, POOL, "h", tmp_path, "fr", 25)
    assert not info["items"][0]["inserted"] and not ins and "refusées" in info["items"][0]["why"]
    monkeypatch.setattr(M, "clip_insert", lambda *a, **k: None)          # YouTube refuse : candidat suivant, puis rien
    info, ins = kw_info(), []
    M.kw_press_fallback(AI(), w, s, info, ins, POOL, "h", tmp_path, "fr", 25)
    assert not ins and "non téléchargeable" in info["items"][0]["why"]


def test_no_ai_no_pool_noop(tmp_path):
    w, s = words_sents()
    info, ins = kw_info(), []
    M.kw_press_fallback(None, w, s, info, ins, POOL, "h", tmp_path, "fr", 25)
    M.kw_press_fallback(AI(), w, s, info, ins, [], "h", tmp_path, "fr", 25)
    assert not ins and not info["items"][0]["inserted"]
