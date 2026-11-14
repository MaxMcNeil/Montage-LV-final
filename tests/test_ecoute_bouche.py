"""Toi qui écoutes pendant un extrait : seulement de vrais moments bouche FERMÉE, toujours en avant, variés."""
from montage import ecoute as E


def data(pattern, fps=8):
    return {"fps": fps, "gap": pattern}


def test_moments_bouche_fermee():
    o, f = 0.05, 0.003                      # bouche ouverte / fermée (écart des lèvres / hauteur du visage)
    g = [o] * 8 + [f] * 20 + [o] * 4 + [f] * 6 + [o] * 2 + [f] * 30 + [-1] + [f] * 40
    runs = E.closed_runs(data(g))
    assert len(runs) == 3                   # 6 images (0,75 s) : trop court ; visage perdu (-1) : coupe le moment
    for a, b in runs:
        assert b - a >= E.MIN_RUN
        i0, i1 = int(round(a * 8)), int(round(b * 8))
        assert all(0 <= x < E.CLOSED for x in g[i0:i1 + 1]), "jamais une image bouche ouverte dans un moment"


def test_pas_de_mesure_pas_de_moment():
    assert E.closed_runs(None) == [] and E.best_frame(None, 10.0) is None


def test_choix_varie_jamais_deux_fois_de_suite(tmp_path):
    g = []
    for k in range(8):                      # 8 moments de 2,5 s bouche fermée, séparés par de la parole
        g += [0.05] * 24 + [0.002] * 20
    e = E.Ecoute(tmp_path / "v.mp4", tmp_path)
    e._d, e._done = data(g), True
    seen = []
    for near in (10.0, 30.0, 50.0, 12.0):
        p = e.pick(20.0, near)
        assert p and sum((b - a) / E.SLOW for a, b in p) >= 20.0
        assert all(x != y for x, y in zip(p, p[1:])), "jamais le même moment deux fois de suite"
        assert all(b > a for a, b in p), "toujours en avant"
        seen += p
    counts = sorted(e.used.values())
    assert counts[-1] - counts[0] <= 1, "chaque moment le moins souvent possible sur toute la vidéo"


def test_trop_peu_de_moments_image_fixe(tmp_path):
    e = E.Ecoute(tmp_path / "v.mp4", tmp_path)
    e._d, e._done = data([0.05] * 40 + [0.002] * 12 + [0.05] * 40), True    # 1,5 s seulement
    assert e.pick(20.0, 5.0) == []          # → image fixe bouche fermée, jamais une boucle


def test_mediapipe_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(E, "_python", lambda: None)
    assert E.measure(tmp_path / "v.mp4", tmp_path) is None
