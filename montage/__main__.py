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
from .assets import (choose_bounds, describe_attachments, list_attachments, og_image, prepare_insert, press_clip,
                     press_search, wiki_image)
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
    for k in ("sous_titres", "recherche_presse", "images_web", "effets_sonores", "fin"):
        o[k] = "non" if o[k] in no else ("oui" if o[k] in yes else C.DEFAULTS[k])
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

    # 1) transcription
    want_lang = opts["langue"] if opts["langue"] not in ("", "auto") else None
    tr = transcribe(src, work, want_lang, tag="main") if info["audio"] else {"lang": want_lang or "fr", "words": [],
                                                                               "silences": []}
    lang = (want_lang or tr.get("lang") or "fr")[:2]
    words = tr["words"]
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
    max_ins = int(opts["max_inserts"] or 3)
    inserts = []
    for k, ins in enumerate(plan["inserts"]):
        x = by_id.get(ins["attachment"])
        if not x or len(inserts) >= max_ins + 5:  # les vidéos de l'auteur passent avant la limite
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
            a0, b0 = choose_bounds(s_, want0, want1 if want1 > want0 else x["duration"], maxd, x["duration"])
        asset = prepare_insert(Path(x["path"]), a0, b0, orient, work, f"insert_att{k}", lang, ai, s_ if s_ else None,
                               x.get("lang"))
        if asset:
            asset["credit"] = {"label": x.get("label") or _pretty(x["name"])}
            asset["source"] = f"pièce jointe « {x['name']} » ({tc(a0)} → {tc(b0)})"
            inserts.append({"after": ins["after"], "asset": asset, "attachment": x["id"]})
    if opts["recherche_presse"] != "non" and plan["press"]:
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
    inserts = inserts[:max_ins + sum(1 for i in plan["inserts"])]

    # 5) ligne de temps
    keep = keep_ranges(words, tr.get("silences") or [], info["duration"], opts["couper_silences"])
    segs, chosen = schedule(words, sents, keep, plan["visuals"], inserts, plan["chapters"], info["duration"], opts, orient)
    if not segs:
        raise SystemExit("Rien à monter (vidéo vide ?)")
    total = segs[-1].out0 + segs[-1].dur
    log.info("Ligne de temps : %d segments, %.0f s → %.0f s", len(segs), info["duration"], total)

    # 6) textes à l'écran
    face = face_center(src)
    log.info("Visage : %s (%.2f, %.2f)", "trouvé" if face["found"] else "non trouvé (cadrage centré)", face["cx"], face["cy"])
    sub = ASS(orient, lang, face)
    if plan.get("hook"):
        sub.hook(plan["hook"])
    chap_times = []
    for i, c in enumerate(plan["chapters"]):
        t = out_time(segs, sents[c["s"]]["t0"]) if c["s"] < len(sents) else None
        if t is None or t < 4.5 or t > total - 8:
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
    ctx = Ctx(src.resolve(), info, face, orient, work.resolve(), ass_path, fonts)
    vid = render_video(segs, ctx, work / "video.mp4", workers=int(os.environ.get("MONTAGE_WORKERS", "2")))
    main_wav = extract_main_audio(src, info, work / "main.wav")
    aud = build_audio(segs, main_wav, work / "mix.wav", opts["effets_sonores"] != "non", chap_times)
    final = mux(vid, aud, outd / "montage-final.mp4")
    log.info("Vidéo finale : %s (%.0f s, rendu en %.0f min)", final, total, (time.time() - T0) / 60)

    # 8) rapport : quoi / où / quand
    write_report(outd, plan, segs, chosen, sents, info, total, lang, opts, att, chap_times, ai)
    return 0


def _pretty(name: str) -> str:
    """Nom de fichier lisible (« ministre_economie.jpg » → « Ministre economie ») ; vide si nom d'appareil photo."""
    s = re.sub(r"[_\-.]+", " ", re.sub(r"^\d{2}_", "", Path(name).stem)).strip()
    if not s or re.match(r"^(img|dsc|pxl|vid|photo|image|screenshot|capture|wa)?\s*[\d\s]+$", s, re.I) or len(s) > 40:
        return ""
    return s[:1].upper() + s[1:]


def _fmt_date(d: str) -> str:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", d or "")
    return f"{m.group(3)}/{m.group(2)}/{m.group(1)}" if m else (d or "")[:20]


def write_report(outd, plan, segs, chosen, sents, info, total, lang, opts, att, chap_times, ai):
    L = []
    L.append(f"# Montage — {plan.get('title') or 'vidéo'}\n")
    L.append(f"- Durée : {tc(info['duration'])} déposée → **{tc(total)}** montée "
             f"(silences : {opts['couper_silences']}) · langue : {lang} · format : {info['w']}x{info['h']}")
    if plan.get("fallback"):
        L.append("- ⚠ IA indisponible : montage simplifié (pièces jointes réparties, sans photos ni presse). "
                 "Vérifie les secrets GEMINI_API_KEYS / GROQ_API_KEYS.")
    if plan.get("hook"):
        L.append(f"- Accroche (0:00 → 0:03) : « {plan['hook']} »")
    if plan.get("title"):
        L.append(f"\n## Pour YouTube\n**Titre conseillé** : {plan['title']}\n")
        if plan.get("description"):
            L.append(plan["description"] + "\n")
    if plan.get("chapters"):
        L.append("**Chapitres** (à coller dans la description) :\n```")
        L.append("0:00 " + (plan["chapters"][0]["title"] if plan["chapters"] and plan["chapters"][0]["s"] == 0 else "Introduction"))
        k = 0
        for c in plan["chapters"]:
            t = out_time(segs, sents[c["s"]]["t0"]) if c["s"] < len(sents) else None
            if t is None or t < 4.5:
                continue
            L.append(f"{tc(t)} {c['title']}")
            k += 1
        L.append("```")
    L.append("\n## Ce qui apparaît, où et quand\n")
    L.append("| Quand (vidéo finale) | Quoi | Où | Pourquoi (ce que tu dis) | Source |")
    L.append("|---|---|---|---|---|")
    for s in segs:
        if s.kind == "split":
            v = s.panel["v"]
            what = {"person": "Photo (personne)", "place": "Photo (lieu)", "thing": "Photo", "event": "Photo (événement)",
                    "article": "Article de presse", "figure": "Chiffre clé", "quote": "Citation",
                    "attachment": "Ta photo"}.get(v["kind"], v["kind"])
            lab = v.get("text") or v.get("label") or ""
            side = ("à droite de toi" if s.side == "left" else "à gauche de toi") if info["w"] >= info["h"] else "sous toi"
            said = sents[v["s0"]]["text"][:110] if v["s0"] < len(sents) else ""
            L.append(f"| {tc(s.out0)} → {tc(s.out0 + s.dur)} | {what} : {lab} | {side} | « {said} » | {v.get('source', '—')} |")
        elif s.kind == "insert":
            a = s.insert["asset"]
            said = sents[s.insert["after"]]["text"][:110] if s.insert["after"] < len(sents) else ""
            tr = " (sous-titres traduits)" if a.get("translated") else ""
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
