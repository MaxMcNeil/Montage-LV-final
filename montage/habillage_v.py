"""HABILLAGE VERTICAL (vidéo montée en 1080x1920 seulement — l'horizontal ne change jamais).

Trois habillages, choisis au hasard par défaut (jamais deux fois de suite le même) :
  newsroom — chaîne d'info premium : bandeau chaîne + « EN DIRECT », toi dans un grand cadre, titre du sujet,
             « AU SOMMAIRE » (sujet en cours surligné), « À SUIVRE », bandeau défilant des sujets ;
  warroom  — centre de commandement : fond noir quadrillé, cadres de visée, « CAM 01 · ANALYSTE », « FLUX · EXTRAIT »,
             dossier en cours / dossiers à venir, radar des lieux que tu cites ;
  story    — pensé pour le téléphone : toi en plein écran, barres de progression (une par sujet, la barre du sujet en
             cours se remplit), grand titre doré, « ENSUITE ».
Les sujets = les chapitres du montage. Rien n'est inventé : titres, lieux cités, sujet suivant viennent de ta vidéo.

Lisibilité : rien d'important sous l'interface YouTube (haut : LIVE / spectateurs / menu ; droite : boutons ; bas :
titre / chaîne / s'abonner) ; textes de 34 px au moins ; aucune heure affichée.

Jamais bloquant : si l'habillage échoue sur un passage, ce passage est refait sans habillage (et PLAN.md le dit)."""
from __future__ import annotations

import json
import logging
import math
import random
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import config as C

log = logging.getLogger("montage.habillage_v")

W, H = 1080, 1920
FONTS = Path(__file__).resolve().parent / "habillage_v_fonts"
THEMES = ("newsroom", "warroom", "story")
NOMS = {"newsroom": "Newsroom", "warroom": "War room", "story": "Story"}
R_HOLE = C.CARD_RADIUS            # même arrondi que tes cadres (aucun coin de fond qui dépasse)

# zones réservées par YouTube (vidéo verticale et live sur téléphone) : jamais de texte ou d'élément important dedans
YT_TOP, YT_BOTTOM, YT_RIGHT_X, YT_RIGHT_Y = 180, 1650, 940, (950, 1650)

# Mises en page (x, y, largeur, hauteur) : cam = toi, media = photos / articles / extraits
LAYOUT = {
    "newsroom": {"cam": (36, 336, 1008, 520), "media": (36, 1124, 904, 420), "full": False},
    "warroom": {"cam": (36, 326, 650, 640), "media": (36, 1000, 880, 420), "full": False},
    "story": {"cam": (0, 0, W, H), "media": (46, 1150, 848, 478), "full": True},
}
# sous-titres de ta voix (s'ils sont activés) : DANS ton cadre, en bas (MarginL, MarginR, MarginV, car./ligne)
CAPS = {"newsroom": (70, 70, H - 840, 24), "warroom": (60, W - 686 + 24, H - 950, 17), "story": (60, 160, H - 1080, 24)}

T = {
    "fr": {"live": "EN DIRECT", "som": "AU SOMMAIRE", "next": "À SUIVRE", "sujet": "SUJET {k} / {n}", "prog": "AU PROGRAMME",
           "cc": "COMMAND CENTER", "cam": "CAM 01 · ANALYSTE", "flux": "FLUX · EXTRAIT", "dos": "DOSSIER {k} / {n}",
           "suiv": "SUIVANT", "zones": "ZONES CITÉES", "doss": "DOSSIERS", "ens": "ENSUITE", "sur": "SUR {n}",
           "fin": "DERNIER SUJET", "pause": "EN PAUSE"},
    "en": {"live": "LIVE", "som": "IN THIS EPISODE", "next": "UP NEXT", "sujet": "TOPIC {k} / {n}", "prog": "ON THE MENU",
           "cc": "COMMAND CENTER", "cam": "CAM 01 · ANALYST", "flux": "FEED · CLIP", "dos": "FILE {k} / {n}",
           "suiv": "NEXT", "zones": "PLACES CITED", "doss": "FILES", "ens": "UP NEXT", "sur": "OF {n}",
           "fin": "LAST TOPIC", "pause": "PAUSED"},
    "it": {"live": "IN DIRETTA", "som": "IN QUESTA PUNTATA", "next": "A SEGUIRE", "sujet": "TEMA {k} / {n}",
           "prog": "IN PROGRAMMA", "cc": "COMMAND CENTER", "cam": "CAM 01 · ANALISTA", "flux": "FLUSSO · ESTRATTO",
           "dos": "DOSSIER {k} / {n}", "suiv": "PROSSIMO", "zones": "LUOGHI CITATI", "doss": "DOSSIER", "ens": "DOPO",
           "sur": "SU {n}", "fin": "ULTIMO TEMA", "pause": "IN PAUSA"},
    "ar": {"live": "مباشر", "som": "في هذه الحلقة", "next": "التالي", "sujet": "الموضوع {k} من {n}", "prog": "على البرنامج",
           "cc": "غرفة العمليات", "cam": "الكاميرا 01 · المحلل", "flux": "البث · مقطع", "dos": "الملف {k} من {n}",
           "suiv": "التالي", "zones": "المناطق المذكورة", "doss": "الملفات", "ens": "بعد قليل", "sur": "من {n}",
           "fin": "الموضوع الأخير", "pause": "متوقف"},
}

