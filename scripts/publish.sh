#!/usr/bin/env bash
# Dépose le montage (output/montage-final.mp4) et son plan (PLAN.md, plan.json) :
#   - < 1,9 Go : release GitHub « out-montage » (une seule : chaque nouveau montage remplace le précédent) ;
#   - au-delà (GitHub refuse > 2 Go) : Google Drive (secret RCLONE_CONF), dossier Montage-LV-final/derniers (remplacé) ;
#   - en dernier recours : Artifacts du run (14 jours).
# Supprime aussi les anciennes vidéos déposées (releases « montage… »), sauf celle qui vient d'être traitée.
set -uo pipefail
F=output/montage-final.mp4
SUM="${GITHUB_STEP_SUMMARY:-/dev/stdout}"
TAG_OUT="out-montage"
[ -s "$F" ] || { echo "::error::Aucune vidéo rendue"; exit 1; }
MB=$(( $(stat -c %s "$F") / 1048576 ))
NAME="montage-${BASE:-video}.mp4"
cp "$F" "output/$NAME"

for t in $(gh release list --repo "$REPO" --limit 100 --json tagName -q '.[].tagName' | grep -E '^out-montage' || true); do
  gh release delete "$t" --repo "$REPO" -y --cleanup-tag || true
done
for t in $(gh release list --repo "$REPO" --limit 100 --json tagName -q '.[].tagName' | grep -iE '^montage' || true); do
  [ "$t" = "${SRC_TAG:-}" ] && continue
  echo "Suppression de l'ancienne vidéo déposée : $t"; gh release delete "$t" --repo "$REPO" -y --cleanup-tag || true
done

for t in ${CONSUMED:-}; do  # releases de pièces jointes utilisées : gardées (pour relancer), marquées ✅
  bash scripts/release-status.sh "$t" ok "pièces jointes utilisées par le montage du $(date -u +%d/%m/%Y) — réutilisables en écrivant « $t » dans le champ pieces_jointes" || true
done
# releases de pièces jointes de plus de 7 jours : supprimées (le dépôt ne grossit pas)
gh release list --repo "$REPO" --limit 100 --json tagName,createdAt -q '.[] | select(.createdAt < (now - 7*86400 | todate)) | .tagName' 2>/dev/null \
  | grep -viE '^(montage|out-)' | while read -r t; do
    [ -n "$t" ] || continue
    echo "Ancienne release de pièces jointes supprimée : $t"; gh release delete "$t" --repo "$REPO" -y --cleanup-tag || true
  done

DEST=""
if [ "$MB" -lt "${RELEASE_MAX_MB:-1900}" ]; then
  { echo "🎬 **Ton dernier montage** ($(date -u +%d/%m/%Y)) — remplacé à chaque nouveau montage."; echo;
    echo "**Nouveau montage** : Releases → *Draft a new release* → tag \`montage-001\`, \`montage-002\`… → joins ta vidéo (+ photos, vidéos) → *Publish*."; echo; echo "---"; echo;
    head -c 120000 output/PLAN.md; } > /tmp/notes.md
  gh release create "$TAG_OUT" --repo "$REPO" --prerelease --title "🎬 RÉSULTAT — Montage final" --notes-file /tmp/notes.md \
    && for i in 1 2 3; do gh release upload "$TAG_OUT" "output/$NAME" output/PLAN.md output/plan.json --repo "$REPO" --clobber && break; sleep 8; done \
    && DEST="release" || echo "::warning::Release impossible, essai Google Drive"
fi
if [ -z "$DEST" ] && [ -n "${RCLONE_CONF:-}" ]; then
  command -v rclone >/dev/null || curl -sSf https://rclone.org/install.sh | sudo bash >/dev/null
  mkdir -p ~/.config/rclone && printf '%s\n' "$RCLONE_CONF" > ~/.config/rclone/rclone.conf
  REMOTE=$(grep -m1 -oE '^\[[^]]+\]' ~/.config/rclone/rclone.conf | tr -d '[]')
  DIR="${GDRIVE_FOLDER:-Montage-LV-final}/derniers"
  rclone delete "$REMOTE:$DIR" -q 2>/dev/null || true
  rclone copy "output/$NAME" "$REMOTE:$DIR" --retries 3 -q && rclone copy output/PLAN.md "$REMOTE:$DIR" -q && DEST="drive"
fi
case "$DEST" in
  release) MSG="Montage prêt ($MB Mo) → [🎬 RÉSULTAT — Montage final](https://github.com/$REPO/releases/tag/$TAG_OUT)";;
  drive)   MSG="Montage prêt ($MB Mo) → Google Drive, dossier ${GDRIVE_FOLDER:-Montage-LV-final}/derniers";;
  *)       MSG="Montage prêt ($MB Mo) → onglet Actions, ce run, section Artifacts (14 jours)"; echo "artifact=1" >> "${GITHUB_OUTPUT:-/dev/null}";;
esac
{ echo "### ✅ $MSG"; echo; cat output/PLAN.md; } >> "$SUM"
bash scripts/release-status.sh "${SRC_TAG:-}" ok "$MSG"
