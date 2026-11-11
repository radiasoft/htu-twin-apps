"""Rerun the whole chain that produced slit_a_rescore.json (see slit_a_rescore_provenance.md).

    python rerun_slit_a_rescore.py DATA NERSC_JSON OUT_DIR [--repo REPO] [--steps 1-17]

DATA is the htu-sample-data directory (holding Undulator/Y2026/09-Sep/26_0929), NERSC_JSON the FBPIC `sample_dataset.json` (the start of step
1), OUT_DIR where everything is written (use a new directory: the original fits are not touched).
Run from anywhere; `compare` runs with the repository root as its working directory. The result,
slit_a_rescore.json, is what `htu_twin_apps/twin_viewer/twin-fit-values.json` was copied from.

Each step skips itself if its output already exists in OUT_DIR, so an interrupted run resumes.
Each `compare` run's printed output goes to OUT_DIR/<name>.out, and every evaluation to
OUT_DIR/<name>.log. The whole chain takes days on the original machine (several fits of
600 to 1,100+ evaluations).

Steps (numbers as in the provenance document):
 1  Scan016 fit from the NERSC sample, hard-edged PMQs       fit_scan016_b.json
 2  wrap its "energy + divergence" source                    scan016_source.json
 3  refit Scan016 with the PMQ fringe                        scan016_fringe_source.json
 4  vertical pointing through the spectrometer               pointing_spectrometer_source.json
 5  joint fit                                                joint_source.json
 6  vertical scales                                          vertical_scales_source.json
 7  Scan019 slit as jaws                                     slit_jaws_source.json
 8  Scan019 slit as jaws plus blade                          slit_jaws_blade_source.json
 9  A-line start                                             aline_start_plus.json
10  A-line fit                                               aline_plus_source.json
11  A-line fit, EMQ offsets added                            aline_offsets_source.json
12  A-line fit, pixel size and vertical divergence added     aline_image_source.json
13  corrected-axis start                                     aline_axis_start.json
14  A-line fit on the corrected energy axis                  aline_axis_source.json
15  slit start                                               slit_a_start.json
16  slit refit                                               slit_a_source.json
17  A-line result with the refitted slit                     slit_a_rescore.json
"""

import argparse
import dataclasses
import json
import pathlib
import re
import subprocess
import sys
import time

from htu_twin_apps import days

# The day the chain fits.
DAY = "26_0929"

# the 15 knobs of the pixel-size A-line fits (steps 12 and 14)
ALINE_KNOBS = (
    "aline_um_per_px,emq1_x_mm,emq1_y_mm,emq2_x_mm,emq2_y_mm,pointing_x_mrad,"
    "pointing_slope_x_mrad,divergence_x_mrad,pointing_y_mrad,divergence_y_mrad,s1h_scale,pmq_x_mm,"
    "emq1_scale,emq2_scale,chicane_jaw1_mm"
)
# step 11's 13 knobs
ALINE_OFFSETS_KNOBS = (
    "emq1_x_mm,emq1_y_mm,emq2_x_mm,emq2_y_mm,pointing_x_mrad,pointing_slope_x_mrad,"
    "divergence_x_mrad,pointing_y_mrad,s1h_scale,pmq_x_mm,emq1_scale,emq2_scale,chicane_jaw1_mm"
)
# bounds of the step 1 fit
SCAN016_BOUNDS = {
    "energy_mev": (20, 150),
    "energy_sigma_mev": (0.5, 80),
    "energy_tail_mev": (1, 150),
    "divergence_x_mrad": (0.5, 40),
    "divergence_y_mrad": (0.5, 40),
    "divergence_power": (0, 3),
}
SCAN016_ENERGY_KNOBS = ["energy_mev", "energy_sigma_mev", "energy_tail_mev"]
PIXEL_KEY = "aline_um_per_px"
SCAN016_KNOBS = (
    "energy_mev,energy_sigma_mev,energy_tail_mev,divergence_x_mrad,divergence_y_mrad,"
    "divergence_power"
)
SLIT_KEYS = ("chicane_jaw1_mm", "chicane_jaw2_mm", "slit_blade_low_mm", "slit_blade_high_mm")


