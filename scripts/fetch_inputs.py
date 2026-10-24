#!/usr/bin/env python3
"""Récupère ce que tu as déposé :
  - la vidéo principale → input/video.<ext>
  - les pièces jointes (photos, vidéos) → input/attachments/
  - tes consignes (texte de la release) → input/notes.txt, et les réglages écrits « réglage: valeur » → input/options.json

Sources acceptées :
  1. une Release GitHub (tag qui commence par « montage ») : la plus grosse vidéo jointe = ta vidéo, le reste = pièces
     jointes. Vidéo trop lourde pour GitHub (> 2 Go) : colle son lien Google Drive dans la description.
  2. un lien Google Drive (fichier, ou DOSSIER pour les pièces jointes), un lien direct, ou un tag de release
     (champ « source » / « pieces_jointes » du formulaire Run workflow).
Google Drive : rclone si le secret RCLONE_CONF existe (aucune limite), sinon gdown (fichier partagé « Tous les
utilisateurs disposant du lien »)."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

VIDEO = (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".3gp", ".mts")
IMAGE = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".heic", ".heif", ".avif")
KEYS = ["couper_silences", "sous_titres", "recherche_presse", "max_inserts", "duree_max_insert", "images_web",
        "effets_sonores", "fin", "langue"]
ALIASES = {"silences": "couper_silences", "coupe": "couper_silences", "sous-titres": "sous_titres", "subtitles": "sous_titres",
           "presse": "recherche_presse", "inserts": "max_inserts", "insertions": "max_inserts", "duree_insert": "duree_max_insert",
           "photos_web": "images_web", "effets": "effets_sonores", "sons": "effets_sonores", "carte_fin": "fin",
           "lang": "langue", "language": "langue"}
REPO = os.environ.get("REPO", "")
IN = Path("input")
RAW = IN / "raw"
ATT = IN / "attachments"
DRIVE_RE = r"https?://(?:drive|docs)\.google\.com/[^\s)>\"'\]]+"


def die(msg: str):
    print(f"::error::{msg}")
    sys.exit(1)


def sh(cmd: list, check=True, **kw) -> subprocess.CompletedProcess:
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)
    if check and r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "").strip()[-600:])
    return r


def out(k, v):
    p = os.environ.get("GITHUB_OUTPUT")
    if p:
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"{k}={v}\n")


# ---------------------------------------------------------------- Google Drive
def drive_id(u: str) -> tuple[str | None, bool]:
    m = re.search(r"/folders/([A-Za-z0-9_-]{10,})", u)
    if m:
        return m.group(1), True
    m = re.search(r"/(?:file/)?d/([A-Za-z0-9_-]{10,})", u) or re.search(r"[?&]id=([A-Za-z0-9_-]{10,})", u)
    if m:
        return m.group(1), False
    if re.fullmatch(r"[A-Za-z0-9_-]{25,}", u.strip()):
        return u.strip(), False
    return None, False


_remote = None


def rclone_remote() -> str | None:
    global _remote
    if _remote is not None:
        return _remote or None
    conf = os.environ.get("RCLONE_CONF", "").strip()
    _remote = ""
    if not conf:
        return None
    if not shutil.which("rclone"):
        subprocess.run("curl -sSf https://rclone.org/install.sh | sudo bash >/dev/null", shell=True)
    p = Path.home() / ".config/rclone/rclone.conf"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(conf + "\n", encoding="utf-8")
    m = re.search(r"^\[([^\]]+)\]", conf, re.M)
    _remote = m.group(1) if m else ""
    return _remote or None


def from_drive(link: str, dest: Path) -> list[Path]:
    did, folder = drive_id(link)
    if not did:
        print(f"::warning::Lien Google Drive non reconnu : {link}")
        return []
    dest.mkdir(parents=True, exist_ok=True)
    before = set(dest.rglob("*"))
    rem = rclone_remote()
    try:
        if rem:
            print(f"Google Drive ({'dossier' if folder else 'fichier'} {did}) → rclone")
            if folder:
                sh(["rclone", "copy", f"{rem}:", dest, "--drive-root-folder-id", did, "--drive-acknowledge-abuse", "-q"])
            else:
                sh(["rclone", "backend", "copyid", f"{rem}:", did, f"{dest}/", "--drive-acknowledge-abuse", "-q"])
        else:
            print(f"Google Drive ({'dossier' if folder else 'fichier'} {did}) → gdown (lien public)")
            if folder:
                sh(["gdown", "--folder", "-q", f"https://drive.google.com/drive/folders/{did}", "-O", dest], timeout=3600)
            else:
                sh(["gdown", "-q", f"https://drive.google.com/uc?id={did}", "-O", f"{dest}/"], timeout=3600)
    except Exception as e:  # noqa: BLE001
        print(f"::warning::Téléchargement Google Drive refusé ({link}) : {str(e)[-300:]}\n"
              "→ partage le fichier « Tous les utilisateurs disposant du lien → Lecteur », ou ajoute le secret RCLONE_CONF "
              "(indispensable si Google affiche « quota de téléchargement dépassé »).")
        return []
    return [p for p in dest.rglob("*") if p.is_file() and p not in before]


# ---------------------------------------------------------------- Releases
def release_body(tag: str) -> str:
    try:
        j = json.loads(sh(["gh", "release", "view", tag, "--repo", REPO, "--json", "body,name"]).stdout)
    except Exception:  # noqa: BLE001
        return ""
    body = j.get("body") or ""
    return body.split("<!-- etat-auto -->")[0]


def asset_names(tag: str) -> list[str]:
    try:
        j = json.loads(sh(["gh", "release", "view", tag, "--repo", REPO, "--json", "assets"]).stdout)
        return [a["name"] for a in j.get("assets") or []]
    except Exception:  # noqa: BLE001
        return []


def waiting_releases(exclude: set) -> list[str]:
    """Releases « pièces jointes en attente » : tag qui ne commence ni par montage ni par out-, sans fichier « moi… »,
    publiées depuis moins de 3 jours. Leurs photos/vidéos sont ajoutées au montage (puis ces releases sont supprimées)."""
    import datetime as dt
    try:
        j = json.loads(sh(["gh", "release", "list", "--repo", REPO, "--limit", "40", "--json",
                           "tagName,createdAt,isDraft"]).stdout)
    except Exception:  # noqa: BLE001
        return []
    now = dt.datetime.now(dt.timezone.utc)
    out_tags = []
    for r in j:
        t = r["tagName"]
        if r.get("isDraft") or t in exclude or t.lower().startswith(("montage", "out-")):
            continue
        try:
            age = now - dt.datetime.fromisoformat(r["createdAt"].replace("Z", "+00:00"))
        except ValueError:
            continue
        if age > dt.timedelta(days=3):
            continue
        names = asset_names(t)
        if names and not any(n.lower().startswith("moi") for n in names):
            out_tags.append(t)
    return out_tags


def from_release(tag: str, dest: Path | None = None) -> list[Path]:
    dest = dest or RAW
    dest.mkdir(parents=True, exist_ok=True)
    print(f"Release {tag} : téléchargement des fichiers joints")
    try:
        sh(["gh", "release", "download", tag, "--repo", REPO, "--dir", dest, "--clobber"], timeout=3600)
    except RuntimeError as e:
        if "no assets" not in str(e).lower():
            print(f"::warning::{e}")
    return [p for p in dest.rglob("*") if p.is_file()]


def from_url(u: str, dest: Path) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^\w.-]", "_", Path(u.split("?")[0]).name) or "fichier"
    if not name.lower().endswith(VIDEO + IMAGE):
        name += ".mp4"
    f = dest / name
    try:
        sh(["curl", "-fL", "--retry", "3", "-o", f, u], timeout=3600)
        return [f]
    except RuntimeError as e:
        print(f"::warning::Téléchargement impossible ({u}) : {e}")
        return []


# ---------------------------------------------------------------- réglages écrits dans la description
def parse_body(body: str) -> tuple[str, dict, list[str]]:
    opts, keep, links = {}, [], re.findall(DRIVE_RE, body)
    for line in body.splitlines():
        m = re.match(r"^\s*[-*•]?\s*([A-Za-zéèàçù_ -]{3,25})\s*[:=]\s*(.+?)\s*$", line)
        if m:
            k = m.group(1).strip().lower().replace(" ", "_").replace("é", "e").replace("è", "e")
            k = ALIASES.get(k, k)
            if k in KEYS:
                opts[k] = m.group(2).strip().lower()
                continue
        keep.append(re.sub(DRIVE_RE, "", line))
    notes = "\n".join(keep).strip()
    return notes, opts, links


TS = r"(\d{1,2}(?::\d{1,2}){0,2}(?:[.,]\d+)?)"
CUT_RE = re.compile(r"^\s*[-*•]?\s*(.+?\.[A-Za-z0-9]{2,4})\s*[=:]\s*" + TS + r"\s*(?:-|–|—|à|a|to)\s*" + TS + r"\s*$", re.I)


def ts(s: str) -> float:
    """« 1:20 » → 80 s ; « 1:02:03 » → 3723 s ; « 95 » → 95 s ; « 1:20,5 » → 80.5 s."""
    sec = 0.0
    for part in s.replace(",", ".").split(":"):
        sec = sec * 60 + float(part)
    return sec


def parse_cuts(text: str) -> tuple[str, dict]:
    """Lignes « fichier.mp4 = 1:20-1:45 » : passage imposé pour une de tes vidéos jointes (facultatif)."""
    cuts, keep = {}, []
    for line in (text or "").splitlines():
        m = CUT_RE.match(line)
        if m and m.group(1).lower().endswith(VIDEO):
            a, b = ts(m.group(2)), ts(m.group(3))
            if b > a:
                cuts[m.group(1).strip().lower()] = [a, b]
                continue
        keep.append(line)
    return "\n".join(keep), cuts


def is_video(p: Path) -> bool:
    return p.suffix.lower() in VIDEO


def main():
    IN.mkdir(exist_ok=True)
    ATT.mkdir(parents=True, exist_ok=True)
    for f in IN.glob("video.*"):
        f.unlink()
    src = (os.environ.get("SOURCE") or "").strip()
    pieces = (os.environ.get("PIECES") or "").strip()
    tag = (os.environ.get("EVENT_TAG") or "").strip()
    body = ""
    files: list[Path] = []
    if src:
        if re.search(r"(drive|docs)\.google\.com", src) or re.fullmatch(r"[A-Za-z0-9_-]{25,}", src):
            files += from_drive(src, RAW)
        elif src.startswith("http"):
            files += from_url(src, RAW)
        else:
            tag = src
    if tag and os.environ.get("GITHUB_EVENT_NAME") == "release" and not tag.lower().startswith("montage"):
        names = asset_names(tag)
        if not any(n.lower().startswith("moi") for n in names) and not re.search(DRIVE_RE, release_body(tag)):
            # release sans ta vidéo : c'est une réserve de pièces jointes pour le prochain montage
            print(f"Release {tag} : pas de fichier « moi… » ni de lien Drive → pièces jointes en attente du prochain montage")
            out("skip", "1")
            subprocess.run(["bash", "scripts/release-status.sh", tag, "wait",
                            "pièces jointes en attente : elles seront ajoutées au prochain montage (release « montage… » "
                            "ou Run workflow) dans les 3 jours"])
            return
    if tag:
        out("tag", tag)
        body = release_body(tag)
        files += from_release(tag)
    elif not src:
        # pas de source : dernière release « montage… »
        r = sh(["gh", "release", "list", "--repo", REPO, "--limit", "40", "--json", "tagName", "-q", ".[].tagName"], check=False)
        tags = [t for t in r.stdout.split() if t.lower().startswith("montage")]
        if not tags:
            die("Aucune source. Publie une release dont le tag commence par « montage » (vidéo jointe ou lien Drive dans "
                "la description), ou remplis le champ « source » du formulaire.")
        tag = tags[0]
        out("tag", tag)
        body = release_body(tag)
        files += from_release(tag)
    body, cuts = parse_cuts(body)
    extra_notes, cuts2 = parse_cuts(os.environ.get("NOTES") or "")
    cuts.update(cuts2)
    notes, opts, links = parse_body(body)
    if extra_notes.strip():
        notes = (notes + "\n" + extra_notes).strip()
    # releases de pièces jointes : citées dans le champ « pieces_jointes » (ex. « Video »), ou en attente (< 3 jours)
    named = [t for t in re.split(r"[\s,;]+", pieces) if t and not t.startswith("http")]
    consumed = []
    for t in dict.fromkeys(named + waiting_releases({tag} if tag else set())):
        if t == tag:
            continue
        got = from_release(t, RAW / f"attente_{re.sub(r'[^A-Za-z0-9_-]', '_', t)}")
        if got:
            consumed.append(t)
            files += got
            b2, c2 = parse_cuts(release_body(t))
            cuts.update(c2)
            n2, _, l2 = parse_body(b2)
            if n2.strip():
                notes = (notes + "\n" + n2).strip()
            links += l2
            print(f"Pièces jointes prises dans la release « {t} » : {', '.join(p.name for p in got)}")
    out("consumed", " ".join(consumed))
    # tout est téléchargé d'abord (release, liens Drive de la description, champ « pieces_jointes »)
    first_link: list[Path] = []
    extra = links + re.findall(DRIVE_RE, pieces) + [u for u in re.findall(r"https?://\S+", pieces) if "google.com" not in u]
    for k, u in enumerate(extra):
        got = from_drive(u, RAW / f"lien{k}") if "google.com" in u else from_url(u, RAW / f"lien{k}")
        if k == 0 and u in links:
            first_link = got
        files += got
    big = lambda fs: sorted([f for f in fs if is_video(f)], key=lambda f: f.stat().st_size, reverse=True)  # noqa: E731
    # vidéo principale :
    #   1. un fichier dont le nom commence par « moi » (moi.mp4, Moi_intro.mov…), où qu'il soit (release ou Drive) ;
    #   2. sinon la plus grosse vidéo jointe à la release (ou donnée en « source ») ;
    #   3. sinon la vidéo du premier lien Drive de la description.
    mine = big([f for f in files if f.name.lower().startswith("moi")])
    direct = big([f for f in files if not any(f.is_relative_to(RAW / f"lien{k}") for k in range(len(extra)))
                  and not f.relative_to(RAW).parts[0].startswith("attente_")])
    main_video = (mine or direct or big(first_link) or big(files) or [None])[0]
    if main_video is None:
        die("Aucune vidéo trouvée : joins ta vidéo à la release (ou colle son lien Google Drive partagé dans la description).")
    print(f"Ta vidéo : {main_video.name}" + (" (nom commençant par « moi »)" if mine else ""))
    n = 0
    for f in files:
        if f == main_video or not f.exists():
            continue
        if f.suffix.lower() in VIDEO + IMAGE:
            n += 1
            shutil.move(str(f), ATT / f"{n:02d}_{f.name}")
    ext = main_video.suffix.lower() if is_video(main_video) else ".mp4"
    dst = IN / f"video{ext}"
    shutil.move(str(main_video), dst)
    shutil.rmtree(RAW, ignore_errors=True)
    (IN / "notes.txt").write_text(notes, encoding="utf-8")
    (IN / "options.json").write_text(json.dumps(opts, ensure_ascii=False, indent=1), encoding="utf-8")
    (IN / "cuts.json").write_text(json.dumps(cuts, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, (a, b) in cuts.items():
        print(f"Passage imposé : {k} de {a:.1f} s à {b:.1f} s")
    base = re.sub(r"[^\w.-]", "_", main_video.stem)[:40] or "video"
    out("video", str(dst))
    out("base", base)
    print(f"Vidéo : {dst} ({dst.stat().st_size / 1e6:.0f} Mo) · pièces jointes : {n} · réglages : {opts or 'par défaut'}")
    if notes:
        print(f"Consignes : {notes[:300]}")
    r = sh(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", dst], check=False)
    if r.returncode != 0 or not r.stdout.strip():
        die("Le fichier n'est pas une vidéo lisible (lien Drive privé ? page web reçue à la place de la vidéo ?).")


if __name__ == "__main__":
    main()
