#!/data/data/com.termux/files/usr/bin/bash
# 📱 Sur ton téléphone (Termux) : télécharge les vidéos que YouTube a refusées à GitHub (« Récupérer médias ») et
#    les dépose dans le dossier Drive montage-joints. Ton téléphone n'est pas bloqué par YouTube.
#
#   Une seule fois :  pkg install -y python ffmpeg rclone jq && pip install -U yt-dlp
#                     (+ rclone configuré sur le MÊME compte Google que tes workflows : « rclone listremotes »)
#   Ensuite, à chaque fois :
#     curl -fsSL https://raw.githubusercontent.com/MaxMcNeil/Montage-LV-final/main/scripts/tel_videos.sh -o ~/tel_videos.sh
#     bash ~/tel_videos.sh
#
# Lit Drive « sources-medias/a-telecharger.txt » (nom | url ou recherche | durée max), télécharge en 720p au plus,
# envoie dans montage-joints, puis retire de la liste ce qui est réussi (relance sans risque : rien n'est doublé).
set -uo pipefail
REMOTE="${REMOTE:-$(rclone listremotes 2>/dev/null | head -1 | tr -d ':')}"
DOSSIER="${DOSSIER:-montage-joints}"
[ -n "$REMOTE" ] || { echo "❌ rclone n'est pas configuré sur ce téléphone (rclone config, même compte Google)"; exit 1; }
command -v yt-dlp >/dev/null || { echo "❌ yt-dlp absent : pip install -U yt-dlp"; exit 1; }
command -v ffmpeg >/dev/null || { echo "❌ ffmpeg absent : pkg install ffmpeg"; exit 1; }
W="$HOME/medias-tel"; mkdir -p "$W"; cd "$W" || exit 1
rclone copyto "$REMOTE:sources-medias/a-telecharger.txt" liste.txt -q 2>/dev/null || : > liste.txt
if [ ! -s liste.txt ]; then echo "✅ Rien à télécharger : toutes les vidéos sont déjà dans « $DOSSIER »."; exit 0; fi
echo "📥 $(grep -c . liste.txt) vidéo(s) à récupérer (stockage « $REMOTE »)"
: > reste.txt; OK=0; KO=0
while IFS='|' read -r nom cible duree; do
  nom=$(echo "$nom" | xargs); cible=$(echo "$cible" | xargs); duree=$(echo "${duree:-900}" | xargs)
  [ -z "$nom" ] && continue
  [[ "$cible" == http* ]] || cible="ytsearch10:$cible"
  rm -f "$nom.mp4"
  echo "→ $nom"
  yt-dlp -q --no-warnings --no-playlist --max-downloads 1 --max-filesize 400M \
    --match-filter "duration < ${duree:-900} & !is_live" --retries 5 \
    -f "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720]/b" --merge-output-format mp4 -o "$nom.mp4" "$cible" >/dev/null 2>&1
  if [ -s "$nom.mp4" ] && rclone copy "$nom.mp4" "$REMOTE:$DOSSIER" -q; then
    echo "  ✅ envoyée dans « $DOSSIER »"; OK=$((OK+1)); rm -f "$nom.mp4"
  else
    echo "  ⚠ échec (gardée dans la liste pour la prochaine fois)"; KO=$((KO+1))
    printf '%s | %s | %s\n' "$nom" "${cible#ytsearch10:}" "$duree" >> reste.txt
  fi
done < liste.txt
rclone copyto reste.txt "$REMOTE:sources-medias/a-telecharger.txt" -q || true
echo; echo "Terminé : $OK envoyée(s), $KO en échec. Tu peux lancer le Montage."
