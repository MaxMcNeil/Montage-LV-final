"""PERTINENCE : chaque photo / vidéo jointe est placée là où tu parles VRAIMENT de son sujet.

L'IA propose un endroit ; ici on vérifie, sans IA, avec les mots : noms propres et mots importants de la pièce jointe
(nom du fichier, légende, description, paroles du passage choisi) comparés à ce que tu dis autour de cet endroit.
Si un autre moment de ta vidéo correspond nettement mieux (tu y cites la personne, le lieu, le sujet), la pièce jointe
y est déplacée. Exemple : la photo « p108_le_pen » va là où tu dis « Le Pen », pas pendant le plan de rigueur de 1983.
Jamais bloquant ; toutes tes pièces jointes restent montées."""
from __future__ import annotations

import logging
import math
import re
import unicodedata

log = logging.getLogger("montage.pertinence")

STOP = set("""
avec dans pour mais donc alors aussi tout tous toute toutes cette celle celui ceux leur leurs nous vous elle elles
ils sont etre avoir fait faire plus moins tres bien encore depuis quand comme apres avant sans sous entre chez
parce quoi dont cela cest quil quelle quelque autre autres meme memes deja jamais toujours rien chose choses
annee annees fois temps jour jours monde france francais francaise gens personne personnes video photo image
portrait affiche declaration extrait journaliste interview plateau emission scene public politique homme femme
the and that this with from have about pour etait avait seront serait peut doit vont faut dire dit disait
des les une aux sur par pas qui que est son ses mes tes nos vos ont ete fin mal bon new
""".split())


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]+", " ", t)


def toks(t: str, minlen: int = 4) -> set:
    t = re.sub(r"(?<=\d)[\s.  ](?=\d{3}\b)", "", t or "")      # « 105 000 » → « 105000 »
    t = re.sub(r"(?<=[A-Za-zÀ-ÿ])(?=\d)|(?<=\d)(?=[A-Za-zÀ-ÿ])", " ", t)   # « des105000euros » → « des 105000 euros »
    out = set()
    for w in _norm(t).split():
        if w.isdigit():
            if len(w) >= 3:                     # nombres et années (105000, 1983, 2017) ; jamais « 2 », « 10 »
                out.add(w)
            continue
        if len(w) < minlen or w in STOP:
            continue
        out.add(w[:-1] if len(w) > 5 and w[-1] in "sx" else w)
    return out


def name_toks(filename: str) -> set:
    """Mots du nom de fichier (« p108_le_pen.jpg » → {pen} ; « v109_macron_orleans_2017 » → {macron, orleans, 2017})."""
    stem = re.sub(r"^\d{2}_", "", filename.rsplit(".", 1)[0])
    stem = re.sub(r"^[pva]\d{2,4}[_-]", "", stem)
    return toks(stem.replace("_", " "), minlen=3)


def _idf(sents: list) -> dict:
    df: dict = {}
    for s in sents:
        for w in toks(s.get("text", ""), 3):
            df[w] = df.get(w, 0) + 1
    n = max(1, len(sents))
    return {w: math.log(1 + n / c) for w, c in df.items()}


def _score(keys: set, window: set, idf: dict) -> float:
    return sum(idf.get(w, 0.0) for w in keys & window)


def _window(sents: list, i: int, before: int, after: int) -> set:
    w = set()
    for k in range(max(0, i - before), min(len(sents), i + after + 1)):
        w |= toks(sents[k].get("text", ""), 3)
    return w


def proper_toks(t: str) -> set:
    """Seulement les NOMS PROPRES (majuscule hors début de phrase) et les années d'une parole : le reste des mots
    prononcés dans un extrait est trop vague pour décider où il va."""
    out = set()
    for m in re.finditer(r"(?<![.!?]\s)(?<!^)\b([A-ZÀ-Ý][\w'’-]{2,})|\b((?:19|20)\d{2})\b", t or ""):
        out |= toks(m.group(1) or m.group(2), 3)
    out |= {w for w in toks(t, 3) if w.isdigit() and len(w) >= 4}    # montants et années prononcés
    return out


def best_place(keys, sents: list, cur: int, idf: dict, before: int, after: int,
               avoid: set | None = None) -> tuple[int, float, float]:
    """(meilleure phrase, son score, score de l'endroit actuel). keys : ensemble de mots, ou (mots forts, mots faibles)
    — les mots forts (nom du fichier, légende) comptent 3 fois. La phrase elle-même compte plein, les voisines moins
    (1/2, 1/4…) : un extrait va juste après la phrase où tu en parles, pas trois phrases plus loin.
    avoid : phrases déjà prises par un autre extrait."""
    if isinstance(keys, tuple):
        strong, weak = keys
        one = [3 * _score(strong, toks(x.get("text", ""), 3), idf) + _score(weak - strong, toks(x.get("text", ""), 3), idf)
               for x in sents]
    else:
        one = [_score(keys, toks(x.get("text", ""), 3), idf) for x in sents]

    def sc(i):
        tot = one[i]
        for k in range(1, before + 1):
            if i - k >= 0:
                tot += one[i - k] / (2 ** k)
        for k in range(1, after + 1):
            if i + k < len(sents):
                tot += one[i + k] / (2 ** k)
        return tot
    cur_s = sc(cur) if 0 <= cur < len(sents) else 0.0
    best_i, best_s = cur, cur_s
    for i in range(len(sents)):
        if avoid and i in avoid:
            continue
        v = sc(i)
        # à score égal, la plus proche de l'endroit proposé par l'IA
        if v > best_s + 1e-9 or (abs(v - best_s) < 1e-9 and v > 0 and abs(i - cur) < abs(best_i - cur)):
            best_i, best_s = i, v
    return best_i, best_s, cur_s


