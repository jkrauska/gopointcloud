"""Minimal GPMF parser: pull GPS samples out of a GoPro MP4's `gpmd` track.

GPMF is a KLV format: 4-char key, 1-byte type, 1-byte struct size,
2-byte repeat count (big-endian), then the payload padded to 4 bytes.
Type 0 means "nested container". We only need the GPS stream:

    DEVC > STRM > { STNM, SCAL, GPSU, GPSF, GPSP, GPS5 | GPS9 }

Payload timing comes from the MP4 packet timestamps (one payload ~1 s),
which we read with ffprobe rather than parsing the moov atom ourselves.
"""

from __future__ import annotations

import json
import struct
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

_TYPE_FMT = {
    b"b": "b", b"B": "B", b"s": "h", b"S": "H", b"l": "i", b"L": "I",
    b"f": "f", b"d": "d", b"j": "q", b"J": "Q",
}


@dataclass
class GpsSample:
    t: float          # seconds from video start
    lat: float
    lon: float
    alt: float        # metres, WGS84 ellipsoid
    speed2d: float
    speed3d: float
    fix: int          # 0 none, 2 = 2D, 3 = 3D
    dop: float


def _klv(buf: bytes):
    """Yield (key, type, structsize, repeat, payload) for each KLV in buf."""
    i = 0
    while i + 8 <= len(buf):
        key = buf[i:i + 4]
        typ = buf[i + 4:i + 5]
        ssize = buf[i + 5]
        rep = struct.unpack(">H", buf[i + 6:i + 8])[0]
        n = ssize * rep
        payload = buf[i + 8:i + 8 + n]
        yield key, typ, ssize, rep, payload
        i += 8 + ((n + 3) & ~3)


def _values(typ: bytes, ssize: int, rep: int, payload: bytes):
    fmt = _TYPE_FMT[typ]
    per = ssize // struct.calcsize(fmt)
    return np.frombuffer(payload, dtype=">" + fmt, count=per * rep).reshape(rep, per)


def _parse_gpsu(payload: bytes) -> datetime:
    s = payload.decode("ascii")  # yymmddhhmmss.sss
    return datetime.strptime(s, "%y%m%d%H%M%S.%f").replace(tzinfo=timezone.utc)


def _packets(mp4: Path) -> tuple[bytes, list[tuple[float, int]]]:
    """Return the raw gpmd track and [(pts_seconds, size), ...] per packet."""
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_packets",
         "-of", "json", str(mp4)],
        capture_output=True, text=True, check=True,
    )
    info = json.loads(probe.stdout)
    idx = next(s["index"] for s in info["streams"]
               if s.get("codec_tag_string") == "gpmd")
    pkts = [(float(p["pts_time"]), int(p["size"]))
            for p in info["packets"] if p["stream_index"] == idx]
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(mp4), "-map", f"0:{idx}",
         "-c", "copy", "-f", "data", "-"],
        capture_output=True, check=True,
    ).stdout
    assert sum(sz for _, sz in pkts) == len(raw), "gpmd packet sizes disagree with dump"
    return raw, pkts


def _gps_from_payload(payload: bytes, t0: float, t1: float) -> list[GpsSample]:
    """Parse one DEVC payload spanning video time [t0, t1)."""
    out: list[GpsSample] = []
    for key, typ, ssize, rep, body in _klv(payload):
        if key != b"DEVC":
            continue
        for k2, ty2, ss2, rp2, strm in _klv(body):
            if k2 != b"STRM":
                continue
            fields: dict[bytes, tuple] = {}
            for k3, ty3, ss3, rp3, val in _klv(strm):
                fields[k3] = (ty3, ss3, rp3, val)
            if b"GPS5" not in fields and b"GPS9" not in fields:
                continue
            scal = _values(*fields[b"SCAL"]).ravel().astype(float)
            fix = int(_values(*fields[b"GPSF"]).ravel()[0]) if b"GPSF" in fields else 0
            dop = float(_values(*fields[b"GPSP"]).ravel()[0]) / 100 if b"GPSP" in fields else float("nan")
            if b"GPS5" in fields:
                v = _values(*fields[b"GPS5"]).astype(float) / scal
                n = len(v)
                # GPS5 has no per-sample time: spread evenly across the payload.
                ts = t0 + (t1 - t0) * np.arange(n) / n
                for i in range(n):
                    out.append(GpsSample(float(ts[i]), v[i, 0], v[i, 1], v[i, 2],
                                         v[i, 3], v[i, 4], fix, dop))
            else:  # GPS9: lat lon alt 2d 3d days secs dop fix, complex type
                # TODO(hero11+): parse complex 'TYPE' descriptor; not needed for hero5
                raise NotImplementedError("GPS9 parsing not implemented yet")
    return out


def read_gps(mp4: Path) -> list[GpsSample]:
    raw, pkts = _packets(mp4)
    samples: list[GpsSample] = []
    off = 0
    for i, (pts, size) in enumerate(pkts):
        t1 = pkts[i + 1][0] if i + 1 < len(pkts) else pts + (pts - pkts[i - 1][0] if i else 1.0)
        samples.extend(_gps_from_payload(raw[off:off + size], pts, t1))
        off += size
    return samples


def read_accl(mp4: Path) -> tuple[np.ndarray, np.ndarray]:
    """Accelerometer samples: (t seconds [n], xyz m/s² [n,3]) in the order
    the camera labels them. HERO5–7 label ACCL as (up/down, right/left,
    forward/back); at rest it reads ~(+9.81, 0, 0), i.e. +x is 'up'."""
    raw, pkts = _packets(mp4)
    ts, acc = [], []
    off = 0
    for i, (pts, size) in enumerate(pkts):
        t1 = pkts[i + 1][0] if i + 1 < len(pkts) else pts + (pts - pkts[i - 1][0] if i else 1.0)
        for key, _, _, _, body in _klv(raw[off:off + size]):
            if key != b"DEVC":
                continue
            for k2, _, _, _, strm in _klv(body):
                if k2 != b"STRM":
                    continue
                f = {k: (ty, ss, rp, val) for k, ty, ss, rp, val in _klv(strm)}
                if b"ACCL" not in f:
                    continue
                scal = _values(*f[b"SCAL"]).ravel().astype(float)
                a = _values(*f[b"ACCL"]).astype(float) / scal
                n = len(a)
                ts.append(pts + (t1 - pts) * np.arange(n) / n)
                acc.append(a)
        off += size
    return np.concatenate(ts), np.vstack(acc)


def save_json(samples: list[GpsSample], path: Path) -> None:
    path.write_text(json.dumps([s.__dict__ for s in samples], indent=1))


def load_json(path: Path) -> list[GpsSample]:
    return [GpsSample(**d) for d in json.loads(path.read_text())]


if __name__ == "__main__":
    import sys
    s = read_gps(Path(sys.argv[1]))
    good = [x for x in s if x.fix >= 2]
    print(f"{len(s)} samples, {len(good)} with fix, "
          f"{s[0].t:.2f}s..{s[-1].t:.2f}s")
    for x in s[:3] + s[-3:]:
        print(f"  t={x.t:6.2f} {x.lat:.6f} {x.lon:.6f} alt={x.alt:7.2f} "
              f"v={x.speed2d:.2f} fix={x.fix} dop={x.dop}")
