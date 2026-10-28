"""Chaîne (logo, couleurs), mise en scène par la voix, recherche par affirmation : cas normaux ET extrêmes."""
import json
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np
import pytest
from PIL import Image

from montage import chaine as K
from montage import config as C


def mk(root: Path, code: str, js=None, logo="round", size=512):
    d = root / code
    d.mkdir(parents=True)
    if js is not None:
        (d / "chaine.json").write_text(js if isinstance(js, str) else json.dumps(js), encoding="utf-8")
    if logo == "round":
        im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        from PIL import ImageDraw
        ImageDraw.Draw(im).ellipse((8, 8, size - 8, size - 8), fill=(20, 40, 90, 255))
        im.save(d / "logo.png")
    elif logo == "opaque":
        Image.new("RGB", (size, size), (10, 30, 60)).save(d / "logo.png")
    elif logo == "corrupt":
        (d / "logo.png").write_bytes(b"\x89PNG pas du tout une image")
    elif logo == "transparent":
        Image.new("RGBA", (size, size), (0, 0, 0, 0)).save(d / "logo.png")
    return d


def test_choose_rules(tmp_path):
    mk(tmp_path, "fr", {"nom": "Le Journal du NON", "langues": ["fr"], "defaut": True})
    mk(tmp_path, "ar", {"langues": ["ar"]})
    assert K.choose("auto", "fr", tmp_path)[0]["code"] == "fr"
    assert K.choose("auto", "ar", tmp_path)[0]["code"] == "ar"
    p, why = K.choose("auto", "it", tmp_path)
    assert p["code"] == "fr" and "par défaut" in why
    p, why = K.choose("en", "fr", tmp_path)
    assert p["code"] == "fr" and why.startswith("⚠")
    assert K.choose("non", "fr", tmp_path)[0] is None
    assert K.choose("auto", "fr", tmp_path / "rien")[0] is None


def test_bad_json_and_missing_logo_are_reported(tmp_path):
    mk(tmp_path, "fr", "{pas du json", logo=None)
    p = K.load_all(tmp_path)[0]
    assert any("illisible" in n for n in p["notes"]) and any("aucun logo" in n for n in p["notes"])
    b = K.prepare(p, "h", tmp_path / "w")
    assert "bug" not in b


@pytest.mark.parametrize("kind,frag", [("corrupt", "illisible"), ("transparent", "illisible")])
def test_unusable_logo_never_crashes(tmp_path, kind, frag):
    mk(tmp_path, "fr", {}, logo=kind)
    b = K.prepare(K.load_all(tmp_path)[0], "h", tmp_path / "w")
    assert "bug" not in b and any(frag in n for n in b["notes"])


def test_tiny_logo_refused_small_logo_warned(tmp_path):
    mk(tmp_path, "fr", {}, size=40)
    b = K.prepare(K.load_all(tmp_path)[0], "h", tmp_path / "w")
    assert "bug" not in b
    mk(tmp_path, "it", {}, size=150)
    b = K.prepare(K.load(tmp_path / "it"), "v", tmp_path / "w2")
    assert b.get("bug") and any("petit" in n for n in b["notes"])


@pytest.mark.parametrize("orient", ["h", "v"])
def test_bug_stays_out_of_frames(tmp_path, orient):
    mk(tmp_path, "fr", {}, logo="opaque")   # sans transparence : coins arrondis
    b = K.prepare(K.load_all(tmp_path)[0], orient, tmp_path / "w")
    im = Image.open(b["bug"])
    x, y = b["bug_xy"]
    W, H = C.SIZE[orient]
    assert 0 <= x and x + im.width <= W and y >= 0
    top_frames = min(g[1] for side in C.GEOM[orient].values() for g in side.values())
    visible = im.getchannel("A").point(lambda v: 255 if v > 40 else 0).getbbox()
    assert y + visible[3] <= top_frames + 2          # le logo visible ne touche aucun cadre (toi / média)
    assert any("coins arrondis" in n for n in b["notes"])


def test_end_card_placement_and_too_small(tmp_path):
    mk(tmp_path, "fr", {})
    b = K.prepare(K.load_all(tmp_path)[0], "h", tmp_path / "w")
    K.end_card(b, (600, 820, 30.0, 330), 1920, tmp_path / "w")
    x, y = b["end_xy"]
    e = Image.open(b["end"])
    assert x + e.width <= 330 and 600 <= y and y + e.height <= 820 and b["end_t0"] == 30.0
    b2 = K.prepare(K.load_all(tmp_path)[0], "h", tmp_path / "w3")
    K.end_card(b2, (600, 660, 30.0, 330), 1920, tmp_path / "w3")
    assert "end" not in b2 and any("trop étroit" in n for n in b2["notes"])
    K.end_card(b2, None, 1920, tmp_path / "w3")   # pas de carte de fin : rien, sans erreur


