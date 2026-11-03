"""Fit the vertical optics with the spectrometer's energy-resolved vertical profiles.

Each spectrometer camera saves, per shot, an image interpolated onto its energy axis and its
AngleAxis (`UC_BCaveMagSpec<cam>-ImageInterp`): columns are `-interpSpec`'s energies, rows
`-interpDiv`'s AngleAxis values in reverse order (the rows summed reproduce `-interpDiv`
exactly, reversed). The pointing fit (`pointing`) uses the profile summed over energy; this
module cuts each step's image into BIN_MEV energy slices and takes each slice's vertical
centroid and rms. In the EMQ scans (Scans 025, 028, 030) that resolves the beam's chromatic
focusing energy by energy: which energy each EMQ setting focuses, and how much the size grows
away from it, which constrains the EMQs' strength and the source's vertical divergence and its
energy dependence far more than the summed profile.

Each step is predicted as in `pointing` ("spectrometer" projection): the source tracked through
the twin with the step's settings, the slit out, each particle's AngleAxis from the twin's
spectrometer map (`pointing.screen_angles`), only what lands in the camera's AngleAxis range
counted, and the moments taken per energy slice. Per camera a scale, a zero and a resolution
floor relate prediction to measurement, the cameras' scales of one sign (`score`). The steps
are tracked in parallel worker processes.

:copyright: Copyright (c) 2026 RadiaSoft LLC.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""

from __future__ import annotations

import dataclasses
import numpy
import pathlib

from htu_twin_apps.lpa_source import scans as htu_scans

# The energy slices' width [MeV].
BIN_MEV = 5.0
CAMERAS = ("Cam1", "Cam2")
# The smallest error [AngleAxis units] given a slice's centroid or rms.
ERROR_FLOOR = 0.05
# The knobs fitted by default: the source's vertical beam, the PMQ triplet's y, the EMQs'
# strengths and vertical offsets, and the spectrometer's field.
FIT_NAMES = (
    "pointing_y_mrad",
    "pmq_y_mm",
    "divergence_y_mrad",
    "divergence_power",
    "emq1_scale",
    "emq2_scale",
    "emq3_scale",
    "emq1_y_mm",
    "emq2_y_mm",
    "magspec_b",
)
# A slice counts only if it holds at least this fraction of its camera's signal at the step.
MIN_FRACTION = 0.02
# Spectrometer scans that step one EMQ, by scan folder name.
SCANS = ("Scan025", "Scan028", "Scan030")
# With Scan016's spectrum in the fit, its distance counts as one number of this error (about twice
# its sampling noise, as in `joint`).
SPECTRUM_SIGMA = 0.01


@dataclasses.dataclass
class EnergyProfiles:
    """One camera at one step: per energy slice (`energy_mev`, the slices' edges), the vertical
    centroid and rms [AngleAxis units] and their errors, NaN for a slice that does not count;
    `angle_range` is the camera's AngleAxis range."""

    angle_range: tuple
    centroid: numpy.ndarray
    centroid_error: numpy.ndarray
    energy_mev: numpy.ndarray
    rms: numpy.ndarray
    rms_error: numpy.ndarray


@dataclasses.dataclass
class EnergyProfilesFit:
    """The fit's result: chi^2 and how many numbers it is over, each camera's (chi^2, a, b, r0),
    and the fitted source and machine state."""

    cameras: dict
    chi2: float
    evaluations: int
    machine_state: dict
    measured_numbers: int
    names: tuple
    source: object
    start_chi2: float
    values: dict


@dataclasses.dataclass
class Step:
    """One step of a scan: each camera's energy-resolved profiles and the twin machine state."""

    cameras: dict
    machine_state: dict


def fit(
    scans: dict,
    source,
    machine_state: dict,
    names=FIT_NAMES,
    bounds: dict | None = None,
    max_evaluations: int = 400,
    restarts: int = 2,
    num_particles: int = 30_000,
    workers: int = 5,
    threads: int = 2,
    spectrum=None,
    log=None,
) -> EnergyProfilesFit:
    """Fit `names` to `scans` (by name, as `measured()` gives each), and to Scan016's spectrum
    if `spectrum` is given: then the objective is the profiles' chi^2 per measured number plus
    `(distance / SPECTRUM_SIGMA) ** 2`, so the two count alike whatever the profiles' excess.

    Args:
        scans: each scan's steps.
        source: the `LPASource` to start from.
        machine_state: twin machine-state keys (and `twin.SCALES`' and `twin.OFFSETS`') set
            over every step's; the fitted ones start from their values here.
        names: the knobs to fit.
        bounds, max_evaluations, restarts, log: as for `fit.minimize`.
        num_particles: particles per evaluation.
        workers: worker processes tracking the steps.
        threads: torch threads per worker.
        spectrum: Scan016's measured spectrum (`compare.measured`), or None.
    """
    from htu_twin_apps.lpa_source import fit as lpa_fit

    s = dataclasses.replace(source, num_particles=num_particles)
    n0 = _numbers(scans)
    with lpa_fit.pool(workers, threads) as p:

        def _chi2(v):
            f = lpa_fit.apply(s, machine_state, names, v)
            d = p.submit(_spectrum_distance, f[0], f[1], spectrum) if spectrum else None
            c, k = score(scans, _predict_parallel(p, scans, *f))
            if d is None:
                return c, k
            d = d.result()
            return c / n0 + (d / SPECTRUM_SIGMA) ** 2, {
                **k,
                "chi2": c,
                "spectrum_distance": d,
            }

        x0 = lpa_fit.knobs(s, machine_state, names)
        x, c, n = lpa_fit.minimize(
            lambda v: _chi2(v)[0],
            x0,
            names,
            bounds=bounds,
            max_evaluations=max_evaluations,
            restarts=restarts,
            gain=1.0,
            log=log,
        )
        f = lpa_fit.apply(s, machine_state, names, x)
        _, k = _chi2(x)
        c0 = _chi2(x0)[0]
    return EnergyProfilesFit(
        cameras=k,
        chi2=c,
        evaluations=n,
        machine_state=f[1],
        measured_numbers=_numbers(scans),
        names=tuple(names),
        source=dataclasses.replace(f[0], num_particles=source.num_particles),
        start_chi2=c0,
        values=dict(zip(names, map(float, x))),
    )


def measured(
    data: pathlib.Path, scan: str, axis_start_mev: float | None = None
) -> list:
    """The steps of `scan` (a scan folder name, such as `Scan025`) found below `data`."""
    f, rows = htu_scans.table(data, scan)
    n = htu_scans.step_numbers(rows)
    k = sorted(set(n))
    c = {x: _camera(f, rows, x, n, k, axis_start_mev) for x in CAMERAS}
    return [
        Step(
            cameras={x: c[x][j] for x in CAMERAS},
            machine_state=htu_scans.machine_state(
                [r for r, m in zip(rows, n) if m == i]
            ),
        )
        for j, i in enumerate(k)
    ]


def predict(particles, steps: list, machine_state: dict) -> list:
    """Per step, per camera: (centroids, rms) [mrad of the twin's AngleAxis] per energy slice."""
    return [_predict_step(particles, s, machine_state) for s in steps]


def score(scans: dict, predictions: dict) -> tuple:
    """(chi^2, {camera: (chi^2, a, b, r0)}) of `predictions` (`predict`'s, by scan) against
    `scans`: per camera a scale `a`, zero `b` and floor `r0` fitted (`centroid = a C + b`,
    `rms^2 = a^2 R^2 + r0^2`), the cameras' scales of one sign. A slice the model has nothing in
    costs as much as its measured numbers' (centroid, rms) misfit at a scale of zero."""
    import scipy.optimize

    def _arrays(camera):
        m, p = [], []
        for n in scans:
            for s, v in zip(scans[n], predictions[n]):
                q = s.cameras[camera]
                k = numpy.isfinite(q.centroid)
                m.append(
                    numpy.stack(
                        [q.centroid[k], q.rms[k], q.centroid_error[k], q.rms_error[k]],
                        axis=1,
                    )
                )
                p.append(numpy.stack([v[camera][0][k], v[camera][1][k]], axis=1))
        return numpy.concatenate(m), numpy.concatenate(p)

    rv = {}
    for c in CAMERAS:
        m, p = _arrays(c)
        e = numpy.maximum(m[:, 2:], ERROR_FLOOR)
        # a slice the model leaves empty: predicted at the beam's centre with no size
        p = numpy.where(numpy.isfinite(p), p, 0.0)
        rv[c] = {}
        for g in (1, -1):

            def _residuals(v):
                return numpy.concatenate(
                    [
                        (m[:, 0] - v[0] * p[:, 0] - v[1]) / e[:, 0],
                        (m[:, 1] - numpy.hypot(v[0] * p[:, 1], v[2])) / e[:, 1],
                    ]
                )

            f = scipy.optimize.least_squares(
                _residuals,
                [0.5 * g, float(numpy.median(m[:, 0])), 2.0],
                bounds=(
                    [1e-6 if g > 0 else -numpy.inf, -numpy.inf, 0.0],
                    [numpy.inf if g > 0 else -1e-6, numpy.inf, numpy.inf],
                ),
            )
            rv[c][g] = (float((f.fun**2).sum()), *map(float, f.x))
    g = min((1, -1), key=lambda x: sum(rv[c][x][0] for c in CAMERAS))
    return sum(rv[c][g][0] for c in CAMERAS), {c: rv[c][g] for c in CAMERAS}


def _camera(
    folder: pathlib.Path,
    rows: list,
    camera: str,
    steps: list,
    step_numbers: list,
    axis_start_mev: float | None = None,
) -> list:
    """`camera`'s EnergyProfiles at each of `step_numbers`."""
    i, zi = htu_scans.stack(folder, f"UC_BCaveMagSpec{camera}-ImageInterp", rows)
    d, _ = htu_scans.stack(folder, f"UC_BCaveMagSpec{camera}-interpDiv", [])
    e = htu_scans.energy_axis(folder, camera, axis_start_mev)
    # POSIT: ImageInterp's rows are interpDiv's AngleAxis in reverse order, its columns
    # interpSpec's energies (checked on Scans 025, 028, 030: the row sums match interpDiv
    # reversed, the column sums interpSpec)
    a = d[0, ::-1, 0].astype(float)
    if i.shape[1:] != (a.size, e.size):
        raise ValueError(
            f"{folder.name} {camera}: ImageInterp {i.shape[1:]} against axes {(a.size, e.size)}"
        )
    b = numpy.arange(e.min(), e.max() + BIN_MEV / 2, BIN_MEV)
    j = numpy.clip(numpy.digitize(e, b) - 1, 0, b.size - 2)
    rv = []
    for t in step_numbers:
        f = [zi[r] for r, n in enumerate(steps) if n == t and zi[r] >= 0]
        if not f:
            raise ValueError(f"{folder.name} step {t}: no {camera} ImageInterp frame")
        # per shot, per slice: the vertical profile
        y = numpy.clip(i[f].astype(float), 0, None)
        p = numpy.stack(
            [y[:, :, j == k].sum(axis=2) for k in range(b.size - 1)], axis=1
        )
        m = p.mean(axis=0)
        w = m.sum(axis=1)
        ok = w >= MIN_FRACTION * w.sum()
        c = numpy.full(b.size - 1, numpy.nan)
        r, ce, re = c.copy(), c.copy(), c.copy()
        for k in numpy.flatnonzero(ok):
            c[k] = (m[k] * a).sum() / w[k]
            r[k] = numpy.sqrt((m[k] * (a - c[k]) ** 2).sum() / w[k])
            q = p[:, k]
            u = q.sum(axis=1)
            g = u > 0
            pc = (q[g] * a).sum(axis=1) / u[g]
            pr = numpy.sqrt((q[g] * (a - pc[:, None]) ** 2).sum(axis=1) / u[g])
            ce[k] = pc.std() / numpy.sqrt(g.sum())
            re[k] = pr.std() / numpy.sqrt(g.sum())
        rv.append(
            EnergyProfiles(
                angle_range=(float(a.min()), float(a.max())),
                centroid=c,
                centroid_error=ce,
                energy_mev=b,
                rms=r,
                rms_error=re,
            )
        )
    return rv


def _numbers(scans: dict) -> int:
    return int(
        sum(
            2 * numpy.isfinite(s.cameras[c].centroid).sum()
            for v in scans.values()
            for s in v
            for c in CAMERAS
        )
    )


def _predict_one(source, step, machine_state):
    from htu_twin_apps.lpa_source import fit

    return _predict_step(fit.sampled(source), step, machine_state)


def _predict_parallel(pool, scans: dict, source, machine_state: dict) -> dict:
    j = {
        n: [pool.submit(_predict_one, source, s, machine_state) for s in v]
        for n, v in scans.items()
    }
    return {n: [x.result() for x in v] for n, v in j.items()}


def _predict_step(particles, step: Step, machine_state: dict) -> dict:
    import htu.model
    from htu_twin_apps.lpa_source import fit, pointing, twin

    m = {**step.machine_state, **twin.without_slit(machine_state)}
    # the data's energy labels are the true energies times this (scans.ENERGY_LABEL_KEY)
    s = m.pop(htu_scans.ENERGY_LABEL_KEY, 1.0)
    t = twin.to_spectrometer(particles, m, reference_mev=fit.REFERENCE_MEV)
    f = {**htu.model.DEFAULT_MACHINE_STATE, **m}["magspec_b"]
    rv = {}
    for c, q in step.cameras.items():
        b = q.energy_mev
        k = (t.charge_pc > 0) & (t.energy_mev * s >= b[0]) & (t.energy_mev * s < b[-1])
        y = pointing.screen_angles(t, k, f)
        e = t.energy_mev[k] * s
        w = t.charge_pc[k]
        with numpy.errstate(invalid="ignore"):
            g = (y >= q.angle_range[0]) & (y <= q.angle_range[1])
        i = numpy.digitize(e, b) - 1
        cc = numpy.full(b.size - 1, numpy.nan)
        rr = cc.copy()
        for j in range(b.size - 1):
            h = g & (i == j)
            if w[h].sum() > 0:
                cc[j] = numpy.average(y[h], weights=w[h])
                rr[j] = numpy.sqrt(numpy.average((y[h] - cc[j]) ** 2, weights=w[h]))
        rv[c] = (cc, rr)
    return rv


def _spectrum_distance(source, machine_state: dict, spectrum) -> float:
    """Scan016's spectrum distance (`compare`) of `source` and `machine_state`, the slit out and
    the twin's energies scaled to the data's labels (scans.ENERGY_LABEL_KEY)."""
    from htu_twin_apps.lpa_source import aline, compare, fit, twin

    m = {
        k: v
        for k, v in twin.without_slit(machine_state).items()
        if k not in (aline.PIXEL_KEY, htu_scans.ENERGY_LABEL_KEY)
    }
    t = twin.to_spectrometer(
        fit.sampled(source),
        {**twin.SCAN016_STATE, **m},
        reference_mev=fit.REFERENCE_MEV,
    )
    t = dataclasses.replace(
        t, energy_mev=t.energy_mev * machine_state.get(htu_scans.ENERGY_LABEL_KEY, 1.0)
    )
    try:
        return float(compare.compare(t, spectrum)["distance"])
    except ValueError:
        return 1.0
