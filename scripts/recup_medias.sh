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

# ---------- vidéos : YouTube d'abord, puis TOUS les contournements, automatiquement ----------
# 1) YouTube (jeton PO bgutil s'il tourne + tes cookies YT_COOKIES + ton proxy) sur les 3 meilleurs résultats,
#    avec plusieurs façons de se présenter ; 2) relais Invidious (la vidéo YouTube passe par un serveur tiers) ;
# 3) même recherche sur Dailymotion puis archive.org (ne bloquent pas GitHub). Rien n'est demandé à aucune IA.
ytdl() { # sortie cible durée [options…]
  local o="$1" c="$2" d="$3"; shift 3
  python3 -m yt_dlp -q --no-warnings --no-playlist --max-downloads 1 --max-filesize 400M \
    --match-filter "duration < $d & !is_live" --retries 3 --fragment-retries 3 --socket-timeout 30 \
    -f "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720][ext=mp4]/b[height<=720]/b" --merge-output-format mp4 \
    -o "$o" "$@" "$c" >/dev/null 2>&1
  [ -s "$o" ]
}

invidious() { # sortie id_youtube
  local o="$1" id="$2" inst u
  for inst in $(curl -s --max-time 15 "https://api.invidious.io/instances.json?sort_by=health" 2>/dev/null \
                | jq -r '.[] | select(.[1].type=="https" and .[1].api==true) | .[1].uri' 2>/dev/null | head -5); do
    u=$(curl -s --max-time 25 "$inst/api/v1/videos/$id?local=true" 2>/dev/null \
        | jq -r '[.formatStreams[]? | select(.container=="mp4")] | sort_by(.resolution) | reverse | .[0].url // empty' 2>/dev/null)
    [ -n "$u" ] || continue
    [[ "$u" == http* ]] || u="$inst$u"
    curl -sL --max-time 600 -A "$UA" -o "$o" "$u" && [ "$(taille "$o")" -gt 200000 ] \
      && ffprobe -v error -show_entries format=duration -of csv=p=0 "$o" >/dev/null 2>&1 && return 0
    rm -f "$o"
  done
  return 1
}

video() { # nom url-ou-recherche durée_max
  local f="$OUT/$1.mp4" q="$2" d="${3:-900}" px=() ck=() urls=() u via="" id v
  [ -n "${YT_PROXY_URL:-}" ] && px=(--proxy "$YT_PROXY_URL")
  [ -s "${YT_COOKIES_FILE:-}" ] && ck=(--cookies "$YT_COOKIES_FILE")
  if [[ "$q" == http* ]]; then urls=("$q")
  else   # la recherche YouTube marche depuis GitHub (seul le téléchargement est parfois refusé)
    mapfile -t urls < <(python3 -m yt_dlp -q --no-warnings --flat-playlist --match-filter "duration < $d & !is_live" \
                          --print "https://www.youtube.com/watch?v=%(id)s" "ytsearch8:$q" 2>/dev/null | head -3)
  fi
  for u in "${urls[@]}"; do
    for v in "" "youtube:player_client=tv" "youtube:player_client=mweb" "youtube:player_client=android,web_safari"; do
      if [ -n "$v" ]; then ytdl "$f" "$u" "$d" "${px[@]}" "${ck[@]}" --extractor-args "$v" && { via="$u"; break 2; }
      else ytdl "$f" "$u" "$d" "${px[@]}" "${ck[@]}" && { via="$u"; break 2; }; fi
    done
    [ ${#px[@]} -gt 0 ] && ytdl "$f" "$u" "$d" "${ck[@]}" && { via="$u"; break; }
    id=$(echo "$u" | sed -nE 's#.*(v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11}).*#\2#p')
    [ -n "$id" ] && invidious "$f" "$id" && { via="$u (via relais Invidious)"; break; }
  done
  if [ ! -s "$f" ] && [[ "$q" != http* ]]; then   # Dailymotion (API publique, sans clé), puis archive.org
    for u in $(curl -s --max-time 25 --get "https://api.dailymotion.com/videos" --data-urlencode "search=$q" \
                 -d "fields=url,duration" -d limit=5 -d sort=relevance 2>/dev/null \
               | jq -r --argjson d "$d" '.list[]? | select(.duration < $d) | .url' 2>/dev/null | head -2); do
      ytdl "$f" "$u" "$d" && { via="$u (Dailymotion)"; break; }
    done
  fi
  if [ ! -s "$f" ] && [[ "$q" != http* ]]; then
    for id in $(curl -s --max-time 25 --get "https://archive.org/advancedsearch.php" --data-urlencode "q=($q) AND mediatype:movies" \
                  -d "fl[]=identifier" -d rows=3 -d output=json 2>/dev/null | jq -r '.response.docs[]?.identifier' 2>/dev/null); do
      ytdl "$f" "https://archive.org/details/$id" "$((d * 4))" && { via="https://archive.org/details/$id (archive.org)"; break; }
    done
  fi
  rm -f "$f.part" "$f".*.part 2>/dev/null
  if [ -s "$f" ]; then bon "$1.mp4" "vidéo" "$via"
  else rm -f "$f"*; rate "vidéo $1 introuvable partout (YouTube, relais, Dailymotion, archive.org) : $2"
       printf '%s | %s | %s\n' "$1" "$2" "$d" >> a-telecharger.txt; fi
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
    echo; echo "ℹ️ $(wc -l < a-telecharger.txt) vidéo(s) introuvable(s) partout : le montage se fait sans elles"
    echo "(facultatif : ton téléphone peut les récupérer avec \`bash tel_videos.sh\`)."
  fi
  echo; echo "Liste des sources aussi copiée dans Drive « sources-medias » (jamais dans montage-joints)."
} >> "$SUM"
[ "$OK" -gt 0 ] || [ -s a-telecharger.txt ] || { echo "::error::aucun média récupéré"; exit 1; }