def test_palette_readable_and_reset():
    try:
        p = {"couleurs_auto": False, "couleurs": {"NAVY": "#FFFFFF", "GOLD": "#123", "ROSE": "#ff00ff"}}
        notes = K.apply_palette(p, {})
        assert C.NAVY != (255, 255, 255)                 # blanc illisible sous du texte crème : refusé
        assert any("ROSE" in n for n in notes) and any("#123" in n for n in notes)
        K.apply_palette({"couleurs_auto": False, "couleurs": {"RED": "#FF3030"}}, {})
        assert K.contrast(C.RED, C.PAPER) >= 4.5          # assombri jusqu'à être lisible
    finally:
        K.apply_palette(None, {})
    assert C.NAVY == K.DEFAULT_PALETTE["NAVY"]


def test_real_logos_in_repo():
    for p in K.load_all():
        assert p["logo"], p["code"]
        im, _ = K.open_logo(p["logo"])
        assert min(im.size) >= 256


# ------------------------------------------------------------------ voix
def _sents(n, dur=3.0):
    words, sents = [], []
    for i in range(n):
        w0 = len(words)
        for k in range(6):
            t = i * dur + k * 0.4
            words.append({"t0": t, "t1": t + 0.3, "w": "mot"})
        sents.append({"i": i, "w0": w0, "w1": len(words) - 1, "t0": i * dur, "t1": i * dur + 2.3, "text": "x"})
    return words, sents


def test_energy_detects_loud_sentence():
    from montage.voix import sentence_energy
    from montage.pauses import HOP, SR
    words, sents = _sents(12)
    fps = SR / HOP
    db = np.full(int(40 * fps), -30.0) + np.random.default_rng(1).normal(0, 0.3, int(40 * fps))
    db[int(15 * fps):int(17.4 * fps)] = -18.0             # phrase 5 criée
    e = sentence_energy(db, words, sents)
    assert e[5]["z"] >= 1.2 and all(x["z"] < 1.2 for k, x in enumerate(e) if k != 5)


def test_energy_degenerate_inputs():
    from montage.voix import sentence_energy
    words, sents = _sents(2)
    assert sentence_energy(None, words, sents) is None
    assert sentence_energy(np.zeros(10), words, sents) is None          # trop peu de phrases mesurables
    words, sents = _sents(10)
    flat = sentence_energy(np.full(5000, -25.0), words, sents)          # voix parfaitement plate
    assert flat is not None and all(abs(x["z"]) < 0.01 for x in flat)


def test_zooms_never_repeat_and_edges_wide():
    from montage.timeline import Atom, Segment, _zooms
    words, sents = _sents(20)
    energy = [{"z": (2.0 if k % 5 == 0 else 0.0), "fast": k % 3 == 0, "rate": 3} for k in range(20)]
    segs = [Segment("insert"), Segment("full", atoms=[Atom(0.0, 60.0)]), Segment("split", atoms=[Atom(60, 62)])]
    st = _zooms(segs, sents, "h", energy)
    z = [a.zoom for a in segs[1].atoms]
    assert len(z) >= 6 and all(abs(a - b) >= 0.02 for a, b in zip(z, z[1:]))
    assert z[0] == 1.0 and z[-1] == 1.0 and st["serre"] >= 1
    assert all(b.a == a.b for a, b in zip(segs[1].atoms, segs[1].atoms[1:]))     # aucun trou, aucun chevauchement
    assert segs[1].atoms[0].a == 0.0 and segs[1].atoms[-1].b == 60.0
    assert min(a.b - a.a for a in segs[1].atoms) >= 1.2


def test_zooms_wrong_energy_length_falls_back():
    from montage.timeline import Atom, Segment, _zooms
    words, sents = _sents(10)
    segs = [Segment("full", atoms=[Atom(0.0, 30.0)])]
    _zooms(segs, sents, "v", [{"z": 3, "fast": True, "rate": 4}])          # longueur incohérente : ignorée
    assert {round(a.zoom, 2) for a in segs[0].atoms} <= {1.0, 1.08}


# ------------------------------------------------------------------ Telegram / Reddit dans les lots
def test_read_posts(tmp_path):
    from montage.finder import read_posts
    f = tmp_path / "posts.csv"
    f.write_text("plateforme,chaine,date,texte,url,audience,commentaires,media,position\n"
                 "telegram,@infos,2026-10-01,Un message assez long sur le sujet,https://t.me/infos/1,500,0,,appui\n"
                 "reddit,r/france,2026-10-02,Discussion,https://reddit.com/x,10,3,,contre\n"
                 "telegram,@infos,2026-10-01,doublon,https://t.me/infos/1,1,0,,\n"
                 ",,,,,,,,\n", encoding="utf-8")
    out = read_posts([f, tmp_path / "absent.csv"])
    assert [x["url"] for x in out] == ["https://t.me/infos/1", "https://reddit.com/x"]
    assert out[0]["source"] == "Telegram · @infos" and out[1]["position"] == "contre"


