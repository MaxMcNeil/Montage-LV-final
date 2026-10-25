"""Silences longs (> 2 s) : détection fiable et coupe invisible.

1. Détection ADAPTATIVE du silence : le niveau sonore est mesuré toutes les 20 ms, puis comparé au bruit de fond
   réel de TA pièce (et non à un seuil fixe) — fonctionne avec un fond vert remplacé, un ventilateur, un micro
   bruyant, dans toutes les langues (on ne regarde que le son, pas les mots).
2. Réparation des horodatages : la transcription « étire » parfois un mot sur une pause ; on le raccourcit pour que la
   pause soit vue (sinon elle resterait dans la vidéo).
3. Effet à la coupe, choisi selon ta position (comparaison des images de part et d'autre) :
   - tu n'as presque pas bougé → changement de plan (zoom avant/arrière) : la coupe devient un « changement de
     caméra », sans saut visible ;
   - tu as bougé → fondu enchaîné doux de 0,24 à 0,32 s (fait avec les images du silence supprimé : la durée et la
     synchro du son ne changent pas)."""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

import numpy as np

from .config import FPS

log = logging.getLogger("montage.pauses")
SR = 8000
HOP = 160          # 20 ms


def quiet_intervals(src: Path, work: Path, min_len: float = 0.4) -> list[tuple[float, float]]:
    """Intervalles calmes (bruit de fond de ta pièce) d'au moins min_len secondes. Mis en cache."""
    cache = work / "quiet.json"
    try:
        return [tuple(x) for x in json.loads(cache.read_text(encoding="utf-8"))]
    except (OSError, ValueError):
        pass
    try:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-i", str(src), "-vn", "-ac", "1",
                            "-ar", str(SR), "-f", "s16le", "-"], capture_output=True, timeout=1800)
        x = np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("analyse du son impossible : %s", e)
        return []
    n = len(x) // HOP
    if n < 50:
        return []
    rms = np.sqrt(np.mean(x[:n * HOP].reshape(n, HOP) ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(rms + 1e-9)
    floor = float(np.percentile(db, 10))
    speech = float(np.percentile(db, 90))
    if speech - floor < 10:          # son trop uniforme : impossible de distinguer silence et parole sans risque
        log.info("Silences : contraste son trop faible (%.0f dB), détection adaptative désactivée", speech - floor)
        out = []
    else:
        thr = min(floor + 0.30 * (speech - floor), speech - 14)
        quiet = db < thr
        # bouche les micro-bruits (clic, souffle bref ≤ 80 ms) au milieu d'un silence
        k = 0
        while k < n:
            if not quiet[k]:
                j = k
                while j < n and not quiet[j]:
                    j += 1
                if k > 0 and j < n and (j - k) <= 4:
                    quiet[k:j] = True
                k = j
            else:
                k += 1
        out, k = [], 0
        while k < n:
            if quiet[k]:
                j = k
                while j < n and quiet[j]:
                    j += 1
                a, b = k * HOP / SR, j * HOP / SR
                if b - a >= min_len:
                    out.append((round(a, 3), round(b, 3)))
                k = j
            else:
                k += 1
        log.info("Silences : bruit de fond %.0f dB, voix %.0f dB → %d passage(s) calme(s)", floor, speech, len(out))
    try:
        cache.write_text(json.dumps(out), encoding="utf-8")
    except OSError:
        pass
    return out


def merge(*lists) -> list[tuple[float, float]]:
    iv = sorted((float(a), float(b)) for lst in lists for a, b in (lst or []) if b > a)
    out: list[list[float]] = []
    for a, b in iv:
        if out and a <= out[-1][1] + 0.02:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def repair_words(words: list, quiet: list, min_q: float = 0.9) -> int:
    """Un mot qui « contient » un long calme (horodatage étiré par la transcription) est raccourci."""
    fixed = 0
    for w in words:
        if w["t1"] - w["t0"] < 1.1:
            continue
        for a, b in quiet:
            a2, b2 = max(a, w["t0"]), min(b, w["t1"])
            if b2 - a2 < min_q:
                continue
            if a2 > w["t0"] + 0.15:      # le calme est après le mot prononcé
                w["t1"] = round(a2 + 0.05, 3)
            elif b2 < w["t1"] - 0.15:    # le calme est avant le mot
                w["t0"] = round(b2 - 0.05, 3)
            else:
                continue
            fixed += 1
            break
    return fixed


def _gray(src: Path, t: float) -> np.ndarray | None:
    try:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-ss", f"{max(0.0, t):.3f}",
                            "-i", str(src), "-frames:v", "1", "-vf", "scale=96:96,format=gray", "-f", "rawvideo", "-"],
                           capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if len(r.stdout) < 96 * 96:
        return None
    return np.frombuffer(r.stdout[:96 * 96], dtype=np.uint8).reshape(96, 96).astype(np.float32)


def cut_effects(segs: list, src: Path, keep: list | None = None, min_cut: float = 1.5) -> dict:
    """Choisit l'effet de chaque coupe d'un silence long, selon ta position avant / après.
    (Une coupe qui tombe sur un changement de mise en page — média qui arrive, extrait — a déjà sa transition.)"""
    stats = {"cuts": 0, "zoom": 0, "fondu": 0, "page": 0, "gagne": 0.0}
    if keep:
        gaps = [b2[0] - b1[1] for b1, b2 in zip(keep, keep[1:]) if b2[0] - b1[1] >= min_cut]
        stats["page"] = len(gaps)
        stats["cuts"] = len(gaps)
        stats["gagne"] = sum(gaps)
    for s in segs:
        if s.kind not in ("full", "split"):
            continue
        t_out = s.out0
        for prev, at in zip(s.atoms, s.atoms[1:]):
            t_out += round((prev.b - prev.a) * FPS) / FPS
            removed = at.a - prev.b
            if removed < min_cut:
                continue
            if not keep:
                stats["cuts"] += 1
                stats["gagne"] += removed
            stats["page"] -= 1 if keep else 0
            a, b = _gray(src, prev.b - 1.0 / FPS), _gray(src, at.a)
            # écart d'image sur la zone centrale (là où tu es)
            diff = float(np.mean(np.abs(a[16:80, 16:80] - b[16:80, 16:80]))) if a is not None and b is not None else 99.0
            if s.kind == "full" and abs(at.zoom - prev.zoom) > 0.02 and diff < 9:
                stats["zoom"] += 1            # même position : le changement de plan suffit, coupe nette
                continue
            at.xin = 0.24 if diff < 22 else 0.32
            at.xfrom = prev
            stats["fondu"] += 1
            log.info("  fondu doux à %.2f s (écart d'image %.0f)", t_out, diff)
    if stats["cuts"]:
        stats["page"] = max(0, stats["page"])
        log.info("Silences longs : %d coupé(s) (%.0f s gagnées) — %d changement(s) de plan, %d fondu(s) doux, "
                 "%d sur une transition de mise en page", stats["cuts"], stats["gagne"], stats["zoom"], stats["fondu"],
                 stats["page"])
    return stats
