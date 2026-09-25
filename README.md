# gopointcloud

GoPro video (or geotagged stills) → georeferenced point cloud. Proof of concept.

See [Design.md](Design.md) for the approach, results log and gotchas;
[samples/SOURCES.md](samples/SOURCES.md) for where the input data comes from.

## Setup (macOS)

```bash
brew install colmap ffmpeg
uv sync
```

Dense reconstruction needs OpenMVS built from source (Homebrew's OpenCV 5 and
Eigen 5 break it — build notes in Design.md). Installed to `~/.local/bin/OpenMVS`
or set `OPENMVS_BIN`.

## Run

```bash
# video with GPMF telemetry (HERO5+, not HERO12): frames → GPS/accel → SfM → align → PLY
uv run run.py samples/hero5.mp4 --dense

# folder of geotagged JPEGs
uv run run_images.py data/photogrammetry/sec04_2_stat --name rindbach300 --count 300
```

Outputs land in `out/<name>/`: `sparse_enu.ply`, `dense_enu.ply`, `overview.png`,
and `index.html` (three.js viewer — serve `out/` with `python3 -m http.server -d out 8765`).
Intermediates (COLMAP database, models, depth maps) are in `work/<name>/`.

Coordinates are local ENU metres about the first frame's GPS position, Z up.

## Tuning knobs

`run.py` (video):

| Flag | Default | When to change |
|---|---|---|
| `--fps` | 3 | Raise to 5–8 for fast motion or more sparse points (matcher overlap scales with it, 4 s window). Costs roughly linear time. |
| `--drop-blurry` | 0.2 | Fraction of frames dropped by Laplacian sharpness. Raise for shaky footage, 0 if frames are all sharp. |
| `--camera` | `OPENCV_FISHEYE` | Wide lens. Use `OPENCV` for Linear lens mode, `SIMPLE_RADIAL_FISHEYE` if fisheye is unstable. Fisheye needs the focal prior `sfm.fisheye_prior` derives from a 120° HFOV guess — adjust for other lens modes. |
| `--align` | `gravity` | Accelerometer up + GPS East/North. `enu` = COLMAP `model_aligner` on lat/lon/alt (worse tilt, no IMU needed). |
| `--dense` | off | OpenMVS. `mvs.run(resolution_level=...)`: 0 = full res (fine for 480p), 1–2 for 4K. Time goes ~4× per level. |

`run_images.py` (stills) adds `--start/--count/--step` to subsample and
`--max-size` (default 2000 px) for SIFT downscaling; 12 MP at 2000 px gave
~13k keypoints/frame, plenty.

Things not exposed as flags but worth knowing: SIFT cap is 8192 features/frame
(`SiftExtraction.max_num_features`); `model_aligner --alignment_max_error` is
5 m (raise for noisy GPS); the gravity smoothing window is 1 s
(`gravity.up_in_camera(smooth_s=)`).

## Viewing

- Web: `http://localhost:8765/<name>/index.html`
- CloudCompare: `open -a CloudCompare out/<name>/dense_enu.ply`
- COLMAP GUI with cameras: `colmap gui --import_path work/<name>/dense_view --database_path work/<name>/database.db --image_path work/<name>/frames`

## Recording tips for new footage

HERO11/13 (GPS9). HyperSmooth **off**, Linear or Wide lens, 4K, fast shutter,
wait for the GPS lock before recording, move slowly and orbit rather than pan,
keep 60–80% overlap, finish where you started if you can.
