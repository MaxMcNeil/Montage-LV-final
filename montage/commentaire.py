"""MODE « COMMENTAIRE D'UNE VIDÉO » : tu commentes une vidéo (déposée dans Drive montage-joints) ; le prompteur
(OSINT-teleprompter, même mode) a choisi l'ouverture choc et les passages, et a écrit ton script avec un
« 🎬 ÉCOUTEZ ÇA » par passage. Sa liste exacte arrive ici : input/commentaire-passages.json.

Montage :
  1. OUVERTURE CHOC : le passage le plus fort de la vidéo commentée, avant que tu apparaisses ;
  2. la vidéo commentée reste À L'ÉCRAN EN PERMANENCE (la moitié de l'écran) : en PAUSE sur l'image du passage qui va
     suivre, avec ⏸ et le titre de ce passage (lent zoom : jamais figée) ;
  3. à chaque « écoutez ça » que tu dis, le passage repart (ta vidéo attend, toi qui écoutes à côté), puis se remet en
     pause sur le passage suivant ;
  4. ATTRIBUTION BLINDÉE : le n-ième « écoutez ça » = le n-ième passage, en suivant l'ordre du script ; si tu en sautes
     un ou en ajoutes un, ta phrase d'annonce (comparée à l'annonce du script) recale la suite ; un « écoutez ça » en
     trop, quand tous les passages sont passés, ne lance rien (écrit dans PLAN.md).
Jamais bloquant : sans la liste du prompteur, le montage se fait comme d'habitude (et PLAN.md le dit)."""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from pathlib import Path

log = logging.getLogger("montage.commentaire")


def actif(opts: dict) -> bool:
    return str(opts.get("mode") or "").strip().lower().startswith("comment")


def charger(path: Path) -> dict | None:
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    ps = [p for p in (d.get("passages") or []) if isinstance(p, dict) and float(p.get("end", 0)) > float(p.get("start", 0))]
    if not ps:
        return None
    d["passages"] = sorted(ps, key=lambda p: float(p["start"]))
    return d


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "", t)


def video_commentee(att: list, data: dict):
    """La pièce jointe qui est la vidéo commentée : même nom que dans la liste du prompteur, sinon la plus longue."""
    vids = [x for x in att if x.get("kind") == "video"]
    if not vids:
        return None
    nom = _norm(Path(str(data.get("video") or "")).stem)
    for x in vids:
        # la chaîne numérote les pièces jointes (« 01_nom.mp4 ») : même nom, au préfixe près
        st = _norm(Path(x["name"]).stem)
        if nom and (st == nom or (st.endswith(nom) and st[:-len(nom)].isdigit())):
            return x
    if nom:   # la liste du prompteur a été faite pour UNE AUTRE vidéo (ancienne liste) : jamais appliquée à celle-ci
        return None
    return max(vids, key=lambda x: float(x.get("duration") or 0))


def _toks(t: str) -> set:
    from .pertinence import toks
    return toks(t, 4)


def attribuer(occ: list, words: list, passages: list) -> list:
    """[(occurrence, passage | None, pourquoi)] dans l'ordre. Le passage suivant du script par défaut ; un passage un peu
    plus loin seulement si ton annonce lui correspond nettement mieux (tu en as sauté un)."""
    out, nxt = [], 0
    for o in occ:
        if nxt >= len(passages):
            out.append((o, None, "tous les passages ont déjà été joués (« écoutez ça » en trop)"))
            continue
        avant = " ".join(w["w"] for w in words[max(0, o["w0"] - 70):o["w0"]])
        mine = _toks(avant)

        def score(p):
            ref = _toks(" ".join(str(p.get(k) or "") for k in ("annonce", "titre")))
            return len(mine & ref) / max(4, len(ref)) if ref else 0.0
        cands = list(range(nxt, min(len(passages), nxt + 3)))
        sc = {j: score(passages[j]) for j in cands}
        best = max(cands, key=lambda j: sc[j] - 0.12 * (j - nxt))
        why = "passage suivant du script"
        if best != nxt and sc[best] >= 0.25 and sc[best] >= sc[nxt] + 0.15:
            why = f"ton annonce correspond au passage {best + 1} (tu as sauté {best - nxt} passage(s))"
        else:
            best = nxt
        out.append((o, passages[best], why))
        nxt = best + 1
    return out


