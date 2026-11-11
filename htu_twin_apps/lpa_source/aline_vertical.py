"""Fit the A-line scans and the spectrometer EMQ scans' vertical profiles together.

The A-line fit (`aline`) and the spectrometer's vertical profiles (`pointing`) disagree on the
EMQs' vertical offsets: the A-line spots want 0.6 to 0.9 mm, with which the twin's beam swings
across the spectrometer's AngleAxis where the measured beam stays put. Fitted together, with one
set of knobs for both, they either find one machine that satisfies both or show that the twin
cannot.

The objective is `aline`'s (the A-line chi^2 with the camera's zeros and floor fitted, plus
Scan019's slit term) plus `pointing`'s vertical chi^2 over `pointing.SCANS` through the twin's
spectrometer model (the slit out, each step reweighted to its spectrum). Each spectrometer
camera's scale, zero and resolution floor are fitted (`pointing.score`, SCALE "free"), or the
scale is held at a number (the twin's AngleAxis taken as the driver's when 1) and the zero and
floor fitted. Each step is tracked in a worker of one pool.

Run as `python -m htu_twin_apps.lpa_source.aline_vertical <day> [--root DIR] --source <saved source>
...` (a day name such as `26_0929`, or a day folder's path).

:copyright: Copyright (c) 2026 RadiaSoft LLC.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import time

import numpy

from htu_twin_apps import days
from htu_twin_apps.lpa_source import scans as htu_scans

# The knobs fitted by default: the A-line fit's and the triplet's vertical offset.
FIT_NAMES = (
    "aline_um_per_px",
    "emq1_x_mm",
    "emq1_y_mm",
    "emq2_x_mm",
    "emq2_y_mm",
    "pointing_x_mrad",
    "pointing_slope_x_mrad",
    "divergence_x_mrad",
    "pointing_y_mrad",
    "divergence_y_mrad",
    "s1h_scale",
    "pmq_x_mm",
    "pmq_y_mm",
    "emq1_scale",
    "emq2_scale",
    "chicane_jaw1_mm",
)
# "free": each spectrometer camera's scale fitted; a number: the scale held there.
SCALE = "free"


def evaluate(pool, data: dict, source, machine_state: dict, scale) -> tuple:
    """(objective, parts) of `source` and `machine_state` on `data` (`measured`'s)."""
    from htu_twin_apps.lpa_source import aline, pointing

    v = {
        n: [pool.submit(_vertical_step, source, n, s, machine_state) for s in t]
        for n, t in data["vertical"].items()
    }
    a, p = aline._evaluate(
        pool, data["slit"], data["aline"], source, machine_state, "jaws_blade"
    )
    v = {n: [x.result() for x in t] for n, t in v.items()}
    if scale == "free":
        c, _, cams = pointing.score(data["vertical"], v)
    else:
        cams = {
            x: _fixed_scale(data["vertical"], v, x, float(scale))
            for x in pointing.CAMERAS
        }
        c = sum(x[0] for x in cams.values())
    return a + c, {**p, "aline_objective": a, "vertical_chi2": c, "cameras": cams}


def fit(
    data: dict,
    source,
    machine_state: dict,
    names=FIT_NAMES,
    scale=SCALE,
    max_evaluations: int = 400,
    restarts: int = 2,
    num_particles: int = 30_000,
    workers: int = 3,
    threads: int = 2,
    log=None,
) -> tuple:
    """(source, machine state, objective, parts, evaluations) of the fit of `names`."""
    from htu_twin_apps.lpa_source import fit as lpa_fit

    s = dataclasses.replace(source, num_particles=num_particles)
    with lpa_fit.pool(workers, threads) as p:

        def _objective(v):
            return evaluate(p, data, *lpa_fit.apply(s, machine_state, names, v), scale)[
                0
            ]

        x, d, n = lpa_fit.minimize(
            _objective,
            lpa_fit.knobs(s, machine_state, names),
            names,
            max_evaluations=max_evaluations,
            restarts=restarts,
            gain=1.0,
            log=log,
        )
        f = lpa_fit.apply(s, machine_state, names, x)
        _, parts = evaluate(p, data, *f, scale)
    return (
        dataclasses.replace(f[0], num_particles=source.num_particles),
        f[1],
        d,
        parts,
        n,
    )


def main():
    from htu_twin_apps.lpa_source import slit, source as lpa_source

    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument(
        "data",
        help="the day to read: a name such as 26_0929 (with --root) or a day folder's path",
    )
    p.add_argument(
        "--root",
        type=pathlib.Path,
        help="the data root, the folder holding Y2026",
    )
    p.add_argument(
        "--source", type=pathlib.Path, required=True, help="a saved source (JSON)"
    )
    p.add_argument("--knobs", help="comma-separated (default: FIT_NAMES)")
    p.add_argument("--scale", default=SCALE, help='"free" or a fixed camera scale')
    p.add_argument("--energy-reference", choices=("early", "late"), default="early")
    p.add_argument("--max-evaluations", type=int, default=400)
    p.add_argument("--restarts", type=int, default=2)
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--threads", type=int, default=2)
    p.add_argument("--log", type=pathlib.Path)
    p.add_argument("--save", type=pathlib.Path)
    a = p.parse_args()
    try:
        a.data = days.folder(a.data, a.root)
    except (FileNotFoundError, ValueError) as e:
        p.error(str(e))
    if a.scale != "free":
        float(a.scale)
    j = json.loads(a.source.read_text())
    f = fit(
        measured(
            a.data,
            (
                None
                if a.energy_reference == "early"
                else htu_scans.LATE_CAM1_AXIS_START_MEV
            ),
        ),
        lpa_source.LPASource(**j["source"]),
        {**slit.SLIT_STARTS["jaws_blade"], **j["machine_state"]},
        names=a.knobs.split(",") if a.knobs else FIT_NAMES,
        scale=a.scale,
        max_evaluations=a.max_evaluations,
        restarts=a.restarts,
        workers=a.workers,
        threads=a.threads,
        log=_logger(a.log),
    )
    s, m, d, parts, n = f
    print(
        f"A-line and vertical fit ({n} evaluations): objective {d:.1f} = A-line and Scan019 "
        + f"{parts['aline_objective']:.1f} + vertical {parts['vertical_chi2']:.1f}; cameras "
        + json.dumps(parts["cameras"]),
        flush=True,
    )
    if a.save:
        a.save.write_text(
            json.dumps({"source": dataclasses.asdict(s), "machine_state": m}, indent=1)
        )
        print(f"saved: {a.save}", flush=True)


def measured(data: pathlib.Path, axis_start_mev: float | None = None) -> dict:
    """The fit's data: Scan019's steps, the A-line scans' and the spectrometer EMQ scans'."""
    from htu_twin_apps.lpa_source import aline, pointing, slit

    return {
        "aline": {x: aline.measured(data, x, axis_start_mev) for x in aline.PAIRS},
        "slit": slit.measured(data, axis_start_mev=axis_start_mev),
        "vertical": {
            x: pointing.measured(data, x, axis_start_mev) for x in pointing.SCANS
        },
    }


def _fixed_scale(scans: dict, predictions: dict, camera: str, scale: float) -> tuple:
    """(chi^2, scale, b, r0) of `camera` with its scale held at `scale` and its zero `b` and
    floor `r0` fitted, as `pointing._camera_fits` with the scale fixed."""
    import scipy.optimize

    from htu_twin_apps.lpa_source import pointing

    m = [s.cameras[camera] for n in scans for s in scans[n]]
    p = numpy.array([v[camera]["spectrometer"] for n in scans for v in predictions[n]])
    if not numpy.all(numpy.isfinite(p)):
        return (numpy.inf, scale, numpy.nan, numpy.nan)
    c, r = (numpy.array([getattr(x, k) for x in m]) for k in ("centroid", "rms"))
    ec, er = (
        numpy.maximum([getattr(x, k) for x in m], pointing.ERROR_FLOOR)
        for k in ("centroid_error", "rms_error")
    )

    def _residuals(v):
        return numpy.concatenate(
            [
                (c - scale * p[:, 0] - v[0]) / ec,
                (r - numpy.hypot(scale * p[:, 1], v[1])) / er,
            ]
        )

    f = scipy.optimize.least_squares(
        _residuals, [0.0, 2.0], bounds=([-numpy.inf, 0.0], [numpy.inf, numpy.inf])
    )
    return (float((f.fun**2).sum()), scale, *map(float, f.x))


def _logger(path: pathlib.Path | None):
    """The fit's `log` callback: every evaluation appended to `path` as JSON, as `compare`'s."""

    def _log(n, value, values):
        if path:
            with open(path, "a") as f:
                f.write(
                    json.dumps(
                        {
                            "fit": "aline_vertical",
                            "n": n,
                            "value": value,
                            "values": values,
                            "time": time.time(),
                        }
                    )
                    + "\n"
                )
        if n % 10 == 0:
            print(f"  aline_vertical evaluation {n}: {value:.0f}", flush=True)

    return _log


def _vertical_step(source, scan: str, step, machine_state: dict) -> dict:
    """`pointing.predict` of one step (in a worker, the source sampled once per process)."""
    from htu_twin_apps.lpa_source import aline, fit, pointing

    return pointing.predict(
        fit.sampled(source),
        {scan: [step]},
        {k: v for k, v in machine_state.items() if k != aline.PIXEL_KEY},
    )[scan][0]


if __name__ == "__main__":
    main()
