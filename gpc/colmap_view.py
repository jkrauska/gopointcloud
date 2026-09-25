"""Build a COLMAP model dir that shows the *dense* cloud with the camera
frustums, so `colmap gui --import_path <dir>` displays both.

COLMAP's GUI can't take a PLY on the command line, so we borrow the
cameras/images from the aligned sparse model and swap its points3D for the
dense points (no tracks). Image 2D observations are dropped, otherwise they
would reference point ids that no longer exist.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
from plyfile import PlyData

from . import viz


def build(sparse_model: Path, dense_ply: Path, out_dir: Path, max_points: int = 2_000_000) -> Path:
    txt = viz._as_text(sparse_model)
    shutil.rmtree(out_dir, ignore_errors=True)
    out_txt = out_dir.parent / (out_dir.name + "_txt")
    shutil.rmtree(out_txt, ignore_errors=True)
    out_txt.mkdir(parents=True)
    out_dir.mkdir(parents=True)

    shutil.copy(txt / "cameras.txt", out_txt / "cameras.txt")
    lines = (txt / "images.txt").read_text().splitlines()
    poses = [l for l in lines if not l.startswith("#")][::2]
    image_ids = [int(pose.split()[0]) for pose in poses]

    v = PlyData.read(str(dense_ply))["vertex"].data
    n = len(v)
    if n > max_points:
        sel = np.random.default_rng(0).choice(n, max_points, replace=False)
        v = v[np.sort(sel)]
        n = len(v)

    # Viewing hack: the GUI hides points with track length < 3 and doesn't
    # persist that setting, so give each dense point a fake 3-image track.
    # COLMAP asserts that tracks and 2D observations agree, so each image
    # also gets one dummy 2D point (at 0,0) per track entry that lands on
    # it. This model is for looking at, never for export.
    m = len(image_ids)
    obs: dict[int, list[int]] = {iid: [] for iid in image_ids}  # image -> point ids
    tracks = []
    for i in range(1, n + 1):
        trk = []
        for k in range(3):
            iid = image_ids[(i + k) % m]
            trk.append((iid, len(obs[iid])))
            obs[iid].append(i)
        tracks.append(trk)

    with (out_txt / "images.txt").open("w") as fh:
        for pose, iid in zip(poses, image_ids):
            fh.write(pose + "\n" + " ".join(f"0 0 {pid}" for pid in obs[iid]) + "\n")

    with (out_txt / "points3D.txt").open("w") as fh:
        fh.write("# POINT3D_ID, X, Y, Z, R, G, B, ERROR, TRACK[]\n")
        for i, (p, trk) in enumerate(zip(v, tracks), 1):
            t = " ".join(f"{iid} {idx}" for iid, idx in trk)
            fh.write(f"{i} {p['x']:.4f} {p['y']:.4f} {p['z']:.4f} "
                     f"{int(p['red'])} {int(p['green'])} {int(p['blue'])} 0 {t}\n")

    subprocess.run(["colmap", "model_converter", "--input_path", str(out_txt),
                    "--output_path", str(out_dir), "--output_type", "BIN"],
                   check=True, capture_output=True)
    print(f"colmap_view: {n:,} dense points + {m} cameras -> {out_dir}")
    return out_dir


if __name__ == "__main__":
    import sys
    build(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
