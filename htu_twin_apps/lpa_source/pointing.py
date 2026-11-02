"""Fit the source's vertical pointing with the spectrometer's EMQ scans' vertical profiles.

HTU's spectrometer cameras record, per shot, a vertical profile (`UC_BCaveMagSpec<cam>-interpDiv`,
against an "AngleAxis") and a spectrum (`-interpSpec`, in MeV). The spectrometer's LabVIEW driver
(GEECS-Device-Drivers `MagSpecCamera`) makes the AngleAxis from each pixel's vertical position on
the screen divided by the "total path" of that pixel's momentum in its trajectory calibration
file: an apparent angle, through the magnet's vertical optics. In the scans that step one EMQ
while the spectrometer records (Scans 025, 028 and 030 on 2026-09-29), the profile's centroid and
width move with the EMQ current, which depends on where the beam is, vertically, in the EMQ
triplet.

For every step of those scans and each camera, the source is tracked through the twin with that
step's settings (`twin.to_spectrometer`), with the chicane slit's jaws out, and reweighted in
ENERGY_BIN_MEV bins to the step's measured spectrum on that camera: the slit cuts horizontally,
by energy, so this stands in for it (the twin's slit model does not reproduce Scan019). The
particles are then projected (`projection`):

- `"spectrometer"` (the default): onto the spectrometer's screen with the twin's model of it,
  `htu.magspec.DutchCalibration`, built from HTU's own calibration files for this magnet (the
  "Dutch magnet"): each particle's vertical screen position from the per-momentum map at its
  momentum over the field (`magspec_b`, a twin machine-state key, 0.825 T by default; the field
  was not logged), divided by that momentum's total path in the same trajectory file, as the
  driver does. The result is in mrad, the AngleAxis's own units if that reading of the driver is
  right (the AngleAxis spans about +-23 mrad, the screen's height over a total path of about
  0.5 m); a fitted scale near +-1 would confirm it. As on the camera, only particles within the
  camera's AngleAxis range count: the beam's strongly mis-focused tail lands off the screen.
- `"stand-in"`: `Y = y + d y'` at the spectrometer entrance, with `d` in DISTANCES_M, the best
  `d` per evaluation (what the fit used before the spectrometer was modelled).

Per camera, a scale `a`, a zero `b` and a resolution floor `r0` relate the prediction to the
measurement (`centroid = a C + b`, `rms^2 = a^2 R^2 + r0^2`); both cameras' scales are given one
sign. The
chi^2 that remains, over every step's centroid and rms on both cameras, is minimized over the
source's vertical pointing, its vertical divergence and the PMQ triplet's vertical offset
(`pmq_y_mm`), with Nelder-Mead from several starts.

Only the vertical plane is measured this way: horizontal is the spectrometer's dispersive plane.

:copyright: Copyright (c) 2026 RadiaSoft LLC.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""

from __future__ import annotations

import csv
import dataclasses
import functools
import numpy
import pathlib

from htu_twin_apps.lpa_source import scans as htu_scans

CAMERAS = ("Cam1", "Cam2")
# The stand-in projection's distances [m], for Y = y + d y'; the best per evaluation is used.
DISTANCES_M = (0.0, 0.1, 0.2, 0.3, 0.45)
# Energy bins [MeV] for reweighting the tracked particles to a step's measured spectrum.
ENERGY_BIN_MEV = 2.0
# The smallest error [AngleAxis units] given a step's centroid or rms: a step's standard error
# from its shots can be implausibly small.
ERROR_FLOOR = 0.05
# The knobs fitted, in order: LPASource fields and a twin machine-state key.
FIT_NAMES = ("pointing_y_mrad", "pmq_y_mm", "divergence_y_mrad")
# The projections: onto the spectrometer's screens, or the stand-in.
PROJECTIONS = ("spectrometer", "stand-in")
# chi^2 rise for a 68% joint region of three parameters, before scaling by chi^2 per degree of
# freedom (the fit's excess over its errors).
RANGE_CHI2 = 3.53
# Spectrometer scans that step one EMQ, by scan folder name.
SCANS = ("Scan025", "Scan028", "Scan030")
# Shots below this percentile of a step's profile sums are left out of its per-shot errors.
WEAK_SHOT_PERCENTILE = 20


@dataclasses.dataclass
class PointingFit:
    """The fit's result.

    `machine_state` is the twin machine state it was fitted with, `pmq_y_mm` fitted; `cameras`
    holds each camera's (chi^2, a, b, r0); `projection` is "spectrometer", or the stand-in's best
    `d` [m]; `ranges` the rough 68% range of each fitted knob, from the evaluated points within the
    scaled RANGE_CHI2 of the best.
    """

    cameras: dict
    chi2: float
    evaluations: int
    machine_state: dict
    measured_numbers: int
    projection: object
    ranges: dict
    source: object
    starts: list


@dataclasses.dataclass
class Profile:
    """A step's mean vertical profile on one camera, and that camera's mean spectrum.

    `angle_range` is the camera's AngleAxis range (min, max): what its screen and view take in.
    """

    angle_range: tuple
    centroid: float
    centroid_error: float
    energy_mev: numpy.ndarray
    rms: float
    rms_error: float
    spectrum: numpy.ndarray


@dataclasses.dataclass
class Step:
    """One step of a scan: its twin machine state and each camera's profile."""

    cameras: dict
    machine_state: dict


