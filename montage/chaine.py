"""Profils de chaîne : logo, nom et couleurs de l'habillage — sans toucher au code.

    chaines/<code>/chaine.json   {"nom": "...", "langues": ["fr"], "defaut": true}
    chaines/<code>/logo.png      PNG (fond transparent idéal, 512 px ou plus)

Choix du profil (réglage « chaine ») : auto (défaut) = la chaîne dont la langue est celle de la vidéo, sinon la
chaîne marquée « defaut » ; un code (fr, ar, it, en…) = cette chaîne ; non = aucun habillage de chaîne.
Changer de logo ou de nom = remplacer le fichier. Nouvelle chaîne = nouveau dossier.

Habillage : petit logo permanent en haut à droite (hors du visage et des cadres), grand logo sur la carte de fin, et
couleurs de l'habillage tirées du logo (bleu nuit, or, rouge) — seulement si elles restent bien lisibles.
Tout problème (logo absent, illisible, sans transparence…) est écrit dans PLAN.md ; le montage continue toujours."""
from __future__ import annotations

import colorsys
import json
import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from . import config as C

log = logging.getLogger("montage.chaine")
ROOT = Path(__file__).resolve().parent.parent / "chaines"
DEFAULT_PALETTE = {k: getattr(C, k) for k in ("NAVY", "NAVY_DEEP", "GOLD", "RED")}
# petit logo permanent : taille et position par format (jamais sur les cadres : ceux-ci commencent à y = 96 / 90)
BUG = {"h": {"size": 84, "x": 1920 - 24 - 84, "y": 8}, "v": {"size": 76, "x": 1080 - 24 - 76, "y": 10}}


# ------------------------------------------------------------------ profils
def load_all(root: Path = ROOT) -> list[dict]:
    out = []
    if not root.is_dir():
        return out
    for d in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
        out.append(load(d))
    return out


def load(d: Path) -> dict:
    p = {"code": d.name.lower(), "dir": d, "nom": "", "langues": [d.name.lower()[:2]], "defaut": False,
         "couleurs": {}, "couleurs_auto": True, "logo": None, "notes": []}
    f = d / "chaine.json"
    if f.exists():
        try:
            j = json.loads(f.read_text(encoding="utf-8-sig"))
            if not isinstance(j, dict):
                raise ValueError("ce n'est pas un objet JSON")
            p["nom"] = str(j.get("nom") or "").strip()[:60]
            lg = j.get("langues") or j.get("langue") or p["langues"]
            p["langues"] = [str(x).strip().lower()[:2] for x in (lg if isinstance(lg, list) else [lg]) if str(x).strip()]
            p["defaut"] = bool(j.get("defaut"))
            p["couleurs"] = j.get("couleurs") if isinstance(j.get("couleurs"), dict) else {}
            p["couleurs_auto"] = j.get("couleurs_auto", True) is not False
            if j.get("logo"):
                p["logo_name"] = str(j["logo"])
        except (OSError, ValueError) as e:
            p["notes"].append(f"chaines/{d.name}/chaine.json illisible ({e}) : réglages par défaut")
    cands = [d / p["logo_name"]] if p.get("logo_name") else []
    cands += sorted(d.glob("logo.*")) + sorted(x for x in d.iterdir() if x.suffix.lower() in (".png", ".webp", ".jpg", ".jpeg"))
    for c in cands:
        if c.is_file():
            p["logo"] = c
            break
    if not p["logo"]:
        p["notes"].append(f"chaines/{d.name} : aucun logo (logo.png) → habillage sans logo")
    return p


def choose(which: str, lang: str, root: Path = ROOT) -> tuple[dict | None, str]:
    """(profil, explication pour PLAN.md)."""
    which = (which or "auto").strip().lower()
    if which in ("non", "no", "aucun", "aucune", "off", "0"):
        return None, "habillage de chaîne désactivé (réglage chaine: non)"
    profs = load_all(root)
    if not profs:
        return None, "aucun profil de chaîne (dossier chaines/ vide) : habillage par défaut, sans logo"
    if which not in ("auto", "oui", "yes", "defaut", "défaut", ""):
        p = next((x for x in profs if x["code"] == which), None) \
            or next((x for x in profs if x["nom"].lower() == which), None)
        if p:
            return p, f"chaîne « {p['nom'] or p['code']} » (choisie : {which})"
        auto, why = choose("auto", lang, root)
        return auto, f"⚠ chaîne « {which} » introuvable dans chaines/ → {why}"
    lg = (lang or "")[:2]
    p = next((x for x in profs if lg and lg in x["langues"]), None)
    if p:
        return p, f"chaîne « {p['nom'] or p['code']} » (langue de la vidéo : {lg})"
    p = next((x for x in profs if x["defaut"]), None) or next((x for x in profs if x["code"] == "fr"), None) or profs[0]
    return p, f"chaîne « {p['nom'] or p['code']} » (aucune chaîne en « {lg} » : chaîne par défaut)"


