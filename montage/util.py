from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import unicodedata
from pathlib import Path

from .config import FPS

log = logging.getLogger("montage")

WORK = Path(os.environ.get("MONTAGE_WORK", "work"))
VIDEO_EXT = (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".3gp", ".mts")
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".heic", ".heif", ".avif")


def run(cmd: list, timeout: float | None = None, check: bool = True, quiet: bool = True) -> subprocess.CompletedProcess:
    cmd = [str(c) for c in cmd]
    if cmd and cmd[0] == "ffmpeg" and "-loglevel" not in cmd:
        cmd[1:1] = ["-hide_banner", "-loglevel", "error", "-nostdin"]
    r = subprocess.run(cmd, capture_output=quiet, text=True, timeout=timeout)
    if check and r.returncode != 0:
        err = (r.stderr or "").strip().splitlines()[-12:] if quiet else []
        raise RuntimeError(f"échec de {Path(cmd[0]).name} ({r.returncode}) :\n" + "\n".join(err))
    return r


def probe(path) -> dict:
    """Durée, taille, fps, rotation, présence audio."""
    r = run(["ffprobe", "-v", "error", "-show_entries",
             "format=duration:stream=codec_type,width,height,avg_frame_rate,r_frame_rate:stream_tags=rotate:stream_side_data=rotation",
             "-of", "json", path])
    j = json.loads(r.stdout or "{}")
    v = next((s for s in j.get("streams", []) if s.get("codec_type") == "video"), {})
    a = any(s.get("codec_type") == "audio" for s in j.get("streams", []))
    w, h = int(v.get("width") or 0), int(v.get("height") or 0)
    rot = 0
    try:
        rot = int((v.get("tags") or {}).get("rotate") or 0)
    except ValueError:
        pass
    for sd in v.get("side_data_list") or []:
        if "rotation" in sd:
            try:
                rot = int(float(sd["rotation"]))
            except (TypeError, ValueError):
                pass
    if abs(rot) % 180 == 90:  # vidéo de téléphone tournée : ffmpeg l'affiche redressée
        w, h = h, w

    def fr(s):
        try:
            n, d = (s or "0/1").split("/")
            return float(n) / float(d) if float(d) else 0.0
        except ValueError:
            return 0.0
    fps = fr(v.get("avg_frame_rate")) or fr(v.get("r_frame_rate")) or FPS
    return {"duration": float((j.get("format") or {}).get("duration") or 0), "w": w, "h": h, "fps": fps, "audio": a,
            "video": bool(v)}


def q(t: float) -> float:
    """Arrondi à l'image (30 i/s) : toutes les coupes tombent pile sur une image."""
    return round(round(t * FPS) / FPS, 6)


def frames(d: float) -> int:
    return int(round(d * FPS))


def tc(t: float) -> str:
    t = max(0.0, t)
    m, s = divmod(int(t), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def load_json(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save_json(p, data) -> Path:
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def norm(s: str) -> str:
    """Comparaison souple (accents, casse, ponctuation, tatweel / diacritiques arabes)."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("ـ", "").lower()
    s = re.sub(r"[أإآ]", "ا", s)
    s = re.sub(r"[^\w]+", " ", s, flags=re.UNICODE)
    return s.strip()


def slug(s: str, n: int = 40) -> str:
    s = norm(s).replace(" ", "-")
    return (s[:n].strip("-") or "x")


def clamp(v, a, b):
    return max(a, min(b, v))
