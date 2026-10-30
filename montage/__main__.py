"""Montage LV final — chaîne complète.

    python -m montage --video input/video.mp4 --attachments input/attachments --notes input/notes.txt --out output

Étapes : transcription → lecture des pièces jointes → plan éditorial (IA) → médias (photos libres, presse, extraits)
→ ligne de temps → textes à l'écran → rendu → PLAN.md (quoi / où / quand)."""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

from . import config as C
from .ai import AI
from .ass import ASS
from .assets import (choose_bounds, clip_insert, is_youtube, quote_card_insert, describe_attachments, list_attachments, og_image, prepare_insert,
                     press_clip, press_search, thumbnail, wiki_image)
from .finder import load_lot, social_clips
from .finder import match as finder_match
from .media import face_center
from .panels import open_image, render_panel
from .plan import ask
from .render import Ctx, build_audio, extract_main_audio, mux, render_video
from .timeline import keep_ranges, out_time, schedule
from .transcribe import sentences, transcribe
from .util import norm, probe, save_json, tc

log = logging.getLogger("montage")


def options(path: str | None) -> dict:
    o = dict(C.DEFAULTS)
    if path and Path(path).exists():
        try:
            o.update({k: str(v).strip().lower() for k, v in json.loads(Path(path).read_text(encoding="utf-8")).items()
                      if str(v).strip() and k in C.DEFAULTS})
        except ValueError:
            pass
    for k in C.DEFAULTS:  # variables d'environnement MONTAGE_<REGLAGE> (formulaire du workflow)
        v = os.environ.get(f"MONTAGE_{k.upper()}", "").strip().lower()
        if v and v not in ("défaut", "defaut", "default"):
            o[k] = v
    # valeurs écrites librement dans la description de la release
    yes = {"oui", "yes", "si", "sì", "true", "1", "on", "نعم"}
    no = {"non", "no", "false", "0", "off", "لا", "aucun", "aucuns", "sans", "désactivé", "desactive", "désactivés", "nessuno"}
    for k in ("sous_titres", "recherche_presse", "images_web", "effets_sonores", "fin", "ouverture_choc", "silences_longs",
              "mots_cles", "rythme", "logo", "mise_en_scene", "voix_studio"):
        o[k] = "non" if o[k] in no else ("oui" if o[k] in yes else C.DEFAULTS[k])
    f = (o.get("finder") or "dernier").strip()
    o["finder"] = "non" if f.lower() in no else ("dernier" if f.lower() in yes | {"dernier", "last", "auto"} else f)
    if o["couper_silences"] not in ("doux", "dynamique", "non"):
        o["couper_silences"] = "non" if o["couper_silences"] in no else C.DEFAULTS["couper_silences"]
    m = re.search(r"\d+", o.get("affirmations") or "")
    o["affirmations"] = "0" if (o.get("affirmations") or "") in no else str(min(30, int(m.group(0)))) if m else "auto"
    o["chaine"] = (o.get("chaine") or "auto").strip() or "auto"
    m = re.search(r"\d+", o.get("max_inserts") or "")
    o["max_inserts"] = m.group(0) if m else "auto"          # auto = dimensionné selon la durée de ta vidéo
    for k in ("duree_max_insert",):
        m = re.search(r"\d+", o[k] or "")
        o[k] = m.group(0) if m else C.DEFAULTS[k]
    o["duree_max_insert"] = str(min(90, max(6, int(o["duree_max_insert"]))))
    names = {"français": "fr", "francais": "fr", "french": "fr", "arabe": "ar", "arabic": "ar", "عربي": "ar",
             "العربية": "ar", "italien": "it", "italiano": "it", "italian": "it", "anglais": "en", "english": "en",
             "espagnol": "es", "español": "es", "allemand": "de", "deutsch": "de"}
    lg = o["langue"]
    o["langue"] = names.get(lg, lg[:2] if re.fullmatch(r"[a-z]{2}(-[a-z]+)?", lg or "") else "auto")
    # 🔒 VERROU : en chaîne (depuis le fond vert, ou Montage lancé à la main avec « chaine_shorts = oui »), la vidéo
    # montée n'a JAMAIS de sous-titres, quel que soit le réglage reçu (les Shorts ont leur propre choix)
    if (os.environ.get("CHAINE_ID") or "").strip() or (os.environ.get("MONTAGE_CHAINE_SHORTS") or "").strip().lower() == "oui":
        if o.get("sous_titres") != "non":
            log.info("Chaîne : sous-titres de la vidéo montée forcés à « non » (verrou)")
        o["sous_titres"] = "non"
    return o


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="montage")
    ap.add_argument("--video", required=True)
    ap.add_argument("--attachments", default="input/attachments")
    ap.add_argument("--notes", default="input/notes.txt")
    ap.add_argument("--options", default="input/options.json")
    ap.add_argument("--cuts", default="input/cuts.json")
    ap.add_argument("--out", default="output")
    ap.add_argument("--work", default="work")
    ap.add_argument("--fonts", default="fonts")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    T0 = time.time()
    src, work, outd = Path(a.video), Path(a.work), Path(a.out)
    work.mkdir(parents=True, exist_ok=True)
    outd.mkdir(parents=True, exist_ok=True)
    opts = options(a.options)
    notes = Path(a.notes).read_text(encoding="utf-8").strip() if Path(a.notes).exists() else ""
    info = probe(src)
    if not info["video"] or info["duration"] < 1:
        raise SystemExit("La vidéo déposée est illisible.")
    orient = "v" if info["h"] > info["w"] * 1.05 else "h"
    log.info("Vidéo : %dx%d, %.0f s, %s", info["w"], info["h"], info["duration"], "verticale" if orient == "v" else "horizontale")
    # vidéo 4K / 60 i/s / HDR : copie de travail légère pour l'image (le son vient toujours de l'original)
    from .media import make_proxy
    vsrc, vinfo = make_proxy(src, info, work)

    # 1) transcription
    want_lang = opts["langue"] if opts["langue"] not in ("", "auto") else None
    tr = transcribe(src, work, want_lang, tag="main") if info["audio"] else {"lang": want_lang or "fr", "words": [],
                                                                               "silences": []}
    lang = (want_lang or tr.get("lang") or "fr")[:2]
    words = tr["words"]
    # silences : détection adaptative (bruit de fond réel de ta pièce) + réparation des mots « étirés »
    quiet = []
    if info["audio"] and words:
        from .pauses import drop_phantoms, quiet_intervals, repair_words
        quiet = quiet_intervals(src, work)
        drop_phantoms(words, quiet)       # mots inventés par la transcription pendant un silence
        nfix = repair_words(words, quiet)
        if nfix:
            log.info("Silences : %d mot(s) à l'horodatage étiré corrigé(s)", nfix)
    sents = sentences(words)
    log.info("Transcription : %d mots, %d phrases, langue %s", len(words), len(sents), lang)

    # 1b) chaîne : logo, nom, couleurs de l'habillage (dossier chaines/) — jamais bloquant
    brand = {"notes": []}
    chaine_why = ""
    try:
        from . import chaine as K
        prof, chaine_why = K.choose(opts.get("chaine", "auto"), lang)
        brand = K.prepare(prof, orient, work / "chaine") if opts.get("logo") != "non" else {"notes": [], "nom": ""}
        brand["notes"] += K.apply_palette(prof, brand)
        brand["profil"] = prof
        log.info("Chaîne : %s%s", chaine_why, " · " + " ; ".join(brand["notes"]) if brand["notes"] else "")
    except Exception as e:  # noqa: BLE001
        brand = {"notes": [f"⚠ habillage de chaîne abandonné ({type(e).__name__}: {e}) : montage sans logo"]}
        log.warning("%s", brand["notes"][0])

    # 2) pièces jointes + plan éditorial
    ai = AI()
    att = list_attachments(Path(a.attachments))
    cuts = {}
    try:  # passages imposés : « discours.mp4 = 1:20-1:45 » dans la description
        cuts = {k.lower(): v for k, v in json.loads(Path(a.cuts).read_text(encoding="utf-8")).items()}
    except (OSError, ValueError):
        pass
    for x in att:
        nm = re.sub(r"^\d{2}_", "", x["name"]).lower()
        c = cuts.get(nm) or next((v for k, v in cuts.items() if Path(k).stem == Path(nm).stem), None)
        if c and x["kind"] == "video":
            x["cut"] = c
    describe_attachments(att, ai, work, lang)
    log.info("Pièces jointes : %d image(s), %d vidéo(s)", sum(x["kind"] == "image" for x in att),
             sum(x["kind"] == "video" for x in att))
    forced = os.environ.get("MONTAGE_PLAN_FILE")  # plan fourni à la main (tests, ou plan retouché)
    if forced and Path(forced).exists() and sents:
        from .plan import clean
        plan = clean(json.loads(Path(forced).read_text(encoding="utf-8")), sents, att)
    else:
        # limites dimensionnées sur la durée (règle du rythme), jamais un chiffre fixe
        from .cadence import rule_count
        speech_s = (sents[-1]["t1"] - sents[0]["t0"]) if sents else info["duration"]
        n_rule = rule_count(speech_s)
        n_vids = max(1, sum(1 for x in att if x["kind"] == "video"))
        opts["_n_rule"] = n_rule
        opts["_per_video"] = max(3, -(-n_rule // n_vids) + 2)    # passages possibles par vidéo jointe
        log.info("Rythme : %d élément(s) attendus pour %s de parole → jusqu'à %d passage(s) par vidéo jointe",
                 n_rule, tc(speech_s), opts["_per_video"])
        plan = ask(ai, lang, sents, att, notes, opts) if sents else {"visuals": [], "inserts": [], "press": [], "chapters": [],
                                                                     "emphasis": {}, "hook": "", "outro": ""}
    save_json(work / "plan_ia.json", plan)
    log.info("Plan : %d visuel(s), %d vidéo(s) jointe(s), %d recherche(s) presse, %d chapitre(s)", len(plan["visuals"]),
             len(plan["inserts"]), len(plan["press"]), len(plan["chapters"]))

    # 3) médias
    pw, ph = C.GEOM[orient]["left"]["panel"][2:]
    pdir = work / "panels"
    by_id = {x["id"]: x for x in att}
    for n, v in enumerate(plan["visuals"]):
        data = {"label": v.get("label", ""), "sublabel": v.get("sublabel", ""), "text": v.get("text", "")}
        kind = v["kind"]
        try:
            if kind == "attachment":
                x = by_id[v["attachment"]]
                data["image"] = open_image(x["path"])
                data["label"] = data["label"] or x.get("label", "") or _pretty(x["name"])
                v["label"] = data["label"]
                data["contain"] = x.get("contain")
                v["source"] = f"pièce jointe « {x['name']} »"
            elif kind in ("person", "place", "thing", "event"):
                if opts["images_web"] == "non":
                    continue
                wl = [v.get("wiki_lang") or lang, lang]
                img = wiki_image(v["query"], wl, work / "web" / f"wiki_{n}")
                if not img:
                    log.info("  pas de photo libre pour « %s »", v["query"])
                    continue
                data["image"] = open_image(img["path"])
                data["credit"] = f"{C.ui(lang, 'photo')} : {img['credit']}"
                v["source"] = f"Wikimedia Commons — {img['title']} ({img['credit']})"
            if kind not in ("figure", "quote") and data.get("image") is None:
                continue
            v["asset"] = render_panel(kind, pw, ph, data, pdir, f"v{n:02d}")
        except Exception as e:  # noqa: BLE001
            log.warning("visuel %d (%s) abandonné : %s", n, kind, e)

    # 4) extraits vidéo insérés pendant tes silences
    maxd = float(opts["duree_max_insert"] or 25)
    from .cadence import rule_count as _rc
    n_rule = opts.get("_n_rule") or _rc((sents[-1]["t1"] - sents[0]["t0"]) if sents else info["duration"])
    max_ins = int(opts["max_inserts"]) if str(opts["max_inserts"]).isdigit() else n_rule
    cap_att = n_rule + 4          # passages de TES vidéos jointes (en plus : « écoutez ça », rythme)
    inserts = []
    from .cadence import clashes, passage_label
    used: dict = {}   # passages déjà pris par vidéo jointe : {id: [(début, fin), …]} — jamais deux fois le même

    def label_for(x, a0_, b0_):
        return passage_label(ai, x, a0_, b0_, lang, work, x.get("label") or _pretty(x["name"]))

    # 4·0) ouverture choc : choisie en premier, son passage n'est plus réutilisé ensuite
    opener = None
    if opts.get("ouverture_choc") == "oui":
        opener = pick_opener(ai, att, lang, orient, work, plan.get("hook", ""), label_for)
        if opener is None:
            log.info("Ouverture choc : aucune vidéo jointe → une vidéo trouvée par la recherche sera essayée")
        else:
            used.setdefault(opener["attachment"], []).append(opener["clip"])
    for k, ins in enumerate(plan["inserts"]):
        x = by_id.get(ins["attachment"])
        if not x or len(inserts) >= cap_att:  # dimensionné selon la durée (tes vidéos passent avant la presse)
            continue
        s_ = x.get("sentences") or []
        want0 = ins.get("clip_start") or 0.0
        want1 = ins.get("clip_end") or 0.0
        if x.get("cut"):  # passage imposé par toi : appliqué à la lettre
            a0, b0 = max(0.0, x["cut"][0]), min(x["duration"], x["cut"][1])
            if b0 - a0 < 1:
                log.warning("passage imposé hors de la vidéo %s (%.0f s) : ignoré", x["name"], x["duration"])
                a0, b0 = choose_bounds(s_, want0, want1 if want1 > want0 else x["duration"], maxd, x["duration"])
        else:
            if want1 > want0 and want1 - want0 < 6:   # extrait trop court pour être compris : au moins ~6 s
                want1 = want0 + 12
            a0, b0 = choose_bounds(s_, want0, want1 if want1 > want0 else x["duration"], maxd, x["duration"])
        if clashes((a0, b0), used.get(x["id"], [])):
            # même passage que l'ouverture choc ou qu'un extrait précédent : on prend la suite de la vidéo, sinon rien
            nxt = max(u1 for u0, u1 in used[x["id"]] if min(u1, b0) - max(u0, a0) > 0)
            if x.get("cut") or nxt > x["duration"] - 4:
                log.info("extrait « %s » %.0f-%.0f s ignoré : passage déjà utilisé", x["name"], a0, b0)
                continue
            a0, b0 = choose_bounds(s_, nxt + 0.2, nxt + 0.2 + max(8.0, b0 - a0), maxd, x["duration"])
            if clashes((a0, b0), used.get(x["id"], [])):
                log.info("extrait « %s » ignoré : passage déjà utilisé", x["name"])
                continue
        asset = prepare_insert(Path(x["path"]), a0, b0, orient, work, f"insert_att{k}", lang, ai, s_ if s_ else None,
                               x.get("lang"))
        if asset:
            asset["credit"] = {"label": label_for(x, a0, b0)}
            asset["source"] = f"pièce jointe « {x['name']} » ({tc(a0)} → {tc(b0)})"
            inserts.append({"after": ins["after"], "asset": asset, "attachment": x["id"], "clip": (a0, b0)})
            used.setdefault(x["id"], []).append((a0, b0))
    # 4a) mots-clés « écoutez ça… » : un passage de ta vidéo jointe juste après chaque annonce
    kw_info = None
    if opts.get("mots_cles") == "oui" and words:
        kw_info = keyword_inserts(ai, words, sents, att, inserts, tr, quiet, orient, work, lang, maxd,
                                  avoid=[(opener["attachment"], *opener["clip"])] if opener else [],
                                  label_for=label_for)
        for i in inserts:
            if i.get("kw") is not None:
                used.setdefault(i["attachment"], []).append(i["clip"])
    # 4b) résultats de Vid-o-presse-finder (dernier lot) placés selon ce que tu dis
    lot_info = None
    finder_used = False
    spare_articles: list = []   # articles / messages trouvés mais pas encore affichés (réserve pour le rythme)
    pool_clips: list = []       # déclarations vidéo trouvées (lot Finder + recherches) : repli des « écoutez ça »
    if opts.get("finder", "dernier") != "non" and sents:
        try:
            lot = load_lot(Path(os.environ.get("VPF_DIR", "vpf")), opts.get("finder", "dernier"))
        except Exception as e:  # noqa: BLE001
            log.warning("lecture des résultats Vid-o-presse-finder impossible : %s", e)
            lot = None
        if lot:
            m = finder_match(ai, sents, lot, lang, max_ins)
            lot_info = {"lot": lot["lot"], "age": lot["age_days"], "clips": len(lot["clips"]),
                        "articles": len(lot["articles"]), "placed": m, "video_ok": 0, "cards": 0,
                        "origine": lot.get("origine") or {}}
            used = set()
            uses = {}
            for x in m["inserts"]:
                uses[x["clip"]] = uses.get(x["clip"], 0) + 1
            seen_part = {}
            for k, x in enumerate(m["inserts"]):
                c = dict(lot["clips"][x["clip"]])
                n_parts = uses[x["clip"]]
                if n_parts > 1:  # déclaration utilisée en plusieurs morceaux : chacun sa portion, dans l'ordre
                    part = seen_part.get(x["clip"], 0)
                    seen_part[x["clip"]] = part + 1
                    a_, b_ = float(c.get("in", c.get("start", 0))), float(c.get("out", c.get("end", 0)))
                    step = (b_ - a_) / n_parts
                    c["in"] = c["start"] = a_ + part * step
                    c["out"] = c["end"] = a_ + (part + 1) * step
                asset = clip_insert([c], orient, work, f"finder{k}", lang, ai, maxd, used)
                if asset:
                    cr = asset["credit"]
                    asset["source"] = f"Vid-o-presse-finder ({lot['lot']}) — {cr.get('title')} — {cr.get('source')} ({cr.get('url')})"
                    inserts.append({"after": x["after"], "asset": asset})
                    lot_info["video_ok"] += 1
                    continue
                # vidéo indisponible : la déclaration apparaît quand même, en carte à côté de toi
                quote = x.get("quote") or c.get("quote") or ""
                ws = quote.split()
                quote = " ".join(ws[:32]) + ("…" if len(ws) > 32 else "")
                img = thumbnail(c, work / "web" / f"thumb_{k}")
                sub_ = " · ".join(z for z in (c.get("channel") or c.get("platform") or "", _fmt_date(c.get("uploaded", ""))) if z)
                v = {"kind": "statement", "s0": x["s0"], "s1": min(x["after"], x["s0"] + 2), "trigger": "", "priority": 1,
                     "label": c.get("speaker") or "", "text": quote,
                     "source": f"Vid-o-presse-finder ({lot['lot']}) — vidéo non téléchargeable, carte déclaration — "
                               f"{c.get('title')} ({c.get('source_url')})"}
                try:
                    v["asset"] = render_panel("statement", pw, ph, {"text": quote, "label": v["label"], "sublabel": sub_,
                                                                    "image": open_image(img) if img else None},
                                              pdir, f"stmt{k}")
                    plan["visuals"].append(v)
                    lot_info["cards"] += 1
                except Exception as e:  # noqa: BLE001
                    log.warning("carte déclaration abandonnée : %s", e)
            for k, x in enumerate(m["articles"]):
                art = lot["articles"][x["article"]]
                img = og_image(art.get("url", ""), work / "web" / f"ogf_{k}")
                data = {"source": art.get("source") or art.get("domaine", ""), "date": _fmt_date(art.get("date", "")),
                        "headline": x.get("headline") or art["titre"], "domain": art.get("domaine", ""),
                        "image": open_image(img) if img else None}
                v = {"kind": "article", "s0": x["s0"], "s1": x["s0"], "trigger": "", "priority": 1,
                     "label": data["headline"][:60], "source": f"Vid-o-presse-finder ({lot['lot']}) — {art.get('source')} — {art.get('url')}"}
                try:
                    v["asset"] = render_panel("article", pw, ph, data, pdir, f"artf{k}")
                    plan["visuals"].append(v)
                except Exception as e:  # noqa: BLE001
                    log.warning("carte article abandonnée : %s", e)
            finder_used = bool(m["inserts"] or m["articles"])
            lot_info["contre"] = lot.get("contre") or []
            pool_clips += list(lot.get("clips") or [])
            placed_a = {x["article"] for x in m["articles"]}
            spare_articles += [a_ for k_, a_ in enumerate(lot["articles"]) if k_ not in placed_a]
            log.info("Vid-o-presse-finder : %d extrait(s) vidéo inséré(s), %d carte(s) déclaration, %d article(s)",
                     lot_info["video_ok"], lot_info["cards"], len(m["articles"]))
    # 4c) recherche PAR AFFIRMATION : chaque affirmation vérifiable de ta vidéo est cherchée (vidéos, presse, Telegram,
    #     Reddit), en plus du lot Finder ; ce qui la contredit est listé à part dans PLAN.md (à anticiper)
    press_info = None
    if opts["recherche_presse"] != "non" and plan["press"]:
        press_info = claim_searches(plan, lot_info, inserts, orient, work, lang, ai, maxd, max_ins, pw, ph, pdir,
                                    len(plan["press"]), len(sents), info["duration"])
        spare_articles += press_info.get("spare") or []
        pool_clips += press_info.get("clips_pool") or []
        ai.save_quota()
    # 4c-bis) « écoutez ça » sans passage de tes vidéos : extrait trouvé par le Finder / la presse, s'il correspond
    if kw_info and pool_clips:
        try:
            kw_press_fallback(ai, words, sents, kw_info, inserts, pool_clips, orient, work, lang, maxd)
        except Exception as e:  # noqa: BLE001 - un repli raté ne bloque jamais le montage
            log.warning("repli « écoutez ça » par la presse abandonné : %s", e)
    # 4c-ter) ouverture choc SANS vidéo jointe : la déclaration la plus forte parmi les vidéos trouvées
    #         (dernier lot Finder + recherche selon ta vidéo). Rien de solide → la vidéo commence normalement.
    if opts.get("ouverture_choc") == "oui" and opener is None:
        try:
            opener, plan["_opener_note"] = pick_found_opener(ai, pool_clips, inserts, lang, orient, work,
                                                             plan.get("hook", "") or plan.get("title", ""))
        except Exception as e:  # noqa: BLE001 - jamais bloquant
            opener, plan["_opener_note"] = None, f"pas d'ouverture choc (erreur : {type(e).__name__})"
            log.warning("ouverture choc par une vidéo trouvée abandonnée : %s", e)
    elif opts.get("ouverture_choc") == "oui":
        plan["_opener_note"] = "ouverture choc : ta vidéo jointe"
    # limite : seulement les extraits de presse / Finder ; tes vidéos jointes et les mots-clés passent toujours
    mine_ins = [i for i in inserts if i.get("attachment") or i.get("kw") is not None]
    other = [i for i in inserts if not (i.get("attachment") or i.get("kw") is not None)]
    if len(other) > max_ins:
        log.info("Extraits de presse : %d trouvés, %d gardés (max_inserts)", len(other), max_ins)
    inserts = mine_ins + other[:max_ins]

    # 4d) rythme (rétention) : 5 premières minutes → un extrait au moins toutes les 60 s ; ensuite toutes les 2 min
    from .pauses import merge
    sil_all = merge(tr.get("silences") or [], quiet)
    rythme_info = None
    if opts.get("rythme") == "oui" and words:
        from .cadence import fill, fill_cards, thin, visual_time

        def _prep(x, a_, b_, name):
            s2 = x.get("sentences") or []
            asset_ = prepare_insert(Path(x["path"]), a_, b_, orient, work, name, lang, ai, s2 if s2 else None, x.get("lang"))
            if asset_:
                asset_["credit"] = {"label": label_for(x, a_, b_)}
            return asset_

        def _visual(kind_, src_, query_, s_):
            """Article / photo jointe / photo libre pour le rythme → visuel prêt (panneau rendu) ou None."""
            k_ = len(plan["visuals"])
            if kind_ == "article":
                img_ = og_image(src_.get("url", ""), work / "web" / f"og_r{k_}")
                data_ = {"source": src_.get("source") or src_.get("domaine", ""), "date": _fmt_date(src_.get("date", "")),
                         "headline": src_["titre"], "domain": src_.get("domaine", ""),
                         "image": open_image(img_) if img_ else None}
                return {"kind": "article", "s0": s_, "s1": s_, "trigger": "", "priority": 2, "label": src_["titre"][:60],
                        "source": f"{src_.get('source')} — {src_.get('url')}",
                        "asset": render_panel("article", pw, ph, data_, pdir, f"artr{k_}")}
            if kind_ == "photo":
                lab_ = src_.get("label") or _pretty(src_["name"])
                data_ = {"label": lab_, "sublabel": "", "text": "", "image": open_image(src_["path"]),
                         "contain": src_.get("contain")}
                if data_["image"] is None:
                    return None
                return {"kind": "attachment", "attachment": src_["id"], "s0": s_, "s1": s_, "trigger": "", "priority": 1,
                        "label": lab_, "source": f"pièce jointe « {src_['name']} »",
                        "asset": render_panel("attachment", pw, ph, data_, pdir, f"attr{k_}")}
            img_ = wiki_image(query_, [lang, "en"], work / "web" / f"wiki_r{k_}")
            if not img_:
                return None
            data_ = {"label": query_, "sublabel": "", "text": "", "image": open_image(img_["path"]),
                     "credit": f"{C.ui(lang, 'photo')} : {img_['credit']}"}
            return {"kind": "thing", "query": query_, "s0": s_, "s1": s_, "trigger": "", "priority": 2, "label": query_,
                    "source": f"Wikimedia Commons — {img_['title']} ({img_['credit']})",
                    "asset": render_panel("thing", pw, ph, data_, pdir, f"wikir{k_}")}
        others = [t_ for t_ in (visual_time(v_, sents) for v_ in plan["visuals"] if v_.get("asset")) if t_ is not None]
        try:   # 1) passages de tes vidéos jointes
            rythme_info = fill(ai, words, sents, att, inserts, used, sil_all, lang, orient, work, bool(opener), _prep,
                               others=others)
        except Exception as e:  # noqa: BLE001 - le rythme est un bonus : jamais bloquant
            log.warning("rythme (extraits) abandonné : %s", e)
            rythme_info = {"added": [], "holes": [], "cards": [], "thinned": [], "rule": "rythme",
                           "why": f"erreur interne ({type(e).__name__}) — montage fait sans"}
        used_ph = {v_.get("attachment") for v_ in plan["visuals"]}
        pool = {"articles": [x_ for x_ in spare_articles if x_.get("titre") and x_.get("url")],
                "photos": [x_ for x_ in att if x_["kind"] == "image" and x_["id"] not in used_ph]}
        try:   # 2) puis articles, 3) puis photos
            fill_cards(ai, words, sents, inserts, plan["visuals"], sil_all, lang, bool(opener), pool, _visual,
                       rythme_info, wiki=opts["images_web"] != "non")
        except Exception as e:  # noqa: BLE001
            log.warning("rythme (articles / photos) abandonné : %s", e)
        try:   # après 5 min : pas d'ajout automatique à moins de 1 min 30 du précédent
            thin(inserts, plan["visuals"], words, sents, sil_all, rythme_info)
        except Exception as e:  # noqa: BLE001
            log.warning("régularité du rythme non appliquée : %s", e)

    # 5) ligne de temps
    from .media import black_start
    b0 = black_start(vsrc)
    if b0 > 0:
        log.info("Images noires au début de ta vidéo (%.2f s) : retirées", b0)
    long_gap = 2.0 if opts.get("silences_longs") == "oui" else None
    voice_free = None
    if info["audio"] and words:
        try:
            from .pauses import voice_free_fn
            voice_free = voice_free_fn(src, work, words)
        except Exception as e:  # noqa: BLE001
            log.warning("mesure du niveau de ta voix impossible : %s", e)
    keep = keep_ranges(words, sil_all, info["duration"], opts["couper_silences"], b0, long_gap=long_gap,
                       voice_free=voice_free)
    energy, voice_info = None, None
    if opts.get("mise_en_scene") != "non" and info["audio"] and sents:
        from .voix import analyse
        energy, why = analyse(src, work, words, sents)
        voice_info = {"why": why, "on": energy is not None}
        log.info("Mise en scène : %s", why)
    zstats: dict = {}
    segs, chosen = schedule(words, sents, keep, plan["visuals"], inserts, plan["chapters"], info["duration"], opts, orient,
                            opener=opener, sil=sil_all, voice_free=voice_free, energy=energy, stats=zstats)
    if voice_info is not None:
        voice_info["stats"] = zstats
    if kw_info:  # mots-clés : extrait réellement placé ? (sinon la raison est notée)
        placed = {s.insert.get("kw"): s for s in segs if s.kind == "insert" and s.insert.get("kw") is not None}
        for it in kw_info["items"]:
            if it["inserted"] and it["n"] not in placed:
                it["inserted"] = False
                it["why"] = "point d'insertion refusé au montage (aucun silence sûr)"
            elif it["inserted"]:
                it["out"] = placed[it["n"]].out0
    pause_stats = None
    if long_gap:
        try:
            from .pauses import cut_effects
            pause_stats = cut_effects(segs, vsrc, keep)
        except Exception as e:  # noqa: BLE001 - un effet en échec ne doit jamais bloquer le montage (coupe nette)
            log.warning("effets de coupe abandonnés (coupes nettes) : %s", e)
    if not segs:
        raise SystemExit("Rien à monter (vidéo vide ?)")
    total = segs[-1].out0 + segs[-1].dur
    log.info("Ligne de temps : %d segments, %.0f s → %.0f s ; extraits prévus %d, insérés %d", len(segs), info["duration"],
             total, len(inserts), sum(1 for s in segs if s.kind == "insert" and not s.insert.get("opener")))

    # 6) textes à l'écran
    face = face_center(vsrc)
    log.info("Visage : %s (%.2f, %.2f)", "trouvé" if face["found"] else "non trouvé (cadrage centré)", face["cx"], face["cy"])
    sub = ASS(orient, lang, face)
    h0 = (segs[0].dur + 0.25) if opener and segs and segs[0].kind == "insert" else 0.25
    hook_end = h0 + 4.2 if plan.get("hook") else 0.0
    if plan.get("hook"):
        sub.hook(plan["hook"], h0, hook_end)
    chap_times = []
    for i, c in enumerate(plan["chapters"]):
        t = out_time(segs, sents[c["s"]]["t0"]) if c["s"] < len(sents) else None
        # le 1er chapitre est couvert par l'accroche ; jamais deux textes en même temps
        if t is None or i == 0 or c["s"] <= (sents[0]["i"] if sents else 0) or t < h0 + 1.0 or t > total - 12:
            continue
        if t < hook_end + 0.4:
            t = hook_end + 0.4
        if chap_times and t < chap_times[-1] + 6.5:
            continue
        # la carte reste 5 s, mais s'efface avant l'extrait suivant (jamais deux bandeaux l'un sur l'autre)
        nxt = min([x.out0 for x in segs if x.kind == "insert" and x.out0 > t] + [t + 99])
        dur = min(5.0, nxt - t - 0.25)
        if dur < 2.6:
            continue
        sub.chapter(t, i + 1, c["title"], dur=dur)
        chap_times.append(t)
    for s in segs:
        if s.kind == "insert":
            sub.insert(s.out0, s.dur, s.insert["asset"], subtitles=opts["sous_titres"] != "non")
    if opts["sous_titres"] != "non":
        emph = {norm(w) for ws in plan.get("emphasis", {}).values() for w in ws for w in [w] if norm(w)}
        emph = {x for w in emph for x in w.split() if len(x) > 2}
        sub.captions(words, segs, emph)
    if opts["fin"] != "non":
        sub.outro(total, plan.get("outro") or C.ui(lang, "outro"), C.ui(lang, "sub"),
                  logo=bool(brand.get("end_src")) and orient == "h")
        try:
            from .chaine import end_card
            end_card(brand, getattr(sub, "outro_box", None), C.SIZE[orient][0], work / "chaine")
        except Exception as e:  # noqa: BLE001
            brand["notes"].append(f"grand logo de fin omis ({e})")
    ass_path = (work / "textes.ass").resolve()
    ass_path.write_text(sub.text(), encoding="utf-8")

    # 7) rendu
    fonts = Path(a.fonts).resolve() if Path(a.fonts).is_dir() else None
    ctx = Ctx(Path(vsrc).resolve(), vinfo, face, orient, work.resolve(), ass_path, fonts)
    from . import render as R
    R.BRAND = brand_check(brand, work / "chaine")
    R.BRAND_FAILS.clear()
    vid = render_video(segs, ctx, work / "video.mp4", workers=int(os.environ.get("MONTAGE_WORKERS", "2")))
    main_wav = extract_main_audio(src, info, work / "main.wav")
    audio_note = ""
    if opts.get("voix_studio") == "oui" and info["audio"]:
        from .voix_studio import apply as studio
        main_wav, audio_note = studio(src, main_wav, work)
        log.info("Voix : %s", audio_note)
    aud = build_audio(segs, main_wav, work / "mix.wav", opts["effets_sonores"] != "non", chap_times)
    # « logo incrusté » écrit dans le fichier : Push-overlay (Shorts) n'ajoute alors pas un 2e petit logo
    tagc = ""
    if R.BRAND and R.BRAND.get("bug") and len(R.BRAND_FAILS) < len(segs):
        prof_ = brand.get("profil") or {}
        tagc = f"montage-lv-final;logo={orient}-haut-droite;chaine={prof_.get('code', '')};langue={lang}"
    final = mux(vid, aud, outd / "montage-final.mp4", comment=tagc)
    log.info("Vidéo finale : %s (%.0f s, rendu en %.0f min)", final, total, (time.time() - T0) / 60)

    # 8) contrôle qualité automatique, puis rapport : quoi / où / quand
    try:
        from .qc import check
        qc = check(final, segs, words, ass_path, long_gap=long_gap, kw_info=kw_info,
                   subs_off=opts["sous_titres"] == "non")
    except Exception as e:  # noqa: BLE001
        qc = [(False, f"contrôle qualité impossible : {e}")]
    if opts.get("rythme") == "oui":
        try:
            from .cadence import qc_holes
            hs_ = qc_holes(segs, total, 5.5 if opts["fin"] != "non" else 0.0)
            qc.append((not hs_, "rythme : aucun trou de plus de 2 min 30 après 5 min" if not hs_ else
                       "rythme : " + ", ".join(f"rien entre {tc(a_)} et {tc(b_)}" for a_, b_ in hs_[:6])
                       + " (voir « Rythme » plus bas : pourquoi)"))
        except Exception as e:  # noqa: BLE001
            log.warning("contrôle du rythme impossible : %s", e)
    if R.BRAND_FAILS:
        brand["notes"].append(f"⚠ logo absent sur {len(R.BRAND_FAILS)} passage(s) (rendu refait sans logo pour ne rien perdre)")
    brand["why"] = chaine_why
    write_report(outd, plan, segs, chosen, sents, info, total, lang, opts, att, chap_times, ai, lot_info, qc, pause_stats,
                 kw_info, rythme_info, brand=brand, press_info=press_info, voice_info=voice_info, audio_note=audio_note)
    return 0


def _search_detail(res: dict, soc_clips: list) -> str:
    """Ce que la recherche a vu, source par source (PLAN.md) : plus jamais « rien » sans explication."""
    clips = res.get("clips") or []
    yt = sum(1 for c in clips if is_youtube(c))
    parts = [f"vidéos : {len(clips)} (dont {yt} YouTube)"]
    soc = res.get("social") or {}
    parts.append(f"Telegram : {soc.get('telegram', '—')}")
    parts.append(f"Reddit : {soc.get('reddit', '—')}")
    if soc_clips:
        parts.append(f"{len(soc_clips)} vidéo(s) postée(s) sur Telegram/Reddit")
    parts.append(f"articles retenus : {len(res.get('articles') or [])}")
    if res.get("error"):
        parts.append(f"⚠ {res['error']}")
    return " · ".join(parts)


def claim_searches(plan, lot_info, inserts, orient, work, lang, ai, maxd, max_ins, pw, ph, pdir, n_max: int,
                   n_sents: int = 10 ** 6, src_dur: float = 0.0) -> dict:
    """Une recherche Vid-o-presse-finder par affirmation (2 à la fois, budget total borné). Jamais bloquant :
    chaque affirmation finit avec un statut lisible (trouvé, rien, déjà couvert, temps écoulé, erreur)."""
    from concurrent.futures import ThreadPoolExecutor
    info = {"claims": [], "contre": [], "social": {}}
    placed = (lot_info or {}).get("placed") or {}
    covered = [x.get("after", -9) for x in placed.get("inserts", [])] + [x.get("s0", -9) for x in placed.get("articles", [])]
    todo = []
    for p in plan["press"][:max(0, n_max)]:
        it = {"p": p, "status": "", "video": False, "card": "", "found": (0, 0, 0)}
        info["claims"].append(it)
        if any(abs(p["after"] - c) <= 2 for c in covered):
            it["status"] = "déjà couvert par le lot Vid-o-presse-finder"
            continue
        todo.append(it)
    # budget proportionnel au nombre d'affirmations (3 recherches à la fois, ~12 min chacune), plafonné à 2 h 30
    budget_end = time.time() + min(150, 15 + 5.0 * len(todo)) * 60
    # garde-fou : le job GitHub est coupé net à 340 min (tout serait perdu). On garde toujours le temps du rendu
    # (~1,6 × la durée de la vidéo), du son, du contrôle et de l'envoi (25 min) : les recherches s'adaptent.
    try:
        t0_job = float(os.environ.get("JOB_T0") or 0)
    except ValueError:
        t0_job = 0.0
    if t0_job:
        job_end = t0_job + float(os.environ.get("MONTAGE_JOB_MINUTES", "340")) * 60
        reserve = (1.6 * src_dur / 60 + 25) * 60
        budget_end = min(budget_end, job_end - reserve)
    # téléchargements des extraits (après les recherches) : jamais sur le temps gardé pour finir le montage
    dl_end = (job_end - reserve) if t0_job else budget_end + 40 * 60
    left_min = (budget_end - time.time()) / 60
    if todo and left_min < 8:
        for it in todo:
            it["status"] = "⚠ sautée : vidéo longue, le temps restant est gardé pour finir le montage"
        info["time_note"] = f"recherches sautées ({left_min:.0f} min disponibles) pour que le montage finisse à temps"
        log.warning("Recherche par affirmation sautée : %s", info["time_note"])
        return info
    results = {}
    main_q = Path(os.environ.get("QF_QUOTA_FILE", "state/quota.json"))
    ai.save_quota()               # point de départ commun des recherches parallèles (refusionnées ensuite)
    qfiles = []

    def go(k_it):
        k, it = k_it
        if time.time() > budget_end - 4 * 60:
            return it, None
        left = (budget_end - time.time()) / 60
        qf = work / "press" / f"quota_{k}.json"
        try:
            qf.parent.mkdir(parents=True, exist_ok=True)
            if main_q.exists():
                qf.write_bytes(main_q.read_bytes())
            qfiles.append(qf)
        except OSError:
            qf = None
        return it, press_search(it["p"], lang, work, minutes=max(6.0, min(12.0, left - 3)), quota_file=qf)
    with ThreadPoolExecutor(max_workers=3) as ex:
        for it, res in ex.map(go, enumerate(todo)):
            results[id(it)] = res
    try:   # quotas consommés par chaque recherche → état commun (les clés épuisées ne seront pas réessayées)
        from quote_finder import quota as Q
        merged = Q.merge(main_q, [f for f in qfiles if f.exists()])
        st = Q.state()
        st.data = merged.data
        st.save()
    except Exception as e:  # noqa: BLE001
        log.warning("état des quotas des recherches non fusionné : %s", e)
    used = set()
    for k, it in enumerate(todo):
        p, res = it["p"], results.get(id(it))
        if res is None:
            it["status"] = "⚠ non cherchée : temps gardé pour finir le montage (les plus importantes passent d'abord)"
            continue
        for key, v in (res.get("social") or {}).items():
            if key in ("telegram", "reddit") and (key not in info["social"] or str(v).startswith("⚠")):
                info["social"][key] = v
        arts = sorted(res.get("articles") or [], key=lambda r: -_num(r.get("autorite")))
        posts = res.get("posts") or []
        info["contre"] += [dict(a, claim=p) for a in arts if (a.get("position") or "") == "contre"]
        info["contre"] += [dict(x, claim=p) for x in posts if x.get("position") == "contre"]
        arts = [a for a in arts if (a.get("position") or "") != "contre" and a.get("titre")]
        posts = [x for x in posts if x.get("position") != "contre"]
        soc_clips = social_clips(posts)
        it["found"] = (len(res.get("clips") or []), len(arts), len(posts))
        it["detail"] = _search_detail(res, soc_clips)
        info.setdefault("clips_pool", []).extend((res.get("clips") or []) + soc_clips)
        if res.get("error") and not any(it["found"]):
            it["status"] = f"⚠ {res['error']}"
            continue
        n_other = sum(1 for i in inserts if not (i.get("attachment") or i.get("kw") is not None))
        if time.time() > dl_end and (res.get("clips") or soc_clips):
            it["detail"] += " ; extraits non téléchargés : temps gardé pour finir le montage"
        elif n_other < max_ins and (res.get("clips") or soc_clips):
            asset = press_clip(res, orient, work, k, lang, ai, maxd, used) if res.get("clips") else None
            if not asset and soc_clips:   # YouTube bloqué : vidéo postée sur Telegram / Reddit (téléchargeable)
                asset = clip_insert(soc_clips[:3], orient, work, f"soc{k}", lang, ai, maxd, used)
                if not asset:
                    it["detail"] += " ; vidéos Telegram/Reddit essayées mais non téléchargées"
            elif not asset:
                it["detail"] += " ; extraits vidéo trouvés mais aucun téléchargeable depuis GitHub (YouTube bloque)"
            if asset:
                cr = asset["credit"]
                asset["source"] = f"{cr.get('title')} — {cr.get('source')} ({cr.get('url')})"
                inserts.append({"after": p["after"], "asset": asset})
                it["video"] = True
        # cartes : tous les articles solides (presse d'abord, puis Telegram / Reddit), chacun sur sa propre phrase,
        # à partir du moment où tu en parles ; le placement final écarte ce qui se chevaucherait
        taken_s = {v_.get("s0") for v_ in plan["visuals"]}
        s_free = [x for x in range(max(0, min(p.get("s0", p["after"]), p["after"])), min(n_sents, p["after"] + 4))
                  if x not in taken_s]
        cards_ = (arts + posts)[:min(4, len(s_free))]
        info.setdefault("spare", []).extend((arts + posts)[len(cards_):])
        names = []
        for j_, card in enumerate(cards_):
            s0 = s_free[j_]
            img = og_image(card.get("url", ""), work / "web" / f"og_c{k}_{j_}")
            data = {"source": card.get("source") or card.get("domaine", ""), "date": _fmt_date(card.get("date", "")),
                    "headline": card["titre"], "domain": card.get("domaine", ""), "image": open_image(img) if img else None}
            v = {"kind": "article", "s0": s0, "s1": s0, "trigger": "", "priority": 1,
                 "label": card["titre"][:60], "source": f"{card.get('source')} — {card.get('url')}"}
            try:
                v["asset"] = render_panel("article", pw, ph, data, pdir, f"artc{k}_{j_}")
                plan["visuals"].append(v)
                names.append(card.get("source") or "")
            except Exception as e:  # noqa: BLE001
                log.warning("carte abandonnée : %s", e)
        it["card"] = ", ".join(n_ for n_ in names if n_)
        it["status"] = ("✅ " + " + ".join(x for x in (("extrait vidéo" if it["video"] else ""),
                                                         (f"{len(names)} carte(s) ({it['card']})" if names else "")) if x)
                        if (it["video"] or names) else "rien de solide trouvé")
    log.info("Recherche par affirmation : %d affirmation(s), %d avec un extrait ou une carte, %d élément(s) contraires",
             len(info["claims"]), sum(1 for i in info["claims"] if i["status"].startswith("✅")), len(info["contre"]))
    return info


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def brand_check(brand: dict, work: Path) -> dict | None:
    """Essai éclair du logo avec ffmpeg avant le vrai rendu : s'il échoue, montage sans logo (et c'est écrit)."""
    if not (brand.get("bug") or brand.get("end")):
        return None
    from .util import run
    try:
        work.mkdir(parents=True, exist_ok=True)
        for k in ("bug", "end"):
            if brand.get(k):
                run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=320x240:d=0.2", "-loop", "1", "-t", "0.2", "-i",
                     brand[k], "-filter_complex", "[0:v][1:v]overlay=10:10:format=auto,format=yuv420p[o]", "-map", "[o]",
                     "-frames:v", "2", str(work / f"essai_{k}.mp4")], timeout=60)
        return brand
    except Exception as e:  # noqa: BLE001
        brand["notes"].append(f"⚠ logo refusé par ffmpeg ({str(e)[-160:]}) : montage sans logo")
        return None


