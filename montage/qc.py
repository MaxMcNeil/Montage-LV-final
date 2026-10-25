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


def check(final: Path, segs: list, words: list, ass_path: Path) -> list[tuple[bool, str]]:
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