def main():
    a = _args()
    a.out.mkdir(parents=True, exist_ok=True)
    for n, f in _steps():
        if n in a.steps:
            print(f"== step {n}: {f.__name__[6:]}", flush=True)
            f(a)


def _args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("data", type=pathlib.Path)
    p.add_argument("nersc", type=pathlib.Path)
    p.add_argument("out", type=pathlib.Path)
    p.add_argument(
        "--repo",
        type=pathlib.Path,
        default=pathlib.Path(__file__).resolve().parents[3],
        help="the repository root (default: the one this file is in)",
    )
    p.add_argument("--steps", default="1-17", help="e.g. 1-17, 14-17 or 3,4")
    a = p.parse_args()
    a.steps = _parse_steps(a.steps)
    # the chain is 2026-09-29's: its scans are read from that day's folder
    a.data = days.folder(DAY, a.data)
    return a


def _best_values(log):
    r = [json.loads(x) for x in open(log)]
    return min(r, key=lambda x: x["value"])["values"]


def _compare(a, name, *args):
    """Run `compare` on the data with `args`, logging to <name>.log and <name>.out."""
    o = a.out / f"{name}.out"
    with open(o, "w") as f:
        p = subprocess.Popen(
            [sys.executable, "-u", "-m", "htu_twin_apps.lpa_source.compare", str(a.data), *args],
            cwd=a.repo,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        for line in p.stdout:
            if not line.startswith("map/"):
                f.write(line)
                f.flush()
        if p.wait():
            raise RuntimeError(f"{name} failed, see {o}")


def _done(*paths):
    if all(p.exists() for p in paths):
        print("   already there, skipped", flush=True)
        return True
    return False


def _fit(a, name, source, *args):
    """A fit that logs, saves its source and plots; the source is rebuilt from the log's best
    line if the run ended without saving one (the original runs crashed before saving)."""
    s = a.out / f"{name}_source.json"
    if _done(s):
        return
    try:
        _compare(
            a,
            name,
            "--source",
            str(source),
            *args,
            "--log",
            str(a.out / f"{name}.log"),
            "--save",
            str(s),
            "--out",
            str(a.out / f"{name}.png"),
        )
    except RuntimeError:
        if not (a.out / f"{name}.log").exists():
            raise
        print(f"   {name} died; rebuilding {s.name} from the best line of its log", flush=True)
    if not s.exists():
        _from_log(source, a.out / f"{name}.log", s)


def _from_log(base, log, dest, kick=None):
    """`base`'s source and machine state with the log's best values laid over them."""
    from htu_twin_apps.lpa_source import source

    j = json.loads(pathlib.Path(base).read_text())
    fields = {f.name for f in dataclasses.fields(source.LPASource)}
    for k, x in _best_values(log).items():
        (j["source"] if k in fields else j["machine_state"])[k] = x
    pathlib.Path(dest).write_text(json.dumps(j, indent=1))


def _parse_steps(s):
    rv = set()
    for x in s.split(","):
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", x.strip())
        if not m:
            raise SystemExit(f"bad --steps: {x!r}")
        rv.update(range(int(m[1]), int(m[2] or m[1]) + 1))
    return rv


def _scan016_run(measured, results, dest, name, src, knobs):
    """One Scan016 fit; `results` (all runs so far) is rewritten to `dest` after each."""
    from htu_twin_apps.lpa_source import fit, twin

    t = time.time()
    f = fit.fit(
        measured,
        src,
        knobs,
        dict(twin.SCAN016_STATE),
        bounds=SCAN016_BOUNDS,
        max_evaluations=400,
        restarts=6,
    )
    n = fit.check(f, measured)
    d = dataclasses.asdict(f.source)
    results[name] = {
        "source": d,
        "comparison": f.comparison,
        "other_seeds": n.tolist(),
        "source_spectrum": _source_stats(f.source),
    }
    print(
        f"{name}: {f.start_distance:.3f} -> {f.comparison['distance']:.3f} "
        f"(other seeds {n.mean():.3f}+-{n.std():.3f}), {f.evaluations} evals "
        f"{time.time() - t:.0f}s | "
        + ", ".join(f"{k}={d[k]:.3g}" for k in SCAN016_BOUNDS if k in d)
        + f" | transmission {f.comparison['transmission']:.3f}",
        flush=True,
    )
    pathlib.Path(dest).write_text(json.dumps(results, indent=1))
    return f


def _source_stats(src):
    import numpy

    from htu_twin_apps.lpa_source import source

    e = source.particles(src)["energy"] / 1e6
    h, b = numpy.histogram(e, numpy.arange(15, 400, 2))
    return {
        "mean_mev": float(e.mean()),
        "rms_mev": float(e.std()),
        "mode_mev": float(b[h.argmax()] + 1),
    }


def _step_01_scan016_hard_edge(a):
    """Energy + divergence fit to Scan016 with restarts, then energy-only fits at 0.5 and 1.5 times
    that divergence."""
    o = a.out / "fit_scan016_b.json"
    if _done(o):
        return
    sys.path.insert(0, str(a.repo))
    import torch

    from htu_twin_apps.lpa_source import compare, source

    torch.set_num_threads(4)
    m = compare.measured(a.data, 16)
    rv = {}
    f = _scan016_run(
        m,
        rv,
        o,
        "energy + divergence",
        source.from_nersc(a.nersc, "sim_0003", num_particles=50_000),
        SCAN016_ENERGY_KNOBS + ["divergence_x_mrad", "divergence_y_mrad", "divergence_power"],
    )
    for k in (0.5, 1.5):
        s = dataclasses.replace(
            f.source,
            divergence_x_mrad=f.source.divergence_x_mrad * k,
            divergence_y_mrad=f.source.divergence_y_mrad * k,
        )
        _scan016_run(m, rv, o, f"energy only, divergence x{k}", s, SCAN016_ENERGY_KNOBS)


def _step_02_wrap(a):
    o = a.out / "scan016_source.json"
    if _done(o):
        return
    d = json.loads((a.out / "fit_scan016_b.json").read_text())["energy + divergence"]["source"]
    o.write_text(json.dumps({"source": d, "machine_state": {}}, indent=1))


def _step_03_scan016_fringe(a):
    # the original run printed to the terminal and passed --save/--out only: no --log
    s = a.out / "scan016_fringe_source.json"
    if _done(s):
        return
    _compare(
        a,
        "scan016_fringe",
        "--source",
        str(a.out / "scan016_source.json"),
        "--fit",
        SCAN016_KNOBS,
        "--save",
        str(s),
        "--out",
        str(a.out / "scan016_fringe.png"),
    )


def _step_04_pointing(a):
    s = a.out / "pointing_spectrometer_source.json"
    if _done(s):
        return
    _compare(
        a,
        "pointing_spectrometer",
        "--source",
        str(a.out / "scan016_fringe_source.json"),
        "--pointing",
        "--save",
        str(s),
        "--out",
        str(a.out / "pointing_spectrometer.png"),
    )


def _step_05_joint(a):
    _fit(a, "joint", a.out / "pointing_spectrometer_source.json", "--joint")


def _step_06_vertical_scales(a):
    _fit(
        a,
        "vertical_scales",
        a.out / "joint_source.json",
        "--joint",
        "--joint-no-spectrum",
        "--joint-knobs",
        "pointing_y_mrad,pmq_y_mm,divergence_y_mrad,emq1_scale,emq2_scale,magspec_b",
        "--joint-train",
        "Scan025,Scan028",
        "--joint-held-out",
        "Scan030",
    )


def _step_07_slit_jaws(a):
    _fit(a, "slit_jaws", a.out / "scan016_fringe_source.json", "--slit", "jaws")


def _step_08_slit_jaws_blade(a):
    _fit(a, "slit_jaws_blade", a.out / "slit_jaws_source.json", "--slit", "jaws_blade")


def _step_09_aline_start(a):
    o = a.out / "aline_start_plus.json"
    if _done(o):
        return
    v = json.loads((a.out / "vertical_scales_source.json").read_text())
    h = json.loads((a.out / "slit_jaws_blade_source.json").read_text())
    src = {
        **v["source"],
        **{
            k: h["source"][k]
            for k in ("divergence_x_mrad", "pointing_x_mrad", "pointing_slope_x_mrad")
        },
    }
    ms = {k: x for k, x in v["machine_state"].items() if k != "magspec_b"}
    ms.update({k: h["machine_state"][k] for k in SLIT_KEYS})
    o.write_text(json.dumps({"source": src, "machine_state": {**ms, "s1h_scale": 1.0}}, indent=1))


def _step_10_aline_plus(a):
    _fit(
        a,
        "aline_plus",
        a.out / "aline_start_plus.json",
        "--aline",
        "--workers",
        "3",
        "--threads",
        "2",
    )


def _step_11_aline_offsets(a):
    _fit(
        a,
        "aline_offsets",
        a.out / "aline_plus_source.json",
        "--aline",
        "--aline-knobs",
        ALINE_OFFSETS_KNOBS,
        "--workers",
        "5",
        "--threads",
        "2",
    )


def _step_12_aline_image(a):
    _fit(
        a,
        "aline_image",
        a.out / "aline_offsets_source.json",
        "--aline",
        "--aline-knobs",
        ALINE_KNOBS,
        "--workers",
        "5",
        "--threads",
        "2",
    )


def _step_13_aline_axis_start(a):
    # aline.fit strips the pixel size from the saved source: take it from the log's best line
    o = a.out / "aline_axis_start.json"
    if _done(o):
        return
    j = json.loads((a.out / "aline_image_source.json").read_text())
    j["machine_state"][PIXEL_KEY] = _best_values(a.out / "aline_image.log")[PIXEL_KEY]
    o.write_text(json.dumps(j, indent=1))


def _step_14_aline_axis(a):
    _fit(
        a,
        "aline_axis",
        a.out / "aline_axis_start.json",
        "--aline",
        "--aline-knobs",
        ALINE_KNOBS,
        "--workers",
        "3",
        "--threads",
        "2",
    )


def _step_15_slit_start(a):
    # only the A-line uses the pixel size; the slit fit would pass it to the twin
    o = a.out / "slit_a_start.json"
    if _done(o):
        return
    j = json.loads((a.out / "aline_axis_source.json").read_text())
    j["machine_state"].pop(PIXEL_KEY, None)
    o.write_text(json.dumps(j, indent=1))


def _step_16_slit_refit(a):
    _fit(
        a,
        "slit_a",
        a.out / "slit_a_start.json",
        "--slit",
        "jaws_blade",
        "--slit-knobs",
        "chicane_jaw1_mm,chicane_jaw2_mm",
        "--threads",
        "2",
    )


def _step_17_rescore_source(a):
    o = a.out / "slit_a_rescore.json"
    if _done(o):
        return
    j = json.loads((a.out / "aline_axis_source.json").read_text())
    k = json.loads((a.out / "slit_a_source.json").read_text())["machine_state"]
    j["machine_state"].update({x: v for x, v in k.items() if "jaw" in x or "blade" in x})
    o.write_text(json.dumps(j, indent=1))


def _steps():
    g = globals()
    return [(int(k[6:8]), g[k]) for k in sorted(g) if re.fullmatch(r"_step_\d\d_\w+", k)]


if __name__ == "__main__":
    main()