def fit(
    scans: dict,
    source,
    machine_state: dict | None = None,
    starts=None,
    emq_sign: int = 1,
    max_evaluations: int = 60,
    num_particles: int = 30_000,
    projection: str = "spectrometer",
    log=None,
) -> PointingFit:
    """Fit FIT_NAMES to `scans` (by name, as `measured()` gives each), starting from `source`.

    Args:
        scans: each scan's steps.
        source: the `LPASource` to start from (such as the one `fit.fit` gives for Scan016).
        machine_state: twin machine-state keys fitted with `source` (such as `pmq_z_mm`), set
            over every step's; its `pmq_y_mm`, if any, is where the default start begins.
        starts: (pointing_y_mrad, pmq_y_mm, divergence_y_mrad) to start Nelder-Mead from; by
            default the source's own values, and -2 mrad, 0.3 mm, 1.4 times its divergence.
        emq_sign: 1 for the twin's EMQ polarity, -1 to flip every EMQ current.
        max_evaluations: Nelder-Mead's evaluation budget, per start.
        num_particles: particles per evaluation (fewer than for the energy fit: every evaluation
            tracks every step of every scan).
        projection: one of PROJECTIONS (see the module's docstring).
        log: called after every evaluation with (evaluation number, chi^2, {name: value}).
    """
    import scipy.optimize

    s = dataclasses.replace(source, num_particles=num_particles)
    m = dict(machine_state or {})
    seen = []

    def _objective(v):
        if v[2] <= 0:
            return 1e9
        rv = score(
            scans, predict(_source(s, v), scans, {**m, "pmq_y_mm": v[1]}, emq_sign, projection)
        )
        seen.append((float(rv[0]), list(map(float, v))))
        if log:
            log(len(seen), float(rv[0]), dict(zip(FIT_NAMES, map(float, v))))
        return rv[0]

    rv = []
    for x in starts or (
        (s.pointing_y_mrad, m.get("pmq_y_mm", 0.0), s.divergence_y_mrad),
        (-2.0, 0.3, 1.4 * s.divergence_y_mrad),
    ):
        x = numpy.array(x, dtype=float)
        r = scipy.optimize.minimize(
            _objective,
            x,
            method="Nelder-Mead",
            options={
                "maxfev": max_evaluations,
                "xatol": 0.02,
                "fatol": 2.0,
                "initial_simplex": numpy.vstack([x, x + numpy.diag([0.5, 0.3, 0.3 * x[2]])]),
            },
        )
        rv.append({"start": x.tolist(), "chi2": float(r.fun), "values": r.x.tolist()})
    b = min(rv, key=lambda r: r["chi2"])["values"]
    c, d, k = score(
        scans, predict(_source(s, b), scans, {**m, "pmq_y_mm": b[1]}, emq_sign, projection)
    )
    n = 4 * sum(len(v) for v in scans.values())
    return PointingFit(
        cameras=k,
        chi2=c,
        evaluations=len(seen),
        machine_state={**m, "pmq_y_mm": b[1]},
        measured_numbers=n,
        projection=d,
        ranges=_ranges(seen, c, n),
        source=_source(source, b),
        starts=rv,
    )


def measured(data: pathlib.Path, scan: str) -> list:
    """The steps of `scan` (a scan folder name, such as `Scan025`) found below `data`."""
    f, rows = htu_scans.table(data, scan)
    n = htu_scans.step_numbers(rows)
    k = sorted(set(n))
    c = {x: [_profiles(f, rows, x, n, i) for i in k] for x in CAMERAS}
    return [
        Step(
            cameras={x: c[x][j] for x in CAMERAS},
            machine_state=htu_scans.machine_state([r for r, m in zip(rows, n) if m == i]),
        )
        for j, i in enumerate(k)
    ]


