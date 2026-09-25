"""Image-folder variant of run.py: geotagged stills -> SfM -> georef (-> dense).

For the Rindbach set: two HERO7s on a van, GPS in EXIF, no accelerometer,
so alignment uses colmap's `model_aligner enu`. With thousands of GPS
points along a long path the altitude noise averages out far better than
it did on hero5's 50 m walk.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from gpc import exif, georef, mvs, sfm, viz, webview


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("images", type=Path, help="folder of geotagged JPEGs")
    ap.add_argument("--name", default=None, help="run name (default: folder name)")
    ap.add_argument("--work", type=Path, default=Path("work"))
    ap.add_argument("--out", type=Path, default=Path("out"))
    ap.add_argument("--start", type=int, default=0, help="first image index (sorted by name)")
    ap.add_argument("--count", type=int, default=None, help="how many images to use")
    ap.add_argument("--step", type=int, default=1, help="use every Nth image")
    ap.add_argument("--max-size", type=int, default=2000,
                    help="downscale longest side for SIFT (0 = full res)")
    ap.add_argument("--camera", default="OPENCV")
    ap.add_argument("--dense", action="store_true")
    args = ap.parse_args()

    name = args.name or args.images.name
    work = args.work / name
    frames = work / "frames"
    shutil.rmtree(frames, ignore_errors=True)
    frames.mkdir(parents=True)

    imgs = exif.list_images(args.images)
    end = None if args.count is None else args.start + args.count * args.step
    chosen = imgs[args.start:end:args.step]
    for p in chosen:
        (frames / p.name).symlink_to(p.resolve())
    print(f"images: {len(chosen)} of {len(imgs)} from {args.images}")

    ref = exif.write_ref(chosen, work / "frames_gps.txt")

    model = sfm.run(frames, work, camera_model=args.camera, fps=1.0,
                    overlap_s=15, max_image_size=args.max_size)
    out = args.out / name
    out.mkdir(parents=True, exist_ok=True)
    aligned = georef.align(model, ref, work / "sparse_enu")
    georef.export_ply(aligned, out / "sparse_enu.ply")
    viz.overview(aligned, ref, out / "overview.png", clip_m=60)

    if args.dense:
        if not mvs.available():
            raise SystemExit("OpenMVS not found; set OPENMVS_BIN or build it (see Design.md)")
        ply = mvs.run(aligned, frames, work, resolution_level=2)
        shutil.copyfile(ply, out / "dense_enu.ply")
        print(f"dense: {out / 'dense_enu.ply'}")
    webview.write(out, aligned)


if __name__ == "__main__":
    main()
