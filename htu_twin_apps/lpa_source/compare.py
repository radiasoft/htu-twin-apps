"""Compare LPA sources, tracked through the HTU twin, with a spectrometer scan's measured spectrum.

Run `htu-lpa-source <day> [--root DIR]` (a day name such as `26_0929`, or a day folder's path) to track the twin's default Gaussian source, sources made
from NERSC `initial_sample` runs (`--nersc`) and the `LPASource` defaults to the spectrometer
entrance with Scan016's settings, and compare each with Scan016's measured spectrum. With
`--fit`, the knobs named are also fitted to the measurement (`fit.fit`), starting from a source
saved earlier (`--source`), the first NERSC run, or the `LPASource` defaults, in that order, and
the fitted source is compared too. With `--pointing`, the fitted (or saved) source's vertical
pointing and divergence and the PMQ triplet's vertical offset are then fitted to the
spectrometer's EMQ scans (`pointing.fit`). `--save` writes the last fitted source, with the twin
machine state it was fitted with, as JSON for `--source`.

The comparison is in energy, where HTU's spectrometer analysis already is (the stitched
`-interpSpec` spectra, in MeV), so neither the spectrometer's field nor the twin's screen map
enters. Both spectra are normalized over the spectrometer's energy window, so the shapes are
compared, not the charge; the charge's units on the HTU side are not known.

:copyright: Copyright (c) 2026 RadiaSoft LLC.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import h5py
import json
import numpy
import pathlib
import time

from htu_twin_apps import days
from htu_twin_apps.lpa_source import scans as htu_scans

# The stitched spectrometer analysis (GEECS ScanAnalysis `UC_BCaveMagSpecStitcher`) of a scan.
AVERAGE_SPECTRUM = (
    "analysis/Scan{scan:03d}/UC_BCaveMagSpecStitcher/Array1DScanAnalyzer/"
    + "UC_BCaveMagSpecCam1_average_processed.h5"
)
# The comparison's energy bin [MeV]: 8 of the -interpSpec spectra's 0.25 MeV steps, so that a
# few 10,000 tracked particles put about 100 in a bin of the spectrum's tail.
ENERGY_STEP_MEV = 2.0
# The -interpSpec spectra's energy step [MeV].
MEASURED_STEP_MEV = 0.25
SHOT_COLUMNS = ("UC_BCaveMagSpecStitcher_peak_location", "UC_BCaveMagSpecStitcher_CoM")


@dataclasses.dataclass
class Measured:
    """A scan's average spectrum on the comparison grid, and the spread of its shots."""

    density: numpy.ndarray
    energy_mev: numpy.ndarray
    scan: int
    shots: dict

    def stats(self) -> dict:
        return _stats(self.energy_mev, self.density)