def preparer(ai, words, sents, att, tr, quiet, orient, work, lang, data, label_for=None):
    """(ouverture, extraits « écoutez ça », informations pour PLAN.md)."""
    from .assets import prepare_insert
    from .keywords import find_occurrences, pause_after
    from .pauses import merge
    from .util import tc
    info = {"items": [], "passages": len(data["passages"]), "video": data.get("video")}
    x = video_commentee(att, data)
    if not x:
        info["erreur"] = (f"la liste du prompteur est pour « {data.get('video')} », introuvable dans montage-joints "
                          "(ancienne liste ? relance le prompteur en mode commentaire) : montage fait comme d'habitude")
        return None, [], info
    info["video"] = x["name"]
    label = (label_for(x, 0, 0) if label_for else None) or x.get("label") or Path(x["name"]).stem.replace("_", " ")

    def clip(a, b, nom, src_txt):
        a, b = max(0.0, float(a)), min(float(x.get("duration") or b), float(b))
        asset = prepare_insert(Path(x["path"]), a, b, orient, work, nom, lang, ai, x.get("sentences") or None,
                               x.get("lang"))
        if asset:
            asset["credit"] = {"label": label}
            asset["source"] = f"{src_txt} — « {x['name']} » ({tc(a)} → {tc(b)})"
            asset["attachment"], asset["clip"] = x["id"], (a, b)
            asset["_com"] = True
        return asset
    ouv = data.get("ouverture") or {}
    opener = clip(ouv["start"], ouv["end"], "insert_opener", "OUVERTURE CHOC (commentaire)") \
        if ouv.get("end", 0) > ouv.get("start", 0) else None
    # « écoutez ça » : toutes les occurrences, y compris sans vrai silence (le script te fait marquer une pause)
    occ = find_occurrences(words)
    sil = merge(tr.get("silences") or [], quiet)
    inserts = []
    for o, p, why in attribuer(occ, words, data["passages"]):
        item = {"phrase": o["phrase"], "t0": o["t0"], "why": why, "inserted": False}
        info["items"].append(item)
        if p is None:
            continue
        a = clip(p["start"], p["end"], f"insert_com{len(inserts)}", f"ÉCOUTEZ ÇA n°{p.get('n', '?')}")
        if not a:
            item["why"] = "passage illisible dans la vidéo commentée"
            continue
        a["pause_titre"] = str(p.get("titre") or "")
        t = pause_after(words, sil, o["w1"], 12.0)
        s_i = next((s["i"] for s in sents if s["w0"] <= o["w1"] <= s["w1"]), 0)
        ins = {"after": s_i, "asset": a, "attachment": x["id"], "clip": a["clip"], "kw": len(inserts),
               "passage": p, "commentaire": True}
        if t is not None:
            ins["forced_t"] = t
        inserts.append(ins)
        item.update(inserted=True, n=p.get("n"), titre=p.get("titre"), at=t)
    joues = {i["passage"].get("n") for i in inserts}
    info["oublies"] = [p for p in data["passages"] if p.get("n") not in joues]
    log.info("Commentaire : %d « écoutez ça » entendu(s), %d passage(s) placé(s) sur %d, ouverture %s",
             len(occ), len(inserts), len(data["passages"]), "oui" if opener else "non")
    return opener, inserts, info


# Mode commentaire, horizontal : la vidéo commentée prend PLUS de la moitié de l'écran (1080 px sur 1920), toi à côté
GEOM_H = {"left": {"card": (80, 140, 620, 800), "panel": (760, 140, 1080, 800)},
          "right": {"card": (1220, 140, 620, 800), "panel": (80, 140, 1080, 800)}}


