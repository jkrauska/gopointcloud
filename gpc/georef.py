"""Stage 6: align the SfM model to GPS and export a point cloud.

`colmap model_aligner --alignment_type enu` fits a similarity transform
from camera centres to GPS positions converted to local East-North-Up
metres about the first image. Output units are metres; origin is the
first frame's GPS position.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _colmap(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["colmap", *args], check=True, capture_output=True, text=True)


def align(model: Path, ref: Path, out_dir: Path, max_error_m: float = 5.0) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    r = _colmap("model_aligner",
                "--input_path", str(model),
                "--output_path", str(out_dir),
                "--ref_images_path", str(ref),
                "--ref_is_gps", "1",
                "--alignment_type", "enu",
                "--alignment_max_error", str(max_error_m))
    for line in (r.stdout + r.stderr).splitlines():
        if any(k in line for k in ("Alignment", "error", "inlier", "Inlier")):
            print("  ", line.strip())
    return out_dir


def export_ply(model: Path, ply: Path) -> Path:
    _colmap("model_converter",
            "--input_path", str(model),
            "--output_path", str(ply),
            "--output_type", "PLY")
    print(f"georef: wrote {ply}")
    return ply


def run(model: Path, ref: Path, work: Path, out: Path) -> Path:
    aligned = align(model, ref, work / "sparse_enu")
    out.mkdir(parents=True, exist_ok=True)
    return export_ply(aligned, out / "sparse_enu.ply")
