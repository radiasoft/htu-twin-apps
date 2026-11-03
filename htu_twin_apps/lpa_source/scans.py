"""Read HTU scans for the source fits: a scan's table, its steps' twin machine state, its stacks.

:copyright: Copyright (c) 2026 RadiaSoft LLC.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""

from __future__ import annotations

import csv
import h5py
import htu_twin_apps.stacks
import numpy
import pathlib

# The spectrometer's Cam1 energy axis starts here [MeV] in the scans whose axis is trusted
# (Scans 014, 019, 020 on 2026-09-29). In Scans 025 to 030 the camera driver's axis is the same one
# scaled by 0.833 or 0.824 (both ends of both cameras alike) while the beam's features stay on the
# same pixels: the driver's field setting changed, not the magnet, so those energies are labelled
# about 17% low (checked 2026-11-02: rescaled, Scan025's slit-cut peak returns to Scan020's 96 MeV
# and the twin's spectrum distance halves). `energy_axis` undoes the scaling. Which setting was
# right was tested by fitting under each (2026-11-03): this early one fits Scan019 and the
# spectrometer scans' spectra better, with the A-line images neutral.
CAM1_AXIS_START_MEV = 54.45
# A machine-state key (not a twin key): the ratio of the spectrometer's energy labels to the
# twin's true energies, fitted to test which of the driver's settings was right (1: the early,
# CAM1_AXIS_START_MEV; LATE_CAM1_AXIS_START_MEV / CAM1_AXIS_START_MEV: the late).
ENERGY_LABEL_KEY = "energy_label_scale"
# Twin machine-state keys of the scan-table columns read as each step's settings.
GEECS_TO_TWIN = {
    "U_ChicaneInner Current": "chicane_current",
    "U_EMQTripletBipolar Current_Limit.Ch1": "EMQ1H",
    "U_EMQTripletBipolar Current_Limit.Ch2": "EMQ2V",
    "U_EMQTripletBipolar Current_Limit.Ch3": "EMQ3H",
    **{f"U_S{i}{p} Current": f"S{i}{p}" for i in range(1, 5) for p in "HV"},
    **{f"U_VS{i}{p} Current": f"VS{i}{p}" for i in range(1, 9) for p in "HV"},
}
# The Cam1 axis start [MeV] of the late setting (Scan025's), the alternative hypothesis.
LATE_CAM1_AXIS_START_MEV = 45.38
# The EMQ setpoints [A] of channels a scan does not log (the EMQ scans log only the scanned
# channel): HTU's nominal settings on 2026-09-29, as logged in Scan022 and given in the data's
# README. A scan that logs a channel (Scan019 logs all three, at 0) uses its own value.
NOMINAL_EMQ = {"EMQ1H": 1.5, "EMQ2V": -0.82, "EMQ3H": 0.0}


def energy_axis(
    folder: pathlib.Path, camera: str, start_mev: float | None = None
) -> numpy.ndarray:
    """`camera`'s `-interpSpec` energy axis [MeV] in the scan `folder`, rescaled to one
    calibration: the camera driver's axis times the scan's factor, so that Cam1's axis starts at
    `start_mev` (CAM1_AXIS_START_MEV, the trusted early setting, if None)."""
    rv, _ = stack(folder, f"UC_BCaveMagSpec{camera}-interpSpec", [])
    c, _ = stack(folder, "UC_BCaveMagSpecCam1-interpSpec", [])
    # POSIT: a mis-set driver field scales every camera's axis by the same factor, Cam1's included
    s = CAM1_AXIS_START_MEV if start_mev is None else start_mev
    return rv[0, :, 0].astype(float) * (s / float(c[0, 0, 0]))


def machine_state(rows: list) -> dict:
    """The twin machine state of one step's rows: each logged setting's median, nominal EMQs."""
    rv = dict(NOMINAL_EMQ)
    for c, k in GEECS_TO_TWIN.items():
        v = [number(r.get(c)) for r in rows]
        v = [x for x in v if x is not None]
        if v:
            rv[k] = float(numpy.median(v))
    return rv


def number(text):
    """`text` as a finite float, or None."""
    try:
        v = float(text)
    except (TypeError, ValueError):
        return None
    return v if numpy.isfinite(v) else None


def stack(folder: pathlib.Path, device: str, rows: list) -> tuple:
    """A device stack's frames and, per table row, the matched frame (-1 for none)."""
    with h5py.File(folder / device / f"{device}.h5", "r") as f:
        a = f["entry/data/data"][()]
        t = f["entry/instrument/NDAttributes"]
        x = t[next(k for k in t if k.endswith("frame_acq_timestamp"))][()]
    return a, htu_twin_apps.stacks.match(
        x, [number(r.get(f"{device.split('-')[0]} acq_timestamp")) for r in rows]
    )


def step_numbers(rows: list) -> list:
    """Each row's step (`Bin #`)."""
    v = [number(r.get("Bin #")) for r in rows]
    if any(x is None for x in v):
        raise ValueError("a scan-table row without a step (Bin #)")
    return [int(x) for x in v]


def table(data: pathlib.Path, scan: str) -> tuple:
    """(folder, rows) of `scan` (a scan folder name, such as `Scan025`) found below `data`."""
    f = sorted(pathlib.Path(data).rglob(f"scans/{scan}/ScanData{scan}.txt"))
    if len(f) != 1:
        raise FileNotFoundError(f"{len(f)} scan tables for {scan} below {data}")
    with open(f[0], newline="") as x:
        return f[0].parent, list(csv.DictReader(x, delimiter="\t"))
