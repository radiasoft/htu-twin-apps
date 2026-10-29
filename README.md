# htu-twin-apps

HTU Twin Dev Apps: small apps for looking at and working with HTU data and the HTU twin. Each app
is a subpackage of `htu_twin_apps` with its own README and console script; they share one install.

| App | Command | What it does |
|---|---|---|
| [Shot viewer](htu_twin_apps/shot_viewer/README.md) | `htu-shot-viewer` | Browse HTU scans shot by shot in the browser: scalars, images, machine settings and a beamline schematic |

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

The raw HTU stacks are written with HDF5 2.0, which needs h5py 3.16 or later (a dependency).

## Data

The data lives outside this repository. Apps take the data directory as an argument, or read it
from `$HTU_DATA`:

```bash
export HTU_DATA=/path/to/htu-data
htu-shot-viewer
```

The directory holds HTU's scan folders as HTU saves them, at any depth:
`<date folder>/scans/ScanNNN/` with `ScanDataScanNNN.txt`, `ScanInfoScanNNN.ini` and one folder of
HDF5 stacks per device.

## Adding an app

1. Create `htu_twin_apps/<app>/` with an `__init__.py`, the app's modules and a `README.md`.
   Browser assets go in `htu_twin_apps/<app>/static/`; the `*/static/**` pattern in
   `pyproject.toml` packages them.
2. Add its console script under `[project.scripts]` in `pyproject.toml`, named `htu-<app>`.
3. Read the data directory from the command line, falling back to `$HTU_DATA`.
4. Add a row to the table above.

Code that a second app needs from an existing one (reading scan folders, for example) moves into a
shared module of `htu_twin_apps` at that point, not before.