def keyword_inserts(ai, words, sents, att, inserts, tr, quiet, orient, work, lang, maxd, avoid=None,
                    label_for=None) -> dict:
    from .keywords import choose, find_occurrences, pause_after
    from .pauses import merge
    occ = find_occurrences(words)
    vids = [x for x in att if x["kind"] == "video"]
    by_id = {x["id"]: x for x in att}
    info = {"items": [], "videos": len(vids)}
    log.info("Mots-clés : %d annonce(s) « écoutez… » trouvée(s), %d vidéo(s) jointe(s)", len(occ), len(vids))
    if not occ:
        return info
    sil = merge(tr.get("silences") or [], quiet)
    # 1) instant d'insertion de chaque annonce (vrai silence juste après)
    real = []
    for o in occ:
        o["at"] = pause_after(words, sil, o["w1"], o.get("wait", 8.0))
        nxt = " ".join(w["w"] for w in words[o["w1"] + 1:o["w1"] + 6])
        if o["at"] is None and o.get("short", o["phrase"].endswith("ça")):
            # « écoutez ça va changer… » : tu continues ta phrase, ce n'est pas une annonce d'extrait
            info.setdefault("ignored", []).append({"t0": o["t0"], "text": f"{o['phrase']} {nxt}"})
            continue
        real.append(o)
    occ = real
    # 2) passage choisi (IA + vérification) uniquement pour les vraies annonces
    picks = {p["n"]: p for p in choose(ai, [o for o in occ if o["at"] is not None], words, vids, lang, maxd,
                                       avoid=avoid or [])} if vids else {}
    idx = [n for n, o in enumerate(occ) if o["at"] is not None]
    picks = {idx[k]: p for k, p in picks.items() if k < len(idx)}
    for n, o in enumerate(occ):
        item = {"n": n, "phrase": o["phrase"], "t0": o["t0"], "t1": o["t1"], "inserted": False}
        info["items"].append(item)
        t = o["at"]
        if t is not None:
            item["pending_t"], item["w1"] = t, o["w1"]      # repli possible : extrait trouvé par le Finder / la presse
        if not vids:
            item["why"] = "aucune vidéo jointe (release ou Drive)"
            continue
        if t is None:
            item["why"] = (f"tu enchaînes sans pause pendant {o.get('wait', 8.0):.0f} s après la phrase : pas d'insertion "
                           f"(pour ne pas te couper)")
            continue
        p = picks.get(n)
        if not p:
            item["why"] = ("aucun passage libre et cohérent dans les vidéos jointes (un passage n'est jamais montré deux "
                           "fois : ajoute plus de vidéos dans montage-joints)")
            continue
        x = by_id[p["video"]]
        asset = prepare_insert(Path(x["path"]), p["a"], p["b"], orient, work, f"insert_kw{n}", lang, ai,
                               x.get("sentences") or None, x.get("lang"))
        if not asset:
            item["why"] = "passage illisible"
            continue
        asset["credit"] = {"label": label_for(x, p["a"], p["b"]) if label_for else (x.get("label") or _pretty(x["name"]))}
        asset["source"] = f"MOT-CLÉ « {o['phrase']} » — pièce jointe « {x['name']} » ({tc(p['a'])} → {tc(p['b'])})"
        s_i = next((s["i"] for s in sents if s["w0"] <= o["w1"] <= s["w1"]), 0)
        inserts.append({"after": s_i, "asset": asset, "attachment": x["id"], "clip": (p["a"], p["b"]), "forced_t": t,
                        "kw": n})
        item.update(inserted=True, at=t, video=x["name"], a=p["a"], b=p["b"], why=p.get("why", ""),
                    check=p.get("check"), confidence=p.get("confidence"))
    # les autres insertions de tes vidéos qui reprendraient le même passage sont retirées (pas de doublon)
    kw = [i for i in inserts if i.get("kw") is not None]
    keep = []
    for i in inserts:
        if i.get("kw") is None and i.get("clip") and any(
                i.get("attachment") == k["attachment"] and
                min(i["clip"][1], k["clip"][1]) - max(i["clip"][0], k["clip"][0]) >
                0.3 * min(i["clip"][1] - i["clip"][0], k["clip"][1] - k["clip"][0]) for k in kw):
            log.info("insertion « %s » retirée : même passage qu'un mot-clé", i["asset"].get("source"))
            continue
        keep.append(i)
    inserts[:] = keep
    log.info("Mots-clés : %d extrait(s) prêt(s) sur %d annonce(s) (%d « écoutez ça… » ignoré(s) : phrase qui continue)",
             len(kw), len(occ), len(info.get("ignored") or []))
    return info


