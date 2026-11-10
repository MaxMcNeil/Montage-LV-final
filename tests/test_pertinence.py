"""Tes photos / vidéos jointes vont là où tu parles VRAIMENT de leur sujet."""
from montage.pertinence import fix_inserts, fix_visuals

S = ["Six présidents et toujours le même tour de magie.",
     "En 1983 le plan de rigueur pour préparer l'euro.",
     "Je n'accepte pas la fatalité du chômage, disait Chirac en 1995.",
     "Et l'histoire des 105 000 euros d'amende pour un homme chez lui.",
     "Je ne veux plus de femmes et d'hommes dans les rues, dans les bois, promettait Macron à Orléans.",
     "Aujourd'hui Marine Le Pen promet un budget miracle.",
     "Et les Français y croient encore."]
SENTS = [{"i": i, "t0": i * 5.0, "t1": i * 5.0 + 4, "text": t} for i, t in enumerate(S)]


def test_photo_le_pen_va_ou_tu_la_cites():
    v = [{"kind": "attachment", "attachment": "img1", "s0": 1, "s1": 1, "label": "Marine Le Pen"}]
    n = fix_visuals(v, {"img1": {"name": "17_p108_le_pen.jpg", "label": "Marine Le Pen"}}, SENTS, [])
    assert n == 1 and v[0]["s0"] == 5


def test_videos_apres_le_bon_sujet():
    by = {"v1": {"name": "03_Le scandale des105000euros.mp4", "label": "", "description": "",
                 "sentences": [{"t0": 0, "t1": 5, "text": "Une amende de 105 000 euros pour avoir hébergé des amis"}]},
          "v2": {"name": "27_v109_macron_orleans_2017_rues_bois.mp4", "label": "Emmanuel Macron à Orléans",
                 "description": "", "sentences": []}}
    ins = [{"attachment": "v1", "after": 2}, {"attachment": "v2", "after": 1}]
    fix_inserts(ins, by, SENTS, [])
    assert ins[0]["after"] == 3 and ins[1]["after"] == 4


def test_deja_bien_place_ne_bouge_pas():
    v = [{"kind": "attachment", "attachment": "img1", "s0": 2, "s1": 2, "label": "Jacques Chirac"}]
    assert fix_visuals(v, {"img1": {"name": "p102_chirac.jpg"}}, SENTS, []) == 0 and v[0]["s0"] == 2
