"""HTU's day folders, found from a day's name without searching the data tree.

HTU saves a day's data as `<root>/Y<yyyy>/<mm>-<Mon>/<yy>_<mmdd>/` with `scans/` and `analysis/`
below it (`Undulator/Y2026/09-Sep/26_0929/`). The apps take the days of interest on their command
line, as a day name (`26_0929`) with the root, or as the path of a day folder, and read only
those folders: nothing walks the tree above them, which on HTU's network drive holds years of
data.

The root is `--root`; it is the folder holding `Y2026` (HTU's `Undulator`) or the
folder holding that one.

:copyright: Copyright (c) 2026 RadiaSoft LLC.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""

from __future__ import annotations

import os
import pathlib
import re

# A day's name: <yy>_<mm><dd>.
DAY = re.compile(r"^(\d\d)_(\d\d)(\d\d)$")
# HTU's month folders are <mm>-<Mon>, in English whatever the locale.
MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)
# The folders that mark a day folder.
MARKERS = ("scans", "analysis")


def folder(
    day: str | os.PathLike, root: str | os.PathLike | None = None
) -> pathlib.Path:
    """The day folder for `day`, a day name (`26_0929`, found below `root`) or
    the path of a day folder (one with `scans` or `analysis` in it)."""
    s = str(day)
    m = DAY.match(s)
    if not m:
        p = pathlib.Path(s).expanduser()
        if not any((p / x).is_dir() for x in MARKERS):
            raise ValueError(
                f"{s!r} is neither a day name such as 26_0929 nor the path of a day folder "
                + f"(one with {' or '.join(MARKERS)} in it)"
            )
        return p.resolve()
    if root is None:
        raise ValueError(f"day {s} needs the data root: give --root")
    r = root
    yy, mm, dd = (int(x) for x in m.groups())
    if not (1 <= mm <= 12 and 1 <= dd <= 31):
        raise ValueError(f"{s!r} is not a day: month {mm}, day {dd}")
    # POSIT: HTU's day folders are named for their own date, so the path is known from the name
    rel = pathlib.Path(f"Y{2000 + yy}") / f"{mm:02d}-{MONTHS[mm - 1]}" / s
    c = [
        pathlib.Path(r).expanduser() / rel,
        pathlib.Path(r).expanduser() / "Undulator" / rel,
    ]
    for p in c:
        if p.is_dir():
            return p.resolve()
    raise FileNotFoundError(
        f"no folder for day {s}: looked for {' or '.join(map(str, c))}"
    )


def folders(days, root: str | os.PathLike | None = None) -> dict:
    """{day name: folder} for each of `days` (see `folder`), in order."""
    rv = {}
    for d in days:
        f = folder(d, root)
        if f.name in rv and rv[f.name] != f:
            raise ValueError(
                f"two different folders for day {f.name}: {rv[f.name]} and {f}"
            )
        rv[f.name] = f
    return rv


def scan_folders(day_folder: str | os.PathLike) -> dict:
    """{scan name (`Scan014`): its folder} for the scans of a day folder that have a scan table:
    one listing of `scans/`, whatever the folders are called (`Scan014_donotuse`)."""
    rv = {}
    s = pathlib.Path(day_folder) / "scans"
    for d in sorted(s.iterdir()) if s.is_dir() else ():
        for t in sorted(d.glob("ScanDataScan*.txt")) if d.is_dir() else ():
            rv[t.name[len("ScanData") : -len(".txt")]] = d
    return rv
