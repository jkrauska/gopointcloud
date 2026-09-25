# Input data sources

Input media is not committed. Fetch it as described here.

## hero5.mp4

GoPro HERO5 Black, 34 s, 854×480, with GPMF telemetry track (GPS5 at ~18 Hz,
ACCL/GYRO at ~200 Hz). Sidewalk with trees, Carlsbad CA. GPS 3D fix throughout.

- Source: GoPro's official `gpmf-parser` sample set
  https://github.com/gopro/gpmf-parser/tree/main/samples
- Fetch:
  `curl -L -o samples/hero5.mp4 https://github.com/gopro/gpmf-parser/raw/main/samples/hero5.mp4`
- Licence: repo is under GoPro's own licence (see LICENSE in that repo);
  samples are provided for parser testing.

## Forest Roads Rindbach (phase 2, lives in `data/`)

Two HERO7 Blacks on a van, ~25,300 stills over ~28 km of forest road,
Upper Austria. Processed by the authors with Agisoft Metashape; GNSS survey
in UTM 33N (EPSG:32633).

- Source: Zenodo record 17189667, https://zenodo.org/records/17189667
- Files: `photogrammetry.zip` (8.68 GB), `forest_roads.zip` (10 MB)
- Fetch:
  `curl -L -o data/photogrammetry.zip https://zenodo.org/api/records/17189667/files/photogrammetry.zip/content`
  `curl -L -o data/forest_roads.zip https://zenodo.org/api/records/17189667/files/forest_roads.zip/content`
- Licence: as stated on the Zenodo record (check before redistribution).
