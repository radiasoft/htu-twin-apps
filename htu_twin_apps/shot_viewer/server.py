"""HTU shot viewer: browse HTU scans shot by shot, from the scan folders as HTU saves them.

Run `htu-shot-viewer [data directory] [--port N]` and open http://127.0.0.1:8050. The data
directory is the argument, or `$HTU_DATA` without one; every `scans/Scan*` folder below it with a
`ScanDataScan*.txt` is a scan.

A scan is aggregated by shot: one row per shot of the scalar table (`ScanDataScan*.txt`), and for
each device folder the frame of its HDF5 stack that belongs to that shot. A frame is matched to its
shot by timestamp: the table's `<device> acq_timestamp` is LabVIEW time (seconds since 1904), the
stack's `frame_acq_timestamp` Unix time. Stacks of frames without timestamps fall back to the frame
order.

The raw stacks are written with HDF5 2.0, so h5py >= 3.16 is needed.

:copyright: Copyright (c) 2026 RadiaSoft LLC.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""

from __future__ import annotations

import argparse
import configparser
import csv
import functools
import h5py
import http
import http.server
import io
import json
import math
import mimetypes
import numpy
import os
import pathlib
import re
import urllib.parse

# The data directory, below which the scans are found; set by main.
DATA = None
# Seconds from the LabVIEW epoch (1904-01-01) to the Unix epoch (1970-01-01).
LABVIEW_EPOCH_OFFSET_S = 2_082_844_800.0
# The largest side, in pixels, of an image sent to the browser; larger images are block-averaged.
MAX_IMAGE_SIDE = 400
# The scalar columns shown as machine settings: magnets, field probes, charge monitors, the gas
# jet, screen plungers, timing and motion stages; not camera statistics or timestamps.
SETTINGS = re.compile(
    r"^(U_EMQ\w*|U_Chicane(Inner|Outer|Motors)|U_V?S\d[HV]|U_[AB]CaveHallProbe|U_BCaveMagSpec"
    + r"|U_\w*ICT|U_ESP_JetXYZ|U_HP_Daq|U_Hexapod|U_VacuumGauge|U_DG645_ShotControl|U_1HzShiftedBox"
    + r"|U_VisaPlungers|U_CompAerotech|U_Amp4TelStage|U_StretchterXMCC|U_ModeImagerESP|U_ESP302_\d+"
    + r"|U_TRAServer\d+|U_Zaber|U_Velmex) "
)
STATIC = pathlib.Path(__file__).resolve().parent / "static"
# How far apart, in seconds, a frame's and a shot's timestamps may be and still match.
TIMESTAMP_TOLERANCE_S = 0.05


class Device:
    """A device folder's HDF5 stack: its kind (image, spectrum or trace) and frame per shot."""

    def __init__(self, name, path, kind, shape, frame_for_row):
        self.name = name
        self.path = path
        self.kind = kind
        self.shape = shape
        self.frame_for_row = frame_for_row

    def frame(self, row: int) -> dict | None:
        i = self.frame_for_row[row]
        if i < 0:
            return None
        with h5py.File(self.path, "r") as f:
            d = f["entry/data/data"][i]
        if self.kind == "spectrum":
            return {"x": _clean(d[:, 0]), "y": _clean(d[:, 1]), "frame": i}
        if self.kind == "trace":
            return {"x": list(range(d.shape[0])), "y": _clean(d), "frame": i}
        z, s = _downsample(numpy.asarray(d, dtype=numpy.float64))
        return {"z": _clean(z), "step": s, "frame": i}

    def summary(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "shape": list(self.shape[1:]),
            "frames": int(self.shape[0]),
            "matched": int(sum(1 for i in self.frame_for_row if i >= 0)),
        }


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = {k: v[-1] for k, v in urllib.parse.parse_qs(u.query).items()}
        try:
            if u.path.startswith("/api/"):
                return self._api(u.path[5:], q)
            return self._static(u.path)
        except KeyError as e:
            return self._error(http.HTTPStatus.NOT_FOUND, f"not found: {e}")
        except (ValueError, IndexError) as e:
            return self._error(http.HTTPStatus.BAD_REQUEST, str(e))

    def log_message(self, format, *args):  # quieter than the default: errors only
        if not str(args[1] if len(args) > 1 else "").startswith(("2", "3")):
            super().log_message(format, *args)

    def _api(self, name, query):
        if name == "scans":
            return self._json([scan(i).summary() for i in scan_folders()])
        s = scan(query["scan"])
        if name == "scan":
            return self._json(
                {
                    **s.summary(),
                    "info": s.info,
                    "columns": s.columns,
                    "shot": s.shots,
                    "bin": s.column("Bin #"),
                    "time": s.times(),
                    "settings": s.settings(),
                    "device_list": [d.summary() for d in s.devices.values()],
                }
            )
        n = [c for c in query.get("columns", "").split("\t") if c]
        if name == "series":
            return self._json({c: s.column(c) for c in n if c in s.columns})
        if name == "export.csv":
            return self._csv(s, n)
        if name == "shot":
            r = s.shots.index(int(query["shot"]))
            return self._json(
                {
                    "shot": s.shots[r],
                    "values": {
                        c: (_number(s.rows[r][i]) if i < len(s.rows[r]) else None)
                        for i, c in enumerate(s.columns)
                    },
                }
            )
        if name == "frame":
            r = s.shots.index(int(query["shot"]))
            return self._json(s.devices[query["device"]].frame(r))
        raise KeyError(name)

    def _csv(self, s: Scan, names: list[str]):
        n = [c for c in names if c in s.columns]
        v = [s.column(c) for c in n]
        o = io.StringIO()
        w = csv.writer(o)
        w.writerow(["shot", *n])
        for r, shot in enumerate(s.shots):
            w.writerow([shot, *("" if x[r] is None else x[r] for x in v)])
        self._send(
            o.getvalue().encode(),
            "text/csv; charset=utf-8",
            {
                "Content-Disposition": "attachment; filename="
                + f'"{s.id.replace("/", "_")}_shots.csv"',
            },
        )

    def _error(self, status, message):
        self._send(json.dumps({"error": message}).encode(), "application/json", status=status)

    def _json(self, value):
        self._send(json.dumps(value, allow_nan=False).encode(), "application/json")

    def _send(self, body, content_type, headers=None, status=http.HTTPStatus.OK):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _static(self, path):
        f = (STATIC / ("index.html" if path in ("", "/") else path.lstrip("/"))).resolve()
        if f.parent != STATIC or not f.is_file():
            raise KeyError(path)
        self._send(f.read_bytes(), mimetypes.guess_type(f.name)[0] or "text/plain")


