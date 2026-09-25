"""Stage 6 (alt): georeference using GPS for East/North and the
accelerometer for Up.

`model_aligner --alignment_type enu` fits scale+rotation+translation to
GPS lat/lon/alt, but GPS altitude is several times noisier than
horizontal, so the fitted roll/pitch is bad (hero5 came out ~8° tilted).

Here we instead:
  1. estimate world-up in model coordinates from the accelerometer:
     each camera's rotation R_i (world→cam) maps the smoothed gravity
     vector seen in the camera frame back into the world;
  2. rotate the model so that up is +Z;
  3. fit a 2-D similarity (scale, yaw, tx, ty) of camera XY to GPS EN;
  4. set tz from the median GPS altitude offset.
Output model is in ENU metres about the first frame's GPS position, the
same frame `viz.overview` and `model_aligner enu` use.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np

from . import gpmf, viz


def _quat_wxyz(q):
    return viz._quat_to_R(*q)


def _read_images(model_txt: Path) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """image_name -> (R world→cam, t)."""
    out = {}
    lines = [l for l in (model_txt / "images.txt").read_text().splitlines() if not l.startswith("#")]
    for line in lines[::2]:
        v = line.split()
        q = [float(x) for x in v[1:5]]
        t = np.array([float(x) for x in v[5:8]])
        out[v[9]] = (_quat_wxyz(q), t)
    return out


def up_in_camera(mp4: Path, frame_times: dict[str, float], smooth_s: float = 1.0
                 ) -> dict[str, np.ndarray]:
    """Unit 'up' vector in each frame's COLMAP camera frame (x right,
    y down, z forward). GoPro ACCL order is (up, right, forward); a
    walking camera's mean acceleration is gravity, so smooth over ~1 s."""
    t, a = gpmf.read_accl(mp4)
    out = {}
    for name, ft in frame_times.items():
        m = np.abs(t - ft) < smooth_s / 2
        up, right, fwd = a[m].mean(0)
        v = np.array([right, -up, fwd])
        out[name] = v / np.linalg.norm(v)
    return out


def world_up(images: dict, up_cam: dict) -> tuple[np.ndarray, float]:
    """Average R_iᵀ·up_cam_i over frames. Returns (unit vector, spread deg)."""
    ups = np.array([images[n][0].T @ up_cam[n] for n in up_cam if n in images])
    u = ups.mean(0)
    u /= np.linalg.norm(u)
    spread = np.degrees(np.arccos(np.clip(ups @ u, -1, 1))).std()
    return u, spread


def rotation_to_z(u: np.ndarray) -> np.ndarray:
    """Rotation matrix taking unit vector u onto +Z (Rodrigues)."""
    z = np.array([0.0, 0.0, 1.0])
    v = np.cross(u, z)
    s, c = np.linalg.norm(v), float(u @ z)
    if s < 1e-9:
        return np.eye(3) if c > 0 else np.diag([1.0, -1.0, -1.0])
    K = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + K + K @ K * ((1 - c) / s ** 2)


def similarity_2d(src: np.ndarray, dst: np.ndarray) -> tuple[float, np.ndarray, np.ndarray]:
    """Umeyama: scale s, rotation R (2x2), translation t with dst ≈ s R src + t."""
    ms, md = src.mean(0), dst.mean(0)
    S, D = src - ms, dst - md
    U, sig, Vt = np.linalg.svd(D.T @ S)
    d = np.sign(np.linalg.det(U @ Vt))
    R = U @ np.diag([1, d]) @ Vt
    s = (sig * [1, d]).sum() / (S ** 2).sum()
    return s, R, md - s * R @ ms


