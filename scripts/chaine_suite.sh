#!/usr/bin/env bash
# CHAÎNE (fond vert → montage → shorts). Ne touche à rien de tes montages manuels (release « out-montage », Drive « derniers »).
#
#   chaine_suite.sh publier  (dans le job du montage)
#     - montage + PLAN.md → release « out-chaine-<id> » (supprimée après 2 jours) ; les Shorts la téléchargent
#       directement (aucune copie Google Drive : ton espace Drive n'est pas consommé) ;
#     - plus de 1,9 Go (GitHub refuse > 2 Go) → Google Drive chaine/<id>/ (privé, supprimé après 2 jours),
#       après vérification de l'espace libre ;
#     - écrit pour le job suivant : video_url ou video_id, video_nom, joints (fichiers pris dans montage-joints).
#   chaine_suite.sh lancer   (job séparé « 🔗 Chaîne — lancer les Shorts » : un échec ne refait QUE ce lancement)
#     - lance Video to Shorts dans Push-overlay, PUIS retire de montage-joints les fichiers utilisés
#       (corbeille Drive : récupérables 30 jours). Si le lancement échoue, montage-joints reste intact.
# Variables : CHAINE_ID, BASE, RCLONE_CONF, CHAINE_JOINTS, CHAINE_GH_TOKEN, REPO, GH_TOKEN (github.token),
#             VIDEO_URL / VIDEO_ID / VIDEO_NOM / JOINTS_B64 (mode lancer)
set -uo pipefail
MODE="${1:-publier}"
SUM="${GITHUB_STEP_SUMMARY:-/dev/stdout}"
CIBLE_REPO="${CHAINE_SHORTS_REPO:-MaxMcNeil/Push-overlay}"
JOINTS="${CHAINE_JOINTS:-montage-joints}"
TAG="out-chaine-${CHAINE_ID:-}"
err() { echo "::error title=Chaîne::$*"; { echo "### ❌ Chaîne arrêtée après le montage"; echo "$*"; } >> "$SUM"; exit 1; }
out() { echo "$1=$2" >> "${GITHUB_OUTPUT:-/dev/null}"; }
[ -n "${CHAINE_ID:-}" ] || err "identifiant de chaîne manquant"

rclone_pret() {
  [ -n "${RCLONE_CONF:-}" ] || return 1
  local i
  for i in 1 2 3; do command -v rclone >/dev/null && break; curl -sSf --retry 3 https://rclone.org/install.sh | sudo bash >/dev/null 2>&1 || sleep 5; done
  command -v rclone >/dev/null || return 1
  mkdir -p ~/.config/rclone && printf '%s\n' "$RCLONE_CONF" > ~/.config/rclone/rclone.conf
  REMOTE=$(grep -m1 -oE '^\[[^]]+\]' ~/.config/rclone/rclone.conf | tr -d '[]')
  [ -n "$REMOTE" ]
}