NAVY, NAVY2, RED, CREAM = (13, 27, 58), (20, 40, 79), (200, 16, 46), (244, 239, 230)
CYAN, AMBER, DARK = (64, 224, 208), (255, 176, 32), (5, 8, 13)
GOLD = (212, 175, 55)


def tr(lang: str, key: str, **kw) -> str:
    return T.get((lang or "fr")[:2], T["fr"]).get(key, T["fr"][key]).format(**kw)


# ------------------------------------------------------------------ choix
def choisir(opt: str, state: Path, seed: str = "") -> str | None:
    """« au hasard » (défaut) : un des 3, jamais le même que la fois d'avant ; « actuel » = aucun habillage."""
    o = re.sub(r"[^a-z]", "", (opt or "auhasard").lower())
    if o in ("actuel", "non", "aucun", "classique", "none", "off"):
        return None
    for t in THEMES:
        if o.startswith(t[:4]):
            return t
    last = None
    try:
        last = json.loads(state.read_text(encoding="utf-8")).get("dernier")
    except (OSError, ValueError):
        pass
    choix = [t for t in THEMES if t != last] or list(THEMES)
    return random.Random(seed or None).choice(choix)


def memoriser(theme: str, state: Path) -> None:
    try:
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps({"dernier": theme}), encoding="utf-8")
    except OSError:
        pass


def mise_en_page(theme: str) -> None:
    """Tes cadres et ceux des médias aux places de l'habillage (avant toute fabrication de carte)."""
    lay = LAYOUT[theme]
    for side in ("left", "right"):
        C.GEOM["v"][side] = {"card": tuple(lay["cam"]), "panel": tuple(lay["media"])}


# ------------------------------------------------------------------ dessin (Pillow)
def _rtl(s: str) -> bool:
    from .panels import has_rtl
    return has_rtl(s)


def font(kind: str, size: int, s: str = "") -> ImageFont.FreeTypeFont:
    """kind : display (titres condensés), serif (grands titres), mono (écrans), sans (texte). Arabe : polices Noto."""
    from .panels import _font
    if _rtl(s):
        return _font("serif" if kind == "serif" else "sans", size, True, s)
    f = {"display": "Oswald-Bold.ttf", "serif": "PlayfairDisplay-Black.ttf", "mono": "JetBrainsMono-Bold.ttf"}.get(kind)
    if f and (FONTS / f).exists():
        try:
            return ImageFont.truetype(str(FONTS / f), size)
        except OSError:
            pass
    return _font("sans", size, True, s)


def text(d: ImageDraw.ImageDraw, xy, s: str, f, fill, anchor="la", w: int | None = None):
    """w = largeur de la boîte : un texte arabe y est aligné à DROITE (sens de lecture) ; sinon à gauche."""
    from .panels import _kw, _shape
    x, y = xy
    if w is not None and _rtl(s) and anchor[0] == "l":
        x, anchor = x + w, "r" + anchor[1:]
    d.text((x, y), _shape(s), font=f, fill=fill, anchor=anchor, **_kw(s))


def width(d, s, f) -> float:
    from .panels import tw
    return tw(d, s, f)


def fit_lines(d, s: str, kind: str, maxw: int, start: int, minimum: int, max_lines: int):
    """(police, lignes) : la plus grande taille qui tient en max_lines lignes de largeur maxw."""
    from .panels import wrap
    s = " ".join(str(s or "").split())
    for size in range(start, minimum - 1, -2):
        f = font(kind, size, s)
        lines = wrap(d, s, f, maxw)
        if len(lines) <= max_lines and all(width(d, x, f) <= maxw for x in lines):
            return f, lines
    f = font(kind, minimum, s)
    lines = wrap(d, s, f, maxw)[:max_lines]
    if lines and len(wrap(d, s, f, maxw)) > max_lines:
        while lines[-1] and width(d, lines[-1] + "…", f) > maxw:
            lines[-1] = lines[-1][:-1]
        lines[-1] = lines[-1].rstrip(" ,.;:") + "…"
    return f, lines


class _D:
    """ImageDraw qui MÉLANGE les couleurs semi-transparentes (Pillow, sur une image RGBA, remplace les pixels au lieu
    de les mélanger : un fond « transparent à 18 % » laisserait voir la vidéo à travers l'habillage)."""

    def __init__(self, im: Image.Image):
        self.im = im
        self.d = ImageDraw.Draw(im)

    def textlength(self, *a, **k):
        return self.d.textlength(*a, **k)

    def __getattr__(self, name):
        fn = getattr(self.d, name)

        def call(*a, **k):
            cols = [k.get(x) for x in ("fill", "outline", "stroke_fill")]
            if len(a) > 1 and name != "text":
                cols.append(a[1])
            semi = any(isinstance(c, tuple) and len(c) == 4 and c[3] < 255 for c in cols)
            if not semi:
                return fn(*a, **k)
            layer = Image.new("RGBA", self.im.size, (0, 0, 0, 0))
            getattr(ImageDraw.Draw(layer), name)(*a, **k)
            self.im.alpha_composite(layer)
        return call


