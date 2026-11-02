"""Fit the beam's horizontal and vertical path with the A-line camera's EMQ scans and Scan019.

In Scans 023 and 026 (2026-09-29) EMQ1 and then EMQ2 are stepped while `UC_ALineEBeam3`, about
1.7 m past the spectrometer magnet (off), images the beam in x and y: quadrupole scans. Each
step's spot gives a centroid and an rms size per plane. The centroid moves with the EMQ current
in proportion to the beam's offset in that EMQ, so the scans measure where the beam passes
through the EMQs; the sizes, the beam's divergence and focusing.

Each step is predicted by tracking the source through the twin with the step's logged settings
(`twin.to_spectrometer`, slit as `slit`), drifting the particles to the camera (DRIFT_TO, the
twin's line from `twin.END_ELEMENT`, magnet off), and reweighting them in energy to the spectrum
measured at the same step of the spectrometer scan run alongside (PAIRS: Scans 025 and 028 step
the same EMQ currents with the spectrometer on). The particles are then rendered as the camera
would see them and measured the same way as its frames: binned into an image at the camera's
pixel size (PIXEL_KEY, a fit knob: the twin's geometry for the camera is a placeholder) and
orientation (SIGNS), blurred by BLUR_PX, thresholded at THRESHOLD of its peak, and its moments
taken. Measuring the model and the frames alike matters: in Scan023 each shot is a cross of two
components, focused in different planes by energy, and the threshold cuts the fainter arm. Per
evaluation the score fits a zero per axis and a resolution floor (`score`).

`fit` joins this with Scan019's spectra (`slit.distances`), each step's distance counting as one
number with an error of SLIT_SIGMA, so the horizontal path is fitted against both. The steps are
tracked in parallel worker processes.

:copyright: Copyright (c) 2026 RadiaSoft LLC.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""

from __future__ import annotations

import dataclasses
import functools
import numpy
import pathlib

from htu_twin_apps.lpa_source import scans as htu_scans

# The scans' background frames.
BACKGROUND = "Scan022"
# The Gaussian blur [pixels] the rendered model image is given: the camera's resolution, and
# smoothing of the particles' sampling noise before the threshold.
BLUR_PX = 2.0
CAMERA = "UC_ALineEBeam3"
# The camera's pixel size [um] when PIXEL_KEY is not in the machine state (the A-line fits of
# 2026-11-02, which fitted it with the orientation free: 216 to 230 um).
DEFAULT_UM_PER_PX = 220.0
# The element the camera is, in the twin's line.
DRIFT_TO = "UC_ALineEBeam3"
# The smallest error [pixels] given a step's median centroid or size.
ERROR_FLOOR_PX = 1.0
# The knobs fitted by default: the beam's horizontal path and divergence, its vertical pointing,
# S1H's strength, the PMQ triplet's x, the slit's edges, and EMQ1 and EMQ2's strength.
FIT_NAMES = (
    "pointing_x_mrad",
    "pointing_slope_x_mrad",
    "divergence_x_mrad",
    "pointing_y_mrad",
    "s1h_scale",
    "pmq_x_mm",
    "chicane_jaw1_mm",
    "slit_blade_low_mm",
    "slit_blade_high_mm",
    "emq1_scale",
    "emq2_scale",
    "aline_um_per_px",
)
# The A-line scans, and the spectrometer scan run alongside each with the same EMQ steps.
PAIRS = {"Scan023": "Scan025", "Scan026": "Scan028"}
# The machine-state key of the camera's pixel size [um], a fit knob (not a twin key).
PIXEL_KEY = "aline_um_per_px"
# The region of the camera's frames [rows, columns] the spot is measured in: the beam stays in
# it, the stray light at the frames' edges and corners does not.
ROI = (slice(150, 650), slice(250, 750))
# The image's (column, row) direction for the twin's (+x, +y): the A-line fits of 2026-11-02,
# with the orientation free, all found the axes not swapped and both reversed.
SIGNS = (-1, -1)
# Scan019's step distances counted as numbers with this error.
SLIT_SIGMA = 0.02
# Pixels below this fraction of a frame's 99.95th percentile are left out of its moments.
THRESHOLD = 0.1


@dataclasses.dataclass
class AlineFit:
    """The fit's result: the objective's parts at the best point (`slit_chi2`, `aline_chi2`,
    `camera`, the fitted camera parameters) and the fitted source and machine state."""

    evaluations: int
    machine_state: dict
    names: tuple
    objective: float
    parts: dict
    source: object
    start_objective: float
    values: dict


@dataclasses.dataclass
class AlineStep:
    """One step: the spot's median centroid and rms size [pixels, (column, row)], their errors,
    the partner scan's spectrum at the step (normalized, on `energy_mev`), and the twin machine
    state."""

    centroid: numpy.ndarray
    centroid_error: numpy.ndarray
    density: numpy.ndarray
    energy_mev: numpy.ndarray
    machine_state: dict
    size: numpy.ndarray
    size_error: numpy.ndarray


def fit(
    slit_steps: list,
    aline_steps: dict,
    source,
    machine_state: dict,
    names=FIT_NAMES,
    slit: str = "jaws_blade",
    bounds: dict | None = None,
    max_evaluations: int = 400,
    restarts: int = 2,
    num_particles: int = 30_000,
    workers: int = 5,
    threads: int = 3,
    log=None,
) -> AlineFit:
    """Fit `names` to Scan019 (`slit.measured`) and the A-line scans (`measured`, by name).

    Args:
        slit_steps: Scan019's steps.
        aline_steps: the A-line scans' steps, by scan name.
        source: the `LPASource` to start from.
        machine_state: twin machine-state keys (and `twin.SCALES`', `twin.OFFSETS`',
            `twin.BLADE_KEYS`' and PIXEL_KEY) set over every step's; the fitted ones start from
            their values here. The result's has no PIXEL_KEY (its `values` do).
        names: the knobs to fit.
        slit: the slit's shape.
        bounds, max_evaluations, restarts, log: as for `fit.minimize`.
        num_particles: particles per evaluation.
        workers: worker processes tracking the steps.
        threads: torch threads per worker.
    """
    from htu_twin_apps.lpa_source import fit as lpa_fit

    s = dataclasses.replace(source, num_particles=num_particles)
    with lpa_fit.pool(workers, threads) as p:

        def _objective(v):
            return _evaluate(p, slit_steps, aline_steps, *lpa_fit.apply(s, machine_state, names, v), slit)[0]

        x0 = lpa_fit.knobs(s, machine_state, names)
        x, d, n = lpa_fit.minimize(
            _objective,
            x0,
            names,
            bounds=bounds,
            max_evaluations=max_evaluations,
            restarts=restarts,
            gain=1.0,
            log=log,
        )
        f = lpa_fit.apply(s, machine_state, names, x)
        _, parts = _evaluate(p, slit_steps, aline_steps, *f, slit)
        o = _objective(x0)
    return AlineFit(
        evaluations=n,
        machine_state={k: v for k, v in f[1].items() if k != PIXEL_KEY},
        names=tuple(names),
        objective=d,
        parts=parts,
        source=dataclasses.replace(f[0], num_particles=source.num_particles),
        start_objective=o,
        values=dict(zip(names, map(float, x))),
    )


def measured(data: pathlib.Path, scan: str) -> list:
    """The steps of A-line scan `scan` below `data`, with its partner's (PAIRS) spectra."""
    from htu_twin_apps.lpa_source import slit

    f, rows = htu_scans.table(data, scan)
    b, _ = htu_scans.stack(htu_scans.table(data, BACKGROUND)[0], CAMERA, [])
    b = numpy.median(b[:, ROI[0], ROI[1]].astype(numpy.float32), axis=0)
    a, z = htu_scans.stack(f, CAMERA, rows)
    n = htu_scans.step_numbers(rows)
    p = slit.measured(data, PAIRS[scan])
    u = sorted(set(n))
    if len(u) != len(p):
        raise ValueError(f"{scan} has {len(u)} steps, {PAIRS[scan]} {len(p)}")
    rv = []
    for i, q in zip(u, p):
        j = [r for r, m in enumerate(n) if m == i and z[r] >= 0]
        if not j:
            raise ValueError(f"{scan} step {i}: no frame")
        m = numpy.array([_moments(a[z[r], ROI[0], ROI[1]].astype(numpy.float32) - b) for r in j])
        e = numpy.maximum(1.2533 * m.std(axis=0) / numpy.sqrt(len(j)), ERROR_FLOOR_PX)
        c = numpy.median(m, axis=0)
        s = htu_scans.machine_state([rows[r] for r in j])
        # POSIT: slit.measured's steps are the partner scan's in step order, at the same currents
        rv.append(
            AlineStep(
                centroid=c[:2],
                centroid_error=e[:2],
                density=q.density,
                energy_mev=q.energy_mev,
                machine_state=s,
                size=c[2:],
                size_error=e[2:],
            )
        )
    return rv


def predict(particles, steps: list, machine_state: dict, slit: str) -> numpy.ndarray:
    """Per step, the rendered spot's (centroid column, centroid row, rms column, rms row)
    [pixels] (see the module's docstring), its origin arbitrary; NaN for a step with nothing in
    its spectrum's range."""
    return numpy.array([_predict_step(particles, s, machine_state, slit) for s in steps])


def score(aline_steps: dict, predictions: dict) -> tuple:
    """(chi^2, camera) of `predictions` (`predict`'s, by scan) against `aline_steps`, a zero per
    image axis and a resolution floor fitted (`camera`: `zero_px`, `floor_px`)."""
    import scipy.optimize

    m = numpy.concatenate(
        [[numpy.r_[s.centroid, s.size] for s in aline_steps[k]] for k in aline_steps]
    )
    e = numpy.concatenate(
        [[numpy.r_[s.centroid_error, s.size_error] for s in aline_steps[k]] for k in aline_steps]
    )
    p = numpy.concatenate([predictions[k] for k in aline_steps])
    if not numpy.isfinite(p).all():
        return 1e9, None

    def _residuals(v):
        # v: column zero, row zero, resolution floor [pixels]
        return numpy.concatenate(
            [
                ((p[:, :2] + v[:2] - m[:, :2]) / e[:, :2]).ravel(),
                ((numpy.sqrt(p[:, 2:] ** 2 + v[2] ** 2) - m[:, 2:]) / e[:, 2:]).ravel(),
            ]
        )

    f = scipy.optimize.least_squares(
        _residuals,
        numpy.r_[(m[:, :2] - p[:, :2]).mean(axis=0), 1.0],
        bounds=([-numpy.inf, -numpy.inf, 0.0], [numpy.inf, numpy.inf, 1e3]),
    )
    return float((f.fun**2).sum()), {
        "floor_px": float(f.x[2]),
        "zero_px": tuple(map(float, f.x[:2])),
    }


@functools.cache
def _drift_m() -> float:
    """The twin's line length [m] from `twin.END_ELEMENT` to DRIFT_TO (field-free with the
    spectrometer off and S4 at 0)."""
    import htu.lattice
    from htu_twin_apps.lpa_source import twin

    s = htu.lattice.build_htu_segment(active_screens=(), to_element=DRIFT_TO)
    n = [x.name for x in s.elements]
    return float(sum(float(getattr(x, "length", 0.0)) for x in s.elements[n.index(twin.END_ELEMENT) + 1 :]))


def _evaluate(pool, slit_steps, aline_steps, source, machine_state, slit) -> tuple:
    """(objective, parts): Scan019's (distance / SLIT_SIGMA)^2 plus the A-line chi^2."""
    j = [pool.submit(_slit_distance, source, s, machine_state, slit) for s in slit_steps]
    k = {
        n: [pool.submit(_predict_one, source, s, machine_state, slit) for s in v]
        for n, v in aline_steps.items()
    }
    d = numpy.array([x.result() for x in j])
    p = {n: numpy.array([x.result() for x in v]) for n, v in k.items()}
    c, cam = score(aline_steps, p)
    t = float(((d / SLIT_SIGMA) ** 2).sum())
    return t + c, {
        "aline_chi2": c,
        "aline_numbers": 4 * sum(len(v) for v in aline_steps.values()),
        "camera": cam,
        "slit_chi2": t,
        "slit_distances": d.tolist(),
        "slit_mean_distance": float(d.mean()),
    }


def _moments(frame: numpy.ndarray) -> numpy.ndarray:
    """(centroid column, centroid row, rms column, rms row) [pixels, frame coordinates] of a
    background-subtracted ROI frame, its border's median taken as its pedestal."""
    return _spot(
        frame
        - numpy.median(
            numpy.concatenate(
                [frame[:20].ravel(), frame[-20:].ravel(), frame[:, :20].ravel(), frame[:, -20:].ravel()]
            )
        ),
        ROI[0].start,
        ROI[1].start,
    )


def _predict_one(source, step, machine_state, slit):
    from htu_twin_apps.lpa_source import fit

    return _predict_step(fit.sampled(source), step, machine_state, slit)


def _predict_step(particles, step: AlineStep, machine_state: dict, slit: str) -> numpy.ndarray:
    import scipy.ndimage
    from htu_twin_apps.lpa_source import fit, twin

    um = machine_state.get(PIXEL_KEY, DEFAULT_UM_PER_PX)
    t = twin.to_spectrometer(
        particles,
        {**step.machine_state, **{k: v for k, v in machine_state.items() if k != PIXEL_KEY}},
        reference_mev=fit.REFERENCE_MEV,
        slit=slit,
    )
    x = t.x_mm + _drift_m() * t.xp_mrad
    y = t.y_mm + _drift_m() * t.yp_mrad
    k = numpy.isfinite(t.energy_mev) & numpy.isfinite(x) & numpy.isfinite(y) & (t.charge_pc > 0)
    e = step.energy_mev
    h = e[1] - e[0]
    b = numpy.floor((numpy.where(k, t.energy_mev, -1e9) - (e[0] - h / 2)) / h).astype(int)
    k &= (b >= 0) & (b < e.size)
    if not k.any():
        return numpy.full(4, numpy.nan)
    q = numpy.zeros(e.size)
    numpy.add.at(q, b[k], t.charge_pc[k])
    w = numpy.zeros_like(t.charge_pc)
    w[k] = t.charge_pc[k] * step.density[b[k]] / q[b[k]]
    if w.sum() <= 0:
        return numpy.full(4, numpy.nan)
    u = SIGNS[0] * x[k] * 1e3 / um
    v = SIGNS[1] * y[k] * 1e3 / um
    # the ROI's size, centred on the spot, as the frames' ROI holds the measured spot
    r = numpy.array([ROI[0].stop - ROI[0].start, ROI[1].stop - ROI[1].start])
    o = numpy.round([numpy.average(v, weights=w[k]), numpy.average(u, weights=w[k])]) - r // 2
    d, _, _ = numpy.histogram2d(
        v, u, bins=r, range=[[o[0], o[0] + r[0]], [o[1], o[1] + r[1]]], weights=w[k]
    )
    return _spot(scipy.ndimage.gaussian_filter(d, BLUR_PX), o[0], o[1])


def _slit_distance(source, step, machine_state, slit) -> float:
    from htu_twin_apps.lpa_source import fit, slit as lpa_slit

    return float(
        lpa_slit.distances(
            [step],
            fit.sampled(source),
            {k: v for k, v in machine_state.items() if k != PIXEL_KEY},
            slit,
        )[0]
    )


def _spot(image: numpy.ndarray, row0: float, column0: float) -> numpy.ndarray:
    """(centroid column, centroid row, rms column, rms row) [pixels] of `image`, whose first
    pixel is at (`row0`, `column0`), counting only pixels above THRESHOLD of its 99.95th
    percentile."""
    d = numpy.where(image > THRESHOLD * numpy.percentile(image, 99.95), image, 0.0)
    y, x = numpy.mgrid[: d.shape[0], : d.shape[1]]
    y = y + row0
    x = x + column0
    w = d.sum()
    cx, cy = (d * x).sum() / w, (d * y).sum() / w
    return numpy.array(
        [cx, cy, numpy.sqrt((d * (x - cx) ** 2).sum() / w), numpy.sqrt((d * (y - cy) ** 2).sum() / w)]
    )
