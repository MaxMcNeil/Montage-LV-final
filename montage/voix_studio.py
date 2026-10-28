"""Voix « studio chaude » (réglage voix_studio, NON par défaut) — réglage « chaude max » choisi à l'écoute.

Chaîne de traitement (ffmpeg, gratuit, aucune IA ni clé) :
  1. coupe-bas 80 Hz raide   → grondements, souffle de clim, bruits de table (même entre les mots)
  2. débruitage DOUX         → seulement si ta pièce est bruyante, réglé d'après le bruit mesuré dans tes silences
                               (jamais fort : un débruitage trop fort donne une voix « sous l'eau »)
  3. profondeur              → +6 dB vers 130 Hz, +2 dB vers 220 Hz (corps, « bouche près d'un bon micro »)
  4. clarté                  → -3 dB vers 380 Hz (pas de voix « boîte »), +3 dB vers 3,2 kHz (présence),
                               +2,5 dB au-dessus de 11 kHz (air)
  5. dé-esseur doux          → « s » et « ch » moins sifflants
  6. double compression      → 4,5:1 puis 2:1 douce : voix posée, « devant », volume régulier (façon radio)
  7. volume YouTube          → -16 LUFS en 2 passes linéaires, crêtes ≤ -1,5 dB (aucune saturation)

Sécurité : le résultat est CONTRÔLÉ (même durée à l'échantillon près, pas de saturation, pas de son vide, pas de
voix écrasée). Au moindre doute → ta voix normale est utilisée, et PLAN.md le dit. Le son des extraits insérés
n'est jamais touché, et la synchro son/image ne change pas."""
from __future__ import annotations

import logging
import re
import wave
from pathlib import Path

import numpy as np

from .config import SAMPLE_RATE
from .util import run

log = logging.getLogger("montage.voix_studio")


def _noise_profile(work: Path) -> tuple[float | None, float | None]:
    """(bruit de fond, niveau de ta voix) en dB, d'après la mesure déjà faite pour les silences (level.npy)."""
    try:
        db = np.load(work / "level.npy")
    except (OSError, ValueError):
        return None, None
    if db.size < 100:
        return None, None
    return float(np.percentile(db, 10)), float(np.percentile(db, 90))


def chain(noise: float | None, voice: float | None) -> tuple[str, str]:
    """(filtres ffmpeg AVANT le réglage du volume, description du débruitage)."""
    parts = ["highpass=f=80:p=2", "highpass=f=80:p=2"]
    gap = (voice - noise) if (noise is not None and voice is not None) else None
    if gap is None:
        dn = "débruitage léger (bruit non mesuré)"
        parts.append("afftdn=nr=8:nf=-50:tn=1")
    elif gap >= 45:
        dn = "pas de débruitage (pièce déjà silencieuse)"
    else:
        nr = 8 if gap >= 35 else 12          # jamais au-delà de 12 dB : sinon voix « métallique »
        nf = int(min(-25, max(-80, noise)))
        dn = f"débruitage {'léger' if nr == 8 else 'moyen'} (bruit de fond {noise:.0f} dB, voix {voice:.0f} dB)"
        parts.append(f"afftdn=nr={nr}:nf={nf}:tn=1")
        # entre les phrases : le souffle restant est abaissé en douceur (au plus -9 dB, jamais coupé net)
        thr = 10 ** ((noise + 0.35 * gap) / 20)
        parts.append(f"agate=threshold={thr:.6f}:ratio=2:range=0.35:attack=8:release=300:knee=4")
    parts += ["equalizer=f=130:t=q:w=0.8:g=6",
              "equalizer=f=220:t=q:w=1:g=2",
              "equalizer=f=380:t=q:w=1.2:g=-3",
              "equalizer=f=3200:t=q:w=1.3:g=3",
              "highshelf=f=11000:g=2.5",
              "deesser=i=0.45:m=0.5:f=0.5",
              "acompressor=threshold=-26dB:ratio=4.5:attack=10:release=160:makeup=2.6:knee=4",
              "acompressor=threshold=-12dB:ratio=2:attack=5:release=80:makeup=1"]
    return ",".join(parts), dn


