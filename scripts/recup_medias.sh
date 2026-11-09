#!/usr/bin/env bash
# Récupère les médias d'un live (vidéos, photos libres, captures d'articles) et les dépose
# dans le dossier Drive montage-joints. AUCUNE clé API utilisée (ni Gemini, ni YouTube Data) :
#   - vidéos : yt-dlp (recherche YouTube intégrée, sans API), via YT_PROXY_URL si présent
#   - photos : image principale Wikipedia/Wikimedia (licences libres, API publique sans clé)
#   - articles : capture d'écran (services gratuits mshots puis thum.io)
# Liste : une ligne par média   sujet | type | nom | url-ou-recherche | durée max (s, vidéos)
# Variables : LISTE, SUJETS (all / 1 / 1,3), DOSSIER (montage-joints ou ID de dossier Drive), RCLONE_CONF
set -uo pipefail
LISTE="${LISTE:?liste manquante}"
SUJETS="${SUJETS:-all}"
DOSSIER="${DOSSIER:-montage-joints}"
OUT="out-medias"; mkdir -p "$OUT"
SUM="${GITHUB_STEP_SUMMARY:-/dev/stdout}"
UA="Mozilla/5.0 (X11; Linux x86_64) JournalDuNON-medias/1.0"
OK=0; KO=0; : > sources.tsv; : > echecs.txt; : > a-telecharger.txt   # a-telecharger : vidéos refusées à GitHub (pour ton téléphone)

garde() { [ "$SUJETS" = all ] && return 0; [[ ",${SUJETS// /}," == *",$1,"* ]]; }
taille() { stat -c%s "$1" 2>/dev/null || echo 0; }
bon() { OK=$((OK+1)); printf '%s\t%s\t%s\n' "$1" "$2" "$3" >> sources.tsv; }
rate() { KO=$((KO+1)); echo "$1" >> echecs.txt; echo "::warning::$1"; }

photo() { # nom "lang:Titre_Wikipedia"
  local f="$OUT/$1.jpg" lang="${2%%:*}" titre="${2#*:}" url
  url=$(curl -s -A "$UA" --retry 3 --get "https://$lang.wikipedia.org/w/api.php" \
        --data-urlencode "titles=$titre" -d action=query -d format=json -d prop=pageimages \
        -d piprop=original -d redirects=1 | jq -r '.query.pages[]?.original.source // empty' | head -1)
  if [ -n "$url" ] && curl -sL -A "$UA" --retry 3 -o "$f.src" "$url" \
     && ffmpeg -loglevel error -y -i "$f.src" -frames:v 1 -vf "scale='min(1600,iw)':-2" -q:v 3 "$f"; then
    rm -f "$f.src"; bon "$1.jpg" "photo libre Wikimedia" "$url"
  else rm -f "$f.src" "$f"; rate "photo $1 ($2) introuvable"; fi
}

article() { # nom url
  local f="$OUT/$1.jpg" enc i ct
  enc=$(jq -rn --arg u "$2" '$u|@uri')
  for i in 1 2 3 4 5 6 7 8; do   # la capture est générée en quelques secondes
    ct=$(curl -sL -A "$UA" -o "$f" -w '%{content_type}' "https://s0.wp.com/mshots/v1/$enc?w=1280&h=1500" || true)
    [[ "$ct" == image/jpeg* ]] && [ "$(taille "$f")" -gt 30000 ] && { bon "$1.jpg" "capture article" "$2"; return; }
    sleep 10
  done
  if curl -sL -A "$UA" -o "$f" "https://image.thum.io/get/width/1280/crop/1500/noanimate/$2" \
     && [ "$(taille "$f")" -gt 30000 ] && file -b --mime-type "$f" | grep -q '^image/'; then
    bon "$1.jpg" "capture article" "$2"; return
  fi
  rm -f "$f"; rate "article $1 : capture impossible ($2)"
}

