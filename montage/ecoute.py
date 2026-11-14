"""TOI QUI ÉCOUTES pendant un extrait (ton cadre à côté de la vidéo jointe).

Avant : un de tes silences de 2 s, ralenti puis joué aller-retour en boucle → ta bouche s'ouvrait et se fermait,
tu avançais et reculais plusieurs fois. Supprimé.

Maintenant :
  1. ta bouche est MESURÉE image par image (écart entre tes lèvres, repères du visage) : on ne garde que les vrais
     moments où elle est FERMÉE (au moins 1 s de suite) ;
  2. pendant l'extrait, on enchaîne PLUSIEURS de ces moments DIFFÉRENTS, toujours en avant (jamais d'aller-retour),
     légèrement ralentis, reliés par de longs fondus — comme un plan d'écoute monté en régie ;
     extrait de 7 s ou plus : MISE AU POINT sur la vidéo — ton premier moment est net, puis ton cadre passe en flou
     léger et un peu plus sombre (le regard va sur l'extrait), et redevient net juste avant de revenir sur toi ;
  3. chaque moment est utilisé le moins souvent possible sur toute la vidéo (les moins utilisés d'abord) ;
  4. pas assez de moments bouche fermée, ou mesure impossible : une image de toi BOUCHE FERMÉE (choisie par la
     mesure), avec le zoom lent du cadre. Jamais une bouche qui bat.
Jamais bloquant."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

log = logging.getLogger("montage.ecoute")

ROOT = Path(__file__).resolve().parents[1]
CLOSED = 0.012      # écart des lèvres / hauteur du visage : en dessous = bouche fermée (mesuré sur tes vidéos)
MIN_RUN = 1.0       # un moment bouche fermée dure au moins 1 s
SLOW = 0.75         # légèrement ralenti (plan d'écoute), jamais à l'envers
XF = 0.6            # fondu entre deux moments
MAX_PIECE = 6.0     # un moment ne dure jamais plus de 6 s à l'écran
LONG = 1.8          # moment « long » (≥ 1,8 s de vraie vidéo, ≈ 2,4 s à l'écran)
RACK_MIN = 7.0      # extrait d'au moins 7 s : mise au point sur l'extrait (ton cadre en flou léger au milieu)
RACK_AT = 3.0       # ton premier moment reste net 3 s au plus
RACK_IN, RACK_OUT, RACK_BACK = 1.0, 0.8, 1.6
BLUR = 7

_LOCK = threading.Lock()


def _python() -> str | None:
    """Python qui a MediaPipe : environnement séparé du workflow (MP_PYTHON), sinon celui-ci s'il l'a."""
    p = os.environ.get("MP_PYTHON")
    if p and Path(p).exists():
        return p
    try:
        import importlib.util
        return sys.executable if importlib.util.find_spec("mediapipe") else None
    except Exception:  # noqa: BLE001
        return None


def measure(src: Path, work: Path) -> dict | None:
    """{"fps", "gap"} mis en cache dans work/bouche.json ; None si mesure impossible."""
    cache = work / "bouche.json"
    try:
        return json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    py = _python()
    if not py:
        log.info("toi qui écoutes : MediaPipe absent → image de toi bouche fermée la plus probable")
        return None
    try:
        r = subprocess.run([py, str(ROOT / "scripts" / "bouche.py"), str(src), str(cache), "8"],
                           capture_output=True, text=True, timeout=3600)
        d = json.loads(cache.read_text(encoding="utf-8"))
        if not d.get("gap"):
            raise ValueError("aucune image")
        log.info("toi qui écoutes : bouche mesurée sur %d images (%s)", len(d["gap"]), (r.stdout or "").strip()[-80:])
        return d
    except Exception as e:  # noqa: BLE001
        log.warning("toi qui écoutes : mesure de la bouche impossible (%s)", str(e)[-200:])
        return None


def closed_runs(d: dict | None) -> list[tuple[float, float]]:
    """Moments (début, fin) où ta bouche reste fermée au moins MIN_RUN s (bords rognés : jamais l'ouverture)."""
    if not d:
        return []
    fps, gap = float(d.get("fps") or 8), d.get("gap") or []
    runs, s = [], None
    for i, g in enumerate(list(gap) + [-1.0]):
        ok = 0 <= g < CLOSED
        if ok and s is None:
            s = i
        elif not ok and s is not None:
            a, b = (s + 1) / fps, (i - 1) / fps        # une image rognée de chaque côté
            if b - a >= MIN_RUN:
                runs.append((round(a, 3), round(b, 3)))
            s = None
    return runs


def best_frame(d: dict | None, near: float) -> float | None:
    """Instant d'une image bouche bien fermée, le plus proche de `near`."""
    runs = closed_runs(d)
    if not runs:
        return None
    a, b = min(runs, key=lambda r: abs((r[0] + r[1]) / 2 - near))
    return (a + b) / 2


class Ecoute:
    """Un par montage : mesure (une fois), moments bouche fermée, compteur d'utilisation (variété)."""

    def __init__(self, src: Path, work: Path):
        self.src, self.work = Path(src), Path(work)
        self._d = None
        self._done = False
        self.used: dict = {}

    def data(self):
        with _LOCK:
            if not self._done:
                self._d = measure(self.src, self.work)
                self._done = True
                runs = closed_runs(self._d)
                if self._d is not None:
                    log.info("toi qui écoutes : %d moment(s) bouche fermée (%.0f s au total)", len(runs),
                             sum(b - a for a, b in runs))
            return self._d

    def pick(self, need: float, near: float) -> list[tuple[float, float]]:
        """Moments à enchaîner pour couvrir `need` secondes (à l'écran, ralenti compris). [] = image fixe."""
        runs = closed_runs(self.data())
        if not runs or sum(b - a for a, b in runs) / SLOW < 4.0:
            return []
        with _LOCK:
            # de préférence les moments longs (moins de fondus, plus calme) ; les courts seulement s'il en manque
            longs = [r for r in runs if r[1] - r[0] >= LONG]
            if len(longs) >= 3:
                runs = longs
            out, tot, last = [], 0.0, None
            for _ in range(200):
                if tot >= need + 0.5:
                    break
                cand = [r for r in runs if r != last] or runs
                # le moins utilisé sur toute la vidéo, puis le plus long, puis le plus proche de ce moment
                r = min(cand, key=lambda r: (self.used.get(r, 0), -(min(r[1] - r[0], MAX_PIECE * SLOW)),
                                             abs((r[0] + r[1]) / 2 - near)))
                self.used[r] = self.used.get(r, 0) + 1
                a, b = r
                b = min(b, a + MAX_PIECE * SLOW)
                out.append((a, b))
                tot += (b - a) / SLOW - (XF if out[:-1] else 0)
                last = r
            return out


def build(ctx, pieces: list, dur: float, out: Path) -> Path | None:
    """Enchaîne les moments (en avant, ralentis, fondus) en une vidéo d'au moins `dur` s, cadrée comme toi."""
    if not pieces:
        return None
    from .config import FPS
    args, filt, lens = [], [], []
    for k, (a, b) in enumerate(pieces):
        args += ["-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", str(ctx.src)]
        L = (b - a) / SLOW
        lens.append(L)
        filt.append(f"[{k}:v]setpts=(PTS-STARTPTS)/{SLOW},fps={FPS},{ctx.full_chain(1.0)},format=yuv420p,"
                    f"settb=1/{FPS},trim=duration={L:.3f},setpts=PTS-STARTPTS[p{k}]")
    cur, acc = "p0", lens[0]
    for k in range(1, len(pieces)):
        x = min(XF, lens[k - 1] / 2.5, lens[k] / 2.5)
        filt.append(f"[{cur}][p{k}]xfade=transition=fade:duration={x:.3f}:offset={acc - x:.3f}[x{k}]")
        cur, acc = f"x{k}", acc + lens[k] - x
    filt.append(f"[{cur}]tpad=stop_mode=clone:stop_duration={max(0.0, dur - acc) + 1:.3f},"
                f"trim=duration={dur:.3f},format=yuv420p,setpts=PTS-STARTPTS[full]")
    if dur >= RACK_MIN:
        # MISE AU POINT sur l'extrait : après ton premier moment (net), ton cadre passe doucement en flou léger et un peu
        # plus sombre (le regard va sur la vidéo), puis redevient net juste avant de revenir sur toi.
        t0 = min(RACK_AT, lens[0] - 0.3)
        e0 = dur - RACK_BACK
        filt.append("[full]split=3[s1][s2][s3]")
        filt.append(f"[s1]trim=duration={t0 + RACK_IN:.3f},setpts=PTS-STARTPTS[sa]")
        filt.append(f"[s2]trim=start={t0:.3f},setpts=PTS-STARTPTS,gblur=sigma={BLUR},"
                    f"eq=brightness=-0.05:saturation=0.8[sb]")
        filt.append(f"[sa][sb]xfade=transition=fade:duration={RACK_IN:.3f}:offset={t0:.3f}[m]")
        filt.append(f"[s3]trim=start={e0:.3f},setpts=PTS-STARTPTS[sc]")
        filt.append(f"[m][sc]xfade=transition=fade:duration={RACK_OUT:.3f}:offset={e0:.3f},format=yuv420p[v]")
    else:
        filt.append("[full]null[v]")
    try:
        subprocess.run(["ffmpeg", "-y", "-v", "error", *args, "-filter_complex", ";".join(filt), "-map", "[v]", "-an",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", str(out)],
                       check=True, capture_output=True, timeout=900)
        return out if out.exists() and out.stat().st_size > 1000 else None
    except Exception as e:  # noqa: BLE001
        err = getattr(e, "stderr", b"") or b""
        log.warning("toi qui écoutes : montage des moments impossible (%s) → image fixe bouche fermée",
                    (err[-300:].decode(errors="ignore") if isinstance(err, bytes) else str(e)[-300:]))
        return None
