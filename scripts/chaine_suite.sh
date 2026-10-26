#!/usr/bin/env bash
# CHAÎNE (fond vert → montage → shorts) : publie le montage puis lance les Shorts dans Push-overlay.
# Ne touche à rien de tes montages manuels (release « out-montage », dossier Drive « derniers ») :
#   - montage → Google Drive chaine/<id>/montage-<nom>.mp4 (privé, transmis aux Shorts, supprimé après 2 jours)
#   - montage + PLAN.md → release « out-chaine-<id> » (supprimée après 2 jours) ;
#     au-delà de 1,9 Go : copie gardée sur Drive dans Montage-LV-final/chaine-<id>/ (GitHub refuse > 2 Go)
#   - fichiers pris dans « montage-joints » → retirés du dossier (corbeille Drive : récupérables 30 jours)
#   - Shorts lancés avec un « bon de livraison » (identifiant Drive de la vidéo)
# Variables : CHAINE_ID, BASE, RCLONE_CONF, CHAINE_JOINTS, CHAINE_GH_TOKEN, REPO, GH_TOKEN (github.token)
set -uo pipefail
F=output/montage-final.mp4
SUM="${GITHUB_STEP_SUMMARY:-/dev/stdout}"
CIBLE_REPO="${CHAINE_SHORTS_REPO:-MaxMcNeil/Push-overlay}"
JOINTS="${CHAINE_JOINTS:-montage-joints}"
TAG="out-chaine-$CHAINE_ID"
err() { echo "::error title=Chaîne::$*"; { echo "### ❌ Chaîne arrêtée après le montage"; echo "$*"; } >> "$SUM"; exit 1; }

[ -s "$F" ] || err "Aucune vidéo rendue"
MB=$(( $(stat -c %s "$F") / 1048576 ))
if head -1 output/PLAN.md 2>/dev/null | grep -q "✅"; then VERDICT="✅ prêt à publier"; else VERDICT="⚠ à vérifier (voir PLAN.md)"; fi
NAME="montage-${BASE:-video}.mp4"
cp "$F" "output/$NAME"

[ -n "${RCLONE_CONF:-}" ] || err "secret RCLONE_CONF absent"
for _i in 1 2 3; do command -v rclone >/dev/null && break; curl -sSf --retry 3 https://rclone.org/install.sh | sudo bash >/dev/null 2>&1 || sleep 5; done
mkdir -p ~/.config/rclone && printf '%s\n' "$RCLONE_CONF" > ~/.config/rclone/rclone.conf
REMOTE=$(grep -m1 -oE '^\[[^]]+\]' ~/.config/rclone/rclone.conf | tr -d '[]')
[ -n "$REMOTE" ] || err "RCLONE_CONF illisible"

echo "Ménage : sorties de chaîne de plus de 2 jours (releases out-chaine-…, Drive chaine/)"
gh release list --repo "$REPO" --limit 100 --json tagName,createdAt \
  -q '.[] | select(.tagName | startswith("out-chaine-")) | select(.createdAt < (now - 2*86400 | todate)) | .tagName' 2>/dev/null \
  | while read -r t; do [ -n "$t" ] && { echo "  supprimée : $t"; gh release delete "$t" --repo "$REPO" -y --cleanup-tag || true; }; done
rclone delete "$REMOTE:chaine" --min-age 2d --drive-use-trash=false -q 2>/dev/null || true
rclone rmdirs "$REMOTE:chaine" --leave-root -q 2>/dev/null || true

# 1) vidéo pour les Shorts : Google Drive (privé)
DST="$REMOTE:chaine/$CHAINE_ID/$NAME"
rclone copyto "output/$NAME" "$DST" --retries 5 --drive-chunk-size 64M || err "envoi Google Drive impossible"
L=$(stat -c %s "output/$NAME")
R=$(rclone size "$DST" --json | python3 -c 'import sys,json;print(json.load(sys.stdin)["bytes"])')
[ "$L" = "$R" ] || err "taille différente après envoi ($L / $R octets)"
FID=$(rclone lsjson "$DST" --no-mimetype | python3 -c 'import sys,json;a=json.load(sys.stdin);print(a[0].get("ID","") if a else "")')
[ -n "$FID" ] || err "identifiant Google Drive introuvable"

