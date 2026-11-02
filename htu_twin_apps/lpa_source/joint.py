"""Fit the source jointly to Scan016's spectrum and the spectrometer EMQ scans' vertical profiles.

The objective is the pointing fit's chi^2 on the training scans (TRAIN, through `pointing`'s
projection) plus `(distance / SPECTRUM_SIGMA) ** 2` of Scan016's spectrum (`compare`): the
spectrum counts like one measured number with an error of SPECTRUM_SIGMA in distance, a choice
(about twice its sampling noise); without a spectrum the objective is the chi^2 alone. Any
knobs can be fitted, with any training scans, including `twin.SCALES`' and the
spectrometer's field (`magspec_b`, which enters only through the projection). The held-out scans (HELD_OUT) are not fitted: they are
predicted with the training fit's per-camera scale, zero and floor held fixed
(`pointing.residual_chi2`), which tests the fit on data it did not see.

:copyright: Copyright (c) 2026 RadiaSoft LLC.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""

from __future__ import annotations

import dataclasses
import numpy

# The knobs fitted by default: the source's energy and divergence, its vertical pointing, and
# the PMQ triplet's vertical and longitudinal position.
FIT_NAMES = (
    "energy_mev",
    "energy_sigma_mev",
    "energy_tail_mev",
    "divergence_x_mrad",
    "divergence_y_mrad",
    "divergence_power",
    "pointing_y_mrad",
    "pmq_y_mm",
    "pmq_z_mm",
)
# The pointing scans held out of the fit, to be predicted.
HELD_OUT = ("Scan030",)
# Scan016's spectrum distance counted as one measured number of this error.
SPECTRUM_SIGMA = 0.01
# The pointing scans fitted.
TRAIN = ("Scan025", "Scan028")


@dataclasses.dataclass
class JointFit:
    """The fit's result.

    `parts` holds the objective's parts at the best point (`spectrum_distance`,
    `pointing_chi2`, `cameras`); `held_out_chi2` the held-out scans' chi^2 with the training
    cameras fixed, and `held_out_numbers` how many numbers that is over.
    """

    evaluations: int
    held_out_chi2: float
    held_out_numbers: int
    machine_state: dict
    names: tuple
    objective: float
    parts: dict
    source: object
    start_objective: float
    training_numbers: int
    values: dict


def evaluate(spectrum, train: dict, source, machine_state: dict, projection: str) -> tuple:
    """(objective, parts) of `source` and `machine_state` (see the module's docstring)."""
    from htu_twin_apps.lpa_source import compare, fit, pointing, source as lpa_source, twin

    g = lpa_source.particles(source)
    c, k, cams = pointing.score(
        train, pointing.predict(g, train, machine_state, projection=projection)
    )
    if spectrum is None:
        return c, {"cameras": cams, "pointing_chi2": c, "projection": k, "spectrum_distance": None}
    try:
        d = compare.compare(
            twin.to_spectrometer(
                g,
                {**twin.SCAN016_STATE, **twin.without_slit(machine_state)},
                reference_mev=fit.REFERENCE_MEV,
            ),
            spectrum,
        )["distance"]
    except ValueError:
        d = 1.0
    return c + (d / SPECTRUM_SIGMA) ** 2, {
        "cameras": cams,
        "pointing_chi2": c,
        "projection": k,
        "spectrum_distance": d,
    }


def fit(
    spectrum,
    train: dict,
    held_out: dict,
    source,
    machine_state: dict,
    names=FIT_NAMES,
    projection: str = "spectrometer",
    bounds: dict | None = None,
    max_evaluations: int = 400,
    restarts: int = 2,
    num_particles: int = 30_000,
    log=None,
) -> JointFit:
    """Fit `names` to `spectrum` (`compare.measured` of Scan016) and `train` (pointing scans,
    `pointing.measured`), then predict `held_out`.

    Args:
        spectrum: Scan016's measured spectrum, or None to fit the pointing scans alone.
        train: the pointing scans fitted, by name.
        held_out: the pointing scans predicted, by name (may be empty).
        source: the `LPASource` to start from.
        machine_state: twin machine-state keys set over every scan's (the fitted ones start
            from their values here, else the twin's defaults).
        names: the knobs to fit.
        projection: `pointing`'s projection.
        bounds, max_evaluations, restarts, log: as for `fit.minimize`.
        num_particles: particles per evaluation.
    """
    from htu_twin_apps.lpa_source import fit as lpa_fit, pointing

    s = dataclasses.replace(source, num_particles=num_particles)

    def _objective(v):
        f = lpa_fit.apply(s, machine_state, names, v)
        return evaluate(spectrum, train, *f, projection)[0]

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
    _, p = evaluate(spectrum, train, *f, projection)
    h = numpy.nan
    if held_out:
        h = pointing.residual_chi2(
            held_out,
            pointing.predict(f[0], held_out, f[1], projection=projection),
            p["projection"],
            p["cameras"],
        )
    return JointFit(
        evaluations=n,
        held_out_chi2=float(h),
        held_out_numbers=4 * sum(len(v) for v in held_out.values()),
        machine_state=f[1],
        names=tuple(names),
        objective=d,
        parts=p,
        source=dataclasses.replace(f[0], num_particles=source.num_particles),
        start_objective=_objective(x0),
        training_numbers=4 * sum(len(v) for v in train.values()) + (spectrum is not None),
        values=dict(zip(names, map(float, x))),
    )
