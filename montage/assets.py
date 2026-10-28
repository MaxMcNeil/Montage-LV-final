"""Récupération des médias : tes pièces jointes, photos libres de droits (Wikimedia Commons), extraits vidéo et
articles trouvés par Vid-o-presse-finder. Tout est gratuit ; chaque échec est simplement ignoré (le montage continue)."""
from __future__ import annotations

import csv
import html
import io
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

import requests

from .config import FPS, SAMPLE_RATE, SIZE
from .transcribe import sentences, transcribe
from .util import IMAGE_EXT, VIDEO_EXT, frames, probe, q, run

log = logging.getLogger("montage.assets")
UA = {"User-Agent": "Montage-LV-final/1.0 (montage video automatique; https://github.com/MaxMcNeil)"}


# ------------------------------------------------------------------ pièces jointes
def list_attachments(folder: Path) -> list[dict]:
    out = []
    if not folder.is_dir():
        return out
    for p in sorted(folder.rglob("*")):
        if not p.is_file():
            continue
        ext = p.suffix.lower()
        kind = "image" if ext in IMAGE_EXT else ("video" if ext in VIDEO_EXT else None)
        if kind:
            out.append({"id": f"{'img' if kind == 'image' else 'vid'}{len([o for o in out if o['kind'] == kind]) + 1}",
                        "kind": kind, "name": p.name, "path": str(p)})
    return out


def _jpeg_bytes(img, max_side=1024) -> bytes:
    im = img.copy()
    im.thumbnail((max_side, max_side))
    b = io.BytesIO()
    im.save(b, "JPEG", quality=85)
    return b.getvalue()


def describe_attachments(att: list, ai, work: Path, lang: str) -> None:
    """Décrit chaque pièce jointe (IA qui regarde l'image) ; transcrit les vidéos jointes."""
    from .panels import open_image
    for a in att:
        img = None
        if a["kind"] == "image":
            img = open_image(a["path"])
            if img is None:
                a["broken"] = True
                continue
            a["w"], a["h"] = img.size
        else:
            try:
                info = probe(a["path"])
                a["duration"] = info["duration"]
                a["has_audio"] = info["audio"]
                fr = work / f"{a['id']}_frame.jpg"
                run(["ffmpeg", "-y", "-ss", f"{min(3.0, info['duration'] / 3):.2f}", "-i", a["path"], "-frames:v", "1", fr])
                img = open_image(fr)
                if info["audio"]:
                    t = transcribe(Path(a["path"]), work, None, tag=a["id"])
                    a["lang"] = t.get("lang")
                    a["sentences"] = [{"t0": s["t0"], "t1": s["t1"], "text": s["text"]} for s in sentences(t["words"])]
            except Exception as e:  # noqa: BLE001
                log.warning("vidéo jointe illisible %s : %s", a["name"], e)
                a["broken"] = True
                continue
        if img is not None and ai and ai.ok:
            j = ai.json(
                f"Décris cette {'image' if a['kind'] == 'image' else 'image tirée d’une vidéo'} (fichier « {a['name']} ») "
                f"pour un monteur vidéo. Réponds en JSON : {{\"description\": \"ce que l'on voit, en une phrase (personnes "
                f"reconnaissables si leur nom est écrit ou évident, lieu, objet, document, texte lisible)\", "
                f"\"label\": \"légende de 2 à 6 mots en langue « {lang} »\", \"document\": true si c'est une capture d'écran, "
                f"un document, un logo ou un graphique (à ne pas rogner)}}",
                image=("image/jpeg", _jpeg_bytes(img)), media_key=f"{a['name']}|{os.path.getsize(a['path'])}")
            if isinstance(j, dict):
                a["description"] = str(j.get("description") or "")[:400]
                a["label"] = str(j.get("label") or "")[:60]
                a["contain"] = bool(j.get("document"))
    att[:] = [a for a in att if not a.get("broken")]


# ------------------------------------------------------------------ Wikimedia Commons (photos libres)
def _get(url, params=None, timeout=20):
    try:
        r = requests.get(url, params=params, headers=UA, timeout=timeout)
        if r.status_code == 200:
            return r
    except requests.RequestException:
        pass
    return None


