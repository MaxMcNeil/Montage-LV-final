"""Contrôle qualité automatique de la vidéo finale (chaque run) : les défauts déjà rencontrés sont vérifiés à chaque
fois et signalés en tête de PLAN.md (et en avertissement GitHub), pour que le workflow reste fiable sans surveillance.

Vérifie : son et image de même durée ; aucune image noire au début ni de longue plage noire ; aucun extrait inséré
pendant que tu parles ; aucun texte d'habillage (accroche, chapitre, carte de fin) en même temps qu'un autre."""
from __future__ import annotations

import logging
import re
from pathlib import Path

from .util import run, tc

log = logging.getLogger("montage.qc")


def _ass_events(path: Path) -> list[tuple[float, float, str]]:
    def sec(t):
        h, m, s = t.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)
    out = []
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.startswith("Dialogue:"):
                p = line.split(",", 9)
                out.append((sec(p[1]), sec(p[2]), p[3]))
    except OSError:
        pass
    return out


def check(final: Path, segs: list, words: list, ass_path: Path, long_gap: float | None = None,
          kw_info: dict | None = None, subs_off: bool = False) -> list[tuple[bool, str]]:
    res: list[tuple[bool, str]] = []
    # 1) durées son / image
    try:
        r = run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration", "-of", "csv=p=0", final])
        d = {}
        for line in r.stdout.splitlines():
            k, _, v = line.partition(",")
            try:
                d[k] = float(v)
            except ValueError:
                pass
        gap = abs(d.get("video", 0) - d.get("audio", 0))
        res.append((gap < 0.15, f"son et image synchronisés (écart {gap:.2f} s)"))
    except Exception as e:  # noqa: BLE001
        res.append((False, f"durées illisibles : {e}"))
    # 2) images noires
    r = run(["ffmpeg", "-hide_banner", "-nostdin", "-i", final, "-an", "-vf",
             "scale=320:-2,blackdetect=d=0.12:pic_th=0.97:pix_th=0.10", "-f", "null", "-"], check=False, timeout=1800)
    blacks = [(float(a), float(b)) for a, b in re.findall(r"black_start:\s*([\d.]+)\s+black_end:\s*([\d.]+)", r.stderr or "")]
    first = [b for b in blacks if b[0] < 0.05]
    res.append((not first, "aucune image noire au début" if not first else f"noir au début ({first[0][1]:.2f} s)"))
    long_b = [b for b in blacks if b[1] - b[0] > 0.6 and b[0] >= 0.05]
    res.append((not long_b, "aucune plage noire" if not long_b else
                "plage(s) noire(s) : " + ", ".join(f"{tc(a)} ({b - a:.1f} s)" for a, b in long_b[:5])))
    # 3) extraits insérés : jamais pendant un mot
    bad = []
    for s in segs:
        if s.kind != "insert" or s.insert.get("opener"):
            continue
        t_src = s.insert.get("t")
        if t_src is None:
            continue
        for w in words:
            if w["t0"] - 0.05 < t_src < w["t1"] + 0.05:
                bad.append(f"{tc(s.out0)} (sur « {w['w']} »)")
                break
    n_ins = sum(1 for s in segs if s.kind == "insert" and not s.insert.get("opener"))
    res.append((not bad, f"{n_ins} extrait(s) inséré(s), tous dans un silence" if not bad else
                "extrait(s) pendant la parole : " + ", ".join(bad)))
    # 3b) silences longs restants (entre deux de tes mots, hors extraits insérés)
    if long_gap:
        from .timeline import out_time
        ins = [(s.out0, s.out0 + s.dur) for s in segs if s.kind == "insert"]
        left = []
        for w1, w2 in zip(words, words[1:]):
            a, b = out_time(segs, w1["t1"]), out_time(segs, w2["t0"])
            if a is None or b is None or b - a <= long_gap + 0.3:
                continue
            if any(a - 0.1 <= x0 and x1 <= b + 0.1 for x0, x1 in ins):
                continue
            left.append(f"{tc(a)} ({b - a:.1f} s)")
        res.append((not left, f"aucun silence de plus de {long_gap:.0f} s" if not left else
                    f"{len(left)} silence(s) long(s) gardé(s) (son non silencieux ?) : " + ", ".join(left[:6])))
    # 3c) mots-clés « écoutez… » : un extrait juste après chaque annonce
    if kw_info is not None:
        from .timeline import out_time
        its = kw_info["items"]
        bad = []
        for it in its:
            if not it["inserted"]:
                bad.append(f"« {it['phrase']} » à {tc(out_time(segs, it['t0']) or 0)} sans extrait")
                continue
            t_end = out_time(segs, it["t1"])
            if t_end is None or not (t_end - 0.05 <= it["out"] <= t_end + 8.5):
                bad.append(f"extrait de « {it['phrase']} » mal placé ({tc(it['out'])})")
            ck = it.get("check") or {}
            if ck and not ck.get("ok"):
                bad.append(f"cohérence douteuse à {tc(it['out'])}")
        res.append((not bad, f"{len(its)} « écoutez… » → {sum(1 for i in its if i['inserted'])} extrait(s) juste après"
                    if not bad else "mots-clés : " + ", ".join(bad[:6])))
    # 3d) blancs réellement entendus dans la vidéo finale (mesurés sur le son final : extraits compris)
    if long_gap:
        try:
            import subprocess
            import numpy as np
            r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-i", str(final), "-vn", "-ac", "1",
                                "-ar", "8000", "-f", "s16le", "-"], capture_output=True, timeout=1800)
            x = np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0
            n = len(x) // 160
            if n > 100:
                db = 20 * np.log10(np.sqrt(np.mean(x[:n * 160].reshape(n, 160) ** 2, axis=1) + 1e-12) + 1e-9)
                thr = float(np.percentile(db, 60)) - 15.0
                low = db < thr
                blancs, k = [], 0
                while k < n:
                    if low[k]:
                        j = k
                        while j < n and low[j]:
                            j += 1
                        if (j - k) * 0.02 >= long_gap + 0.2 and k > 25 and j < n - 25:   # hors tout début / toute fin
                            blancs.append(f"{tc(k * 0.02)} ({(j - k) * 0.02:.1f} s)")
                        k = j
                    else:
                        k += 1
                res.append((not blancs, f"aucun blanc de plus de {long_gap:.0f} s à l'écoute" if not blancs else
                            f"{len(blancs)} blanc(s) de plus de {long_gap:.0f} s à l'écoute : " + ", ".join(blancs[:8])))
        except Exception as e:  # noqa: BLE001
            log.warning("mesure des blancs impossible : %s", e)
    # 3e) sous-titres désactivés : vraiment AUCUN sous-titre (ni de ta voix, ni des extraits)
    if subs_off:
        n_sub = sum(1 for e in _ass_events(ass_path) if e[2] in ("Cap", "Sub"))
        res.append((n_sub == 0, "sous-titres désactivés : aucun sous-titre à l'écran" if n_sub == 0 else
                    f"sous-titres désactivés mais {n_sub} sous-titre(s) présent(s)"))
    # 4) textes d'habillage qui se chevauchent
    ev = [e for e in _ass_events(ass_path) if e[2] in ("Hook", "Chap", "Outro")]
    over = []
    for i, a in enumerate(ev):
        for b in ev[i + 1:]:
            if a[2] != b[2] and min(a[1], b[1]) - max(a[0], b[0]) > 0.2:
                over.append(f"{a[2]}/{b[2]} à {tc(max(a[0], b[0]))}")
    res.append((not over, "aucun texte superposé" if not over else "textes superposés : " + ", ".join(over[:5])))
    for ok, msg in res:
        if not ok:
            print(f"::warning::Contrôle qualité — {msg}")
    log.info("Contrôle qualité : %s", " | ".join(("✅ " if ok else "⚠ ") + m for ok, m in res))
    return res