def _loudnorm_args(src: Path, af: str) -> str:
    """Réglage du volume en 2 passes, mode LINÉAIRE : le volume global est ajusté sans remonter les silences
    (le mode automatique « pompe » le souffle entre les phrases). Repli : mode simple."""
    import json as _json
    try:
        r = run(["ffmpeg", "-loglevel", "info", "-i", src, "-vn", "-af",
                 af + ",loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"], timeout=3600, quiet=True)
        m = _json.loads((r.stderr or "")[(r.stderr or "").rindex("{"):(r.stderr or "").rindex("}") + 1])
        vals = {k: float(m[k]) for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")}
        if any(v != v or abs(v) == float("inf") for v in vals.values()) or vals["input_i"] < -70:
            raise ValueError("mesure inexploitable")
        return ("loudnorm=I=-16:TP=-1.5:LRA=11:linear=true:"
                f"measured_I={vals['input_i']}:measured_TP={vals['input_tp']}:measured_LRA={vals['input_lra']}:"
                f"measured_thresh={vals['input_thresh']}:offset={vals['target_offset']}")
    except Exception as e:  # noqa: BLE001
        log.info("volume en 1 passe (%s)", e)
        return "loudnorm=I=-16:TP=-1.5:LRA=11"


def _frames(p: Path) -> int:
    with wave.open(str(p), "rb") as w:
        return w.getnframes()


def _levels(p: Path) -> tuple[float, float]:
    """(crête, niveau moyen) en dB pleine échelle."""
    r = run(["ffmpeg", "-loglevel", "info", "-i", p, "-af", "astats=measure_overall=Peak_level+RMS_level:measure_perchannel=0", "-f", "null",
             "-"], timeout=1800, quiet=True)
    txt = r.stderr or ""
    pk = re.findall(r"Peak level dB:\s*(-?[\d.]+|-inf)", txt)
    rm = re.findall(r"RMS level dB:\s*(-?[\d.]+|-inf)", txt)
    f = lambda v: -200.0 if not v or v[-1] == "-inf" else float(v[-1])   # noqa: E731
    return f(pk), f(rm)


def apply(src: Path, normal: Path, work: Path) -> tuple[Path, str]:
    """Rend (fichier à utiliser, explication). Ne lève jamais d'exception : repli sur `normal`."""
    out = work / "main_studio.wav"
    try:
        noise, voice = _noise_profile(work)
        af, dn = chain(noise, voice)
        af = af + "," + _loudnorm_args(src, af) + ",alimiter=limit=0.89:level=disabled"
        run(["ffmpeg", "-y", "-i", src, "-vn", "-af", af, "-ac", "2", "-ar", SAMPLE_RATE, "-c:a", "pcm_s16le", out],
            timeout=3600)
        n0, n1 = _frames(normal), _frames(out)
        if abs(n0 - n1) > SAMPLE_RATE * 0.02:       # plus de 20 ms d'écart : la synchro serait en danger
            return normal, f"⚠ voix studio annulée (durée différente de {abs(n0 - n1) / SAMPLE_RATE:.2f} s) : voix normale"
        if n1 != n0:                                # écart minime : recalé à l'échantillon près
            _fit_length(out, n0)
        pk, rms = _levels(out)
        pk0, rms0 = _levels(normal)
        if pk > -0.5:
            return normal, f"⚠ voix studio annulée (saturation {pk:.1f} dB) : voix normale"
        if rms < -45 or rms < rms0 - 10:
            return normal, f"⚠ voix studio annulée (son trop faible : {rms:.0f} dB contre {rms0:.0f}) : voix normale"
        return out, (f"voix studio chaude appliquée — {dn}, profondeur, clarté, dé-esseur, double compression, "
                     "volume YouTube")
    except Exception as e:  # noqa: BLE001
        log.warning("voix studio impossible : %s", e)
        return normal, f"⚠ voix studio annulée ({type(e).__name__}) : voix normale"


def _fit_length(p: Path, n: int) -> None:
    with wave.open(str(p), "rb") as w:
        params = w.getparams()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).reshape(-1, params.nchannels)
    if len(data) > n:
        data = data[:n]
    else:
        data = np.vstack([data, np.zeros((n - len(data), params.nchannels), dtype=np.int16)])
    with wave.open(str(p), "wb") as w:
        w.setparams(params)
        w.writeframes(data.tobytes())