def plot(scans: dict, result: PointingFit, path: pathlib.Path, emq_sign: int = 1) -> None:
    """Each scan's measured centroid and rms per camera against the fit's (scaled) prediction."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot

    p = predict(
        result.source,
        scans,
        result.machine_state,
        emq_sign,
        "spectrometer" if result.projection == "spectrometer" else "stand-in",
    )
    f, ax = matplotlib.pyplot.subplots(4, len(scans), figsize=(5 * len(scans), 13), squeeze=False)
    for j, (n, steps) in enumerate(scans.items()):
        x = [_stepped(steps, s) for s in steps]
        for i, cam in enumerate(CAMERAS):
            _, a, b, r0 = result.cameras[cam]
            q = [v[cam][result.projection] for v in p[n]]
            for k, (y, e, z, t) in enumerate(
                (
                    ("centroid", "centroid_error", [a * v[0] + b for v in q], "centroid"),
                    ("rms", "rms_error", [numpy.hypot(a * v[1], r0) for v in q], "rms"),
                )
            ):
                g = ax[2 * i + k, j]
                g.errorbar(
                    x,
                    [getattr(s.cameras[cam], y) for s in steps],
                    [max(getattr(s.cameras[cam], e), ERROR_FLOOR) for s in steps],
                    fmt="ko",
                    ms=3,
                    label="measured",
                )
                g.plot(x, z, "r-", label="twin (scaled)")
                g.set_title(f"{n} {cam} {t}", fontsize=9)
                g.grid(alpha=0.3)
        ax[-1, j].set_xlabel("stepped EMQ current (A)")
    ax[0, 0].legend()
    f.savefig(path, dpi=75, bbox_inches="tight")


def predict(
    source,
    scans: dict,
    machine_state: dict,
    emq_sign: int = 1,
    projection: str = "spectrometer",
) -> dict:
    """Per scan, per step, per camera: {key: (C, R)}, the predicted centroid and rms.

    With the "spectrometer" projection the key is "spectrometer" and the values are AngleAxis
    mrad; with the "stand-in" the keys are DISTANCES_M and the values are mm of `y + d y'`.

    Args:
        source: the `LPASource` (or a `ParticleGroup` of it, to reuse one sampling).
        scans: each scan's steps (`measured()`).
        machine_state: twin machine-state keys set over every step's (such as `pmq_y_mm`),
            and `twin.SCALES`' knobs.
        emq_sign: 1 for the twin's EMQ polarity, -1 to flip every EMQ current.
        projection: one of PROJECTIONS.
    """
    import htu.model
    from htu_twin_apps.lpa_source import fit, source as lpa_source, twin

    if projection not in PROJECTIONS:
        raise ValueError(f"projection {projection!r} not one of {PROJECTIONS}")

    g = lpa_source.particles(source) if isinstance(source, lpa_source.LPASource) else source
    rv = {}
    for n, steps in scans.items():
        rv[n] = []
        for s in steps:
            m = {
                k: (emq_sign * v if k in htu_scans.NOMINAL_EMQ else v)
                for k, v in s.machine_state.items()
            }
            m = {**m, **twin.without_slit(machine_state)}
            t = twin.to_spectrometer(g, m, reference_mev=fit.REFERENCE_MEV)
            b = {**htu.model.DEFAULT_MACHINE_STATE, **m}["magspec_b"]
            rv[n].append(
                {c: _projected(t, p, projection, b) for c, p in s.cameras.items()}
            )
    return rv


def residual_chi2(scans: dict, predictions: dict, key, cameras: dict) -> float:
    """chi^2 of `predictions` at projection `key` against `scans` with each camera's (chi^2,
    a, b, r0) in `cameras` held fixed (such as a fit's on other scans): a prediction."""
    rv = 0.0
    for c, (_, a, b, r0) in cameras.items():
        m = [s.cameras[c] for n in scans for s in scans[n]]
        p = numpy.array([v[c][key] for n in scans for v in predictions[n]])
        if not numpy.all(numpy.isfinite(p)):
            return numpy.inf
        for x, e, y in (
            ("centroid", "centroid_error", a * p[:, 0] + b),
            ("rms", "rms_error", numpy.hypot(a * p[:, 1], r0)),
        ):
            r = (numpy.array([getattr(z, x) for z in m]) - y) / numpy.maximum(
                [getattr(z, e) for z in m], ERROR_FLOOR
            )
            rv += float((r**2).sum())
    return rv


def score(scans: dict, predictions: dict) -> tuple:
    """(chi^2, key, {camera: (chi^2, a, b, r0)}) at the best projection key (one for the
    spectrometer, the stand-in's distances), the cameras' scales of one sign."""
    rv = (numpy.inf, None, None)
    p = next(iter(predictions.values()))[0]
    for d in p[CAMERAS[0]]:
        f = {c: _camera_fits(scans, predictions, c, d) for c in CAMERAS}
        if any(v is None for v in f.values()):
            continue
        for s in (1, -1):
            x = sum(f[c][s][0] for c in CAMERAS)
            if x < rv[0]:
                rv = (float(x), d, {c: f[c][s] for c in CAMERAS})
    return rv


def screen_angles(transported, mask: numpy.ndarray, field_t: float) -> numpy.ndarray:
    """The AngleAxis [mrad] of the `mask` particles: vertical screen position over total path.

    NaN for a particle beyond the side screen's or the maps' momentum range.
    """
    from htu_twin_apps.lpa_source import source

    c, p_table, path = _spectrometer()
    e = transported.energy_mev[mask]
    p = numpy.sqrt(numpy.maximum(e**2 - source.ELECTRON_MASS_MEV**2, 0)) / field_t
    # POSIT: htu.magspec.DutchCalibration.map_to_screens' vertical map: coordinates in m and rad
    # at its reference plane (the twin's MagSpec entrance, END_ELEMENT's exit), the per-momentum
    # coefficients interpolated at p / B, y_f the sum over its exponents' monomials
    v = numpy.stack(
        [
            transported.x_mm[mask] * 1e-3,
            transported.xp_mrad[mask] * 1e-3,
            transported.y_mm[mask] * 1e-3,
            transported.yp_mrad[mask] * 1e-3,
        ],
        axis=1,
    )
    y = numpy.sum(
        c._interp_rows(c.coeff_y, p)
        * numpy.prod(v[:, None, :] ** c.exponents[None, :, :], axis=2),
        axis=1,
    )
    # POSIT: HTU's Cam1 and Cam2 view the trajectory file's side screen (the twin's
    # docs/magspec-design.md crosswalk), which takes momenta up to p_side_max
    k = (p >= c.p_mev[0]) & (p <= c.p_side_max)
    return numpy.where(k, y / numpy.interp(p, p_table, path) * 1e3, numpy.nan)


def _camera_fits(scans: dict, predictions: dict, camera: str, d: float):
    """{sign: (chi^2, a, b, r0)} of `camera` over every step at projection key `d`, the scale of
    each sign."""
    import scipy.optimize

    m = [s.cameras[camera] for n in scans for s in scans[n]]
    p = numpy.array([v[camera][d] for n in scans for v in predictions[n]])
    if not numpy.all(numpy.isfinite(p)):
        return None
    c, r = (numpy.array([getattr(x, k) for x in m]) for k in ("centroid", "rms"))
    ec, er = (
        numpy.maximum([getattr(x, k) for x in m], ERROR_FLOOR)
        for k in ("centroid_error", "rms_error")
    )

    def _residuals(v):
        a, b, r0 = v
        return numpy.concatenate(
            [(c - a * p[:, 0] - b) / ec, (r - numpy.hypot(a * p[:, 1], r0)) / er]
        )

    rv = {}
    for s in (1, -1):
        f = scipy.optimize.least_squares(
            _residuals,
            [0.5 * s, 0.0, 2.0],
            bounds=(
                [1e-6 if s > 0 else -numpy.inf, -numpy.inf, 0.0],
                [numpy.inf if s > 0 else -1e-6, numpy.inf, numpy.inf],
            ),
        )
        rv[s] = (float((f.fun**2).sum()), *map(float, f.x))
    return rv




def _moments(values: numpy.ndarray, weights: numpy.ndarray) -> tuple:
    """(centroid, rms) of `values` with `weights`; NaN for no weight."""
    if values.size == 0 or weights.sum() <= 0:
        return (numpy.nan, numpy.nan)
    c = numpy.average(values, weights=weights)
    return (float(c), float(numpy.sqrt(numpy.average((values - c) ** 2, weights=weights))))




def _profiles(folder: pathlib.Path, rows: list, camera: str, steps: list, step: int) -> Profile:
    """`camera`'s profile and spectrum for one step, from its two stacks in the scan folder."""
    d, e = (
        htu_scans.stack(folder, f"UC_BCaveMagSpec{camera}-{k}", rows)
        for k in ("interpDiv", "interpSpec")
    )
    i = [j for j, n in enumerate(steps) if n == step and d[1][j] >= 0 and e[1][j] >= 0]
    if not i:
        raise ValueError(f"{folder.name} step {step}: no shot with both {camera} stacks")
    x = d[0][0, :, 0]
    y = numpy.clip(d[0][[d[1][j] for j in i], :, 1], 0, None)
    m = y.mean(axis=0)
    c = float((m * x).sum() / m.sum())
    w = y.sum(axis=1)
    k = w > numpy.percentile(w, WEAK_SHOT_PERCENTILE)
    pc = (y[k] * x).sum(axis=1) / w[k]
    pr = numpy.sqrt((y[k] * (x - pc[:, None]) ** 2).sum(axis=1) / w[k])
    return Profile(
        angle_range=(float(x.min()), float(x.max())),
        centroid=c,
        centroid_error=float(pc.std() / numpy.sqrt(k.sum())),
        energy_mev=e[0][0, :, 0],
        rms=float(numpy.sqrt((m * (x - c) ** 2).sum() / m.sum())),
        rms_error=float(pr.std() / numpy.sqrt(k.sum())),
        spectrum=numpy.clip(e[0][[e[1][j] for j in i], :, 1], 0, None).mean(axis=0),
    )


def _projected(transported, profile: Profile, projection: str, field_t: float) -> dict:
    """{key: (C, R)} of the transported particles on `profile`'s camera, reweighted to its
    spectrum (see `predict`)."""
    e = profile.energy_mev
    a = (
        (transported.charge_pc > 0)
        & (transported.energy_mev >= e.min())
        & (transported.energy_mev < e.max())
    )
    b = numpy.arange(e.min(), e.max() + ENERGY_BIN_MEV, ENERGY_BIN_MEV)
    h, _ = numpy.histogram(transported.energy_mev[a], b, weights=transported.charge_pc[a])
    r = numpy.where(
        h > 0, numpy.interp((b[1:] + b[:-1]) / 2, e, profile.spectrum) / numpy.where(h > 0, h, 1), 0
    )
    i = numpy.clip(numpy.digitize(transported.energy_mev[a], b) - 1, 0, r.size - 1)
    w = transported.charge_pc[a] * r[i]
    if projection == "spectrometer":
        y = screen_angles(transported, a, field_t)
        # as on the camera: only what lands within its AngleAxis range is in the profile
        with numpy.errstate(invalid="ignore"):
            k = (y >= profile.angle_range[0]) & (y <= profile.angle_range[1])
        return {"spectrometer": _moments(y[k], w[k])}
    return {
        d: _moments(transported.y_mm[a] + d * transported.yp_mrad[a], w) for d in DISTANCES_M
    }


def _ranges(seen: list, chi2: float, measured_numbers: int) -> dict:
    """Each knob's (low, high) over the evaluated points within the scaled RANGE_CHI2 of `chi2`."""
    # POSIT: 6 nuisance parameters (a, b, r0 per camera in CAMERAS) and FIT_NAMES are fitted
    s = max(chi2 / (measured_numbers - 6 - len(FIT_NAMES)), 1.0) * RANGE_CHI2
    v = numpy.array([x for c, x in seen if c <= chi2 + s])
    return {n: (float(v[:, i].min()), float(v[:, i].max())) for i, n in enumerate(FIT_NAMES)}


def _source(source, values):
    return dataclasses.replace(
        source, pointing_y_mrad=float(values[0]), divergence_y_mrad=float(values[2])
    )


@functools.cache
def _spectrometer() -> tuple:
    """The twin's spectrometer calibration, and its trajectory file's momenta [MeV/c at 1 T] and
    total paths [m] (DutchCalibration does not keep the paths)."""
    import htu.magspec

    with open(htu.magspec.TRJ_FILE, newline="") as f:
        r = [x for x in csv.reader(f, delimiter="\t") if x and x[0].strip()]
    h = [x.strip() for x in r[0]]
    p, t = h.index("momentum [MeV/c]"), h.index("total path [m]")
    v = numpy.array([[float(x[p]), float(x[t])] for x in r[1:]])
    return htu.magspec.DutchCalibration(), v[:, 0], v[:, 1]






def _stepped(steps: list, step: Step) -> float:
    """The setting that changes across `steps`, at `step`: the scanned EMQ's current."""
    k = max(
        htu_scans.NOMINAL_EMQ,
        key=lambda n: numpy.ptp([s.machine_state.get(n, 0.0) for s in steps]),
    )
    return step.machine_state[k]