def _strip(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def _commons_file(name: str) -> dict | None:
    r = _get("https://commons.wikimedia.org/w/api.php", {
        "action": "query", "format": "json", "titles": f"File:{name}", "prop": "imageinfo",
        "iiprop": "url|extmetadata|size|mime", "iiurlwidth": 1600})
    if not r:
        return None
    for p in (r.json().get("query", {}).get("pages") or {}).values():
        ii = (p.get("imageinfo") or [None])[0]
        if not ii or "missing" in p and p.get("imagerepository") != "shared":
            continue
        meta = ii.get("extmetadata") or {}
        artist = _strip((meta.get("Artist") or {}).get("value", ""))[:60]
        lic = _strip((meta.get("LicenseShortName") or {}).get("value", ""))[:30]
        return {"url": ii.get("thumburl") or ii.get("url"), "credit": " / ".join(x for x in (artist, lic) if x),
                "w": ii.get("width", 0), "h": ii.get("height", 0)}
    return None


def _relevant(fname: str, title: str, query: str) -> bool:
    """L'image d'un article Wikipédia n'est pas toujours celle du sujet (ex. article « RQTH » illustré par la photo
    d'un conseil départemental). On exige qu'un mot du sujet figure dans le nom du fichier. L'image officielle
    Wikidata (P18), elle, est toujours celle du sujet."""
    from .util import norm
    stop = {"de", "la", "le", "les", "des", "du", "et", "en", "the", "of", "and", "pour", "sur", "file", "jpg", "png",
            "svg", "jpeg", "logo"}
    words = {w for w in norm(f"{title} {query}").split() if len(w) > 2 and w not in stop}
    fn = set(norm(re.sub(r"\.[a-z]+$", "", fname, flags=re.I)).split())
    return bool(words & fn)


def wiki_image(query: str, langs: list[str], dest: Path) -> dict | None:
    """Photo libre de droits de l'article Wikipédia (image principale, ou P18 Wikidata). Seules les images hébergées
    sur Wikimedia Commons (licences libres) sont utilisées ; le crédit est affiché sous la photo."""
    if not query:
        return None
    for lang in dict.fromkeys([x for x in langs if x] + ["en"]):
        base = f"https://{lang}.wikipedia.org/w/api.php"
        title = query
        for attempt in range(2):
            r = _get(base, {"action": "query", "format": "json", "redirects": 1, "titles": title,
                            "prop": "pageimages|pageprops", "piprop": "name", "ppprop": "wikibase_item|disambiguation"})
            if not r:
                break
            pages = list((r.json().get("query", {}).get("pages") or {}).values())
            page = pages[0] if pages else {}
            if "missing" in page or (page.get("pageprops") or {}).get("disambiguation") is not None:
                if attempt == 0:
                    s = _get(base, {"action": "query", "format": "json", "list": "search", "srsearch": query, "srlimit": 1})
                    hits = (s.json().get("query", {}).get("search") or []) if s else []
                    if hits:
                        title = hits[0]["title"]
                        continue
                break
            names = []
            if page.get("pageimage") and _relevant(page["pageimage"], page.get("title", ""), query):
                names.append(page["pageimage"])  # image d'illustration : gardée seulement si elle parle du sujet
            qid = (page.get("pageprops") or {}).get("wikibase_item")
            if qid:
                w = _get("https://www.wikidata.org/w/api.php", {"action": "wbgetclaims", "format": "json", "entity": qid,
                                                                 "property": "P18"})
                for c in ((w.json().get("claims") or {}).get("P18") or []) if w else []:
                    v = ((c.get("mainsnak") or {}).get("datavalue") or {}).get("value")
                    if v and v.replace(" ", "_") not in [n.replace(" ", "_") for n in names]:
                        names.append(v)
            for n in names:
                info = _commons_file(n)
                if not info or not info.get("url"):
                    continue
                img = _get(info["url"], timeout=40)
                if not img or len(img.content) < 5000:
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(img.content)
                return {"path": str(dest), "credit": f"{info['credit']} · Wikimedia Commons".strip(" ·/"),
                        "title": page.get("title", query)}
            break
    return None


# ------------------------------------------------------------------ Vid-o-presse-finder
def press_search(p: dict, lang: str, work: Path, minutes: float = 9.0, quota_file: Path | None = None) -> dict:
    """Lance une recherche Vid-o-presse-finder (processus séparé, limité dans le temps). Retourne clips + articles.
    quota_file : copie privée de l'état des quotas (recherches en parallèle), refusionnée ensuite."""
    out = work / "press"
    sid = f"s{abs(hash((p['target'], p['claim']))) % 10_000:04d}"
    langs = p.get("langs") or ""
    langs = ",".join(dict.fromkeys([x.strip() for x in f"{lang},{langs},en".split(",") if x.strip()]))[:20]
    cmd = [sys.executable, "-m", "quote_finder", "--target", p["target"], "--claim", p.get("claim", ""),
           "--type", p.get("type") if p.get("type") in ("personne", "pays", "entite", "sujet") else "auto",
           "--speakers", "auto",
           "--authority", "moyenne" if p.get("type") == "personne" else "toutes",   # soupçons / rumeurs : toutes les voix "--max-videos", "5", "--max-articles", "8",
           "--langs", langs, "--max-minutes", str(minutes), "--out", str(out), "--batch-id", "lot", "--search-id", sid]
    log.info("Recherche presse : %s | %s", p["target"], p.get("claim", ""))
    res = {"clips": [], "articles": [], "posts": [], "error": "", "social": {}}
    try:
        env = dict(os.environ)
        if quota_file:
            env["QF_QUOTA_FILE"] = str(quota_file)
        r = subprocess.run(cmd, timeout=minutes * 60 + 240, capture_output=True, text=True, env=env)
        if r.returncode not in (0,):
            tail = [x for x in (r.stderr or "").strip().splitlines() if x.strip()][-3:]
            res["error"] = {2: "aucune clé IA (secret GEMINI_API_KEYS)", 3: "IA indisponible pour préparer la recherche",
                            4: "erreur interne de la recherche"}.get(r.returncode, f"code {r.returncode}")
            log.warning("recherche presse « %s » : %s — %s", p["target"], res["error"], " | ".join(tail)[-300:])
    except subprocess.TimeoutExpired:
        res["error"] = "trop longue : arrêtée"
        log.warning("recherche presse « %s » arrêtée (temps dépassé)", p["target"])
    except (subprocess.SubprocessError, OSError) as e:
        res["error"] = f"interrompue ({type(e).__name__})"
        log.warning("recherche presse interrompue : %s", e)
    d = out / "lot" / sid
    try:
        res["clips"] = json.loads((d / "montage.json").read_text(encoding="utf-8")).get("clips", [])
    except (OSError, ValueError):
        pass
    try:
        with open(d / "articles.csv", encoding="utf-8-sig") as f:
            res["articles"] = list(csv.DictReader(f))
    except OSError:
        pass
    from .finder import read_posts
    res["posts"] = read_posts([d / "posts.csv"]) if (d / "posts.csv").exists() else []
    try:
        res["social"] = ((json.loads((d / "results.json").read_text(encoding="utf-8")).get("plan") or {})
                         .get("diag") or {}).get("social") or {}
    except (OSError, ValueError):
        pass
    if not res["error"] and (d / "ERREUR.txt").exists():
        res["error"] = (d / "ERREUR.txt").read_text(encoding="utf-8", errors="replace").strip().splitlines()[0][:160]
    log.info("  → %d extrait(s) vidéo, %d article(s), %d message(s) Telegram/Reddit%s", len(res["clips"]),
             len(res["articles"]), len(res["posts"]), f" — ⚠ {res['error']}" if res["error"] else "")
    return res


def og_image(url: str, dest: Path) -> str | None:
    r = _get(url, timeout=20)
    if not r:
        return None
    m = re.search(r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\'][^>]+content=["\']([^"\']+)', r.text, re.I) \
        or re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'](?:og:image|twitter:image)', r.text, re.I)
    if not m:
        return None
    src = html.unescape(m.group(1))
    if src.startswith("//"):
        src = "https:" + src
    img = _get(src, timeout=30)
    if not img or len(img.content) < 8000:
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(img.content)
    return str(dest)


