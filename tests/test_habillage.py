"""Habillage horizontal : là où rien n'est prévu, toi dans ton cadre + carte de ta phrase (chiffre clé / citation)."""
from montage.habillage import _num, make_ambient
from montage.timeline import schedule


def _sents(n=40, dur=4.0):
    out, words = [], []
    for i in range(n):
        t0 = 2.0 + i * (dur + 0.6)
        txt = f"phrase numéro {i} avec 105 000 euros d'amende" if i == 7 else f"voici la phrase {i} assez longue pour lire"
        out.append({"i": i, "t0": t0, "t1": t0 + dur, "text": txt})
        words.append({"w": "x", "t0": t0, "t1": t0 + dur})
    return out, words


def test_num():
    assert _num("une amende de 105 000 euros") == "105 000 euros"
    assert _num("en 1981 Mitterrand") is None
    assert _num("2 300 enfants dorment dehors") == "2 300 enfants"


def test_ambient_couvre_la_plupart_du_temps(tmp_path):
    sents, words = _sents()
    made = []
    amb = make_ambient(sents, {i: f"citation {i} forte et claire" for i in range(len(sents))}, [{"s": 0, "title": "Intro"}],
                       lambda k, d, n: made.append((k, d)) or {"frame": "x"}, "fr")
    keep = [(0.0, sents[-1]["t1"] + 1)]
    opts = {"fin": "non", "couper_silences": "non"}
    segs, chosen = schedule(words, sents, keep, [], [], [], keep[0][1], opts, "h", ambient=amb)
    cover = sum(c["en"] - c["st"] for c in chosen if c.get("ambient"))
    assert cover > 0.55 * keep[0][1]
    assert any(k == "figure" for k, _ in made)          # le chiffre prononcé devient un chiffre clé
    segs2, chosen2 = schedule(words, sents, keep, [], [], [], keep[0][1], opts, "h")
    assert not any(c.get("ambient") for c in chosen2)    # sans habillage : comme avant