video() { # nom url-ou-recherche durée_max
  local f="$OUT/$1.mp4" cible="$2" px=()
  [[ "$cible" == http* ]] || cible="ytsearch10:$2"
  [ -n "${YT_PROXY_URL:-}" ] && px=(--proxy "$YT_PROXY_URL")
  local base=(python3 -m yt_dlp -q --no-warnings --no-playlist --max-downloads 1 --max-filesize 400M
              --match-filter "duration < ${3:-900} & !is_live" --retries 5 --fragment-retries 5
              -f "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720]/b" --merge-output-format mp4
              --print-to-file "%(webpage_url)s | %(title)s | %(duration_string)s" "$f.url" -o "$f")
  # 1) via le proxy s'il existe  2) client « android/tv »  3) sans proxy
  "${base[@]}" "${px[@]}" "$cible" >/dev/null 2>&1
  [ -s "$f" ] || "${base[@]}" "${px[@]}" --extractor-args "youtube:player_client=tv,android,web_safari" "$cible" >/dev/null 2>&1
  [ -s "$f" ] || { [ ${#px[@]} -gt 0 ] && "${base[@]}" "$cible" >/dev/null 2>&1; }
  if [ -s "$f" ]; then bon "$1.mp4" "vidéo" "$(cat "$f.url" 2>/dev/null)"
  else rm -f "$f"*; rate "vidéo $1 non téléchargée (YouTube a peut-être bloqué GitHub) : $2"
       printf '%s | %s | %s\n' "$1" "$2" "${3:-900}" >> a-telecharger.txt; fi
  rm -f "$f.url"
}

while IFS='|' read -r sujet type nom cible duree; do
  sujet=$(echo "$sujet" | xargs); [[ -z "$sujet" || "$sujet" == \#* ]] && continue
  type=$(echo "$type" | xargs); nom=$(echo "$nom" | xargs); cible=$(echo "$cible" | xargs); duree=$(echo "${duree:-}" | xargs)
  garde "$sujet" || continue
  echo "::group::$type $nom"
  case "$type" in
    video) video "$nom" "$cible" "${duree:-900}" ;;
    photo) photo "$nom" "$cible" ;;
    article) article "$nom" "$cible" ;;
    *) rate "type inconnu « $type » pour $nom" ;;
  esac
  echo "::endgroup::"
done < "$LISTE"

# ---------- dépôt sur Google Drive ----------
mkdir -p ~/.config/rclone && printf '%s\n' "$RCLONE_CONF" > ~/.config/rclone/rclone.conf
REMOTE=$(grep -m1 -oE '^\[[^]]+\]' ~/.config/rclone/rclone.conf | tr -d '[]')
[ -n "$REMOTE" ] || { echo "::error::RCLONE_CONF vide ou illisible"; exit 1; }
if [[ "$DOSSIER" =~ ^[A-Za-z0-9_-]{25,}$ ]]; then DEST="$REMOTE,root_folder_id=$DOSSIER:"   # ID de dossier Drive
else DEST="$REMOTE:${DOSSIER#*:}"; fi
N=$(find "$OUT" -type f | wc -l)
if [ "$N" -gt 0 ]; then
  rclone copy "$OUT" "$DEST" --retries 5 --low-level-retries 20 --drive-chunk-size 64M -q \
    || { echo "::error::copie vers Google Drive ($DEST) échouée"; exit 1; }
  rclone copy sources.tsv "$REMOTE:sources-medias" -q 2>/dev/null || true   # HORS montage-joints
fi
# vidéos refusées à GitHub : liste pour ton téléphone (Termux : bash tel_videos.sh) — remplacée à chaque lancement
rclone copyto a-telecharger.txt "$REMOTE:sources-medias/a-telecharger.txt" -q 2>/dev/null || true

{
  echo "## 📥 Médias du live → Drive « $DOSSIER »"
  echo "**$OK OK**, **$KO échec(s)** — liste : \`$LISTE\`, sujets : $SUJETS"
  echo; echo "| Fichier | Type | Source |"; echo "|---|---|---|"
  awk -F'\t' '{printf "| %s | %s | %s |\n",$1,$2,$3}' sources.tsv
  if [ -s echecs.txt ]; then echo; echo "### ⚠ À compléter"; sed 's/^/- /' echecs.txt; fi
  if [ -s a-telecharger.txt ]; then
    echo; echo "📱 **$(wc -l < a-telecharger.txt) vidéo(s) refusée(s) à GitHub** : sur ton téléphone (Termux), lance"
    echo "\`bash tel_videos.sh\` — elles arrivent dans « $DOSSIER » toutes seules."
  fi
  echo; echo "Liste des sources aussi copiée dans Drive « sources-medias » (jamais dans montage-joints)."
} >> "$SUM"
[ "$OK" -gt 0 ] || [ -s a-telecharger.txt ] || { echo "::error::aucun média récupéré"; exit 1; }