def _moved(best_s: float, cur_s: float) -> bool:
    return best_s >= 2.0 and best_s >= 2 * cur_s + 1.0


def fix_visuals(visuals: list, by_id: dict, sents: list, notes: list) -> int:
    """Tes PHOTOS : déplacées là où tu cites leur sujet (si c'est nettement mieux). Renvoie le nombre déplacé."""
    if not sents:
        return 0
    idf, n = _idf(sents), 0
    for v in visuals:
        if v.get("kind") != "attachment":
            continue
        x = by_id.get(v.get("attachment"))
        if not x:
            continue
        keys = name_toks(x.get("name", "")) | toks(v.get("label", "") + " " + x.get("label", ""), 3)
        if not keys:
            continue
        cur = int(v.get("s0") or 0)
        bi, bs, cs = best_place(keys, sents, cur, idf, 0, 0)
        if bi != cur and _moved(bs, cs):
            span = max(0, int(v.get("s1", cur)) - cur)
            v["s0"], v["s1"] = bi, min(len(sents) - 1, bi + span)
            v["trigger"] = ""
            n += 1
            notes.append(f"photo « {x.get('name')} » déplacée là où tu en parles (phrase {bi + 1} au lieu de {cur + 1})")
            log.info("pertinence : photo %s %d → %d (score %.1f → %.1f)", x.get("name"), cur, bi, cs, bs)
    return n


def fix_inserts(inserts: list, by_id: dict, sents: list, notes: list) -> int:
    """Tes VIDÉOS : placées juste après le moment où tu parles de leur sujet (nom du fichier, légende, paroles du
    passage) si c'est nettement mieux que l'endroit proposé. Renvoie le nombre déplacé."""
    if not sents:
        return 0
    idf, n = _idf(sents), 0
    for ins in inserts:
        x = by_id.get(ins.get("attachment"))
        if not x:
            continue
        a0, a1 = float(ins.get("clip_start") or 0), float(ins.get("clip_end") or 0) or 1e9
        said = " ".join(s["text"] for s in (x.get("sentences") or []) if s["t1"] > a0 and s["t0"] < a1)[:600]
        strong = name_toks(x.get("name", "")) | toks(x.get("label", ""), 4)
        weak = proper_toks(said) | toks(x.get("description", ""), 6)
        if not strong and not weak:
            continue
        keys = (strong, weak)
        cur = int(ins.get("after") if ins.get("after") is not None else -1)
        taken = {int(o["after"]) for o in inserts if o is not ins and o.get("after") is not None}
        bi, bs, cs = best_place(keys, sents, cur, idf, 2, 0, avoid=taken)
        if bi != cur and _moved(bs, cs):
            ins["after"] = bi
            n += 1
            notes.append(f"vidéo « {x.get('name')} » déplacée après le moment où tu en parles (phrase {bi + 1} au lieu "
                         f"de {cur + 1})")
            log.info("pertinence : vidéo %s après %d → %d (score %.1f → %.1f)", x.get("name"), cur, bi, cs, bs)
    return n


def link_photos_to_videos(visuals: list, inserts: list, by_id: dict, sents: list, notes: list) -> int:
    """Une photo de personne / de sujet sans endroit évident va juste avant la VIDÉO du même sujet (même nom dans les
    fichiers : « p110_lescure.jpg » ↔ « v111_lescure_amiel… »). Seulement si la photo n'est pas déjà là où tu en parles."""
    if not sents:
        return 0
    idf, n = _idf(sents), 0
    vids = []
    for ins in inserts:
        x = by_id.get(ins.get("attachment"))
        if x and ins.get("after") is not None:
            vids.append((name_toks(x.get("name", "")), int(ins["after"]), x.get("name")))
    for v in visuals:
        if v.get("kind") != "attachment":
            continue
        x = by_id.get(v.get("attachment"))
        if not x:
            continue
        nk = {w for w in name_toks(x.get("name", "")) if not w.isdigit()}
        cur = int(v.get("s0") or 0)
        if not nk or _score(nk | toks(v.get("label", ""), 3), _window(sents, cur, 0, 0), idf) >= 2.0:
            continue   # déjà là où tu en parles
        same = [(after, nm) for vk, after, nm in vids if nk & {w for w in vk if not w.isdigit()}]
        if not same:
            continue
        after, nm = min(same, key=lambda a: abs(a[0] - cur))
        if after != cur:
            span = max(0, int(v.get("s1", cur)) - cur)
            v["s0"], v["s1"], v["trigger"] = after, min(len(sents) - 1, after + span), ""
            n += 1
            notes.append(f"photo « {x.get('name')} » placée avec la vidéo du même sujet (« {nm} »)")
            log.info("pertinence : photo %s → avec la vidéo %s (phrase %d)", x.get("name"), nm, after)
    return n
