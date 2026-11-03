"""HTU twin viewer: step through a recorded HTU scan and see the twin's prediction beside the data.

Run `htu-twin-viewer [data directory] --source twin-fit-values.json [--port N]` and open http://127.0.0.1:8060. The
data directory is the argument, or `$HTU_DATA` without one. The twin is `geecs-lume-twin` as
`htu_twin_apps.lpa_source` drives it (its PMQ fringe fields, the slit's jaws and blade, the fitted
calibration corrections), with the LPA source and corrections of the best fit.

Each dataset (DATASETS) is a recorded scan with raw data; its steps are the scan's steps. For a
step, the twin is run with the step's logged settings and the fit's corrections, and its output is
returned beside the measurement: the A-line camera's image (Scans 023 and 026, rendered as the
camera would see it, `aline.render`), or the spectrometer's spectrum and its energy against
AngleAxis image. A step is simulated when first asked for and cached, and the rest of its dataset
is simulated in the background.

A step can be run with edits (`/api/step?...&edits={"EMQ1H": 1.2, "source.divergence_x_mrad": 4}`):
values that replace what the twin runs with. The keys are the step's magnet currents
(STEP_KNOBS, the current the twin's magnet sees: the fitted scale is not applied to an edited
one), the fit's corrections (MACHINE_KNOBS) and the source's knobs (SOURCE_KNOBS, prefixed
`source.`). Any other key is refused.

The measured spectrometer image is the two cameras' ImageInterp side by side (Cam1 below
SPECTROMETER_SPLIT_MEV, Cam2 above). Each camera's image is in its own raw counts and its own
AngleAxis zero, so the stitch can be corrected (`scale=1`, `align=1`, both by default): each
camera's image scaled to its `-interpSpec` (the camera's calibrated spectrum), and Cam2 shifted in
AngleAxis so that its centroid within SEAM_WINDOW_MEV of the seam matches Cam1's, per step.

:copyright: Copyright (c) 2026 RadiaSoft LLC.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import http
import http.server
import json
import math
import mimetypes
import numpy
import os
import pathlib
import threading
import urllib.parse

from htu_twin_apps.lpa_source import scans as htu_scans

# TODO(pjm): this should be metadata input
# The recorded scans the viewer offers, by scan folder name: what kind of comparison, and a title.
DATASETS = {
    "Scan016": ("scan016", "Long noscan: chicane, EMQs and slit out (spectrum)"),
    "Scan019": ("spectrum", "R56 scan, slit in (spectrum)"),
    "Scan020": ("spectrum", "Noscan at 140 um R56, slit in (spectrum)"),
    "Scan023": ("aline", "EMQ1 scan onto the A-line camera"),
    "Scan025": ("magspec", "EMQ1 scan on the spectrometer"),
    "Scan026": ("aline", "EMQ2 scan onto the A-line camera"),
    "Scan028": ("magspec", "EMQ2 scan on the spectrometer"),
    "Scan030": ("magspec", "EMQ3 scan on the spectrometer"),
}
DEFAULT_PORT = 8060
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
# The energy [MeV, corrected axis] where the two cameras meet, and their AngleAxis windows.
SPECTROMETER_SPLIT_MEV = 129.3
SPECTROMETER_WINDOWS = {"Cam1": (-23.5, 23.5), "Cam2": (-17.5, 19.75)}
STATIC = pathlib.Path(__file__).resolve().parent / "static"
# The step's logged magnet currents [A] an edit may replace.
STEP_KNOBS = ("EMQ1H", "EMQ2V", "EMQ3H", "S1H", "S3H", "chicane_current")
# The viewer; set by main.
VIEWER = None


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        try:
            if u.path == "/api/datasets":
                return self._json(VIEWER.datasets())
            if u.path == "/api/step":
                q = urllib.parse.parse_qs(u.query)
                return self._json(
                    VIEWER.step(
                        q["scan"][0],
                        int(q["step"][0]),
                        json.loads(q.get("edits", ["{}"])[0]),
                        q.get("scale", ["1"])[0] == "1",
                        q.get("align", ["1"])[0] == "1",
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
    """The data, the twin's source and corrections, and the cache of simulated steps."""

    def __init__(self, data: pathlib.Path, source_path: pathlib.Path, particles: int):
        from htu_twin_apps.lpa_source import aline, source

        self.data = data
        j = json.loads(source_path.read_text())
        self.machine_state = dict(j["machine_state"])
        if aline.PIXEL_KEY not in self.machine_state:
            # a finished A-line fit saves no pixel size; its log has it
            self.machine_state[aline.PIXEL_KEY] = _logged_pixel(source_path)
        self.source = dataclasses.replace(
            source.LPASource(**j["source"]), num_particles=particles
        )
        self.source_label = source_path.name
        self._cache = {}
        self._datasets = {}
        self._edited_particles = (None, None)
        self._lock = threading.Lock()
        # one simulation at a time: requests and the background share the twin's line cache
        self._compute = threading.Lock()
        self._particles = None
        self._wanted = None
        self._worker = None

    def datasets(self) -> dict:
        """The datasets offered, their steps, and the fit the twin runs with."""
        return {
            "source": self.source_label,
            "datasets": [
                {
                    "scan": n,
                    "kind": k,
                    "title": t,
                    "steps": len(self._dataset(n)["steps"]),
                    "scanned": self._dataset(n)["scanned"],
                }
                for n, (k, t) in DATASETS.items()
                if self._exists(n)
            ],
        }

    def step(
        self, scan: str, index: int, edits: dict, scale: bool = True, align: bool = True
    ) -> dict:
        """The twin's output and the measurement at `scan`'s step `index` with `edits` (see the
        module's docstring; computed if need be), the spectrometer image's stitch corrected
        as `scale` and `align` say, and the rest of the dataset started in the background with
        the same edits."""
        d = self._dataset(scan)
        if not 0 <= index < len(d["steps"]):
            raise IndexError(f"{scan} has {len(d['steps'])} steps")
        e = _edits(edits)
        rv = self._step(scan, index, e)
        self._background(scan, e)
        if d["kind"] != "magspec":
            return rv
        i, k = _stitched(d["steps"][index]["cameras"], scale, align)
        # the cached result is shared: a copy with this stitch
        return {
            **rv,
            "measured": {**rv["measured"], "image": i},
            "stitch": {"scale": scale, "align": align, "cam2_shift": k},
        }

    def _background(self, scan: str, edits: tuple) -> None:
        """Simulates `scan`'s steps with `edits`; a worker already running switches to them."""

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
                        self._step(w[0], i, w[1])
                    if _done(w):
                        return
            finally:
                _done(None)

        with self._lock:
            self._wanted = (scan, edits)
            if self._worker is not None:
                return
            self._worker = threading.Thread(target=_run, daemon=True)
        self._worker.start()

    def _dataset(self, scan: str) -> dict:
        with self._lock:
            if scan not in self._datasets:
                self._datasets[scan] = _load(self.data, scan, DATASETS[scan][0])
            return self._datasets[scan]

    def _edited(self, edits: tuple) -> tuple:
        """(source, particles, machine_state, step_state): the fit's with `edits` applied."""
        from htu_twin_apps.lpa_source import source, twin

        e = dict(edits)
        s = dataclasses.replace(
            self.source,
            **{k[7:]: v for k, v in e.items() if k.startswith("source.")},
        )
        if s == self.source:
            p = self._sampled()
        else:
            with self._lock:
                if self._edited_particles[0] != s:
                    self._edited_particles = (s, source.particles(s))
                p = self._edited_particles[1]
        m = {**self.machine_state, **{k: v for k, v in e.items() if k in MACHINE_KNOBS}}
        t = {k: v for k, v in e.items() if k in STEP_KNOBS}
        for k in t:
            if k in twin.SCALES:
                # an edited current is what the twin's magnet sees
                m[twin.SCALES[k]] = 1.0
        return s, p, m, t

    def _exists(self, scan: str) -> bool:
        k = DATASETS[scan][0]
        try:
            if k == "scan016":
                return bool(list(self.data.rglob("analysis/s16.txt")))
            htu_scans.table(self.data, scan)
        except FileNotFoundError:
            return False
        return True

    def _sampled(self):
        from htu_twin_apps.lpa_source import source

        with self._lock:
            if self._particles is None:
                self._particles = source.particles(self.source)
            return self._particles

    def _step(self, scan: str, index: int, edits: tuple) -> dict:
        key = (scan, index, edits)
        with self._lock:
            if key in self._cache:
                return self._cache[key]
        d = self._dataset(scan)
        with self._compute:
            with self._lock:
                if key in self._cache:
                    return self._cache[key]
            s, p, m, t = self._edited(edits)
            rv = _simulate(d, index, p, m, t)
            rv["settings"] = _settings(d, index, s, m, t)
            rv.update(
                scan=scan,
                step=index,
                kind=d["kind"],
                source=self.source_label,
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
        "data", nargs="?", default=os.environ.get("HTU_DATA"), type=pathlib.Path
    )
    p.add_argument("--source", type=pathlib.Path, help="the fit's saved source (JSON)")
    p.add_argument("--particles", type=int, default=PARTICLES)
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--threads", type=int, default=2, help="torch threads (default 2)")
    a = p.parse_args()
    if a.data is None:
        p.error("give the data directory, or set $HTU_DATA")
    s = a.source
    if s is None:
        p.error(f"no source: give --source")
    import torch

    torch.set_num_threads(a.threads)
    global VIEWER
    VIEWER = Viewer(a.data, s, a.particles)
    print(f"HTU twin viewer: http://127.0.0.1:{a.port} (source {s})", flush=True)
    http.server.ThreadingHTTPServer(("0.0.0.0", a.port), Handler).serve_forever()


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


