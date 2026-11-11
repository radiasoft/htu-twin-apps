"""An adjustable LPA electron source, as an openPMD `ParticleGroup` at the plasma exit.

The source is a handful of knobs (`LPASource`) sampled into particles:

- energy: an exponentially modified Gaussian, a Gaussian peak (`energy_mev`,
  `energy_sigma_mev`) with an exponential high-energy tail (`energy_tail_mev`): a particle's
  energy is the sum of a normal and an exponential deviate. Particles below `energy_min_mev` are
  dropped (fbpic's analysis keeps `uz > 30`, about 15 MeV).
- per plane, a waist at the plasma exit (no position-angle correlation) with an rms size and an
  rms divergence that scales with energy as `(E / reference_mev) ** -divergence_power`.
- per plane, a pointing angle that varies linearly with energy: `pointing_<p>_mrad` at
  `reference_mev`, plus `pointing_slope_<p>_mrad` per unit of `E / reference_mev - 1`.
- the bunch duration (rms) and the charge.

`from_nersc()` sets the knobs from one run of the NERSC `initial_sample` dataset (its moments,
not particles), so that a run can start the source. `from_fbpic()` reads an fbpic run's particles
instead, for use in place of the knobs.

:copyright: Copyright (c) 2026 RadiaSoft LLC.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""

from __future__ import annotations

import dataclasses
import json
import math
import numpy
import pathlib

# The speed of light [m/s] and the electron's charge [C].
C = 299792458.0
E_CHARGE = 1.602176634e-19
ELECTRON_MASS_MEV = 0.51099895
# fbpic's analysis selection: electrons with uz above 30 (about 15 MeV)
NERSC_UZ_MIN = 30.0


@dataclasses.dataclass
class LPASource:
    """The source's knobs. Energies in MeV, sizes in um, angles in mrad, duration in fs."""

    charge_pc: float = 30.0
    divergence_power: float = 1.0
    divergence_x_mrad: float = 10.0
    divergence_y_mrad: float = 6.0
    duration_fs: float = 5.0
    energy_mev: float = 88.0
    energy_min_mev: float = 15.0
    energy_sigma_mev: float = 6.0
    energy_tail_mev: float = 25.0
    num_particles: int = 50_000
    pointing_slope_x_mrad: float = 0.0
    pointing_slope_y_mrad: float = 0.0
    pointing_x_mrad: float = 0.0
    pointing_y_mrad: float = 0.0
    reference_mev: float = 100.0
    seed: int = 1
    size_x_um: float = 3.0
    size_y_um: float = 2.0


def from_fbpic(path: pathlib.Path, energy_min_mev: float = 15.0):
    """The electrons of an fbpic openPMD file (`data<iteration>.h5`, species `electrons`) above
    `energy_min_mev` and moving forward, as a `ParticleGroup` at the plasma exit as `particles()`
    makes one: fbpic saves every particle at one time, so each is drifted from its z to the
    bunch's mean z (straight, as in vacuum), its arrival time there becoming its `t`, and `z`
    set to 0."""
    import h5py
    import pmd_beamphysics

    with h5py.File(path, "r") as f:
        # POSIT: fbpic writes one iteration per file
        g = f[f"data/{next(iter(f['data']))}/particles/electrons"]

        def _si(name):
            return g[name][()] * g[name].attrs.get("unitSI", 1.0)

        x, y, z = (_si(f"position/{c}") for c in "xyz")
        # momenta in units of m_e c
        u = [
            _si(f"momentum/{c}") / (ELECTRON_MASS_MEV * 1e6 * E_CHARGE / C)
            for c in "xyz"
        ]
        w = _si("weighting")
    gamma = numpy.sqrt(1.0 + u[0] ** 2 + u[1] ** 2 + u[2] ** 2)
    k = ((gamma - 1.0) * ELECTRON_MASS_MEV > energy_min_mev) & (u[2] > 0)
    if not k.any():
        raise ValueError(f"no electrons above {energy_min_mev} MeV in {path}")
    d = numpy.average(z[k], weights=w[k]) - z[k]
    t = d / (u[2][k] / gamma[k] * C)
    return pmd_beamphysics.ParticleGroup(
        data={
            "x": x[k] + u[0][k] / u[2][k] * d,
            "y": y[k] + u[1][k] / u[2][k] * d,
            "z": numpy.zeros(k.sum()),
            "px": u[0][k] * ELECTRON_MASS_MEV * 1e6,
            "py": u[1][k] * ELECTRON_MASS_MEV * 1e6,
            "pz": u[2][k] * ELECTRON_MASS_MEV * 1e6,
            "t": t - numpy.average(t, weights=w[k]),
            "status": numpy.ones(k.sum(), dtype=int),
            "weight": w[k] * E_CHARGE,
            "species": "electron",
        }
    )


