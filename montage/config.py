"""Réglages communs : formats, géométrie de l'écran, palette, polices, textes par langue.

Palette sobre et lisible pour un public de 40 ans et plus : bleu nuit, crème, or discret.
Tout se règle ici (une seule source de vérité)."""
from __future__ import annotations

import os
import shutil
import subprocess
from functools import lru_cache

FPS = 30
SAMPLE_RATE = 48000

# --- formats de sortie -------------------------------------------------------------------------------------
SIZE = {"h": (1920, 1080), "v": (1080, 1920)}

# Géométrie du partage d'écran (x, y, largeur, hauteur) dans l'image finale.
#   card  = toi, dans un cadre arrondi ;  panel = photo / article / chiffre à côté de toi
GEOM = {
    "h": {
        "left": {"card": (96, 96, 760, 888), "panel": (920, 96, 904, 888)},     # toi à gauche, média à droite
        "right": {"card": (1064, 96, 760, 888), "panel": (96, 96, 904, 888)},   # toi à droite, média à gauche
    },
    "v": {  # vertical : toi en haut, média en bas (le « côté » alterne quand même le sens d'entrée du média)
        "left": {"card": (70, 90, 940, 940), "panel": (70, 1090, 940, 720)},
        "right": {"card": (70, 90, 940, 940), "panel": (70, 1090, 940, 720)},
    },
}
CARD_RADIUS = 34
PANEL_RADIUS = 28
SHADOW_PAD = 48          # marge autour des cadres pour l'ombre portée

# --- couleurs (RGB) -------------------------------------------------------------------------------------------
NAVY = (20, 33, 61)
NAVY_DEEP = (11, 19, 38)
CREAM = (244, 239, 230)
PAPER = (250, 247, 241)
GOLD = (201, 162, 39)
INK = (27, 27, 31)
GREY = (110, 110, 116)
RED = (164, 22, 26)


def ass_color(rgb: tuple, alpha: int = 0) -> str:
    """Couleur ASS (&HAABBGGRR). alpha : 0 = opaque, 255 = invisible."""
    r, g, b = rgb
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


def ff_color(rgb: tuple, a: float = 1.0) -> str:
    r, g, b = rgb
    return f"0x{r:02X}{g:02X}{b:02X}@{a:.2f}"


# --- polices ---------------------------------------------------------------------------------------------------
# Familles (installées par le workflow : paquet fonts-noto-core). Repli automatique si absentes.
FONT_FAMILY = {
    "serif": "Noto Serif",
    "sans": "Noto Sans",
    "serif_ar": "Noto Naskh Arabic",
    "sans_ar": "Noto Sans Arabic",
}


@lru_cache(maxsize=None)
def font_file(kind: str, bold: bool = True) -> str | None:
    """Chemin du fichier de police (pour Pillow). Cherche dans fonts/, puis via fontconfig."""
    fam = FONT_FAMILY.get(kind, kind)
    here = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts")
    if os.path.isdir(here):
        want = fam.replace(" ", "").lower()
        for f in sorted(os.listdir(here)):
            n = f.lower()
            if n.startswith(want) and n.endswith((".ttf", ".otf")) and (("bold" in n) == bold):
                return os.path.join(here, f)
    if shutil.which("fc-match"):
        try:
            lang = ":lang=ar" if kind.endswith("_ar") else ""
            p = subprocess.run(["fc-match", "-f", "%{file}", f"{fam}:{'bold' if bold else 'regular'}{lang}"],
                               capture_output=True, text=True, timeout=10).stdout.strip()
            if p and os.path.exists(p):
                return p
        except (OSError, subprocess.SubprocessError):
            pass
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if os.path.exists(p):
            return p
    return None


def is_rtl(lang: str) -> bool:
    return (lang or "")[:2] in ("ar", "fa", "he", "ur")


def fam(kind: str, lang: str) -> str:
    """Nom de famille ASS selon la langue (l'arabe a ses propres polices)."""
    if is_rtl(lang):
        return FONT_FAMILY["serif_ar" if kind == "serif" else "sans_ar"]
    return FONT_FAMILY[kind]


# --- textes fixes par langue (le reste est écrit par l'IA, dans la langue de la vidéo) -------------------------
UI = {
    "fr": {"source": "Source", "photo": "Photo", "outro": "Merci de votre attention", "sub": "Abonnez-vous pour ne rien manquer",
           "translated": "Traduction", "chapter": "Partie"},
    "en": {"source": "Source", "photo": "Photo", "outro": "Thank you for watching", "sub": "Subscribe so you don't miss anything",
           "translated": "Translation", "chapter": "Part"},
    "it": {"source": "Fonte", "photo": "Foto", "outro": "Grazie per l'attenzione", "sub": "Iscriviti per non perdere nulla",
           "translated": "Traduzione", "chapter": "Parte"},
    "ar": {"source": "المصدر", "photo": "صورة", "outro": "شكراً على المتابعة", "sub": "اشترك حتى لا يفوتك شيء",
           "translated": "ترجمة", "chapter": "الجزء"},
    "es": {"source": "Fuente", "photo": "Foto", "outro": "Gracias por su atención", "sub": "Suscríbase para no perderse nada",
           "translated": "Traducción", "chapter": "Parte"},
    "de": {"source": "Quelle", "photo": "Foto", "outro": "Danke fürs Zuschauen", "sub": "Abonnieren, um nichts zu verpassen",
           "translated": "Übersetzung", "chapter": "Teil"},
}


def ui(lang: str, key: str) -> str:
    return UI.get((lang or "fr")[:2], UI["fr"]).get(key, UI["fr"][key])


# --- réglages par défaut (modifiables par le formulaire du workflow ou la description de la release) ----------
DEFAULTS = {
    "couper_silences": "doux",      # doux | dynamique | non
    "sous_titres": "oui",           # oui | non
    "recherche_presse": "oui",      # oui | non  (Vid-o-presse-finder)
    "max_inserts": "6",             # extraits de presse (Finder) insérés au maximum (pendant tes silences)
    "duree_max_insert": "25",       # secondes max par vidéo insérée (coupée en fin de phrase)
    "images_web": "oui",            # photos libres de droits (Wikimedia Commons) des personnes / lieux / choses citées
    "effets_sonores": "oui",        # petits souffles discrets aux transitions (pas de musique)
    "fin": "oui",                   # carte de fin « merci / abonnez-vous »
    "langue": "auto",               # auto | fr | ar | it | en ...
    "silences_longs": "oui",        # oui : tout silence de plus de 2 s est raccourci (avec effet doux selon ta position)
    "rythme": "oui",                # oui : 5 premières min → un extrait au moins toutes les 60 s ; ensuite toutes les 2 min
    "mots_cles": "oui",             # oui : après « écoutez ça / écoutez ce qu'il dit… », un passage de ta vidéo jointe
    "ouverture_choc": "oui",        # oui : la vidéo commence par le passage le plus fort de ta vidéo jointe
                                    # (aucune vidéo jointe → la vidéo commence normalement, comme « non »)
    "finder": "dernier",            # dernier | non | <nom d'un lot> : résultats de Vid-o-presse-finder à monter
}