KW_PRESS = """Montage d'une vidéo face caméra (langue « {lang} »). À chaque ANNONCE ci-dessous, l'auteur dit « écoutez ça »
(ou équivalent) : juste après, on doit faire entendre la déclaration qu'il annonce. Ses vidéos jointes n'ont rien de
cohérent : choisis parmi les DÉCLARATIONS TROUVÉES (presse, chaînes officielles) celle qui correspond EXACTEMENT à ce
qu'il annonce (même personne, même propos, même sujet). Jamais une déclaration seulement « dans le thème ».

ANNONCES :
{items}

DÉCLARATIONS TROUVÉES :
{clips}

Une déclaration ne sert qu'une fois. Rien de vraiment cohérent → liste vide pour cette annonce.
Réponds en JSON : {{"picks": [{{"n": numéro d'annonce, "clips": [numéros par ordre de préférence, 3 au plus],
"why": "le lien, en une phrase"}}]}}"""

KW_PRESS_CHECK = """Vérification indépendante (langue « {lang} »). L'auteur annonce « {phrase} » ; on fait entendre la
déclaration ci-dessous. Est-ce bien CE QU'IL ANNONCE (même personne / même propos) ?
AVANT l'annonce : « {before} »
APRÈS : « {after} »
DÉCLARATION : {who} — « {quote} »
Réponds en JSON : {{"ok": true/false, "score": 0 à 10, "reason": "une phrase",
"quote": "la déclaration, FIDÈLE, traduite en « {lang} » si besoin, 12 à 40 mots"}}"""


