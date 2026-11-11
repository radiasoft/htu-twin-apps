"""HTU twin viewer: step through a recorded HTU scan and see the twin's prediction beside the data.

Run `htu-twin-viewer <day> ... --source twin-fit-values.json [--root DIR] [--fbpic DIR] [--port
N]` and open http://127.0.0.1:8060. The days are the arguments: day names such as `26_0929`
(below `--root`) or day folders' paths (`htu_twin_apps.days`). Only those days'
folders are read, and nothing is searched for. The twin is `geecs-lume-twin` as
`htu_twin_apps.lpa_source` drives it (its PMQ fringe fields, the slit's jaws and blade, the fitted
calibration corrections), with the LPA source and corrections of the best fit.

The datasets are the scans of the given days. Each scan with raw data that saved both
spectrometer cameras' `-interpSpec` is one, a spectrum (or, with their `-ImageInterp` as well, the
spectrometer's image), named by its day and scan (`26_1001/Scan013`), with defaults read from the
folder (`_defaults`): the title from its `ScanInfo`, the slit out (the day's `slit` if it has one:
the slit is not logged), and the day's energy labels ("early": rescaled to the Sept 29 early
driver setting, `scans.CAM1_AXIS_START_MEV`; "recorded", the default: the driver's own labels,
`scans.recorded_axis_start`). DATASETS_FILE (or `--datasets`) holds only what the folders do not
say: per day, `energy_axis`, `slit` and a `note`; per scan, an entry whose fields replace the
defaults (`kind`: "scan016" for Scan016, which has no raw folder, or "aline" for an A-line
scan, which needs the file for its background and spectra; `slit`; `title`) or that adds a
`variant` of the scan (below). A scan is read when first selected, not when the list is built
(`/api/dataset`). A dataset's steps are the scan's steps,
or, for an entry with a `split` (a noscan's shots regrouped, with a `variant` name), groups of its
shots with an ICT charge above `min_ict_pc`, each step a group's mean (`_split`): `{"by": "ict" |
"time", "groups": N}` for N groups of equal size by rising charge or in time order, or `{"by":
"peak", "split_mev": E}` for the shots whose spectrum peaks below E and those that peak at E or
above.
For a step, the twin is run with the step's logged settings and the fit's corrections, and its
output is returned beside the measurement: the A-line camera's image (rendered as the camera
would see it, `aline.render`), or the spectrometer's spectrum and its energy against AngleAxis
image. A step is simulated when first asked for and cached, and the rest of its dataset is
simulated in the background.

The twin's source is the fit's (FIT_SOURCE) or, with `--fbpic DIR`, the beam at the plasma exit
of an fbpic run below DIR (each `*_diags` folder's last `data*.h5`, `source.from_fbpic`), chosen
per request (`source=`). The fit's corrections to the line apply with either.

A step can be run with edits (`/api/step?...&edits={"EMQ1H": 1.2, "source.divergence_x_mrad": 4}`):
values that replace what the twin runs with. The keys are the step's magnet currents
(STEP_KNOBS, the current the twin's magnet sees: the fitted scale is not applied to an edited
one), the fit's corrections (MACHINE_KNOBS) and, with the fit's source, the source's knobs
(SOURCE_KNOBS, prefixed `source.`). Any other key is refused.

The measured spectrometer image is the two cameras' ImageInterp side by side (Cam1 below the
seam, where Cam2's energy axis starts, Cam2 above). Each camera's image is in its own raw counts and its own
AngleAxis zero, so the stitch can be corrected (`scale=1`, `align=1`, both by default): each
camera's image scaled to its `-interpSpec` (the camera's calibrated spectrum), and Cam2 shifted in
AngleAxis so that its centroid within SEAM_WINDOW_MEV of the seam matches Cam1's, per step.

:copyright: Copyright (c) 2026 RadiaSoft LLC.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""

from __future__ import annotations

import argparse
import configparser
import csv
import dataclasses
import http
import http.server
import json
import math
import mimetypes
import numpy
import pathlib
import threading
import urllib.parse

from htu_twin_apps import days
from htu_twin_apps.lpa_source import scans as htu_scans

# The days and recorded scans the viewer offers (see the module's docstring).
DATASETS_FILE = pathlib.Path(__file__).resolve().parent / "datasets.json"
DEFAULT_PORT = 8060
# A day's settings the datasets file does not give: the driver's own energy labels, the slit out.
DAY_CONFIG = {
    "energy_axis": "recorded",
    "slit": "out",
    "note": "energies as the driver labelled them (not verified)",
}
# The fit's source's id among the sources (`source=`).
FIT_SOURCE = "fit"
# The fit's machine-state corrections an edit may replace.
MACHINE_KNOBS = (
    "aline_um_per_px",
    "chicane_jaw1_mm",
    "emq1_x_mm",
    "emq1_y_mm",
    "emq2_x_mm",
    "emq2_y_mm",
    "emq3_x_mm",
    "emq3_y_mm",
    "pmq_scale",
    "pmq_x_mm",
    "pmq_y_mm",
    "pmq_z_mm",
    "slit_blade_high_mm",
    "slit_blade_low_mm",
)
# Simulated steps kept (edited and not); the oldest are dropped past it.
MAX_CACHE = 500
# The largest side, in pixels, of an image sent to the browser; larger images are block-averaged.
MAX_IMAGE_SIDE = 160
# Particles the twin tracks per step.
PARTICLES = 20_000
# The energy [MeV] either side of the cameras' seam whose AngleAxis centroids align them.
SEAM_WINDOW_MEV = 4.0
# The source's knobs an edit may replace (`source.<knob>`), with their labels and units.
SOURCE_KNOBS = {
    "divergence_x_mrad": ("divergence x", "mrad"),
    "divergence_y_mrad": ("divergence y", "mrad"),
    "pointing_x_mrad": ("pointing x", "mrad"),
    "pointing_y_mrad": ("pointing y", "mrad"),
    "size_x_um": ("size x", "um"),
    "size_y_um": ("size y", "um"),
    "energy_mev": ("energy peak", "MeV"),
    "energy_sigma_mev": ("energy sigma", "MeV"),
    "energy_tail_mev": ("energy tail", "MeV"),
}
# The spectrometer image's bins: energy [MeV] and AngleAxis.
SPECTROMETER_BINS = ((45.0, 250.0, 2.0), (-24.0, 24.0, 0.5))
# The cameras' AngleAxis windows (the same on every day so far).
SPECTROMETER_WINDOWS = {"Cam1": (-23.5, 23.5), "Cam2": (-17.5, 19.75)}
STATIC = pathlib.Path(__file__).resolve().parent / "static"
# The step's logged magnet currents [A] an edit may replace.
STEP_KNOBS = ("EMQ1H", "EMQ2V", "EMQ3H", "S1H", "S1V", "S3H", "chicane_current")
# The viewer; set by main.
VIEWER = None


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        try:
            if u.path == "/api/datasets":
                return self._json(VIEWER.datasets())
            if u.path == "/api/dataset":
                q = urllib.parse.parse_qs(u.query)
                return self._json(VIEWER.dataset(q["scan"][0]))
            if u.path == "/api/step":
                q = urllib.parse.parse_qs(u.query)
                return self._json(
                    VIEWER.step(
                        q["scan"][0],
                        int(q["step"][0]),
                        json.loads(q.get("edits", ["{}"])[0]),
                        q.get("scale", ["1"])[0] == "1",
                        q.get("align", ["1"])[0] == "1",
                        q.get("source", [FIT_SOURCE])[0],
                    )
                )
            return self._static(u.path)
        except (KeyError, IndexError, ValueError) as e:
            return self._send(
                json.dumps({"error": str(e)}).encode(),
                "application/json",
                status=http.HTTPStatus.BAD_REQUEST,
            )

    def log_message(self, format, *args):  # quieter than the default: errors only
        pass

    def _json(self, value):
        self._send(
            json.dumps(_clean(value), allow_nan=False).encode(), "application/json"
        )

    def _send(self, body, content_type, status=http.HTTPStatus.OK):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _static(self, path):
        f = (STATIC / (path.lstrip("/") or "index.html")).resolve()
        if STATIC not in f.parents or not f.is_file():
            return self._send(
                b"not found", "text/plain", status=http.HTTPStatus.NOT_FOUND
            )
        self._send(f.read_bytes(), mimetypes.guess_type(f.name)[0] or "text/plain")


class Viewer:
    """The data, the twin's sources and corrections, and the cache of simulated steps."""

    def __init__(
        self,
        day_dirs: dict,
        source_path: pathlib.Path,
        particles: int,
        datasets_path: pathlib.Path,
        fbpic: pathlib.Path | None,
    ):
        from htu_twin_apps.lpa_source import aline, source

        self.day_dirs = dict(day_dirs)
        j = json.loads(source_path.read_text())
        self.machine_state = dict(j["machine_state"])
        if aline.PIXEL_KEY not in self.machine_state:
            # a finished A-line fit saves no pixel size; its log has it
            self.machine_state[aline.PIXEL_KEY] = _logged_pixel(source_path)
        self.source = dataclasses.replace(
            source.LPASource(**j["source"]), num_particles=particles
        )
        self.source_label = source_path.name
        m = json.loads(datasets_path.read_text())
        self.day_config = {
            d: {**DAY_CONFIG, **m["days"].get(d, {})} for d in self.day_dirs
        }
        self._scans = {d: days.scan_folders(f) for d, f in self.day_dirs.items()}
        self.entries = _entries(
            self.day_dirs, self._scans, self.day_config, m["datasets"]
        )
        # id: (label, path); the fit's has no file of particles
        self.sources = {
            FIT_SOURCE: (f"fitted ({source_path.name})", None),
            **_fbpic_runs(fbpic),
        }
        self._cache = {}
        self._datasets = {}
        self._edited_particles = (None, None)
        self._fbpic = {}
        self._lock = threading.Lock()
        # one simulation at a time: requests and the background share the twin's line cache
        self._compute = threading.Lock()
        self._particles = None
        self._wanted = None
        self._worker = None

    def dataset(self, scan: str) -> dict:
        """`scan`'s steps, their labels (for regrouped shots) and the setting it scans: what the
        list leaves to its first use, since reading a scan takes time."""
        d = self._dataset(self._entry(scan))
        return {
            "steps": len(d["steps"]),
            "step_labels": d["labels"],
            "scanned": d["scanned"],
        }

    def datasets(self) -> dict:
        """The datasets offered, the sources and the fit the twin runs with."""
        return {
            "source": self.source_label,
            "sources": [{"id": k, "label": v[0]} for k, v in self.sources.items()],
            "datasets": [
                {"scan": n, "day": e["day"], "kind": e["kind"], "title": e["title"]}
                for n, e in self.entries.items()
                if self._exists(n)
            ],
        }

    def step(
        self,
        scan: str,
        index: int,
        edits: dict,
        scale: bool = True,
        align: bool = True,
        source: str = FIT_SOURCE,
    ) -> dict:
        """The twin's output and the measurement at dataset `scan`'s step `index` with `edits`
        and `source` (see the module's docstring; computed if need be), the spectrometer image's
        stitch corrected as `scale` and `align` say, and the rest of the dataset started in the
        background with the same edits and source."""
        n = self._entry(scan)
        d = self._dataset(n)
        if not 0 <= index < len(d["steps"]):
            raise IndexError(f"{n} has {len(d['steps'])} steps")
        if source not in self.sources:
            raise ValueError(f"source {source!r} not one of {sorted(self.sources)}")
        e = _edits(edits)
        if source != FIT_SOURCE and any(k.startswith("source.") for k, _ in e):
            raise ValueError("source edits apply to the fitted source only")
        rv = self._step(n, index, e, source)
        self._background(n, e, source)
        if d["kind"] != "magspec":
            return rv
        i, k = _stitched(d["steps"][index]["cameras"], scale, align)
        # the cached result is shared: a copy with this stitch
        return {
            **rv,
            "measured": {**rv["measured"], "image": i},
            "stitch": {"scale": scale, "align": align, "cam2_shift": k},
        }

    def _background(self, scan: str, edits: tuple, source: str) -> None:
        """Simulates `scan`'s steps with `edits` and `source`; a worker already running switches
        to them."""

        def _done(w):
            with self._lock:
                if w is not None and self._wanted != w:
                    return False
                if self._worker is threading.current_thread():
                    self._worker = None
                return True

        def _run():
            try:
                while True:
                    with self._lock:
                        w = self._wanted
                    for i in range(len(self._dataset(w[0])["steps"])):
                        if self._wanted != w:
                            break
                        self._step(w[0], i, w[1], w[2])
                    if _done(w):
                        return
            finally:
                _done(None)

        with self._lock:
            self._wanted = (scan, edits, source)
            if self._worker is not None:
                return
            self._worker = threading.Thread(target=_run, daemon=True)
        self._worker.start()

    def _dataset(self, name: str) -> dict:
        e = self.entries[name]
        with self._lock:
            if name not in self._datasets:
                self._datasets[name] = _load(
                    self.day_dirs[e["day"]],
                    e,
                    self.day_config[e["day"]],
                )
            return self._datasets[name]

    def _edited(self, edits: tuple, source: str) -> tuple:
        """(source, particles, machine_state, step_state): the fit's with `edits` applied; the
        source None for an fbpic run's."""
        from htu_twin_apps.lpa_source import source as lpa_source, twin

        e = dict(edits)
        if source == FIT_SOURCE:
            s = dataclasses.replace(
                self.source,
                **{k[7:]: v for k, v in e.items() if k.startswith("source.")},
            )
            if s == self.source:
                p = self._sampled()
            else:
                with self._lock:
                    if self._edited_particles[0] != s:
                        self._edited_particles = (s, lpa_source.particles(s))
                    p = self._edited_particles[1]
        else:
            s = None
            with self._lock:
                if source not in self._fbpic:
                    self._fbpic[source] = lpa_source.from_fbpic(self.sources[source][1])
                p = self._fbpic[source]
        m = {**self.machine_state, **{k: v for k, v in e.items() if k in MACHINE_KNOBS}}
        t = {k: v for k, v in e.items() if k in STEP_KNOBS}
        for k in t:
            if k in twin.SCALES:
                # an edited current is what the twin's magnet sees
                m[twin.SCALES[k]] = 1.0
        return s, p, m, t

    def _entry(self, scan: str) -> str:
        """The dataset named `scan`: its full name, or a scan folder name only one day has."""
        if scan in self.entries:
            return scan
        f = [n for n in self.entries if n.endswith(f"/{scan}") and ":" not in n]
        if len(f) != 1:
            raise KeyError(f"no single dataset {scan!r}")
        return f[0]

    def _exists(self, name: str) -> bool:
        e = self.entries[name]
        if e["kind"] == "scan016":
            return (self.day_dirs[e["day"]] / "analysis" / "s16.txt").is_file()
        return e["scan"] in self._scans[e["day"]]

    def _sampled(self):
        from htu_twin_apps.lpa_source import source

        with self._lock:
            if self._particles is None:
                self._particles = source.particles(self.source)
            return self._particles

    def _step(self, scan: str, index: int, edits: tuple, source: str) -> dict:
        key = (scan, index, edits, source)
        with self._lock:
            if key in self._cache:
                return self._cache[key]
        d = self._dataset(scan)
        with self._compute:
            with self._lock:
                if key in self._cache:
                    return self._cache[key]
            s, p, m, t = self._edited(edits, source)
            rv = _simulate(d, index, p, m, t)
            rv["settings"] = _settings(
                d,
                index,
                s,
                m,
                t,
                None if s else (self.sources[source][0], _beam_summary(p)),
            )
            rv.update(
                scan=scan,
                step=index,
                kind=d["kind"],
                source=self.sources[source][0],
                edits=dict(edits),
            )
            with self._lock:
                if len(self._cache) >= MAX_CACHE:
                    del self._cache[next(iter(self._cache))]
                self._cache[key] = rv
        return rv


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument(
        "days",
        nargs="+",
        help="the days to read: names such as 26_0929, or day folders' paths",
    )
    p.add_argument(
        "--root",
        type=pathlib.Path,
        help="the data root, the folder holding Y2026",
    )
    p.add_argument("--source", type=pathlib.Path, help="the fit's saved source (JSON)")
    p.add_argument(
        "--datasets",
        type=pathlib.Path,
        default=DATASETS_FILE,
        help="the days and datasets offered (JSON; default datasets.json)",
    )
    p.add_argument(
        "--fbpic", type=pathlib.Path, help="fbpic runs offered as sources (a directory)"
    )
    p.add_argument("--particles", type=int, default=PARTICLES)
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--threads", type=int, default=2, help="torch threads (default 2)")
    a = p.parse_args()
    try:
        day_dirs = days.folders(a.days, a.root)
    except (FileNotFoundError, ValueError) as e:
        p.error(str(e))
    s = a.source
    if s is None:
        p.error("no source: give --source")
    import torch

    torch.set_num_threads(a.threads)
    global VIEWER
    VIEWER = Viewer(day_dirs, s, a.particles, a.datasets, a.fbpic)
    print(f"HTU twin viewer: http://127.0.0.1:{a.port} (source {s})", flush=True)
    http.server.ThreadingHTTPServer(("0.0.0.0", a.port), Handler).serve_forever()