def from_nersc(dataset: pathlib.Path, run: str, **overrides) -> LPASource:
    """The knobs matching one run of the NERSC `initial_sample` dataset (`sample_dataset.json`).

    The run's outputs are moments of the electrons with `uz > 30`: means, the 6x6 covariance of
    (x, ux, y, uy, z, uz) and the charge. Mapped as:

    - energy: the mean and rms of `uz` split evenly between the peak and the tail
      (`energy_sigma_mev = energy_tail_mev = rms / sqrt(2)`, `energy_mev = mean - tail`), so the
      source has the run's mean and rms energy; the split itself is a choice, not in the data.
    - divergence: `sqrt(cov_u<p>_u<p>) / mean_uz` at the mean energy, scaled to
      `reference_mev` with `divergence_power` 1 (a transverse momentum spread that does not
      depend on energy).
    - size: `sqrt(cov_<p>_<p>)`; the position-angle correlation is dropped (a waist).
    - pointing: the mean angle, and its slope with energy from `cov_u<p>_uz / cov_uz_uz`.
    - duration: `sqrt(cov_z_z) / c`.

    Args:
        dataset: the dataset's `sample_dataset.json`.
        run: the run's name, such as `sim_0000`.
        overrides: knobs to set after the mapping.
    """
    o = json.loads(pathlib.Path(dataset).read_text())["runs"][run]["output"]
    u = o["mean_uz"]
    r = math.sqrt(o["cov_uz_uz"]) * ELECTRON_MASS_MEV
    s = LPASource()
    t = r / math.sqrt(2.0)
    rv = dict(
        charge_pc=o["total_beam_charge_pc"],
        divergence_power=1.0,
        duration_fs=math.sqrt(o["cov_z_z"]) / 299_792_458.0 * 1e15,
        energy_mev=u * ELECTRON_MASS_MEV - t,
        energy_min_mev=NERSC_UZ_MIN * ELECTRON_MASS_MEV,
        energy_sigma_mev=t,
        energy_tail_mev=t,
    )
    for p in ("x", "y"):
        rv[f"divergence_{p}_mrad"] = (
            math.sqrt(o[f"cov_u{p}_u{p}"])
            / u
            * 1e3
            * (u * ELECTRON_MASS_MEV / s.reference_mev)
        )
        rv[f"pointing_{p}_mrad"] = o[f"mean_u{p}"] / u * 1e3
        # d(angle)/d(E/reference) = (d u<p> / d uz) * reference / E_mean
        rv[f"pointing_slope_{p}_mrad"] = (
            o[f"cov_u{p}_uz"]
            / o["cov_uz_uz"]
            * 1e3
            * s.reference_mev
            / (u * ELECTRON_MASS_MEV)
        )
        rv[f"size_{p}_um"] = math.sqrt(o[f"cov_{p}_{p}"]) * 1e6
    return dataclasses.replace(s, **{**rv, **overrides})


def particles(source: LPASource):
    """The source sampled into a `ParticleGroup` at the plasma exit (`z = 0`, `t` per particle).

    Every particle has the same weight; their sum is `charge_pc`. Fewer than `num_particles`
    remain when some fall below `energy_min_mev`.
    """
    import pmd_beamphysics

    g = numpy.random.default_rng(source.seed)
    e = _energies(source, g)
    n = e.size
    v = {"t": g.normal(0.0, source.duration_fs * 1e-15, n)}
    p = numpy.sqrt(e**2 - ELECTRON_MASS_MEV**2) * 1e6
    a = {}
    for x in ("x", "y"):
        a[x] = _angles(source, x, e, g)
        v[x] = g.normal(0.0, getattr(source, f"size_{x}_um") * 1e-6, n)
    v["pz"] = p / numpy.sqrt(1.0 + a["x"] ** 2 + a["y"] ** 2)
    v["px"] = v["pz"] * a["x"]
    v["py"] = v["pz"] * a["y"]
    return pmd_beamphysics.ParticleGroup(
        data={
            **v,
            "z": numpy.zeros(n),
            "status": numpy.ones(n, dtype=int),
            "weight": numpy.full(n, source.charge_pc * 1e-12 / n),
            "species": "electron",
        }
    )


def _angles(source: LPASource, plane: str, energies, generator):
    """Each particle's angle [rad] in `plane`: pointing (with its energy slope) plus divergence."""
    r = energies / source.reference_mev
    return 1e-3 * (
        getattr(source, f"pointing_{plane}_mrad")
        + getattr(source, f"pointing_slope_{plane}_mrad") * (r - 1.0)
        + generator.normal(0.0, 1.0, energies.size)
        * getattr(source, f"divergence_{plane}_mrad")
        * r**-source.divergence_power
    )


def _energies(source: LPASource, generator):
    """Total energies [MeV] from the exponentially modified Gaussian, below the cut dropped."""
    n = int(source.num_particles)
    if n < 100:
        raise ValueError(f"num_particles={n} is too few for a spectrum")
    e = generator.normal(source.energy_mev, source.energy_sigma_mev, n)
    if source.energy_tail_mev > 0:
        e += generator.exponential(source.energy_tail_mev, n)
    e = e[e > max(source.energy_min_mev, 2 * ELECTRON_MASS_MEV)]
    if e.size < 100:
        raise ValueError(
            f"only {e.size} particles above energy_min_mev={source.energy_min_mev}"
        )
    return e
