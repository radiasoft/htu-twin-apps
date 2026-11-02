"""Fit LPA source knobs (and twin machine settings) to a measured spectrum.

The objective is `compare.compare()`'s `distance` between the transported source's spectrum and
the measured one. It is minimized with Nelder-Mead (scipy), which needs no gradients: Cheetah's
apertures kill particles with a step function, so the tracking is not usefully differentiable.
Every evaluation samples the source with the same seed, so a knob's change moves the same
particles and the objective does not jitter from one evaluation to the next; the result still
carries the sampling noise of one seed (about 0.005 in `distance` at 50,000 particles), which
`check()` measures.

:copyright: Copyright (c) 2026 RadiaSoft LLC.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""

from __future__ import annotations

import dataclasses
import functools
import numpy

# Bounds for the knobs most often fitted: the ranges inside which the sampling stays physical.
# The EMQ scales may be negative: a negative scale reverses the EMQ's polarity.
DEFAULT_BOUNDS = {
    "aline_um_per_px": (50.0, 500.0),
    "chicane_jaw1_mm": (-20.0, 20.0),
    "chicane_jaw2_mm": (-20.0, 20.0),
    "divergence_power": (0.0, 3.0),
    "divergence_x_mrad": (0.05, 40.0),
    "divergence_y_mrad": (0.05, 40.0),
    "emq1_scale": (-1.5, 1.5),
    "emq1_x_mm": (-5.0, 5.0),
    "emq1_y_mm": (-5.0, 5.0),
    "emq2_scale": (-1.5, 1.5),
    "emq2_x_mm": (-5.0, 5.0),
    "emq2_y_mm": (-5.0, 5.0),
    "emq3_scale": (-1.5, 1.5),
    "energy_mev": (20.0, 150.0),
    "energy_sigma_mev": (0.5, 80.0),
    "energy_tail_mev": (1.0, 150.0),
    "magspec_b": (0.4, 1.2),
    "pmq_x_mm": (-3.0, 3.0),
    "pmq_y_mm": (-3.0, 3.0),
    "pmq_z_mm": (-15.0, 15.0),
    "pointing_slope_x_mrad": (-30.0, 30.0),
    "pointing_slope_y_mrad": (-30.0, 30.0),
    "pointing_x_mrad": (-10.0, 10.0),
    "pointing_y_mrad": (-10.0, 10.0),
    "s1h_scale": (-2.0, 2.0),
    "slit_blade_high_mm": (-20.0, 20.0),
    "slit_blade_low_mm": (-20.0, 20.0),
}
# The reference energy [MeV] the line is built at for every evaluation, so it is built once.
REFERENCE_MEV = 100.0
# The smallest improvement in distance for which Nelder-Mead starts again.
RESTART_GAIN = 1e-3


@dataclasses.dataclass
class Fit:
    """A fit's result: the fitted source and machine state, and how they compare."""

    comparison: dict
    evaluations: int
    machine_state: dict
    names: tuple
    source: object
    start_distance: float


def apply(source, machine_state: dict, names, values) -> tuple:
    """(source, machine state) with the knobs `names` set to `values`: `LPASource` fields on
    the source, the rest (twin machine-state keys) on the machine state."""
    s = {f.name for f in dataclasses.fields(source)}
    v = dict(zip(names, map(float, values)))
    return (
        dataclasses.replace(source, **{k: w for k, w in v.items() if k in s}),
        {**machine_state, **{k: w for k, w in v.items() if k not in s}},
    )


def check(fit: Fit, measured, seeds=(2, 3, 4, 5)) -> numpy.ndarray:
    """The fitted source's `distance` resampled with other seeds: its sampling noise."""
    return numpy.array(
        [
            _distance(dataclasses.replace(fit.source, seed=s), fit.machine_state, measured)
            for s in seeds
        ]
    )


def fit(
    measured,
    source,
    names,
    machine_state: dict,
    bounds: dict | None = None,
    max_evaluations: int = 400,
    restarts: int = 4,
    log=None,
) -> Fit:
    """Fit the knobs `names` of `source` (an `LPASource`) and of `machine_state` to `measured`.

    Args:
        measured: a `compare.Measured`.
        source: the `LPASource` to start from; its other knobs stay fixed.
        names: the knobs to fit: `LPASource` fields or twin machine-state keys.
        machine_state: the twin's machine state (such as `twin.SCAN016_STATE`); fitted keys
            start from its values, or the twin's defaults.
        bounds: (low, high) per name; DEFAULT_BOUNDS if None. A name without one is unbounded.
        max_evaluations: Nelder-Mead's evaluation budget, per start.
        restarts: how many more times Nelder-Mead starts again, with a fresh simplex, from where
            it stopped, while that improves the distance by more than RESTART_GAIN. The
            objective is flat in places (the spectrum is binned), so one simplex can collapse
            before the minimum.
        log: called after every evaluation with (evaluation number, distance, {name: value}).
    """
    x, _, n = minimize(
        lambda v: _distance(*apply(source, machine_state, names, v), measured),
        knobs(source, machine_state, names),
        names,
        bounds=bounds,
        max_evaluations=max_evaluations,
        restarts=restarts,
        log=log,
    )
    f = apply(source, machine_state, names, x)
    return Fit(
        comparison=_compare(*f, measured),
        evaluations=n,
        machine_state=f[1],
        names=tuple(names),
        source=f[0],
        start_distance=_distance(source, machine_state, measured),
    )


