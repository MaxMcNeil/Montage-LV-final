"""Pièces jointes rangées (jamais à la corbeille) après un montage réussi, puis reprises à la relance."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FAKE = r'''#!/bin/bash
D=__D__; p(){ echo "$D/${1#*:}"; }
case "$1" in
 move) src=$(p "$2"); dst=$(p "$3"); mkdir -p "$dst"
       if [ "$4" = --files-from ]; then while read -r f; do mkdir -p "$dst/$(dirname "$f")"; mv "$src/$f" "$dst/$f"; done < "$5"
       else mv "$src"/* "$dst"/ && rmdir "$src"; fi;;
 copyto) cp "$2" "$(p "$3")";;
 lsf) ls -1p "$(p "$2")" | grep /;;
 purge) rm -rf "$(p "$2")";;
 cat) cat "$(p "$2")";;
esac
'''


def test_ranger_puis_reprendre(tmp_path):
    d = tmp_path / "drive"
    (d / "montage-joints").mkdir(parents=True)
    (d / "montage-joints-utilises/20200101-0000-ancien").mkdir(parents=True)
    (d / "montage-joints-utilises/20200101-0000-ancien/x.jpg").write_text("x")
    for f in ("vieille_photo.jpg", "v1.mp4", "pas_utilise.jpg"):
        (d / "montage-joints" / f).write_text(f)
    os.utime(d / "montage-joints/vieille_photo.jpg", (946684800, 946684800))     # fichier très ancien : jamais supprimé
    b = tmp_path / "bin"
    b.mkdir()
    (b / "rclone").write_text(FAKE.replace("__D__", str(d)))
    (b / "rclone").chmod(0o755)
    lst = tmp_path / "l.txt"
    lst.write_text("vieille_photo.jpg\nv1.mp4\n")
    env = dict(os.environ, PATH=f"{b}:{os.environ['PATH']}")
    for script in ("chaine_suite.sh", "publish.sh"):
        r = subprocess.run(["bash", "-c", f"source <(sed -n '/^ranger_joints()/,/^}}/p' {ROOT}/scripts/{script}); "
                            f"ranger_joints gd montage-joints {lst} essai"], env=env)
        if script == "chaine_suite.sh":
            assert r.returncode == 0
    st = (d / "montage-joints-utilises/dernier.txt").read_text().strip()
    assert sorted(p.name for p in (d / "montage-joints-utilises" / st).iterdir()) == ["v1.mp4", "vieille_photo.jpg"]
    assert not (d / "montage-joints-utilises/20200101-0000-ancien").exists()       # ménage par DATE DE DOSSIER
    assert [p.name for p in (d / "montage-joints").iterdir()] == ["pas_utilise.jpg"]
    r = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, 'scripts'); import fetch_inputs as F; "
                        "F.reprendre_joints('gd', 'montage-joints')"], cwd=ROOT, env=dict(env, REPRENDRE_JOINTS="oui"))
    assert r.returncode == 0
    assert sorted(p.name for p in (d / "montage-joints").iterdir()) == ["pas_utilise.jpg", "v1.mp4", "vieille_photo.jpg"]
