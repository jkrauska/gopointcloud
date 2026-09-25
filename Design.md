# gopointcloud — Design

Proof of concept: turn a GoPro video (with its embedded GPMF telemetry) into a
georeferenced point cloud.

Sample input: `samples/hero5.mp4` — 34 s, 854×480, HERO5 Black, sidewalk with
trees and buildings, GPS 3D fix throughout (Carlsbad, CA). Copied from
[gopro/gpmf-parser samples](https://github.com/gopro/gpmf-parser/tree/main/samples).

## Pipeline

```
video ─┬─ frames ──► filter blurry ──► SfM (poses + sparse) ──► MVS (dense) ─┐
       │                                                                      ├─► georef ──► PLY/LAS
       └─ GPMF ───► GPS per frame ──────────────────────────────────────────┘
```

| Stage | Input | Output |
|---|---|---|
| 1. Extract frames | MP4 | `work/frames/*.jpg` at ~3 fps, sharpness-filtered |
| 2. Extract telemetry | MP4 `gpmd` track | `work/telemetry.json` (GPS5 samples + timestamps) |
| 3. Geotag | frames + telemetry | `work/frames_gps.txt` (name, lat, lon, alt) |
| 4. SfM | frames | `work/sparse/0` (cameras, poses, sparse cloud) |
| 5. MVS | sparse | `work/dense/fused.ply` |
| 6. Georeference | dense + frames_gps | `out/cloud_utm.ply` (+ `.las` later) |

## Approaches

### A. Local, classical — **first take**

COLMAP does SfM and MVS. Everything runs on the M4 laptop.

- Frames: `ffmpeg` at 3 fps, then drop frames whose Laplacian variance is in
  the bottom ~20% (motion blur).
- Telemetry: parse the `gpmd` track ourselves. GPMF is a simple KLV format;
  we only need `GPS5` (lat, lon, alt, 2D speed, 3D speed), `SCAL`, `GPSU`
  (timestamp) and `GPSF` (fix type). A small Python parser avoids native
  dependencies. Interpolate to each frame's presentation time.
- SfM: `colmap feature_extractor` with a single shared `OPENCV_FISHEYE`
  camera (GoPro Wide), `sequential_matcher` (video, so neighbours + loop
  detection), `mapper`.
- MVS: COLMAP `patch_match_stereo` needs CUDA, which macOS does not have.
  Options, in order of preference:
  1. **OpenMVS** `DensifyPointCloud` — CPU, works on macOS, good quality.
  2. Skip densification for the first take and just georeference the
     sparse cloud. Enough to prove the pipeline end to end.
- Georeference: `colmap model_aligner` with `--ref_is_gps 1
  --alignment_type enu` fits a similarity transform (scale, rotation,
  translation) from camera centres to GPS. Also lets us report the RMS
  residual, which is a useful sanity check on the GPS quality.

Why first: no accounts, no uploads, fully inspectable, and the sample clip is
tiny (480p, ~100 frames) so iteration is fast.

Expected weakness on this clip: 480p and heavy H.264 compression give few
reliable features; the sidewalk / lawn are low texture. Sparse cloud will be
thin. Trees should come out reasonably — foliage is feature-rich.

### B. Local, learned

Feed-forward models predict poses + dense points directly from frames.

- **VGGT** — batch of frames in, cameras + depth + points out. Runs on
  Apple MPS but needs a lot of memory; ~50 frames is a practical cap.
- **MASt3R-SLAM** — sequential, handles video naturally, more memory
  friendly.

Better on low-texture and blurry input than COLMAP; worse metric accuracy;
no fisheye model, so undistort frames first. Worth trying as a comparison
once A works, especially because hero5 is exactly the kind of low-res
footage where classical SfM struggles.

### C. Georeferenced-first (OpenDroneMap)

WebODM in Docker consumes geotagged JPEGs and emits LAS/LAZ in UTM with no
extra alignment step. Heaviest install, least control, but the closest to
"one command". Good fallback if A's alignment step is fiddly.

### D. Cloud APIs

KIRI Engine, Polycam, Luma. Upload video, get a model. Fast, but opaque and
they mostly ignore GPS. Not pursued unless local approaches fail.

## Georeferencing details

- GoPro GPS is ~2–5 m accurate; SfM is cm-level internally. GPS is a
  *weak* prior: we align the finished model to it, we don't constrain SfM
  with it.
- Convert lat/lon → local ENU (or UTM) *before* alignment so the fit is in
  metres, not degrees.
- Sanity checks: GPS speed vs. camera-centre spacing; RMS residual after
  alignment should be on the order of GPS accuracy, not 10× worse.
- Clock offset between GPS samples and video frames is small on HERO5
  (GPS5 payloads are aligned to ~1 s video chunks) but real; a 0.5 s error
  at walking pace is ~0.7 m. Acceptable for the POC.

## Layout

```
gopointcloud/
├── Design.md
├── samples/hero5.mp4
├── gpc/                 # python package
│   ├── frames.py        # ffmpeg extraction + blur filter
│   ├── gpmf.py          # GPMF parser → GPS samples
│   ├── geotag.py        # interpolate GPS to frames
│   ├── sfm.py           # colmap driver
│   └── georef.py        # model_aligner + export
├── run.py               # end-to-end CLI
├── work/                # intermediates (gitignored)
└── out/                 # final clouds (gitignored)
```

Python via `uv`; system deps via `brew install colmap ffmpeg` (+ OpenMVS
later).

## Results log

### 2026-09-24 — hero5, approach A, sparse only

`uv run run.py samples/hero5.mp4` → 12 s wall clock on M4, CPU-only.

- 104 frames at 3 fps, 83 kept after blur filter; 618 GPS5 samples, all 3D fix.
- COLMAP: 83/83 images registered in one model, 5,968 points, 0.61 px
  mean reprojection error. Needed a focal-length prior for `OPENCV_FISHEYE`
  (COLMAP 4.2 refuses fisheye pairs without one); `hfov=120°` guess worked.
- `model_aligner` ENU: 0.66 m mean residual camera-vs-GPS, 1.26 m max.
  SfM path 46.6 m vs GPS 48.7 m. The L-shaped sidewalk and the tree canopies
  either side are clearly visible in `out/hero5/overview.png`.
- Known issue: side view shows the ground plane tilted ~8° because GPS
  altitude is noisier than horizontal. Fix candidates: `--alignment_type
  enu-plane`, or weight altitude down / use gravity from `ACCL`.
- COLMAP 4.2 renamed options: `SiftExtraction.*` → `FeatureExtraction.*`,
  `SiftMatching.*` → `FeatureMatching.*`.

### 2026-09-24 — gravity alignment (`gpc/gravity.py`), now the default

Up-vector from the accelerometer, East/North from GPS, altitude offset only
from GPS. hero5 ACCL stream is labelled (up/down, right/left, forward/back);
mean over the clip is (9.81, −0.18, 1.14) m/s², i.e. clean gravity with a
~7° forward pitch. Per-frame gravity (1 s window) mapped through each
camera rotation gives a world-up estimate with 4.0° spread across frames.

- Ground plane tilt: **0.5°** (was ~8° with `model_aligner enu`).
- Horizontal residual camera-vs-GPS 0.45 m; 3D 0.76 m (the vertical part is
  GPS altitude noise, visible as ±1 m wobble in the side view).
- COLMAP 4 gotchas: `model_transformer` does not apply the scale of a 3×4
  Sim3 the way one would expect, so we transform the TXT model ourselves.
  And COLMAP 4 models carry `frames.txt`/`rigs.txt` which *override* the
  poses in `images.txt` when present — always write into an empty dir.

### Density experiment: 8 fps

`--fps 8 --drop-blurry 0.1`: 249 frames, 15,266 points (2.5× the 3 fps
run) in 62 s. With the old fixed 10-frame matcher overlap the model split
in two (157 + rest); overlap is now time-based (4 s of frames).
Keypoints/frame stayed ~2,400 regardless of fps — that is the 480p ceiling
(COLMAP's cap is 8,192). Sparse SfM only ever triangulates keypoints;
real density (10⁵–10⁶ points) needs MVS. OpenMVS isn't in Homebrew, so
it's a source build.

### 2026-09-24 — dense, OpenMVS on hero5

`uv run run.py samples/hero5.mp4 --dense` → **526,827 points** (from 5,968
sparse), 4 min on the M4 CPU at full 480p resolution. So on this input the
density limit was the stage, not the frame count: MVS gave ~90× more points
than sparse; doubling fps gave ~2.5×.

OpenMVS build notes (macOS, Homebrew, Sept 2026): master needs
TinyEXIF/TinyNPY/PoseLib via vcpkg; **v2.4.0** builds with
`opencv@4` (v5 breaks `DataType<>` specialisations), Eigen 3.4.0 headers
(Homebrew ships Eigen 5), a separate `vcglib` clone, and
`LIBRARY_PATH=/opt/homebrew/lib` so the linker finds `libjxl`. Installed to
`~/.local/bin/OpenMVS`; `gpc/mvs.py` reads `OPENMVS_BIN` to override.
Pipeline: `colmap image_undistorter` → `InterfaceCOLMAP` →
`DensifyPointCloud`. Everything passed to OpenMVS must be an absolute path
(it runs with cwd = dense dir). Output PLY has per-vertex view lists, so
read it with `plyfile`, not `np.frombuffer`.

## Phase 2: Forest Roads Rindbach

After hero5 proves the pipeline, run it on a real forest dataset:
[Forest Roads Rindbach, Zenodo 17189667](https://zenodo.org/records/17189667)
(Upper Austria; CC-licensed research data).

- `photogrammetry.zip` — **8.68 GB**, 25,300 stills from two HERO7 Blacks on
  the rear of a van, 1.85 m above ground, ~28 km of forest road. Already
  processed with Metashape by the authors → reference point cloud / raster
  to compare against.
- `forest_roads.zip` — 10 MB GeoPackage: road centreline, GNSS survey
  (UTM 33N, EPSG:32633), culverts, bridges. The centreline is a useful
  ground-truth trajectory.

Differences from hero5 that the pipeline must absorb:

| | hero5 | Rindbach |
|---|---|---|
| Input | MP4 + GPMF track | JPEGs, GPS in EXIF (to verify) |
| Cameras | 1 | 2 rigs → COLMAP rig / two shared cameras |
| Scale | ~100 frames | 25k images → subsample one road segment first |
| Georef | model_aligner on GPMF | model_aligner on EXIF GPS, validate vs GNSS centreline |

So stage 3 (geotag) needs a second input path: read EXIF GPS instead of
interpolating GPMF. Stages 4–6 are unchanged. Start with a ~500-image
stretch, not the whole 28 km.

### 2026-09-24 — Rindbach, first 300 images, sparse

Dataset facts: one HERO7 (not two, at least in `sec04_2_stat`), 2 fps
timelapse (0.5 s apart, ~1 m spacing at van speed), 4000×3000, EXIF GPS on
90% of frames (29/300 have none — canopy dropouts). Section descends
946 m → 666 m.

`uv run run_images.py data/photogrammetry/sec04_2_stat --name rindbach300
--count 300` (SIFT at 2000 px): 10 min, 300/300 registered, 81,381 points,
13k keypoints/frame (vs 2.4k on hero5 — the resolution effect), 0.70 px
reprojection.

**Problem: scale drift.** `model_aligner enu` residual 7.6 m mean / 30 m
max. Residual by frame: 1.8 m (0–50), 2.7, 3.9, 15.6, 12.0 m (200–271).
SfM path 257 m vs GPS 356 m. A single similarity transform can't fix a
scale that drifts along the track; forward motion with a rear-facing camera
is the worst case for sequential SfM. GPS itself wobbles ±5 m under canopy.

Fix candidates, in order: (1) `colmap pose_prior_mapper` — uses the EXIF
GPS stored in the database as position priors *during* BA; (2) GLOMAP
global SfM; (3) split into ~100-frame chunks, align each, merge.

**Resolved 2026-09-25: it was the GPS, not the SfM.** Checked against the
authors' GNSS road centreline (`forestroads.gpkg`, layers `fr_line`/`pct`):
along-road distance between our first and last frame is **245–250 m**,
straight-line 235 m. SfM path: **258 m**. Raw GoPro GPS path: 335 m — the
±5 m canopy wobble adds ~35% of fake length, and the last frame's GPS is
18 m off the road. `pose_prior_mapper` (271 WGS84 priors, std 3/3/5 m,
robust loss) changed nothing (258 m path), which is consistent: the image
evidence overrules noisy priors. So: **never judge SfM scale against a raw
under-canopy GPS track**; smooth it (~10 s window) or align to survey data.

Lessons: `pose_prior_mapper` aborts if any image has an undefined prior
(`coordinate_system = -1`, images without EXIF GPS) — delete those rows
first. `sec04_2_stat_01.tif` is a 10 cm float32 raster in EPSG:32633
(44929×18432), the authors' Metashape DSM/DTM — ground truth for Z.

## Status / next (paused 2026-09-25)

Working end to end on hero5 (sparse + dense, gravity-aligned) and on a
300-image Rindbach slice (sparse, GPS-aligned; dense not yet run — expect
~30+ min at `resolution_level=2`).

Next when HERO13 footage arrives:
- `gpmf.py` needs the **GPS9** branch (complex type with per-sample time,
  DOP, fix) — currently `NotImplementedError`.
- Check ACCL axis labelling on HERO13 (HERO5–7 is up/right/forward; newer
  firmware may differ) — `gravity.up_in_camera` assumes that order.
- CORI (camera orientation quaternions) on HERO11+ could replace the
  accelerometer averaging entirely.
- Rindbach georef should align to the GNSS centreline, not the GoPro GPS.

## Open questions

- Does `colmap model_aligner` work well with only ~100 GPS points along a
  near-straight line? A straight path gives a poorly constrained rotation
  about the path axis. Might need to fall back to a hand-rolled
  Umeyama/Kabsch fit with an up-vector constraint from gravity (GoPro also
  records accelerometer `ACCL`).
- HERO5 lens: Wide FOV, fisheye. If `OPENCV_FISHEYE` is unstable on 480p,
  try `SIMPLE_RADIAL_FISHEYE` (fewer parameters).
- Real footage later: HERO11/13 with `GPS9` gives per-sample timestamps,
  which removes most of the clock-offset guesswork above.
