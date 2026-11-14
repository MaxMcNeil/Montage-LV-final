"""Pack d'animations de la chaîne (transitions, raccords, like/abonnement, écran de fin) : placement et pose."""
import subprocess
from pathlib import Path

from montage import pack as PK
from montage.timeline import Atom, Segment

ROOT = Path(__file__).resolve().parents[1]


def seg(kind, out0, dur, atoms=None):
    s = Segment(kind=kind, out0=out0, n=int(round(dur * 30)))
    s.atoms = atoms or [Atom(0.0, dur)]
    return s


def timeline():
    """20 min : toi plein cadre avec une vraie coupe toutes les 20 s, un extrait à 60 s, une carte à côté à 300 s."""
    segs, t, src = [], 0.0, 0.0
    for k in range(60):
        if k == 3:
            segs.append(seg("insert", t, 20.0)); t += 20.0
            continue
        if k == 15:
            segs.append(seg("split", t, 20.0, [Atom(src, src + 20)])); t += 20.0; src += 21
            continue
        segs.append(seg("full", t, 20.0, [Atom(src, src + 10), Atom(src + 11, src + 21)])); t += 20.0; src += 22
    return segs, t


def test_pack_seulement_pour_la_chaine_qui_l_a():
    assert PK.find("fr") is not None, "le pack FR doit être complet dans chaines/fr/habillage"
    assert PK.find("ar") is None and PK.find("") is None and PK.find("it") is None


def test_placement_jamais_sur_un_extrait_ni_une_carte():
    segs, total = timeline()
    chaps = [200.0, 500.0, 800.0, 1000.0]
    words = [{"w": "non", "t0": 150.0, "t1": 150.3}]
    ev = PK.plan(segs, chaps, words, total, "ma_video")
    busy = [(s.out0, s.out0 + s.dur) for s in segs if s.kind != "full"]
    for e in ev:
        assert not any(a - 0.4 < e["t"] + e["dur"] and e["t"] < b + 0.4 for a, b in busy), e
        assert 3 < e["t"] < total - 20
    kinds = [e["kind"] for e in ev]
    assert kinds.count("cta") == 1
    assert kinds.count("transition") <= 3 and kinds.count("raccord") <= 3
    cta = next(e for e in ev if e["kind"] == "cta")
    assert 45 <= cta["t"] <= 0.45 * total
    assert not any(c - 1.0 < cta["t"] + 7 and cta["t"] < c + 5.5 for c in chaps), "jamais sur un titre de chapitre"
    rac = sorted(e["t"] for e in ev if e["kind"] == "raccord")
    assert all(b - a >= 89 for a, b in zip(rac, rac[1:])), "raccords espacés d'au moins 1 min 30"
    assert sum(1 for e in ev if e.get("style") == "R2") <= 1, "tampon NON : une fois au plus"


def test_tampon_non_seulement_si_tu_dis_non():
    segs, total = timeline()
    ev = PK.plan(segs, [], [{"w": "bonjour", "t0": 5.0, "t1": 5.3}], total, "v")
    assert not any(e.get("style") == "R2" for e in ev)


def test_variete_d_une_video_a_l_autre():
    segs, total = timeline()
    chaps = [200.0, 500.0, 800.0]
    seen = set()
    for name in ("moi_NC_20261101", "moi_NC_20261102", "moi_NC_20261103", "moi_NC_20261104", "moi_NC_20261105",
                 "moi_NC_20261106"):
        ev = PK.plan(segs, chaps, [], total, name)
        seen.add(tuple((e["kind"], e.get("style"), round(e["t"])) for e in ev))
        assert ev == PK.plan(segs, chaps, [], total, name), "même vidéo → même habillage (relance identique)"
    assert len(seen) >= 3, "le style et les moments doivent changer d'une vidéo à l'autre"


def test_like_abonnement_sans_son():
    assert "CTA_Like-Abonne-toi" in PK.MUET
    assert not (ROOT / "chaines/fr/habillage/sons/CTA_Like-Abonne-toi.wav").exists()


def _video(p, w, h, d):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=s={w}x{h}:r=30:d={d}", "-f", "lavfi",
                    "-i", f"sine=f=200:d={d}:r=48000", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-ac", "2", "-shortest", "-metadata", "comment=montage-lv-final;logo=h", str(p)],
                   check=True)


def test_pose_reelle_et_repli(tmp_path):
    d = PK.find("fr")
    v = tmp_path / "final.mp4"
    _video(v, 1280, 720, 14)
    ev = [{"kind": "transition", "file": "T3_Transition_Coup-de-Sabre", "t": 2.0, "dur": 1.25, "style": "T3"},
          {"kind": "raccord", "file": "R1_Raccord_Flash-Logo", "t": 5.0, "dur": 0.95, "style": "R1"},
          {"kind": "cta", "file": "CTA_Like-Abonne-toi", "t": 6.5, "dur": 7.0}]
    ok, why = PK.apply(v, ev, d, tmp_path)
    assert ok, why
    assert abs(PK._dur(v) - 34.0) < 0.5, "vidéo + écran de fin de 20 s"
    assert PK._size(v) == (1280, 720)
    tag = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format_tags=comment", "-of", "csv=p=0", str(v)],
                         capture_output=True, text=True).stdout
    assert "montage-lv-final" in tag, "l'étiquette « logo incrusté » doit rester dans le fichier"
    # vidéo verticale : jamais touchée
    vv = tmp_path / "vert.mp4"
    _video(vv, 720, 1280, 4)
    size0 = vv.stat().st_size
    ok, _ = PK.apply(vv, ev, d, tmp_path)
    assert not ok and vv.stat().st_size == size0
    # pack abîmé : la vidéo d'origine est gardée
    v2 = tmp_path / "f2.mp4"
    _video(v2, 1280, 720, 6)
    size0 = v2.stat().st_size
    ok, why = PK.apply(v2, [{"kind": "raccord", "file": "N_EXISTE_PAS", "t": 2.0, "dur": 0.9}], d, tmp_path)
    assert not ok and v2.stat().st_size == size0, why
