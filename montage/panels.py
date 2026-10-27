"""Dessin des éléments graphiques (Pillow) : cadre arrondi de l'auteur, ombres, cartes photo / article / chiffre /
citation. Style « magazine » sobre : papier crème, bleu nuit, filet or. L'arabe est écrit de droite à gauche."""
from __future__ import annotations

import logging
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, features

from . import config as C

log = logging.getLogger("montage.panels")
RAQM = features.check("raqm")
AR_RE = re.compile(r"[֐-ࣿיִ-ﻼ]")


def has_rtl(s: str) -> bool:
    return bool(AR_RE.search(s or ""))


def _font(kind: str, size: int, bold: bool = True, text: str = "") -> ImageFont.FreeTypeFont:
    if has_rtl(text):
        kind = {"serif": "serif_ar", "sans": "sans_ar"}.get(kind, kind)
    p = C.font_file(kind, bold) or C.font_file("sans", True)
    try:
        return ImageFont.truetype(p, size, layout_engine=ImageFont.Layout.RAQM if RAQM else ImageFont.Layout.BASIC)
    except (OSError, TypeError):
        return ImageFont.load_default()


def _shape(s: str) -> str:
    """Sans moteur RAQM, l'arabe doit être « reformé » à la main (lettres liées, ordre visuel)."""
    if RAQM or not has_rtl(s):
        return s
    try:
        import arabic_reshaper
        try:
            from bidi import get_display
        except ImportError:
            from bidi.algorithm import get_display
        return get_display(arabic_reshaper.reshape(s))
    except ImportError:
        return s


def _kw(s: str) -> dict:
    return {"direction": "rtl"} if (RAQM and has_rtl(s)) else {}


def tw(d: ImageDraw.ImageDraw, s: str, f) -> float:
    return d.textlength(_shape(s), font=f, **_kw(s))


def wrap(d, text: str, f, maxw: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if tw(d, t, f) <= maxw or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def fit(d, text: str, kind: str, maxw: int, maxh: int, start: int, minimum: int, max_lines: int, spacing=1.18):
    """Plus grande taille de police pour que le texte tienne dans la boîte."""
    for size in range(start, minimum - 1, -2):
        f = _font(kind, size, True, text)
        lines = wrap(d, text, f, maxw)
        if len(lines) <= max_lines and len(lines) * size * spacing <= maxh:
            return f, lines, size
    f = _font(kind, minimum, True, text)
    lines = wrap(d, text, f, maxw)[:max_lines]
    if lines:
        lines[-1] = lines[-1].rstrip(" ,.;:") + "…"
    return f, lines, minimum


def draw_lines(d, lines, f, size, box, fill, align="left", spacing=1.18, valign="top"):
    x0, y0, w, h = box
    total = len(lines) * size * spacing
    y = y0 if valign == "top" else (y0 + (h - total) / 2 if valign == "middle" else y0 + h - total)
    for ln in lines:
        lw = tw(d, ln, f)
        rtl = has_rtl(ln)
        al = "right" if (rtl and align == "left") else align
        x = x0 if al == "left" else (x0 + w - lw if al == "right" else x0 + (w - lw) / 2)
        d.text((x, y), _shape(ln), font=f, fill=fill, **_kw(ln))
        y += size * spacing
    return y


def rounded_mask(w: int, h: int, r: int) -> Image.Image:
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w - 1, h - 1), r, fill=255)
    return m


def shadow(w: int, h: int, r: int, pad: int = C.SHADOW_PAD, strength: int = 150, dy: int = 14) -> Image.Image:
    im = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    a = Image.new("L", im.size, 0)
    ImageDraw.Draw(a).rounded_rectangle((pad, pad + dy, pad + w, pad + h + dy), r, fill=strength)
    a = a.filter(ImageFilter.GaussianBlur(pad / 2.4))
    im.putalpha(a)
    return im


