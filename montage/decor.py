"""DÉCOR (chaîne depuis le fond vert) : le logo de la chaîne tourne lentement DERRIÈRE toi, style plateau télé, quand
tu es seul à l'écran (plan plein, sans média).

Le fond vert envoie l'image de fond qu'il a posée derrière toi (day / night). En la comparant à ta vidéo, on sait
exactement où tu es (ta silhouette) : le logo n'est dessiné que sur le fond, jamais sur toi. Si la comparaison n'est
pas fiable (autre fond, vidéo retouchée…), rien n'est fait : montage normal. Aucune IA, aucune clé.

Une erreur de silhouette n'est jamais grave : là où on se tromperait, le pixel du fond est presque identique au tien,
seul un voile de logo très léger pourrait apparaître."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

log = logging.getLogger("montage.decor")

PERIOD = 60.0      # un tour complet du logo en 60 s : lent, sobre (public 40 ans et plus)
LOGO_ALPHA = 0.26  # logo en filigrane
THRESH = 20        # écart (0-255) au-delà duquel un pixel est « toi » et non le fond


def _run(cmd: list, timeout: int = 900) -> None:
    subprocess.run([str(c) for c in cmd], check=True, capture_output=True, timeout=timeout)


def _frame(src: Path, t: float, w: int, h: int, out: Path) -> np.ndarray | None:
    try:
        _run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", src, "-frames:v", "1",
              "-vf", f"scale={w}:{h}", out], timeout=120)
        return np.asarray(Image.open(out).convert("RGB"), dtype=np.int16)
    except Exception:  # noqa: BLE001
        return None


def _gray_diff(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    d = np.abs(a - b).astype(np.float32)
    return 0.299 * d[..., 0] + 0.587 * d[..., 1] + 0.114 * d[..., 2]


def _matte(src: Path, bg: np.ndarray, w: int, h: int, fps: int, out: Path) -> float:
    """Ta silhouette pour TOUTE la vidéo (au quart de la taille, 30 i/s calées sur le temps de ta vidéo) : écart au
    fond reçu, petits points retirés, trous BOUCHÉS (le logo ne passe jamais sur toi). Renvoie la part d'images où une
    silhouette nette a été trouvée."""
    import cv2
    sw, sh = w // 8 * 2, h // 8 * 2
    bs = cv2.resize(bg.astype(np.uint8), (sw, sh), interpolation=cv2.INTER_AREA).astype(np.int16)
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(src), "-vf", f"fps={fps},scale={sw}:{sh}:flags=area",
                            "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    enc = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{sw}x{sh}",
                            "-r", str(fps), "-i", "-", "-c:v", "ffv1", "-g", "1", str(out)], stdin=subprocess.PIPE)
    k3 = np.ones((3, 3), np.uint8)
    k5 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    n = ok = 0
    prev = None
    try:
        while True:
            buf = dec.stdout.read(sw * sh * 3)
            if len(buf) < sw * sh * 3:
                break
            fr = np.frombuffer(buf, np.uint8).reshape(sh, sw, 3).astype(np.int16)
            m = (_gray_diff(fr, bs) > THRESH).astype(np.uint8)
            m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k5)   # contour fermé (jamais d'ouverture : elle le casserait)
            cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            big = [c for c in cs if cv2.contourArea(c) > 0.012 * sw * sh]
            filled = np.zeros_like(m)
            if big:
                # enveloppe extérieure de ta silhouette : aucun « trou » possible sur toi (cheveux sombres devant une
                # bibliothèque sombre…) ; le logo reste simplement un peu plus loin de tes bords
                hull = cv2.convexHull(np.vstack(big))
                cv2.drawContours(filled, [hull], -1, 1, thickness=-1)
                filled = cv2.dilate(filled, k3)
                ok += 1
            elif prev is not None:     # image douteuse : on garde la silhouette précédente (pas de clignotement)
                filled = prev
            prev = filled
            enc.stdin.write((filled * 255).astype(np.uint8).tobytes())
            n += 1
    finally:
        enc.stdin.close()
        enc.wait(timeout=600)
        dec.stdout.close()
        dec.wait(timeout=60)
    if n == 0 or not out.exists():
        raise RuntimeError("silhouette vide")
    return ok / n


def build(bg_jpg: Path, logo_png: str | None, src: Path, info: dict, face: dict, work: Path) -> tuple[dict | None, str]:
    """Prépare le décor. Retourne ({"bg": fond.mkv, "decor": decor.mp4, "period": s}, note) ou (None, raison)."""
    if not bg_jpg or not Path(bg_jpg).exists():
        return None, "pas d'image de fond reçue du fond vert"
    if not logo_png or not Path(logo_png).exists():
        return None, "pas de logo de chaîne"
    w, h, dur = int(info["w"]), int(info["h"]), float(info.get("duration") or 0)
    if w < 320 or h < 320 or dur < 5:
        return None, "vidéo trop petite ou trop courte"
    d = work / "decor"
    d.mkdir(parents=True, exist_ok=True)
    bg_png = d / "fond.png"
    try:   # même cadrage que le fond vert : recadré au centre, jamais étiré
        _run(["ffmpeg", "-y", "-v", "error", "-i", bg_jpg, "-vf",
              f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1", "-frames:v", "1", bg_png])
        bg = np.asarray(Image.open(bg_png).convert("RGB"), dtype=np.int16)
    except Exception as e:  # noqa: BLE001
        return None, f"image de fond illisible ({type(e).__name__})"
    # contrôle : ta vidéo a-t-elle VRAIMENT ce fond ? (6 images réparties sur la vidéo)
    fg_parts, bg_parts = [], []
    for k in range(6):
        fr = _frame(src, dur * (k + 0.5) / 6, w, h, d / f"test{k}.png")
        if fr is None:
            continue
        g = _gray_diff(fr, bg)
        bg_parts.append(float((g < 12).mean()))
        fg_parts.append(float((g > THRESH).mean()))
    if len(bg_parts) < 3:
        return None, "images de contrôle illisibles"
    bg_ok, fg_ok = float(np.median(bg_parts)), float(np.median(fg_parts))
    if bg_ok < 0.20 or not (0.05 <= fg_ok <= 0.80):
        return None, (f"fond non reconnu dans ta vidéo (fond identique sur {bg_ok:.0%} de l'image, toi sur {fg_ok:.0%}) "
                      "→ montage sans logo derrière toi")
    # fond de référence en vidéo sans perte (2 s, lu en boucle) + décor : fond + logo qui tourne lentement
    decor_mp4 = d / "decor.mp4"
    L = int(min(h * 0.86, w * 0.48)) // 2 * 2
    cx = w * (0.74 if face.get("cx", 0.5) < 0.5 else 0.26)
    x, y = int(cx - L / 2), int(h * 0.48 - L / 2)
    from .render import FPS
    try:
        _run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-framerate", FPS, "-t", f"{PERIOD:.0f}", "-i", bg_png,
              "-loop", "1", "-framerate", FPS, "-t", f"{PERIOD:.0f}", "-i", logo_png, "-filter_complex",
              f"[1:v]format=rgba,scale={L}:{L}:force_original_aspect_ratio=decrease,pad={L}:{L}:(ow-iw)/2:(oh-ih)/2:"
              f"color=black@0,colorchannelmixer=aa={LOGO_ALPHA},"
              f"rotate=a=2*PI*t/{PERIOD:.0f}:c=none:ow={L}:oh={L}[lg];"
              f"[0:v][lg]overlay=x={x}:y={y}:shortest=1:format=auto,format=yuv420p[v]",
              "-map", "[v]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-g", str(FPS * 2), decor_mp4],
             timeout=1800)
        matte = d / "silhouette.mkv"
        cov = _matte(src, bg, w, h, FPS, matte)
    except Exception as e:  # noqa: BLE001
        return None, f"décor impossible à préparer ({type(e).__name__})"
    return ({"matte": str(matte), "decor": str(decor_mp4), "period": PERIOD},
            f"logo de la chaîne qui tourne lentement derrière toi (plans pleins) — fond reconnu sur {bg_ok:.0%} de "
            f"l'image, ta silhouette suivie sur {cov:.0%} des images")
