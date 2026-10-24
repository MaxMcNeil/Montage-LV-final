#!/usr/bin/env bash
# Affiche l'état du traitement DIRECTEMENT sur la release que tu as déposée (titre + note en bas de la description) :
#   ⏳ EN COURS — <titre>   puis   ✅ TERMINÉ — <titre>   ou   ❌ ÉCHEC — <titre>
# Usage : release-status.sh <tag> <run|ok|fail> "<message>"   (REPO et GH_TOKEN dans l'environnement)
TAG="$1"; STATE="$2"; MSG="$3"
[ -n "$TAG" ] || exit 0
cur=$(gh release view "$TAG" --repo "$REPO" --json name,body 2>/dev/null) || exit 0
name=$(jq -r '.name // ""' <<<"$cur"); body=$(jq -r '.body // ""' <<<"$cur")
base=$(sed -E 's/^(⏳ EN COURS|✅ TERMINÉ|❌ ÉCHEC|📎 EN ATTENTE) — //' <<<"$name"); [ -n "$base" ] || base="$TAG"
body=$(awk '/^<!-- etat-auto -->/{exit} {print}' <<<"$body")   # retire l'ancien bloc d'état
case "$STATE" in run) p="⏳ EN COURS";; ok) p="✅ TERMINÉ";; wait) p="📎 EN ATTENTE";; *) p="❌ ÉCHEC";; esac
printf '%s\n\n<!-- etat-auto -->\n---\n**%s** — %s\n' "$body" "$p" "$MSG" > /tmp/release-body.md
gh release edit "$TAG" --repo "$REPO" --title "$p — $base" --notes-file /tmp/release-body.md >/dev/null && echo "État de la release $TAG : $p" || true