def _fmt(value, digits=2):
    return "n/a" if value is None or not math.isfinite(value) else f"{value:.{digits}f}"


def _load(data: pathlib.Path, scan: str, kind: str) -> dict:
    """A dataset: its steps (each with its logged machine state and measurement), the rows of
    each step for the logged values, and the variable it scans."""
    from htu_twin_apps.lpa_source import aline, compare, slit, twin

    if kind == "scan016":
        f = next(data.rglob("analysis/s16.txt"))
        with open(f, newline="") as x:
            rows = list(csv.DictReader(x, delimiter="\t"))
        m = compare.measured(data, 16)
        s = {**htu_scans.machine_state(rows), **twin.SCAN016_STATE}
        return {
            "kind": kind,
            "rows": [rows],
            "scanned": None,
            "steps": [
                {"machine_state": s, "energy_mev": m.energy_mev, "density": m.density}
            ],
            "measured016": m,
        }
    folder, rows = htu_scans.table(data, scan)
    n = htu_scans.step_numbers(rows)
    u = sorted(set(n))
    by = [[r for r, k in zip(rows, n) if k == i] for i in u]
    if kind == "aline":
        st = aline.measured(data, scan)
        img = _aline_image(folder, rows, u)
        steps = [
            {
                "machine_state": a.machine_state,
                "aline": a,
                "image": i,
                "centroid": a.centroid,
                "size": a.size,
            }
            for a, i in zip(st, img)
        ]
    else:
        st = slit.measured(data, scan)
        steps = [
            {
                "machine_state": s.machine_state,
                "energy_mev": s.energy_mev,
                "density": s.density,
            }
            for s in st
        ]
        if kind == "magspec":
            for s, c in zip(steps, _magspec_images(folder, rows, u)):
                s["cameras"] = c
    return {"kind": kind, "rows": by, "scanned": _scanned(by), "steps": steps}


