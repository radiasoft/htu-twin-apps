# htu-twin-apps

HTU Twin Dev Apps: small apps for looking at and working with HTU data and the HTU twin. Each app
is a subpackage of `htu_twin_apps` with its own README and console script; they share one install.

| App | Command | What it does |
|---|---|---|
| [LPA source](htu_twin_apps/lpa_source/README.md) | `htu-lpa-source` | An adjustable LPA source tracked through the HTU twin to the spectrometer, compared with a measured spectrum |
| [Shot viewer](htu_twin_apps/shot_viewer/README.md) | `htu-shot-viewer` | Browse HTU scans shot by shot in the browser: scalars, images, machine settings and a beamline schematic |
| [Twin viewer](htu_twin_apps/twin_viewer/README.md) | `htu-twin-viewer` | The HTU twin with the fitted LPA source at a recorded scan's settings, step by step, beside the measurement |

## Shared modules

| Module | What it does |
|---|---|
| `htu_twin_apps.machine_state` | The transport line's machine state, independent of the simulator: every setting (logged by GEECS) and correction (fitted) with its unit; a scan step's settings (`from_geecs()`), a setting's EPICS name (`pv_name()`), and the state a simulator takes (`to_twin()`) |
| `htu_twin_apps.pv_access` | The settings by machine-state key, live over EPICS PV Access (`Live`: `get()`, `monitor()`; the twin's PVs or HTU's) or from a recorded scan (`archive()`) |
| `htu_twin_apps.days` | A day's folder from its name (see "Data") |

[`docs/htu-pv-translation.md`](docs/htu-pv-translation.md) maps the names of the twin's PVs, GEECS's
devices and the machine state, and records what is known of their calibrations.
[`docs/htu-twin-questions.md`](docs/htu-twin-questions.md) is the short list for the GEECS team: a
bug in the twin's spectrometer model and the questions we most need answered, with the rest in
[`docs/htu-twin-other-questions.md`](docs/htu-twin-other-questions.md).

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

## Tests

```bash
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest tests
```

The live PV tests start the HTU twin's server (`python -m htu.serve`), so they need the twin
(`htu`, from geecs-lume-twin) and `p4p`; they are skipped without them. The test of a recorded
scan needs the data: set `HTU_DATA_ROOT` to the folder holding `Y2026`.

## Adding an app

1. Create `htu_twin_apps/<app>/` with an `__init__.py`, the app's modules and a `README.md`.
   Browser assets go in `htu_twin_apps/<app>/static/`; the `*/static/**` pattern in
   `pyproject.toml` packages them.
2. Add its console script under `[project.scripts]` in `pyproject.toml`, named `htu-<app>`.
3. Take the days from the command line (`htu_twin_apps.days.folders`, with `--root`) and read only those day folders.
4. Add a row to the table above.

Code that a second app needs from an existing one (reading scan folders, for example) moves into a
shared module of `htu_twin_apps` at that point, not before.
