"""Analyse de l'image : où est ton visage (pour cadrer les zooms et le cadre arrondi sans jamais te couper la tête)."""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("montage.media")


def black_start(video: Path, probe_s: float = 6.0) -> float:
    """Fin des images noires au tout début de la vidéo (0 s s'il n'y en a pas)."""
    import re
    import subprocess
    try:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-t", str(probe_s), "-i", str(video), "-an", "-vf",
                            "blackdetect=d=0.03:pic_th=0.95:pix_th=0.12", "-f", "null", "-"],
                           capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return 0.0
    m = re.search(r"black_start:\s*([\d.]+)\s+black_end:\s*([\d.]+)", r.stderr or "")
    if m and float(m.group(1)) < 0.05:
        return float(m.group(2))
    return 0.0


def face_center(video: Path, samples: int = 36) -> dict:
    """Centre du visage en coordonnées normalisées (0-1) dans l'image affichée. Défaut : centre, un peu haut."""
    default = {"found": False, "cx": 0.5, "cy": 0.38, "fh": 0.3}
    try:
        import cv2
        import numpy as np
    except ImportError:
        return default
    if not hasattr(cv2, "CascadeClassifier"):  # OpenCV 5 : détecteur déplacé → cadrage par défaut
        return default
    try:
        return _detect(cv2, np, video, samples, default)
    except Exception as e:  # noqa: BLE001
        log.warning("détection du visage impossible : %s", e)
        return default


def _detect(cv2, np, video, samples, default):
    cap = cv2.VideoCapture(str(video))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if n <= 0:
        return default
    cas = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    pts = []
    for k in range(samples):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(n * (k + 0.5) / samples))
        ok, fr = cap.read()
        if not ok or fr is None:
            continue
        h, w = fr.shape[:2]
        sc = 480.0 / max(h, w)
        small = cv2.resize(fr, (int(w * sc), int(h * sc)))
        g = cv2.equalizeHist(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY))
        faces = cas.detectMultiScale(g, 1.1, 5, minSize=(24, 24))
        if len(faces):
            x, y, fw, fh = max(faces, key=lambda f: f[2] * f[3])
            H, W = g.shape
            pts.append(((x + fw / 2) / W, (y + fh / 2) / H, fh / H))
    cap.release()
    if len(pts) < max(3, samples // 6):
        return default
    a = np.array(pts)
    return {"found": True, "cx": float(np.median(a[:, 0])), "cy": float(np.median(a[:, 1])), "fh": float(np.median(a[:, 2]))}


def make_proxy(src: Path, info: dict, work: Path) -> tuple[Path, dict]:
    """Copie de travail légère de TA vidéo, seulement si elle est lourde à monter : 4K, plus de 40 i/s, ou HDR
    (iPhone / Android récents). Sinon ta vidéo est utilisée telle quelle.
    - 4K / 60 i/s : chaque morceau du montage décode la vidéo ; en 4K HEVC la machine GitHub pourrait manquer de mémoire.
      La copie (côté court 1440 px, 30 i/s, H.264) garde une image nette même avec les zooms.
    - HDR : sans conversion, les couleurs sortent ternes / délavées. La copie est convertie en couleurs standard (SDR).
    Le temps de la vidéo est conservé à l'identique (aucun décalage son / image) : le son vient toujours de l'original."""
    import json as _json
    import subprocess
    from .util import probe, run
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=codec_name,pix_fmt,color_transfer,avg_frame_rate", "-of", "json", str(src)],
                           capture_output=True, text=True, timeout=60)
        st = (_json.loads(r.stdout or "{}").get("streams") or [{}])[0]
    except (OSError, ValueError, subprocess.SubprocessError):
        return src, info
    hdr = st.get("color_transfer") in ("arib-std-b67", "smpte2084")
    big = max(info["w"], info["h"]) > 2200
    fast = (info.get("fps") or 30) > 40
    if not (hdr or big or fast):
        return src, info
    out = work / "source-proxy.mp4"
    short = min(info["w"], info["h"])
    s = min(1.0, 1440 / max(1, short))
    w2, h2 = max(2, int(info["w"] * s) // 2 * 2), max(2, int(info["h"] * s) // 2 * 2)
    vf = f"fps=30,scale={w2}:{h2}:flags=lanczos"
    if hdr:
        vf = (f"fps=30,zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,"
              f"zscale=t=bt709:m=bt709:r=tv,scale={w2}:{h2}:flags=lanczos")
    why = ", ".join(x for x, c in (("4K", big), ("plus de 40 i/s", fast), ("HDR", hdr)) if c)
    log.info("Vidéo lourde (%s) : copie de travail %dx%d 30 i/s (le son reste celui de l'original)", why, w2, h2)
    cmd = ["ffmpeg", "-y", "-i", src, "-map", "0:v:0", "-an", "-copyts", "-start_at_zero", "-vf", vf + ",format=yuv420p",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-g", "15", "-video_track_timescale", "15360", out]
    try:
        run(cmd, timeout=7200)
    except Exception as e:  # noqa: BLE001
        if hdr:  # conversion HDR impossible : copie sans conversion des couleurs plutôt que rien
            log.warning("conversion HDR impossible (%s) : copie sans conversion", str(e)[-200:])
            cmd[cmd.index("-vf") + 1] = f"fps=30,scale={w2}:{h2}:flags=lanczos,format=yuv420p"
            try:
                run(cmd, timeout=7200)
            except Exception as e2:  # noqa: BLE001
                log.warning("copie de travail impossible (%s) : vidéo originale utilisée", str(e2)[-200:])
                return src, info
        else:
            log.warning("copie de travail impossible (%s) : vidéo originale utilisée", str(e)[-200:])
            return src, info
    try:
        p = probe(out)
    except Exception:  # noqa: BLE001
        return src, info
    if abs(p["duration"] - info["duration"]) > 1.0:
        log.warning("copie de travail de durée différente (%.1f / %.1f s) : vidéo originale utilisée",
                    p["duration"], info["duration"])
        return src, info
    return out, dict(info, w=p["w"], h=p["h"], fps=30.0)


HDR_TM = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,"
          "zscale=t=bt709:m=bt709:r=tv,format=yuv420p")


def is_hdr(path) -> bool:
    import subprocess
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=color_transfer",
                            "-of", "csv=p=0", str(path)], capture_output=True, text=True, timeout=60)
        return r.stdout.strip() in ("arib-std-b67", "smpte2084")
    except Exception:  # noqa: BLE001
        return False
