"""Rendu ffmpeg, segment par segment (mémoire faible, robuste), puis assemblage sans ré-encodage.

- plein cadre : toi, avec des zooms de relance qui changent à chaque coupe (les coupes deviennent invisibles) ;
- partage d'écran : fond = toi flouté teinté bleu nuit, toi dans un cadre arrondi avec ombre, média qui glisse
  à côté (photo animée en lent travelling) ; fondu enchaîné depuis et vers le plein cadre ;
- extrait inséré : tu disparais, transition glissée depuis ton image, l'extrait joue avec son propre son, retour.
Le son est monté à part, à l'échantillon près (numpy) : pas de décalage son/image, pas de clic aux coupes."""
from __future__ import annotations

import logging
import math
import os
import threading
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from . import config as C
from .config import FPS, GEOM, SAMPLE_RATE, SIZE
from .panels import card_layers
from .util import clamp, frames, run

log = logging.getLogger("montage.render")
SPF = SAMPLE_RATE // FPS  # échantillons par image (1600)
X264 = ["-c:v", "libx264", "-preset", os.environ.get("X264_PRESET", "veryfast"), "-crf", os.environ.get("X264_CRF", "20"),
        "-pix_fmt", "yuv420p", "-r", str(FPS), "-g", str(FPS * 2), "-video_track_timescale", "15360", "-an"]


def _even(x: float) -> int:
    v = int(math.ceil(x))
    return v + (v % 2)


class Ctx:
    def __init__(self, src: Path, info: dict, face: dict, orient: str, work: Path, ass_path: Path, fonts: Path | None):
        self.src, self.info, self.face, self.o, self.work = src, info, face, orient, work
        self.W, self.H = SIZE[orient]
        self.ass = ass_path
        self.fonts = fonts
        self.sw, self.sh = info["w"], info["h"]

    def full_chain(self, z: float = 1.0) -> str:
        W, H = self.W, self.H
        s = max(W / self.sw, H / self.sh) * z
        SW, SH = _even(self.sw * s), _even(self.sh * s)
        x = int(clamp(self.face["cx"] * SW - W / 2, 0, SW - W))
        y = int(clamp(self.face["cy"] * SH - H * 0.42, 0, SH - H))
        return f"scale={SW}:{SH}:flags=bicubic,crop={W}:{H}:{x}:{y},setsar=1"

    def card_crop(self, cw: int, ch: int) -> str:
        """Recadrage (dans l'image plein cadre) pour le cadre arrondi : visage centré, proportions du cadre."""
        W, H = self.W, self.H
        s = max(W / self.sw, H / self.sh)
        SW, SH = _even(self.sw * s), _even(self.sh * s)
        x1 = clamp(self.face["cx"] * SW - W / 2, 0, SW - W)
        y1 = clamp(self.face["cy"] * SH - H * 0.42, 0, SH - H)
        fx, fy = self.face["cx"] * SW - x1, self.face["cy"] * SH - y1
        r = cw / ch
        hh = H * 0.97
        ww = hh * r
        if ww > W * 0.98:
            ww = W * 0.98
            hh = ww / r
        ww, hh = int(ww) // 2 * 2, int(hh) // 2 * 2
        x = int(clamp(fx - ww / 2, 0, W - ww))
        y = int(clamp(fy - hh * 0.40, 0, H - hh))
        return f"crop={ww}:{hh}:{x}:{y},scale={cw}:{ch}:flags=bicubic,setsar=1"

    def ass_tail(self, off: float) -> str:
        if not self.ass or not Path(self.ass).exists():
            return "format=yuv420p"
        fd = f":fontsdir='{self.fonts}'" if self.fonts and Path(self.fonts).is_dir() else ""
        return f"setpts=PTS+{off:.4f}/TB,ass=filename='{self.ass}'{fd},setpts=PTS-STARTPTS,format=yuv420p"


# Habillage de chaîne (montage/chaine.py) : {"bug", "bug_xy", "end", "end_xy", "end_t0"} — None = aucun logo.
BRAND: dict | None = None
BRAND_FAILS: list = []          # segments rendus SANS logo après un échec (signalés dans PLAN.md)
_TL = threading.local()         # par fil de rendu : t0 = début du segment dans la vidéo finale, off = logo désactivé


