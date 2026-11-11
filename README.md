# htu-twin-apps

HTU Twin Dev Apps: small apps for looking at and working with HTU data and the HTU twin. Each app
is a subpackage of `htu_twin_apps` with its own README and console script; they share one install.

| App | Command | What it does |
|---|---|---|
| [LPA source](htu_twin_apps/lpa_source/README.md) | `htu-lpa-source` | An adjustable LPA source tracked through the HTU twin to the spectrometer, compared with a measured spectrum |
| [Shot viewer](htu_twin_apps/shot_viewer/README.md) | `htu-shot-viewer` | Browse HTU scans shot by shot in the browser: scalars, images, machine settings and a beamline schematic |
| [Twin viewer](htu_twin_apps/twin_viewer/README.md) | `htu-twin-viewer` | The HTU twin with the fitted LPA source at a recorded scan's settings, step by step, beside the measurement |

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

The raw HTU stacks are written with HDF5 2.0, which needs h5py 3.16 or later (a dependency).

## Data

The data lives outside this repository. Apps take the days of interest as arguments, as day names
(`26_0929`, found below the data root, `--root`) or the paths of day folders, and
read only those folders; nothing searches the data tree:

```bash
# --root: the folder holding Y2026 (HTU's Undulator folder), or the one holding that
htu-shot-viewer 26_0929 26_1001 --root /path/to/Undulator
```

HTU saves a day as `<root>/Y2026/09-Sep/26_0929/`, with `analysis/` (the scalar tables
`s<N>.txt`) and `scans/ScanNNN/` below it: `ScanDataScanNNN.txt`, `ScanInfoScanNNN.ini` and one
folder of HDF5 stacks per device. The day's folder is built from its name, so only the days asked
for are read.

## Adding an app

1. Create `htu_twin_apps/<app>/` with an `__init__.py`, the app's modules and a `README.md`.
   Browser assets go in `htu_twin_apps/<app>/static/`; the `*/static/**` pattern in
   `pyproject.toml` packages them.
2. Add its console script under `[project.scripts]` in `pyproject.toml`, named `htu-<app>`.
3. Take the days from the command line (`htu_twin_apps.days.folders`, with `--root`) and read only those day folders.
4. Add a row to the table above.

Code that a second app needs from an existing one (reading scan folders, for example) moves into a
shared module of `htu_twin_apps` at that point, not before.