def _axis_start(folder: pathlib.Path, labelling: str) -> float | None:
    """`scans.energy_axis`'s `start_mev` for a day's energy `labelling` ("early" or "recorded")."""
    if labelling == "early":
        return None
    if labelling == "recorded":
        return htu_scans.recorded_axis_start(folder)
    raise ValueError(f"energy_axis {labelling!r} not early or recorded")


def _aline_image(folder: pathlib.Path, rows: list, steps: list) -> list:
    """Per step, the A-line camera's mean frame in the fits' ROI, minus Scan022's background."""
    from htu_twin_apps.lpa_source import aline

    b, _ = htu_scans.stack(folder.parent / aline.BACKGROUND, aline.CAMERA, [])
    b = numpy.median(b[:, aline.ROI[0], aline.ROI[1]].astype(numpy.float32), axis=0)
    a, z = htu_scans.stack(folder, aline.CAMERA, rows)
    n = htu_scans.step_numbers(rows)
    rv = []
    for i in steps:
        f = [z[r] for r, m in enumerate(n) if m == i and z[r] >= 0]
        rv.append(
            a[f][:, aline.ROI[0], aline.ROI[1]].astype(numpy.float32).mean(axis=0) - b
        )
    return rv


def _beam_summary(particles) -> str:
    """A ParticleGroup's charge, energy and divergence at the plasma exit, in a few words."""
    e = numpy.asarray(particles["energy"]) / 1e6
    w = numpy.asarray(particles["weight"])

    def _rms(v):
        return float(
            numpy.sqrt(numpy.average((v - numpy.average(v, weights=w)) ** 2, weights=w))
        )

    return (
        f"{w.sum() * 1e12:.0f} pC, {numpy.average(e, weights=w):.0f} +- {_rms(e):.0f} MeV, "
        + f"div. {_rms(numpy.asarray(particles['xp']) * 1e3):.1f} / "
        + f"{_rms(numpy.asarray(particles['yp']) * 1e3):.1f} mrad"
    )


