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
        self.k = 1.2 if is_rtl(lang) else 1.0     # agrandissement de l'écriture arabe
        f = face or {"cy": 0.38, "fh": 0.3}
        fh = max(0.12, min(0.5, f.get("fh", 0.3)))
        # zone protégée : du haut des cheveux au bas du menton (marges larges)
        self.face_top = (f["cy"] - fh * 0.95) * self.H
        self.face_bot = (f["cy"] + fh * 0.80) * self.H
        cap_lh = (70 if orient == "v" else 64) * 1.2 * self.k
        self.cap_top = self.H - (0.17 * self.H if orient == "v" else 64) - 2 * cap_lh - 44   # haut des sous-titres (2 lignes)

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
        """Styles pensés pour la lisibilité (malvoyants, écrans de téléphone) : grandes polices GRASSES, texte blanc ou
        or lumineux sur fond bleu nuit quasi opaque (contraste > 12:1), contour sombre épais sur tout texte posé sur
        l'image, jamais de texte fin, gris ou transparent."""
        L, v = self.lang, self.o == "v"
        cap = 70 if v else 64
        box = ass_color(C.NAVY_DEEP, 0x14)          # fond des sous-titres : ~92 % opaque
        dark = ass_color((4, 8, 18), 0x00)
        shadow = ass_color((0, 0, 0), 0x60)
        st = [
            # Name, Font, Size, Primary, Secondary, Outline, Back, Bold, Italic, Border, Outl, Shad, Align, ML, MR, MV
            ("Cap", fam("sans", L), cap, ass_color((255, 255, 255)), ass_color(C.GOLD_HI), box, "&H00000000",
             -1, 0, 3, 16, 0, 2, 200, 200, 64),
            ("Sub", fam("sans", L), cap, ass_color(C.SUB_YELLOW), ass_color(C.GOLD_HI), ass_color((0, 0, 0), 0x18),
             "&H00000000", -1, 0, 3, 16, 0, 2, 160, 160, 70),
            ("Hook", fam("serif", L), 88 if not v else 80, ass_color((255, 255, 255)), ass_color(C.GOLD_HI), dark,
             shadow, -1, 0, 1, 4, 3, 5, 120, 120, 0),
            ("ChapNum", fam("sans", L), 42 if not v else 44, ass_color(C.GOLD_HI), ass_color(C.GOLD_HI), dark, "&H00000000",
             -1, 0, 1, 2, 0, 7, 0, 0, 0),
            ("Chap", fam("serif", L), 76 if not v else 72, ass_color((255, 255, 255)), ass_color(C.GOLD_HI), dark, shadow,
             -1, 0, 1, 3, 2, 7, 0, 0, 0),
            ("Box", "Arial", 10, ass_color(C.NAVY_DEEP, 0x20), ass_color(C.NAVY_DEEP), "&H00000000", "&H00000000",
             0, 0, 1, 0, 0, 7, 0, 0, 0),
            ("Credit", fam("sans", L), 48 if not v else 46, ass_color((255, 255, 255)), ass_color(C.GOLD_HI), dark,
             "&H00000000", -1, 0, 1, 2, 0, 7, 0, 0, 0),
            ("CreditSm", fam("sans", L), 38, ass_color(C.GOLD_HI), ass_color(C.GOLD_HI), dark, "&H00000000",
             -1, 0, 1, 2, 0, 7, 0, 0, 0),
            ("Outro", fam("serif", L), 84 if not v else 76, ass_color((255, 255, 255)), ass_color(C.GOLD_HI), dark,
             shadow, -1, 0, 1, 4, 3, 5, 100, 100, 0),
            ("OutroSm", fam("sans", L), 50 if not v else 48, ass_color(C.GOLD_HI), ass_color(C.GOLD_HI), dark,
             "&H00000000", -1, 0, 1, 3, 0, 5, 100, 100, 0),
        ]
        if is_rtl(L):   # l'écriture arabe paraît plus petite à taille égale : agrandie pour la même lisibilité
            st = [(x[0], x[1], x[2] if x[0] == "Box" else int(x[2] * 1.2)) + x[3:] for x in st]
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
        """(MarginL, MarginR, MarginV, nb de caractères max PAR LIGNE) selon la mise en page du moment.
        Calibré pour une police grasse de 64-70 px : aucune ligne ne déborde, 2 lignes au plus."""
        W, H = self.W, self.H
        if seg is not None and seg.kind == "split":
            x, y, w, h = GEOM[self.o][seg.side]["card"]
            return x + 20, W - (x + w) + 20, H - (y + h) + 34, (22 if self.o == "h" else 30)
        if self.o == "v":
            return 60, 60, int(0.17 * H), 26
        return 200, 200, 64, 40

    # ------------------------------------------------------------------ sous-titres de ta voix
    def captions(self, words, segs, emphasis_words: set):
        """Phrase par phrase, 2 lignes au plus, coupées aux endroits naturels, restent à l'écran assez longtemps."""
        chunks, cur = [], []
        for k, w in enumerate(words):
            t = out_time(segs, (w["t0"] + w["t1"]) / 2)
            if t is None:
                continue
            seg = seg_at(segs, t)
            maxc = self.cap_margins(seg)[3] * 2 - 6
            if cur:
                pw, ps = cur[-1]
                txt = " ".join(x["w"] for x, _ in cur)
                if (ps is not seg or w["t0"] - pw["t1"] > 0.65 or len(txt) + 1 + len(w["w"]) > maxc
                        or re.search(r"[.!?…؟;:]$", pw["w"]) or (re.search(r"[,،]$", pw["w"]) and len(txt) > maxc * 0.6)):
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
            times.append([a, b + 0.25, ch])
        for i, (a, b, ch) in enumerate(times):
            seg = ch[0][1]
            if i + 1 < len(times):
                nxt = times[i + 1][0]
                b = min(max(b, min(a + 1.3, nxt)), nxt)       # temps de lecture minimal, sans chevaucher la suite
            b = min(b, seg.out0 + seg.dur)
            ml, mr, mv, per_line = self.cap_margins(seg)
            toks = []
            for w, _ in ch:
                core = norm(w["w"])
                gold = bool(core and (core in emphasis_words or re.search(r"\d", w["w"])))
                tok = re.sub(r"\s+", "\u00a0", (w["w"] or "").strip())
                if tok:
                    toks.append((tok, gold))
            lines = _balance([t for t, _ in toks], per_line)
            out, k = [], 0
            for li, ln in enumerate(lines):
                parts = []
                for _ in ln.split():
                    tok, gold = toks[k]
                    k += 1
                    parts.append(r"{\c" + ass_color(C.GOLD_HI) + "}" + esc(tok) + r"{\c&HFFFFFF&}" if gold else esc(tok))
                out.append(" ".join(parts))
            self.add(a, b, "Cap", r"{\fad(90,70)}" + r"\N".join(out), layer=2, ml=ml, mr=mr, mv=mv)

    # ------------------------------------------------------------------ accroche
    def hook(self, text: str, t0: float = 0.25, t1: float = 4.2):
        if not text:
            return
        W = self.W
        fs = int((88 if self.o == "h" else 80) * self.k)
        lines = _balance(text.split(), int((W - 240) / (0.50 * fs)))
        if len(lines) > 3:
            fs = int(fs * 0.82)
            lines = _balance(text.split(), int((W - 240) / (0.50 * fs)))
        lh = int(fs * 1.18)
        half = (len(lines) * lh + 90) // 2
        y = self.text_band_y(half)
        top, bot = y - half, y + half
        self.add(t0, t1, "Box", r"{\an7\pos(0,0)\fad(250,300)\1a&H26&\p1}" +
                 f"m 0 {top} l {W} {top} l {W} {bot} l 0 {bot}" + r"{\p0}", layer=1)
        ty = top + 30 + (len(lines) * lh) // 2
        self.add(t0 + 0.1, t1, "Hook", r"{\an5\pos(" + f"{W // 2},{ty}" + r")\fs" + str(fs) + r"\fad(300,300)\fscx94\fscy94"
                 r"\t(0,450,0.5,\fscx100\fscy100)}" + r"\N".join(esc(x) for x in lines), layer=3)
        line_w = int(W * (0.36 if self.o == "h" else 0.5))
        x0 = (W - line_w) // 2
        gy = bot - 30
        self.add(t0 + 0.35, t1, "Box", r"{\an7\pos(0,0)\fad(0,300)\1c" + ass_color(C.GOLD_HI) + r"\1a&H00&\clip(" +
                 f"{x0},{gy},{x0},{gy + 8}" + r")\t(0,600,0.6,\clip(" + f"{x0},{gy},{x0 + line_w},{gy + 8}" + r"))\p1}" +
                 f"m {x0} {gy} l {x0 + line_w} {gy} l {x0 + line_w} {gy + 7} l {x0} {gy + 7}" + r"{\p0}", layer=3)

    # ------------------------------------------------------------------ chapitres
    def chapter(self, t0: float, num: int, title: str, dur: float = 5.0):
        """Carte de chapitre façon journal télévisé : bandeau bleu nuit opaque qui glisse depuis le bord, grande barre
        or, « PARTIE 02 » en or lumineux, titre en grand (2 lignes au plus), filet or qui se trace sous le titre."""
        W, H = self.W, self.H
        rtl = is_rtl(self.lang)
        v = self.o == "v"
        fs = int((72 if v else 76) * self.k)
        pad = 44
        maxw = (W - 80) if v else int(W * 0.66)
        per = max(10, int((maxw - 2 * pad - 30) / (0.48 * fs)))
        lines = _balance(title.split(), per)
        while len(lines) > 2 and fs > 52:
            fs -= 6
            per = max(10, int((maxw - 2 * pad - 30) / (0.48 * fs)))
            lines = _balance(title.split(), per)
        lh = int(fs * 1.16)
        nh = int(58 * self.k)                                        # hauteur de la ligne « PARTIE 02 »
        bh = 30 + nh + len(lines) * lh + 34            # hauteur du bandeau
        text_w = max(len(x) for x in lines) * 0.46 * fs if lines else 0
        bw = int(min(maxw, max(W * (0.42 if not v else 0.7), text_w + 2 * pad + 40)))
        y = int(H * (0.10 if not v else 0.06))
        if y + bh > self.face_top - 10:                # le bandeau du haut toucherait le visage : sous le visage
            y = self.text_band_y(bh // 2) - bh // 2
        bx0 = 0 if not rtl else W - bw
        bx1 = bx0 + bw
        slide = -70 if not rtl else 70
        draw = f"m {bx0} {y} l {bx1} {y} l {bx1} {y + bh} l {bx0} {y + bh}"
        # bandeau (glisse de 70 px + fondu)
        self.add(t0, t0 + dur, "Box", r"{\an7\move(" + f"{slide},0,0,0,0,320" + r")\fad(220,400)\1a&H12&\p1}" + draw + r"{\p0}",
                 layer=1)
        # barre or épaisse sur le bord intérieur
        gx = (bx0 + 28) if not rtl else (bx1 - 40)
        self.add(t0 + 0.08, t0 + dur, "Box", r"{\an7\move(" + f"{slide},0,0,0,0,320" + r")\fad(150,400)\1c" +
                 ass_color(C.GOLD_HI) + r"\1a&H00&\p1}" + f"m {gx} {y + 24} l {gx + 12} {y + 24} l {gx + 12} {y + bh - 24} "
                 f"l {gx} {y + bh - 24}" + r"{\p0}", layer=2)
        an = 7 if not rtl else 9
        tx = (gx + 12 + 30) if not rtl else (gx - 30)
        self.add(t0 + 0.18, t0 + dur, "ChapNum", r"{\an" + str(an) + r"\move(" + f"{tx},{y + 40},{tx},{y + 28},0,380" +
                 (r")\fad(200,400)}" if rtl else r")\fsp3\fad(200,400)}") +
                 f"{esc(ui(self.lang, 'chapter')).upper()}  {num:02d}", layer=3)
        ty = y + 28 + nh
        self.add(t0 + 0.3, t0 + dur, "Chap", r"{\an" + str(an) + r"\move(" + f"{tx},{ty + 16},{tx},{ty},0,420" +
                 r")\fs" + str(fs) + r"\fad(250,400)}" + r"\N".join(esc(x) for x in lines), layer=3)
        # filet or qui se trace sous le titre
        lw = int(min(bw - 2 * pad - 60, max(160, text_w * 0.5)))
        ly = y + bh - 22
        lx0 = tx if not rtl else tx - lw
        c0 = f"{lx0},{ly},{lx0},{ly + 6}" if not rtl else f"{lx0 + lw},{ly},{lx0 + lw},{ly + 6}"
        self.add(t0 + 0.6, t0 + dur, "Box", r"{\an7\pos(0,0)\fad(0,400)\1c" + ass_color(C.GOLD_HI) + r"\1a&H00&\clip(" + c0 +
                 r")\t(0,650,0.6,\clip(" + f"{lx0},{ly},{lx0 + lw},{ly + 6}" + r"))\p1}" +
                 f"m {lx0} {ly} l {lx0 + lw} {ly} l {lx0 + lw} {ly + 5} l {lx0} {ly + 5}" + r"{\p0}", layer=3)

    # ------------------------------------------------------------------ extraits insérés
    def insert(self, t0: float, dur: float, ins: dict, subtitles: bool = True):
        """Crédit de l'extrait (qui, quoi, source, date) ; ses sous-titres seulement si les sous-titres sont activés."""
        W, H = self.W, self.H
        rtl = is_rtl(self.lang)
        cr = ins.get("credit") or {}
        top = " — ".join(x for x in (cr.get("speaker"), cr.get("label")) if x)
        bottom = " · ".join(x for x in (cr.get("source"), _date(cr.get("date", ""))) if x)
        if subtitles and ins.get("translated") and ins.get("subs"):
            bottom = (bottom + " · " if bottom else "") + ui(self.lang, "translated")
        fs1, fs2 = int((48 if self.o == "h" else 46) * self.k), int(38 * self.k)
        maxw = W - 120
        per1, per2 = int((maxw - 100) / (0.50 * fs1)), int((maxw - 100) / (0.50 * fs2))
        tl = _balance(top.split(), per1)          # 2 lignes au plus, sans couper un nom au milieu
        if len(tl) > 2:
            tl = [tl[0], _fit(" ".join(tl[1:]), per1)]
        bl = [_fit(bottom, per2)] if bottom else []
        if tl or bl:
            y = int(H * (0.06 if self.o == "h" else 0.05))
            x = 80 if not rtl else W - 80
            an = 7 if not rtl else 9
            e = min(t0 + 7.0, t0 + dur - 0.3)
            bw = int(min(maxw, 100 + max([len(z) * 0.47 * fs1 for z in tl] + [len(z) * 0.47 * fs2 for z in bl])))
            bx0, bx1 = (x - 34, x - 34 + bw) if not rtl else (x + 34 - bw, x + 34)
            lh1 = int(fs1 * 1.2)
            hh = len(tl) * lh1 + (fs2 + 12 if bl else 0) + 14
            self.add(t0 + 0.5, e, "Box", r"{\an7\pos(0,0)\fad(250,300)\1a&H14&\p1}" +
                     f"m {bx0} {y - 16} l {bx1} {y - 16} l {bx1} {y + hh} l {bx0} {y + hh}" + r"{\p0}", layer=4)
            gx = bx0 if not rtl else bx1 - 10
            self.add(t0 + 0.5, e, "Box", r"{\an7\pos(0,0)\fad(250,300)\1c" + ass_color(C.GOLD_HI) + r"\1a&H00&\p1}" +
                     f"m {gx} {y - 16} l {gx + 10} {y - 16} l {gx + 10} {y + hh} l {gx} {y + hh}" + r"{\p0}", layer=5)
            yy = y
            if tl:
                self.add(t0 + 0.6, e, "Credit", r"{\an" + str(an) + r"\pos(" + f"{x},{yy}" + r")\fad(250,300)}" +
                         r"\N".join(esc(z) for z in tl), layer=5)
                yy += len(tl) * lh1 + 4
            if bl:
                self.add(t0 + 0.6, e, "CreditSm", r"{\an" + str(an) + r"\pos(" + f"{x},{yy}" + r")\fad(250,300)}" + esc(bl[0]),
                         layer=5)
        if not subtitles:
            return
        mv = 70 if self.o == "h" else 520
        per = 40 if self.o == "h" else 26
        for s in ins.get("subs") or []:
            for a, b, txt in _split_sub(s, per * 2 - 6):
                self.add(t0 + a, min(t0 + b + 0.15, t0 + dur - 0.05), "Sub",
                         r"{\fad(90,70)}" + r"\N".join(esc(x) for x in _balance(txt.split(), per)), layer=4,
                         ml=140, mr=140, mv=mv)

    # ------------------------------------------------------------------ fin
    def outro(self, total: float, line1: str, line2: str, dur: float = 5.5):
        if total < 20:
            return
        W = self.W
        t0 = total - dur
        fs = int((84 if self.o == "h" else 76) * self.k)
        l1 = _balance((line1 or "").split(), int((W - 200) / (0.50 * fs)))[:3]
        lh = int(fs * 1.16)
        half = (len(l1) * lh + 70 + 60) // 2
        y = self.text_band_y(half)
        top, bot = y - half, y + half
        self.add(t0, total, "Box", r"{\an7\pos(0,0)\fad(500,0)\1a&H20&\p1}" +
                 f"m 0 {top} l {W} {top} l {W} {bot} l 0 {bot}" + r"{\p0}", layer=6)
        ty = top + 30 + (len(l1) * lh) // 2
        self.add(t0 + 0.2, total, "Outro", r"{\an5\pos(" + f"{W // 2},{ty}" + r")\fad(500,0)\fscx95\fscy95"
                 r"\t(0,600,0.5,\fscx100\fscy100)}" + r"\N".join(esc(x) for x in l1), layer=7)
        self.add(t0 + 0.6, total, "OutroSm", r"{\an5\pos(" + f"{W // 2},{bot - 50}" + r")\fad(500,0)}" + esc(line2), layer=7)


_WEAK = {"je", "tu", "il", "on", "le", "la", "les", "l'", "de", "des", "du", "d'", "un", "une", "à", "au", "aux", "et",
         "ou", "en", "ce", "se", "ne", "que", "qui", "a", "the", "of", "to", "and", "il", "lo", "di", "e", "che", "per",
         "في", "من", "على", "و", "أن", "إلى"}


def _balance(words: list, per_line: int) -> list[str]:
    """Répartit des mots en le moins de lignes possible (≤ per_line caractères chacune), de longueurs aussi égales que
    possible, en coupant de préférence après une ponctuation et jamais juste après un petit mot (« de », « je »…)."""
    words = [w for w in words if w]
    if not words:
        return []
    n_w = len(words)
    L = [len(w) for w in words]

    def ln(i, j):
        return sum(L[i:j]) + (j - i - 1)
    total = ln(0, n_w)
    n_min = max(1, -(-total // max(1, per_line)))
    for n in range(n_min, n_w + 1):
        target = total / n
        INF = float("inf")
        best = {(0, 0): (0.0, None)}           # (mots placés, lignes) → (coût, coupure précédente)
        for k in range(n):
            for (i, kk), (c, _) in list(best.items()):
                if kk != k:
                    continue
                for j in range(i + 1, n_w + 1):
                    w = ln(i, j)
                    if w > per_line and j > i + 1:
                        break
                    if k == n - 1 and j != n_w:
                        continue
                    cost = c + (w - target) ** 2
                    if j < n_w:
                        last = words[j - 1].lower().strip("«»\"'")
                        if re.search(r"[,.;:!?…،؟]$", words[j - 1]):
                            cost -= 12
                        elif last in _WEAK:
                            cost += 60
                    key = (j, k + 1)
                    if cost < best.get(key, (INF, None))[0]:
                        best[key] = (cost, i)
        if (n_w, n) in best:
            cuts, j, k = [], n_w, n
            while k > 0:
                i = best[(j, k)][1]
                cuts.append(" ".join(words[i:j]))
                j, k = i, k - 1
            return cuts[::-1]
    return [" ".join(words)]


def _fit(s: str, maxc: int) -> str:
    s = (s or "").strip()
    if len(s) <= maxc:
        return s
    cut = s[:maxc - 1].rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:—·-") + "…"


def _date(d: str) -> str:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", d or "")
    return f"{m.group(3)}/{m.group(2)}/{m.group(1)}" if m else (d or "")


def _split_sub(s: dict, maxc: int):
    """Découpe une phrase longue en morceaux lisibles (coupés après une ponctuation, jamais après un petit mot),
    au prorata du temps."""
    words = s["text"].split()
    if not words:
        return []
    parts = [p.split() for p in _balance(words, maxc)]
    tot = sum(len(" ".join(p)) for p in parts) or 1
    out, t = [], s["t0"]
    for p in parts:
        d = (s["t1"] - s["t0"]) * len(" ".join(p)) / tot
        out.append((t, t + d, " ".join(p)))
        t += d
    return out
