#!/usr/bin/env bash
# Dépose le montage (output/montage-final.mp4) et son plan (PLAN.md, plan.json) :
#   - Google Drive (si le secret RCLONE_CONF existe) : TOUJOURS une copie dans le dossier des résultats
#     (variable RCLONE_DEST, sinon « <ton stockage>:resultats », comme le dépôt fond vert) — quelle que soit la taille ;
#   - release GitHub « out-montage » si < 1,9 Go (une seule : chaque nouveau montage remplace le précédent) ;
#   - si ni Drive ni release : Artifacts du run (14 jours).
# Tes releases déposées (vidéos « montage… », pièces jointes) ne sont JAMAIS supprimées automatiquement :
# seul l'état de leur titre change (✅ TERMINÉ…). Tu les supprimes toi-même quand tu veux.
# Dossier Drive montage-joints : seuls les fichiers réellement pris par CE montage sont retirés (corbeille Drive,
# récupérables 30 jours), et seulement si le montage a bien été déposé quelque part.
set -uo pipefail
F=output/montage-final.mp4
SUM="${GITHUB_STEP_SUMMARY:-/dev/stdout}"
TAG_OUT="out-montage"
[ -s "$F" ] || { echo "::error::Aucune vidéo rendue"; exit 1; }
MB=$(( $(stat -c %s "$F") / 1048576 ))
# verdict du contrôle qualité (1re ligne de PLAN.md) : affiché dans le titre du résultat et l'état de ta release
if head -1 output/PLAN.md 2>/dev/null | grep -q "✅"; then VERDICT="✅ prêt à publier"; else VERDICT="⚠ à vérifier (voir PLAN.md)"; fi
NAME="montage-${BASE:-video}.mp4"
cp "$F" "output/$NAME"

for t in ${CONSUMED:-}; do  # releases de pièces jointes utilisées : gardées (pour relancer), marquées ✅
  bash scripts/release-status.sh "$t" ok "pièces jointes utilisées par le montage du $(date -u +%d/%m/%Y) — réutilisables en écrivant « $t » dans le champ pieces_jointes" || true
done

# ---------- Google Drive : toujours une copie dans le dossier des résultats ----------
OU=()
REMOTE=""
if [ -n "${RCLONE_CONF:-}" ]; then
  for _i in 1 2 3; do command -v rclone >/dev/null && break; curl -sSf --retry 3 https://rclone.org/install.sh | sudo bash >/dev/null 2>&1 || sleep 5; done
  mkdir -p ~/.config/rclone && printf '%s\n' "$RCLONE_CONF" > ~/.config/rclone/rclone.conf
  REMOTE=$(grep -m1 -oE '^\[[^]]+\]' ~/.config/rclone/rclone.conf | tr -d '[]')
  DEST_DIR="${RCLONE_DEST:-}"
  [ -n "$DEST_DIR" ] || DEST_DIR="$REMOTE:resultats"
  case "$DEST_DIR" in *:*) DEST_DIR="$REMOTE:${DEST_DIR#*:}";; *) DEST_DIR="$REMOTE:$DEST_DIR";; esac   # bon nom de stockage
  if command -v rclone >/dev/null && [ -n "$REMOTE" ]; then
    if rclone copyto "output/$NAME" "$DEST_DIR/$NAME" --retries 5 --drive-chunk-size 64M -q; then
      L=$(stat -c %s "output/$NAME")
      R=$(rclone size "$DEST_DIR/$NAME" --json 2>/dev/null | python3 -c 'import sys,json;print(json.load(sys.stdin)["bytes"])' 2>/dev/null || echo 0)
      if [ "$L" = "$R" ]; then
        rclone copyto output/PLAN.md "$DEST_DIR/${NAME%.mp4}-PLAN.md" -q || true
        OU+=("Google Drive \`$DEST_DIR/$NAME\`")
      else
        echo "::warning::Copie Google Drive incomplète ($L / $R octets)"
      fi
    else
      echo "::warning::Copie Google Drive impossible (espace plein ? jeton RCLONE_CONF expiré ?)"
    fi
  else
    echo "::warning::rclone indisponible : pas de copie Google Drive"
  fi
fi

# ---------- Release GitHub (si < 1,9 Go) ----------
if [ "$MB" -lt "${RELEASE_MAX_MB:-1900}" ]; then
  for t in $(gh release list --repo "$REPO" --limit 100 --json tagName -q '.[].tagName' | grep -E '^out-montage$' || true); do
    gh release delete "$t" --repo "$REPO" -y --cleanup-tag || true
  done
  { echo "## $VERDICT"; echo; echo "🎬 **Ton dernier montage** ($(date -u +%d/%m/%Y)) — remplacé à chaque nouveau montage."
    [ ${#OU[@]} -gt 0 ] && { echo; echo "Copie aussi sur ${OU[0]}."; }
    echo; echo "**Nouveau montage** : Releases → *Draft a new release* → tag \`montage-001\`, \`montage-002\`… → joins ta vidéo (+ photos, vidéos) → *Publish*."; echo; echo "---"; echo;
    head -c 120000 output/PLAN.md; } > /tmp/notes.md
  if gh release create "$TAG_OUT" --repo "$REPO" --prerelease --title "🎬 RÉSULTAT — Montage final — $VERDICT" --notes-file /tmp/notes.md; then
    for i in 1 2 3; do
      if gh release upload "$TAG_OUT" "output/$NAME" output/PLAN.md output/plan.json --repo "$REPO" --clobber; then
        OU+=("[🎬 RÉSULTAT — Montage final](https://github.com/$REPO/releases/tag/$TAG_OUT)"); break
      fi
      sleep 8
    done
  else
    echo "::warning::Release impossible"
  fi
else
  echo "Montage de $MB Mo : trop lourd pour une release GitHub (2 Go max) → Google Drive seulement"
fi

if [ ${#OU[@]} -eq 0 ]; then
  echo "artifact=1" >> "${GITHUB_OUTPUT:-/dev/null}"
  MSG="$VERDICT — montage ($MB Mo) → onglet Actions, ce run, section Artifacts (14 jours)"
else
  MSG="$VERDICT — montage ($MB Mo) → $(IFS='|'; echo "${OU[*]}" | sed 's/|/ + /g')"
  # montage déposé : on retire de montage-joints UNIQUEMENT les fichiers pris par ce montage
  if [ -n "$REMOTE" ] && [ -s input/joints-utilises.txt ]; then
    JD="${JOINTS_DOSSIER:-montage-joints}"
    rclone delete "$REMOTE:$JD" --files-from input/joints-utilises.txt -q \
      && echo "Dossier Drive « $JD » : $(wc -l < input/joints-utilises.txt) fichier(s) utilisé(s) retiré(s) (corbeille Drive)." \
      || echo "::warning::Le dossier « $JD » n'a pas pu être vidé : retire ces fichiers à la main avant la prochaine vidéo."
  fi
fi
{ echo "### $MSG"; echo; cat output/PLAN.md; } >> "$SUM"
bash scripts/release-status.sh "${SRC_TAG:-}" ok "$MSG"