def kw_press_fallback(ai, words, sents, kw_info, inserts, pool, orient, work, lang, maxd) -> None:
    """« écoutez ça » sans passage de tes vidéos jointes → déclaration trouvée par le Finder / la recherche par
    affirmation, choisie par l'IA PUIS vérifiée par une 2e lecture. Téléchargement impossible → candidat suivant.
    Rien de cohérent → l'annonce reste sans extrait (et PLAN.md / le contrôle qualité le disent)."""
    from .keywords import _ctx
    pend = [it for it in kw_info["items"] if not it["inserted"] and it.get("pending_t") is not None]
    if not pend or not ai or not getattr(ai, "ok", False):
        return
    seen, clips = set(), []
    taken = {str((i.get("asset") or {}).get("credit", {}).get("url") or "") for i in inserts}
    for c in pool:
        key = (c.get("source_url"), round(float(c.get("start") or 0)))
        if c.get("source_url") and c.get("verdict") != "denial" and key not in seen and c.get("source_url") not in taken:
            seen.add(key)
            clips.append(c)
    clips = clips[:40]
    if not clips:
        return
    items_txt = []
    for it in pend:
        bef, aft = _ctx(words, max(0, it["w1"] - 60), it["w1"], 90, 40)
        items_txt.append(f"[{it['n']}] AVANT : … {bef}\n    APRÈS : {aft} …")
    clips_txt = "\n".join(f"[{k}] {c.get('speaker') or '?'} — {c.get('channel') or c.get('platform') or ''} : "
                           f"« {(c.get('quote') or '')[:300]} »" for k, c in enumerate(clips))
    j = ai.json(KW_PRESS.format(lang=lang, items="\n".join(items_txt), clips=clips_txt))
    picks = (j or {}).get("picks") if isinstance(j, dict) else None
    if not isinstance(picks, list):
        return
    by_n = {it["n"]: it for it in pend}
    used: set = set()
    used_k: set = set()
    # garde-fou temps : au plus 20 min pour ce repli, et jamais sur le temps gardé pour finir le montage
    end_t = time.time() + 20 * 60
    try:
        t0_job = float(os.environ.get("JOB_T0") or 0)
    except ValueError:
        t0_job = 0.0
    if t0_job:
        end_t = min(end_t, t0_job + float(os.environ.get("MONTAGE_JOB_MINUTES", "340")) * 60 - 100 * 60)
    for p in picks:
        if time.time() > end_t:
            for it in pend:
                if not it["inserted"]:
                    it["why"] = (it.get("why") or "") + " ; repli par la presse non tenté : temps gardé pour finir le montage"
            log.warning("repli « écoutez ça » interrompu : temps gardé pour finir le montage")
            break
        try:
            it = by_n.get(int(p.get("n")))
        except (TypeError, ValueError):
            continue
        if not it or it["inserted"]:
            continue
        cands = []
        for k in p.get("clips") or []:
            try:
                k = int(k)
            except (TypeError, ValueError):
                continue
            if 0 <= k < len(clips) and k not in used_k:
                cands.append(k)
        cands = cands[:3]
        cands.sort(key=lambda k_: is_youtube(clips[k_]))   # à pertinence vérifiée égale : téléchargeables d'abord
        verified = []
        for k in cands:
            c = clips[k]
            bef, aft = _ctx(words, max(0, it["w1"] - 60), it["w1"], 90, 40)
            ck = ai.json(KW_PRESS_CHECK.format(lang=lang, phrase=it["phrase"], before=bef, after=aft,
                                               who=f"{c.get('speaker') or '?'} ({c.get('channel') or ''})",
                                               quote=(c.get("quote") or "")[:500]))
            if not (isinstance(ck, dict) and ck.get("ok")):
                it.setdefault("press_refused", []).append(str((ck or {}).get("reason") or "vérification négative")[:120]
                                                          if isinstance(ck, dict) else "vérification indisponible")
                continue
            verified.append((k, c, ck))
            asset = clip_insert([c], orient, work, f"kwp{it['n']}_{k}", lang, ai, maxd, used)
            if not asset:
                it.setdefault("press_refused", []).append("vidéo non téléchargeable")
                continue
            cr = asset.get("credit") or {}
            asset["source"] = (f"MOT-CLÉ « {it['phrase']} » — déclaration trouvée : {cr.get('title')} — "
                               f"{cr.get('source')} ({cr.get('url')})")
            s_i = next((x["i"] for x in sents if x["w0"] <= it["w1"] <= x["w1"]), 0)
            inserts.append({"after": s_i, "asset": asset, "forced_t": it["pending_t"], "kw": it["n"]})
            used_k.add(k)
            it.update(inserted=True, at=it["pending_t"], video=f"{c.get('speaker') or 'déclaration'} — "
                      f"{c.get('channel') or c.get('platform') or ''}", a=float(c.get("start") or 0),
                      b=float(c.get("end") or 0), why=str(p.get("why") or "")[:200],
                      check={"ok": True, "score": ck.get("score"), "reason": str(ck.get("reason") or "")[:200]},
                      press=True)
            log.info("Mot-clé « %s » : déclaration trouvée insérée (%s)", it["phrase"], it["video"])
            break
        if not it["inserted"] and verified and time.time() < end_t:
            # cas extrême : la bonne déclaration existe mais aucune vidéo ne se télécharge → la VRAIE citation en carte
            k, c, ck = verified[0]
            quote = str(ck.get("quote") or c.get("quote") or "").strip()
            ws = quote.split()
            quote = " ".join(ws[:45]) + ("…" if len(ws) > 45 else "")
            pw_, ph_ = C.GEOM[orient]["left"]["panel"][2:]
            asset = quote_card_insert(c, quote, orient, work, f"kwq{it['n']}", lang, pw_, ph_) if quote else None
            if asset:
                asset["source"] = (f"MOT-CLÉ « {it['phrase']} » — CARTE CITATION (vidéo non téléchargeable) : "
                                   f"{c.get('speaker') or '?'} — {c.get('channel') or ''} ({c.get('source_url')})")
                s_i = next((x["i"] for x in sents if x["w0"] <= it["w1"] <= x["w1"]), 0)
                inserts.append({"after": s_i, "asset": asset, "forced_t": it["pending_t"], "kw": it["n"]})
                used_k.add(k)
                it.update(inserted=True, at=it["pending_t"], video=f"carte citation : {c.get('speaker') or 'déclaration'}"
                          f" — {c.get('channel') or ''}", a=float(c.get("start") or 0), b=float(c.get("end") or 0),
                          why=str(p.get("why") or "")[:200] + " (vidéo non téléchargeable : citation réelle en carte)",
                          check={"ok": True, "score": ck.get("score"), "reason": str(ck.get("reason") or "")[:200]},
                          press=True)
                log.info("Mot-clé « %s » : vidéo bloquée → citation réelle en carte (%s)", it["phrase"], it["video"])
        if not it["inserted"] and it.get("press_refused"):
            it["why"] = (it.get("why") or "") + " ; déclarations trouvées essayées mais refusées (" + \
                "; ".join(it["press_refused"][:2]) + ")"