if [ "$MODE" = "publier" ]; then
  F=output/montage-final.mp4
  [ -s "$F" ] || err "Aucune vidéo rendue"
  MB=$(( $(stat -c %s "$F") / 1048576 ))
  if head -1 output/PLAN.md 2>/dev/null | grep -q "✅"; then VERDICT="✅ prêt à publier"; else VERDICT="⚠ à vérifier (voir PLAN.md)"; fi
  # nom simple (sans accents ni espaces) : utilisable tel quel dans un lien de téléchargement
  SAFE=$(python3 -c 'import re,sys,unicodedata as u;t=u.normalize("NFKD",sys.argv[1]).encode("ascii","ignore").decode();print(re.sub(r"[^A-Za-z0-9._-]+","_",t).strip("_")[:50] or "video")' "${BASE:-video}")
  NAME="montage-$SAFE.mp4"
  ln -f "$F" "output/$NAME" 2>/dev/null || cp "$F" "output/$NAME"   # lien : pas de deuxième copie sur le disque

  echo "Ménage : sorties de chaîne de plus de 2 jours"
  gh release list --repo "$REPO" --limit 100 --json tagName,createdAt \
    -q '.[] | select(.tagName | startswith("out-chaine-")) | select(.createdAt < (now - 2*86400 | todate)) | .tagName' 2>/dev/null \
    | while read -r t; do [ -n "$t" ] && { echo "  supprimée : $t"; gh release delete "$t" --repo "$REPO" -y --cleanup-tag || true; }; done
  RC=0; rclone_pret || RC=1
  if [ "$RC" = 0 ]; then
    rclone delete "$REMOTE:chaine" --min-age 2d --drive-use-trash=false -q 2>/dev/null || true
    rclone rmdirs "$REMOTE:chaine" --leave-root -q 2>/dev/null || true
  fi

  { echo "## $VERDICT"; echo; echo "🔗 **Chaîne \`$CHAINE_ID\`** — montage terminé ($(date -u +%d/%m/%Y)). Release supprimée automatiquement après 2 jours."
    echo; echo "Les Shorts de ce montage arrivent dans Push-overlay, release \`$TAG\`."
    [ -n "${CHAINE_ORIGINE:-}" ] && echo "Fond vert : ${CHAINE_ORIGINE}"
    echo; echo "---"; echo; head -c 110000 output/PLAN.md; } > /tmp/notes-chaine.md

  OU=""; URL=""; FID=""
  # 1) release out-chaine-<id> (≤ 1,9 Go)
  if [ "$MB" -lt "${RELEASE_MAX_MB:-1900}" ]; then
    if gh release view "$TAG" --repo "$REPO" >/dev/null 2>&1 \
       || gh release create "$TAG" --repo "$REPO" --prerelease --title "🔗 CHAÎNE $CHAINE_ID — Montage final — $VERDICT" --notes-file /tmp/notes-chaine.md; then
      for i in 1 2 3; do
        if gh release upload "$TAG" "output/$NAME" output/PLAN.md output/plan.json --repo "$REPO" --clobber; then
          OU="release [$TAG](https://github.com/$REPO/releases/tag/$TAG)"; break
        fi
        sleep 8
      done
    fi
    if [ -n "$OU" ]; then
      U="https://github.com/$REPO/releases/download/$TAG/$NAME"
      for i in 1 2 3 4 5; do curl -fsSIL --retry 2 -o /dev/null "$U" && { URL="$U"; break; }; sleep 6; done
      [ -n "$URL" ] || echo "::warning::lien de téléchargement de la release pas encore joignable : passage par Google Drive"
    fi
  fi
  # 2) sinon : Google Drive chaine/<id>/ (privé)
  if [ -z "$URL" ]; then
    [ "$RC" = 0 ] || { out artifact 1; err "Montage trop lourd pour une release ($MB Mo) et Google Drive indisponible (secret RCLONE_CONF / rclone). Le montage est gardé dans les Artifacts de ce run (14 jours)."; }
    L=$(stat -c %s "output/$NAME")
    LIBRE=$(rclone about "$REMOTE:" --json 2>/dev/null | python3 -c 'import sys,json
try: print(int(json.load(sys.stdin).get("free") or 0))
except Exception: print(0)')
    if [ "${LIBRE:-0}" -gt 0 ] && [ "$LIBRE" -lt $((L + 300000000)) ]; then
      out artifact 1
      err "Google Drive presque plein : $((LIBRE / 1048576)) Mo libres, il en faut $((L / 1048576 + 300)) pour transmettre le montage ($MB Mo) aux Shorts. Le montage est gardé dans les Artifacts de ce run (14 jours). Libère de la place (corbeille comprise), puis « Re-run failed jobs »."
    fi
    DST="$REMOTE:chaine/$CHAINE_ID/$NAME"
    rclone copyto "output/$NAME" "$DST" --retries 5 --low-level-retries 20 --drive-chunk-size 64M \
      || { out artifact 1; err "envoi Google Drive impossible (montage gardé dans les Artifacts de ce run)"; }
    R=$(rclone lsjson "$DST" --no-mimetype | python3 -c 'import sys,json;a=json.load(sys.stdin);print(a[0]["Size"] if a else "")')
    [ "$L" = "$R" ] || { out artifact 1; err "taille différente après envoi Drive ($L / ${R:-?} octets)"; }
    FID=$(rclone lsjson "$DST" --no-mimetype | python3 -c 'import sys,json;a=json.load(sys.stdin);print(a[0].get("ID","") if a else "")')
    [ -n "$FID" ] || { out artifact 1; err "identifiant Google Drive introuvable"; }
    rclone copy output/PLAN.md "$REMOTE:chaine/$CHAINE_ID" -q || true
    [ -n "$OU" ] || OU="Google Drive, dossier chaine/$CHAINE_ID (supprimé après 2 jours : télécharge-le)"
  fi

  out video_url "$URL"; out video_id "$FID"; out video_nom "$NAME"
  out joints "$( [ -s input/joints-utilises.txt ] && base64 -w0 input/joints-utilises.txt || true )"
  { echo "### ✅ 🔗 Chaîne \`$CHAINE_ID\` — $VERDICT — montage ($MB Mo) → $OU"
    echo; echo "Transmis aux Shorts : $([ -n "$URL" ] && echo "lien de la release" || echo "Google Drive (privé)")"
    [ -s input/joints-utilises.txt ] && { echo; echo "Fichiers pris dans « $JOINTS » (retirés une fois les Shorts lancés) :"; sed 's/^/- /' input/joints-utilises.txt; }
    echo; cat output/PLAN.md; } >> "$SUM"
  echo "::notice title=Chaîne $CHAINE_ID::$VERDICT — montage ($MB Mo) → $OU"
  exit 0
fi

[ "$MODE" = "lancer" ] || err "usage : chaine_suite.sh publier | lancer"
[ -n "${VIDEO_URL:-}" ] || [ -n "${VIDEO_ID:-}" ] || err "aucune vidéo à transmettre (le job du montage n'a rien publié)"
[ -n "${CHAINE_GH_TOKEN:-}" ] || err "jeton de chaîne absent (variable CHAINE_APP_ID + secret CHAINE_APP_KEY, ou secret CHAINE_TOKEN, dans Montage-LV-final). Le montage est publié ; corrige puis « Re-run failed jobs » (seul ce lancement est refait)."
ST="$(printf '%s' "${SHORTS_SOUS_TITRES:-oui}" | tr 'A-Z' 'a-z')"; [ "$ST" = non ] || ST=oui
python3 - "$CHAINE_ID" "${VIDEO_URL:-}" "${VIDEO_ID:-}" "${VIDEO_NOM:-montage.mp4}" "https://github.com/$REPO/actions/runs/${GITHUB_RUN_ID:-0}" "$ST" > bon-shorts.json <<'PY'
import json, sys
i, url, fid, nom, origine, st = sys.argv[1:7]
print(json.dumps({"event_type": "chaine-shorts", "client_payload": {
    "v": 2, "chaine_id": i, "video_url": url, "video_id": fid, "video_nom": nom, "origine": origine,
    "sous_titres": st}}, ensure_ascii=False))
PY
echo "Sous-titres dans les Shorts : $ST"
cat bon-shorts.json
OK=0
for i in 1 2 3 4 5; do
  if GH_TOKEN="$CHAINE_GH_TOKEN" gh api "repos/$CIBLE_REPO/dispatches" --input bon-shorts.json >/dev/null 2>dispatch.err; then OK=1; break; fi
  echo "::warning::lancement des Shorts : essai $i échoué ($(tail -1 dispatch.err))"; sleep $((i * 15))
done
[ "$OK" = 1 ] || err "Shorts non lancés : $(tail -2 dispatch.err | tr '\n' ' '). L'app « chaine-maxmcneil » a-t-elle « Contents : Read and write » et est-elle installée sur Push-overlay ? Corrige puis « Re-run failed jobs »."
echo "### ✅ 🔗 Chaîne \`$CHAINE_ID\` — Shorts lancés dans [Push-overlay](https://github.com/$CIBLE_REPO/actions)" >> "$SUM"

# dossier montage-joints : seulement les fichiers réellement utilisés, une fois les Shorts lancés (jamais bloquant)
if [ -n "${JOINTS_B64:-}" ]; then
  printf '%s' "$JOINTS_B64" | base64 -d > joints-utilises.txt 2>/dev/null || : > joints-utilises.txt
  if [ -s joints-utilises.txt ] && rclone_pret; then
    rclone delete "$REMOTE:$JOINTS" --files-from joints-utilises.txt -q \
      && echo "Dossier « $JOINTS » vidé ($(wc -l < joints-utilises.txt) fichier(s), corbeille Drive)." | tee -a "$SUM" \
      || echo "::warning::Le dossier « $JOINTS » n'a pas pu être vidé : retire ces fichiers à la main avant la prochaine vidéo."
  else
    echo "::warning::Le dossier « $JOINTS » n'a pas pu être vidé : retire ces fichiers à la main avant la prochaine vidéo."
  fi
fi
echo "::notice title=Chaîne $CHAINE_ID::Shorts lancés dans Push-overlay"
