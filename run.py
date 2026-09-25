"""End-to-end: video -> frames -> GPS -> (SfM -> georef, once colmap lands)."""

from __future__ import annotations

import argparse
from pathlib import Path

from gpc import colmap_view, frames, geotag, georef, gpmf, gravity, mvs, sfm, viz, webview


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video", type=Path)
    ap.add_argument("--work", type=Path, default=Path("work"))
    ap.add_argument("--fps", type=float, default=3.0)
    ap.add_argument("--drop-blurry", type=float, default=0.2)
    ap.add_argument("--out", type=Path, default=Path("out"))
    ap.add_argument("--camera", default="OPENCV_FISHEYE")
    ap.add_argument("--dense", action="store_true", help="run OpenMVS densification on the aligned model")
    ap.add_argument("--align", choices=["gravity", "enu"], default="gravity",
                    help="gravity: accelerometer up + GPS EN; enu: colmap model_aligner on lat/lon/alt")
    args = ap.parse_args()

    work = args.work / args.video.stem
    work.mkdir(parents=True, exist_ok=True)

    idx = frames.run(args.video, work / "frames", args.fps, args.drop_blurry)

    samples = gpmf.read_gps(args.video)
    gpmf.save_json(samples, work / "telemetry.json")
    fixed = sum(s.fix >= 2 for s in samples)
    print(f"gpmf: {len(samples)} GPS samples, {fixed} with fix")

    ref = geotag.write_ref(idx, samples, work / "frames_gps.txt")

    model = sfm.run(work / "frames", work, camera_model=args.camera, fps=args.fps)
    out = args.out / args.video.stem
    out.mkdir(parents=True, exist_ok=True)
    if args.align == "gravity":
        aligned = gravity.align(model, args.video, idx, ref, work / "sparse_enu")
    else:
        aligned = georef.align(model, ref, work / "sparse_enu")
    georef.export_ply(aligned, out / "sparse_enu.ply")
    viz.overview(aligned, ref, out / "overview.png")

    if args.dense:
        if not mvs.available():
            raise SystemExit("OpenMVS not found; set OPENMVS_BIN or build it (see Design.md)")
        ply = mvs.run(aligned, work / "frames", work)
        (out / "dense_enu.ply").write_bytes(ply.read_bytes())
        print(f"dense: {out / 'dense_enu.ply'}")
        colmap_view.build(aligned, out / "dense_enu.ply", work / "dense_view")
    webview.write(out, aligned)


if __name__ == "__main__":
    main()
