"""Vidéo jointe longue : le plan voit sa transcription du début À LA FIN (plus de coupure après 60 phrases)."""
from montage.plan import describe_attachments, video_lines


def test_long_video_covered_to_the_end():
    ss = [{"t0": i * 4.0, "t1": i * 4.0 + 3.5, "text": f"phrase {i} sur le sujet du reportage"} for i in range(400)]
    att = [{"id": "vid1", "kind": "video", "name": "reportage.mp4", "duration": 1600, "sentences": ss}]
    txt = describe_attachments(att)
    assert "-1600s]" in txt                                                   # la fin est bien là
    assert "[0-" in txt
    assert len(txt) < 20000                                                   # taille raisonnable


def test_short_video_unchanged():
    ss = [{"t0": 0, "t1": 4, "text": "Bonjour."}, {"t0": 5, "t1": 9, "text": "Au revoir."}]
    assert video_lines(ss) == "[0-4s] Bonjour. / [5-9s] Au revoir."
