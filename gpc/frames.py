"""Stage 1: extract frames from video and drop the blurry ones."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import cv2
import numpy as np


def extract(mp4: Path, out_dir: Path, fps: float = 3.0) -> list[tuple[str, float]]:
    """Write frames at `fps` to out_dir. Returns [(filename, t_seconds), ...]."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.jpg"):
        old.unlink()
    subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(mp4), "-vf", f"fps={fps}",
         "-q:v", "2", str(out_dir / "f%05d.jpg")],
        check=True,
    )
    files = sorted(p.name for p in out_dir.glob("f*.jpg"))
    # fps filter emits frame i at t = i / fps
    return [(f, i / fps) for i, f in enumerate(files)]


def sharpness(path: Path) -> float:
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    return float(cv2.Laplacian(img, cv2.CV_64F).var())


def filter_blurry(out_dir: Path, frames: list[tuple[str, float]],
                  drop_fraction: float = 0.2) -> list[tuple[str, float]]:
    """Delete the blurriest `drop_fraction` of frames (Laplacian variance)."""
    scores = np.array([sharpness(out_dir / f) for f, _ in frames])
    thresh = np.quantile(scores, drop_fraction)
    kept = []
    for (f, t), s in zip(frames, scores):
        if s < thresh:
            (out_dir / f).unlink()
        else:
            kept.append((f, t))
    return kept


def run(mp4: Path, out_dir: Path, fps: float = 3.0, drop_fraction: float = 0.2) -> Path:
    frames = extract(mp4, out_dir, fps)
    kept = filter_blurry(out_dir, frames, drop_fraction)
    index = out_dir.parent / "frames.json"  # keep it out of colmap's image dir
    index.write_text(json.dumps(kept, indent=1))
    print(f"frames: extracted {len(frames)}, kept {len(kept)} -> {out_dir}")
    return index


if __name__ == "__main__":
    import sys
    run(Path(sys.argv[1]), Path(sys.argv[2]))