def _clean(value):
    """`value` with NaN and infinite numbers as None and numpy values as Python ones."""
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, numpy.ndarray):
        return _clean(value.tolist())
    if isinstance(value, (numpy.floating, float)):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, numpy.integer):
        return int(value)
    return value


def _defaults(day: str, scan: str, folder: pathlib.Path, config: dict) -> dict:
    """A scan's dataset entry as the folder gives it: its title from `ScanInfo` (with the slit
    noted as assumed), the slit as the day's `config` has it, and its kind, a spectrum or the
    spectrometer's image if it saved both cameras' `-interpSpec`, else None (not a dataset).
    """
    saved = {x.name for x in folder.iterdir() if x.is_dir()}
    spectra = {f"UC_BCaveMagSpec{c}-interpSpec" for c in ("Cam1", "Cam2")}
    images = {f"UC_BCaveMagSpec{c}-ImageInterp" for c in ("Cam1", "Cam2")}
    p = configparser.ConfigParser(interpolation=None)
    p.read(sorted(folder.glob("ScanInfoScan*.ini")))
    t = p["Scan Info"].get("ScanStartInfo", "").strip('"') if "Scan Info" in p else ""
    return {
        "day": day,
        "scan": scan,
        "kind": (
            None
            if not spectra <= saved
            else "magspec" if images <= saved else "spectrum"
        ),
        "slit": config["slit"],
        "title": f"{t or 'no description'} (slit not logged: assumed {config['slit']})",
    }


