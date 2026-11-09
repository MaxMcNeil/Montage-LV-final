#!/data/data/com.termux/files/usr/bin/bash
# 📱 Sur ton téléphone (Termux) : récupère les vidéos que YouTube a refusées à GitHub (« Préparer les médias ») et
#    les dépose dans ton dossier Drive (montage-joints). Ton téléphone n'est pas bloqué par YouTube.
#
#   Une seule fois :  pkg install -y python ffmpeg rclone jq && pip install -U yt-dlp
#                     (+ rclone configuré sur le MÊME compte Google que tes workflows : « rclone listremotes »)
#   Puis :
#     curl -fsSL https://raw.githubusercontent.com/MaxMcNeil/Montage-LV-final/main/scripts/tel_videos.sh -o ~/tel_videos.sh
#     bash ~/tel_videos.sh veille     ← RECOMMANDÉ : laisse Termux ouvert, il s'occupe de tout, tout seul
#     bash ~/tel_videos.sh            ← une seule fois, maintenant
#
# Mode « veille » : toutes les 2 minutes, regarde sur Drive si « Préparer les médias » a laissé des vidéos bloquées ;
# si oui, les télécharge (720p max), les dépose dans le dossier Drive, et prévient le Montage (qui l'attend 20 min max).
# Fichiers Drive « sources-medias/ » : a-telecharger.txt (liste), telephone-demande.txt (écrit par GitHub),
# telephone-veille.txt (« je suis là », écrit ici), telephone-fini.txt (« c'est déposé », écrit ici).
set -uo pipefail
MODE="${1:-une-fois}"
REMOTE="${REMOTE:-$(rclone listremotes 2>/dev/null | head -1 | tr -d ':')}"
[ -n "$REMOTE" ] || { echo "❌ rclone n'est pas configuré sur ce téléphone (rclone config, même compte Google)"; exit 1; }
command -v yt-dlp >/dev/null || { echo "❌ yt-dlp absent : pip install -U yt-dlp"; exit 1; }
command -v ffmpeg >/dev/null || { echo "❌ ffmpeg absent : pkg install ffmpeg"; exit 1; }
W="$HOME/medias-tel"; mkdir -p "$W"; cd "$W" || exit 1
SM="$REMOTE:sources-medias"
FRAIS=$((3 * 3600))   # une demande de plus de 3 h est ignorée (jamais de vidéo déposée dans le montage suivant)

passe() { # $1 = numéro de la demande GitHub (ou « main ») ; $2 = dossier Drive
  local run="$1" dossier="${2:-montage-joints}" dest nom cible duree OK=0 KO=0
  if [[ "$dossier" =~ ^[A-Za-z0-9_-]{25,}$ ]]; then dest="$REMOTE,root_folder_id=$dossier:"; else dest="$REMOTE:${dossier#*:}"; fi
  rclone copyto "$SM/a-telecharger.txt" liste.txt -q 2>/dev/null || : > liste.txt
  if ! grep -q '[^[:space:]]' liste.txt; then
    echo "✅ Rien à télécharger : toutes les vidéos sont déjà là."
  else
    echo "📥 $(grep -c '[^[:space:]]' liste.txt) vidéo(s) à récupérer → « $dossier »"
    : > reste.txt
    while IFS='|' read -r nom cible duree; do
      nom=$(echo "$nom" | xargs); cible=$(echo "$cible" | xargs); duree=$(echo "${duree:-900}" | xargs)
      [[ -z "$nom" || "$nom" == \#* ]] && continue
      [[ "$cible" == http* ]] || cible="ytsearch10:$cible"
      rm -f "$nom.mp4"; echo "→ $nom"
      yt-dlp -q --no-warnings --no-playlist --max-downloads 1 --max-filesize 400M \
        --match-filter "duration < ${duree:-900} & !is_live" --retries 5 \
        -f "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720]/b" --merge-output-format mp4 -o "$nom.mp4" "$cible" >/dev/null 2>&1
      if [ -s "$nom.mp4" ] && rclone copy "$nom.mp4" "$dest" -q; then
        echo "  ✅ déposée"; OK=$((OK+1)); rm -f "$nom.mp4"
      else
        echo "  ⚠ échec"; KO=$((KO+1)); printf '%s | %s | %s\n' "$nom" "${cible#ytsearch10:}" "$duree" >> reste.txt
      fi
    done < liste.txt
    rclone copyto reste.txt "$SM/a-telecharger.txt" -q || true
    echo "Terminé : $OK déposée(s), $KO en échec."
  fi
  echo "$run $(date +%s) ok=$OK ko=$KO" > fini.txt
  rclone copyto fini.txt "$SM/telephone-fini.txt" -q || true   # le Montage arrête d'attendre
}

demande() { # lit « numéro époque dossier » écrit par GitHub
  rclone cat "$SM/telephone-demande.txt" 2>/dev/null | head -1
}

if [ "$MODE" != veille ]; then
  read -r run t dossier <<< "$(demande)"
  passe "${run:-main}" "${dossier:-montage-joints}"
  echo "Tu peux lancer (ou laisser tourner) le Montage."
  exit 0
fi

command -v termux-wake-lock >/dev/null && termux-wake-lock   # le téléphone ne s'endort pas pendant la veille
echo "👂 Veille active : laisse Termux ouvert. Je surveille « Préparer les médias » toutes les 2 minutes."
echo "   (pour arrêter : Ctrl+C, ou ferme Termux)"
fait=$(cat .derniere 2>/dev/null || echo "")
while true; do
  date +%s > veille.txt; rclone copyto veille.txt "$SM/telephone-veille.txt" -q 2>/dev/null || true
  read -r run t dossier <<< "$(demande)"
  if [ -n "${run:-}" ] && [ "$run" != "$fait" ] && [ $(( $(date +%s) - ${t:-0} )) -lt "$FRAIS" ]; then
    echo; echo "🔔 $(date +%H:%M) Nouvelle demande de GitHub (lancement $run)"
    passe "$run" "${dossier:-montage-joints}"
    fait="$run"; echo "$fait" > .derniere
    echo "👂 Je continue de surveiller…"
  fi
  sleep 120
done