# ------------------------------------------------------------------ logo
def open_logo(path: Path) -> tuple[Image.Image, list[str]]:
    """Logo RGBA rogné au plus juste. Sans transparence : coins arrondis (et note pour fournir un PNG transparent)."""
    notes = []
    with Image.open(path) as im0:
        im0.verify()   # fichier corrompu → exception claire
    im = Image.open(path)
    im.load()
    im = im.convert("RGBA")
    if min(im.size) < 64:
        raise ValueError(f"logo trop petit ({im.size[0]}×{im.size[1]} px)")
    if min(im.size) < 256:
        notes.append(f"logo petit ({im.size[0]}×{im.size[1]} px) : fournis 512 px ou plus pour un rendu net")
    a = im.getchannel("A")
    if a.getextrema()[0] >= 250:   # aucun pixel transparent
        w, h = im.size
        r = int(min(w, h) * 0.22)
        mask = Image.new("L", (w * 4, h * 4), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, w * 4 - 1, h * 4 - 1), r * 4, fill=255)
        im.putalpha(mask.resize((w, h), Image.LANCZOS))
        notes.append("logo sans fond transparent : coins arrondis ajoutés (un PNG transparent rendra mieux)")
    box = im.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    if not box:
        raise ValueError("logo entièrement transparent")
    return im.crop(box), notes


def _fit(im: Image.Image, size: int) -> Image.Image:
    k = size / max(im.size)
    return im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)


def _with_shadow(im: Image.Image, opacity: float, pad: int, blur: float) -> Image.Image:
    a = im.getchannel("A").point(lambda v: int(v * opacity))
    logo = im.copy()
    logo.putalpha(a)
    out = Image.new("RGBA", (im.width + 2 * pad, im.height + 2 * pad), (0, 0, 0, 0))
    sh = Image.new("RGBA", out.size, (0, 0, 0, 255))
    smask = Image.new("L", out.size, 0)
    smask.paste(a.point(lambda v: int(v * 0.55)), (pad, pad + 2))
    sh.putalpha(smask.filter(ImageFilter.GaussianBlur(blur)))
    out = Image.alpha_composite(out, sh)
    out.alpha_composite(logo, (pad, pad))
    return out


