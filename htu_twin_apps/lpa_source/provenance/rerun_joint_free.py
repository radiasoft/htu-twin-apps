"""Rerun the fit that produced aline_slit_spectrometer_free_scale.json (see
joint_free_provenance.md).

    python rerun_joint_free.py DATA OUT_DIR [--start FILE] [--repo REPO] [--workers N]
        [--threads N]

DATA is the htu-sample-data directory (holding Undulator/Y2026/09-Sep/26_0929), OUT_DIR where
everything is written (use a new directory: the original fits are not touched). The fit starts
from `htu_twin_apps/twin_viewer/fits/aline_slit.json` (the end of `rerun_slit_a_rescore.py`'s
chain; `--start` takes that chain's own `slit_a_rescore.json` instead), and writes
OUT_DIR/aline_slit_spectrometer_free_scale.json, the source, machine state and spectrometer
cameras' calibration (`spectrometer`), in the viewer's format.

Steps:
 1  the start, EMQ3's vertical offset added at 0      joint_aline_start.json
 2  the A-line, Scan019 and the spectrometer fitted
    together, the cameras' scales free                 aline_slit_spectrometer_free_scale.json

The fit needs the spectrometer projection it was made with: this repository's, with the COSY
maps' upstream drift removed (`pointing.upstream_drift_m`) and thresholded profiles
(`pointing.THRESHOLD`); it refuses to run otherwise. `--repo` runs it from another checkout of
this repository.

Each step skips itself if its output already exists in OUT_DIR. The fit's printed output goes to
OUT_DIR/joint_free.out and every evaluation to OUT_DIR/joint_free.log. It took 8.6 hours on the
original machine (1,201 evaluations, 6 workers of 2 threads); the fit is stochastic, so a rerun
gives similar, not identical, values.
"""

import argparse
import json
import pathlib
import subprocess
import sys

from htu_twin_apps import days

# The day the fit reads.
DAY = "26_0929"
# The knobs fitted: aline_vertical.FIT_NAMES and EMQ3's vertical offset.
KNOBS = (
    "aline_um_per_px,emq1_x_mm,emq1_y_mm,emq2_x_mm,emq2_y_mm,pointing_x_mrad,"
    + "pointing_slope_x_mrad,divergence_x_mrad,pointing_y_mrad,divergence_y_mrad,s1h_scale,"
    + "pmq_x_mm,pmq_y_mm,emq1_scale,emq2_scale,chicane_jaw1_mm,emq3_y_mm"
)
# The fit's result, in the viewer's format.
RESULT = "aline_slit_spectrometer_free_scale.json"


def main():
    a = _args()
    a.out.mkdir(parents=True, exist_ok=True)
    _check_code(a)
    _step_1_start(a)
    _step_2_fit(a)


def _args():
    r = pathlib.Path(__file__).resolve().parents[3]
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    p.add_argument("data", type=pathlib.Path)
    p.add_argument("out", type=pathlib.Path)
    p.add_argument(
        "--start",
        type=pathlib.Path,
        default=r / "htu_twin_apps" / "twin_viewer" / "fits" / "aline_slit.json",
        help="the fit to start from (default: the viewer's fits/aline_slit.json)",
    )
    p.add_argument(
        "--repo",
        type=pathlib.Path,
        default=r,
        help="the repository root (default: the one this file is in)",
    )
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--threads", type=int, default=2)
    a = p.parse_args()
    a.data = days.folder(DAY, a.data)
    return a


def _check_code(a):
    """Fail unless the fit would run with the spectrometer model it was made with."""
    p = subprocess.run(
        [
            sys.executable,
            "-c",
            "from htu_twin_apps.lpa_source import pointing as p; "
            + "print(hasattr(p, 'upstream_drift_m'), hasattr(p, 'THRESHOLD'))",
        ],
        cwd=a.repo,
        capture_output=True,
        text=True,
    )
    if p.returncode:
        raise SystemExit(f"cannot import {a.repo}'s pointing: {p.stderr}")
    if p.stdout.split()[-2:] != ["True", "True"]:
        raise SystemExit(
            "the fit needs the spectrometer model of 2026-11-16 (the maps' upstream drift "
            + "removed, thresholded profiles); give --repo as the module's docstring says"
        )


def _done(path):
    if path.exists():
        print(f"   {path.name} already there, skipped", flush=True)
        return True
    return False


def _step_1_start(a):
    o = a.out / "joint_aline_start.json"
    print("== step 1: start", flush=True)
    if _done(o):
        return
    j = json.loads(a.start.read_text())
    # the start was fitted without EMQ3's vertical offset: the twin's default, 0
    j["machine_state"].setdefault("emq3_y_mm", 0.0)
    o.write_text(json.dumps(j, indent=1))


def _step_2_fit(a):
    s = a.out / RESULT
    print("== step 2: A-line, Scan019 and spectrometer, scales free", flush=True)
    if _done(s):
        return
    o = a.out / "joint_free.out"
    with open(o, "w") as f:
        p = subprocess.Popen(
            [
                sys.executable,
                "-u",
                "-m",
                "htu_twin_apps.lpa_source.aline_vertical",
                str(a.data),
                "--source",
                str(a.out / "joint_aline_start.json"),
                "--knobs",
                KNOBS,
                "--scale",
                "free",
                "--workers",
                str(a.workers),
                "--threads",
                str(a.threads),
                "--log",
                str(a.out / "joint_free.log"),
                "--save",
                str(s),
            ],
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
            raise RuntimeError(f"the fit failed, see {o}")


if __name__ == "__main__":
    main()
