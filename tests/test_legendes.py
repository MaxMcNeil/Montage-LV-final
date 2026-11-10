"""Légendes = le sujet de ton nom de fichier, jamais un détail inventé (« un enfant », « son lapin », « Pierre »)."""
from montage.assets import subject_labels


class AI:
    ok = True

    def __init__(self, labels):
        self.labels = labels

    def json(self, prompt, **k):
        return {"labels": [{"n": i, "l": l} for i, l in enumerate(self.labels)]}


def test_legendes_fideles():
    att = [{"name": "22_v103_chirac_1995_fracture_sociale.mp4", "label": "Jacques Chirac évoquant son lapin"},
           {"name": "19_p110_lescure.jpg", "label": "Portrait de Pierre Lescure"},
           {"name": "17_p108_le_pen.jpg", "label": "x"},
           {"name": "01_6a856751d0fb9433364007.avif", "label": "Nicolas Sarkozy"}]
    subject_labels(AI(["Chirac, 1995 : la fracture sociale", "Pierre Lescure", "Marine Le Pen"]), att, "fr")
    assert att[0]["label"] == "Chirac, 1995 : la fracture sociale"
    assert att[1]["label"] == "Lescure"            # prénom inventé refusé
    assert att[2]["label"] == "Le Pen"
    assert att[3]["label"] == "Nicolas Sarkozy"    # nom de téléchargement : légende de l'IA gardée


def test_sans_ia():
    att = [{"name": "20_v101_mitterrand_10mai1981_victoire.mp4", "label": "Un enfant à l'élection"}]
    subject_labels(None, att, "fr")
    assert att[0]["label"] == "Mitterrand 10 mai 1981 victoire"


def test_jamais_un_mot_qui_change_le_sens():
    att = [{"name": "27_v109_macron_orleans_2017_rues_bois.mp4", "label": ""}]
    subject_labels(AI(["Macron, Orléans 2017 : rues en bois"]), att, "fr")
    assert att[0]["label"] == "Macron orleans 2017 rues bois"
