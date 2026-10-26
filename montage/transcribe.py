"""Transcription mot à mot (gratuite).

1. Groq Whisper large-v3 (en ligne, gratuit, rotation des clés GROQ_API_KEYS) — l'audio est découpé en morceaux
   d'environ 10 min, coupés dans un silence.
2. Repli : faster-whisper sur la machine GitHub (aucune clé, plus lent).
Résultat : {"lang", "duration", "words": [{"t0", "t1", "w"}]} (la ponctuation est collée aux mots)."""
from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path

import requests

from .ai import groq_keys
from .util import probe, run

log = logging.getLogger("montage.asr")

LANGS = {"arabic": "ar", "french": "fr", "english": "en", "italian": "it", "spanish": "es", "german": "de",
         "portuguese": "pt", "dutch": "nl", "turkish": "tr", "russian": "ru"}
CHUNK = 600.0


def silences(audio: Path, noise_db: int = -34, min_d: float = 0.35) -> list[tuple[float, float]]:
    """Silences réels de l'audio (ffmpeg silencedetect)."""
    r = run(["ffmpeg", "-hide_banner", "-nostdin", "-i", audio, "-af", f"silencedetect=noise={noise_db}dB:d={min_d}",
             "-f", "null", "-"], check=False, quiet=True)
    out, start = [], None
    for line in (r.stderr or "").splitlines():
        m = re.search(r"silence_start: (-?[\d.]+)", line)
        if m:
            start = max(0.0, float(m.group(1)))
        m = re.search(r"silence_end: ([\d.]+)", line)
        if m and start is not None:
            out.append((start, float(m.group(1))))
            start = None
    return out


def _chunks(duration: float, sil: list) -> list[tuple[float, float]]:
    if duration <= CHUNK * 1.15:
        return [(0.0, duration)]
    cuts, t = [0.0], 0.0
    while duration - t > CHUNK * 1.15:
        target = t + CHUNK
        near = [((a + b) / 2) for a, b in sil if abs((a + b) / 2 - target) < 40]
        c = min(near, key=lambda x: abs(x - target)) if near else target
        cuts.append(c)
        t = c
    cuts.append(duration)
    return list(zip(cuts[:-1], cuts[1:]))


def _punctuate(words: list, segments: list) -> list:
    """Groq donne les mots sans ponctuation et les segments avec : on recolle la ponctuation finale aux mots."""
    from .util import norm
    toks = []
    for s in segments:
        toks += [t for t in str(s.get("text", "")).split() if t.strip()]
    j = 0
    for w in words:
        nw = norm(w["w"])
        for k in range(j, min(j + 6, len(toks))):
            if norm(toks[k]) == nw and nw:
                m = re.search(r"[.,!?;:…؟،]+$", toks[k])
                if m:
                    w["w"] = w["w"].rstrip(".,!?;:…؟،") + m.group(0)
                j = k + 1
                break
    return words


_groq_dead_until = 0.0
# modèle de transcription Groq : si Groq retire un modèle un jour, le suivant est pris automatiquement
_GROQ_MODELS = [m for m in (os.environ.get("GROQ_ASR_MODEL"), "whisper-large-v3", "whisper-large-v3-turbo") if m]
_groq_bad_models: set = set()


