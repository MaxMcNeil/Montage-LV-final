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
