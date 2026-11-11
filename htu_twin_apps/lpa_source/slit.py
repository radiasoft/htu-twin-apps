"""Fit the chicane slit and the source's horizontal beam to an R56 scan with the slit in.

In Scan019 (2026-09-29) the chicane's R56 is stepped with its energy slit in. The slit sits where
the chicane disperses the beam horizontally by energy, so it cuts the spectrum, and as R56 (the
dispersion) grows the cut moves in energy. The measured cut does not move as two fixed jaws on a
beam with no energy-dependent position would make it (status: "Chicane calibration"), and its
edges are sharp (1 to 2 MeV), which needs a horizontally small beam at the slit.

Each step's measured spectrum is the mean, over its shots, of the two spectrometer cameras'
`-interpSpec` spectra stitched together, binned and normalized over the spectrometer's window as
`compare.measured` does Scan016's. Each step is predicted by tracking the source through the twin
with the step's logged settings and the slit, and compared by `compare`'s distance; the objective
is the mean distance over the steps. The fitted knobs are by default the slit's edges, the
source's horizontal pointing, its slope with energy and divergence, and the PMQ triplet's
longitudinal position (which moves its focus), with the slit as jaws, as a blade, or as jaws
with a blade (`twin.to_spectrometer`'s `slit`), whose edges are then fitted too.

:copyright: Copyright (c) 2026 RadiaSoft LLC.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""

from __future__ import annotations

import dataclasses
import numpy
import pathlib

from htu_twin_apps.lpa_source import scans as htu_scans

CAMERAS = ("Cam1", "Cam2")
# The knobs fitted by default: the slit's edges, the source's horizontal beam, the PMQs' z.
FIT_NAMES = (
    "chicane_jaw1_mm",
    "chicane_jaw2_mm",
    "pointing_x_mrad",
    "pointing_slope_x_mrad",
    "divergence_x_mrad",
    "pmq_z_mm",
)
SCAN = "Scan019"
# Where the slit's edges start when the machine state does not give them [mm, lab frame]: jaw 1
# just outside the beam at the scan's middle setting with jaw 2 retracted, or a 1 mm blade there
# (status: "Chicane calibration", the edges' implied positions).
SLIT_STARTS = {
    "blade": {"chicane_jaw1_mm": 7.0, "chicane_jaw2_mm": 6.0},
    "jaws": {"chicane_jaw1_mm": 6.0, "chicane_jaw2_mm": -20.0},
    # the jaw where the jaws fit put it, a 0.6 mm blade where the slit-fitted beam puts Scan019's
    # notch at its middle steps
    "jaws_blade": {
        "chicane_jaw1_mm": 3.74,
        "chicane_jaw2_mm": -20.0,
        "slit_blade_high_mm": 1.6,
        "slit_blade_low_mm": 1.0,
    },
}


@dataclasses.dataclass
class SlitFit:
    """The fit's result: the knobs, the fitted source and machine state, and each step's
    distance."""

    distance: float
    distances: list
    evaluations: int
    machine_state: dict
    names: tuple
    slit: str
    source: object
    start_distance: float
    values: dict


@dataclasses.dataclass
class SlitStep:
    """One step: its measured spectrum (normalized, on `energy_mev`) and twin machine state."""

    density: numpy.ndarray
    energy_mev: numpy.ndarray
    machine_state: dict


def distances(steps: list, source, machine_state: dict, slit: str) -> numpy.ndarray:
    """Each step's distance between its measured spectrum and the source's, tracked with the
    step's settings, `machine_state` over them, and `slit`; 1 for no charge in the window.
    """
    from htu_twin_apps.lpa_source import compare, fit, source as lpa_source, twin

    g = (
        lpa_source.particles(source)
        if isinstance(source, lpa_source.LPASource)
        else source
    )
    rv = []
    for s in steps:
        t = twin.to_spectrometer(
            g,
            {**s.machine_state, **machine_state},
            reference_mev=fit.REFERENCE_MEV,
            slit=slit,
        )
        try:
            d = compare.spectrum(t, s.energy_mev)[0]
        except ValueError:
            rv.append(1.0)
            continue
        rv.append(0.5 * float(numpy.abs(d - s.density).sum() * compare.ENERGY_STEP_MEV))
    return numpy.array(rv)


def fit(
    steps: list,
    source,
    machine_state: dict,
    names=FIT_NAMES,
    slit: str = "blade",
    bounds: dict | None = None,
    max_evaluations: int = 400,
    restarts: int = 4,
    num_particles: int = 30_000,
    log=None,
) -> SlitFit:
    """Fit the knobs `names` to `steps` (`measured()`), starting from `source` and
    `machine_state` (the jaws' start among its keys).

    Args:
        steps: the scan's steps.
        source: the `LPASource` to start from.
        machine_state: twin machine-state keys set over every step's (the fitted ones start
            from their values here, else the twin's defaults).
        names: the knobs to fit: `LPASource` fields or twin machine-state keys.
        slit: the slit's shape (`twin.SLITS`).
        bounds: as for `fit.minimize`.
        max_evaluations: Nelder-Mead's budget per start.
        restarts: as for `fit.minimize`.
        num_particles: particles per evaluation.
        log: called after every evaluation with (evaluation number, mean distance, values).
    """
    from htu_twin_apps.lpa_source import fit as lpa_fit, twin

    s = dataclasses.replace(source, num_particles=num_particles)
    if slit == "jaws_blade":
        names = tuple(names) + tuple(x for x in twin.BLADE_KEYS if x not in names)
    x, d, n = lpa_fit.minimize(
        lambda v: distances(
            steps, *lpa_fit.apply(s, machine_state, names, v), slit
        ).mean(),
        lpa_fit.knobs(s, machine_state, names),
        names,
        bounds=bounds,
        max_evaluations=max_evaluations,
        restarts=restarts,
        log=log,
    )
    f = lpa_fit.apply(source, machine_state, names, x)
    return SlitFit(
        distance=d,
        distances=distances(
            steps, *lpa_fit.apply(s, machine_state, names, x), slit
        ).tolist(),
        evaluations=n,
        machine_state=f[1],
        names=tuple(names),
        slit=slit,
        source=f[0],
        start_distance=float(distances(steps, s, machine_state, slit).mean()),
        values=dict(zip(names, map(float, x))),
    )


def measured(
    data: pathlib.Path,
    scan: str = SCAN,
    axis_start_mev: float | None = None,
    numbers: list | None = None,
) -> list:
    """The steps of `scan` found below `data`: stitched spectra and settings. `axis_start_mev`: as for `scans.energy_axis`.
    `numbers`: each row's step in place of the scan's own (`Bin #`), to group its shots otherwise
    (by charge, say); a negative number leaves the row out."""
    from htu_twin_apps.lpa_source import compare

    f, rows = htu_scans.table(data, scan)
    n = htu_scans.step_numbers(rows) if numbers is None else list(numbers)
    c = [htu_scans.stack(f, f"UC_BCaveMagSpec{x}-interpSpec", rows) for x in CAMERAS]
    # POSIT: each camera's -interpSpec frames share one energy axis (column 0) in a scan
    x = numpy.concatenate(
        [htu_scans.energy_axis(f, n, axis_start_mev) for n in CAMERAS]
    )
    o = numpy.argsort(x, kind="stable")
    k = round(compare.ENERGY_STEP_MEV / compare.MEASURED_STEP_MEV)
    e = numpy.arange(x.min(), x.max(), compare.MEASURED_STEP_MEV)
    e = e[: e.size // k * k]
    rv = []
    for i in sorted(x for x in set(n) if x >= 0):
        j = [r for r, m in enumerate(n) if m == i and all(z[r] >= 0 for _, z in c)]
        if not j:
            raise ValueError(f"{scan} step {i}: no shot with both cameras' spectra")
        y = numpy.mean(
            [numpy.concatenate([a[z[r], :, 1] for a, z in c])[o] for r in j], axis=0
        )
        d = numpy.clip(numpy.interp(e, x[o], y), 0.0, None).reshape(-1, k).mean(axis=1)
        rv.append(
            SlitStep(
                density=d / (d.sum() * compare.ENERGY_STEP_MEV),
                energy_mev=e.reshape(-1, k).mean(axis=1),
                machine_state=htu_scans.machine_state([rows[r] for r in j]),
            )
        )
    return rv


def plot(steps: list, result: SlitFit, path: pathlib.Path) -> None:
    """Each step's measured spectrum against the fitted source's, around the cut."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot
    from htu_twin_apps.lpa_source import compare, fit, source as lpa_source, twin

    g = lpa_source.particles(result.source)
    f, ax = matplotlib.pyplot.subplots(4, 5, figsize=(20, 12), sharex=True)
    for a, s, d in zip(ax.flat, steps, result.distances):
        t = twin.to_spectrometer(
            g,
            {**s.machine_state, **result.machine_state},
            reference_mev=fit.REFERENCE_MEV,
            slit=result.slit,
        )
        a.plot(s.energy_mev, s.density, "k", lw=1.5, label="measured")
        a.plot(
            s.energy_mev, compare.spectrum(t, s.energy_mev)[0], "r", lw=1, label="twin"
        )
        a.set_xlim(55, 160)
        a.set_title(
            f"{s.machine_state['chicane_current']:.3f} A, distance {d:.2f}", fontsize=9
        )
        a.grid(alpha=0.3)
    ax.flat[0].legend()
    f.savefig(path, dpi=70, bbox_inches="tight")