def mise_en_page(orient: str) -> None:
    """Agrandit la zone de la vidéo commentée (horizontal) pour tout le montage : pause, passages et ouverture au même
    endroit, à la même taille."""
    from . import config as C
    if orient == "h":
        C.GEOM["h"].update({k: dict(v) for k, v in GEOM_H.items()})


def zone_video(orient: str, clip_wh: tuple, side: str = "left") -> tuple:
    """(x, y, w, h) de la vidéo DANS la zone média — exactement le calcul du rendu d'un passage joué (render.py)."""
    from . import config as C
    W, H = (1920, 1080) if orient == "h" else (1080, 1920)
    pw, ph = C.GEOM[orient][side]["panel"][2:]
    cw_, ch_ = clip_wh if clip_wh and clip_wh[0] and clip_wh[1] else (16, 9)
    if orient == "h":
        vw, vh = pw // 2 * 2, int(pw * H / W) // 2 * 2
    elif cw_ > ch_ * 1.2:
        vw, vh = pw // 2 * 2, min(ph, int(pw * ch_ / cw_)) // 2 * 2
    else:
        vw, vh = pw // 2 * 2, ph // 2 * 2
    return (pw - vw) // 2, (ph - vh) // 2, vw, vh


def panneau_pause(x_path: str, passage: dict, video_label: str, orient: str, work: Path, n: int,
                  clip_wh: tuple = (16, 9), titre: str | None = None) -> dict:
    """Vidéo commentée EN PAUSE, exactement à la place (et à la taille) où le passage va jouer : l'image du passage qui
    suit (lent zoom, jamais figée), assombrie, et en bas un bandeau « EN PAUSE · À SUIVRE » + titre.
    Même format que les cartes (render_panel) : {"frame", "photo", "hole", "size"}."""
    import subprocess
    from PIL import Image, ImageDraw, ImageEnhance
    from . import config as C
    from .panels import _font, fit, draw_lines, shadow
    d = work / "commentaire"
    d.mkdir(parents=True, exist_ok=True)
    P = C.SHADOW_PAD
    pw, ph = C.GEOM[orient]["left"]["panel"][2:]
    hx, hy, vw, vh = zone_video(orient, clip_wh)
    # image du passage (0,6 s après son début : jamais un fondu au noir ni une image de transition)
    img_p = d / f"pause_src_{n}.jpg"
    t = float(passage.get("start") or 0) + 0.6
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", x_path, "-frames:v", "1", str(img_p)],
                   check=True, timeout=120)
    from .panels import _cover
    ph_img = _cover(Image.open(img_p), vw, vh, 0.5)
    ph_img = ImageEnhance.Brightness(ph_img).enhance(0.78)
    photo = d / f"pause_photo_{n}.png"
    ph_img.save(photo)
    # cadre : ombre + filet crème autour de la vidéo, fenêtre transparente, ⏸ et bandeau du titre par-dessus
    fr = Image.new("RGBA", (pw + 2 * P, ph + 2 * P), (0, 0, 0, 0))
    fr.alpha_composite(shadow(vw, vh, C.CARD_RADIUS, strength=170), (hx, hy))
    a = fr.getchannel("A")
    ImageDraw.Draw(a).rounded_rectangle((P + hx, P + hy, P + hx + vw - 1, P + hy + vh - 1), C.CARD_RADIUS, fill=0)
    fr.putalpha(a)
    ov = Image.new("RGBA", (vw, vh), (0, 0, 0, 0))
    dr = ImageDraw.Draw(ov)
    # bandeau du bas (dégradé bleu nuit) : « EN PAUSE · À SUIVRE » + titre du passage
    band = int(vh * 0.30)
    for k in range(band):
        al = int(235 * min(1.0, (k / band) * 1.6))
        dr.line((0, vh - band + k, vw, vh - band + k), fill=C.NAVY_DEEP + (al,))
    tit = (titre if titre is not None else str(passage.get("titre") or "")).strip()
    m = int(vw * 0.05)
    fk = _font("sans", max(18, int(vh * 0.045)), True)
    ky = vh - band + int(band * 0.22)
    # ⏸ en petit devant le mot (dessiné : aucune police n'a besoin d'avoir le symbole)
    bh_k = int(fk.size * 0.8)
    for dx in (0, int(bh_k * 0.55)):
        dr.rectangle((m + dx, ky + 3, m + dx + max(3, bh_k // 4), ky + 3 + bh_k), fill=C.GOLD_HI + (255,))
    kick = "EN PAUSE · À SUIVRE" if tit else "EN PAUSE"
    dr.text((m + int(bh_k * 1.35), ky), kick, font=fk, fill=C.GOLD_HI + (255,))
    if tit:
        f, lines, size = fit(dr, tit, "serif", vw - 2 * m, int(band * 0.50), int(vh * 0.085), int(vh * 0.05), 2, 1.08)
        draw_lines(dr, lines, f, size, (m, ky + int(fk.size * 1.45), vw - 2 * m, int(band * 0.52)), C.CREAM,
                   spacing=1.08)
    # (pas de grand ⏸ au centre : il cacherait le visage de la personne à l'écran)
    mk = Image.new("L", (vw, vh), 0)
    ImageDraw.Draw(mk).rounded_rectangle((0, 0, vw - 1, vh - 1), C.CARD_RADIUS, fill=255)
    ov.putalpha(Image.composite(ov.getchannel("A"), Image.new("L", (vw, vh), 0), mk))
    ImageDraw.Draw(ov).rounded_rectangle((1, 1, vw - 2, vh - 2), C.CARD_RADIUS, outline=C.CREAM + (235,), width=4)
    fr.alpha_composite(ov, (P + hx, P + hy))
    frame = d / f"pause_frame_{n}.png"
    fr.save(frame)
    return {"frame": str(frame), "photo": str(photo), "hole": (P + hx, P + hy, vw, vh), "size": fr.size,
            "label": tit}


def permanent(segs: list, panels: list) -> int:
    """Chaque plan où tu parles seul devient « toi + la vidéo commentée en pause » (le passage qui va suivre).
    panels : [(instant de sortie de l'extrait, carte)] dans l'ordre. Renvoie le nombre de plans convertis."""
    if not panels:
        return 0
    n = 0
    for k, s in enumerate(segs):
        if s.kind != "full":
            continue
        nxt = next((x for x in segs[k + 1:] if x.kind == "insert" and x.insert.get("commentaire")), None)
        asset = (nxt.insert["asset"].get("_pause_panel") if nxt else None) or panels[-1]
        s.kind, s.side = "split", "left"
        tit = (nxt.insert["asset"].get("pause_titre") if nxt else "") or ""
        s.panel = {"v": {"asset": asset, "kind": "commentaire", "label": tit}, "side": "left", "persistent": True}
        n += 1
    # continuité : entre deux plans « en pause » qui se suivent, ni glissement de la carte ni fondu de ton cadre
    for k, s in enumerate(segs):
        if s.kind == "split" and s.panel and s.panel.get("persistent"):
            p = segs[k - 1] if k else None
            q = segs[k + 1] if k + 1 < len(segs) else None
            s.panel["cont_in"] = bool(p and p.kind == "split" and p.panel and p.panel.get("persistent")
                                      and p.panel["v"]["asset"] is s.panel["v"]["asset"])
            s.panel["cont_out"] = bool(q and q.kind == "split" and q.panel and q.panel.get("persistent")
                                       and q.panel["v"]["asset"] is s.panel["v"]["asset"])
            s.panel["after_insert"] = bool(p and p.kind == "insert")
            s.panel["before_insert"] = bool(q and q.kind == "insert")
    return n