class Graph:
    def __init__(self):
        self.inputs: list[list[str]] = []
        self.lines: list[str] = []

    def inp(self, *args) -> int:
        self.inputs.append([str(a) for a in args])
        return len(self.inputs) - 1

    def add(self, s: str):
        self.lines.append(s)

    def _brand(self, label: str, n: int) -> str:
        """Ajoute le petit logo permanent (et le grand logo de fin) par-dessus l'image finale du segment."""
        b = BRAND
        if not b or getattr(_TL, "off", False) or not (b.get("bug") or b.get("end")):
            return label
        t0 = getattr(_TL, "t0", None)
        d = n / FPS
        cur = label
        end_rel = (b["end_t0"] - t0) if (b.get("end") and t0 is not None and b.get("end_t0") is not None) else None
        if end_rel is not None and end_rel >= d:
            end_rel = None                       # la carte de fin n'est pas dans ce segment
        if b.get("bug"):
            i = self.inp("-loop", "1", "-framerate", FPS, "-t", f"{d + 1:.3f}", "-i", b["bug"])
            x, y = b["bug_xy"]
            en = f":enable='lt(t,{max(0.0, end_rel):.3f})'" if end_rel is not None else ""
            self.add(f"[{cur}][{i}:v]overlay=x={x}:y={y}:format=auto{en},format=yuv420p[brand1]")
            cur = "brand1"
        if end_rel is not None:
            i = self.inp("-loop", "1", "-framerate", FPS, "-t", f"{d + 1:.3f}", "-i", b["end"])
            x, y = b["end_xy"]
            st = max(0.0, end_rel)
            self.add(f"[{i}:v]format=rgba,fade=t=in:st={st:.3f}:d=0.5:alpha=1[brandl]")
            self.add(f"[{cur}][brandl]overlay=x={x}:y={y}:format=auto:enable='gte(t,{st:.3f})',format=yuv420p[brand2]")
            cur = "brand2"
        return cur

    def run(self, out: Path, n: int, label: str, script: Path):
        label = self._brand(label, n)
        script.write_text(";\n".join(self.lines), encoding="utf-8")
        cmd = ["ffmpeg", "-y"]
        for i in self.inputs:
            cmd += i
        cmd += ["-filter_complex_script", str(script), "-map", f"[{label}]", "-frames:v", str(n)] + X264 + [str(out)]
        run(cmd, timeout=3600)


def _talk(g: Graph, ctx: Ctx, atoms, chain_for) -> str:
    """Concatène les morceaux de ta vidéo (chacun avec son propre traitement) → étiquette [cat]."""
    labels = []
    for k, at in enumerate(atoms):
        n = frames(at.b - at.a)
        i = g.inp("-ss", f"{at.a:.4f}", "-t", f"{at.b - at.a + 0.6:.4f}", "-i", ctx.src)
        g.add(f"[{i}:v]fps={FPS},tpad=stop_mode=clone:stop_duration=1,trim=end_frame={n},setpts=N/{FPS}/TB,"
              f"{chain_for(at)},settb=1/{FPS},format=yuv420p[t{k}]")
        nx = min(frames(getattr(at, "xin", 0.0) or 0.0), n - 1)
        if k > 0 and nx >= 3 and getattr(at, "xfrom", None) is not None:
            # fondu doux : les images du silence supprimé (juste après le morceau précédent) se fondent dans celui-ci —
            # la durée ne change pas, le son reste parfaitement synchro
            p = at.xfrom
            j = g.inp("-ss", f"{p.b:.4f}", "-t", f"{nx / FPS + 0.6:.4f}", "-i", ctx.src)
            g.add(f"[{j}:v]fps={FPS},tpad=stop_mode=clone:stop_duration=1,trim=end_frame={nx + 2},setpts=N/{FPS}/TB,"
                  f"{chain_for(p)},settb=1/{FPS},format=yuv420p[xa{k}]")
            g.add(f"[xa{k}][t{k}]xfade=transition=fade:duration={nx / FPS:.4f}:offset=0,"
                  f"trim=end_frame={n},setpts=N/{FPS}/TB[tx{k}]")
            labels.append(f"[tx{k}]")
            continue
        labels.append(f"[t{k}]")
    if len(labels) == 1:
        g.add(f"{labels[0]}null[cat]")
    else:
        g.add(f"{''.join(labels)}concat=n={len(labels)}:v=1:a=0[cat]")
    return "cat"


def render_full(seg, ctx: Ctx, out: Path):
    g = Graph()
    _talk(g, ctx, seg.atoms, lambda at: ctx.full_chain(at.zoom))
    g.add(f"[cat]tpad=stop_mode=clone:stop_duration=1,{ctx.ass_tail(seg.out0)}[out]")
    g.run(out, seg.n, "out", out.with_suffix(".txt"))