class Scan:
    """One scan: its info, its scalar table and its device stacks, matched to shots."""

    def __init__(self, scan_id: str, folder: pathlib.Path):
        self.id = scan_id
        self.folder = folder
        self.info = _read_info(folder)
        self.columns, self.rows = _read_table(folder)
        self.shots = [
            int(v) if v is not None else i + 1
            for i, v in enumerate(self.column("Shotnumber") or [None] * len(self.rows))
        ]
        p = self.info.get("Scan Parameter", "")
        # a noscan names `Shotnumber` as its parameter: it scans nothing
        self.parameter = p if p in self.columns and p != "Shotnumber" else None
        self.devices = {
            d.name: d for d in (_device(self, x) for x in sorted(folder.glob("*/*.h5"))) if d
        }

    def column(self, name: str) -> list[float | None] | None:
        if name not in self.columns:
            return None
        i = self.columns.index(name)
        return [_number(r[i]) if i < len(r) else None for r in self.rows]

    def settings(self) -> list[dict]:
        """The machine-setting columns (`SETTINGS`) that hold numbers, with their per-shot values."""
        rv = []
        for n in self.columns:
            if SETTINGS.match(n) and "timestamp" not in n:
                v = self.column(n)
                if any(x is not None for x in v):
                    rv.append({"name": n, "values": v})
        return rv

    def summary(self) -> dict:
        return {
            "id": self.id,
            "description": self.info.get("ScanStartInfo", ""),
            "parameter": self.parameter,
            "shots": len(self.rows),
            "devices": len(self.devices),
        }

    def times(self) -> list[float | None]:
        """Each shot's time (Unix seconds): the acquisition time most shots have."""
        b = max(
            (self.column(c) for c in self.columns if c.endswith("acq_timestamp")),
            key=lambda v: sum(1 for t in v if t),
            default=[None] * len(self.rows),
        )
        return [t - LABVIEW_EPOCH_OFFSET_S if t else None for t in b]


