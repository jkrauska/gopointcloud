"""Stage 5: dense reconstruction with OpenMVS (CPU; COLMAP's own MVS needs CUDA).

InterfaceCOLMAP reads a COLMAP model + undistorted images into an .mvs
scene, DensifyPointCloud runs patch-match stereo and fuses depth maps.
Run on the *aligned* model so the dense cloud is already in ENU metres.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
from plyfile import PlyData, PlyElement

_BIN = Path(os.environ.get("OPENMVS_BIN", Path.home() / ".local" / "bin" / "OpenMVS"))


def available() -> bool:
    return (_BIN / "DensifyPointCloud").exists()


def _run(tool: str, *args: str, cwd: Path) -> None:
    subprocess.run([str(_BIN / tool), *args], check=True, cwd=cwd)


def run(model: Path, frames_dir: Path, work: Path, resolution_level: int = 1,
        max_threads: int = 0) -> Path:
    """Returns path to the fused dense PLY.

    resolution_level: 0 = full res, 1 = half (default; 480p input is small
    enough for 0 but larger footage wants 1 or 2).
    """
    # OpenMVS runs with cwd=dense, so everything it sees must be absolute.
    model, frames_dir = model.resolve(), frames_dir.resolve()
    dense = work.resolve() / "dense"
    shutil.rmtree(dense, ignore_errors=True)
    dense.mkdir(parents=True)

    # OpenMVS wants pinhole images: undistort with COLMAP first. This also
    # writes a copy of the sparse model in the layout InterfaceCOLMAP expects.
    undist = dense / "undistorted"
    subprocess.run(["colmap", "image_undistorter",
                    "--image_path", str(frames_dir),
                    "--input_path", str(model),
                    "--output_path", str(undist),
                    "--output_type", "COLMAP"], check=True)

    _run("InterfaceCOLMAP", "-i", str(undist), "-o", str(dense / "scene.mvs"),
         "--image-folder", str(undist / "images"), cwd=dense)
    _run("DensifyPointCloud", "scene.mvs",
         "--resolution-level", str(resolution_level),
         "--max-threads", str(max_threads),
         "-o", "scene_dense.mvs", cwd=dense)
    raw = dense / "scene_dense.ply"
    if not raw.exists():
        raise RuntimeError("DensifyPointCloud produced no PLY")
    ply = clean_ply(raw, dense / "dense.ply")
    print(f"mvs: wrote {ply} ({ply.stat().st_size / 1e6:.1f} MB)")
    return ply


def clean_ply(src: Path, dst: Path) -> Path:
    """OpenMVS writes per-vertex view lists that CloudCompare/MeshLab refuse
    to load ("nothing to load"). Keep xyz, rgb and normals only."""
    v = PlyData.read(str(src))["vertex"].data
    keep = [n for n in ("x", "y", "z", "red", "green", "blue", "nx", "ny", "nz") if n in v.dtype.names]
    out = np.empty(len(v), dtype=[(n, v.dtype[n]) for n in keep])
    for n in keep:
        out[n] = v[n]
    PlyData([PlyElement.describe(out, "vertex")], text=False).write(str(dst))
    return dst
