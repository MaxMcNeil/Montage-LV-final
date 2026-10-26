"""Mots-clés « écoutez… » : détection exacte, point d'insertion dans un vrai silence, choix du passage."""
from montage.keywords import choose, find_occurrences, pause_after


def _w(text, t=0.0, step=0.4):
    out = []
    for tok in text.split():
        out.append({"t0": round(t, 3), "t1": round(t + step * 0.85, 3), "w": tok})
        t += step
    return out


def test_exact_phrases_only():
    ok = ["Écoutez ça.", "écoutez-moi ça !", "Écoutez ce qu'il dit :", "écoutez ce qu'elle dit.",
          "Écoutez ce qu'ils disent.", "ÉCOUTEZ ÇA"]
    for s in ok:
        assert len(find_occurrences(_w("alors " + s + " bon"))) == 1, s
    no = ["écoutez bien ça", "écoute ça", "écoutez ceci", "écoutez ce qu'il a dit", "écoutez-moi bien",
          "écoutez ce qu'on dit", "regardez ça", "écoutez, ça va"]
    for s in no:
        assert find_occurrences(_w("alors " + s + " bon")) == [], s
    # « écoutez-moi ça » n'est pas compté deux fois (pas aussi comme « écoutez ça »)
    occ = find_occurrences(_w("écoutez-moi ça puis écoutez ça"))
    assert [o["phrase"] for o in occ] == ["écoutez-moi ça", "écoutez ça"]


def test_pause_after_needs_real_silence():
    w = _w("et voilà écoutez ça", 0.0) + _w("donc il a dit", 3.0)       # pause 1,5 → 3,0 s
    occ = find_occurrences(w)[0]
    assert 1.5 < pause_after(w, [(1.5, 3.0)], occ["w1"]) < 3.0
    assert pause_after(w, [(10, 11)], occ["w1"]) is None             # le son ne confirme pas : pas d'insertion
    w3 = _w("écoutez ça va changer beaucoup de choses", 0.0) + _w("ensuite", 6.0)   # pause trop tardive
    assert pause_after(w3, [], find_occurrences(w3)[0]["w1"], find_occurrences(w3)[0]["wait"]) is None
    w2 = _w("écoutez ce qu'il dit " + "et je continue de parler sans aucune pause " * 4, 0.0)
    assert pause_after(w2, [], find_occurrences(w2)[0]["w1"], 8.0) is None  # aucune pause dans les 8 s


def test_choose_with_check_and_retry():
    words = _w("le ministre parle des impôts écoutez ce qu'il dit") + _w("voilà sur les retraites maintenant écoutez ça", 8)
    occ = find_occurrences(words)
    vids = [{"id": "vid1", "name": "a.mp4", "duration": 60, "sentences": [
        {"t0": 0, "t1": 8, "text": "Nous allons baisser les impôts."},
        {"t0": 8.5, "t1": 16, "text": "Les impôts baisseront dès janvier."},
        {"t0": 20, "t1": 30, "text": "La réforme des retraites est nécessaire."}]}]

    class AI:
        ok = True
        calls = []

        def json(self, prompt, **k):
            self.calls.append(prompt[:30])
            if prompt.startswith("Tu es le monteur"):
                if len(self.calls) == 1:    # 1er choix : erreur volontaire sur l'annonce 1
                    return {"choices": [{"n": 0, "video": "vid1", "start": 0, "end": 16},
                                        {"n": 1, "video": "vid1", "start": 0, "end": 8}]}
                return {"choices": [{"n": 1, "video": "vid1", "start": 20, "end": 30}]}
            if "PASSAGE INSÉRÉ" in prompt:
                case1 = prompt.split("[1]")[1] if "[1]" in prompt else ""
                passage = case1.split("PASSAGE INSÉRÉ")[1].split("APRÈS")[0] if case1 else ""
                bad = bool(case1) and "retraites" not in passage
                return {"checks": [{"n": 0, "ok": True, "score": 9}, {"n": 1, "ok": not bad, "score": 2 if bad else 9}]}
    res = choose(AI(), occ, words, vids, "fr", 25)
    assert [(r["n"], r["a"] < 1, r["b"] > 15) for r in res][0] == (0, True, True)
    assert res[1]["a"] >= 19 and res[1]["b"] <= 30.5 and res[1]["check"]["ok"]


def test_choose_without_ai_uses_matching_words():
    words = _w("parlons de la réforme des retraites écoutez ça")
    occ = find_occurrences(words)
    vids = [{"id": "vid1", "name": "a.mp4", "duration": 60, "sentences": [
        {"t0": 0, "t1": 8, "text": "Les impôts baissent."}, {"t0": 20, "t1": 28, "text": "La réforme des retraites arrive."}]}]
    res = choose(None, occ, words, vids, "fr", 25)
    assert res and res[0]["a"] >= 19
