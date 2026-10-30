"""Photo Wikimedia : jamais la photo d'un autre sujet trouvé par une recherche dans le texte (bug « Pegasus »)."""
from montage import assets


class R:
    def __init__(self, d):
        self.d, self.content = d, b"x" * 9000

    def json(self):
        return self.d


def _fake(hits):
    seen = {}

    def get(url, params=None, timeout=None):
        params = params or {}
        if "wikidata" in url:
            return R({"claims": {}})
        if params.get("list") == "search":
            return R({"query": {"search": [{"title": t} for t in hits]}})
        if params.get("titles"):
            t = params["titles"]
            seen.setdefault("titles", []).append(t)
            if t == "Pegasus":
                return R({"query": {"pages": {"1": {"title": "Pegasus", "pageprops": {"disambiguation": ""}}}}})
            return R({"query": {"pages": {"2": {"title": t, "pageimage": t.replace(" ", "_") + ".jpg"}}}})
        return R({})
    return get, seen


def test_search_hit_that_does_not_name_subject_is_refused(monkeypatch, tmp_path):
    get, seen = _fake(["Adrien Quatennens"])
    monkeypatch.setattr(assets, "_get", get)
    monkeypatch.setattr(assets, "_commons_file", lambda n: {"url": "https://u/" + n, "credit": "c"})
    assert assets.wiki_image("Pegasus", ["fr"], tmp_path / "p") is None


def test_search_hit_naming_subject_is_used(monkeypatch, tmp_path):
    get, seen = _fake(["Adrien Quatennens", "Pegasus (logiciel espion)"])
    monkeypatch.setattr(assets, "_get", get)
    monkeypatch.setattr(assets, "_commons_file", lambda n: {"url": "https://u/" + n, "credit": "c"})
    r = assets.wiki_image("Pegasus", ["fr"], tmp_path / "p")
    assert r and r["title"] == "Pegasus (logiciel espion)"