def render_split(seg, ctx: Ctx, out: Path):
    W, H, D, N = ctx.W, ctx.H, seg.dur, seg.n
    geo = GEOM[ctx.o][seg.side]
    cx, cy, cw, ch = geo["card"]
    px, py, pw, ph = geo["panel"]
    P = C.SHADOW_PAD
    lay = card_layers(cw, ch, ctx.work / "layers")
    panel = seg.panel["v"]["asset"]
    g = Graph()
    _talk(g, ctx, seg.atoms, lambda at: ctx.full_chain(1.0))
    tdur = D + 1
    im_mask = g.inp("-loop", "1", "-framerate", FPS, "-t", f"{tdur:.3f}", "-i", lay["mask"])
    im_under = g.inp("-loop", "1", "-framerate", FPS, "-t", f"{tdur:.3f}", "-i", lay["under"])
    im_over = g.inp("-loop", "1", "-framerate", FPS, "-t", f"{tdur:.3f}", "-i", lay["over"])
    im_frame = g.inp("-loop", "1", "-framerate", FPS, "-t", f"{tdur:.3f}", "-i", panel["frame"])
    fa_n = min(int(0.5 * FPS), N // 3)
    fb_n = min(int(0.42 * FPS), N // 3)
    g.add("[cat]split=4[cbg][ccard][cfa][cfb]")
    g.add(f"[cbg]scale={W // 6}:{H // 6},boxblur=6:2,scale={W}:{H},eq=brightness=-0.06:saturation=0.5[bg0]")
    g.add(f"color=c={C.ff_color(C.NAVY, 0.50)}:s={W}x{H}:r={FPS}[tint]")
    g.add("[bg0][tint]overlay=shortest=1[bg]")
    g.add(f"[ccard]{ctx.card_crop(cw, ch)},format=yuva420p[cv]")
    g.add(f"[{im_mask}:v]format=gray,scale={cw}:{ch}[mk]")
    g.add("[cv][mk]alphamerge[card]")
    g.add(f"[bg][{im_under}:v]overlay=x={cx - P}:y={cy - P}:shortest=1[b1]")
    g.add(f"[b1][card]overlay=x={cx}:y={cy}[b2]")
    g.add(f"[b2][{im_over}:v]overlay=x={cx}:y={cy}:shortest=1[b3]")
    # carte média (avec photo animée derrière le trou du cadre)
    fw, fh = panel["size"]
    if panel.get("photo") and panel.get("hole"):
        hx, hy, hw, hh = panel["hole"]
        im_photo = g.inp("-loop", "1", "-framerate", FPS, "-t", f"{tdur:.3f}", "-i", panel["photo"])
        tf = max(1, N)
        zx = "iw/2-(iw/zoom/2)" if seg.side == "left" else "(iw-iw/zoom)*0.35"
        g.add(f"[{im_photo}:v]zoompan=z='1.0+0.085*on/{tf}':x='{zx}':y='ih/2-(ih/zoom/2)':d=1:s={hw}x{hh}:fps={FPS},"
              f"setsar=1[kb]")
        g.add(f"color=c=black@0.0:s={fw}x{fh}:r={FPS},format=rgba[pc]")
        g.add(f"[pc][kb]overlay=x={hx}:y={hy}:format=rgb:shortest=1[pk]")
        g.add(f"[pk][{im_frame}:v]overlay=format=rgb:shortest=1[pn]")
    else:
        g.add(f"[{im_frame}:v]format=rgba[pn]")
    t_in, d_in, d_out = 0.18, 0.62, 0.45
    t_out = max(t_in + d_in + 0.2, D - d_out - 0.12)
    g.add(f"[pn]fade=t=in:st={t_in}:d={d_in * 0.7:.3f}:alpha=1,fade=t=out:st={t_out:.3f}:d={d_out}:alpha=1[pf]")
    x1 = px - P
    if ctx.o == "h":
        x0 = W + 40 if seg.side == "left" else -fw - 40
        x2 = x0
        xe = (f"if(lt(t,{t_in}),{x0},if(lt(t,{t_in + d_in}),{x0}+({x1}-({x0}))*(1-pow(1-(t-{t_in})/{d_in},3)),"
              f"if(lt(t,{t_out:.3f}),{x1},{x1}+({x2}-({x1}))*pow((t-{t_out:.3f})/{d_out},3))))")
        ye = f"{py - P}"
    else:
        y1 = py - P
        y0 = H + 40
        xe = f"{x1}"
        ye = (f"if(lt(t,{t_in}),{y0},if(lt(t,{t_in + d_in}),{y0}+({y1}-({y0}))*(1-pow(1-(t-{t_in})/{d_in},3)),"
              f"if(lt(t,{t_out:.3f}),{y1},{y1}+({y0}-({y1}))*pow((t-{t_out:.3f})/{d_out},3))))")
    g.add(f"[b3][pf]overlay=x='{xe}':y='{ye}':eval=frame:shortest=1[b4]")
    norm = f"fps={FPS},settb=1/{FPS},format=yuv420p"
    g.add(f"[b4]{norm}[comp]")
    g.add(f"[cfa]trim=end_frame={fa_n + 2},setpts=PTS-STARTPTS,{norm}[fa]")
    g.add(f"[cfb]trim=start_frame={N - fb_n},setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration=1,{norm}[fb]")
    g.add(f"[fa][comp]xfade=transition=fade:duration={fa_n / FPS:.4f}:offset=0[x1]")
    g.add(f"[x1][fb]xfade=transition=fade:duration={fb_n / FPS:.4f}:offset={(N - fb_n) / FPS:.4f}[x2]")
    g.add(f"[x2]tpad=stop_mode=clone:stop_duration=1,{ctx.ass_tail(seg.out0)}[out]")
    g.run(out, N, "out", out.with_suffix(".txt"))


def freeze(ctx: Ctx, t: float, out: Path) -> Path:
    t = max(0.0, min(t, ctx.info["duration"] - 0.05))
    run(["ffmpeg", "-y", "-ss", f"{t:.4f}", "-i", ctx.src, "-frames:v", "1", "-vf", ctx.full_chain(1.0), out])
    return out


OPENER_NOTES: list = []   # comment l'ouverture choc a été habillée (PLAN.md)
INSERT_NOTES: list = []   # extraits du milieu qui n'ont pas pu être encadrés (PLAN.md)


def _opener_framed(seg, ctx: Ctx, out: Path, pa: Path, pb: Path, mode: str, opener: bool = True):
    """Ouverture choc JAMAIS en plein écran (règle YouTube contenu réutilisé / monétisation) :
      cadre : toi (image de ta 1re prise, très lent zoom) dans ton cadre arrondi + l'extrait dans un cadre arrondi à
              côté (horizontal) ou dessous (vertical), sur ton fond flouté teinté bleu nuit — sobre, pas « bling » ;
      simple : l'extrait réduit à 80 %, centré, sur ce même fond (repli si le cadre échoue).
    Le petit logo de la chaîne s'ajoute par-dessus comme partout (Graph.run). Fin : fondu vers ta 1re prise."""
    ins = seg.insert["asset"]
    N = seg.n
    W, H = ctx.W, ctx.H
    P = C.SHADOW_PAD
    tdur = N / FPS + 1
    g = Graph()
    i_clip = g.inp("-i", ins["video"])
    i_a = g.inp("-loop", "1", "-framerate", FPS, "-t", f"{tdur:.3f}", "-i", pa)
    i_b = g.inp("-loop", "1", "-framerate", FPS, "-t", "1", "-i", pb)
    norm = f"fps={FPS},settb=1/{FPS},format=yuv420p"
    dout = min(0.45, N / FPS / 4)
    g.add(f"[{i_clip}:v]{norm},setpts=N/{FPS}/TB,tpad=stop_mode=clone:stop_duration=1,trim=end_frame={N}[cl]")
    g.add(f"[{i_a}:v]fps={FPS},setsar=1,split=2[abg][acard]")
    g.add(f"[abg]scale={W // 6}:{H // 6},boxblur=6:2,scale={W}:{H},eq=brightness=-0.06:saturation=0.5,"
          f"trim=end_frame={N + 2}[bg0]")
    g.add(f"color=c={C.ff_color(C.NAVY, 0.50)}:s={W}x{H}:r={FPS}[tint]")
    g.add("[bg0][tint]overlay=shortest=1,format=yuv420p[bg]")
    if mode == "cadre":
        geo = GEOM[ctx.o]["left"]
        cx, cy, cw, ch = geo["card"]
        px, py, pw, ph = geo["panel"]
        lay = card_layers(cw, ch, ctx.work / "layers")
        if ctx.o == "h":   # extrait entier visible (aucune partie coupée), centré dans la zone média
            vw, vh = pw // 2 * 2, int(pw * H / W) // 2 * 2
        else:              # vertical : la zone sous toi est remplie (centre de l'extrait)
            vw, vh = pw // 2 * 2, ph // 2 * 2
        vx, vy = px + (pw - vw) // 2, py + (ph - vh) // 2
        lv = card_layers(vw, vh, ctx.work / "layers")
        ims = {n_: g.inp("-loop", "1", "-framerate", FPS, "-t", f"{tdur:.3f}", "-i", f_)
               for n_, f_ in (("m", lay["mask"]), ("u", lay["under"]), ("o", lay["over"]),
                              ("vm", lv["mask"]), ("vu", lv["under"]), ("vo", lv["over"]))}
        g.add(f"[acard]{ctx.card_crop(cw, ch)},zoompan=z='1.0+0.04*on/{max(1, N)}':x='iw/2-(iw/zoom/2)':"
              f"y='ih/2-(ih/zoom/2)':d=1:s={cw}x{ch}:fps={FPS},setsar=1,format=yuva420p[cv]")
        g.add(f"[{ims['m']}:v]format=gray,scale={cw}:{ch}[mk]")
        g.add("[cv][mk]alphamerge[card]")
        g.add(f"[cl]scale={vw}:{vh}:force_original_aspect_ratio=increase:flags=bicubic,crop={vw}:{vh},setsar=1,"
              f"format=yuva420p[clv]")
        g.add(f"[{ims['vm']}:v]format=gray,scale={vw}:{vh}[vmk]")
        g.add("[clv][vmk]alphamerge[clr]")
        g.add(f"[bg][{ims['u']}:v]overlay=x={cx - P}:y={cy - P}:shortest=1[b1]")
        g.add(f"[b1][card]overlay=x={cx}:y={cy}:shortest=1[b2]")
        g.add(f"[b2][{ims['o']}:v]overlay=x={cx}:y={cy}:shortest=1[b3]")
        g.add(f"[b3][{ims['vu']}:v]overlay=x={vx - P}:y={vy - P}:shortest=1[b4]")
        g.add(f"[b4][clr]overlay=x={vx}:y={vy}:shortest=1[b5]")
        g.add(f"[b5][{ims['vo']}:v]overlay=x={vx}:y={vy}:shortest=1,{norm}[x1]")
    else:
        vw, vh = int(W * 0.8) // 2 * 2, int(H * 0.8) // 2 * 2
        g.add("[acard]nullsink")
        g.add(f"[cl]scale={vw}:{vh}:flags=bicubic,setsar=1[clv]")
        g.add(f"[bg][clv]overlay=x={(W - vw) // 2}:y={(H - vh) // 2}:shortest=1,{norm}[x1]")
    g.add(f"[{i_b}:v]{norm}[fb]")
    if not opener:   # extrait au milieu : fondu doux depuis ton plan (pas de coupe sèche)
        din = min(0.5, N / FPS / 4)
        i_a2 = g.inp("-loop", "1", "-framerate", FPS, "-t", "1", "-i", pa)
        g.add(f"[{i_a2}:v]{norm}[fa]")
        g.add(f"[fa][x1]xfade=transition=fade:duration={din:.3f}:offset=0[x1b]")
        g.add(f"[x1b]trim=end_frame={N},setpts=PTS-STARTPTS[x1c]")
        x1 = "x1c"
    else:
        x1 = "x1"
    g.add(f"[{x1}][fb]xfade=transition=fade:duration={dout:.3f}:offset={N / FPS - dout:.4f}[x2]")
    g.add(f"[x2]tpad=stop_mode=clone:stop_duration=1,{ctx.ass_tail(seg.out0)}[out]")
    g.run(out, N, "out", out.with_suffix(".txt"))


def render_insert(seg, ctx: Ctx, out: Path, prev_t: float, next_t: float, k: int):
    ins = seg.insert["asset"]
    N = seg.n
    opener = bool(seg.insert.get("opener"))
    pa = freeze(ctx, prev_t, ctx.work / f"freeze_{k}_a.png")
    pb = freeze(ctx, next_t, ctx.work / f"freeze_{k}_b.png")
    if opener:   # ouverture choc : jamais en plein écran — toi visible à côté, sinon extrait réduit sur ton fond
        for mode in ("cadre", "simple"):
            try:
                _opener_framed(seg, ctx, out, pa, pb, mode)
                OPENER_NOTES.append("ouverture choc habillée : " + (
                    "toi dans ton cadre + l'extrait dans un cadre à côté (jamais en plein écran)" if mode == "cadre"
                    else "extrait réduit à 80 % sur ton fond (le cadre n'a pas pu être fait)"))
                return
            except Exception as e:  # noqa: BLE001
                log.warning("ouverture choc (%s) en échec : %s", mode, str(e)[-400:])
        OPENER_NOTES.append("⚠ ouverture choc : habillage impossible → image fixe de toi à la place de l'extrait")
        raise RuntimeError("ouverture choc : habillage impossible")
    # extrait au milieu de la vidéo : lui aussi JAMAIS en plein écran (contenu réutilisé) — toi visible à côté
    for mode in ("cadre", "simple"):
        try:
            _opener_framed(seg, ctx, out, pa, pb, mode, opener=False)
            if mode == "simple":
                INSERT_NOTES.append(f"extrait à {seg.out0:.0f} s : réduit à 80 % (le cadre n'a pas pu être fait)")
            return
        except Exception as e:  # noqa: BLE001
            log.warning("extrait %d (%s) en échec : %s", k, mode, str(e)[-400:])
    INSERT_NOTES.append(f"⚠ extrait à {seg.out0:.0f} s : habillage impossible → affiché en plein écran")
    g = Graph()
    i_clip = g.inp("-i", ins["video"])
    i_a = g.inp("-loop", "1", "-framerate", FPS, "-t", "1", "-i", pa)
    i_b = g.inp("-loop", "1", "-framerate", FPS, "-t", "1", "-i", pb)
    norm = f"fps={FPS},settb=1/{FPS},format=yuv420p"
    din, dout = min(0.55, N / FPS / 4), min(0.45, N / FPS / 4)
    g.add(f"[{i_clip}:v]{norm},setpts=N/{FPS}/TB,tpad=stop_mode=clone:stop_duration=1,trim=end_frame={N}[cl]")
    g.add(f"[{i_a}:v]{norm}[fa]")
    g.add(f"[{i_b}:v]{norm}[fb]")
    if opener:  # ouverture : l'extrait démarre sur la toute première image (aucun noir, aucune transition)
        g.add("[fa]nullsink")
        g.add("[cl]null[x1]")
    else:
        g.add(f"[fa][cl]xfade=transition=smoothleft:duration={din:.3f}:offset=0[x1]")
    g.add(f"[x1][fb]xfade=transition=smoothright:duration={dout:.3f}:offset={N / FPS - dout:.4f}[x2]")
    g.add(f"[x2]tpad=stop_mode=clone:stop_duration=1,{ctx.ass_tail(seg.out0)}[out]")
    g.run(out, N, "out", out.with_suffix(".txt"))


def render_video(segs, ctx: Ctx, out: Path, workers: int = 2) -> Path:
    d = ctx.work / "segments"
    d.mkdir(parents=True, exist_ok=True)
    jobs = []
    for k, s in enumerate(segs):
        f = d / f"seg{k:04d}.mp4"
        if s.kind == "insert":
            prev = next((x for x in reversed(segs[:k]) if x.kind != "insert"), None)
            nxt = next((x for x in segs[k + 1:] if x.kind != "insert"), None)
            pt = prev.atoms[-1].b - 1 / FPS if prev else (nxt.atoms[0].a if nxt else 0)
            nt = nxt.atoms[0].a if nxt else pt
            jobs.append((render_insert, (s, ctx, f, pt, nt, k), f))
        elif s.kind == "split":
            jobs.append((render_split, (s, ctx, f), f))
        else:
            jobs.append((render_full, (s, ctx, f), f))

    def go(job):
        fn, args, f = job
        _TL.t0, _TL.off = args[0].out0, False
        try:
            try:
                fn(*args)
            except Exception as e:  # noqa: BLE001
                if not BRAND:
                    raise
                # le logo ne doit jamais coûter un segment : nouvel essai sans logo (signalé dans PLAN.md)
                log.warning("segment %s : échec avec le logo → nouvel essai sans logo : %s", f.name, str(e)[-300:])
                _TL.off = True
                fn(*args)
                BRAND_FAILS.append(f.name)   # réussi sans logo : c'était bien le logo
        except Exception as e:  # noqa: BLE001
            s = args[0]
            if s.kind == "full":
                raise
            # un effet en échec ne doit pas faire perdre la vidéo : repli en plein cadre (ou plan figé pour un extrait)
            log.warning("segment %s (%s) en échec → version simple : %s", f.name, s.kind, str(e)[-400:])
            if s.kind == "split":
                render_full(s, ctx, f)
            else:
                g = Graph()
                i = g.inp("-loop", "1", "-framerate", FPS, "-t", f"{s.dur + 1:.3f}", "-i",
                          ctx.work / f"freeze_{args[-1]}_a.png")
                g.add(f"[{i}:v]fps={FPS},format=yuv420p,{ctx.ass_tail(s.out0)}[out]")
                g.run(f, s.n, "out", f.with_suffix(".txt"))
        return f
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        files = list(ex.map(go, jobs))
        for k, _ in enumerate(files):
            if (k + 1) % 10 == 0 or k + 1 == len(files):
                log.info("rendu : %d/%d segments", k + 1, len(files))
    lst = d / "list.txt"
    lst.write_text("".join(f"file '{f.resolve()}'\n" for f in files), encoding="utf-8")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", out], timeout=1800)
    return out


# ------------------------------------------------------------------ son
def _read(path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        ch, n = w.getnchannels(), w.getnframes()
        a = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32) / 32768.0
    a = a.reshape(-1, ch)
    if ch == 1:
        a = np.repeat(a, 2, axis=1)
    return a[:, :2]


def _wav_map(path) -> np.ndarray:
    """Son PCM 16 bits lu SANS le charger en mémoire (np.memmap) : une vidéo d'une heure ne sature jamais la machine."""
    import struct
    ch = bits = None
    with open(path, "rb") as f:
        head = f.read(12)
        if head[:4] != b"RIFF" or head[8:12] != b"WAVE":
            raise ValueError("WAV illisible")
        while True:
            hdr = f.read(8)
            if len(hdr) < 8:
                raise ValueError("WAV sans données")
            cid, size = hdr[:4], struct.unpack("<I", hdr[4:])[0]
            if cid == b"data":
                pos = f.tell()
                break
            body = f.read(size + (size & 1))
            if cid == b"fmt ":
                ch, bits = struct.unpack("<H", body[2:4])[0], struct.unpack("<H", body[14:16])[0]
    if ch is None or bits != 16:
        raise ValueError("WAV non 16 bits")
    total = (Path(path).stat().st_size - pos) // (2 * ch)
    if 0 < size < 0xFFFFFFF0:
        total = min(total, size // (2 * ch))
    return np.memmap(path, dtype=np.int16, mode="r", offset=pos, shape=(total, ch))


class _Main:
    """Accès par morceaux au son principal (float32 stéréo à la demande)."""

    def __init__(self, path):
        self.m = None
        try:
            self.m = _wav_map(path) if path and Path(path).exists() else None
        except (ValueError, OSError) as e:
            log.warning("son principal en lecture directe impossible (%s) : lecture complète", e)
            self.full = _read(path)

    def __len__(self):
        return len(self.m) if self.m is not None else len(self.full)

    def get(self, s0: int, n: int) -> np.ndarray:
        if self.m is None:
            return self.full[s0:s0 + n]
        x = np.asarray(self.m[s0:s0 + n], dtype=np.float32) / 32768.0
        if x.ndim == 1:
            x = x[:, None]
        if x.shape[1] == 1:
            x = np.repeat(x, 2, axis=1)
        return x[:, :2]


def _fade(x: np.ndarray, n_in: int, n_out: int) -> np.ndarray:
    x = x.copy()
    if n_in and len(x) > n_in:
        x[:n_in] *= np.linspace(0, 1, n_in, dtype=np.float32)[:, None]
    if n_out and len(x) > n_out:
        x[-n_out:] *= np.linspace(1, 0, n_out, dtype=np.float32)[:, None]
    return x


def sfx_whoosh(seed: int = 0) -> np.ndarray:
    """Souffle discret synthétisé (bruit filtré, enveloppe douce) — pas de musique."""
    rng = np.random.default_rng(seed)
    n = int(0.55 * SAMPLE_RATE)
    noise = rng.standard_normal(n).astype(np.float32)
    spec = np.fft.rfft(noise)
    f = np.fft.rfftfreq(n, 1 / SAMPLE_RATE)
    spec *= np.exp(-((np.log(f + 1) - np.log(1400)) ** 2) / 0.9)
    s = np.fft.irfft(spec, n).astype(np.float32)
    t = np.linspace(0, 1, n, dtype=np.float32)
    env = np.sin(np.pi * t ** 0.7) ** 2
    s = s * env
    s /= (np.abs(s).max() + 1e-9)
    pan = np.stack([s * (1 - 0.3 * t), s * (0.7 + 0.3 * t)], axis=1)
    return pan * 0.075


def sfx_chapter() -> np.ndarray:
    """Petit générique de chapitre façon journal télévisé, entièrement synthétisé (aucun droit d'auteur) :
    souffle montant 0,3 s → impact grave feutré + deux notes de cloche (mi puis si-mi à l'octave), qui s'éteignent
    en 1,5 s. Volume discret : présent sans couvrir ta voix. L'impact tombe 0,3 s après le début du son."""
    sr = SAMPLE_RATE
    n = int(1.9 * sr)
    t = np.arange(n, dtype=np.float32) / sr
    out = np.zeros(n, dtype=np.float32)
    # 1) souffle montant (bruit filtré passe-bande qui monte, 0 → 0,3 s)
    rng = np.random.default_rng(7)
    m = int(0.32 * sr)
    noise = rng.standard_normal(m).astype(np.float32)
    spec = np.fft.rfft(noise)
    f = np.fft.rfftfreq(m, 1 / sr)
    spec *= np.exp(-((np.log(f + 1) - np.log(2400)) ** 2) / 0.6)
    r = np.fft.irfft(spec, m).astype(np.float32)
    r /= np.abs(r).max() + 1e-9
    out[:m] += r * np.linspace(0, 1, m, dtype=np.float32) ** 2.2 * 0.35
    hit = int(0.30 * sr)
    th = t[:n - hit]
    # 2) impact grave feutré (sinus qui descend de 70 à 48 Hz)
    fr = 48 + 22 * np.exp(-th * 9)
    ph = 2 * np.pi * np.cumsum(fr) / sr
    out[hit:] += np.sin(ph) * np.exp(-th * 7) * 0.55 * np.minimum(1, th / 0.004)
    # 3) cloches (partiels inharmoniques d'une cloche tubulaire, attaque douce de 3 ms)

    def bell(f0, start, amp, decay=2.6):
        k0 = hit + int(start * sr)
        tt = t[:n - k0]
        env = np.exp(-tt * decay) * np.minimum(1, tt / 0.003)
        w = (np.sin(2 * np.pi * f0 * tt) + 0.42 * np.sin(2 * np.pi * f0 * 2.76 * tt) * np.exp(-tt * 3)
             + 0.18 * np.sin(2 * np.pi * f0 * 5.40 * tt) * np.exp(-tt * 6))
        out[k0:] += (w * env * amp).astype(np.float32)
    bell(659.3, 0.0, 0.42)      # mi
    bell(987.8, 0.0, 0.22)      # si (quinte)
    bell(1318.5, 0.13, 0.36)    # mi aigu : petite montée, signature « info »
    out[-int(0.08 * sr):] *= np.linspace(1, 0, int(0.08 * sr), dtype=np.float32)
    out /= np.abs(out).max() + 1e-9
    st = np.stack([out * 0.96, out], axis=1)
    return (st * 0.16).astype(np.float32)


BED_LEVEL = 0.04    # nappe sous les cartes : ≈ -40 dB efficaces, ~20 dB sous ta voix (≈ -20 dB) — discrète


def sfx_bed(dur: float, seed: int = 0) -> np.ndarray:
    """Nappe discrète façon journal d'information (BBC / Al Jazeera), entièrement synthétisée (aucun droit d'auteur) :
    accord feutré (la – mi – la) qui respire lentement + léger « tic » de rédaction toutes les 0,6 s.
    Montée douce 0,7 s, extinction 0,9 s. Pas de mélodie, pas de basse qui couvrirait ta voix."""
    sr = SAMPLE_RATE
    n = max(1, int(dur * sr))
    t = np.arange(n, dtype=np.float32) / sr
    rng = np.random.default_rng(1000 + seed)
    ph = rng.uniform(0, 2 * np.pi, 6)
    pad = np.zeros(n, dtype=np.float32)
    for k, (f0, a) in enumerate(((220.0, 1.0), (329.6, 0.55), (440.0, 0.35))):
        det = 1 + 0.0025 * (k + 1)       # deux voix légèrement désaccordées : son chaud, pas électronique
        pad += a * (np.sin(2 * np.pi * f0 * t + ph[k]) + np.sin(2 * np.pi * f0 * det * t + ph[k + 3])) / 2
    pad *= 0.75 + 0.25 * np.sin(2 * np.pi * 0.18 * t + ph[0])      # respiration lente
    pad /= np.abs(pad).max() + 1e-9
    tick = np.zeros(n, dtype=np.float32)
    m = int(0.025 * sr)
    tt = np.arange(m, dtype=np.float32) / sr
    click = (np.sin(2 * np.pi * 2600 * tt) * np.exp(-tt * 260)).astype(np.float32)
    step = int(0.6 * sr)
    for k0 in range(int(0.3 * sr), n - m, step):
        tick[k0:k0 + m] += click * (1.0 if (k0 // step) % 2 == 0 else 0.6)
    x = 0.8 * pad + 0.35 * tick
    env = np.ones(n, dtype=np.float32)
    a_, b_ = min(n // 2, int(0.7 * sr)), min(n // 2, int(0.9 * sr))
    if a_:
        env[:a_] = np.linspace(0, 1, a_, dtype=np.float32) ** 2
    if b_:
        env[-b_:] = np.linspace(1, 0, b_, dtype=np.float32) ** 2
    x = x * env / (np.abs(x).max() + 1e-9)
    return (np.stack([x, x * 0.97], axis=1) * BED_LEVEL).astype(np.float32)


def card_spans(segs) -> list[tuple[float, float]]:
    """(début, fin) dans la vidéo finale de chaque carte affichée à côté de toi (segments consécutifs regroupés)."""
    out, prev = [], None
    for s in segs:
        if s.kind == "split" and s.panel is not None:
            if prev is s.panel and out:
                out[-1] = (out[-1][0], s.out0 + s.dur)
            else:
                out.append((s.out0, s.out0 + s.dur))
            prev = s.panel
        else:
            prev = None
    return [(a, b) for a, b in out if b - a >= 1.0]


def sfx_tick() -> np.ndarray:   # (gardé pour compatibilité)
    return sfx_chapter()


def build_audio(segs, main_wav: Path, out: Path, sfx: bool, chapter_times: list) -> Path:
    total = sum(s.n for s in segs) * SPF
    buf = np.zeros((total, 2), dtype=np.float32)
    main = _Main(main_wav)
    pos, prev_end = 0, None
    cut_fade = int(0.008 * SAMPLE_RATE)
    for s in segs:
        if s.kind == "insert":
            n = s.n * SPF
            clip = _read(s.insert["asset"]["audio"])[:n]
            if len(clip) < n:
                clip = np.concatenate([clip, np.zeros((n - len(clip), 2), np.float32)])
            buf[pos:pos + n] = _fade(clip, int(0.05 * SAMPLE_RATE), int(0.25 * SAMPLE_RATE))
            pos += n
            prev_end = None
            continue
        for at in s.atoms:
            n = frames(at.b - at.a) * SPF
            s0 = int(round(at.a * SAMPLE_RATE))
            piece = main.get(s0, n)
            if len(piece) < n:
                piece = np.concatenate([piece, np.zeros((n - len(piece), 2), np.float32)])
            jump = prev_end is None or abs(at.a - prev_end) > 1e-3
            if jump:  # vraie coupe : micro-fondu pour éviter le clic
                if pos > cut_fade:
                    buf[pos - cut_fade:pos] *= np.linspace(1, 0, cut_fade, dtype=np.float32)[:, None]
                piece = _fade(piece, cut_fade, 0)
            buf[pos:pos + n] = piece
            pos += n
            prev_end = at.b
    if sfx:
        marks = []
        for k, s in enumerate(segs):
            if s.kind in ("split", "insert"):
                marks.append((s.out0 + (0.12 if s.kind == "split" else 0.0), k))
                marks.append((s.out0 + s.dur - 0.45, k + 1000))
        for t, k in marks:
            w = sfx_whoosh(k)
            p = int(max(0.0, t) * SAMPLE_RATE)
            e = min(total, p + len(w))
            buf[p:e] += w[:e - p]
        try:   # nappe très discrète sous chaque carte (article, presse, photo) — un bonus, jamais bloquant
            for k, (a, b) in enumerate(card_spans(segs)):
                bed = sfx_bed(b - a, k)
                p = int(max(0.0, a) * SAMPLE_RATE)
                e = min(total, p + len(bed))
                buf[p:e] += bed[:e - p]
        except Exception as e_:  # noqa: BLE001
            log.warning("nappe sous les cartes sautée : %s", e_)
        tk = sfx_chapter()
        for t in chapter_times:
            p = int(max(0.0, t - 0.25) * SAMPLE_RATE)   # l'impact tombe pile quand le bandeau arrive
            e = min(total, p + len(tk))
            buf[p:e] += tk[:e - p]
    peak = float(np.abs(buf).max()) if len(buf) else 0
    if peak > 0.99:
        buf *= 0.99 / peak
    with wave.open(str(out), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes((np.clip(buf, -1, 1) * 32767).astype(np.int16).tobytes())
    return out


def extract_main_audio(src: Path, info: dict, out: Path) -> Path:
    if info.get("audio"):
        run(["ffmpeg", "-y", "-i", src, "-vn", "-af", "highpass=f=60,loudnorm=I=-16:TP=-1.5:LRA=11", "-ac", "2",
             "-ar", SAMPLE_RATE, "-c:a", "pcm_s16le", out], timeout=3600)
    else:
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"anullsrc=r={SAMPLE_RATE}:cl=stereo", "-t", f"{info['duration']:.3f}",
             "-c:a", "pcm_s16le", out])
    return out


def mux(video: Path, audio: Path, out: Path, comment: str = "") -> Path:
    meta = ["-metadata", f"comment={comment}"] if comment else []
    run(["ffmpeg", "-y", "-i", video, "-i", audio, "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac",
         "-b:a", "192k", "-movflags", "+faststart", "-shortest"] + meta + [out], timeout=1800)
    return out
