"""Voix « studio chaude » (réglage voix_studio, NON par défaut) — réglage « chaude max » choisi à l'écoute.

Chaîne de traitement (ffmpeg, gratuit, aucune IA ni clé) :
  1. coupe-bas 80 Hz raide   → grondements, souffle de clim, bruits de table (même entre les mots)
  2. débruitage DOUX         → seulement si ta pièce est bruyante, réglé d'après le bruit mesuré dans tes silences
                               (jamais fort : un débruitage trop fort donne une voix « sous l'eau »)
  3. profondeur              → +6 dB vers 130 Hz, +2 dB vers 220 Hz (corps, « bouche près d'un bon micro »)
  4. clarté                  → -3 dB vers 380 Hz (pas de voix « boîte »), +1,5 dB vers 3,2 kHz (présence)
                               (plus de « air » au-dessus de 11 kHz : il rendait les « s » perçants)
  5. dé-esseur doux          → « s » et « ch » moins sifflants
  6. double compression      → 4,5:1 puis 2:1 douce : voix posée, « devant », volume régulier (façon radio)
  7. volume YouTube          → -16 LUFS en 2 passes linéaires, crêtes ≤ -1,5 dB (aucune saturation)
  8. anti-« s » final        → APRÈS la compression (qui remontait les « s ») : la bande 4,5–12 kHz n'est baissée
                               QUE quand un « s » domine la voix (au plus -14 dB) ; le reste de la voix n'est pas touché.
                               Échec -> étape sautée (voix studio quand même), jamais de plantage.

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
              "equalizer=f=3200:t=q:w=1.3:g=1.5",
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
        ds = deess_file(out)
        pk, rms = _levels(out)
        pk0, rms0 = _levels(normal)
        if pk > -0.5:
            return normal, f"⚠ voix studio annulée (saturation {pk:.1f} dB) : voix normale"
        if rms < -45 or rms < rms0 - 10:
            return normal, f"⚠ voix studio annulée (son trop faible : {rms:.0f} dB contre {rms0:.0f}) : voix normale"
        return out, (f"voix studio chaude appliquée — {dn}, profondeur, clarté, dé-esseur, double compression, "
                     f"volume YouTube, {ds}")
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


def deess(x: np.ndarray, sr: int, thresh_db: float = -10.0, ratio: float = 3.0, max_cut_db: float = 14.0,
          lo: float = 4500.0, hi: float = 12000.0) -> np.ndarray:
    """Dé-esseur spectral. x : float32 (n,) ou (n, canaux) dans [-1, 1] -> même forme, même longueur.
    La bande des sifflantes n'est baissée que quand elle domine la voix (120 Hz–4 kHz) de plus de `thresh_db`."""
    mono = x if x.ndim == 1 else x.mean(axis=1)
    n, hop = 1024, 256
    win = np.hanning(n).astype(np.float32)
    pad = n
    chans = [x] if x.ndim == 1 else [x[:, c] for c in range(x.shape[1])]
    L = len(mono)

    def frames(sig):
        s = np.concatenate([np.zeros(pad, np.float32), sig.astype(np.float32), np.zeros(pad + n, np.float32)])
        return s, np.arange(0, len(s) - n, hop)
    s, idx = frames(mono)
    F = np.fft.rfft(np.stack([s[i:i + n] * win for i in idx]), axis=1)
    f = np.fft.rfftfreq(n, 1 / sr)
    band = (f >= lo) & (f < hi)
    voice = (f >= 120) & (f < 4000)
    P = np.abs(F) ** 2
    r = 10 * np.log10((P[:, band].sum(1) + 1e-12) / (P[:, voice].sum(1) + 1e-12))
    cut = np.clip((r - thresh_db) * (1 - 1 / ratio), 0, max_cut_db)       # dB d'atténuation par trame
    rel = np.exp(-hop / sr / 0.04)                                         # relâchement ≈ 40 ms
    g = np.empty_like(cut)
    cur = 0.0
    for k, c in enumerate(cut):
        cur = c if c > cur else rel * cur + (1 - rel) * c
        g[k] = cur
    ramp = np.clip((f - (lo - 1000)) / 1000, 0, 1) * np.clip(((hi + 3000) - f) / 3000, 0, 1)   # pas de « trou » net
    gain = (10 ** (-g[:, None] * ramp[None, :] / 20)).astype(np.float32)
    norm = np.zeros(len(s), np.float32)
    for i in idx:
        norm[i:i + n] += win ** 2
    out = []
    for ch in chans:
        sc, _ = frames(ch)
        fr = np.fft.irfft(np.fft.rfft(np.stack([sc[i:i + n] * win for i in idx]), axis=1) * gain, n=n,
                          axis=1).astype(np.float32) * win
        y = np.zeros(len(sc), np.float32)
        for k, i in enumerate(idx):
            y[i:i + n] += fr[k]
        out.append((y / np.maximum(norm, 1e-6))[pad:pad + L])
    res = out[0] if x.ndim == 1 else np.stack(out, axis=1)
    return np.clip(res, -1.0, 1.0).astype(np.float32)


def deess_file(p: Path, block_s: float = 30.0, margin_s: float = 0.5) -> str:
    """Anti-« s » sur un WAV 16 bits, par blocs (mémoire limitée même pour 1 h de voix), même longueur.
    Ne lève jamais d'exception : en cas d'échec le fichier reste tel quel."""
    tmp = p.with_name(p.stem + "_ds.wav")
    try:
        with wave.open(str(p), "rb") as r, wave.open(str(tmp), "wb") as w:
            params = r.getparams()
            if params.sampwidth != 2 or params.nframes == 0:
                raise ValueError("format inattendu")
            w.setparams(params)
            sr, total, nc = params.framerate, params.nframes, params.nchannels
            blk, mg = int(block_s * sr), int(margin_s * sr)
            for a in range(0, total, blk):                 # lecture bloc par bloc : peu de mémoire, même pour 2 h
                b = min(total, a + blk)
                a0, b0 = max(0, a - mg), min(total, b + mg)
                r.setpos(a0)
                data = np.frombuffer(r.readframes(b0 - a0), dtype=np.int16).reshape(-1, nc)
                y = deess(data.astype(np.float32) / 32768.0, sr)[a - a0:a - a0 + (b - a)]
                w.writeframes(np.clip(np.round(y * 32767), -32768, 32767).astype(np.int16).tobytes())
        if _frames(tmp) != total:
            raise ValueError("longueur différente")
        tmp.replace(p)
        return "anti-« s »"
    except Exception as e:  # noqa: BLE001
        log.warning("anti-« s » sauté : %s", e)
        try:
            tmp.unlink()
        except OSError:
            pass
        return "anti-« s » sauté"
