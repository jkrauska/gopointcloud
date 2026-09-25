"""Quick-look plot: aligned sparse cloud (top-down + side), SfM camera path,
and the GPS track it was aligned to. Sanity check for georeferencing."""

from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path

import matplotlib
import numpy as np
from pyproj import Transformer

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def _as_text(model: Path) -> Path:
    txt = model.parent / (model.name + "_txt")
    shutil.rmtree(txt, ignore_errors=True)
    txt.mkdir()
    subprocess.run(["colmap", "model_converter", "--input_path", str(model),
                    "--output_path", str(txt), "--output_type", "TXT"],
                   check=True, capture_output=True)
    return txt


def _quat_to_R(qw: float, qx: float, qy: float, qz: float) -> np.ndarray:
    return np.array([
        [1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
        [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
        [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)],
    ])


def load_model(model: Path) -> tuple[np.ndarray, np.ndarray, dict[str, np.ndarray]]:
    """Returns (points xyz, rgb, {image_name: camera centre})."""
    txt = _as_text(model)
    pts, rgb = [], []
    for line in (txt / "points3D.txt").read_text().splitlines():
        if line.startswith("#"):
            continue
        v = line.split()
        pts.append(v[1:4])
        rgb.append(v[4:7])
    cams: dict[str, np.ndarray] = {}
    lines = [l for l in (txt / "images.txt").read_text().splitlines() if not l.startswith("#")]
    for line in lines[::2]:
        v = line.split()
        q = [float(x) for x in v[1:5]]
        t = np.array([float(x) for x in v[5:8]])
        cams[v[9]] = -_quat_to_R(*q).T @ t
    return np.array(pts, float), np.array(rgb, float) / 255, cams


def lla_to_enu(lla: np.ndarray, origin: np.ndarray) -> np.ndarray:
    """WGS84 lat/lon/alt -> local East-North-Up metres about `origin`."""
    to_ecef = Transformer.from_crs("EPSG:4979", "EPSG:4978", always_xy=True)
    x, y, z = to_ecef.transform(lla[:, 1], lla[:, 0], lla[:, 2])
    x0, y0, z0 = to_ecef.transform(origin[1], origin[0], origin[2])
    d = np.column_stack([x - x0, y - y0, z - z0])
    la, lo = math.radians(origin[0]), math.radians(origin[1])
    R = np.array([
        [-math.sin(lo), math.cos(lo), 0],
        [-math.sin(la) * math.cos(lo), -math.sin(la) * math.sin(lo), math.cos(la)],
        [math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la)],
    ])
    return d @ R.T


def load_ref(ref: Path) -> tuple[list[str], np.ndarray]:
    rows = [l.split() for l in ref.read_text().splitlines() if l.strip()]
    return [r[0] for r in rows], np.array([[float(x) for x in r[1:4]] for r in rows])


def overview(model: Path, ref: Path, png: Path, clip_m: float = 15.0) -> None:
    P, rgb, cams = load_model(model)
    names, lla = load_ref(ref)
    G = lla_to_enu(lla, lla[0])
    C = np.array([cams[n] for n in names if n in cams])
    Gm = np.array([g for n, g in zip(names, G) if n in cams])

    keep = np.all(np.abs(P - np.median(P, 0)) < clip_m, axis=1)
    fig, ax = plt.subplots(1, 2, figsize=(14, 6))
    for a, (i, j, lab) in zip(ax, [(0, 1, "North"), (0, 2, "Up")]):
        a.scatter(P[keep, i], P[keep, j], c=rgb[keep], s=1)
        a.plot(C[:, i], C[:, j], "r-", lw=1, label="SfM cameras")
        a.plot(Gm[:, i], Gm[:, j], "b.", ms=3, label="GPS")
        a.set_aspect("equal")
        a.set_xlabel("East (m)")
        a.set_ylabel(f"{lab} (m)")
    ax[0].legend()
    ax[0].set_title(f"{model.parent.name}: {keep.sum()} pts (clipped to ±{clip_m:g} m)")
    plt.tight_layout()
    png.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(png, dpi=110)

    res = np.linalg.norm(C - Gm, axis=1)
    path = lambda X: float(np.sum(np.linalg.norm(np.diff(X, axis=0), axis=1)))
    print(f"viz: path length SfM {path(C):.1f} m vs GPS {path(Gm):.1f} m; "
          f"cam-vs-GPS residual mean {res.mean():.2f} m, max {res.max():.2f} m -> {png}")