def thumbnail(c: dict, dest: Path) -> str | None:
    """Vignette de la vidéo source (YouTube : toujours accessible, même quand la vidéo est bloquée)."""
    vid = c.get("video_id") or ""
    if c.get("platform") == "youtube" or "youtu" in (c.get("source_url") or ""):
        for q_ in ("maxresdefault", "sddefault", "hqdefault"):
            r = _get(f"https://i.ytimg.com/vi/{vid}/{q_}.jpg", timeout=20)
            if r and len(r.content) > 6000:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(r.content)
                return str(dest)
        return None
    return og_image(c.get("source_url", ""), dest)


def download_section(url: str, a: float, b: float, dest: Path) -> Path | None:
    """Télécharge uniquement le passage [a, b] (yt-dlp). YouTube bloque souvent les serveurs GitHub : plusieurs façons
    de se présenter sont essayées (et tes cookies / ton proxy si tu les as mis en secrets)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    base = [sys.executable, "-m", "yt_dlp", "--no-warnings", "--no-playlist", "--download-sections", f"*{a:.2f}-{b:.2f}",
            "--force-keyframes-at-cuts", "-f", "bv*[height<=1080]+ba/b[height<=1080]/b", "--merge-output-format", "mp4",
            "-o", f"{dest}.%(ext)s"]
    if os.environ.get("YT_PROXY_URL") and "youtu" in url:
        base += ["--proxy", os.environ["YT_PROXY_URL"]]
    ck = os.environ.get("YT_COOKIES_FILE")
    if ck and os.path.exists(ck) and os.path.getsize(ck) > 50:  # cookies d'un compte YouTube : passe le blocage « bot »
        base += ["--cookies", ck]
    variants = [[]]
    if "youtu" in url:
        variants += [["--extractor-args", "youtube:player_client=tv"], ["--extractor-args", "youtube:player_client=mweb"]]
    last = "?"
    for v in variants:
        for f in dest.parent.glob(dest.name + ".*"):
            f.unlink()
        try:
            r = subprocess.run(base + v + [url], capture_output=True, text=True, timeout=240)
            last = ((r.stderr or "").strip().splitlines() or ["?"])[-1][:160]
        except (subprocess.SubprocessError, OSError) as e:
            last = str(e)
            continue
        f = next(iter(p for p in dest.parent.glob(dest.name + ".*") if not p.name.endswith(".part")), None)
        if f is not None and f.stat().st_size > 20_000:
            return f
        if "not a bot" not in last.lower() and "sign in" not in last.lower() and "403" not in last:
            break  # autre erreur (vidéo supprimée…) : inutile d'insister
    log.warning("téléchargement refusé (%s) : %s", url, last)
    return None


# ------------------------------------------------------------------ extraits insérés (pendant tes silences)
def choose_bounds(sents: list, want0: float, want1: float, maxd: float, dur: float) -> tuple[float, float]:
    """Début et fin sur des phrases complètes (jamais de phrase amputée), au plus maxd secondes (souplesse si une
    seule phrase est plus longue)."""
    if not sents:
        a = max(0.0, want0)
        b = min(dur, want1 if want1 > a + 2 else a + maxd)
        return a, min(b, a + maxd)
    first = next((s for s in sents if s["t0"] >= want0 - 1.0), sents[0])
    a = max(0.0, first["t0"] - 0.3)
    b = None
    lim = want1 + 1.0 if want1 > want0 + 2 else 1e9
    for s in sents:
        if s["t0"] < first["t0"]:
            continue
        if s["t1"] - a <= maxd and s["t1"] <= lim:
            b = s["t1"]
        elif b is None:
            b = min(s["t1"], a + maxd * 1.6)
            break
        else:
            break
    b = min(dur, (b or a + maxd) + 0.35)
    return a, b


def translate(ai, sents: list, src: str, dst: str) -> list:
    if not sents or not ai or not ai.ok:
        return sents
    j = ai.json(
        f"Traduis fidèlement ces sous-titres ({src or 'langue détectée'}) en langue « {dst} »"
        f"{' (arabe littéraire simple)' if dst == 'ar' else ''}, phrase par phrase, de façon naturelle et concise. "
        f"Réponds en JSON : {{\"lines\": [\"…\", …]}} (même nombre de lignes, même ordre).\n"
        + "\n".join(f"{i}. {s['text']}" for i, s in enumerate(sents)))
    lines = (j or {}).get("lines") if isinstance(j, dict) else None
    if not isinstance(lines, list) or len(lines) != len(sents):
        return sents
    return [dict(s, text=str(t).strip() or s["text"]) for s, t in zip(sents, lines)]


def prepare_insert(src: Path, a: float, b: float, orient: str, work: Path, name: str, lang: str, ai,
                   clip_sents: list | None = None, clip_lang: str | None = None) -> dict | None:
    """Normalise l'extrait [a, b] : image au format de sortie (sans déformation, fond flou), 30 i/s, son égalisé.
    Ajoute les sous-titres (traduits si l'extrait n'est pas dans la langue de la vidéo)."""
    W, H = SIZE[orient]
    d = q(b - a)
    if d < 2.0:
        return None
    vout, aout = work / f"{name}.mp4", work / f"{name}.wav"
    info = probe(src)
    if info["duration"] and b > info["duration"]:   # jamais au-delà de la fin de la vidéo jointe
        b = info["duration"]
        d = q(b - a)
        if d < 2.0:
            return None
    n = frames(d)
    from .media import HDR_TM, is_hdr
    tm = (HDR_TM + ",") if is_hdr(src) else ""   # vidéo jointe HDR (téléphone récent) : couleurs normales, pas délavées
    vf = (f"[0:v]{tm}fps={FPS},split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
          f"scale={W // 8}:{H // 8},boxblur=8:2,scale={W}:{H},eq=brightness=-0.15:saturation=0.6[bg];"
          f"[b]scale={W}:{H}:force_original_aspect_ratio=decrease,setsar=1[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,"
          f"tpad=stop_mode=clone:stop_duration=2,trim=end_frame={n},setpts=N/{FPS}/TB,format=yuv420p[v]")
    try:
        run(["ffmpeg", "-y", "-ss", f"{a:.3f}", "-t", f"{d + 0.5:.3f}", "-i", src, "-filter_complex", vf, "-map", "[v]",
             "-frames:v", n, "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-an", vout], timeout=900)
        if info["audio"]:
            run(["ffmpeg", "-y", "-ss", f"{a:.3f}", "-t", f"{d:.3f}", "-i", src, "-vn", "-af",
                 "loudnorm=I=-16:TP=-1.5:LRA=11", "-ac", "2", "-ar", SAMPLE_RATE, "-c:a", "pcm_s16le", aout], timeout=600)
        else:
            run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"anullsrc=r={SAMPLE_RATE}:cl=stereo", "-t", f"{d:.3f}",
                 "-c:a", "pcm_s16le", aout])
    except Exception as e:  # noqa: BLE001
        log.warning("extrait %s inutilisable : %s", name, e)
        return None
    subs = []
    if info["audio"]:
        if clip_sents is None:
            try:
                t = transcribe(aout, work, None, tag=f"{name}_asr")
                clip_lang = t.get("lang")
                clip_sents = sentences(t["words"])
                rel = [{"t0": s["t0"], "t1": s["t1"], "text": s["text"]} for s in clip_sents]
            except Exception as e:  # noqa: BLE001
                log.warning("sous-titres de l'extrait %s impossibles : %s", name, e)
                rel = []
        else:
            rel = [{"t0": s["t0"] - a, "t1": s["t1"] - a, "text": s["text"]} for s in clip_sents
                   if s["t1"] > a + 0.2 and s["t0"] < b - 0.2]
        rel = [dict(s, t0=max(0.0, s["t0"]), t1=min(d, s["t1"])) for s in rel if s["t1"] - s["t0"] > 0.3]
        translated = bool(clip_lang) and clip_lang[:2] != (lang or "")[:2]
        subs = translate(ai, rel, clip_lang or "", lang) if translated else rel
    return {"video": str(vout), "audio": str(aout), "duration": d, "frames": n, "subs": subs,
            "translated": bool(subs) and bool(clip_lang) and clip_lang[:2] != (lang or "")[:2], "clip_lang": clip_lang}


def is_youtube(c: dict) -> bool:
    return c.get("platform") == "youtube" or "youtu" in str(c.get("source_url") or "")


def quote_card_insert(c: dict, quote: str, orient: str, work: Path, name: str, lang: str, pw: int, ph: int) -> dict | None:
    """Extrait impossible à télécharger : la VRAIE déclaration montrée en carte plein écran pendant ton silence
    (vignette de la vidéo, citation fidèle, qui parle, média, date). Rien d'inventé : c'est la citation réelle."""
    from PIL import Image
    from .panels import open_image, render_panel
    try:
        W, H = SIZE[orient]
        img_p = thumbnail(c, work / "web" / f"{name}_thumb")
        when = str(c.get("uploaded") or c.get("date") or "")[:10]
        sub = " · ".join(x for x in (c.get("channel") or c.get("platform") or "", when) if x)
        panel = render_panel("statement", pw, ph, {"text": quote, "label": c.get("speaker") or "", "sublabel": sub,
                                                   "image": open_image(img_p) if img_p else None},
                             work / "kwcards", name)
        frame = Image.open(panel["frame"]).convert("RGBA")
        card = Image.new("RGBA", frame.size, (0, 0, 0, 0))
        if panel.get("photo") and panel.get("hole"):
            x, y, w, h = panel["hole"]
            card.paste(Image.open(panel["photo"]).convert("RGBA").resize((w, h)), (x, y))
        card.alpha_composite(frame)
        k = min(W * 0.86 / card.width, H * 0.86 / card.height, 1.6)
        card = card.resize((int(card.width * k), int(card.height * k)), Image.LANCZOS)
        from . import config as C
        bg = Image.new("RGBA", (W, H), C.NAVY_DEEP + (255,))
        bg.alpha_composite(card, ((W - card.width) // 2, (H - card.height) // 2))
        png = work / f"{name}.png"
        bg.convert("RGB").save(png)
        d = q(max(5.0, min(12.0, len(quote.split()) / 2.6 + 1.5)))
        n = frames(d)
        vout, aout = work / f"{name}.mp4", work / f"{name}.wav"
        run(["ffmpeg", "-y", "-loop", "1", "-framerate", FPS, "-i", png, "-frames:v", n, "-vf", "format=yuv420p",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-an", vout], timeout=300)
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"anullsrc=r={SAMPLE_RATE}:cl=stereo", "-t", f"{d:.3f}",
             "-c:a", "pcm_s16le", aout])
        return {"video": str(vout), "audio": str(aout), "duration": d, "frames": n, "subs": [], "translated": False,
                "clip_lang": lang, "card": True,
                "credit": {"speaker": c.get("speaker") or "", "label": sub, "url": c.get("source_url"),
                           "title": c.get("title") or "", "source": c.get("channel") or c.get("platform") or ""}}
    except Exception as e:  # noqa: BLE001
        log.warning("carte citation %s impossible : %s", name, e)
        return None


def press_clip(res: dict, orient: str, work: Path, idx: int, lang: str, ai, maxd: float, used: set) -> dict | None:
    """Meilleur extrait téléchargeable d'une recherche presse (essaie jusqu'à 4 candidats)."""
    order = {"ia-affiné": 0, "sous-titres": 0, "ia": 1}
    cands = [c for c in res.get("clips", []) if c.get("source_url") and c.get("verdict") != "denial"]
    # à précision égale : d'abord les sources qui se téléchargent bien depuis GitHub (médias, Dailymotion…), YouTube
    # ensuite (il bloque souvent) — la pertinence reste le 1er critère
    cands.sort(key=lambda c: (order.get(c.get("timing"), 2), is_youtube(c), -float(c.get("score") or 0)))
    return clip_insert(cands[:4], orient, work, f"press{idx}", lang, ai, maxd, used)


def clip_insert(cands: list, orient: str, work: Path, idx, lang: str, ai, maxd: float, used: set) -> dict | None:
    """Télécharge et prépare le premier extrait possible parmi les candidats (déclarations horodatées)."""
    for k, c in enumerate(cands):
        if (c.get("source_url"), round(c.get("start", 0))) in used:
            continue
        a0, b0 = float(c.get("in", c.get("start", 0))), float(c.get("out", c.get("end", 0)))
        if b0 - a0 < 3:
            continue
        b0 = min(b0, a0 + maxd * 2.2)  # on télécharge un peu plus, la coupe se fait en fin de phrase
        f = download_section(c["source_url"], max(0.0, a0 - 1.0), b0 + 1.5, work / f"{idx}_{k}_raw")
        if not f:
            continue
        try:
            t = transcribe(f, work, None, tag=f"{idx}_{k}_asr")
        except Exception:  # noqa: BLE001
            t = {"words": [], "lang": ""}
        ss = sentences(t["words"])
        dur = probe(f)["duration"]
        quote_start = (float(c.get("start", a0)) - max(0.0, a0 - 1.0))
        a, b = choose_bounds(ss, quote_start, dur, maxd, dur)
        ins = prepare_insert(f, a, b, orient, work, f"insert_{idx}_{k}", lang, ai, ss, t.get("lang"))
        if ins:
            used.add((c.get("source_url"), round(c.get("start", 0))))
            ins["credit"] = {"speaker": c.get("speaker") or "", "role": c.get("speaker_role") or "",
                             "source": c.get("channel") or c.get("platform") or "", "date": c.get("uploaded") or "",
                             "url": c.get("source_url"), "title": c.get("title") or "", "quote": c.get("quote") or ""}
            return ins
    return None
