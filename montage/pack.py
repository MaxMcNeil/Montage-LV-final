"""PACK D'HABILLAGE DE LA CHAÎNE (chaines/<code>/habillage/) : transitions, raccords, invitation like/abonnement et
écran de fin, posés sur la vidéo MONTÉE en une passe finale. Seulement :
  - pour la chaîne dont c'est le pack (ton logo n'apparaît que sur les vidéos de sa langue) ;
  - en horizontal (le pack est en 16:9 : les Shorts et les vidéos verticales ne changent pas).

Placement (jamais sur un extrait, une carte à côté de toi ou un titre) :
  - TRANSITION au changement de chapitre (au plus 3), juste avant le titre du chapitre ;
  - RACCORD discret sur quelques vraies coupes (au plus 3, espacées d'au moins 1 min 30) ;
  - INVITATION like / abonnement UNE fois, entre 45 s et 2 min 30, quand tu es seul à l'écran ;
  - ÉCRAN DE FIN 20 s collé après la fin de ta vidéo (rien n'est coupé).
Variété d'une vidéo à l'autre : le style des transitions et des raccords, et le moment de l'invitation, changent
selon la vidéo. Le « Tampon NON » (comique) : au plus une fois, seulement sur une coupe où tu dis « non ».
Son du pack : déjà grave et bas ; on coupe en plus tout aigu (> 3,5 kHz) par sécurité. Jamais bloquant."""
from __future__ import annotations

import hashlib
import logging
import random
import re
import subprocess
from pathlib import Path

log = logging.getLogger("montage.pack")

ROOT = Path(__file__).resolve().parents[1]
TRANS = {"T1": ("T1_Transition_Tricolore", 0.60), "T2": ("T2_Transition_Iris-Logo", 0.50),
         "T3": ("T3_Transition_Coup-de-Sabre", 0.40)}
RACC = {"R1": ("R1_Raccord_Flash-Logo", 0.13), "R2": ("R2_Raccord_Tampon-NON", 0.13),
        "R3": ("R3_Raccord_Glitch-Tricolore", 0.17)}
CTA = ("CTA_Like-Abonne-toi", 7.0)
FIN = "ECRAN-DE-FIN_20s.mp4"
# Animations posées SANS leur son : la clochette « tiiin » du like/abonnement (note tenue 220 → 440 Hz pendant 3 s)
# déplaît à ton audience.
MUET = {"CTA_Like-Abonne-toi"}


def find(code: str) -> Path | None:
    """Dossier du pack de la chaîne, s'il est complet (sinon None : montage sans pack, comme avant)."""
    if not code:
        return None
    d = ROOT / "chaines" / code / "habillage"
    need = [f"{n}_ALPHA.webm" for n, _ in list(TRANS.values()) + list(RACC.values())] + [f"{CTA[0]}_ALPHA.webm", FIN]
    if d.is_dir() and all((d / f).exists() for f in need):
        return d
    return None


def _busy(segs) -> list[tuple[float, float]]:
    """Plages où l'écran est déjà occupé (extrait, carte à côté de toi)."""
    return [(s.out0, s.out0 + s.dur) for s in segs if s.kind in ("insert", "split")]


def _free(t0: float, t1: float, busy, chap_times, margin: float = 1.0) -> bool:
    if any(a - margin < t1 and t0 < b + margin for a, b in busy):
        return False
    return not any(t0 - 1.0 < c < t1 + 5.5 for c in chap_times)   # jamais sur un titre de chapitre


def plan(segs, chap_times: list, words: list, total: float, name: str) -> list[dict]:
    """Événements [{"kind", "file", "t", "dur"}] (t = début dans la vidéo montée)."""
    rnd = random.Random(int(hashlib.md5(name.encode()).hexdigest()[:8], 16))
    busy = _busy(segs)
    ev: list[dict] = []
    # 1) transitions de chapitre : un style principal par vidéo (+ un second), au plus 3
    styles = list(TRANS)
    rnd.shuffle(styles)
    for k, c in enumerate([c for c in sorted(chap_times) if 8.0 < c < total - 25.0][:3]):
        st = styles[0] if k % 2 == 0 else styles[1]
        fname, cut = TRANS[st]
        t = c - 0.25 - cut                      # tout l'écran couvert juste avant le titre du chapitre
        if t > 3 and not any(a - 0.5 < t + 1.3 and t < b + 0.5 for a, b in busy):
            ev.append({"kind": "transition", "file": fname, "t": t, "dur": 1.25, "style": st})
    # 2) raccords sur de VRAIES coupes (saut dans ta vidéo, sans fondu), au plus 3, espacés d'au moins 90 s
    cuts = []
    for s in segs:
        if s.kind != "full":
            continue
        t = s.out0
        prev = None
        for at in s.atoms:
            if prev is not None and abs(at.a - prev.b) > 0.3 and not (getattr(at, "xin", 0) or 0):
                cuts.append((t, at.a))
            t += round((at.b - at.a) * 30) / 30
            prev = at
    r_styles = ["R1", "R3"]
    rnd.shuffle(r_styles)
    stamp_used = False
    first_cut = rnd.uniform(20.0, 110.0)        # le 1er raccord ne tombe pas au même moment d'une vidéo à l'autre
    taken = [e["t"] for e in ev]
    for t, src_t in sorted(cuts, key=lambda c: c[0]):
        if len([e for e in ev if e["kind"] == "raccord"]) >= 3:
            break
        if t < first_cut or t > total - 25 or any(abs(t - x) < 90 for x in taken):
            continue
        if not _free(t - 0.6, t + 1.0, busy, chap_times, 0.6):
            continue
        said = " ".join(w.get("w", "") for w in words if src_t - 2.0 <= w.get("t0", -9) <= src_t + 0.5).lower()
        if not stamp_used and re.search(r"\bnon\b", said):
            st, stamp_used = "R2", True                 # « NON » prononcé juste là : le tampon, une seule fois
        else:
            st = r_styles[len([e for e in ev if e["kind"] == "raccord"]) % 2]
        fname, cut = RACC[st]
        ev.append({"kind": "raccord", "file": fname, "t": t - cut, "dur": 0.95, "style": st})
        taken.append(t)
    # 3) invitation like / abonnement : une fois, quand tu es seul à l'écran (7 s libres)
    starts = [45.0 + 15.0 * i for i in range(8)]
    rnd.shuffle(starts)
    for t in starts + [x for x in range(150, int(total * 0.45), 10)]:
        if t + 7.5 < total - 25 and _free(t, t + CTA[1], busy, chap_times) and not any(abs(t - x) < 8 for x in taken):
            ev.append({"kind": "cta", "file": CTA[0], "t": float(t), "dur": CTA[1]})
            break
    return sorted(ev, key=lambda e: e["t"])