def _logged_pixel(source_path: pathlib.Path) -> float:
    from htu_twin_apps.lpa_source import aline

    log = source_path.with_name(source_path.name.replace("_source.json", ".log"))
    if not log.exists():
        return aline.DEFAULT_UM_PER_PX
    r = [json.loads(x) for x in open(log)]
    return min(r, key=lambda x: x["value"])["values"].get(
        aline.PIXEL_KEY, aline.DEFAULT_UM_PER_PX
    )


def _magspec_images(folder: pathlib.Path, rows: list, steps: list) -> list:
    """Per step, each camera's mean ImageInterp binned onto SPECTROMETER_BINS (energy on the
    corrected axis), with the scale to its `-interpSpec` and its AngleAxis centroid at the seam
    (`_stitched` puts them together): {camera: {"image", "scale", "seam"}}."""
    (e0, e1, de), (a0, a1, da) = SPECTROMETER_BINS
    eb = numpy.arange(e0, e1 + de / 2, de)
    ab = numpy.arange(a0, a1 + da / 2, da)
    n = htu_scans.step_numbers(rows)
    rv = [{} for _ in steps]
    y = (ab[:-1] + ab[1:]) / 2
    x = (eb[:-1] + eb[1:]) / 2
    for c in SPECTROMETER_WINDOWS:
        i, z = htu_scans.stack(folder, f"UC_BCaveMagSpec{c}-ImageInterp", rows)
        p, g = htu_scans.stack(folder, f"UC_BCaveMagSpec{c}-interpSpec", rows)
        # the seam's columns on this camera's side
        k = (
            (x >= SPECTROMETER_SPLIT_MEV - SEAM_WINDOW_MEV)
            & (x < SPECTROMETER_SPLIT_MEV)
            if c == "Cam1"
            else (x >= SPECTROMETER_SPLIT_MEV)
            & (x < SPECTROMETER_SPLIT_MEV + SEAM_WINDOW_MEV)
        )
        d, _ = htu_scans.stack(folder, f"UC_BCaveMagSpec{c}-interpDiv", [])
        e = htu_scans.energy_axis(folder, c)
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
    dataset: dict, index: int, source, machine_state: dict, step_state: dict
) -> list:
    """The synoptic's elements, in beam order: what was logged at the step, what the twin ran
    with, the fitted correction between, and the knobs an edit may set (key, label, value the
    twin ran with, unit)."""
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
    slit_in = dataset["kind"] != "scan016"
    return [
        {
            "id": "source",
            "label": "LPA source",
            "logged": f"ICT {_fmt(_logged('U_BCaveICT Python Results.ChA'))} pC",
            "twin": f"divergence {source.divergence_x_mrad:.1f} / {source.divergence_y_mrad:.1f} mrad, "
            + f"pointing {source.pointing_x_mrad:.1f} / {source.pointing_y_mrad:.1f} mrad",
            "note": "fitted",
            "knobs": [
                [f"source.{k}", l, getattr(source, k), u]
                for k, (l, u) in SOURCE_KNOBS.items()
            ],
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
            "note": "fitted",
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
            "twin": "off (A-line)" if aline_kind else "on; energies on Scan020's axis",
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
        rv["seam_mev"] = SPECTROMETER_SPLIT_MEV
        rv["twin"]["image"] = _spectrometer_image(
            t, {**s["machine_state"], **step_state, **tw}
        )
        rv["image_axes"] = SPECTROMETER_BINS
    return rv


def _spectrometer_image(transported, machine_state: dict) -> numpy.ndarray:
    """The twin's particles binned like `_magspec_images`: energy against AngleAxis, each
    camera's window."""
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
            ((e < SPECTROMETER_SPLIT_MEV) & (a >= c1[0]) & (a <= c1[1]))
            | ((e >= SPECTROMETER_SPLIT_MEV) & (a >= c2[0]) & (a <= c2[1]))
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