def _hole(im: Image.Image, box, r=R_HOLE):
    """Fenêtre VRAIMENT transparente (on y voit ton image / le média)."""
    x, y, w, h = box
    a = im.getchannel("A")
    ImageDraw.Draw(a).rounded_rectangle((x, y, x + w - 1, y + h - 1), r, fill=0)
    im.putalpha(a)


def _shadow(im: Image.Image, box, r=R_HOLE, strength=150):
    x, y, w, h = box
    s = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(s).rounded_rectangle((x, y + 14, x + w, y + h + 14), r, fill=(0, 0, 0, strength))
    im.alpha_composite(s.filter(ImageFilter.GaussianBlur(22)))


def _vgrad(w, h, top, bot, a0=255, a1=255) -> Image.Image:
    g = Image.new("RGBA", (w, h))
    px = g.load()
    for yy in range(h):
        k = yy / max(1, h - 1)
        c = tuple(int(top[i] + (bot[i] - top[i]) * k) for i in range(3)) + (int(a0 + (a1 - a0) * k),)
        for xx in range(w):
            px[xx, yy] = c
    return g


def _logo(path: str | None, size: int) -> Image.Image | None:
    try:
        lg = Image.open(path).convert("RGBA")
        lg.thumbnail((size, size), Image.LANCZOS)
        m = Image.new("L", lg.size, 0)
        ImageDraw.Draw(m).ellipse((0, 0, lg.width - 1, lg.height - 1), fill=255)
        out = Image.new("RGBA", lg.size, (0, 0, 0, 0))
        out.paste(lg, (0, 0), Image.composite(lg.getchannel("A"), Image.new("L", lg.size, 0), m))
        return out
    except Exception:  # noqa: BLE001 - pas de logo : le nom de la chaîne seul
        return None


