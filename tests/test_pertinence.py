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


# cas réels du montage du 10/11 : extraits au mauvais endroit à cause des mots vagues de leurs paroles
S2 = ["1981 Mitterrand, 110 propositions pour changer la vie.",
      "Deux ans plus tard, plan de rigueur pour préparer l'euro.",
      "2012, Hollande, le 9 septembre, 20h de TF1, promet d'inverser la courbe du chômage.",
      "Les favoris, droit du sol, immigration, et surtout le miracle budgétaire du gouvernement.",
      "Roland Lescure parle d'un budget en carton-pâte.",
      "Alors la Maison Blanche n'a pas démenti le fond, les risques sont là."]
SENTS2 = [{"i": i, "t0": i * 5.0, "t1": i * 5.0 + 4, "text": t} for i, t in enumerate(S2)]


def test_cas_reels_rigueur_hollande():
    by = {"r": {"name": "21_v102_tournant_rigueur_1983.mp4", "label": "", "description": "",
                "sentences": [{"t0": 0, "t1": 9, "text": "le gouvernement doit tenir compte de la situation budgétaire "
                               "et de l'immigration, nous devons faire des efforts"}]},
          "h": {"name": "26_v108_hollande_renonce_2016.mp4", "label": "", "description": "",
                "sentences": [{"t0": 0, "t1": 9, "text": "Je suis conscient des risques. J'ai décidé de ne pas être "
                               "candidat. François Hollande"}]}}
    ins = [{"attachment": "r", "after": 3}, {"attachment": "h", "after": 5}]
    fix_inserts(ins, by, SENTS2, [])
    assert ins[0]["after"] == 1 and ins[1]["after"] == 2


def test_photo_avec_la_video_du_meme_sujet():
    from montage.pertinence import link_photos_to_videos
    sents = [dict(s, text=s["text"].replace("Roland Lescure", "Le ministre")) for s in SENTS2]   # nom mal transcrit
    by = {"p": {"name": "19_p110_lescure.jpg"}, "v": {"name": "29_v111_lescure_amiel_carton_pate.mp4"}}
    vis = [{"kind": "attachment", "attachment": "p", "s0": 1, "s1": 1, "label": "Portrait de Pierre Lescure"}]
    assert link_photos_to_videos(vis, [{"attachment": "v", "after": 4}], by, sents, []) == 1 and vis[0]["s0"] == 4