OPENER_PROMPT = """Une vidéo face caméra (langue « {lang} ») doit commencer par une OUVERTURE CHOC : le passage le plus
fort, le plus choquant ou le plus saisissant d'une des vidéos jointes ci-dessous (phrase qui choque, chiffre terrible,
aveu, accusation, moment d'émotion), compréhensible seul, qui donne envie de rester. Sujet de la vidéo : {hook}

{videos}

Choisis UN passage de 4 à 12 secondes, qui commence et finit sur une phrase complète.
Réponds en JSON : {{"video": "id", "start": secondes, "end": secondes, "why": "pourquoi c'est le plus fort"}}."""


FOUND_OPENER_PROMPT = """Une vidéo face caméra (langue « {lang} ») doit commencer par une OUVERTURE CHOC : la déclaration la
plus forte, la plus choquante ou la plus saisissante parmi les déclarations vidéo ci-dessous (trouvées par une recherche
sur le sujet), compréhensible seule, EN RAPPORT DIRECT avec le sujet, qui donne envie de rester.
Sujet de la vidéo : {hook}

{clips}

Classe au plus 4 déclarations, de la plus forte à la moins forte, en n'en gardant AUCUNE hors sujet (liste vide si rien
ne convient). Réponds en JSON : {{"order": [numéros], "why": "pourquoi la 1re est la plus forte"}}."""