def main():
    global DATA
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument(
        "data",
        nargs="?",
        type=pathlib.Path,
        default=os.environ.get("HTU_DATA"),
        help="the directory below which the scans are found (default: $HTU_DATA)",
    )
    p.add_argument("--port", type=int, default=8050)
    a = p.parse_args()
    if a.data is None:
        p.error("give the data directory, or set $HTU_DATA")
    DATA = pathlib.Path(a.data).resolve()
    if not DATA.is_dir():
        p.error(f"not a directory: {DATA}")
    print(f"{len(scan_folders())} scans under {DATA}")
    s = http.server.ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    print(f"serving on http://127.0.0.1:{a.port}")
    try:
        s.serve_forever()
    except KeyboardInterrupt:
        pass


@functools.cache
def scan(scan_id: str) -> Scan:
    return Scan(scan_id, scan_folders()[scan_id])


@functools.cache
def scan_folders() -> dict[str, pathlib.Path]:
    """Every scan below the data directory, by `<date folder>/<scan folder>`."""
    rv = {}
    for t in sorted(DATA.rglob("ScanDataScan*.txt")):
        f = t.parent
        if f.parent.name == "scans":
            rv[f"{f.parent.parent.name}/{f.name}"] = f
    return rv


def _clean(values) -> list:
    """`values` as nested lists of floats, with NaN and infinities as None (JSON has neither)."""
    return _nan_to_none(numpy.round(numpy.asarray(values, dtype=numpy.float64), 6).tolist())


def _device(s: Scan, path: pathlib.Path) -> Device | None:
    """The device of the stack at `path`, with its frames matched to the scan's shots."""
    try:
        with h5py.File(path, "r") as f:
            shape = f["entry/data/data"].shape
            a = f.get("entry/instrument/NDAttributes")
            t = [n for n in (a or []) if n.endswith("frame_acq_timestamp")]
            times = a[t[0]][...] if t else None
    except (OSError, KeyError):
        return None
    kind = _kind(shape)
    if kind is None:
        return None
    n = path.parent.name
    t = s.column(f"{n.split('-')[0]} acq_timestamp")
    if times is not None and t is not None:
        m = _match(times, t)
    else:
        m = [i if i < shape[0] else -1 for i in range(len(s.rows))]
    return Device(n, path, kind, shape, m)


def _downsample(image: numpy.ndarray) -> tuple[numpy.ndarray, int]:
    """`image` block-averaged so that no side exceeds MAX_IMAGE_SIDE, and the block size."""
    s = max(1, math.ceil(max(image.shape) / MAX_IMAGE_SIDE))
    if s == 1:
        return image, 1
    r, c = (image.shape[0] // s) * s, (image.shape[1] // s) * s
    return image[:r, :c].reshape(r // s, s, c // s, s).mean(axis=(1, 3)), s


def _kind(shape) -> str | None:
    """What a stack of `shape` holds: spectra (x, y pairs), images or traces; None for neither."""
    if len(shape) == 3:
        return "spectrum" if shape[-1] == 2 else "image"
    return "trace" if len(shape) == 2 else None


def _match(frame_times, table_times) -> list[int]:
    """For each table row, the index of the frame taken within TIMESTAMP_TOLERANCE_S of it, or -1."""
    f = numpy.asarray(frame_times, dtype=numpy.float64)
    o = numpy.argsort(f)
    s = f[o]

    def _frame(t):
        if t is None or not math.isfinite(t) or f.size == 0:
            return -1
        u = t - LABVIEW_EPOCH_OFFSET_S
        i = int(numpy.searchsorted(s, u))
        k = min((k for k in (i - 1, i) if 0 <= k < f.size), key=lambda k: abs(s[k] - u))
        return int(o[k]) if abs(s[k] - u) <= TIMESTAMP_TOLERANCE_S else -1

    return [_frame(t) for t in table_times]


def _nan_to_none(value):
    if isinstance(value, list):
        return [_nan_to_none(v) for v in value]
    return None if isinstance(value, float) and not math.isfinite(value) else value


def _number(text: str) -> float | None:
    try:
        v = float(text)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _read_info(folder: pathlib.Path) -> dict[str, str]:
    f = list(folder.glob("ScanInfoScan*.ini"))
    if not f:
        return {}
    p = configparser.ConfigParser(interpolation=None)
    p.optionxform = str  # keep the keys' case
    p.read(f[0])
    return {k: v.strip('"') for k, v in p["Scan Info"].items()} if "Scan Info" in p else {}


def _read_table(folder: pathlib.Path) -> tuple[list[str], list[list[str]]]:
    with open(next(folder.glob("ScanDataScan*.txt")), newline="") as f:
        r = list(csv.reader(f, delimiter="\t"))
    return [c.strip() for c in r[0]], [x for x in r[1:] if any(c.strip() for c in x)]


if __name__ == "__main__":
    main()