def knobs(source, machine_state: dict, names) -> numpy.ndarray:
    """The current values of the knobs `names`: `LPASource` fields, or twin machine-state keys
    (from `machine_state`, else the twin's defaults)."""
    import htu.model

    s = {f.name for f in dataclasses.fields(source)}
    m = {**htu.model.DEFAULT_MACHINE_STATE, **machine_state}
    u = [n for n in names if n not in s and n not in m]
    if u:
        raise KeyError(f"not LPASource knobs or twin machine-state keys: {u}")
    return numpy.array([getattr(source, n) if n in s else m[n] for n in names], dtype=float)


def minimize(
    objective,
    x0,
    names,
    bounds: dict | None = None,
    max_evaluations: int = 400,
    restarts: int = 4,
    gain: float = RESTART_GAIN,
    log=None,
) -> tuple:
    """(values, objective, evaluations) of Nelder-Mead on `objective` from `x0`, restarted.

    Nelder-Mead starts again, with a fresh simplex, from where it stopped, up to `restarts`
    more times while that lowers the objective by more than `gain`.

    Args:
        objective: called with the knobs' values (an array, in `names`' order).
        x0: the start.
        names: the knobs, for `bounds` and `log`.
        bounds: (low, high) per name; DEFAULT_BOUNDS if None. A name without one is unbounded.
        max_evaluations: the evaluation budget, per start.
        restarts: the most restarts.
        gain: the smallest improvement for which Nelder-Mead starts again.
        log: called after every evaluation with (evaluation number, objective, {name: value}).
    """
    import scipy.optimize

    n = [0]

    def _objective(v):
        rv = float(objective(v))
        n[0] += 1
        if log:
            log(n[0], rv, dict(zip(names, map(float, v))))
        return rv

    x = numpy.asarray(x0, dtype=float)
    d = _objective(x)
    for _ in range(restarts + 1):
        r = scipy.optimize.minimize(
            _objective,
            x,
            method="Nelder-Mead",
            bounds=[
                (DEFAULT_BOUNDS if bounds is None else bounds).get(k, (None, None))
                for k in names
            ],
            options={
                "maxfev": max_evaluations,
                "initial_simplex": _simplex(x),
                "xatol": 1e-3,
                "fatol": 1e-4,
            },
        )
        if r.fun > d - gain:
            if r.fun < d:
                x, d = r.x, float(r.fun)
            break
        x, d = r.x, float(r.fun)
    return x, d, n[0]


def pool(workers: int, threads: int):
    """A process pool for tracking steps in parallel, each worker with `threads` torch threads.

    Workers are started by a fork server: workers forked from a parent that has used torch's
    threads can deadlock.
    """
    import concurrent.futures
    import multiprocessing

    return concurrent.futures.ProcessPoolExecutor(
        max_workers=workers,
        mp_context=multiprocessing.get_context("forkserver"),
        initializer=_init_worker,
        initargs=(threads,),
    )


def sampled(source):
    """`source`'s particles (an `LPASource`), sampled once per process for repeated calls."""
    return _sampled(tuple(sorted(dataclasses.asdict(source).items())))


def _compare(source, machine_state: dict, measured) -> dict:
    from htu_twin_apps.lpa_source import compare, source as lpa_source, twin

    return compare.compare(
        twin.to_spectrometer(
            lpa_source.particles(source), machine_state, reference_mev=REFERENCE_MEV
        ),
        measured,
    )


def _distance(source, machine_state: dict, measured) -> float:
    """The objective; a source with no charge in the window is as far as it gets (1)."""
    try:
        return _compare(source, machine_state, measured)["distance"]
    except ValueError:
        return 1.0


def _init_worker(threads: int) -> None:
    import torch

    torch.set_num_threads(threads)


@functools.lru_cache(maxsize=2)
def _sampled(key: tuple):
    from htu_twin_apps.lpa_source import source

    return source.particles(source.LPASource(**dict(key)))


def _simplex(x0: numpy.ndarray) -> numpy.ndarray:
    """Nelder-Mead's first simplex: each knob stepped by 20% (by 1 if it is 0)."""
    rv = numpy.tile(x0, (x0.size + 1, 1))
    for i, v in enumerate(x0):
        rv[i + 1, i] = v * 1.2 if v != 0 else 1.0
    return rv