def pick_found_opener(ai, pool: list, inserts: list, lang: str, orient: str, work: Path, hook: str):
    """Ouverture choc sans vidéo jointe : déclaration vidéo trouvée (lot Finder / recherche), réellement téléchargée.
    Renvoie (extrait prêt ou None, phrase pour PLAN.md). Jamais deux fois la même vidéo que les extraits déjà placés."""
    if not pool:
        return None, "pas d'ouverture choc : aucune vidéo jointe et aucune déclaration vidéo trouvée par la recherche"
    taken = {((i.get("asset") or {}).get("credit") or {}).get("url") for i in inserts}
    seen, cands = set(), []
    for c in pool:
        url, q = c.get("source_url"), (c.get("quote") or "").strip()
        try:
            ln = float(c.get("out", c.get("end", 0))) - float(c.get("in", c.get("start", 0)))
        except (TypeError, ValueError):
            continue
        if not url or not q or ln < 3 or url in taken or (url, round(float(c.get("start", 0) or 0))) in seen:
            continue
        seen.add((url, round(float(c.get("start", 0) or 0))))
        cands.append(c)
    if not cands:
        return None, "pas d'ouverture choc : aucune déclaration vidéo utilisable (déjà placées ou sans citation)"
    cands = cands[:40]
    order, why = [], ""
    if ai and getattr(ai, "ok", False):
        txt = "\n".join(f'{k}. {c.get("speaker") or "?"} ({c.get("channel") or c.get("platform") or "?"}) : '
                        f'« {" ".join((c.get("quote") or "").split()[:45])} »' for k, c in enumerate(cands))
        j = ai.json(FOUND_OPENER_PROMPT.format(lang=lang, hook=hook or "(voir les déclarations)", clips=txt))
        if isinstance(j, dict):
            for v in j.get("order") or []:
                try:
                    k = int(v)
                except (TypeError, ValueError):
                    continue
                if 0 <= k < len(cands) and k not in order:
                    order.append(k)
            why = str(j.get("why") or "")
        if not order:
            return None, "pas d'ouverture choc : aucune déclaration trouvée assez forte et en rapport avec ton sujet"
    else:
        order = [0]
    t_end = time.time() + 8 * 60                       # garde-fou : jamais plus de 8 min pour l'ouverture
    try:                                               # … ni sur le temps gardé pour finir le montage (rendu, envoi)
        t0_job = float(os.environ.get("JOB_T0") or 0)
    except ValueError:
        t0_job = 0.0
    if t0_job:
        t_end = min(t_end, t0_job + float(os.environ.get("MONTAGE_JOB_MINUTES", "340")) * 60 - 100 * 60)
        if time.time() > t_end:
            return None, "pas d'ouverture choc : temps gardé pour finir le montage"
    for n, k in enumerate(order[:4]):
        if time.time() > t_end:
            break
        c = cands[k]
        asset = clip_insert([c], orient, work, f"opener{n}", lang, ai, 12.0, set())
        if asset:
            cr = asset.get("credit") or {}
            asset["opener_found"] = True
            asset["source"] = (f"OUVERTURE CHOC — vidéo trouvée — {cr.get('title') or ''} — {cr.get('source') or ''} "
                               f"({cr.get('url') or ''})" + (f" — {why}" if why and n == 0 else ""))
            log.info("Ouverture choc : déclaration trouvée %s", cr.get("url"))
            who = c.get("speaker") or cr.get("source") or "vidéo trouvée"
            return asset, f"ouverture choc : déclaration de {who} trouvée par la recherche ({cr.get('url') or ''})"
    return None, ("pas d'ouverture choc : les déclarations choisies n'ont pas pu être téléchargées "
                  "(vidéo bloquée ou indisponible)")