def compare(transported, measured: Measured) -> dict:
    """How the transported source's spectrum compares with `measured`.

    Keys: `transmission` (fraction of the source charge at the spectrometer entrance),
    `in_window` (fraction of that inside the measured energy window), `peak_mev`, `mean_mev`,
    `rms_mev` of the predicted spectrum in the window, `distance` (half the integral of the
    absolute difference of the two normalized spectra: 0 identical, 1 disjoint), `yp_rms_mrad`
    (vertical angle spread at the entrance).
    """
    d, f = spectrum(transported, measured.energy_mev)
    a = transported.charge_pc > 0
    return {
        "transmission": transported.transmission(),
        "in_window": f,
        **_stats(measured.energy_mev, d),
        "distance": 0.5
        * float(numpy.abs(d - measured.density).sum() * ENERGY_STEP_MEV),
        "yp_rms_mrad": float(
            numpy.sqrt(
                numpy.cov(transported.yp_mrad[a], aweights=transported.charge_pc[a])
            )
        ),
    }


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument(
        "data",
        nargs="?",
        type=pathlib.Path,
        help="the day to read, a name such as 26_0929 (with --root) or a day folder's path "
        + "(see htu_twin_apps.days)",
    )
    p.add_argument(
        "--root",
        type=pathlib.Path,
        help="the data root, the folder holding Y2026",
    )
    p.add_argument(
        "--aline",
        action="store_true",
        help="fit the beam's path to the A-line camera's EMQ scans (023, 026) and Scan019 "
        + "jointly (needs --fit or --source; many hours)",
    )
    p.add_argument(
        "--aline-knobs",
        help="the A-line fit's knobs, comma-separated (default: aline.FIT_NAMES)",
    )
    p.add_argument(
        "--joint",
        action="store_true",
        help="fit the source jointly to Scan016's spectrum and Scans 025 and 028's vertical "
        + "profiles, predicting Scan030 (needs --fit or --source; many hours)",
    )
    p.add_argument(
        "--joint-held-out",
        help="the joint fit's held-out pointing scans, comma-separated, or none "
        + "(default: Scan030)",
    )
    p.add_argument(
        "--joint-knobs",
        help="the joint fit's knobs, comma-separated (default: joint.FIT_NAMES); may include "
        + "magspec_b and emq1_scale, emq2_scale, emq3_scale (which start at 1)",
    )
    p.add_argument(
        "--joint-no-spectrum",
        action="store_true",
        help="leave Scan016's spectrum out of the joint fit: the pointing scans alone",
    )
    p.add_argument(
        "--joint-train",
        help="the joint fit's training pointing scans, comma-separated "
        + "(default: Scan025,Scan028)",
    )
    p.add_argument(
        "--log",
        type=pathlib.Path,
        help="append every fit evaluation to this file, one JSON object a line",
    )
    p.add_argument("--nersc", type=pathlib.Path, help="the NERSC sample_dataset.json")
    p.add_argument(
        "--runs",
        default="sim_0000,sim_0003,sim_0004",
        help="the NERSC runs to start sources from (default: the nominal ones)",
    )
    p.add_argument(
        "--energy-reference",
        choices=("early", "late"),
        default="early",
        help="the spectrometer driver's field setting taken as right for every scan's energy "
        + "axis: early (Scans 014 to 020's; default) or late (Scan025's): "
        + "scans.CAM1_AXIS_START_MEV, scans.LATE_CAM1_AXIS_START_MEV",
    )
    p.add_argument(
        "--fit",
        help="comma-separated knobs to fit (LPASource fields or twin machine-state keys), "
        + "such as energy_mev,energy_sigma_mev,energy_tail_mev,divergence_x_mrad,"
        + "divergence_y_mrad,divergence_power",
    )
    p.add_argument(
        "--out",
        type=pathlib.Path,
        default=pathlib.Path("lpa_source_compare.png"),
        help="the plot; the pointing fit's goes next to it, with _pointing added to the name",
    )
    p.add_argument("--particles", type=int, default=50_000)
    p.add_argument(
        "--profiles",
        action="store_true",
        help="fit the vertical optics to the spectrometer EMQ scans' energy-resolved vertical "
        + "profiles (ImageInterp; needs --fit or --source; many hours)",
    )
    p.add_argument(
        "--profiles-spectrum",
        action="store_true",
        help="add Scan016's spectrum to the profile fit's objective (energy_profiles.fit)",
    )
    p.add_argument(
        "--profiles-knobs",
        help="the energy-resolved profile fit's knobs, comma-separated "
        + "(default: energy_profiles.FIT_NAMES)",
    )
    p.add_argument(
        "--pointing",
        action="store_true",
        help="fit vertical pointing to the spectrometer EMQ scans (needs --fit or --source; "
        + "an hour or more)",
    )
    p.add_argument(
        "--pointing-projection",
        choices=("spectrometer", "stand-in"),
        default="spectrometer",
        help="how the pointing fit predicts the vertical profiles: through the twin's model of "
        + "the spectrometer (default), or the older y + d y' stand-in",
    )
    p.add_argument(
        "--save", type=pathlib.Path, help="write the last fitted source as JSON"
    )
    p.add_argument(
        "--slit",
        choices=("jaws", "blade", "jaws_blade"),
        help="fit the chicane slit (as jaws, a blade, or jaws and a blade), the horizontal beam and the PMQs' z to "
        + "Scan019 (needs --fit or --source; hours)",
    )
    p.add_argument(
        "--slit-knobs",
        help="the slit fit's knobs, comma-separated (default: slit.FIT_NAMES; a blade's edges "
        + "are added for jaws_blade)",
    )
    p.add_argument("--source", type=pathlib.Path, help="a source saved with --save")
    p.add_argument(
        "--workers",
        type=int,
        default=5,
        help="worker processes for the A-line fit, each with --threads torch threads (default: 5)",
    )
    p.add_argument(
        "--threads",
        type=int,
        default=4,
        help="torch threads; torch's default (every core) is far slower here (default: 4)",
    )
    a = p.parse_args()
    if a.data is None:
        p.error("give the day, such as 26_0929 with --root, or a day folder's path")
    try:
        a.data = days.folder(a.data, a.root)
    except (FileNotFoundError, ValueError) as e:
        p.error(str(e))
    if (a.aline or a.pointing or a.profiles or a.slit or a.joint) and not (
        a.fit or a.source
    ):
        p.error(
            "--aline, --pointing, --profiles, --slit and --joint need a source to start from: "
            + "--fit or --source"
        )
    import torch

    torch.set_num_threads(a.threads)
    a.axis_start_mev = (
        htu_scans.LATE_CAM1_AXIS_START_MEV
        if a.energy_reference == "late"
        else htu_scans.CAM1_AXIS_START_MEV
    )
    # Scan016's spectrum is on the early setting
    m = measured(a.data, 16, a.axis_start_mev / htu_scans.CAM1_AXIS_START_MEV)
    s = _sources(a)
    r = _run(s, m)
    f = _load(a.source) if a.source else None
    if a.fit:
        n, v, f = _fit(a, s, m)
        r[n] = v
    if a.pointing:
        f = _pointing(a, f)
        r["after the pointing fit"] = _run({"": (_particles(f[0]), *f)}, m)[""]
    if a.slit:
        f = _slit(a, f)
        r[f"after the {a.slit} slit fit"] = _run({"": (_particles(f[0]), *f)}, m)[""]
    if a.aline:
        f = _aline(a, f)
        r["after the A-line fit"] = _run({"": (_particles(f[0]), *f)}, m)[""]
    if a.profiles:
        f = _profiles(a, f, m)
        r["after the profile fit"] = _run({"": (_particles(f[0]), *f)}, m)[""]
    if a.joint:
        f = _joint(a, f, m)
        r["after the joint fit"] = _run({"": (_particles(f[0]), *f)}, m)[""]
    print(_table(m, r))
    _plot(m, r, a.out)
    print(f"plot: {a.out}")
    if a.save and f:
        a.save.write_text(
            json.dumps(
                {"source": dataclasses.asdict(f[0]), "machine_state": f[1]}, indent=1
            )
        )
        print(f"saved: {a.save}")


