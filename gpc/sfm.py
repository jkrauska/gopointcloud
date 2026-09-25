"""Stage 4: COLMAP structure-from-motion on the extracted frames."""

from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path

import cv2


def _colmap(*args: str) -> None:
    subprocess.run(["colmap", *args], check=True)


def fisheye_prior(frames_dir: Path, hfov_deg: float = 120.0) -> str:
    """Initial OPENCV_FISHEYE params (fx fy cx cy k1 k2 k3 k4) for a GoPro
    Wide frame. COLMAP refuses to register fisheye pairs without a focal
    prior, since it can't be recovered from the fundamental matrix.
    Equidistant model: r = f * theta, so f = (w/2) / (hfov/2)."""
    img = next(iter(sorted(frames_dir.glob("*.jpg"))))
    h, w = cv2.imread(str(img)).shape[:2]
    f = (w / 2) / math.radians(hfov_deg / 2)
    return f"{f:.2f},{f:.2f},{w / 2:.1f},{h / 2:.1f},0,0,0,0"


def run(frames_dir: Path, work: Path, camera_model: str = "OPENCV_FISHEYE",
        camera_params: str | None = None, fps: float = 3.0,
        overlap_s: float = 4.0, max_image_size: int = 0, threads: int = -1) -> Path:
    """Returns the path to the largest reconstructed model (sparse/N)."""
    overlap = max(10, int(round(fps * overlap_s)))  # neighbours to match, in frames
    if camera_params is None and "FISHEYE" in camera_model:
        camera_params = fisheye_prior(frames_dir)
    db = work / "database.db"
    sparse = work / "sparse"
    shutil.rmtree(sparse, ignore_errors=True)
    sparse.mkdir(parents=True)
    if db.exists():
        db.unlink()

    _colmap("feature_extractor",
            "--database_path", str(db),
            "--image_path", str(frames_dir),
            "--ImageReader.camera_model", camera_model,
            "--ImageReader.single_camera", "1",
            *(["--ImageReader.camera_params", camera_params] if camera_params else []),
            "--FeatureExtraction.use_gpu", "0",
            *(["--FeatureExtraction.max_image_size", str(max_image_size)] if max_image_size else []),
            "--FeatureExtraction.num_threads", str(threads))

    # Video: match each frame to its neighbours, plus loop detection.
    _colmap("sequential_matcher",
            "--database_path", str(db),
            "--SequentialMatching.overlap", str(overlap),
            "--SequentialMatching.quadratic_overlap", "1",
            "--FeatureMatching.use_gpu", "0")

    _colmap("mapper",
            "--database_path", str(db),
            "--image_path", str(frames_dir),
            "--output_path", str(sparse),
            "--Mapper.num_threads", str(threads))

    models = sorted((p for p in sparse.iterdir() if (p / "cameras.bin").exists()),
                    key=_num_images, reverse=True)
    if not models:
        raise RuntimeError("mapper produced no model")
    best = models[0]
    print(f"sfm: {len(models)} model(s); best {best} with {_num_images(best)} images")
    return best


def _num_images(model: Path) -> int:
    r = subprocess.run(["colmap", "model_analyzer", "--path", str(model)],
                       capture_output=True, text=True)
    n = 0
    for line in (r.stdout + r.stderr).splitlines():
        if "Registered images" in line:
            n = int(line.rsplit(":", 1)[1].strip())
    return n