def pick_opener(ai, att: list, lang: str, orient: str, work: Path, hook: str, label_for=None):
    """Passage le plus choquant (4 à 12 s) des vidéos jointes, préparé comme un extrait inséré."""
    vids = [x for x in att if x["kind"] == "video" and x.get("duration", 0) >= 3]
    if not vids:
        return None
    pick = None
    if ai and ai.ok and any(x.get("sentences") for x in vids):
        txt = "\n".join(f'- id "{x["id"]}" « {x["name"]} » ({x["duration"]:.0f} s) : ' +
                        " / ".join(f'[{s["t0"]:.1f}-{s["t1"]:.1f}s] {s["text"]}' for s in (x.get("sentences") or [])[:120])
                        for x in vids)
        j = ai.json(OPENER_PROMPT.format(lang=lang, hook=hook or "(voir les vidéos)", videos=txt))
        if isinstance(j, dict):
            x = next((v for v in vids if v["id"] == str(j.get("video"))), None)
            try:
                a0, b0 = float(j.get("start")), float(j.get("end"))
            except (TypeError, ValueError):
                a0 = b0 = 0.0
            if x and b0 > a0:
                pick = (x, a0, b0, str(j.get("why") or ""))
    if pick is None:  # sans IA : le début du passage imposé, sinon le début de la vidéo jointe
        x = vids[0]
        a0 = (x.get("cut") or [0.0])[0]
        pick = (x, a0, a0 + 8.0, "")
    x, a0, b0 = pick[0], pick[1], pick[2]
    s_ = x.get("sentences") or []
    a, b = choose_bounds(s_, a0, b0, 12.0, x["duration"]) if s_ else (max(0.0, a0), min(x["duration"], b0))
    b = min(b, a + 15.0)
    asset = prepare_insert(Path(x["path"]), a, b, orient, work, "insert_opener", lang, ai, s_ if s_ else None, x.get("lang"))
    if asset:
        asset["credit"] = {"label": label_for(x, a, b) if label_for else (x.get("label") or _pretty(x["name"]))}
        asset["attachment"], asset["clip"] = x["id"], (a, b)
        asset["source"] = f"OUVERTURE CHOC — pièce jointe « {x['name']} » ({tc(a)} → {tc(b)})" + \
            (f" — {pick[3]}" if pick[3] else "")
        log.info("Ouverture choc : %s de %.1f s à %.1f s", x["name"], a, b)
    return asset


def _pretty(name: str) -> str:
    """Nom de fichier lisible (« ministre_economie.jpg » → « Ministre economie ») ; vide si nom d'appareil photo."""
    s = re.sub(r"[_\-.]+", " ", re.sub(r"^\d{2}_", "", Path(name).stem)).strip()
    if not s or re.match(r"^(img|dsc|pxl|vid|photo|image|screenshot|capture|wa)?\s*[\d\s]+$", s, re.I) or len(s) > 40:
        return ""
    return s[:1].upper() + s[1:]


def _fmt_date(d: str) -> str:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", d or "")
    return f"{m.group(3)}/{m.group(2)}/{m.group(1)}" if m else (d or "")[:20]


