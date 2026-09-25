"""Stage 3: assign a GPS position to each kept frame.

Output is the text file COLMAP's `model_aligner --ref_is_gps 1` reads:

    image_name lat lon alt
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .gpmf import GpsSample


def interpolate(samples: list[GpsSample], times: list[float]) -> np.ndarray:
    """Linear lat/lon/alt at each time, using only samples with a fix."""
    good = [s for s in samples if s.fix >= 2]
    if not good:
        raise RuntimeError("no GPS samples with a fix")
    t = np.array([s.t for s in good])
    lla = np.array([[s.lat, s.lon, s.alt] for s in good])
    return np.column_stack([np.interp(times, t, lla[:, i]) for i in range(3)])


def write_ref(frames_index: Path, samples: list[GpsSample], out: Path) -> Path:
    frames = json.loads(frames_index.read_text())
    names = [f for f, _ in frames]
    times = [t for _, t in frames]
    lla = interpolate(samples, times)
    with out.open("w") as fh:
        for n, (lat, lon, alt) in zip(names, lla):
            fh.write(f"{n} {lat:.8f} {lon:.8f} {alt:.3f}\n")
    print(f"geotag: {len(names)} frames -> {out}")
    return out
