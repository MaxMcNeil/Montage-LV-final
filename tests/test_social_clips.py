"""Vidéos postées sur Telegram / Reddit : extraits possibles quand YouTube bloque GitHub."""
import csv

from montage.finder import read_posts, social_clips
import montage.__main__ as M


def _csv(tmp_path, rows):
    f = tmp_path / "posts.csv"
    with open(f, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["plateforme", "chaine", "date", "texte", "url", "audience", "commentaires", "media", "position",
                    "video_url", "duree"])
        w.writerows(rows)
    return f


def test_posts_with_video_become_clips(tmp_path):
    f = _csv(tmp_path, [
        ["telegram", "@news", "2026-10-29", "Vidéo : la Chine accusée", "https://t.me/news/5", 900, 0, "vidéo", "pour",
         "https://t.me/news/5", "33"],
        ["reddit", "r/x", "2026-10-29", "Texte seul", "https://reddit.com/r/x/1", 50, 3, "", "", "", ""],
        ["telegram", "@b", "2026-10-29", "Contre", "https://t.me/b/2", 10, 0, "vidéo", "contre", "https://t.me/b/2", "20"],
    ])
    posts = read_posts([f])
    clips = social_clips(posts)
    assert [c["source_url"] for c in clips] == ["https://t.me/news/5"]       # sans vidéo / « contre » : écartés
    c = clips[0]
    assert c["end"] == 33 and c["quote"].startswith("Vidéo") and c["platform"] == "telegram"


def test_old_posts_csv_without_video_columns_still_read(tmp_path):
    f = tmp_path / "posts.csv"
    with open(f, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["plateforme", "chaine", "date", "texte", "url", "audience", "commentaires", "media", "position"])
        w.writerow(["reddit", "r/x", "2026-10-29", "ancien format", "https://reddit.com/1", 5, 0, "", ""])
    posts = read_posts([f])
    assert posts and social_clips(posts) == []


def test_search_detail_explains_everything():
    res = {"clips": [{"platform": "youtube", "source_url": "https://youtu.be/x"}, {"source_url": "https://dai.ly/y"}],
           "articles": [{}], "social": {"telegram": "ok : 3 message(s)", "reddit": "ok : 2 discussion(s)"}}
    d = M._search_detail(res, [{"source_url": "https://t.me/a/1"}])
    assert "vidéos : 2 (dont 1 YouTube)" in d and "Telegram : ok" in d and "Reddit : ok" in d
    assert "1 vidéo(s) postée(s)" in d and "articles retenus : 1" in d


def test_download_fallback_whole_video_then_cut(monkeypatch, tmp_path):
    """Hébergeur qui refuse les sections : vidéo entière puis coupe exacte (jamais pour YouTube)."""
    from montage import assets
    calls = []

    class R:
        def __init__(self, rc=1, err="ERROR: unsupported"):
            self.returncode, self.stderr = rc, err

    def fake_run(cmd, **k):
        calls.append(cmd)
        if "--download-sections" in cmd:
            return R()
        if cmd[:3] == [assets.sys.executable, "-m", "yt_dlp"]:
            out = [x for x in cmd if x.endswith("%(ext)s")][0].replace("%(ext)s", "mp4")
            open(out, "wb").write(b"x" * 30_000)
            return R(0, "")
        if cmd[0] == "ffmpeg":
            open(cmd[-1], "wb").write(b"y" * 30_000)
            return R(0, "")
        return R()
    monkeypatch.setattr(assets.subprocess, "run", fake_run)
    f = assets.download_section("https://t.me/news/5", 0.0, 20.0, tmp_path / "c")
    assert f and f.name == "c.mp4" and any(c[0] == "ffmpeg" for c in calls)
    calls.clear()
    assert assets.download_section("https://www.youtube.com/watch?v=x", 0.0, 20.0, tmp_path / "y") is None
    assert not any(c[0] == "ffmpeg" for c in calls)
