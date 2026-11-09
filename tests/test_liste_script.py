"""Script de live → liste « Récupérer médias » : format exact, adresses jamais inventées, noms propres."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("lds", Path(__file__).parents[1] / "scripts" / "liste_depuis_script.py")
L = importlib.util.module_from_spec(spec)
spec.loader.exec_module(L)


class FakeAI:
    ok = True

    def __init__(self, rep):
        self.rep = rep

    def json(self, prompt, **k):
        return self.rep

    def usage_line(self):
        return "IA : 1 demande(s)"


def test_list_from_script(tmp_path, monkeypatch):
    s = tmp_path / "script.txt"
    s.write_text("Ok écoutez. En 1981 Mitterrand est élu. Le 9 septembre 2012, Hollande promet d'inverser la courbe "
                 "du chômage. Source : https://www.slate.fr/story/129518/inversion-courbe-chomage et le reste.",
                 encoding="utf-8")
    rep = {"sujets": [{"n": 1, "titre": "45 ans de promesses", "medias": [
        {"type": "video", "nom": "v101 Mitterrand 1981!", "recherche": "10 mai 1981 Mitterrand élu | INA", "duree": 99999},
        {"type": "photo", "nom": "p101_mitterrand", "wiki": "fr:François Mitterrand"},
        {"type": "article", "nom": "a101_slate", "url": "https://www.slate.fr/story/129518/inversion-courbe-chomage"},
        {"type": "article", "nom": "a102_invente", "url": "https://www.inventé.example/faux"},   # pas dans le script
        {"type": "photo", "nom": "p_bad", "wiki": "Mitterrand"},                                # format invalide
        "n'importe quoi"]}]}
    import montage.ai as A
    monkeypatch.setattr(A, "AI", lambda: FakeAI(rep))
    monkeypatch.setattr(L, "bing_article", lambda q, lang: "")
    out = tmp_path / "liste.txt"
    monkeypatch.setattr("sys.argv", ["x", str(s), str(out)])
    assert L.main() == 0
    lines = [x for x in out.read_text(encoding="utf-8").splitlines() if x and not x.startswith("#")]
    assert lines[0] == "1 | video | v101_mitterrand_1981 | 10 mai 1981 Mitterrand élu INA | 1200"
    assert lines[1] == "1 | photo | p101_mitterrand | fr:François_Mitterrand"
    assert lines[2] == "1 | article | a101_slate | https://www.slate.fr/story/129518/inversion-courbe-chomage"
    assert len(lines) == 3                    # adresse inventée et photo mal formée écartées
    assert all(len(x.split("|")) in (4, 5) for x in lines)


def test_script_too_short_or_ai_garbage(tmp_path, monkeypatch):
    s = tmp_path / "script.txt"
    s.write_text("court", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["x", str(s), str(tmp_path / "o.txt")])
    assert L.main() == 1
    s.write_text("Un vrai script assez long pour être lu par le programme, avec des sujets et des noms. " * 3,
                 encoding="utf-8")
    import montage.ai as A
    monkeypatch.setattr(A, "AI", lambda: FakeAI("pas du json"))
    assert L.main() == 1 and not (tmp_path / "o.txt").exists()