# 2) résultat visible : release out-chaine-<id> (ou Drive si trop lourd)
OU=""
{ echo "## $VERDICT"; echo; echo "🔗 **Chaîne \`$CHAINE_ID\`** — montage terminé ($(date -u +%d/%m/%Y)). Release supprimée automatiquement après 2 jours."
  echo; echo "Les Shorts de ce montage arrivent dans Push-overlay, release \`$TAG\`."
  [ -n "${CHAINE_ORIGINE:-}" ] && echo "Fond vert : ${CHAINE_ORIGINE}"
  echo; echo "---"; echo; head -c 110000 output/PLAN.md; } > /tmp/notes-chaine.md
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
fi
if [ -z "$OU" ]; then
  KEEP="${GDRIVE_FOLDER:-Montage-LV-final}/chaine-$CHAINE_ID"
  rclone copyto "$DST" "$REMOTE:$KEEP/$NAME" -q && rclone copy output/PLAN.md "$REMOTE:$KEEP" -q && OU="Google Drive, dossier $KEEP" \
    || { echo "artifact=1" >> "${GITHUB_OUTPUT:-/dev/null}"; OU="Artifacts de ce run (14 jours)"; }
fi

# 3) lancer les Shorts
[ -n "${CHAINE_GH_TOKEN:-}" ] || err "jeton de chaîne absent (variable CHAINE_APP_ID + secret CHAINE_APP_KEY, ou secret CHAINE_TOKEN, dans montage-lv-final). Montage publié : $OU"
python3 - "$CHAINE_ID" "$FID" "$NAME" "https://github.com/$REPO/actions/runs/${GITHUB_RUN_ID:-0}" > bon-shorts.json <<'PY'
import json, sys
i, fid, nom, origine = sys.argv[1:5]
print(json.dumps({"event_type": "chaine-shorts", "client_payload": {
    "v": 1, "chaine_id": i, "video_id": fid, "video_nom": nom, "origine": origine}}, ensure_ascii=False))
PY
rclone copyto bon-shorts.json "$REMOTE:chaine/$CHAINE_ID/bon-shorts.json" -q || true
OK=0
for i in 1 2 3 4; do
  if GH_TOKEN="$CHAINE_GH_TOKEN" gh api "repos/$CIBLE_REPO/dispatches" --input bon-shorts.json >/dev/null 2>dispatch.err; then OK=1; break; fi
  echo "::warning::lancement des Shorts : essai $i échoué ($(tail -1 dispatch.err))"; sleep $((i * 10))
done
[ "$OK" = 1 ] || err "Shorts non lancés : $(tail -2 dispatch.err | tr '\n' ' '). Le jeton a-t-il « Contents : read and write » sur push-overlay ? Montage publié : $OU"

# 4) dossier montage-joints : on retire seulement les fichiers réellement utilisés — APRÈS le lancement des Shorts,
#    pour qu'un « Re-run » retrouve les mêmes fichiers si quelque chose a échoué avant
if [ -s input/joints-utilises.txt ]; then
  rclone delete "$REMOTE:$JOINTS" --files-from input/joints-utilises.txt -q \
    && echo "Dossier « $JOINTS » vidé ($(wc -l < input/joints-utilises.txt) fichier(s), corbeille Drive)." \
    || echo "::warning::Le dossier « $JOINTS » n'a pas pu être vidé : retire ces fichiers à la main avant la prochaine vidéo."
fi

MSG="$VERDICT — montage ($MB Mo) → $OU · Shorts lancés dans Push-overlay"
{ echo "### ✅ 🔗 Chaîne \`$CHAINE_ID\` — $MSG"
  [ -s input/joints-utilises.txt ] && { echo; echo "Fichiers pris dans « $JOINTS » :"; sed 's/^/- /' input/joints-utilises.txt; }
  echo; cat output/PLAN.md; } >> "$SUM"
echo "::notice title=Chaîne $CHAINE_ID::$MSG"