def test_load_lot_separates_contre(tmp_path):
    from montage.finder import load_lot
    lot = tmp_path / "results" / "2026-10-28_1200_n1" / "01-x"
    lot.mkdir(parents=True)
    (lot / "montage.json").write_text('{"clips": []}', encoding="utf-8")
    (lot / "articles.csv").write_text("titre,date,source,domaine,autorite,url,texte_complet_verifie,position\n"
                                      "Pour,2026,Le Monde,lemonde.fr,0.9,https://a,True,appui\n"
                                      "Contre,2026,AFP,afp.com,0.95,https://b,True,contre\n"
                                      "Ancien,2026,X,x.fr,0.5,https://c,True\n", encoding="utf-8")
    d = load_lot(tmp_path, "dernier")
    assert [a["titre"] for a in d["articles"]] == ["Pour", "Ancien"] and [c["titre"] for c in d["contre"]] == ["Contre"]


# ------------------------------------------------------------------ recherche par affirmation
def test_claim_searches_statuses(tmp_path, monkeypatch):
    import montage.__main__ as M
    calls = []

    def fake_search(p, lang, work, minutes=9, quota_file=None):
        calls.append(p["target"])
        if p["target"] == "boom":
            return {"clips": [], "articles": [], "posts": [], "error": "IA indisponible pour préparer la recherche"}
        return {"clips": [], "posts": [{"titre": "msg telegram", "url": "https://t.me/a/1", "source": "Telegram · @a",
                                        "position": "contre"}],
                "articles": [{"titre": "Un article", "url": "https://x", "source": "Le Monde", "autorite": "0.9",
                              "position": "appui"}], "error": "", "social": {"telegram": "⚠ session refusée"}}
    monkeypatch.setattr(M, "press_search", fake_search)
    monkeypatch.setattr(M, "og_image", lambda *a, **k: None)
    monkeypatch.setattr(M, "render_panel", lambda *a, **k: "panel.png")
    plan = {"visuals": [], "press": [{"target": "ok", "claim": "c", "after": 3, "s0": 2},
                                     {"target": "boom", "claim": "", "after": 10, "s0": 9},
                                     {"target": "couvert", "claim": "", "after": 20, "s0": 19},
                                     {"target": "trop", "claim": "", "after": 30, "s0": 29}]}
    lot = {"placed": {"inserts": [{"after": 21}], "articles": []}}
    ai = NS(save_quota=lambda: None)
    info = M.claim_searches(plan, lot, [], "h", tmp_path, "fr", ai, 25, 6, 900, 800, tmp_path, 3)
    st = [c["status"] for c in info["claims"]]
    assert st[0].startswith("✅") and "carte" in st[0]
    assert st[1].startswith("⚠") and "IA" in st[1]
    assert "déjà couvert" in st[2] and len(info["claims"]) == 3 and "couvert" not in calls
    assert len(info["contre"]) == 1 and info["social"]["telegram"].startswith("⚠")
    assert len(plan["visuals"]) == 1


def test_logo_failure_rerenders_without_logo(tmp_path, monkeypatch):
    import montage.render as R
    from montage.timeline import Segment
    calls = []

    def fake_full(seg, ctx, out):
        calls.append(R._TL.off)
        if not R._TL.off:
            raise RuntimeError("overlay cassé")
        Path(out).write_bytes(b"x")
    monkeypatch.setattr(R, "render_full", fake_full)
    monkeypatch.setattr(R, "run", lambda *a, **k: None)
    R.BRAND, R.BRAND_FAILS[:] = {"bug": "/nope.png", "bug_xy": (0, 0)}, []
    try:
        seg = Segment("full", n=30)
        R.render_video([seg], NS(work=tmp_path), tmp_path / "v.mp4", workers=1)
    finally:
        R.BRAND = None
    assert calls == [False, True] and R.BRAND_FAILS == ["seg0000.mp4"]


def test_brand_filter_graph():
    import montage.render as R
    g = R.Graph()
    R.BRAND = {"bug": "b.png", "bug_xy": (10, 8), "end": "e.png", "end_xy": (40, 600), "end_t0": 12.0}
    try:
        R._TL.t0, R._TL.off = 10.0, False
        lab = g._brand("out", 90)                        # segment 10 s → 13 s : la carte de fin commence à 2 s
        txt = ";".join(g.lines)
        assert lab == "brand2" and "enable='lt(t,2.000)'" in txt and "gte(t,2.000)" in txt
        g2 = R.Graph()
        R._TL.t0 = 0.0
        assert g2._brand("out", 90) == "brand1" and "enable" not in ";".join(g2.lines)
        R._TL.off = True
        assert R.Graph()._brand("out", 90) == "out"
    finally:
        R.BRAND, R._TL.off = None, False