def align(model: Path, mp4: Path, frames_index: Path, ref: Path, out_dir: Path) -> Path:
    txt = viz._as_text(model)
    images = _read_images(txt)
    frame_times = {n: t for n, t in json.loads(frames_index.read_text())}
    up_cam = up_in_camera(mp4, frame_times)
    u, spread = world_up(images, up_cam)
    Rg = rotation_to_z(u)

    names, lla = viz.load_ref(ref)
    enu = viz.lla_to_enu(lla, lla[0])
    names = [n for n in names if n in images]
    C = np.array([Rg @ (-images[n][0].T @ images[n][1]) for n in names])
    G = np.array([g for n, g in zip(*viz.load_ref(ref)) if n in images])
    G = viz.lla_to_enu(lla[[i for i, n in enumerate(viz.load_ref(ref)[0]) if n in images]], lla[0])

    s, R2, t2 = similarity_2d(C[:, :2], G[:, :2])
    R = np.eye(3)
    R[:2, :2] = R2
    tz = np.median(G[:, 2] - s * C[:, 2])
    T = np.zeros((3, 4))
    T[:, :3] = s * R @ Rg
    T[:, 3] = [t2[0], t2[1], tz]

    Cw = (T[:, :3] @ np.array([-images[n][0].T @ images[n][1] for n in names]).T).T + T[:, 3]
    res = np.linalg.norm(Cw - G, axis=1)
    res_xy = np.linalg.norm((Cw - G)[:, :2], axis=1)
    print(f"gravity: up-vector spread {spread:.1f}°, scale {s:.3f}, "
          f"residual mean {res.mean():.2f} m (xy {res_xy.mean():.2f} m), max {res.max():.2f} m")

    np.savetxt(out_dir.parent / "gravity_transform.txt", T, fmt="%.9f")
    apply_sim3(txt, s, R @ Rg, T[:, 3], out_dir)
    return out_dir


def _R_to_quat(R: np.ndarray) -> np.ndarray:
    """Rotation matrix -> (qw, qx, qy, qz)."""
    m = R
    tr = np.trace(m)
    if tr > 0:
        S = np.sqrt(tr + 1.0) * 2
        return np.array([0.25 * S, (m[2, 1] - m[1, 2]) / S, (m[0, 2] - m[2, 0]) / S, (m[1, 0] - m[0, 1]) / S])
    i = int(np.argmax(np.diag(m)))
    if i == 0:
        S = np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        return np.array([(m[2, 1] - m[1, 2]) / S, 0.25 * S, (m[0, 1] + m[1, 0]) / S, (m[0, 2] + m[2, 0]) / S])
    if i == 1:
        S = np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        return np.array([(m[0, 2] - m[2, 0]) / S, (m[0, 1] + m[1, 0]) / S, 0.25 * S, (m[1, 2] + m[2, 1]) / S])
    S = np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
    return np.array([(m[1, 0] - m[0, 1]) / S, (m[0, 2] + m[2, 0]) / S, (m[1, 2] + m[2, 1]) / S, 0.25 * S])


def apply_sim3(txt: Path, s: float, R: np.ndarray, t: np.ndarray, out_dir: Path) -> Path:
    """Write a COLMAP model with world points mapped x' = s R x + t.
    Camera poses (cam_from_world) become R_c R^T, s t_c - R_c R^T t.
    COLMAP's model_transformer mishandles the scale in a 3x4 Sim3, so we
    do it by hand on the TXT model and convert back to BIN."""
    # Start from empty dirs: COLMAP 4 stores poses in frames.txt/rigs.txt
    # when present, which would silently override the images.txt we write.
    out_txt = out_dir.parent / (out_dir.name + "_txt")
    for d in (out_txt, out_dir):
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
    (out_txt / "cameras.txt").write_text((txt / "cameras.txt").read_text())

    lines_out = []
    lines = (txt / "images.txt").read_text().splitlines()
    it = iter(lines)
    for line in it:
        if line.startswith("#"):
            lines_out.append(line)
            continue
        v = line.split()
        Rc = viz._quat_to_R(*[float(x) for x in v[1:5]])
        tc = np.array([float(x) for x in v[5:8]])
        Rn = Rc @ R.T
        tn = s * tc - Rn @ t
        q = _R_to_quat(Rn)
        lines_out.append(" ".join([v[0], *(f"{x:.9f}" for x in q), *(f"{x:.9f}" for x in tn), v[8], v[9]]))
        lines_out.append(next(it))  # 2D points line, unchanged
    (out_txt / "images.txt").write_text("\n".join(lines_out) + "\n")

    pts_out = []
    for line in (txt / "points3D.txt").read_text().splitlines():
        if line.startswith("#"):
            pts_out.append(line)
            continue
        v = line.split()
        x = s * R @ np.array([float(a) for a in v[1:4]]) + t
        pts_out.append(" ".join([v[0], *(f"{a:.6f}" for a in x), *v[4:]]))
    (out_txt / "points3D.txt").write_text("\n".join(pts_out) + "\n")

    subprocess.run(["colmap", "model_converter", "--input_path", str(out_txt),
                    "--output_path", str(out_dir), "--output_type", "BIN"],
                   check=True, capture_output=True)
    return out_dir