# ------------------------------------------------------------------ habillage par sujet
class Habillage:
    """Images (PNG) de l'habillage par sujet et par état (« solo » = toi seul, « media » = un média est à l'écran),
    + éléments animés (bandeau défilant, radar, barre de progression). Utilisé par render.Graph (montage/render.py)."""

    def __init__(self, theme: str, topics: list, total: float, lang: str, nom: str, logo: str | None, places: list,
                 work: Path):
        self.theme, self.lang, self.nom = theme, (lang or "fr")[:2], nom or ""
        self.total = float(total)
        self.work = Path(work) / "habillage_v"
        self.work.mkdir(parents=True, exist_ok=True)
        self.logo = logo
        self.places = [p for p in places if p][:3]
        self.topics = topics          # [(début dans la vidéo montée, titre)] — au moins 1
        self.n = len(topics)
        self.lay = LAYOUT[theme]
        self.layers: list = []        # [(png, x, y, t0, t1, état)]
        self.anim: list = []          # [dict(kind, png, x, y, ...)]
        self.fails: list = []

    # bornes de chaque sujet
    def spans(self):
        out = []
        for k, (t, title) in enumerate(self.topics):
            t1 = self.topics[k + 1][0] if k + 1 < self.n else self.total + 60
            out.append((k, max(0.0, t), t1, title))
        return out

    def build(self):
        states = ("solo", "media")
        for k, a, b, title in self.spans():
            for st in states:
                im = getattr(self, f"_{self.theme}")(k, title, st)
                p = self.work / f"{self.theme}_{st}_{k:02d}.png"
                im.save(p)
                self.layers.append((str(p), 0, 0, a, b, st))
        getattr(self, f"_anim_{self.theme}")()
        return self

    # ---------------- NEWSROOM
    def _newsroom(self, k, title, st):
        L = self.lang
        im = _vgrad(W, H, (16, 30, 62), (9, 16, 32))
        tr_ = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        dt = ImageDraw.Draw(tr_)
        for yy in range(0, H, 6):     # trame fine (texture « plateau »)
            dt.line((0, yy, W, yy), fill=(255, 255, 255, 7))
        im.alpha_composite(tr_)
        d = _D(im)
        cam, med = self.lay["cam"], self.lay["media"]
        _shadow(im, cam)
        # bandeau chaîne
        hx, hy, hw, hh = 36, 196, 1008, 118
        d.rounded_rectangle((hx, hy, hx + hw, hy + hh), 18, fill=NAVY2 + (255,))
        for i, c in enumerate(((31, 75, 184), (255, 255, 255), RED)):
            d.rectangle((hx + i * hw // 3, hy + hh - 6, hx + (i + 1) * hw // 3, hy + hh), fill=c + (255,))
        lg = _logo(self.logo, 90)
        x = hx + 22
        if lg:
            im.alpha_composite(lg, (x, hy + (hh - 6 - lg.height) // 2))
            x += lg.width + 20
        live = tr(L, "live")
        fl = font("display", 40, live)
        lw = int(width(d, live, fl)) + 70
        lx1 = hx + hw - 22
        d.rounded_rectangle((lx1 - lw, hy + 22, lx1, hy + hh - 28), 12, fill=RED + (255,))
        d.ellipse((lx1 - lw + 18, hy + 47, lx1 - lw + 36, hy + 65), fill=(255, 255, 255, 255))
        text(d, (lx1 - lw + 46, hy + 56), live, fl, (255, 255, 255, 255), "lm")
        nom = self.nom.upper() or ""
        if nom:
            fn, ln = fit_lines(d, nom, "display", lx1 - lw - 24 - x, 52, 30, 1)
            text(d, (x, hy + 56), ln[0], fn, (255, 255, 255, 255), "lm", w=lx1 - lw - 24 - x)
        # titre du sujet (sous ton cadre)
        kick = tr(L, "sujet", k=k + 1, n=self.n) if self.n > 1 else (tr(L, "live"))
        fk = font("display", 40, kick)
        ky = cam[1] + cam[3] + 14
        kw_ = int(width(d, kick, fk)) + 48
        d.rounded_rectangle((36, ky, 36 + kw_, ky + 58), 10, fill=RED + (255,))
        text(d, (36 + 24, ky + 29), kick, fk, (255, 255, 255, 255), "lm")
        ft, lines = fit_lines(d, title, "serif", 860, 64, 44, 2)
        th = int(len(lines) * ft.size * 1.08) + 34
        ty = ky + 56
        tw_ = int(max(width(d, x_, ft) for x_ in lines)) + 56
        d.rounded_rectangle((36, ty, 36 + max(tw_, kw_ + 40), ty + th), 14, fill=(255, 255, 255, 255))
        yy = ty + 14
        for x_ in lines:
            text(d, (36 + 28, yy), x_, ft, NAVY + (255,), w=max(tw_, kw_ + 40) - 56)
            yy += int(ft.size * 1.08)
        # zone du bas : sommaire (toi seul) ou fenêtre du média
        mx, my, mw, mh = med
        if st == "solo":
            d.rounded_rectangle((mx, my, mx + mw, my + mh), 20, fill=(255, 255, 255, 18))
            som = tr(L, "som")
            fs = font("display", 38, som)
            text(d, (mx + 24, my + 20), som, fs, (159, 179, 217, 255))
            lo = max(0, min(k - 1, self.n - 4))
            yy = my + 76
            for j in range(lo, min(self.n, lo + 4)):
                t_ = self.topics[j][1]
                fi, li = fit_lines(d, t_, "sans", 470, 38, 30, 1)
                if j == k:
                    d.rounded_rectangle((mx + 14, yy - 6, mx + 560, yy + 60), 12, fill=(255, 255, 255, 255))
                col = NAVY + (255,) if j == k else ((223, 231, 246, 110) if j < k else (223, 231, 246, 255))
                fnum = font("display", 42, "0")
                text(d, (mx + 28, yy + 27), f"{j + 1:02d}", fnum, (RED + (255,)) if j == k else (125, 148, 196, 255), "lm")
                text(d, (mx + 92, yy + 27), li[0], fi, col, "lm", w=450)
                yy += 76
            if k + 1 < self.n:   # à suivre
                nx = mx + 590
                d.rounded_rectangle((nx, my + 76, mx + mw - 18, my + mh - 24), 12, fill=(255, 255, 255, 26))
                d.rectangle((nx, my + 76, nx + 8, my + mh - 24), fill=RED + (255,))
                nt = tr(L, "next")
                text(d, (nx + 26, my + 94), nt, font("display", 34, nt), (255, 122, 138, 255))
                fn2, l2 = fit_lines(d, self.topics[k + 1][1], "sans", mw - 590 - 60, 36, 28, 4)
                yy = my + 146
                for x_ in l2:
                    text(d, (nx + 26, yy), x_, fn2, (255, 255, 255, 255), w=mw - 590 - 60)
                    yy += int(fn2.size * 1.15)
        else:
            _shadow(im, med)
        # bandeau défilant : son fond (le texte qui défile est posé par-dessus)
        d.rounded_rectangle((-20, 1558, YT_RIGHT_X, 1640), 14, fill=(255, 255, 255, 255))
        pl = tr(L, "prog")
        fp = font("display", 40, pl)
        pw = int(width(d, pl, fp)) + 48
        d.rounded_rectangle((-20, 1558, pw, 1640), 14, fill=RED + (255,))
        text(d, (24, 1599), pl, fp, (255, 255, 255, 255), "lm")
        self._ticker_box = (pw + 10, 1560, YT_RIGHT_X - 14 - (pw + 10), 78)
        _hole(im, cam)
        if st != "solo":
            _hole(im, med)
        return im

    def _anim_newsroom(self):
        """Bandeau défilant : tous les sujets en boucle, séparés par un point rouge dessiné (aucun symbole de police)."""
        bx, by, bw, bh = self._ticker_box
        items = [f"{j + 1:02d}  {t}" for j, (_, t) in enumerate(self.topics)]
        if _rtl(" ".join(items)):
            items = items[::-1]           # arabe : défile de gauche à droite, dans l'ordre de lecture
        d0 = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
        gap = 90
        fs = [font("sans", 40, it) for it in items]
        ws = [int(width(d0, it, f)) for it, f in zip(items, fs)]
        per = max(sum(ws) + gap * len(items), bw + 10)
        strip = Image.new("RGBA", (per * 2 + bw, bh), (0, 0, 0, 0))
        d = ImageDraw.Draw(strip)
        x = 0
        while x < strip.width:
            for it, f, w_ in zip(items, fs, ws):
                text(d, (x, bh // 2), it, f, NAVY + (255,), "lm")
                x += w_
                d.ellipse((x + gap // 2 - 8, bh // 2 - 8, x + gap // 2 + 8, bh // 2 + 8), fill=RED + (255,))
                x += gap
        p = self.work / "ticker.png"
        strip.save(p)
        self.anim.append({"kind": "ticker", "png": str(p), "x": bx, "y": by, "w": bw, "h": bh, "per": per,
                          "speed": 95.0, "rtl": _rtl(" ".join(items))})

    # ---------------- WAR ROOM
    def _warroom(self, k, title, st):
        L = self.lang
        im = Image.new("RGBA", (W, H), DARK + (255,))
        gr = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        dg = ImageDraw.Draw(gr)
        for x in range(0, W, 54):
            dg.line((x, 0, x, H), fill=CYAN + (18,))
        for y in range(0, H, 54):
            dg.line((0, y, W, y), fill=CYAN + (18,))
        im.alpha_composite(gr)
        vig = Image.new("L", (W, H), 0)
        ImageDraw.Draw(vig).ellipse((-300, -200, W + 300, H + 200), fill=255)
        vig = vig.filter(ImageFilter.GaussianBlur(160))
        dark = Image.new("RGBA", (W, H), (0, 0, 0, 200))
        dark.putalpha(Image.eval(vig, lambda v: int((255 - v) * 0.8)))
        im.alpha_composite(dark)
        d = _D(im)
        cam, med = self.lay["cam"], self.lay["media"]

        def box(b, fill=(5, 20, 24, 215), line=CYAN + (110,)):
            x, y, w, h = b
            d.rectangle((x, y, x + w, y + h), fill=fill, outline=line, width=2)

        def corners(b, col=CYAN + (255,), L_=50, t=7):
            """Coins de visée (équerres) autour d'un cadre."""
            x, y, w, h = b
            for cx, cy, sx, sy in ((x, y, 1, 1), (x + w, y, -1, 1), (x, y + h, 1, -1), (x + w, y + h, -1, -1)):
                d.rectangle(_rect(cx - 4 * sx, cy - 4 * sy, sx * L_, sy * t), fill=col)
                d.rectangle(_rect(cx - 4 * sx, cy - 4 * sy, sx * t, sy * L_), fill=col)
        # barre du haut
        bb = (36, 196, 1008, 104)
        box(bb, line=CYAN + (160,))
        lg = _logo(self.logo, 74)
        x = 58
        if lg:
            im.alpha_composite(lg, (x, 196 + 15))
            x += lg.width + 20
        d = _D(im)
        live = tr(L, "live")
        fl = font("display", 40, live)
        lw_ = int(width(d, live, fl)) + 30
        d.ellipse((1044 - 22 - lw_, 240, 1044 - 22 - lw_ + 16, 256), fill=(255, 59, 59, 255))
        text(d, (1044 - 22 - lw_ + 30, 248), live, fl, (255, 59, 59, 255), "lm")
        cc = tr(L, "cc")
        fc, lc = fit_lines(d, cc, "display", 1044 - 22 - lw_ - 30 - x, 50, 30, 1)
        text(d, (x, 248), lc[0], fc, (232, 251, 255, 255), "lm", w=1044 - 22 - lw_ - 30 - x)
        # toi
        box(cam, fill=(0, 0, 0, 0), line=CYAN + (100,))
        corners(cam)
        lab = tr(L, "cam")
        fla = font("mono", 32, lab)
        d.rectangle((cam[0] + 14, cam[1] + 12, cam[0] + 58 + int(width(d, lab, fla)), cam[1] + 56), fill=(0, 0, 0, 180))
        d.ellipse((cam[0] + 24, cam[1] + 27, cam[0] + 38, cam[1] + 41), fill=(255, 59, 59, 255))
        text(d, (cam[0] + 48, cam[1] + 34), lab, fla, (232, 251, 255, 255), "lm")
        # colonne de droite : dossier en cours + radar (lieux cités) ou sujet suivant
        sx, sw = 712, 332
        b1 = (sx, 326, sw, 250)
        box(b1)
        h4 = tr(L, "doss")
        text(d, (sx + 18, 346), h4, font("display", 36, h4), CYAN + (255,))
        big = f"{k + 1:02d}/{self.n:02d}"
        text(d, (sx + 18, 396), big, font("display", 84, big), AMBER + (255,))
        seg_w = (sw - 36 - 6 * (min(self.n, 10) - 1)) / max(1, min(self.n, 10))
        for j in range(min(self.n, 10)):
            x0 = sx + 18 + j * (seg_w + 6)
            jj = j if self.n <= 10 else int(j * self.n / 10)
            d.rectangle((x0, 526, x0 + seg_w, 556), fill=AMBER + ((255,) if jj <= k else (45,)))
        b2 = (sx, 596, sw, 344)
        box(b2)
        if self.places:
            h4 = tr(L, "zones")
            text(d, (sx + 18, 614), h4, font("display", 36, h4), CYAN + (255,))
            self._radar = (sx + (sw - 180) // 2, 660, 180)
            rx, ry, rd = self._radar
            for rr, a in ((rd // 2, 160), (rd // 3, 110), (rd // 6, 90)):
                cx_, cy_ = rx + rd // 2, ry + rd // 2
                d.ellipse((cx_ - rr, cy_ - rr, cx_ + rr, cy_ + rr), outline=CYAN + (a,), width=2)
            rnd = random.Random(self.places[0])
            for j, _ in enumerate(self.places):
                ang, dist = rnd.uniform(0, 6.28), rnd.uniform(0.25, 0.85) * rd / 2
                px_, py_ = rx + rd // 2 + dist * math.cos(ang), ry + rd // 2 + dist * math.sin(ang)
                col = (255, 59, 59, 255) if j == 0 else AMBER + (255,)
                d.ellipse((px_ - 8, py_ - 8, px_ + 8, py_ + 8), fill=col)
            yy = 844
            for p in self.places[:2]:
                fpl, lpl = fit_lines(d, p.upper(), "display", sw - 36, 36, 30, 1)
                text(d, (sx + 18, yy), lpl[0], fpl, (191, 233, 228, 255))
                yy += 38
        else:
            self._radar = None
            h4 = tr(L, "suiv") if k + 1 < self.n else tr(L, "fin")
            text(d, (sx + 18, 614), h4, font("display", 32, h4), CYAN + (255,))
            nt = self.topics[k + 1][1] if k + 1 < self.n else title
            fn_, ln_ = fit_lines(d, nt.upper(), "display", sw - 36, 44, 30, 5)
            yy = 666
            for x_ in ln_:
                text(d, (sx + 18, yy), x_, fn_, (255, 255, 255, 255), w=sw - 36)
                yy += int(fn_.size * 1.12)
        # zone média : fenêtre du média, ou liste des dossiers (toi seul)
        mx, my, mw, mh = med
        if st == "solo":
            box(med)
            h4 = tr(L, "doss")
            text(d, (mx + 22, my + 18), h4, font("display", 34, h4), CYAN + (255,))
            lo = max(0, min(k - 1, self.n - 4))
            yy = my + 74
            for j in range(lo, min(self.n, lo + 4)):
                on = j == k
                d.rectangle((mx + 18, yy, mx + mw - 18, yy + 72),
                            fill=(255, 176, 32, 36) if on else (5, 20, 24, 180), outline=(AMBER + (255,)) if on else CYAN + (70,),
                            width=2)
                fnum = font("mono", 34, "0")
                text(d, (mx + 34, yy + 36), f"{j + 1:02d}", fnum, (AMBER + (255,)) if on else CYAN + (200,), "lm")
                if on:      # sujet en cours : triangle « lecture »
                    d.polygon([(mx + 98, yy + 24), (mx + 98, yy + 48), (mx + 118, yy + 36)], fill=AMBER + (255,))
                elif j < k:  # sujet traité : coche
                    d.line([(mx + 96, yy + 36), (mx + 104, yy + 45), (mx + 120, yy + 26)], fill=CYAN + (200,), width=4)
                fi, li = fit_lines(d, self.topics[j][1].upper(), "display", mw - 200, 38, 28, 1)
                text(d, (mx + 170, yy + 36), li[0], fi, (255, 255, 255, 255 if j >= k else 120), "lm", w=mw - 200)
                yy += 84
        else:
            box(med, fill=(0, 0, 0, 0), line=CYAN + (100,))
            corners(med)
            lab = tr(L, "flux")
            d.rectangle((mx + 14, my + mh - 54, mx + 58 + int(width(d, lab, fla)), my + mh - 12), fill=(0, 0, 0, 180))
            d.ellipse((mx + 24, my + mh - 40, mx + 38, my + mh - 26), fill=(255, 59, 59, 255))
            text(d, (mx + 48, my + mh - 33), lab, fla, (232, 251, 255, 255), "lm")
        # titre du dossier
        kick = tr(L, "dos", k=f"{k + 1:02d}", n=f"{self.n:02d}")
        fk, lk = fit_lines(d, kick, "display", 900, 40, 34, 1)
        text(d, (36, 1446), lk[0], fk, AMBER + (255,))
        ft, lt = fit_lines(d, title.upper(), "display", 900, 76, 46, 2)
        yy = 1446 + 52
        for x_ in lt:
            text(d, (36, yy), x_, ft, (255, 255, 255, 255), w=900)
            yy += int(ft.size * 1.04)
        _hole(im, cam, 0)
        if st != "solo":
            _hole(im, med, 0)
        return im

    def _anim_warroom(self):
        if not getattr(self, "_radar", None):
            return
        rx, ry, rd = self._radar
        im = Image.new("RGBA", (rd, rd), (0, 0, 0, 0))
        d = _D(im)
        for a in range(0, 70, 2):      # balayage (secteur dégradé)
            d.pieslice((0, 0, rd - 1, rd - 1), -a - 2, -a, fill=CYAN + (int(150 * (1 - a / 70)),))
        p = self.work / "radar.png"
        im.save(p)
        self.anim.append({"kind": "radar", "png": str(p), "x": rx, "y": ry})

    # ---------------- STORY
    def _story(self, k, title, st):
        """solo : grand titre doré + « ENSUITE » ; media : le média en bas (jamais sur ton visage), titre court au-dessus."""
        L = self.lang
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        im.alpha_composite(_vgrad(W, 420, (0, 0, 0), (0, 0, 0), 150, 0), (0, 0))
        g0 = 1060 if st == "media" else 1110
        im.alpha_composite(_vgrad(W, 220, (8, 12, 24), (8, 12, 24), 0, 170 if st == "media" else 200), (0, g0))
        im.alpha_composite(_vgrad(W, H - g0 - 220, (8, 12, 24), (8, 12, 24), 170 if st == "media" else 200, 245),
                           (0, g0 + 220))
        d = _D(im)
        # barres de progression (une par sujet ; celle du sujet en cours se remplit : élément animé)
        n = min(self.n, 12)
        gap = 12
        bw = (W - 72 - gap * (n - 1)) / n
        self._bars = []
        for j in range(n):
            x0 = 36 + j * (bw + gap)
            jj = j if self.n <= 12 else int(j * self.n / 12)
            d.rounded_rectangle((x0, 200, x0 + bw, 212), 6, fill=(255, 255, 255, 255 if jj < k else 80))
            self._bars.append((int(x0), int(bw)))
        lg = _logo(self.logo, 86)
        x = 36
        if lg:
            ring = Image.new("RGBA", (lg.width + 8, lg.height + 8), (0, 0, 0, 0))
            ImageDraw.Draw(ring).ellipse((0, 0, ring.width - 1, ring.height - 1), fill=(255, 255, 255, 255))
            im.alpha_composite(ring, (x, 236))
            im.alpha_composite(lg, (x + 4, 240))
            x += ring.width + 18
            d = _D(im)
        if self.nom:
            text(d, (x, 236 + 47), self.nom, font("sans", 40, self.nom), (255, 255, 255, 255), "lm")
        num = f"{k + 1:02d}"
        if st == "media":
            # rappel du sujet au-dessus du média
            fnum = font("display", 46, num)
            text(d, (46, 1112), num, fnum, GOLD + (255,), "lm")
            ft, lt = fit_lines(d, title, "display", W - 46 - 150 - 80, 44, 32, 1)
            text(d, (46 + 74, 1112), lt[0], ft, (255, 255, 255, 255), "lm", w=W - 46 - 150 - 80)
            mx, my, mw, mh = self.lay["media"]
            _shadow(im, self.lay["media"], strength=170)
            d = _D(im)
            d.rounded_rectangle((mx - 6, my - 6, mx + mw + 6, my + mh + 6), R_HOLE + 6, fill=(255, 255, 255, 255))
            _hole(im, self.lay["media"])
            return im
        fnum = font("serif", 120, num)
        d.text((46, 1290), num, font=fnum, fill=(0, 0, 0, 0), stroke_width=4, stroke_fill=GOLD + (255,))
        nw = int(d.textlength(num, font=fnum))
        sur = tr(L, "sur", n=self.n) if self.n > 1 else ""
        if sur:
            text(d, (46 + nw + 22, 1290 + 62), sur, font("display", 44, sur), GOLD + (255,), "lm")
        ft, lt = fit_lines(d, title, "serif", W - 46 - 150, 74, 48, 2)
        yy = 1400
        for x_ in lt:
            text(d, (46, yy), x_, ft, (255, 255, 255, 255), w=W - 46 - 150)
            yy += int(ft.size * 1.02)
        if k + 1 < self.n:
            ens = tr(L, "ens")
            fe = font("display", 34, ens)
            ew = int(width(d, ens, fe))
            d.rounded_rectangle((46, 1586, W - 150, 1644), 18, fill=(255, 255, 255, 40), outline=(255, 255, 255, 90), width=1)
            text(d, (66, 1615), ens, fe, GOLD + (255,), "lm")
            fn_, ln_ = fit_lines(d, self.topics[k + 1][1], "sans", W - 150 - 66 - ew - 40, 34, 26, 1)
            text(d, (66 + ew + 22, 1615), ln_[0], fn_, (255, 255, 255, 255), "lm", w=W - 150 - 66 - ew - 40)
        return im

    def _anim_story(self):
        if not getattr(self, "_bars", None):
            self._story(0, self.topics[0][1], "solo")
        bar = Image.new("RGBA", (max(b[1] for b in self._bars), 12), (0, 0, 0, 0))
        ImageDraw.Draw(bar).rounded_rectangle((0, 0, bar.width - 1, 11), 6, fill=(255, 255, 255, 255))
        p = self.work / "bar.png"
        bar.save(p)
        for k, a, b, _ in self.spans():
            j = k if self.n <= 12 else int(k * 12 / self.n)
            if j < len(self._bars):
                x0, bw = self._bars[j]
                self.anim.append({"kind": "progress", "png": str(p), "x": x0, "y": 200, "w": bw, "h": 12,
                                  "t0": a, "t1": min(b, self.total)})

    # ------------------------------------------------------------------ pour le rendu (ffmpeg)
    def graph(self, g, base: str, off: float, dur: float, state: str, fps: int) -> str:
        """Ajoute l'habillage au graphe d'un passage (temps du passage : 0 → dur ; dans la vidéo : off → off+dur).
        Renvoie l'étiquette de sortie."""
        st = state
        cur = base
        n = 0

        def lab():
            nonlocal n
            n += 1
            return f"hv{n}"
        for png, x, y, a, b, s in self.layers:
            if s != st or b <= off or a >= off + dur:
                continue
            i = g.inp("-loop", "1", "-framerate", fps, "-t", f"{dur + 1:.3f}", "-i", png)
            ra, rb = max(0.0, a - off), min(dur + 1, b - off)
            out = lab()
            g.add(f"[{cur}][{i}:v]overlay=x={x}:y={y}:format=auto:enable='between(t,{ra:.3f},{rb - 0.001:.3f})'[{out}]")
            cur = out
        for an in self.anim:
            i = g.inp("-loop", "1", "-framerate", fps, "-t", f"{dur + 1:.3f}", "-i", an["png"])
            if an["kind"] == "ticker":
                sign = "-" if an.get("rtl") else ""
                x_expr = f"mod({sign}(t+{off:.3f})*{an['speed']:.1f}+{an['per'] * 4},{an['per']})"
                t_ = lab()
                g.add(f"[{i}:v]format=rgba,crop=w={an['w']}:h={an['h']}:x='{x_expr}':y=0[{t_}]")
                out = lab()
                g.add(f"[{cur}][{t_}]overlay=x={an['x']}:y={an['y']}:format=auto[{out}]")
                cur = out
            elif an["kind"] == "radar":
                t_ = lab()
                g.add(f"[{i}:v]format=rgba,rotate=a='(t+{off:.3f})*1.3':c=none:ow=iw:oh=ih[{t_}]")
                out = lab()
                g.add(f"[{cur}][{t_}]overlay=x={an['x']}:y={an['y']}:format=auto[{out}]")
                cur = out
            elif an["kind"] == "progress":
                a, b = an["t0"], an["t1"]
                if b <= off or a >= off + dur:
                    g.add(f"[{i}:v]nullsink")
                    continue
                cv, pf, out = lab(), lab(), lab()
                span = max(0.5, b - a)
                g.add(f"color=c=black@0.0:s={an['w']}x{an['h']}:r={fps},format=rgba[{cv}]")
                g.add(f"[{cv}][{i}:v]overlay=x='-{an['w']}+{an['w']}*clip((t+{off:.3f}-{a:.3f})/{span:.3f},0,1)':y=0:"
                      f"shortest=1[{pf}]")
                ra, rb = max(0.0, a - off), min(dur + 1, b - off)
                g.add(f"[{cur}][{pf}]overlay=x={an['x']}:y={an['y']}:format=auto:"
                      f"enable='between(t,{ra:.3f},{rb - 0.001:.3f})'[{out}]")
                cur = out
        return cur


def _rect(x, y, dx, dy):
    """Rectangle (x0, y0, x1, y1) ordonné à partir d'un coin et d'une étendue signée."""
    return (min(x, x + dx), min(y, y + dy), max(x, x + dx), max(y, y + dy))


# ------------------------------------------------------------------ sujets (chapitres) et lieux
def sujets(plan: dict, segs: list, sents: list, total: float, out_time) -> list:
    """[(début dans la vidéo montée, titre)] : les chapitres du montage (le 1er commence à 0)."""
    out = []
    for i, c in enumerate(plan.get("chapters") or []):
        title = " ".join(str(c.get("title") or "").split())
        if not title:
            continue
        t = 0.0 if i == 0 else (out_time(segs, sents[c["s"]]["t0"]) if c.get("s", 10 ** 9) < len(sents) else None)
        if t is None or t > total - 8:
            continue
        if out and t < out[-1][0] + 8:     # deux chapitres trop proches : un seul sujet
            continue
        out.append((0.0 if not out else float(t), title))
    if not out:
        out = [(0.0, " ".join(str(plan.get("title") or plan.get("hook") or "").split())[:80] or "—")]
    return out


def lieux(plan: dict) -> list:
    """Lieux que TU cites (cartes « lieu » du plan), sans doublon."""
    seen, out = set(), []
    for v in plan.get("visuals") or []:
        if v.get("kind") != "place":
            continue
        lab = " ".join(str(v.get("label") or v.get("query") or "").split())
        k = lab.lower()
        if lab and k not in seen:
            seen.add(k)
            out.append(lab[:28])
    return out