def measured(data: pathlib.Path, scan: int, axis_scale: float = 1.0) -> Measured:
    """Scan `scan`'s average stitched spectrum, below `data`, in ENERGY_STEP_MEV bins, normalized.

    The stitched spectrum is interpolated onto its own MEASURED_STEP_MEV grid (the two cameras'
    samples interleave where they overlap) and averaged over each bin; a partial last bin is
    dropped. `axis_scale` multiplies its energy axis first: a test of the camera driver's field
    setting (`scans.CAM1_AXIS_START_MEV`).
    """
    f = _one(data, AVERAGE_SPECTRUM.format(scan=scan))
    with h5py.File(f, "r") as h:
        x, y = h["data"][()].astype(float).T
    x = x * axis_scale
    k = round(ENERGY_STEP_MEV / MEASURED_STEP_MEV)
    e = numpy.arange(x.min(), x.max(), MEASURED_STEP_MEV)
    e = e[: e.size // k * k]
    d = numpy.clip(numpy.interp(e, x, y), 0.0, None).reshape(-1, k).mean(axis=1)
    return Measured(
        density=d / (d.sum() * ENERGY_STEP_MEV),
        energy_mev=e.reshape(-1, k).mean(axis=1),
        scan=scan,
        shots=_shots(f.parents[3] / f"s{scan}.txt"),
    )


def spectrum(transported, energy_mev: numpy.ndarray) -> tuple[numpy.ndarray, float]:
    """The transported charge's density on the grid `energy_mev`, normalized over the grid, and
    the fraction of the transported charge that falls on the grid."""
    e = numpy.append(
        energy_mev - ENERGY_STEP_MEV / 2, energy_mev[-1] + ENERGY_STEP_MEV / 2
    )
    h, _ = numpy.histogram(
        transported.energy_mev, bins=e, weights=transported.charge_pc
    )
    s = h.sum()
    if s <= 0:
        raise ValueError("no transported charge in the spectrometer's energy window")
    return h / (s * ENERGY_STEP_MEV), float(s / transported.charge_pc.sum())


def _aline(args, start: tuple) -> tuple:
    """The A-line and Scan019 fit from `start` (LPASource, machine state); prints it, and returns
    the source and machine state it ends with."""
    from htu_twin_apps.lpa_source import aline, slit, twin

    n = args.aline_knobs.split(",") if args.aline_knobs else aline.FIT_NAMES
    f = aline.fit(
        slit.measured(args.data, axis_start_mev=args.axis_start_mev),
        {x: aline.measured(args.data, x, args.axis_start_mev) for x in aline.PAIRS},
        start[0],
        {
            **slit.SLIT_STARTS["jaws_blade"],
            **{x: 1.0 for x in twin.SCALES.values() if x in n},
            **{x: 0.0 for v in twin.OFFSETS.values() for x in v if x in n},
            **(
                {aline.PIXEL_KEY: aline.DEFAULT_UM_PER_PX}
                if aline.PIXEL_KEY in n
                else {}
            ),
            **start[1],
        },
        names=n,
        workers=args.workers,
        threads=args.threads,
        log=_logger(args.log, "aline"),
    )
    p = f.parts
    print(
        f"A-line fit ({', '.join(aline.PAIRS)} and {slit.SCAN}; {f.evaluations} evaluations): "
        + f"objective {f.start_objective:.0f} -> {f.objective:.0f}: A-line chi2 "
        + f"{p['aline_chi2']:.0f} over {p['aline_numbers']} numbers, {slit.SCAN} mean distance "
        + f"{p['slit_mean_distance']:.3f} (chi2 {p['slit_chi2']:.0f})\n  camera: {p['camera']}\n  "
        + ", ".join(f"{k} = {v:.4g}" for k, v in f.values.items())
        + "\n"
    )
    return f.source, f.machine_state


def _fit(args, sources: dict, measured: Measured) -> tuple:
    """(label, the fitted source as `_run` gives each source, (LPASource, machine state)).

    Starts from the first source with knobs (`_sources` puts a saved one first), with its saved
    machine state over Scan016's, the slit out; prints the fitted knobs. The returned machine
    state keeps the saved one's slit keys.
    """
    from htu_twin_apps.lpa_source import fit, twin

    n, (_, s, m) = next((k, v) for k, v in sources.items() if v[1] is not None)
    f = fit.fit(
        measured, s, args.fit.split(","), {**twin.SCAN016_STATE, **twin.without_slit(m)}
    )
    c = fit.check(f, measured)
    v = {**dataclasses.asdict(f.source), **f.machine_state}
    print(
        f"fit from {n}: distance {f.start_distance:.3f} -> {f.comparison['distance']:.3f} "
        + f"({f.evaluations} evaluations; other seeds {c.mean():.3f} +- {c.std():.3f})\n  "
        + ", ".join(f"{k} = {v[k]:.4g}" for k in f.names)
        + "\n"
    )
    # the fitted state, less Scan016's own settings: what a later scan's settings go under
    k = {
        **m,
        **{x: y for x, y in f.machine_state.items() if x not in twin.SCAN016_STATE},
    }
    return (
        f"fitted from {n}",
        _run({"": (_particles(f.source), f.source, k)}, measured)[""],
        (f.source, k),
    )


def _joint(args, start: tuple, spectrum: Measured) -> tuple:
    """The joint fit from `start` (LPASource, machine state); prints it, and returns the source
    and machine state it ends with."""
    from htu_twin_apps.lpa_source import joint, pointing, twin

    def _scans(value, default):
        return () if value == "none" else value.split(",") if value else default

    t = _scans(args.joint_train, joint.TRAIN)
    h = _scans(args.joint_held_out, joint.HELD_OUT)
    n = args.joint_knobs.split(",") if args.joint_knobs else joint.FIT_NAMES
    d = None if args.joint_no_spectrum else spectrum
    f = joint.fit(
        d,
        {x: pointing.measured(args.data, x, args.axis_start_mev) for x in t},
        {x: pointing.measured(args.data, x, args.axis_start_mev) for x in h},
        start[0],
        {
            **{x: 1.0 for x in twin.SCALES.values() if x in n},
            **{x: 0.0 for v in twin.OFFSETS.values() for x in v if x in n},
            **start[1],
        },
        names=n,
        projection=args.pointing_projection,
        log=_logger(args.log, "joint"),
    )
    print(
        f"joint fit ({'' if d is None else 'Scan016 and '}{', '.join(t)}; "
        + f"{f.evaluations} evaluations): objective {f.start_objective:.0f} -> "
        + f"{f.objective:.0f}: Scan016 distance "
        + ("not fitted" if d is None else f"{f.parts['spectrum_distance']:.3f}")
        + f", pointing chi2 {f.parts['pointing_chi2']:.0f} over "
        + f"{f.training_numbers - (d is not None)} numbers\n  per camera (chi2, scale, zero, "
        + "floor): "
        + "; ".join(
            f"{c} {', '.join(f'{x:.3g}' for x in y)}"
            for c, y in f.parts["cameras"].items()
        )
        + f"\n  held out ({', '.join(h) or 'none'}): chi2 {f.held_out_chi2:.0f} over "
        + f"{f.held_out_numbers} numbers, the training cameras fixed\n  "
        + ", ".join(f"{k} = {v:.4g}" for k, v in f.values.items())
        + "\n"
    )
    return f.source, f.machine_state


def _load(path: pathlib.Path) -> tuple:
    """(LPASource, machine state) saved with --save."""
    from htu_twin_apps.lpa_source import source

    d = json.loads(path.read_text())
    return source.LPASource(**d["source"]), d.get("machine_state", {})


def _logger(path: pathlib.Path | None, name: str):
    """A fit's `log` callback: every evaluation appended to `path` as JSON, every tenth printed."""

    def _log(n, value, values):
        if path:
            with open(path, "a") as f:
                f.write(
                    json.dumps(
                        {
                            "fit": name,
                            "n": n,
                            "value": value,
                            "values": values,
                            "time": time.time(),
                        }
                    )
                    + "\n"
                )
        if n % 10 == 0:
            print(f"  {name} evaluation {n}: {value:.4g}", flush=True)

    return _log


def _one(data: pathlib.Path, pattern: str) -> pathlib.Path:
    f = sorted(pathlib.Path(data).glob(pattern))
    if len(f) != 1:
        raise FileNotFoundError(
            f"{len(f)} matches of {pattern} in the day folder {data}"
        )
    return f[0]


def _particles(source):
    from htu_twin_apps.lpa_source import source as lpa_source

    return lpa_source.particles(source)


def _plot(measured: Measured, results: dict, path: pathlib.Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot

    f, x = matplotlib.pyplot.subplots(figsize=(9, 5))
    for n, (r, d, _) in results.items():
        x.step(
            measured.energy_mev,
            d,
            where="mid",
            lw=2.5 if n.startswith("fitted") else 1.0,
            zorder=9 if n.startswith("fitted") else 2,
            label=f"{n} (distance {r['distance']:.2f})",
        )
    x.plot(
        measured.energy_mev,
        measured.density,
        color="black",
        lw=2.5,
        zorder=10,
        label=f"Scan{measured.scan:03d} measured (average)",
    )
    x.set_xlabel("energy (MeV)")
    x.set_ylabel("density in the window (1/MeV)")
    x.legend()
    f.savefig(path, dpi=100, bbox_inches="tight")


def _pointing(args, start: tuple) -> tuple:
    """The pointing fit from `start` (LPASource, machine state); prints and plots it, and
    returns the source and machine state it ends with."""
    from htu_twin_apps.lpa_source import pointing

    s = {
        n: pointing.measured(args.data, n, args.axis_start_mev) for n in pointing.SCANS
    }
    f = pointing.fit(
        s,
        start[0],
        start[1],
        projection=args.pointing_projection,
        log=_logger(args.log, "pointing"),
    )
    v = {**dataclasses.asdict(f.source), **f.machine_state}
    print(
        f"pointing fit ({', '.join(s)}, {f.measured_numbers} measured numbers): "
        + f"chi2 {f.chi2:.0f}, projection "
        + (f.projection if f.projection == "spectrometer" else f"y + {f.projection} y'")
        + f", {f.evaluations} evaluations\n  "
        + "\n  ".join(
            f"{k} = {v[k]:.4g} (rough 68% range {f.ranges[k][0]:.4g} to {f.ranges[k][1]:.4g})"
            for k in pointing.FIT_NAMES
        )
        + "\n  per camera (chi2, scale, zero, floor): "
        + "; ".join(
            f"{c} {', '.join(f'{x:.3g}' for x in y)}" for c, y in f.cameras.items()
        )
        + "\n"
    )
    p = args.out.with_name(args.out.stem + "_pointing" + args.out.suffix)
    pointing.plot(s, f, p)
    print(f"pointing plot: {p}")
    return f.source, f.machine_state


def _profiles(args, start: tuple, spectrum: Measured) -> tuple:
    """The energy-resolved vertical profile fit from `start` (LPASource, machine state), with
    Scan016's `spectrum` if --profiles-spectrum; prints it, and returns the source and machine
    state it ends with."""
    from htu_twin_apps.lpa_source import energy_profiles, twin

    n = (
        args.profiles_knobs.split(",")
        if args.profiles_knobs
        else energy_profiles.FIT_NAMES
    )
    s = {
        x: energy_profiles.measured(args.data, x, args.axis_start_mev)
        for x in energy_profiles.SCANS
    }
    f = energy_profiles.fit(
        s,
        start[0],
        {
            **{
                x: 1.0
                for x in (
                    *twin.SCALES.values(),
                    twin.PMQ_SCALE_KEY,
                    htu_scans.ENERGY_LABEL_KEY,
                )
                if x in n
            },
            **{x: 0.0 for v in twin.OFFSETS.values() for x in v if x in n},
            **start[1],
        },
        names=n,
        workers=args.workers,
        threads=args.threads,
        spectrum=spectrum if args.profiles_spectrum else None,
        log=_logger(args.log, "profiles"),
    )
    print(
        f"energy-resolved profile fit ({', '.join(s)}, {f.measured_numbers} measured numbers; "
        + f"{f.evaluations} evaluations): chi2 {f.start_chi2:.0f} -> {f.chi2:.0f}\n  "
        + "per camera (chi2, scale, zero, floor): "
        + "; ".join(
            f"{c} {', '.join(f'{x:.3g}' for x in y)}"
            for c, y in f.cameras.items()
            if isinstance(y, tuple)
        )
        + "".join(
            f"; {c} {y:.4g}" for c, y in f.cameras.items() if not isinstance(y, tuple)
        )
        + "\n  "
        + ", ".join(f"{k} = {v:.4g}" for k, v in f.values.items())
        + "\n"
    )
    return f.source, f.machine_state


def _run(sources: dict, measured: Measured) -> dict:
    """Each source tracked with Scan016's settings, and its own machine state over them, the
    slit out: (comparison, density, LPASource or None).

    The slit's keys are dropped: Scan016 logs no jaw positions, with the chicane off they cut
    nothing, and a blade's edges read as jaws would block the beam. So is the A-line camera's
    pixel size (`aline.PIXEL_KEY`), not a twin key.
    """
    from htu_twin_apps.lpa_source import aline, twin

    rv = {}
    for n, (g, s, m) in sources.items():
        k = {
            x: v
            for x, v in twin.without_slit(m).items()
            if x not in (aline.PIXEL_KEY, htu_scans.ENERGY_LABEL_KEY)
        }
        t = twin.to_spectrometer(g, {**twin.SCAN016_STATE, **k})
        rv[n] = (compare(t, measured), spectrum(t, measured.energy_mev)[0], s)
    return rv


def _shots(path: pathlib.Path) -> dict:
    """The 10th and 90th percentiles of the scan's per-shot spectrum peak and centroid."""
    with open(path, newline="") as f:
        r = list(csv.DictReader(f, delimiter="\t"))
    rv = {}
    for c in SHOT_COLUMNS:
        v = numpy.array([float(x[c]) for x in r if x.get(c) not in (None, "")])
        if v.size:
            rv[c] = numpy.percentile(v, [10, 90])
    return rv


def _slit(args, start: tuple) -> tuple:
    """The Scan019 slit fit from `start` (LPASource, machine state); prints and plots it, and
    returns the source and machine state it ends with."""
    from htu_twin_apps.lpa_source import slit

    s = slit.measured(args.data, axis_start_mev=args.axis_start_mev)
    m = {**slit.SLIT_STARTS[args.slit], **start[1]}
    f = slit.fit(
        s,
        start[0],
        m,
        names=args.slit_knobs.split(",") if args.slit_knobs else slit.FIT_NAMES,
        slit=args.slit,
        log=_logger(args.log, f"slit {args.slit}"),
    )
    print(
        f"slit fit ({slit.SCAN}, {len(s)} steps, {args.slit}; {f.evaluations} evaluations): "
        + f"mean distance {f.start_distance:.3f} -> {f.distance:.3f}\n  "
        + ", ".join(f"{k} = {v:.4g}" for k, v in f.values.items())
        + "\n  per step: "
        + " ".join(f"{d:.2f}" for d in f.distances)
        + "\n"
    )
    p = args.out.with_name(args.out.stem + f"_slit_{args.slit}" + args.out.suffix)
    slit.plot(s, f, p)
    print(f"slit plot: {p}")
    return f.source, f.machine_state


def _sources(args) -> dict:
    """The sources to compare, by label: (ParticleGroup, LPASource or None, machine state).

    A saved source (--source) comes first, with its own particle count and machine state.
    """
    import htu.source
    from htu_twin_apps.lpa_source import source

    n = args.particles
    rv = {}
    if args.source:
        s, m = _load(args.source)
        rv[f"saved {args.source.name}"] = (source.particles(s), s, m)
    rv["twin default Gaussian"] = (
        htu.source.make_beam(
            htu.source.SourceParams(num_particles=n)
        ).to_openpmd_particlegroup(),
        None,
        {},
    )
    for r in args.runs.split(",") if args.nersc else ():
        s = source.from_nersc(args.nersc, r, num_particles=n)
        rv[f"NERSC {r}"] = (source.particles(s), s, {})
    s = source.LPASource(num_particles=n)
    rv["LPASource defaults"] = (source.particles(s), s, {})
    return rv


def _stats(energy_mev: numpy.ndarray, density: numpy.ndarray) -> dict:
    w = density / density.sum()
    m = float((w * energy_mev).sum())
    return {
        "peak_mev": float(energy_mev[numpy.argmax(density)]),
        "mean_mev": m,
        "rms_mev": float(numpy.sqrt((w * (energy_mev - m) ** 2).sum())),
    }


def _table(measured: Measured, results: dict) -> str:
    s = measured.stats()
    p = measured.shots.get(SHOT_COLUMNS[0])
    c = measured.shots.get(SHOT_COLUMNS[1])
    rv = [
        f"Scan{measured.scan:03d} measured: peak {s['peak_mev']:.1f}, mean {s['mean_mev']:.1f}, "
        + f"rms {s['rms_mev']:.1f} MeV in {measured.energy_mev[0]:.1f}-"
        + f"{measured.energy_mev[-1]:.1f} MeV"
        + (f"; shots: peak {p[0]:.1f}-{p[1]:.1f}" if p is not None else "")
        + (
            f", centroid {c[0]:.1f}-{c[1]:.1f} (10th-90th percentile)"
            if c is not None
            else ""
        ),
        "",
        f"{'source':28s} {'transm':>7s} {'in win':>7s} {'peak':>7s} {'mean':>7s} {'rms':>7s} "
        + f"{'dist':>6s} {'yp rms':>7s}",
    ]
    for n, (r, _, _) in results.items():
        rv.append(
            f"{n:28s} {r['transmission']:7.3f} {r['in_window']:7.3f} {r['peak_mev']:7.1f} "
            + f"{r['mean_mev']:7.1f} {r['rms_mev']:7.1f} {r['distance']:6.3f} "
            + f"{r['yp_rms_mrad']:7.2f}"
        )
    return "\n".join(rv)


if __name__ == "__main__":
    main()
