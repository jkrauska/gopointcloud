"""Stage 2/3 for still-image inputs: GPS from EXIF instead of GPMF.

Writes the same `name lat lon alt` reference file that `geotag.write_ref`
produces from video telemetry, so stages 4–6 don't care which path fed them.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from PIL.ExifTags import GPSTAGS, IFD

_EXTS = {".jpg", ".jpeg", ".JPG", ".JPEG"}


def _dms(v, ref: str) -> float:
    d, m, s = (float(x) for x in v)
    deg = d + m / 60 + s / 3600
    return -deg if ref in ("S", "W") else deg


def read_gps(path: Path) -> tuple[float, float, float] | None:
    """(lat, lon, alt) from EXIF, or None if the image has no GPS block."""
    with Image.open(path) as im:
        exif = im.getexif()
        gps = exif.get_ifd(IFD.GPSInfo)
    if not gps:
        return None
    g = {GPSTAGS.get(k, k): v for k, v in gps.items()}
    if "GPSLatitude" not in g or "GPSLongitude" not in g:
        return None
    lat = _dms(g["GPSLatitude"], g.get("GPSLatitudeRef", "N"))
    lon = _dms(g["GPSLongitude"], g.get("GPSLongitudeRef", "E"))
    alt = float(g.get("GPSAltitude", 0.0))
    if g.get("GPSAltitudeRef", 0) in (1, b"\x01"):
        alt = -alt
    return lat, lon, alt


def list_images(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.suffix in _EXTS)


def write_ref(images: list[Path], out: Path) -> Path:
    n_ok = 0
    with out.open("w") as fh:
        for p in images:
            g = read_gps(p)
            if g is None:
                continue
            fh.write(f"{p.name} {g[0]:.8f} {g[1]:.8f} {g[2]:.3f}\n")
            n_ok += 1
    print(f"exif: {n_ok}/{len(images)} images with GPS -> {out}")
    if n_ok == 0:
        raise RuntimeError("no EXIF GPS found in any image")
    return out
