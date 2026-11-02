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

# Twin machine-state keys of the scan-table columns read as each step's settings.
GEECS_TO_TWIN = {
    "U_ChicaneInner Current": "chicane_current",
    "U_EMQTripletBipolar Current_Limit.Ch1": "EMQ1H",
    "U_EMQTripletBipolar Current_Limit.Ch2": "EMQ2V",
    "U_EMQTripletBipolar Current_Limit.Ch3": "EMQ3H",
    **{f"U_S{i}{p} Current": f"S{i}{p}" for i in range(1, 5) for p in "HV"},
    **{f"U_VS{i}{p} Current": f"VS{i}{p}" for i in range(1, 9) for p in "HV"},
}
# The EMQ setpoints [A] of channels a scan does not log (the EMQ scans log only the scanned
# channel): HTU's nominal settings on 2026-09-29, as logged in Scan022 and given in the data's
# README. A scan that logs a channel (Scan019 logs all three, at 0) uses its own value.
NOMINAL_EMQ = {"EMQ1H": 1.5, "EMQ2V": -0.82, "EMQ3H": 0.0}


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