def _groq(mp3: Path, lang: str | None):
    global _groq_dead_until
    ks = groq_keys()
    if not ks or time.time() < _groq_dead_until:
        return None
    data = mp3.read_bytes()
    if len(data) > 24 * 1024 * 1024:
        return None
    for attempt in range(3):
        wait = 1e9
        for i, k in enumerate(ks):
            model = next((m for m in _GROQ_MODELS if m not in _groq_bad_models), None)
            if model is None:
                return None
            form = {"model": model, "response_format": "verbose_json", "temperature": "0"}
            files = [("file", ("audio.mp3", data, "audio/mpeg")), ("timestamp_granularities[]", (None, "word")),
                     ("timestamp_granularities[]", (None, "segment"))]
            if lang:
                form["language"] = lang
            try:
                r = requests.post("https://api.groq.com/openai/v1/audio/transcriptions",
                                  headers={"Authorization": f"Bearer {k}"}, data=form, files=files, timeout=300)
            except requests.RequestException as e:
                log.warning("Groq (clé %d) : %s", i + 1, e)
                continue
            if r.status_code == 429:
                try:
                    wait = min(wait, float(r.headers.get("retry-after") or 20))
                except ValueError:
                    wait = min(wait, 20)
                log.info("Groq (clé %d) : limite atteinte", i + 1)
                continue
            if r.status_code != 200:
                low = r.text.lower()
                if r.status_code in (400, 404) and "model" in low and re.search(r"decommission|not found|does not exist|"
                                                                                 r"not supported|deprecated", low):
                    log.warning("Groq : modèle %s retiré → modèle suivant", model)
                    _groq_bad_models.add(model)
                    return _groq(mp3, lang)
                log.warning("Groq (clé %d) : HTTP %s %s", i + 1, r.status_code, r.text[:160])
                continue
            j = r.json()
            words = [{"t0": float(w["start"]), "t1": float(w["end"]), "w": str(w.get("word", "")).strip()}
                     for w in j.get("words") or [] if str(w.get("word", "")).strip()]
            ln = str(j.get("language") or "").lower()
            return {"lang": LANGS.get(ln, ln[:2]), "words": _punctuate(words, j.get("segments") or [])}
        if wait > 90:
            _groq_dead_until = time.time() + wait
            log.warning("Groq : quota épuisé pour %d min → transcription locale", wait // 60)
            return None
        time.sleep(wait + 1)
    return None


_fw = {}


def _local(wav: Path, lang: str | None, long_video: bool):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        log.warning("faster-whisper absent : pas de transcription locale")
        return None
    name = os.environ.get("WHISPER_MODEL") or ("small" if long_video else "large-v3-turbo")
    if name not in _fw:
        log.info("Transcription locale : modèle %s (premier chargement : téléchargement)", name)
        try:
            _fw[name] = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=os.cpu_count() or 4)
        except Exception as e:  # noqa: BLE001
            log.warning("modèle %s indisponible (%s) → small", name, e)
            name = "small"
            _fw[name] = WhisperModel(name, device="cpu", compute_type="int8")
    segs, info = _fw[name].transcribe(str(wav), language=lang, word_timestamps=True, vad_filter=True, beam_size=1)
    words = []
    for s in segs:
        for w in s.words or []:
            t = (w.word or "").strip()
            if t:
                words.append({"t0": float(w.start), "t1": float(w.end), "w": t})
    return {"lang": info.language, "words": words}


def transcribe(media: Path, work: Path, lang: str | None = None, tag: str = "main") -> dict:
    """Transcrit un fichier audio/vidéo. Résultat mis en cache dans work/<tag>.transcript.json."""
    from .util import load_json, save_json
    cache = work / f"{tag}.transcript.json"
    hit = load_json(cache)
    if hit and hit.get("words") is not None:
        return hit
    work.mkdir(parents=True, exist_ok=True)
    wav = work / f"{tag}.16k.wav"
    run(["ffmpeg", "-y", "-i", media, "-vn", "-ac", "1", "-ar", "16000", wav], timeout=1800)
    dur = probe(wav)["duration"]
    sil = silences(wav)
    words, langs = [], []
    for n, (a, b) in enumerate(_chunks(dur, sil)):
        mp3 = work / f"{tag}.part{n}.mp3"
        run(["ffmpeg", "-y", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", wav, "-ac", "1", "-b:a", "64k", mp3])
        part = None
        try:
            part = _groq(mp3, lang)
        except Exception as e:  # noqa: BLE001
            log.warning("Groq : %s", e)
        if part is None:
            pw = work / f"{tag}.part{n}.wav"
            run(["ffmpeg", "-y", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", wav, pw])
            part = _local(pw, lang, dur > 2400)
            pw.unlink(missing_ok=True)
        mp3.unlink(missing_ok=True)
        if not part:
            continue
        langs.append(part.get("lang") or "")
        for w in part["words"]:
            words.append({"t0": round(w["t0"] + a, 3), "t1": round(max(w["t1"], w["t0"] + 0.05) + a, 3), "w": w["w"]})
        log.info("transcription %s : morceau %d (%.0f→%.0f s) : %d mots", tag, n + 1, a, b, len(part["words"]))
    words.sort(key=lambda w: w["t0"])
    lang_out = lang or (max(set(langs), key=langs.count) if langs else "")
    res = {"lang": (lang_out or "fr")[:2], "duration": dur, "words": words, "silences": sil}
    save_json(cache, res)
    wav.unlink(missing_ok=True)
    return res


def sentences(words: list, max_words: int = 28) -> list[dict]:
    """Phrases : coupe à la ponctuation finale, à une pause > 0,9 s, ou au-delà de max_words mots."""
    out, cur = [], []

    def flush():
        if cur:
            out.append({"i": len(out), "w0": cur[0], "w1": cur[-1], "t0": words[cur[0]]["t0"], "t1": words[cur[-1]]["t1"],
                        "text": " ".join(words[k]["w"] for k in cur)})
            cur.clear()
    for k, w in enumerate(words):
        if cur and w["t0"] - words[cur[-1]]["t1"] > 0.9:
            flush()
        cur.append(k)
        if re.search(r"[.!?…؟]['\"»”)]*$", w["w"]) or len(cur) >= max_words:
            flush()
    flush()
    return out
