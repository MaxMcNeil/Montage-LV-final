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
from .assets import (choose_bounds, clip_insert, describe_attachments, list_attachments, og_image, prepare_insert,
                     press_clip, press_search, thumbnail, wiki_image)
from .finder import load_lot
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
    no = {"non", "no", "false", "0", "off", "لا"}
    for k in ("sous_titres", "recherche_presse", "images_web", "effets_sonores", "fin", "ouverture_choc", "silences_longs",
              "mots_cles", "rythme"):
        o[k] = "non" if o[k] in no else ("oui" if o[k] in yes else C.DEFAULTS[k])
    f = (o.get("finder") or "dernier").strip()
    o["finder"] = "non" if f.lower() in no else ("dernier" if f.lower() in yes | {"dernier", "last", "auto"} else f)
    if o["couper_silences"] not in ("doux", "dynamique", "non"):
        o["couper_silences"] = "non" if o["couper_silences"] in no else C.DEFAULTS["couper_silences"]
    for k in ("max_inserts", "duree_max_insert"):
        m = re.search(r"\d+", o[k] or "")
        o[k] = m.group(0) if m else C.DEFAULTS[k]
    o["duree_max_insert"] = str(min(90, max(6, int(o["duree_max_insert"]))))
    names = {"français": "fr", "francais": "fr", "french": "fr", "arabe": "ar", "arabic": "ar", "عربي": "ar",
             "العربية": "ar", "italien": "it", "italiano": "it", "italian": "it", "anglais": "en", "english": "en",
             "espagnol": "es", "español": "es", "allemand": "de", "deutsch": "de"}
    lg = o["langue"]
    o["langue"] = names.get(lg, lg[:2] if re.fullmatch(r"[a-z]{2}(-[a-z]+)?", lg or "") else "auto")
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
    max_ins = int(opts["max_inserts"] or 6)
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
            log.info("Ouverture choc : aucune vidéo jointe → la vidéo commence normalement")
        else:
            used.setdefault(opener["attachment"], []).append(opener["clip"])
    for k, ins in enumerate(plan["inserts"]):
        x = by_id.get(ins["attachment"])
        if not x or len(inserts) >= 12:  # tes vidéos passent avant la limite des extraits de presse
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
            log.info("Vid-o-presse-finder : %d extrait(s) vidéo inséré(s), %d carte(s) déclaration, %d article(s)",
                     lot_info["video_ok"], lot_info["cards"], len(m["articles"]))
    if opts["recherche_presse"] != "non" and plan["press"] and not finder_used:
        used = set()
        budget_end = time.time() + 25 * 60
        for k, p in enumerate(plan["press"][:2]):
            if time.time() > budget_end:
                break
            res = press_search(p, lang, work, minutes=9)
            if len(inserts) < max_ins:
                asset = press_clip(res, orient, work, k, lang, ai, maxd, used)
                if asset:
                    cr = asset["credit"]
                    asset["source"] = f"{cr.get('title')} — {cr.get('source')} ({cr.get('url')})"
                    inserts.append({"after": p["after"], "asset": asset})
            arts = sorted(res.get("articles") or [], key=lambda r: -float(r.get("autorite") or 0))
            for j, art in enumerate(arts[:1]):
                if not art.get("titre"):
                    continue
                img = og_image(art.get("url", ""), work / "web" / f"og_{k}_{j}")
                data = {"source": art.get("source") or art.get("domaine", ""), "date": _fmt_date(art.get("date", "")),
                        "headline": art["titre"], "domain": art.get("domaine", ""),
                        "image": open_image(img) if img else None}
                s0 = max(0, min(p.get("s0", p["after"]), p["after"]))
                v = {"kind": "article", "s0": s0, "s1": min(s0 + 1, p["after"]), "trigger": "", "priority": 1,
                     "label": art["titre"][:60], "source": f"{art.get('source')} — {art.get('url')}"}
                try:
                    v["asset"] = render_panel("article", pw, ph, data, pdir, f"art{k}{j}")
                    plan["visuals"].append(v)
                except Exception as e:  # noqa: BLE001
                    log.warning("carte article abandonnée : %s", e)
        ai.save_quota()
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
        from .cadence import fill

        def _prep(x, a_, b_, name):
            s2 = x.get("sentences") or []
            asset_ = prepare_insert(Path(x["path"]), a_, b_, orient, work, name, lang, ai, s2 if s2 else None, x.get("lang"))
            if asset_:
                asset_["credit"] = {"label": label_for(x, a_, b_)}
            return asset_
        try:
            rythme_info = fill(ai, words, sents, att, inserts, used, sil_all, lang, orient, work, bool(opener), _prep)
        except Exception as e:  # noqa: BLE001 - le rythme est un bonus : jamais bloquant
            log.warning("rythme des extraits abandonné : %s", e)

    # 5) ligne de temps
    from .media import black_start
    b0 = black_start(vsrc)
    if b0 > 0:
        log.info("Images noires au début de ta vidéo (%.2f s) : retirées", b0)
    long_gap = 2.0 if opts.get("silences_longs") == "oui" else None
    keep = keep_ranges(words, sil_all, info["duration"], opts["couper_silences"], b0, long_gap=long_gap)
    segs, chosen = schedule(words, sents, keep, plan["visuals"], inserts, plan["chapters"], info["duration"], opts, orient,
                            opener=opener, sil=sil_all)
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
    hook_end = h0 + 3.35 if plan.get("hook") else 0.0
    if plan.get("hook"):
        sub.hook(plan["hook"], h0, hook_end)
    chap_times = []
    for i, c in enumerate(plan["chapters"]):
        t = out_time(segs, sents[c["s"]]["t0"]) if c["s"] < len(sents) else None
        # le 1er chapitre est couvert par l'accroche ; jamais deux textes en même temps
        if t is None or i == 0 or c["s"] <= (sents[0]["i"] if sents else 0) or t < h0 + 1.0 or t > total - 8:
            continue
        if t < hook_end + 0.4:
            t = hook_end + 0.4
        if chap_times and t < chap_times[-1] + 4.5:
            continue
        sub.chapter(t, i + 1, c["title"])
        chap_times.append(t)
    for s in segs:
        if s.kind == "insert":
            sub.insert(s.out0, s.dur, s.insert["asset"])
    if opts["sous_titres"] != "non":
        emph = {norm(w) for ws in plan.get("emphasis", {}).values() for w in ws for w in [w] if norm(w)}
        emph = {x for w in emph for x in w.split() if len(x) > 2}
        sub.captions(words, segs, emph)
    if opts["fin"] != "non":
        sub.outro(total, plan.get("outro") or C.ui(lang, "outro"), C.ui(lang, "sub"))
    ass_path = (work / "textes.ass").resolve()
    ass_path.write_text(sub.text(), encoding="utf-8")

    # 7) rendu
    fonts = Path(a.fonts).resolve() if Path(a.fonts).is_dir() else None
    ctx = Ctx(Path(vsrc).resolve(), vinfo, face, orient, work.resolve(), ass_path, fonts)
    vid = render_video(segs, ctx, work / "video.mp4", workers=int(os.environ.get("MONTAGE_WORKERS", "2")))
    main_wav = extract_main_audio(src, info, work / "main.wav")
    aud = build_audio(segs, main_wav, work / "mix.wav", opts["effets_sonores"] != "non", chap_times)
    final = mux(vid, aud, outd / "montage-final.mp4")
    log.info("Vidéo finale : %s (%.0f s, rendu en %.0f min)", final, total, (time.time() - T0) / 60)

    # 8) contrôle qualité automatique, puis rapport : quoi / où / quand
    try:
        from .qc import check
        qc = check(final, segs, words, ass_path, long_gap=long_gap, kw_info=kw_info)
    except Exception as e:  # noqa: BLE001
        qc = [(False, f"contrôle qualité impossible : {e}")]
    write_report(outd, plan, segs, chosen, sents, info, total, lang, opts, att, chap_times, ai, lot_info, qc, pause_stats,
                 kw_info, rythme_info)
    return 0


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
        if o["at"] is None and o["phrase"].endswith("ça"):
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
        if not vids:
            item["why"] = "aucune vidéo jointe (release ou Drive)"
            continue
        if t is None:
            item["why"] = (f"tu enchaînes sans pause pendant {o.get('wait', 8.0):.0f} s après la phrase : pas d'insertion "
                           f"(pour ne pas te couper)")
            continue
        p = picks.get(n)
        if not p:
            item["why"] = "aucun passage trouvé dans les vidéos jointes"
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


