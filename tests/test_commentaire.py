"""Mode « commentaire d'une vidéo » : attribution blindée des « écoutez ça » aux passages du prompteur."""
import json
from types import SimpleNamespace as NS

from montage import commentaire as COM


def W(text):
    out, t = [], 0.0
    for w in text.split():
        out.append({"w": w, "t0": t, "t1": t + 0.3})
        t += 0.35
    return out


P = [
    {"n": 1, "start": 10, "end": 25, "titre": "Le carnet d'adresses", "annonce": "regardez ce qu'il dit sur le carnet d'adresses des invités"},
    {"n": 2, "start": 40, "end": 55, "titre": "L'avion privé", "annonce": "maintenant l'avion privé et les vols vers l'île"},
    {"n": 3, "start": 70, "end": 88, "titre": "Le juge", "annonce": "et voilà ce que le juge a répondu au procureur"},
]


def occ_at(words, *idx):
    return [{"w0": i, "w1": i + 1, "phrase": "écoutez ça", "t0": words[i]["t0"]} for i in idx]


def test_ordre_du_script():
    w = W("bonjour " * 20 + "écoutez ça " + "suite " * 20 + "écoutez ça " + "suite " * 20 + "écoutez ça fin")
    ks = [i for i, x in enumerate(w) if x["w"] == "écoutez"]
    r = COM.attribuer(occ_at(w, *ks), w, P)
    assert [p["n"] for _, p, _ in r] == [1, 2, 3]


def test_passage_saute_recale_par_annonce():
    txt = "on passe tout de suite à l'avion privé et les vols vers l'île écoutez ça " + "x " * 30 + \
          "et voilà ce que le juge a répondu au procureur écoutez ça"
    w = W(txt)
    ks = [i for i, x in enumerate(w) if x["w"] == "écoutez"]
    r = COM.attribuer(occ_at(w, *ks), w, P)
    assert [p["n"] for _, p, _ in r] == [2, 3]
    assert "sauté" in r[0][2]


def test_ecoutez_ca_en_trop_ne_lance_rien():
    w = W(" ".join(["mot écoutez ça"] * 5))
    ks = [i for i, x in enumerate(w) if x["w"] == "écoutez"]
    r = COM.attribuer(occ_at(w, *ks), w, P)
    assert [p and p["n"] for _, p, _ in r] == [1, 2, 3, None, None]


def test_charger(tmp_path):
    f = tmp_path / "p.json"
    f.write_text(json.dumps({"video": "x.mp4", "passages": [P[2], {"n": 9, "start": 5, "end": 3}, P[0]]}))
    d = COM.charger(f)
    assert [p["n"] for p in d["passages"]] == [1, 3]
    assert COM.charger(tmp_path / "absent.json") is None
    f.write_text("{pas du json")
    assert COM.charger(f) is None


def test_video_commentee_prefixe_chaine():
    att = [{"kind": "video", "name": "02_clip.mp4", "duration": 999},
           {"kind": "video", "name": "01_Jeffrey_Epstein.mp4", "duration": 300}]
    assert COM.video_commentee(att, {"video": "Jeffrey Epstein.mp4"})["name"] == "01_Jeffrey_Epstein.mp4"
    assert COM.video_commentee(att, {"video": "autre.mp4"})["name"] == "02_clip.mp4"


def test_permanent_pause_partout():
    a1, a2 = {"_pause_panel": "p1"}, {"_pause_panel": "p2"}
    segs = [NS(kind="full", panel=None), NS(kind="insert", insert={"commentaire": True, "asset": a1}),
            NS(kind="full", panel=None), NS(kind="full", panel=None),
            NS(kind="insert", insert={"commentaire": True, "asset": a2}), NS(kind="full", panel=None)]
    n = COM.permanent(segs, ["p1", "p2"])
    assert n == 4
    assert [s.panel["v"]["asset"] for s in segs if s.kind == "split"] == ["p1", "p2", "p2", "p2"]
    assert segs[2].panel["cont_out"] and segs[3].panel["cont_in"] and segs[2].panel["after_insert"]