def write_report(outd, plan, segs, chosen, sents, info, total, lang, opts, att, chap_times, ai, lot_info=None, qc=None,
                 pause_stats=None, kw_info=None, rythme_info=None, brand=None, press_info=None, voice_info=None,
                 audio_note=""):
    L = []
    qc = list(qc or [])
    # tes pièces jointes : chacune doit apparaître (sinon verdict ⚠, avec le nom et la raison)
    used_ = {c["v"].get("attachment") for c in chosen}
    for s_ in segs:
        if s_.kind == "insert":
            used_ |= {s_.insert.get("attachment"), (s_.insert.get("asset") or {}).get("attachment")}
    miss_ = [x for x in att if x["id"] not in used_]
    if miss_:
        qc.append((False, "pièce(s) jointe(s) absente(s) du montage : " + ", ".join(
            f"{x['name']} ({'aucun silence sûr pour l’insérer sans te couper' if x['kind'] == 'video' else 'pas de place à l’écran au moment prévu'})"
            for x in miss_[:8])))
    # logo manquant à l'écran = visible par le public → compte dans le verdict
    for n_ in (brand or {}).get("notes") or []:
        if n_.startswith("⚠") and "logo" in n_:
            qc.append((False, n_.lstrip("⚠ ")))
    bad0 = [m for ok, m in (qc or []) if not ok]
    # 1re ligne = le verdict (c'est elle que tu regardes avant de publier ; reprise dans le titre de la release)
    L.append("# ✅ PRÊT À PUBLIER" if qc and not bad0 else "# ⚠ À VÉRIFIER AVANT DE PUBLIER")
    L.append("> 📌 **Ton réflexe** : regarde cette 1re ligne. **✅** = tu peux publier sans tout revisionner. "
             "**⚠** = la ligne « Contrôle qualité » ci-dessous dit exactement quoi et à quel moment ; regarde ce passage "
             "avant de publier.\n")
    L.append(f"## Montage — {plan.get('title') or 'vidéo'}\n")
    if qc:
        bad = [m for ok, m in qc if not ok]
        L.append(("**Contrôle qualité : ✅ tout est bon** — " + " · ".join(m for _, m in qc)) if not bad else
                 ("**Contrôle qualité : ⚠ à vérifier** — " + " · ".join(bad)))
        L.append("")
    L.append(f"- Durée : {tc(info['duration'])} déposée → **{tc(total)}** montée "
             f"(silences : {opts['couper_silences']}) · langue : {lang} · format : {info['w']}x{info['h']}")
    if pause_stats and pause_stats.get("cuts"):
        L.append(f"- Silences de plus de 2 s : {pause_stats['cuts']} raccourci(s), {pause_stats['gagne']:.0f} s gagnées — "
                 f"{pause_stats['zoom']} changement(s) de plan (tu n'avais pas bougé), {pause_stats['fondu']} fondu(s) "
                 f"doux, {pause_stats['page']} masquée(s) par l'arrivée d'un média ou d'un extrait")
    if plan.get("fallback"):
        L.append("- ⚠ IA indisponible : montage simplifié (pièces jointes réparties, sans photos ni presse). "
                 "Vérifie les secrets GEMINI_API_KEYS / GROQ_API_KEYS.")
    try:
        for w in Path("input/warnings.txt").read_text(encoding="utf-8").splitlines():
            if w.strip():
                L.append(f"- ⚠ {w.strip()}")
    except OSError:
        pass
    if brand is not None:
        b_on = "logo permanent" + (" + grand logo de fin" if brand.get("end") else "") if brand.get("bug") else "sans logo"
        L.append(f"- 🎨 Habillage : {brand.get('why') or 'chaîne par défaut'} — {b_on}")
        for n_ in brand.get("notes") or []:
            L.append(f"  - {n_}")
    if audio_note:
        L.append(f"- 🎙 {audio_note}")
    if voice_info is not None:
        st = voice_info.get("stats") or {}
        L.append(f"- 🎬 Mise en scène par la voix : {voice_info['why']}"
                 + (f" → {st.get('serre', 0)} plan(s) serré(s), {st.get('moyen', 0)} moyen(s), {st.get('large', 0)} large(s), "
                    f"{st.get('punch', 0)} coupe(s) sur un ton qui monte" if voice_info.get("on") else ""))
    if plan.get("_opener_note"):
        L.append(f"- ⚡ {plan['_opener_note']}")
    if plan.get("hook"):
        h0 = segs[0].dur if segs and segs[0].kind == "insert" and segs[0].insert.get("opener") else 0.0
        L.append(f"- Accroche ({tc(h0)} → {tc(h0 + 3.5)}) : « {plan['hook']} »")
    if kw_info is not None:
        its = kw_info["items"]
        L.append(f"- Mots-clés « écoutez… » : {len(its)} annonce(s) dans ta vidéo → "
                 f"{sum(1 for i in its if i['inserted'])} extrait(s) inséré(s) juste après")
        for i in its:
            when = tc(out_time(segs, i["t0"]) or 0)
            if i["inserted"]:
                ck = i.get("check") or {}
                verif = (f" — vérifié ✅ ({ck.get('score')}/10)" if ck.get("ok") else
                         (f" — ⚠ cohérence douteuse : {ck.get('reason')}" if ck else " — non vérifié (IA indisponible)"))
                L.append(f"  - {when} « {i['phrase']} » → {i['video']} {tc(i['a'])} → {tc(i['b'])} (à {tc(i['out'])}) : "
                         f"{i.get('why') or ''}{verif}")
            else:
                L.append(f"  - {when} « {i['phrase']} » → ⚠ non inséré : {i['why']}")
        for g in kw_info.get("ignored") or []:
            L.append(f"  - {tc(out_time(segs, g['t0']) or 0)} « {g['text']}… » → ignoré : tu continues ta phrase, ce "
                     f"n'est pas une annonce d'extrait")
    if rythme_info is not None:
        ins_t = sorted(s.out0 for s in segs if s.kind == "insert" and not s.insert.get("opener"))
        first5 = sum(1 for t in ins_t if t < 300)
        L.append(f"- Rythme ({rythme_info['rule']}) : {len(ins_t)} extrait(s) vidéo au total, dont {first5} dans les "
                 f"5 premières minutes — ajoutés pour tenir le rythme : {len(rythme_info['added'])} extrait(s), "
                 f"{len(rythme_info.get('cards') or [])} article(s) / photo(s)")
        KIND_ = {"article": "article", "photo": "ta photo", "wiki": "photo libre"}
        for c_ in rythme_info.get("cards") or []:
            L.append(f"  - {tc(out_time(segs, c_['t']) or 0)} → {KIND_.get(c_['kind'], c_['kind'])} « {c_['label']} » : "
                     f"{c_['why']} — vérifié ✅ ({(c_.get('check') or {}).get('score')}/10)")
        for d_ in rythme_info.get("thinned") or []:
            L.append(f"  - retiré pour garder un rythme régulier ({d_['gap']:.0f} s après l'élément précédent) : "
                     f"{d_['label']}")
        if rythme_info.get("why"):
            L.append(f"  - ⚠ aucun extrait vidéo ajouté : {rythme_info['why']}")
        placed_t = {round(s.insert.get("forced_t") or -1, 2) for s in segs if s.kind == "insert" and s.insert.get("rythme")}
        for r in rythme_info["added"]:
            ok_ = round(r["t"], 2) in placed_t
            ck = r.get("check") or {}
            L.append(f"  - {tc(out_time(segs, r['t']) or 0)} → {r['video']} {tc(r['a'])} → {tc(r['b'])} : {r['why']}"
                     + (f" — vérifié ✅ ({ck.get('score')}/10)" if ck.get("ok") else "")
                     + ("" if ok_ else " — ⚠ refusé au montage (silence pas assez sûr)"))
        # trous fusionnés en plages qui ne se chevauchent pas (une ligne par plage, raisons regroupées)
        merged = []
        for h in sorted(rythme_info["holes"], key=lambda h: h["t0"]):
            if merged and h["t0"] <= merged[-1]["t1"] + 1:
                merged[-1]["t1"] = max(merged[-1]["t1"], h["t1"])
                if h["why"] not in merged[-1]["why"]:
                    merged[-1]["why"].append(h["why"])
            else:
                merged.append({"t0": h["t0"], "t1": h["t1"], "why": [h["why"]]})
        for h in merged:
            a_, b_ = out_time(segs, h["t0"]), out_time(segs, h["t1"])
            if a_ is not None and b_ is not None and b_ > a_:
                L.append(f"  - ⚠ entre {tc(a_)} et {tc(b_)} : pas d'extrait — " + " ; ".join(h["why"][:3]))
    if lot_info:
        age = f", il y a {lot_info['age']} jour(s)" if lot_info.get("age") is not None else ""
        if lot_info.get("origine"):
            o = lot_info["origine"]
            L.append(f"- 🔗 Lot lancé par OSINT-teleprompter- pour le live « {(o.get('court') or o.get('sujet') or '')[:120]} » "
                     f"(script `prompter/{o.get('dossier', '')}`)")
        L.append(f"- Vid-o-presse-finder : lot **{lot_info['lot']}**{age} — {lot_info['clips']} extrait(s) et "
                 f"{lot_info['articles']} article(s) disponibles → {len(lot_info['placed']['inserts'])} déclaration(s) en "
                 f"rapport avec ce que tu dis ({lot_info['video_ok']} en vidéo, {lot_info['cards']} en carte car la vidéo "
                 f"n'a pas pu être téléchargée), {len(lot_info['placed']['articles'])} article(s)")
        if lot_info.get("age") and lot_info["age"] > 7:
            L.append("  ⚠ ce lot date de plus d'une semaine : relance Vid-o-presse-finder sur ton sujet avant le montage.")
    elif opts.get("finder") != "non":
        L.append("- Vid-o-presse-finder : aucun lot de résultats trouvé.")
    if press_info is not None:
        L.append(f"\n## 🔎 Recherche par affirmation ({len(press_info['claims'])})\n")
        for it in press_info["claims"]:
            p = it["p"]
            when = tc(out_time(segs, sents[p["after"]]["t0"]) or 0) if 0 <= p["after"] < len(sents) else "?"
            nv, na, ns = it["found"]
            L.append(f"- {when} « {p['target']}{' — ' + p['claim'] if p.get('claim') else ''} » → {it['status']}"
                     + (f" ({nv} vidéo(s), {na} article(s), {ns} message(s) trouvés)" if any(it["found"]) else ""))
            if it.get("detail"):
                L.append(f"  - 🔍 {it['detail']}")
        soc = press_info.get("social") or {}
        if soc:
            L.append(f"- Telegram : {soc.get('telegram', '—')} · Reddit : {soc.get('reddit', '—')}")
            for k_, v_ in soc.items():
                if str(v_).startswith("⚠"):
                    L.append(f"  - 🔧 À régler ({k_}, n'empêche pas de publier) : {str(v_).lstrip('⚠ ')}")
    contre = list((press_info or {}).get("contre") or []) + list((lot_info or {}).get("contre") or [])
    if contre:
        L.append("\n## 🛡 Ce qui te contredit (à anticiper : réponds-y avant qu'on te le sorte en commentaire)\n")
        seen_ = set()
        for c in contre:
            if c.get("url") in seen_:
                continue
            seen_.add(c.get("url"))
            about = f" — sur « {c['claim']['target']} »" if isinstance(c.get("claim"), dict) else ""
            L.append(f"- {c.get('source') or c.get('domaine', '')} ({_fmt_date(c.get('date', '')) or '?'}) : "
                     f"{(c.get('titre') or '')[:160]} — {c.get('url')}{about}")
    if plan.get("title"):
        L.append(f"\n## Pour YouTube\n**Titre conseillé** : {plan['title']}\n")
        if plan.get("description"):
            L.append(plan["description"] + "\n")
    if plan.get("chapters"):
        L.append("**Chapitres** (à coller dans la description) :\n```")
        L.append("0:00 " + (plan["chapters"][0]["title"] if plan["chapters"] and plan["chapters"][0]["s"] == 0 else "Introduction"))
        last = 0.0
        for i, c in enumerate(plan["chapters"]):
            t = out_time(segs, sents[c["s"]]["t0"]) if c["s"] < len(sents) else None
            # YouTube : le 1er chapitre est toujours 0:00 (déjà écrit), puis au moins 10 s entre deux chapitres
            if t is None or (i == 0 and plan["chapters"][0]["s"] == 0) or t < last + 10:
                continue
            L.append(f"{tc(t)} {c['title']}")
            last = t
        L.append("```")
    L.append("\n## Ce qui apparaît, où et quand\n")
    L.append("| Quand (vidéo finale) | Quoi | Où | Pourquoi (ce que tu dis) | Source |")
    L.append("|---|---|---|---|---|")
    for s in segs:
        if s.kind == "split":
            v = s.panel["v"]
            what = {"person": "Photo (personne)", "place": "Photo (lieu)", "thing": "Photo", "event": "Photo (événement)",
                    "article": "Article de presse", "figure": "Chiffre clé", "quote": "Citation",
                    "attachment": "Ta photo", "statement": "Déclaration (carte)"}.get(v["kind"], v["kind"])
            lab = v.get("text") or v.get("label") or ""
            side = ("à droite de toi" if s.side == "left" else "à gauche de toi") if info["w"] >= info["h"] else "sous toi"
            said = sents[v["s0"]]["text"][:110] if v["s0"] < len(sents) else ""
            L.append(f"| {tc(s.out0)} → {tc(s.out0 + s.dur)} | {what} : {lab} | {side} | « {said} » | {v.get('source', '—')} |")
        elif s.kind == "insert":
            a = s.insert["asset"]
            said = sents[s.insert["after"]]["text"][:110] if 0 <= s.insert["after"] < len(sents) else ""
            tr = " (sous-titres traduits)" if a.get("translated") else ""
            if s.insert.get("opener"):
                L.append(f"| {tc(s.out0)} → {tc(s.out0 + s.dur)} | **Ouverture choc**{tr} | plein écran, avant que tu "
                         f"apparaisses | passage le plus fort de l'extrait | {a.get('source', '—')} |")
                continue
            L.append(f"| {tc(s.out0)} → {tc(s.out0 + s.dur)} | Extrait vidéo{tr} | plein écran, tu disparais "
                     f"(pendant ton silence) | après « {said} » | {a.get('source', '—')} |")
    used_att = {c["v"].get("attachment") for c in chosen} | {s.insert.get("attachment") for s in segs if s.kind == "insert"} \
        | {(s.insert.get("asset") or {}).get("attachment") for s in segs if s.kind == "insert"}
    left = [x["name"] for x in att if x["id"] not in used_att]
    if left:
        L.append(f"\n⚠ Pièces jointes non placées (aucun moment ne s'y prêtait, ou place prise) : {', '.join(left)}")
    dropped = [v for v in plan["visuals"] if v.get("asset") and not any(c["v"] is v for c in chosen)]
    if dropped:
        L.append(f"\nVisuels écartés pour garder l'écran respirable : {len(dropped)}")
    if ai.errors:
        L.append(f"\n<details><summary>⚠ Incidents IA ({len(ai.errors)}) — demandes restées sans réponse (aucune source "
                 f"disponible)</summary>\n\n" + "\n".join(f"- {e}" for e in ai.errors[:15]) + "\n</details>")
    if getattr(ai, "recovered", 0):
        L.append(f"\nIA : {ai.recovered} refus momentané(s) (limite de débit, requête trop longue pour une source…) "
                 f"rattrapé(s) automatiquement par une autre source — sans effet sur le montage.")
    (outd / "PLAN.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    slim = {k: v for k, v in plan.items() if k != "visuals"}
    slim["visuals"] = [{k: v for k, v in x.items() if k != "asset"} for x in plan["visuals"]]
    save_json(outd / "plan.json", slim)


if __name__ == "__main__":
    sys.exit(main())
