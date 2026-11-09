#!/usr/bin/env bash
# Accélère (ou ralentit) une vidéo et son son, SANS changer la hauteur de ta voix (atempo).
#   usage : bash scripts/vitesse.sh <video.mp4> <son.wav | -> <vitesse> <i/s>
#     <son.wav> : son séparé du morceau (vidéos longues, Beauté) ; « - » : le son est dans la vidéo (vidéo courte).
#   vitesse : 1 = inchangé (rien n'est fait, aucun ré-encodage) ; 1.1 = 10 % plus rapide ; accepté de 0.8 à 1.5.
# Image et son gardent EXACTEMENT la même durée (le son est calé sur le nombre d'images obtenu) : les morceaux se
# recollent sans décalage, quelle que soit la vitesse.
# Code 0 : fait (ou vitesse 1). Code 1 : échec → les fichiers d'origine sont intacts ; un morceau ne doit jamais
# rester à une autre vitesse que les autres, donc le job s'arrête avec un message clair (« Re-run failed jobs »).
set -uo pipefail
V="$1"; A="$2"; S="${3:-1}"; FPS="${4:-30}"
S=$(python3 - "$S" <<'PY'
import sys
try:
    s = float(sys.argv[1].replace(",", "."))
except ValueError:
    s = 1.0
if not (0.8 <= s <= 1.5):
    print("BAD")
else:
    print("%.4f" % s)
PY
)
if [ "$S" = "BAD" ]; then
  echo "::warning title=Vitesse::valeur « $3 » refusée (de 0.8 à 1.5) : vidéo gardée à vitesse normale"
  exit 0
fi
python3 -c "import sys; sys.exit(0 if abs(float('$S') - 1) < 0.001 else 1)" && exit 0   # vitesse 1 : rien à faire
test -s "$V" || { echo "::error title=Vitesse::vidéo introuvable : $V"; exit 1; }
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
fail() { echo "::error title=Vitesse::$* — fichiers d'origine intacts ; relance avec « Re-run failed jobs »"; exit 1; }

# 1) image : haute qualité (crf 16 ; le montage ré-encode ensuite), images régulières
ffmpeg -v error -y -i "$V" -map 0:v:0 -an -vf "setpts=PTS/$S,fps=$FPS" \
  -c:v libx264 -preset "${VITESSE_PRESET:-veryfast}" -crf 16 -pix_fmt yuv420p -r "$FPS" -fps_mode cfr "$T/v.mp4" || fail "accélération de l'image impossible"
NF=$(ffprobe -v error -count_packets -select_streams v:0 -show_entries stream=nb_read_packets -of csv=p=0 "$T/v.mp4" | tr -dc '0-9')
[ -n "$NF" ] && [ "$NF" -gt 0 ] || fail "nombre d'images illisible"
DV=$(python3 -c "n=$NF; f='$FPS'.split('/'); fr=float(f[0])/(float(f[1]) if len(f)>1 else 1); print('%.6f' % (n/fr))")

# 2) son : même voix (hauteur gardée), durée calée à l'image près sur la vidéo accélérée
if [ "$A" = "-" ]; then
  if ffprobe -v error -select_streams a:0 -show_entries stream=index -of csv=p=0 "$V" | grep -q .; then
    ffmpeg -v error -y -i "$V" -map 0:a:0 -vn -c:a pcm_s16le "$T/a0.wav" || fail "lecture du son impossible"
    SRC_A="$T/a0.wav"
  else
    SRC_A=""
  fi
else
  test -s "$A" || fail "son du morceau introuvable : $A"
  SRC_A="$A"
fi
if [ -n "$SRC_A" ]; then
  DA=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$SRC_A")
  F=$(python3 -c "print('%.6f' % (float('$DA') / float('$DV')))")
  ffmpeg -v error -y -i "$SRC_A" -af "atempo=$F,apad" -t "$DV" -c:a pcm_s16le "$T/a.wav" || fail "accélération du son impossible"
fi

# 3) remplacement (seulement si tout a réussi)
if [ "$A" = "-" ]; then
  if [ -n "$SRC_A" ]; then
    ffmpeg -v error -y -i "$T/v.mp4" -i "$T/a.wav" -map 0:v -map 1:a -c:v copy -c:a aac -b:a 256k -shortest \
      -movflags +faststart "$T/out.mp4" || fail "assemblage image + son impossible"
  else
    ffmpeg -v error -y -i "$T/v.mp4" -c copy -movflags +faststart "$T/out.mp4" || fail "finalisation impossible"
  fi
  mv -f "$T/out.mp4" "$V"
else
  mv -f "$T/v.mp4" "$V"
  [ -n "$SRC_A" ] && mv -f "$T/a.wav" "$A"
fi
echo "Vitesse ×$S appliquée : $(basename "$V") → $DV s ($NF images)"