def prepare(profile: dict | None, orient: str, work: Path) -> dict:
    """Fichiers prêts pour le rendu : {"bug", "bug_xy", "end", "notes"} (clés absentes si pas de logo)."""
    out = {"notes": list((profile or {}).get("notes") or []), "nom": (profile or {}).get("nom", "")}
    if not profile or not profile.get("logo"):
        return out
    try:
        im, notes = open_logo(profile["logo"])
        out["notes"] += notes
    except Exception as e:  # noqa: BLE001
        out["notes"].append(f"⚠ logo « {profile['logo'].name} » illisible ({e}) : montage sans logo")
        return out
    work.mkdir(parents=True, exist_ok=True)
    b = BUG[orient]
    pad = 6
    bug = _with_shadow(_fit(im, b["size"]), 0.92, pad, 3)
    bp = work / "logo_bug.png"
    bug.save(bp)
    out["bug"] = str(bp)
    # le logo est centré dans sa case (largeur ou hauteur réduite selon ses proportions)
    out["bug_xy"] = (b["x"] - pad + (b["size"] - (bug.width - 2 * pad)) // 2,
                     b["y"] - pad + (b["size"] - (bug.height - 2 * pad)) // 2)
    big = _fit(im, 400)
    ep = work / "logo_fin.png"
    big.save(ep)
    out["end_src"] = str(ep)
    out["logo_img"] = im
    return out


def end_card(brand: dict, box: tuple, W: int, work: Path) -> None:
    """Grand logo dans le bandeau de fin (à gauche du texte). box = (haut, bas, début, gauche_du_texte)."""
    if not brand.get("end_src") or not box:
        return
    top, bot, t0, slot = box
    size = int(min(bot - top - 36, 260, slot - 60))
    if size < 90:
        brand["notes"].append("bandeau de fin trop étroit : grand logo omis")
        return
    im = _fit(Image.open(brand["end_src"]).convert("RGBA"), size)
    p = work / "logo_fin_ok.png"
    im.save(p)
    brand["end"] = str(p)
    brand["end_xy"] = (max(24, (slot - im.width) // 2), top + (bot - top - im.height) // 2)
    brand["end_t0"] = t0


# ------------------------------------------------------------------ couleurs
def _lum(rgb) -> float:
    def ch(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a, b) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def logo_colors(im: Image.Image) -> dict:
    """Couleurs marquantes du logo : bleu nuit (fond), or/jaune, rouge — None si absentes."""
    small = im.copy()
    small.thumbnail((160, 160))
    px = [p[:3] for p in small.getdata() if p[3] > 200]
    if len(px) < 50:
        return {}
    q = Image.new("RGB", (len(px), 1))
    q.putdata(px)
    pal = q.quantize(colors=12, method=Image.Quantize.MEDIANCUT)
    cols = pal.getpalette()[:36]
    counts = sorted(pal.getcolors(), reverse=True)
    found = {}
    tot = len(px)
    for n, idx in counts:
        rgb = tuple(cols[idx * 3: idx * 3 + 3])
        h, l, s = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
        share = n / tot
        if share < 0.03:
            continue
        hue = h * 360
        if l < 0.30 and s > 0.25 and 190 <= hue <= 260 and "navy" not in found:
            found["navy"] = rgb
        elif 0.35 <= l <= 0.75 and s > 0.45 and 30 <= hue <= 58 and "gold" not in found:
            found["gold"] = rgb
        elif 0.30 <= l <= 0.65 and s > 0.50 and (hue < 12 or hue > 345) and "red" not in found:
            found["red"] = rgb
    return found


def _hex(v) -> tuple | None:
    s = str(v or "").strip().lstrip("#")
    if len(s) == 6:
        try:
            return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            return None
    return None


def apply_palette(profile: dict | None, brand: dict) -> list[str]:
    """Met à jour les couleurs de config (habillage). Revient toujours à la palette maison si illisible."""
    for k, v in DEFAULT_PALETTE.items():
        setattr(C, k, v)
    if not profile:
        return []
    notes, want = [], {}
    if profile.get("couleurs_auto", True) and brand.get("logo_img") is not None:
        f = logo_colors(brand["logo_img"])
        if f.get("navy"):
            want["NAVY"] = f["navy"]
        if f.get("gold"):
            want["GOLD"] = f["gold"]
        if f.get("red"):
            want["RED"] = f["red"]
    for k, v in (profile.get("couleurs") or {}).items():
        rgb = _hex(v)
        if k.upper() in DEFAULT_PALETTE and rgb:
            want[k.upper()] = rgb
        else:
            notes.append(f"couleur « {k}: {v} » ignorée (clés : NAVY, NAVY_DEEP, GOLD, RED ; format #RRGGBB)")
    # lisibilité (contrastes WCAG) : sinon on garde la couleur maison
    checks = {"NAVY": lambda c: contrast(c, C.CREAM) >= 7 and contrast(c, C.GOLD_HI) >= 6,
              "NAVY_DEEP": lambda c: contrast(c, C.CREAM) >= 9,
              "GOLD": lambda c: contrast(c, want.get("NAVY", C.NAVY)) >= 3,
              "RED": lambda c: contrast(c, C.PAPER) >= 4.5}
    for k, rgb in want.items():
        c = rgb
        for _ in range(12):   # même teinte, assombrie jusqu'à être lisible
            if checks[k](c):
                break
            c = tuple(int(x * 0.88) for x in c)
        if checks[k](c):
            setattr(C, k, c)
        else:
            notes.append(f"couleur {k} {rgb} illisible même assombrie : couleur maison gardée")
    if "NAVY" in want and "NAVY_DEEP" not in want and C.NAVY == want["NAVY"]:
        C.NAVY_DEEP = tuple(int(c * 0.55) for c in C.NAVY)
    return notes
