"""Rythme : extraits, articles et photos comptent pareil ; régularité après 5 min ; contrôle des trous."""
from types import SimpleNamespace as NS

from montage import cadence as K


def sents_every(n, step=10.0):
    out, words = [], []
    for i in range(n):
        t = i * step
        words.append({"t0": t, "t1": t + 2, "w": f"mot{i}"})
        out.append({"i": i, "w0": i, "w1": i, "t0": t, "t1": t + 2, "text": f"phrase {i} sur le ministre et les chiffres"})
    return out, words


def test_holes_rule():
    # 0 → 600 s sans rien : 5 premières minutes = fenêtres de 60 s, ensuite une carte 30-45 s après la précédente
    hs = K.holes([], 0.0, 600.0, False)
    assert hs[0] == (25.0, 60.0) and all(b - a <= 35.0 for a, b in hs if a < 300)
    late = [h for h in hs if h[0] >= 300]
    assert late and all(b - a == 15.0 for a, b in late)          # 30 s → 45 s après le précédent
    assert len(late) >= 6                                         # bien plus de cartes qu'avant (1 toutes les 2 min)
    # un élément toutes les 50 s au début puis toutes les 45 s : aucun trou
    times = [50 * k for k in range(1, 7)] + [300 + 45 * k for k in range(1, 9)]
    assert K.holes(times, 0.0, 660.0, False) == []
    # toutes les 2 min après 5 min : il manque des cartes
    assert K.holes([50 * k for k in range(1, 7)] + [420, 540], 0.0, 660.0, False)
    assert K.holes([], 0.0, 0.0, False) == []                     # vidéo vide


def test_thin_never_removes_cards_only_spaces_auto_videos():
    sents, words = sents_every(80)            # 0 → 790 s
    vis = [{"kind": "article", "s0": 35, "asset": {"x": 1}, "label": "a35"},   # 350 s
           {"kind": "article", "s0": 40, "asset": {"x": 1}, "label": "a40"},   # 400 s : 50 s après → retiré
           {"kind": "attachment", "s0": 42, "asset": {"x": 1}, "label": "ma photo"},   # 420 s : protégée
           {"kind": "thing", "s0": 55, "asset": {"x": 1}, "label": "w55"},     # 550 s : 130 s après → gardé
           {"kind": "article", "s0": 10, "asset": {"x": 1}, "label": "a10"},   # 100 s : < 5 min, jamais retiré
           {"kind": "article", "s0": 11, "asset": {"x": 1}, "label": "a11"}]   # 110 s : idem
    ins = [{"forced_t": 560.0, "kw": 1, "asset": {"source": "écoutez ça"}},     # protégé même à 10 s
           {"forced_t": 600.0, "asset": {"source": "presse"}}]                   # auto, 40 s après → retiré
    info = {}
    K.thin(ins, vis, words, sents, [], info)
    assert [v["label"] for v in vis] == ["a35", "a40", "ma photo", "w55", "a10", "a11"]    # aucune carte retirée
    assert [i["asset"]["source"] for i in ins] == ["écoutez ça"]                    # vidéo auto 40 s après : retirée
    assert len(info["thinned"]) == 1


class FakeAI:
    ok = True

    def __init__(self, verify_ok=True, garbage=False):
        self.verify_ok, self.garbage, self.calls = verify_ok, garbage, 0

    def json(self, prompt, **k):
        self.calls += 1
        if self.garbage:
            return "pas du json"
        if "Vérification indépendante" in prompt:
            n = prompt.count("PHRASE :")
            return {"checks": [{"n": i, "ok": self.verify_ok, "score": 8, "reason": "même sujet"} for i in range(n)]}
        n = prompt.count("Créneau ")
        out = []
        for k in range(n):
            seg = prompt.split(f"Créneau {k} (")[1]
            first = int(seg.split("[")[1].split("]")[0])
            out.append({"slot": k, "s": first, "item": f"A{k}" if k < 2 else "W", "query": "Emmanuel Macron",
                        "why": "il parle de ça"})
        return {"fills": out}


def test_fill_cards_fills_holes_in_order_and_verifies():
    sents, words = sents_every(40)            # 0 → 392 s, aucun élément
    vis, ins = [], []
    pool = {"articles": [{"titre": f"Article {k}", "url": f"https://x/{k}", "source": "Le Monde"} for k in range(3)],
            "photos": []}
    made = []

    def mk(kind, src, query, s):
        made.append((kind, s))
        return {"kind": "article" if kind == "article" else "thing", "s0": s, "s1": s, "asset": {"ok": 1},
                "label": (src or {}).get("titre") or query, "source": "src"}
    info = {"holes": [], "cards": []}
    K.fill_cards(FakeAI(), words, sents, ins, vis, [], "fr", False, pool, mk, info)
    assert vis and all(v.get("rythme") for v in vis)
    assert made[0][0] == "article" and any(k == "wiki" for k, _ in made)
    times = sorted(sents[v["s0"]]["t0"] for v in vis)
    assert times[0] <= 60                                          # 1er élément dans la 1re minute


def test_fill_cards_refused_or_garbage_adds_nothing_and_explains():
    sents, words = sents_every(30)
    for ai in (FakeAI(verify_ok=False), FakeAI(garbage=True), NS(ok=False)):
        vis, info = [], {"holes": [], "cards": []}
        K.fill_cards(ai, words, sents, [], vis, [], "fr", False, {"articles": [{"titre": "t", "url": "u"}]},
                     lambda *a: {"kind": "article", "s0": a[3], "asset": {}}, info, rounds=2)
        assert vis == [] and info["holes"]


def test_fill_cards_make_visual_failure_is_safe():
    sents, words = sents_every(30)
    vis, info = [], {"holes": [], "cards": []}

    def boom(*a):
        raise RuntimeError("og:image cassé")
    K.fill_cards(FakeAI(), words, sents, [], vis, [], "fr", False, {"articles": [{"titre": "t", "url": "u"}] * 3},
                 boom, info, rounds=1)
    assert vis == [] and any("impossible" in h["why"] for h in info["holes"])


def test_qc_holes():
    Seg = lambda kind, out0, panel=None: NS(kind=kind, out0=out0, panel=panel)   # noqa: E731
    p1, p2 = object(), object()
    segs = [Seg("full", 0), Seg("insert", 280), Seg("full", 290), Seg("split", 400, p1), Seg("split", 410, p1),
            Seg("full", 420), Seg("split", 700, p2)]
    hs = K.qc_holes(segs, 800.0, 5.5)
    assert hs == [(400, 700)]                                      # 5 min de trou entre 400 et 700 s
    assert K.qc_holes([Seg("full", 0)], 200.0) == []               # vidéo courte : pas de règle « après 5 min »