def _downsample(image: numpy.ndarray) -> numpy.ndarray:
    k = max(1, math.ceil(max(image.shape) / MAX_IMAGE_SIDE))
    r, c = (image.shape[0] // k) * k, (image.shape[1] // k) * k
    return image[:r, :c].reshape(r // k, k, c // k, k).mean(axis=(1, 3))


def _edits(edits: dict) -> tuple:
    """`edits` checked (known keys, finite numbers), as a sorted tuple to key the cache."""
    if not isinstance(edits, dict):
        raise ValueError("edits must be an object")
    for k, v in edits.items():
        if not (
            k in MACHINE_KNOBS
            or k in STEP_KNOBS
            or (k.startswith("source.") and k[7:] in SOURCE_KNOBS)
        ):
            raise ValueError(f"edits: {k!r} is not editable")
        if (
            isinstance(v, bool)
            or not isinstance(v, (int, float))
            or not math.isfinite(v)
        ):
            raise ValueError(f"edits: {k!r} must be a finite number")
    return tuple(sorted((k, float(v)) for k, v in edits.items()))


def _entries(day_dirs: dict, scans: dict, config: dict, described: list) -> dict:
    """{name: entry} of the datasets: each scan of the days with a kind (`_defaults`), and the
    described entries of the datasets file over those defaults, in order of day, scan, variant.
    A described entry of a scan with no folder (Scan016) stands on its own."""
    base = {
        (d, n): _defaults(d, n, x, config[d])
        for d in day_dirs
        for n, x in scans[d].items()
    }
    rv = {}
    for (d, n), e in base.items():
        if e["kind"]:
            rv[(d, n, "")] = e
    for e in described:
        if e["day"] not in day_dirs:
            continue
        k = (e["day"], e["scan"], e.get("variant", ""))
        b = base.get((k[0], k[1]), {})
        m = {**b, **e}
        if "kind" not in m or not m["kind"]:
            raise ValueError(f"datasets file: {k[0]}/{k[1]} needs a kind")
        m.setdefault("slit", config[k[0]]["slit"])
        if "title" not in e:
            m["title"] = m.get("title", k[1]) + (f" [{k[2]}]" if k[2] else "")
        rv[k] = m
    return {
        f"{d}/{n}" + (f":{v}" if v else ""): rv[(d, n, v)] for d, n, v in sorted(rv)
    }


def _fbpic_runs(directory: pathlib.Path | None) -> dict:
    """{id: (label, path)} of the fbpic runs below `directory`: each `*_diags` folder's last
    `data*.h5` (the beam at the plasma exit), sorted by the run's name as a number where it is
    one (a density scan's `4e+18_diags`)."""
    if directory is None:
        return {}
    rv = []
    for d in sorted(pathlib.Path(directory).glob("*_diags")):
        f = sorted(d.glob("*/data*.h5"))
        if not f:
            continue
        n = d.name[: -len("_diags")]
        try:
            k = (0, float(n), n)
        except ValueError:
            k = (1, 0.0, n)
        rv.append((k, f"fbpic:{n}", (f"FBPIC {n} ({f[-1].stem})", f[-1])))
    if not rv:
        raise FileNotFoundError(
            f"no fbpic runs (*_diags/**/data*.h5) below {directory}"
        )
    return {i: v for _, i, v in sorted(rv)}


def _fmt(value, digits=2):
    return "n/a" if value is None or not math.isfinite(value) else f"{value:.{digits}f}"


def _load(data: pathlib.Path, entry: dict, day: dict) -> dict:
    """A dataset (`entry` of DATASETS_FILE, its day folder `data`, its `day`'s settings): its
    steps (each with its logged machine state and measurement), the rows of each step for the
    logged values, the variable it scans, its slit, its energy labelling and the cameras' seam.
    """
    from htu_twin_apps.lpa_source import aline, compare, slit, twin

    scan, kind = entry["scan"], entry["kind"]
    rv = {
        "kind": kind,
        "slit": entry["slit"],
        "energy_note": day.get("note", ""),
        "labels": None,
    }
    if kind == "scan016":
        f = data / "analysis" / "s16.txt"
        with open(f, newline="") as x:
            rows = list(csv.DictReader(x, delimiter="\t"))
        m = compare.measured(data, 16)
        s = {**htu_scans.machine_state(rows), **twin.SCAN016_STATE}
        return {
            **rv,
            "rows": [rows],
            "scanned": None,
            "steps": [
                {"machine_state": s, "energy_mev": m.energy_mev, "density": m.density}
            ],
            "measured016": m,
        }
    folder, rows = htu_scans.table(data, scan)
    a = _axis_start(folder, day["energy_axis"])
    labels = None
    if entry.get("split"):
        n, labels = _split(folder, rows, entry["split"], a)
        rv["labels"] = labels
    else:
        n = htu_scans.step_numbers(rows)
    u = sorted(x for x in set(n) if x >= 0)
    by = [[r for r, k in zip(rows, n) if k == i] for i in u]
    if kind == "aline":
        st = aline.measured(data, scan, a)
        img = _aline_image(folder, rows, u)
        steps = [
            {
                "machine_state": x.machine_state,
                "aline": x,
                "image": i,
                "centroid": x.centroid,
                "size": x.size,
            }
            for x, i in zip(st, img)
        ]
    else:
        st = slit.measured(data, scan, a, n)
        steps = [
            {
                "machine_state": x.machine_state,
                "energy_mev": x.energy_mev,
                "density": x.density,
            }
            for x in st
        ]
        if kind == "magspec":
            # POSIT: Cam2's energy axis starts where Cam1's image gives way to it
            rv["seam_mev"] = float(htu_scans.energy_axis(folder, "Cam2", a)[0])
            for x, c in zip(
                steps, _magspec_images(folder, rows, u, a, rv["seam_mev"], n)
            ):
                x["cameras"] = c
    return {
        **rv,
        "rows": by,
        "scanned": None if labels else _scanned(by),
        "steps": steps,
    }


def _logged_pixel(source_path: pathlib.Path) -> float:
    from htu_twin_apps.lpa_source import aline

    log = source_path.with_name(source_path.name.replace("_source.json", ".log"))
    if not log.exists():
        return aline.DEFAULT_UM_PER_PX
    r = [json.loads(x) for x in open(log)]
    return min(r, key=lambda x: x["value"])["values"].get(
        aline.PIXEL_KEY, aline.DEFAULT_UM_PER_PX
    )


def _magspec_images(
    folder: pathlib.Path,
    rows: list,
    steps: list,
    axis_start: float | None,
    seam: float,
    numbers: list | None = None,
) -> list:
    """Per step, each camera's mean ImageInterp binned onto SPECTROMETER_BINS (energy on the
    axis `axis_start` gives, as for `scans.energy_axis`), with the scale to its `-interpSpec` and
    its AngleAxis centroid within SEAM_WINDOW_MEV of the cameras' `seam` [MeV] (`_stitched` puts
    them together): {camera: {"image", "scale", "seam"}}. `numbers`: each row's step, as for
    `slit.measured`."""
    (e0, e1, de), (a0, a1, da) = SPECTROMETER_BINS
    eb = numpy.arange(e0, e1 + de / 2, de)
    ab = numpy.arange(a0, a1 + da / 2, da)
    n = htu_scans.step_numbers(rows) if numbers is None else list(numbers)
    rv = [{} for _ in steps]
    y = (ab[:-1] + ab[1:]) / 2
    x = (eb[:-1] + eb[1:]) / 2
    for c in SPECTROMETER_WINDOWS:
        i, z = htu_scans.stack(folder, f"UC_BCaveMagSpec{c}-ImageInterp", rows)
        p, g = htu_scans.stack(folder, f"UC_BCaveMagSpec{c}-interpSpec", rows)
        # the seam's columns on this camera's side
        k = (
            (x >= seam - SEAM_WINDOW_MEV) & (x < seam)
            if c == "Cam1"
            else (x >= seam) & (x < seam + SEAM_WINDOW_MEV)
        )
        d, _ = htu_scans.stack(folder, f"UC_BCaveMagSpec{c}-interpDiv", [])
        e = htu_scans.energy_axis(folder, c, axis_start)
        # POSIT: ImageInterp's rows are interpDiv's AngleAxis reversed (energy_profiles)
        a = d[0, ::-1, 0].astype(float)
        ee, aa = numpy.meshgrid(e, a)
        for j, t in enumerate(steps):
            f = [z[r] for r, m in enumerate(n) if m == t and z[r] >= 0]
            w = numpy.clip(i[f].astype(float), 0, None).mean(axis=0)
            h, _, _ = numpy.histogram2d(
                aa.ravel(), ee.ravel(), bins=(ab, eb), weights=w.ravel()
            )
            # POSIT: -interpSpec's columns are (energy, spectrum) on ImageInterp's energy grid
            v = [g[r] for r, m in enumerate(n) if m == t and g[r] >= 0]
            q = h[:, k].sum(axis=1)
            rv[j][c] = {
                "image": h,
                "scale": (
                    float(p[v][:, :, 1].astype(float).mean(axis=0).sum() / w.sum())
                    if v and w.sum() > 0
                    else 1.0
                ),
                "seam": float((q * y).sum() / q.sum()) if q.sum() > 0 else None,
            }
    return rv


def _scanned(rows_by_step: list) -> str | None:
    """The twin key of the logged setting that changes most across the steps, if any changes."""
    if len(rows_by_step) < 2:
        return None
    s = [htu_scans.machine_state(r) for r in rows_by_step]
    k = max(s[0], key=lambda x: numpy.ptp([v.get(x, 0.0) for v in s]))
    return k if numpy.ptp([v.get(k, 0.0) for v in s]) > 0 else None


def _settings(
    dataset: dict,
    index: int,
    source,
    machine_state: dict,
    step_state: dict,
    beam: tuple | None = None,
) -> list:
    """The synoptic's elements, in beam order: what was logged at the step, what the twin ran
    with, the fitted correction between, and the knobs an edit may set (key, label, value the
    twin ran with, unit). `source` is the fit's `LPASource`, or None for an fbpic run's beam,
    `beam` then its (label, summary)."""
    from htu_twin_apps.lpa_source import aline, twin

    s = dataset["steps"][index]["machine_state"]
    m = machine_state
    rows = dataset["rows"][index]
    t = {**s, **step_state}

    def _logged(column):
        v = [htu_scans.number(r.get(column)) for r in rows]
        v = [x for x in v if x is not None]
        return float(numpy.median(v)) if v else None

    def _scale(key, scale):
        return t.get(key, 0.0) * m.get(scale, 1.0)

    def _note(key, note):
        return "edited" if key in step_state else note

    aline_kind = dataset["kind"] == "aline"
    slit_in = dataset["slit"] == "in"
    return [
        {
            "id": "source",
            "label": "LPA source",
            "logged": f"ICT {_fmt(_logged('U_BCaveICT Python Results.ChA'))} pC",
            "twin": (
                beam[1]
                if source is None
                else f"divergence {source.divergence_x_mrad:.1f} / {source.divergence_y_mrad:.1f} mrad, "
                + f"pointing {source.pointing_x_mrad:.1f} / {source.pointing_y_mrad:.1f} mrad"
            ),
            "note": f"{beam[0]}, at the plasma exit" if source is None else "fitted",
            "knobs": (
                []
                if source is None
                else [
                    [f"source.{k}", l, getattr(source, k), u]
                    for k, (l, u) in SOURCE_KNOBS.items()
                ]
            ),
        },
        {
            "id": "pmq",
            "label": "PMQ triplet",
            "logged": f"hexapod y {_fmt(_logged('U_Hexapod ypos'))}, z {_fmt(_logged('U_Hexapod zpos'))}, "
            + f"yaw {_fmt(_logged('U_Hexapod wangle'), 3)} deg",
            "twin": f"x {m.get('pmq_x_mm', 0):+.2f}, y {m.get('pmq_y_mm', 0):+.2f}, "
            + f"z {m.get('pmq_z_mm', 0):+.2f} mm",
            "note": "fitted offsets (twin frame)",
            "knobs": [
                ["pmq_x_mm", "x", m.get("pmq_x_mm", 0.0), "mm"],
                ["pmq_y_mm", "y", m.get("pmq_y_mm", 0.0), "mm"],
                ["pmq_z_mm", "z", m.get("pmq_z_mm", 0.0), "mm"],
                ["pmq_scale", "gradient scale", m.get("pmq_scale", 1.0), ""],
            ],
        },
        {
            "id": "S1H",
            "label": "S1H",
            "logged": f"{_fmt(s.get('S1H'))} A",
            "twin": f"{_fmt(_scale('S1H', 's1h_scale'), 3)} A",
            "note": _note("S1H", f"x{m.get('s1h_scale', 1.0):.3f} (fitted strength)"),
            "knobs": [["S1H", "current", _scale("S1H", "s1h_scale"), "A"]],
        },
        {
            "id": "S1V",
            "label": "S1V",
            "logged": f"{_fmt(s.get('S1V'))} A",
            "twin": f"{_fmt(t.get('S1V'), 3)} A",
            "note": _note("S1V", "twin's calibration (not fitted)"),
            "knobs": [["S1V", "current", t.get("S1V", 0.0), "A"]],
        },
        {
            "id": "chicane",
            "label": "Chicane",
            "logged": f"{_fmt(s.get('chicane_current'), 3)} A",
            "twin": f"{_fmt(t.get('chicane_current'), 3)} A",
            "note": _note("chicane_current", "twin's B-I table"),
            "knobs": [
                ["chicane_current", "current", t.get("chicane_current", 0.0), "A"]
            ],
        },
        {
            "id": "slit",
            "label": "Slit",
            "logged": "not logged",
            "twin": (
                "out"
                if not slit_in
                else f"jaw {m.get('chicane_jaw1_mm', 20):.2f} mm, blade "
                + f"{m.get('slit_blade_low_mm', float('nan')):.2f}-{m.get('slit_blade_high_mm', float('nan')):.2f} mm"
            ),
            "note": (
                "fitted"
                if slit_in
                else ("" if dataset["kind"] == "scan016" else "not logged: assumed out")
            ),
            "knobs": (
                [
                    ["chicane_jaw1_mm", "jaw", m.get("chicane_jaw1_mm", 20.0), "mm"],
                    [
                        "slit_blade_low_mm",
                        "blade low",
                        m.get("slit_blade_low_mm"),
                        "mm",
                    ],
                    [
                        "slit_blade_high_mm",
                        "blade high",
                        m.get("slit_blade_high_mm"),
                        "mm",
                    ],
                ]
                if slit_in
                else []
            ),
        },
        *[
            {
                "id": k,
                "label": k[:4],
                "logged": f"{_fmt(s.get(k))} A"
                + (
                    ""
                    if _logged(f"U_EMQTripletBipolar Current_Limit.Ch{k[3]}")
                    is not None
                    else " (nominal)"
                ),
                "twin": f"{_fmt(_scale(k, x), 3)} A",
                "note": _note(
                    k,
                    f"x{m.get(x, 1.0):.3f}, offset {m.get(twin.OFFSETS[k][0], 0):+.2f} / "
                    + f"{m.get(twin.OFFSETS[k][1], 0):+.2f} mm",
                ),
                "knobs": [
                    [k, "current", _scale(k, x), "A"],
                    [
                        twin.OFFSETS[k][0],
                        "offset x",
                        m.get(twin.OFFSETS[k][0], 0.0),
                        "mm",
                    ],
                    [
                        twin.OFFSETS[k][1],
                        "offset y",
                        m.get(twin.OFFSETS[k][1], 0.0),
                        "mm",
                    ],
                ],
            }
            for k, x in twin.SCALES.items()
            if k.startswith("EMQ")
        ],
        {
            "id": "S3H",
            "label": "S3H",
            "logged": f"{_fmt(s.get('S3H'))} A",
            "twin": f"{_fmt(t.get('S3H'))} A",
            "note": _note("S3H", ""),
            "knobs": [["S3H", "current", t.get("S3H", 0.0), "A"]],
        },
        {
            "id": "magspec",
            "label": "Spectrometer",
            "logged": "field not logged",
            "twin": "off (A-line)" if aline_kind else f"on; {dataset['energy_note']}",
            "note": "",
        },
        {
            "id": "aline",
            "label": "A-line camera",
            "logged": "images" if aline_kind else "",
            "twin": (
                f"{m.get(aline.PIXEL_KEY, aline.DEFAULT_UM_PER_PX):.0f} um/px"
                if aline_kind
                else ""
            ),
            "note": "fitted pixel size" if aline_kind else "",
            "knobs": (
                [
                    [
                        aline.PIXEL_KEY,
                        "pixel",
                        m.get(aline.PIXEL_KEY, aline.DEFAULT_UM_PER_PX),
                        "um",
                    ]
                ]
                if aline_kind
                else []
            ),
        },
    ]


def _simulate(
    dataset: dict, index: int, particles, machine_state: dict, step_state: dict
) -> dict:
    """The twin's output beside the measurement, and the numbers compared; `step_state`
    replaces settings the step logged."""
    from htu_twin_apps.lpa_source import aline, compare, fit, twin

    s = dataset["steps"][index]
    k = dataset["kind"]
    tw = {x: v for x, v in machine_state.items() if x != aline.PIXEL_KEY}
    if k == "aline":
        a = dataclasses.replace(
            s["aline"], machine_state={**s["aline"].machine_state, **step_state}
        )
        img, _, _ = aline.render(particles, a, machine_state, "jaws_blade")
        sim = aline.spot(img, 0, 0) if img is not None else numpy.full(4, numpy.nan)
        return {
            "measured": {"image": _downsample(s["image"])},
            "twin": {"image": _downsample(img) if img is not None else None},
            "numbers": [
                ["rms size x [px]", s["size"][0], sim[2]],
                ["rms size y [px]", s["size"][1], sim[3]],
                ["centroid x [px]", s["centroid"][0], None],
                ["centroid y [px]", s["centroid"][1], None],
            ],
        }
    if k == "scan016":
        t = twin.to_spectrometer(
            particles,
            {**twin.SCAN016_STATE, **step_state, **twin.without_slit(tw)},
            reference_mev=fit.REFERENCE_MEV,
        )
    elif dataset["slit"] == "out":
        t = twin.to_spectrometer(
            particles,
            {**s["machine_state"], **step_state, **twin.without_slit(tw)},
            reference_mev=fit.REFERENCE_MEV,
        )
    else:
        t = twin.to_spectrometer(
            particles,
            {**s["machine_state"], **step_state, **tw},
            reference_mev=fit.REFERENCE_MEV,
            slit="jaws_blade",
        )
    e = s["energy_mev"]
    p = compare.spectrum(t, e)[0]
    d = 0.5 * float(numpy.abs(p - s["density"]).sum() * compare.ENERGY_STEP_MEV)
    rv = {
        "energy_mev": e,
        "measured": {"spectrum": s["density"]},
        "twin": {"spectrum": p},
        "numbers": [
            ["spectrum distance (0 same, 1 disjoint)", None, d],
            *[
                [f"{n} [MeV]", a, b]
                for n, a, b in zip(
                    ("peak", "mean", "rms"), _stats(e, s["density"]), _stats(e, p)
                )
            ],
        ],
    }
    if k == "magspec":
        rv["seam_mev"] = dataset["seam_mev"]
        rv["twin"]["image"] = _spectrometer_image(
            t, {**s["machine_state"], **step_state, **tw}, dataset["seam_mev"]
        )
        rv["image_axes"] = SPECTROMETER_BINS
    return rv


def _split(
    folder: pathlib.Path, rows: list, spec: dict, axis_start: float | None
) -> tuple:
    """(numbers, labels): each row's group (0 to N - 1, negative for a row left out) and a
    label per group, for `spec` (see the module's docstring): the shots whose ICT charge is above
    `min_ict_pc`, grouped by rising charge ("ict"), in time order ("time") or by the energy of
    each shot's spectrum's peak ("peak", on the energy axis `axis_start` gives)."""
    q = numpy.array(
        [
            htu_scans.number(r.get("U_BCaveICT Python Results.ChA")) or numpy.nan
            for r in rows
        ]
    )
    beam = numpy.nan_to_num(q, nan=-1.0) > spec.get("min_ict_pc", 0.0)
    n = numpy.full(len(rows), -1)
    idx = numpy.flatnonzero(beam)
    if spec["by"] == "peak":
        p = _shot_peaks(folder, rows, axis_start)
        idx = idx[numpy.isfinite(p[idx])]
        groups = [idx[p[idx] < spec["split_mev"]], idx[p[idx] >= spec["split_mev"]]]
        names = [
            f"peaking below {spec['split_mev']:g} MeV",
            f"peaking at {spec['split_mev']:g} MeV or above",
        ]
    else:
        if spec["by"] == "ict":
            idx = idx[numpy.argsort(q[idx], kind="stable")]
        elif spec["by"] != "time":
            raise ValueError(f"split by {spec['by']!r} not ict, time or peak")
        groups = numpy.array_split(idx, spec["groups"])
        names = [""] * len(groups)
    labels = []
    for i, (c, w) in enumerate(zip(groups, names)):
        n[c] = i
        v = q[c]
        t = [htu_scans.number(rows[k].get("Shotnumber")) for k in c]
        labels.append(
            f"{c.size} shots{' ' + w if w else ''}, ICT {v.min():.0f}-{v.max():.0f} pC "
            + f"(median {numpy.median(v):.0f})"
            + (f", shots {int(min(t))}-{int(max(t))}" if spec["by"] == "time" else "")
        )
    return [int(x) for x in n], labels


def _shot_peaks(
    folder: pathlib.Path, rows: list, axis_start: float | None
) -> numpy.ndarray:
    """Each row's spectrum's peak energy [MeV] (both cameras' `-interpSpec` joined, lightly
    smoothed); NaN for a row without both cameras' frames or without signal."""
    import scipy.ndimage

    c = [
        htu_scans.stack(folder, f"UC_BCaveMagSpec{x}-interpSpec", rows)
        for x in ("Cam1", "Cam2")
    ]
    e = [htu_scans.energy_axis(folder, x, axis_start) for x in ("Cam1", "Cam2")]
    # POSIT: Cam1's axis runs into Cam2's; Cam2 takes over where it starts
    k = e[0] < e[1][0]
    z = [numpy.array(x[1]) for x in c]
    rv = numpy.full(len(rows), numpy.nan)
    ok = (z[0] >= 0) & (z[1] >= 0)
    sp = numpy.clip(
        numpy.concatenate(
            [c[0][0][z[0][ok]][:, k, 1], c[1][0][z[1][ok]][:, :, 1]], axis=1
        ).astype(float),
        0,
        None,
    )
    sp = scipy.ndimage.uniform_filter1d(sp, 9, axis=1)
    f = numpy.concatenate([e[0][k], e[1]])
    rv[ok] = numpy.where(sp.sum(axis=1) > 0, f[sp.argmax(axis=1)], numpy.nan)
    return rv


def _spectrometer_image(transported, machine_state: dict, seam: float) -> numpy.ndarray:
    """The twin's particles binned like `_magspec_images`: energy against AngleAxis, each
    camera's window either side of the cameras' `seam` [MeV]."""
    import htu.model
    from htu_twin_apps.lpa_source import pointing

    (e0, e1, de), (a0, a1, da) = SPECTROMETER_BINS
    f = {**htu.model.DEFAULT_MACHINE_STATE, **machine_state}["magspec_b"]
    k = (transported.charge_pc > 0) & numpy.isfinite(transported.energy_mev)
    a = pointing.screen_angles(transported, k, f)
    e = transported.energy_mev[k]
    w = transported.charge_pc[k]
    c1, c2 = SPECTROMETER_WINDOWS["Cam1"], SPECTROMETER_WINDOWS["Cam2"]
    with numpy.errstate(invalid="ignore"):
        g = numpy.isfinite(a) & (
            ((e < seam) & (a >= c1[0]) & (a <= c1[1]))
            | ((e >= seam) & (a >= c2[0]) & (a <= c2[1]))
        )
    h, _, _ = numpy.histogram2d(
        a[g],
        e[g],
        bins=(numpy.arange(a0, a1 + da / 2, da), numpy.arange(e0, e1 + de / 2, de)),
        weights=w[g],
    )
    return h


def _stats(energy_mev: numpy.ndarray, density: numpy.ndarray) -> tuple:
    w = numpy.clip(density, 0, None)
    if w.sum() <= 0:
        return (None, None, None)
    m = float(numpy.average(energy_mev, weights=w))
    return (
        float(energy_mev[numpy.argmax(w)]),
        m,
        float(numpy.sqrt(numpy.average((energy_mev - m) ** 2, weights=w))),
    )


def _stitched(cameras: dict, scale: bool, align: bool) -> tuple:
    """(image, Cam2's shift [AngleAxis]): `_magspec_images`' cameras side by side, each scaled
    to its spectrum if `scale`, and Cam2 shifted by whole bins to Cam1's centroid at the seam if
    `align` (no shift without charge on both sides)."""
    (_, _, _), (_, _, da) = SPECTROMETER_BINS
    rv = numpy.zeros_like(cameras["Cam1"]["image"])
    s = 0.0
    a, b = cameras["Cam1"]["seam"], cameras["Cam2"]["seam"]
    if align and a is not None and b is not None:
        s = round((a - b) / da) * da
    for c, v in cameras.items():
        h = v["image"] * (v["scale"] if scale else 1.0)
        if c == "Cam2" and s:
            k = int(round(s / da))
            h = numpy.roll(h, k, axis=0)
            if k > 0:
                h[:k] = 0
            else:
                h[k:] = 0
        rv += h
    return rv, s


if __name__ == "__main__":
    main()