# ---------------- cadre de l'auteur (masque arrondi + ombre + filet) ----------------
def card_layers(w: int, h: int, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    p = {"mask": out / f"card_mask_{w}x{h}.png", "under": out / f"card_under_{w}x{h}.png",
         "over": out / f"card_over_{w}x{h}.png"}
    if not p["mask"].exists():
        rounded_mask(w, h, C.CARD_RADIUS).save(p["mask"])
        shadow(w, h, C.CARD_RADIUS, strength=170).save(p["under"])
        ov = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(ov).rounded_rectangle((1, 1, w - 2, h - 2), C.CARD_RADIUS, outline=C.CREAM + (235,), width=4)
        ov.save(p["over"])
    return p


# ---------------- cartes « média » à côté de l'auteur ----------------
def _cover(img: Image.Image, w: int, h: int, anchor_y: float = 0.35) -> Image.Image:
    img = ImageOps.exif_transpose(img).convert("RGB")
    sc = max(w / img.width, h / img.height)
    nw, nh = max(w, int(img.width * sc + 0.5)), max(h, int(img.height * sc + 0.5))
    img = img.resize((nw, nh), Image.LANCZOS)
    x = (nw - w) // 2
    y = int((nh - h) * anchor_y)
    return img.crop((x, y, x + w, y + h))


def _contain_on_blur(img: Image.Image, w: int, h: int) -> Image.Image:
    """Image entière (sans la rogner) posée sur une version floutée d'elle-même (logos, captures d'écran, documents)."""
    img = ImageOps.exif_transpose(img).convert("RGB")
    bg = _cover(img, w, h, 0.5).filter(ImageFilter.GaussianBlur(28))
    bg = Image.blend(bg, Image.new("RGB", bg.size, C.NAVY), 0.35)
    sc = min(w / img.width, h / img.height)
    im = img.resize((max(1, int(img.width * sc)), max(1, int(img.height * sc))), Image.LANCZOS)
    bg.paste(im, ((w - im.width) // 2, (h - im.height) // 2))
    return bg


def _base(pw: int, ph: int, color, hole=None, hole_r: int = 18) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    P = C.SHADOW_PAD
    im = shadow(pw, ph, C.PANEL_RADIUS, strength=160)
    card = Image.new("RGBA", (pw, ph), color + (255,))
    m = rounded_mask(pw, ph, C.PANEL_RADIUS)
    if hole:
        hx, hy, hw, hh = hole
        hm = Image.new("L", (pw, ph), 255)
        ImageDraw.Draw(hm).rounded_rectangle((hx, hy, hx + hw - 1, hy + hh - 1), hole_r, fill=0)
        m = Image.composite(m, Image.new("L", (pw, ph), 0), hm)
    card.putalpha(m)
    im.alpha_composite(card, (P, P))
    return im, ImageDraw.Draw(im)


def render_panel(kind: str, pw: int, ph: int, data: dict, out: Path, name: str) -> dict:
    """Retourne {"frame": png (carte + ombre, trou transparent), "photo": png ou None, "hole": (x,y,w,h) dans le png,
    "size": (w,h) du png}. La photo est animée (lent travelling) par ffmpeg derrière le trou du cadre."""
    out.mkdir(parents=True, exist_ok=True)
    P = C.SHADOW_PAD
    img = data.get("image")
    label, sub, credit = data.get("label", ""), data.get("sublabel", ""), data.get("credit", "")
    photo = None
    hole = None
    if kind == "figure":
        im, d = _base(pw, ph, C.NAVY)
        m = 64
        f, lines, size = fit(d, data.get("text", ""), "serif", pw - 2 * m, int(ph * 0.48), 190, 60, 3, 1.08)
        y_end = draw_lines(d, lines, f, size, (P + m, P + int(ph * 0.16), pw - 2 * m, int(ph * 0.48)), C.GOLD,
                           align="center", spacing=1.08, valign="middle")
        y_end += int(size * 0.22)   # le filet passe SOUS les chiffres (jamais à travers)
        d.rectangle((P + pw / 2 - 60, y_end + 26, P + pw / 2 + 60, y_end + 31), fill=C.GOLD)
        if label:
            f2, l2, s2 = fit(d, label, "sans", pw - 2 * m, int(ph * 0.2), 52, 36, 2)
            yy = draw_lines(d, l2, f2, s2, (P + m, y_end + 60, pw - 2 * m, int(ph * 0.2)), C.CREAM, align="center")
        else:
            yy = y_end + 60
        if sub:
            f3, l3, s3 = fit(d, sub, "sans", pw - 2 * m, int(ph * 0.14), 38, 30, 2)
            draw_lines(d, l3, f3, s3, (P + m, yy + 10, pw - 2 * m, int(ph * 0.12)), (222, 226, 236), align="center")
    elif kind == "quote":
        im, d = _base(pw, ph, C.PAPER)
        m = 70
        text = data.get("text", "")
        fq = _font("serif", 220, True, "«")
        rtl = has_rtl(text)
        d.text((P + (pw - m - 110 if rtl else m - 20), P + 10), "”" if rtl else "“", font=fq, fill=C.GOLD)
        f, lines, size = fit(d, text, "serif", pw - 2 * m, int(ph * 0.62), 84, 44, 6, 1.2)
        draw_lines(d, lines, f, size, (P + m, P + int(ph * 0.2), pw - 2 * m, int(ph * 0.62)), C.INK, align="left",
                   spacing=1.2, valign="middle")
        d.rectangle((P + m, P + ph - 92, P + m + 90, P + ph - 87), fill=C.GOLD)
        if label:
            f2, l2, s2 = fit(d, label, "sans", pw - 2 * m, 46, 36, 28, 1)
            draw_lines(d, l2, f2, s2, (P + m, P + ph - 78, pw - 2 * m, 46), C.NAVY)
    elif kind == "statement":  # déclaration (extrait vidéo non téléchargeable) : vignette + citation + qui + où
        has_img = img is not None
        hole = (22, 22, pw - 44, int(ph * 0.42)) if has_img else None
        im, d = _base(pw, ph, C.PAPER, hole)
        m = 40
        top = (hole[1] + hole[3] + 22) if hole else 40
        quote = data.get("text", "")
        rtl = has_rtl(quote)
        fq = _font("serif", 120, True, "«")
        d.text((P + (pw - m - 70 if rtl else m - 8), P + top - 34), "”" if rtl else "“", font=fq, fill=C.GOLD)
        avail = ph - top - 150
        f, lines, size = fit(d, quote, "serif", pw - 2 * m - 30, avail, 56, 34, 7, 1.18)
        draw_lines(d, lines, f, size, (P + m + (0 if rtl else 30), P + top + 34, pw - 2 * m - 30, avail), C.INK, spacing=1.18)
        y = P + ph - 108
        if label:
            d.rectangle((P + pw - m - 8 if has_rtl(label) else P + m, y + 6, P + pw - m if has_rtl(label) else P + m + 8,
                         y + 50), fill=C.GOLD)
            f2, l2, s2 = fit(d, label, "sans", pw - 2 * m - 26, 50, 40, 30, 1)
            draw_lines(d, l2, f2, s2, (P + m + (0 if has_rtl(label) else 26), y + 4, pw - 2 * m - 26, 50), C.NAVY)
        if sub:
            f3, l3, s3 = fit(d, sub, "sans", pw - 2 * m - 26, 40, 32, 26, 1)
            draw_lines(d, l3, f3, s3, (P + m + 26, y + 58, pw - 2 * m - 26, 40), (70, 70, 78))
        if has_img:
            photo = _cover(img, hole[2] * 2, hole[3] * 2, 0.4)
    elif kind == "article":
        hdr = 92
        has_img = img is not None
        hole = (22, hdr, pw - 44, int(ph * 0.40)) if has_img else None
        im, d = _base(pw, ph, C.PAPER, hole)
        m = 36
        src = (data.get("source") or "").upper()
        fs = _font("sans", 36, True, src)
        draw_lines(d, [src[:32]], fs, 36, (P + m, P + 26, pw * 0.6, 46), C.RED)
        if data.get("date"):
            fd = _font("sans", 32, True, data["date"])
            draw_lines(d, [data["date"]], fd, 32, (P + pw * 0.55, P + 30, pw * 0.45 - m, 44), (70, 70, 78), align="right")
        top = hdr + (hole[3] + 26 if hole else 10)
        d.rectangle((P + m, P + top - 12, P + pw - m, P + top - 10), fill=(200, 192, 178))
        avail = ph - top - 80
        f, lines, size = fit(d, data.get("headline", ""), "serif", pw - 2 * m, avail, 70 if not has_img else 58, 38, 6, 1.16)
        draw_lines(d, lines, f, size, (P + m, P + top + 6, pw - 2 * m, avail), C.INK, spacing=1.16)
        fdom = _font("sans", 30, True, "x")
        d.rectangle((P + m, P + ph - 58, P + m + 70, P + ph - 54), fill=C.GOLD)
        draw_lines(d, [(data.get("domain") or "")[:44]], fdom, 30, (P + m + 86, P + ph - 74, pw - 2 * m - 86, 38), (70, 70, 78))
        if has_img:
            photo = _cover(img, hole[2] * 2, hole[3] * 2, 0.3)
    else:  # photo : personne, lieu, chose, événement, image jointe
        band = 0
        if label or sub:
            band = 150 if sub else 112
        cband = 40 if credit else 0
        hole = (20, 20, pw - 40, ph - 40 - band - cband)
        im, d = _base(pw, ph, C.PAPER, hole)
        m = 34
        y = P + hole[1] + hole[3] + 18
        if label:
            rtl = has_rtl(label)
            d.rectangle((P + pw - m - 8 if rtl else P + m, y + 8, P + pw - m if rtl else P + m + 8, y + 58), fill=C.GOLD)
            f, l1, s1 = fit(d, label, "serif", pw - 2 * m - 30, 64, 50, 38, 1)
            draw_lines(d, l1, f, s1, (P + m + (0 if rtl else 26), y, pw - 2 * m - 26, 64), C.INK)
            y += 66
        if sub:
            f, l2, s2 = fit(d, sub, "sans", pw - 2 * m - 26, 44, 34, 28, 1)
            draw_lines(d, l2, f, s2, (P + m + (0 if has_rtl(sub) else 26), y, pw - 2 * m - 26, 44), (70, 70, 78))
        if credit:
            fc = _font("sans", 24, True, credit)
            draw_lines(d, [credit[:70]], fc, 24, (P + m, P + ph - 38, pw - 2 * m, 30), (88, 88, 96), align="right")
        if img is not None:
            hw, hh = hole[2] * 2, hole[3] * 2
            portrait = kind == "person"
            ratio = img.width / max(1, img.height)
            hr = hole[2] / max(1, hole[3])
            # une image très différente du cadre (logo, document, capture) n'est pas rognée : posée sur fond flou
            if (not portrait) and (ratio > hr * 1.9 or ratio < hr / 1.9 or kind == "attachment" and data.get("contain")):
                photo = _contain_on_blur(img, hw, hh)
            else:
                photo = _cover(img, hw, hh, 0.22 if portrait else 0.4)
    frame = out / f"{name}_frame.png"
    im.save(frame)
    ph_path = None
    if photo is not None and hole:
        ph_path = out / f"{name}_photo.jpg"
        photo.save(ph_path, quality=92)
    return {"frame": str(frame), "photo": str(ph_path) if ph_path else None,
            "hole": (P + hole[0], P + hole[1], hole[2], hole[3]) if (hole and ph_path) else None, "size": im.size}


def open_image(path) -> Image.Image | None:
    try:
        try:
            import pillow_heif  # photos d'iPhone (.heic)
            pillow_heif.register_heif_opener()
        except ImportError:
            pass
        im = Image.open(path)
        im.load()
        if getattr(im, "is_animated", False):
            im.seek(0)
        im = ImageOps.exif_transpose(im)
        if im.mode in ("RGBA", "LA", "P"):
            bg = Image.new("RGB", im.size, (255, 255, 255))
            im = im.convert("RGBA")
            bg.paste(im, mask=im.split()[-1])
            im = bg
        return im.convert("RGB")
    except Exception as e:  # noqa: BLE001
        log.warning("image illisible %s : %s", path, e)
        return None
