"""Tous les textes à l'écran (un seul fichier ASS, rendu par libass : l'arabe est correctement lié et écrit de droite
à gauche) : sous-titres phrase par phrase avec mots clés en or, accroche d'ouverture, titres de chapitres, crédit et
sous-titres (traduits) des extraits insérés, carte de fin. Animations douces : fondus, glissés, filet qui se trace."""
from __future__ import annotations

import re

from . import config as C
from .config import GEOM, SIZE, ass_color, fam, is_rtl, ui
from .timeline import out_time, seg_at
from .util import norm


def _t(s: float) -> str:
    s = max(0.0, s)
    cs = int(round(s * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    sec, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{sec:02d}.{cs:02d}"


def esc(s: str) -> str:
    return (s or "").replace("\\", "⧵").replace("{", "(").replace("}", ")").replace("\n", " ")


class ASS:
    def __init__(self, orient: str, lang: str, face: dict | None = None):
        self.o, self.lang = orient, lang
        self.W, self.H = SIZE[orient]
        self.ev: list[str] = []
        f = face or {"cy": 0.38, "fh": 0.3}
        fh = max(0.12, min(0.5, f.get("fh", 0.3)))
        # zone protégée : du haut des cheveux au bas du menton (marges larges)
        self.face_top = (f["cy"] - fh * 0.95) * self.H
        self.face_bot = (f["cy"] + fh * 0.80) * self.H
        self.cap_top = self.H - (0.17 * self.H if orient == "v" else 64) - 90   # haut des sous-titres

    def text_band_y(self, half: int) -> int:
        """Centre d'un bandeau de texte (hauteur 2*half) qui ne touche ni le visage ni les sous-titres :
        sous le visage si la place existe, sinon au-dessus, sinon le plus bas possible."""
        below = self.face_bot + half + 20
        if below + half <= self.cap_top:
            return int(below)
        above = self.face_top - half - 20
        if above - half >= 0.04 * self.H:
            return int(above)
        return int(self.cap_top - half)

    def add(self, t0, t1, style, text, layer=1, ml=0, mr=0, mv=0):
        if t1 - t0 >= 0.05:
            self.ev.append(f"Dialogue: {layer},{_t(t0)},{_t(t1)},{style},,{ml},{mr},{mv},,{text}")

    def header(self) -> str:
        L, v = self.lang, self.o == "v"
        cap = 58 if v else 52
        st = [
            # Name, Font, Size, Primary, Secondary, Outline, Back, Bold, Italic, U, S, ScX, ScY, Sp, Ang, Border, Outl, Shad, Align, ML, MR, MV
            ("Cap", fam("sans", L), cap, ass_color(C.PAPER), ass_color(C.GOLD), ass_color(C.NAVY_DEEP, 0x48), "&H00000000",
             -1, 0, 3, 13, 0, 2, 200, 200, 64),
            ("Sub", fam("sans", L), cap - 4, ass_color((255, 248, 225)), ass_color(C.GOLD), ass_color((0, 0, 0), 0x50),
             "&H00000000", -1, 0, 3, 12, 0, 2, 160, 160, 70),
            ("Hook", fam("serif", L), 84 if not v else 78, ass_color(C.PAPER), ass_color(C.GOLD), ass_color(C.NAVY_DEEP, 0x30),
             ass_color((0, 0, 0), 0x80), -1, 0, 1, 0, 3, 5, 120, 120, 0),
            ("Kicker", fam("sans", L), 34, ass_color(C.GOLD), ass_color(C.GOLD), ass_color((0, 0, 0), 0x60), "&H00000000",
             -1, 0, 1, 0, 2, 5, 120, 120, 0),
            ("ChapNum", fam("serif", L), 46, ass_color(C.GOLD), ass_color(C.GOLD), "&H00000000", "&H00000000",
             -1, 0, 1, 0, 0, 4, 0, 0, 0),
            ("Chap", fam("serif", L), 58 if not v else 56, ass_color(C.PAPER), ass_color(C.GOLD), "&H00000000", "&H00000000",
             -1, 0, 1, 0, 0, 4, 0, 0, 0),
            ("Box", "Arial", 10, ass_color(C.NAVY_DEEP, 0x20), ass_color(C.NAVY_DEEP), "&H00000000", "&H00000000",
             0, 0, 1, 0, 0, 7, 0, 0, 0),
            ("Credit", fam("sans", L), 36, ass_color(C.PAPER), ass_color(C.GOLD), "&H00000000", "&H00000000",
             -1, 0, 1, 0, 0, 7, 0, 0, 0),
            ("CreditSm", fam("sans", L), 28, ass_color(C.GOLD), ass_color(C.GOLD), "&H00000000", "&H00000000",
             -1, 0, 1, 0, 0, 7, 0, 0, 0),
            ("Outro", fam("serif", L), 70 if not v else 66, ass_color(C.PAPER), ass_color(C.GOLD), ass_color(C.NAVY_DEEP, 0x30),
             "&H00000000", -1, 0, 1, 0, 2, 5, 100, 100, 0),
            ("OutroSm", fam("sans", L), 40, ass_color(C.GOLD), ass_color(C.GOLD), ass_color(C.NAVY_DEEP, 0x30), "&H00000000",
             -1, 0, 1, 0, 2, 5, 100, 100, 0),
        ]
        lines = [f"Style: {n},{f},{s},{p},{sc},{oc},{bc},{b},{i},0,0,100,100,0,0,{bs},{ol},{sh},{al},{ml},{mr},{mv},1"
                 for (n, f, s, p, sc, oc, bc, b, i, bs, ol, sh, al, ml, mr, mv) in st]
        return ("[Script Info]\nScriptType: v4.00+\nWrapStyle: 0\nScaledBorderAndShadow: yes\n"
                f"PlayResX: {self.W}\nPlayResY: {self.H}\nYCbCr Matrix: TV.709\n\n[V4+ Styles]\n"
                "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
                "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
                "MarginR, MarginV, Encoding\n" + "\n".join(lines) + "\n\n[Events]\n"
                "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")

    def text(self) -> str:
        return self.header() + "\n".join(self.ev) + "\n"

    # ------------------------------------------------------------------ placements
    def cap_margins(self, seg) -> tuple[int, int, int, int]:
        """(MarginL, MarginR, MarginV, nb de caractères max par ligne) selon la mise en page du moment."""
        W, H = self.W, self.H
        if seg is not None and seg.kind == "split":
            x, y, w, h = GEOM[self.o][seg.side]["card"]
            return x + 26, W - (x + w) + 26, H - (y + h) + 30, (26 if self.o == "h" else 30)
        if self.o == "v":
            return 70, 70, int(0.17 * H), 28
        return 220, 220, 64, 44

    # ------------------------------------------------------------------ sous-titres de ta voix
    def captions(self, words, segs, emphasis_words: set):
        chunks, cur = [], []
        for k, w in enumerate(words):
            t = out_time(segs, (w["t0"] + w["t1"]) / 2)
            if t is None:
                continue
            seg = seg_at(segs, t)
            maxc = self.cap_margins(seg)[3]
            if cur:
                pw, ps = cur[-1]
                txt = " ".join(x["w"] for x, _ in cur)
                if (ps is not seg or w["t0"] - pw["t1"] > 0.65 or len(txt) + 1 + len(w["w"]) > maxc
                        or re.search(r"[.!?…؟;:]$", pw["w"]) or (re.search(r"[,،]$", pw["w"]) and len(txt) > maxc * 0.55)):
                    chunks.append(cur)
                    cur = []
            cur.append((w, seg))
        if cur:
            chunks.append(cur)
        times = []
        for ch in chunks:
            a = out_time(segs, ch[0][0]["t0"])
            b = out_time(segs, ch[-1][0]["t1"])
            if a is None or b is None:
                continue
            times.append([a, b + 0.22, ch])
        for i, (a, b, ch) in enumerate(times):
            if i + 1 < len(times):
                b = min(b, times[i + 1][0])
            seg = ch[0][1]
            b = min(b, seg.out0 + seg.dur)
            ml, mr, mv, _ = self.cap_margins(seg)
            parts = []
            for w, _ in ch:
                tok = esc(w["w"])
                core = norm(w["w"])
                if core and (core in emphasis_words or re.search(r"\d", w["w"])):
                    parts.append(r"{\c" + ass_color(C.GOLD) + "}" + tok + r"{\c" + ass_color(C.PAPER) + "}")
                else:
                    parts.append(tok)
            self.add(a, b, "Cap", r"{\fad(80,60)}" + " ".join(parts), layer=2, ml=ml, mr=mr, mv=mv)

    # ------------------------------------------------------------------ accroche
    def hook(self, text: str, t0: float = 0.25, t1: float = 3.6):
        if not text:
            return
        W = self.W
        y = self.text_band_y(130) + 30
        line_w = int(W * (0.36 if self.o == "h" else 0.5))
        self.add(t0, t1, "Box", r"{\an7\pos(0,0)\fad(250,300)\1a&H70&\p1}" +
                 f"m 0 {y - 150} l {W} {y - 150} l {W} {y + 110} l 0 {y + 110}" + r"{\p0}", layer=1)
        self.add(t0 + 0.1, t1, "Hook", r"{\an5\pos(" + f"{W // 2},{y - 30}" + r")\fad(300,300)\blur0.6\fscx94\fscy94"
                 r"\t(0,450,0.5,\fscx100\fscy100)}" + esc(text), layer=3)
        x0 = (W - line_w) // 2
        self.add(t0 + 0.35, t1, "Box", r"{\an7\pos(0,0)\fad(0,300)\1c" + ass_color(C.GOLD) + r"\1a&H00&\clip(" +
                 f"{x0},{y + 40},{x0},{y + 50}" + r")\t(0,600,0.6,\clip(" + f"{x0},{y + 40},{x0 + line_w},{y + 50}" + r"))\p1}" +
                 f"m {x0} {y + 42} l {x0 + line_w} {y + 42} l {x0 + line_w} {y + 47} l {x0} {y + 47}" + r"{\p0}", layer=3)

    # ------------------------------------------------------------------ chapitres
    def chapter(self, t0: float, num: int, title: str, dur: float = 3.8):
        W, H = self.W, self.H
        rtl = is_rtl(self.lang)
        y = int(H * (0.12 if self.o == "h" else 0.07))
        if y + 140 > self.face_top:  # le bandeau du haut toucherait le visage : on le met sous le visage
            y = self.text_band_y(75) - 60
        x = 96 if not rtl else W - 96
        bw = int(W * (0.46 if self.o == "h" else 0.86))
        bx0 = 0 if not rtl else W - bw - 60
        bx1 = bw + 60 if not rtl else W
        self.add(t0, t0 + dur, "Box", r"{\an7\pos(0,0)\fad(300,350)\1a&H38&\p1}" +
                 f"m {bx0} {y - 16} l {bx1} {y - 16} l {bx1} {y + 128} l {bx0} {y + 128}" + r"{\p0}", layer=1)
        gx = x if not rtl else x - 6
        self.add(t0 + 0.1, t0 + dur, "Box", r"{\an7\pos(0,0)\fad(0,350)\1c" + ass_color(C.GOLD) + r"\1a&H00&\p1}" +
                 f"m {gx} {y} l {gx + 6} {y} l {gx + 6} {y + 112} l {gx} {y + 112}" + r"{\p0}", layer=2)
        an = 7 if not rtl else 9
        tx = x + 28 if not rtl else x - 28
        mv = f"{tx},{y + 18},{tx},{y},0,450"
        self.add(t0 + 0.1, t0 + dur, "ChapNum", r"{\an" + str(an) + r"\move(" + mv + r")\fad(250,350)}" +
                 f"{num:02d} · {esc(ui(self.lang, 'chapter'))}", layer=3)
        mv2 = f"{tx},{y + 72},{tx},{y + 52},80,530"
        self.add(t0 + 0.15, t0 + dur, "Chap", r"{\an" + str(an) + r"\move(" + mv2 + r")\fad(250,350)}" + esc(title), layer=3)

    # ------------------------------------------------------------------ extraits insérés
    def insert(self, t0: float, dur: float, ins: dict):
        W, H = self.W, self.H
        rtl = is_rtl(self.lang)
        cr = ins.get("credit") or {}
        top = " — ".join(x for x in (cr.get("speaker"), cr.get("label")) if x)
        bottom = " · ".join(x for x in (cr.get("source"), _date(cr.get("date", ""))) if x)
        if ins.get("translated"):
            bottom = (bottom + " · " if bottom else "") + ui(self.lang, "translated")
        if top or bottom:
            y = int(H * (0.07 if self.o == "h" else 0.06))
            x = 80 if not rtl else W - 80
            an = 7 if not rtl else 9
            e = min(t0 + 6.0, t0 + dur - 0.3)
            longest = max(len(top), len(bottom))
            bw = min(W - 120, 140 + int(longest * 19))
            bx0, bx1 = (x - 30, x - 30 + bw) if not rtl else (x + 30 - bw, x + 30)
            hh = 112 if (top and bottom) else 66
            self.add(t0 + 0.5, e, "Box", r"{\an7\pos(0,0)\fad(250,300)\1a&H30&\p1}" +
                     f"m {bx0} {y - 14} l {bx1} {y - 14} l {bx1} {y + hh} l {bx0} {y + hh}" + r"{\p0}", layer=4)
            gx = bx0 if not rtl else bx1 - 6
            self.add(t0 + 0.5, e, "Box", r"{\an7\pos(0,0)\fad(250,300)\1c" + ass_color(C.GOLD) + r"\1a&H00&\p1}" +
                     f"m {gx} {y - 14} l {gx + 6} {y - 14} l {gx + 6} {y + hh} l {gx} {y + hh}" + r"{\p0}", layer=5)
            yy = y
            if top:
                self.add(t0 + 0.6, e, "Credit", r"{\an" + str(an) + r"\pos(" + f"{x},{yy}" + r")\fad(250,300)}" + esc(top), layer=5)
                yy += 50
            if bottom:
                self.add(t0 + 0.6, e, "CreditSm", r"{\an" + str(an) + r"\pos(" + f"{x},{yy}" + r")\fad(250,300)}" + esc(bottom),
                         layer=5)
        mv = 70 if self.o == "h" else 520
        for s in ins.get("subs") or []:
            for a, b, txt in _split_sub(s, 44 if self.o == "h" else 28):
                self.add(t0 + a, min(t0 + b + 0.1, t0 + dur - 0.05), "Sub", r"{\fad(80,60)}" + esc(txt), layer=4,
                         ml=160, mr=160, mv=mv)

    # ------------------------------------------------------------------ fin
    def outro(self, total: float, line1: str, line2: str, dur: float = 5.0):
        if total < 20:
            return
        W = self.W
        t0 = total - dur
        y = self.text_band_y(125)
        self.add(t0, total, "Box", r"{\an7\pos(0,0)\fad(500,0)\1a&H60&\p1}" +
                 f"m 0 {y - 120} l {W} {y - 120} l {W} {y + 120} l 0 {y + 120}" + r"{\p0}", layer=6)
        self.add(t0 + 0.2, total, "Outro", r"{\an5\pos(" + f"{W // 2},{y - 30}" + r")\fad(500,0)\fscx95\fscy95"
                 r"\t(0,600,0.5,\fscx100\fscy100)}" + esc(line1), layer=7)
        self.add(t0 + 0.6, total, "OutroSm", r"{\an5\pos(" + f"{W // 2},{y + 55}" + r")\fad(500,0)}" + esc(line2), layer=7)


def _date(d: str) -> str:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", d or "")
    return f"{m.group(3)}/{m.group(2)}/{m.group(1)}" if m else (d or "")


def _split_sub(s: dict, maxc: int):
    """Découpe une phrase longue en morceaux lisibles, au prorata du temps."""
    words = s["text"].split()
    if not words:
        return []
    parts, cur = [], []
    for w in words:
        if cur and len(" ".join(cur + [w])) > maxc:
            parts.append(cur)
            cur = []
        cur.append(w)
    if cur:
        parts.append(cur)
    tot = sum(len(" ".join(p)) for p in parts) or 1
    out, t = [], s["t0"]
    for p in parts:
        d = (s["t1"] - s["t0"]) * len(" ".join(p)) / tot
        out.append((t, t + d, " ".join(p)))
        t += d
    return out