def _size(p: Path) -> tuple[int, int]:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                        "-of", "csv=p=0", str(p)], capture_output=True, text=True)
    try:
        w, h = r.stdout.strip().split(",")[:2]
        return int(w), int(h)
    except ValueError:
        return 0, 0


def apply(final: Path, events: list, pack_dir: Path, work: Path, end_screen: bool = True) -> tuple[bool, str]:
    """Pose les animations et colle l'écran de fin. Remplace `final` seulement si tout a réussi."""
    if not events and not end_screen:
        return False, "rien à poser"
    W, H = _size(final)
    if W < H or W < 640:                       # le pack est en 16:9 : jamais sur une vidéo verticale
        return False, "vidéo non horizontale : pack non appliqué"
    out = work / "montage-habille.mp4"
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(final)]
    for e in events:
        cmd += ["-itsoffset", f"{e['t']:.3f}", "-c:v", "libvpx-vp9", "-i", str(pack_dir / f"{e['file']}_ALPHA.webm")]
    n = len(events)
    snd = []
    for e in events:
        w = pack_dir / "sons" / f"{e['file']}.wav"
        snd.append(w if w.exists() and e["file"] not in MUET else None)
    for w in snd:
        if w:
            cmd += ["-i", str(w)]
    if end_screen:
        cmd += ["-i", str(pack_dir / FIN)]
    g, v = [], "[0:v]"
    for k, e in enumerate(events, 1):
        if e["kind"] == "cta":
            # like / abonnement : réduit et remonté AU-DESSUS des sous-titres (en bas à gauche, sous ton visage)
            cw = int(round(1140 * 0.62 * W / 1920 / 2)) * 2
            g.append(f"[{k}:v]crop=1140:320:85:745,scale={cw}:-2[p{k}]")
            pos = f"x={int(W * 0.03)}:y={int(H * 0.75)}-h:"
        else:
            g.append(f"[{k}:v]scale={W}:{H}[p{k}]")
            pos = ""
        g.append(f"{v}[p{k}]overlay={pos}eof_action=pass:format=auto:enable='between(t,{e['t']:.3f},{e['t'] + e['dur'] + 0.2:.3f})'"
                 f"[v{k}]")
        v = f"[v{k}]"
    a_ins = ["[0:a]aresample=48000,aformat=channel_layouts=stereo[a0]"]
    mix, idx = ["[a0]"], n + 1
    for k, (e, w) in enumerate(zip(events, snd)):
        if not w:
            continue
        ms = int(round(e["t"] * 1000))
        a_ins.append(f"[{idx}:a]aresample=48000,aformat=channel_layouts=stereo,lowpass=f=3500,"
                     f"adelay={ms}|{ms}[s{k}]")
        mix.append(f"[s{k}]")
        idx += 1
    g += a_ins
    if len(mix) > 1:
        g.append(f"{''.join(mix)}amix=inputs={len(mix)}:duration=first:normalize=0[am]")
    else:
        g.append("[a0]anull[am]")
    if end_screen:
        e_i = idx
        g.append(f"{v}fps=30,format=yuv420p,setsar=1[vm]")
        g.append(f"[{e_i}:v]scale={W}:{H},fps=30,format=yuv420p,setsar=1[ve]")
        g.append(f"[{e_i}:a]aresample=48000,aformat=channel_layouts=stereo,lowpass=f=3500[ae]")
        g.append("[vm][am][ve][ae]concat=n=2:v=1:a=1[vo][ao]")
    else:
        g.append(f"{v}format=yuv420p[vo]")
        g.append("[am]anull[ao]")
    cmd += ["-filter_complex", ";".join(g), "-map", "[vo]", "-map", "[ao]", "-map_metadata", "0", "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=5400)
        d0 = _dur(final)
        d1 = _dur(out)
        want = d0 + (20.0 if end_screen else 0.0)
        if abs(d1 - want) > 0.5:
            return False, f"durée inattendue ({d1:.1f} s au lieu de {want:.1f} s) : vidéo laissée sans habillage"
        out.replace(final)
        return True, "ok"
    except Exception as e:  # noqa: BLE001 - jamais bloquant : la vidéo normale reste
        err = getattr(e, "stderr", b"") or b""
        return False, f"habillage du pack impossible ({type(e).__name__} {err[-200:].decode(errors='ignore')})"


def _dur(p: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0
