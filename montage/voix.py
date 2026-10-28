"""Mise en scène pilotée par ta voix (réglage « mise_en_scene », activé par défaut).

Pour chaque phrase : intensité de ta voix (par rapport à TA voix habituelle dans cette vidéo) et débit.
- ton qui monte (phrase nettement plus forte que d'habitude) → plan serré, avec une coupe au début de la phrase ;
- ton posé → plan large ; entre les deux → plan moyen, en alternance (jamais deux fois le même plan de suite) ;
- débit rapide → changements de plan plus fréquents ; débit lent → plans plus longs.
Le son n'est jamais touché. Sans son exploitable, retour automatique à l'alternance simple (c'est écrit dans PLAN.md)."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import numpy as np

from .pauses import HOP, SR

log = logging.getLogger("montage.voix")
LOUD = 1.2      # écart (en « écarts types robustes ») au-dessus de ta voix habituelle = ton qui monte
SOFT = -0.9


def levels(src: Path, work: Path) -> np.ndarray | None:
    cache = work / "level.npy"     # même mesure que la détection des silences (déjà calculée, en cache)
    try:
        return np.load(cache)
    except (OSError, ValueError):
        pass
    try:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-i", str(src), "-vn", "-ac", "1",
                            "-ar", str(SR), "-f", "s16le", "-"], capture_output=True, timeout=1800)
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("mesure de la voix impossible : %s", e)
        return None
    x = np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    n = len(x) // HOP
    if n < 50:
        return None
    db = 20 * np.log10(np.sqrt(np.mean(x[:n * HOP].reshape(n, HOP) ** 2, axis=1) + 1e-12) + 1e-9)
    try:
        np.save(cache, db)
    except OSError:
        pass
    return db


def sentence_energy(db: np.ndarray | None, words: list, sents: list) -> list[dict] | None:
    """[{"z": intensité relative, "rate": mots/s, "fast": bool}] aligné sur sents (None si inexploitable)."""
    if db is None or not sents or not words:
        return None
    fps = SR / HOP
    vals, rates = [], []
    for s in sents:
        seg = []
        for w in words[s["w0"]:s["w1"] + 1]:
            a, b = int(w["t0"] * fps), int(w["t1"] * fps) + 1
            seg.append(db[max(0, a):min(len(db), b)])
        v = np.concatenate(seg) if seg else np.array([])
        vals.append(float(np.percentile(v, 80)) if v.size >= 3 else np.nan)
        d = max(0.3, s["t1"] - s["t0"])
        rates.append((s["w1"] - s["w0"] + 1) / d)
    arr = np.array(vals)
    ok = arr[~np.isnan(arr)]
    if ok.size < 4:
        return None
    med = float(np.median(ok))
    mad = float(np.median(np.abs(ok - med))) * 1.4826
    mad = max(mad, 1.5)    # voix très régulière : seuls les vrais écarts (≥ ~2 dB) comptent
    r_hi = float(np.percentile(rates, 75))
    out = []
    for v, r in zip(arr, rates):
        z = 0.0 if np.isnan(v) else float(np.clip((v - med) / mad, -4, 4))
        out.append({"z": z, "rate": r, "fast": r >= r_hi and r > 2.6})
    return out


def analyse(src: Path, work: Path, words: list, sents: list) -> tuple[list[dict] | None, str]:
    try:
        e = sentence_energy(levels(src, work), words, sents)
    except Exception as ex:  # noqa: BLE001
        return None, f"analyse de la voix impossible ({type(ex).__name__}) : plans alternés simples"
    if e is None:
        return None, "voix trop régulière ou son inexploitable : plans alternés simples"
    n_loud = sum(1 for x in e if x["z"] >= LOUD)
    return e, f"{n_loud} phrase(s) au ton qui monte (plan serré), {sum(1 for x in e if x['fast'])} au débit rapide"
