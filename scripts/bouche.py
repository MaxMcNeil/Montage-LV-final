#!/usr/bin/env python3
"""Mesure, image par image, si ta BOUCHE est FERMÉE (écart entre tes lèvres, repères du visage MediaPipe).

  python bouche.py <vidéo> <sortie.json> [images_par_seconde=8]

Écrit {"fps": 8, "gap": [écart lèvres / hauteur du visage, -1 = visage non trouvé], ...}.
Lancé dans son PROPRE environnement Python (MediaPipe apporte sa version d'OpenCV, qui ne doit jamais remplacer celle du
montage). Code 0 = mesure faite ; autre code = pas de mesure (le montage utilise alors une image fixe bouche fermée)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "models" / "face_landmarker.task"


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    src, out = sys.argv[1], Path(sys.argv[2])
    fps = float(sys.argv[3]) if len(sys.argv) > 3 else 8.0
    try:
        import numpy as np
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision
    except Exception as e:  # noqa: BLE001
        print(f"MediaPipe absent : {e}")
        return 3
    if not MODEL.exists():
        print(f"modèle absent : {MODEL}")
        return 3
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                        "-of", "csv=p=0", src], capture_output=True, text=True)
    try:
        w0, h0 = (int(x) for x in r.stdout.strip().split(",")[:2])
    except ValueError:
        print("vidéo illisible")
        return 4
    s = 640.0 / max(w0, h0)
    W, H = int(w0 * s) // 2 * 2, int(h0 * s) // 2 * 2
    lm = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(MODEL)), running_mode=vision.RunningMode.IMAGE, num_faces=1))
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", src, "-vf", f"fps={fps},scale={W}:{H}", "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    gap = []
    n = W * H * 3
    while True:
        b = p.stdout.read(n)
        if len(b) < n:
            break
        res = lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.frombuffer(b, np.uint8).reshape(H, W, 3)))
        if not res.face_landmarks:
            gap.append(-1.0)
            continue
        L = res.face_landmarks[0]

        def P(i):
            return np.array([L[i].x * W, L[i].y * H])
        fh = float(np.linalg.norm(P(10) - P(152))) or 1.0
        # milieu des lèvres + les deux côtés (une bouche entrouverte d'un seul côté compte aussi)
        g = max(np.linalg.norm(P(13) - P(14)), np.linalg.norm(P(82) - P(87)), np.linalg.norm(P(312) - P(317))) / fh
        gap.append(round(float(g), 4))
    p.wait()
    out.write_text(json.dumps({"fps": fps, "gap": gap}), encoding="utf-8")
    print(f"bouche : {len(gap)} images mesurées")
    sys.stdout.flush()
    os._exit(0)      # (MediaPipe peut planter en se fermant : la mesure est déjà écrite)


if __name__ == "__main__":
    sys.exit(main())
