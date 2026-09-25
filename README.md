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

## Viewing

- Web: `http://localhost:8765/<name>/index.html`
- CloudCompare: `open -a CloudCompare out/<name>/dense_enu.ply`
- COLMAP GUI with cameras: `colmap gui --import_path work/<name>/dense_view --database_path work/<name>/database.db --image_path work/<name>/frames`

## Recording tips for new footage

HERO11/13 (GPS9). HyperSmooth **off**, Linear or Wide lens, 4K, fast shutter,
wait for the GPS lock before recording, move slowly and orbit rather than pan,
keep 60–80% overlap, finish where you started if you can.