OPENER_PROMPT = """Une vidéo face caméra (langue « {lang} ») doit commencer par une OUVERTURE CHOC : le passage le plus
fort, le plus choquant ou le plus saisissant d'une des vidéos jointes ci-dessous (phrase qui choque, chiffre terrible,
aveu, accusation, moment d'émotion), compréhensible seul, qui donne envie de rester. Sujet de la vidéo : {hook}

{videos}

Choisis UN passage de 4 à 12 secondes, qui commence et finit sur une phrase complète.
Réponds en JSON : {{"video": "id", "start": secondes, "end": secondes, "why": "pourquoi c'est le plus fort"}}."""


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
                 pause_stats=None, kw_info=None, rythme_info=None):
    L = []
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
        L.append(f"- Rythme des extraits ({rythme_info['rule']}) : {len(ins_t)} extrait(s) au total, dont {first5} dans les "
                 f"5 premières minutes — {len(rythme_info['added'])} ajouté(s) pour tenir le rythme")
        if rythme_info.get("why"):
            L.append(f"  - ⚠ rien ajouté : {rythme_info['why']}")
        placed_t = {round(s.insert.get("forced_t") or -1, 2) for s in segs if s.kind == "insert" and s.insert.get("rythme")}
        for r in rythme_info["added"]:
            ok_ = round(r["t"], 2) in placed_t
            ck = r.get("check") or {}
            L.append(f"  - {tc(out_time(segs, r['t']) or 0)} → {r['video']} {tc(r['a'])} → {tc(r['b'])} : {r['why']}"
                     + (f" — vérifié ✅ ({ck.get('score')}/10)" if ck.get("ok") else "")
                     + ("" if ok_ else " — ⚠ refusé au montage (silence pas assez sûr)"))
        for h in rythme_info["holes"]:
            a_, b_ = out_time(segs, h["t0"]), out_time(segs, h["t1"])
            if a_ is not None and b_ is not None:
                L.append(f"  - ⚠ entre {tc(a_)} et {tc(b_)} : pas d'extrait — {h['why']}")
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
    used_att = {c["v"].get("attachment") for c in chosen} | {s.insert.get("attachment") for s in segs if s.kind == "insert"}
    left = [x["name"] for x in att if x["id"] not in used_att]
    if left:
        L.append(f"\n⚠ Pièces jointes non placées (aucun moment ne s'y prêtait, ou place prise) : {', '.join(left)}")
    dropped = [v for v in plan["visuals"] if v.get("asset") and not any(c["v"] is v for c in chosen)]
    if dropped:
        L.append(f"\nVisuels écartés pour garder l'écran respirable : {len(dropped)}")
    if ai.errors:
        L.append(f"\n<details><summary>Incidents IA ({len(ai.errors)})</summary>\n\n" +
                 "\n".join(f"- {e}" for e in ai.errors[:15]) + "\n</details>")
    (outd / "PLAN.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    slim = {k: v for k, v in plan.items() if k != "visuals"}
    slim["visuals"] = [{k: v for k, v in x.items() if k != "asset"} for x in plan["visuals"]]
    save_json(outd / "plan.json", slim)


if __name__ == "__main__":
    sys.exit(main())
