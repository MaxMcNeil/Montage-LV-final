"""Rythme des extraits : 60 s max dans les 5 premières minutes, 2 min ensuite, jamais deux fois le même passage."""
from pathlib import Path

from montage.cadence import clashes, fill


def speech(total=840.0, sent_len=8.0):
    """Vidéo simulée : phrases de 8 s, un vrai silence de 0,7 s à chaque fin de phrase."""
    words, sents, sil = [], [], []
    t, i = 0.5, 0
    while t + sent_len < total:
        w0 = len(words)
        n = 10
        for k in range(n):
            a = t + k * (sent_len - 0.7) / n
            words.append({"w": f"mot{k}" + ("." if k == n - 1 else ""), "t0": a, "t1": a + 0.6})
        sents.append({"i": i, "t0": t, "t1": words[-1]["t1"], "w0": w0, "w1": len(words) - 1, "text": f"phrase {i} prix courses"})
        sil.append((words[-1]["t1"], words[-1]["t1"] + 0.7))
        t = words[-1]["t1"] + 0.7
        i += 1
    return words, sents, sil


class FakeAI:
    """Choisit pour chaque créneau le 1er point d'insertion et le prochain passage libre de la vidéo."""
    ok = True

    def __init__(self, refuse=()):
        self.cursor = {"v1": 0.0, "v2": 0.0}
        self.refuse = set(refuse)
        self.calls = 0

    def json(self, prompt, image=None, media_key=""):
        self.calls += 1
        if prompt.startswith("Vérification"):
            n = prompt.count("PASSAGE INSÉRÉ")
            return {"checks": [{"n": k, "ok": k not in self.refuse, "score": 8, "reason": "ok"} for k in range(n)]}
        import re
        slots = re.findall(r"Créneau (\d+) .*?\n   points d'insertion possibles : \[(\d+)\]", prompt)
        fills = []
        for n, after in slots:
            vid = "v1" if self.cursor["v1"] < 80 else "v2"
            a = self.cursor[vid]
            self.cursor[vid] = a + 10
            fills.append({"slot": int(n), "after": int(after), "video": vid, "start": a, "end": a + 8, "why": "lien"})
        return {"fills": fills}


def vids():
    def v(i):
        return {"id": i, "kind": "video", "name": f"{i}.mp4", "path": f"/x/{i}.mp4", "duration": 90.0,
                "sentences": [{"t0": k * 2.0, "t1": k * 2.0 + 1.9, "text": f"s{k}"} for k in range(45)]}
    return [v("v1"), v("v2")]


def test_rythme_respecte_les_ecarts_et_ne_repete_rien(tmp_path: Path):
    words, sents, sil = speech()
    att = vids()
    used = {"v1": [(0.0, 8.0)]}           # ouverture choc déjà prise sur v1 0-8 s
    inserts = []
    ai = FakeAI()
    info = fill(ai, words, sents, att, inserts, used, sil, "fr", "v", tmp_path, True,
                lambda x, a, b, name: {"duration": b - a, "credit": {}})
    ts = sorted(i["forced_t"] for i in inserts)
    assert ts, info
    pts = [sents[0]["t0"]] + ts
    for p, q in zip(pts, pts[1:]):
        lim = 60 if p - sents[0]["t0"] < 300 else 120
        assert q - p <= lim + 5.5, (p, q)
        assert q - p >= 20, (p, q)
    assert sents[-1]["t1"] - ts[-1] <= 125
    # aucun passage repris (ni l'ouverture choc, ni entre eux)
    for k, i in enumerate(inserts):
        others = [j["clip"] for j in inserts[:k] if j["attachment"] == i["attachment"]]
        assert not clashes(i["clip"], others)
        assert not (i["attachment"] == "v1" and clashes(i["clip"], [(0.0, 8.0)]))
    assert sum(1 for t in ts if t < 300) >= 4


def test_refus_a_la_verification_laisse_un_trou_signale(tmp_path: Path):
    words, sents, sil = speech(total=200)
    ai = FakeAI(refuse={0})
    inserts = []
    info = fill(ai, words, sents, vids(), inserts, {}, sil, "fr", "v", tmp_path, False,
                lambda x, a, b, name: {"duration": b - a, "credit": {}})
    assert any("refusé à la vérification" in h["why"] for h in info["holes"])


def test_sans_ia_rien_n_est_ajoute(tmp_path: Path):
    words, sents, sil = speech(total=200)

    class NoAI:
        ok = False
    inserts = []
    info = fill(NoAI(), words, sents, vids(), inserts, {}, sil, "fr", "v", tmp_path, False, lambda *a: {})
    assert inserts == [] and "IA indisponible" in info["why"]
