# HTU twin viewer

A small local web app that runs the HTU twin, with an LPA source (the fitted one, or an fbpic
simulation's beam) and the fitted corrections to the line, at the logged settings of a recorded scan
step and shows it beside that step's measurement. Pick a dataset, move the step slider, and the page shows the beamline synoptic with
the values the twin ran with, the twin's output against the data, and the numbers below.

![Scan025, an EMQ1 scan on the spectrometer: EMQ1 outlined on the beamline, the measured and twin spectra, the measured ImageInterp and the twin's energy against AngleAxis](screenshots/scan025.png)

*Scan025, step 1: EMQ1 is the scanned element; the spectrum, the measured ImageInterp and the
twin's energy–AngleAxis image, with the compared values and the settings below.*

![Scan023, an EMQ1 scan onto the A-line camera: the measured UC_ALineEBeam3 spot and the twin's rendered spot](screenshots/scan023.png)

*Scan023, step 1: the A-line camera frame (background subtracted) and the twin's spot rendered at
the fitted pixel size.*

## Run

Install the repository (see the [top-level README](../../README.md)), then:

```bash
htu-twin-viewer <day> ... --source <fitted twin values json file> [--root <data root>]
```

Ex., the command the viewer was developed with (two days, the fbpic density scan as extra
sources, 50,000 particles per step, 4 torch threads, on port 8008):

```bash
htu-twin-viewer 26_0929 26_1001 \
    --root <data root> \
    --source <repo>/htu_twin_apps/twin_viewer/twin-fit-values.json \
    --fbpic <data root>/simulations/htu_den_scan \
    --port 8008 --particles 50000 --threads 4
```

Run from a clone without installing the package, the same command is:

```bash
cd <repo>
PYTHONPATH=$PWD OMP_NUM_THREADS=4 python -u -m htu_twin_apps.twin_viewer.server 26_0929 26_1001 \
    --root <data root> --source htu_twin_apps/twin_viewer/twin-fit-values.json \
    --fbpic <data root>/simulations/htu_den_scan --port 8008 --particles 50000 --threads 4
```

`<data root>` is the folder holding `Undulator/Y2026/...` (here it also holds `simulations/`, which
is not HTU data). `--fbpic`, `--particles` and `--threads` are optional (defaults: no fbpic
sources, 20000 particles, 2 threads, port 8060).

The days are day names such as `26_0929`, found as `<data root>/Y2026/09-Sep/26_0929` (`--root` is
HTU's `Undulator` folder, or the folder holding it), or the paths
of day folders. Only those days' folders are read: nothing searches the data tree. `--fbpic DIR`
offers the fbpic runs in DIR (`*_diags/*/data*.h5`) as sources (below); `--datasets FILE`
replaces the list of days and datasets.

`twin-fit-values.json` is the result of the 17-step fit chain traced in
[`lpa_source/provenance`](../lpa_source/provenance/slit_a_rescore_provenance.md), which also has a
script that reruns it. `--source` takes any fit's saved source in that format, such as one of
2026-10-01's population fits (`oct1_high_fbpic_1.10.json`, written by a joint fit of Scan014's two
populations). Such a file also holds `oct1_energy_label_scale`, which the viewer does not use: it
shows 2026-10-01 on the driver's own energy labels, so a fit made with the labels divided by that
scale looks shifted in energy by it.

Open the port's page (<http://127.0.0.1:8008> above; 8060 by default). Options: `--port N`,
`--particles N` (default 20000), `--threads N` (torch threads, default 2; one simulation runs at a
time, with this many cores) and `--source FILE` (a fit's saved source JSON; required). The page
opens a dataset, step and source from the URL, and keeps the address bar at the view as you move
(`?scan=26_1001/Scan013&step=1&source=fbpic:3.8e%2B18`; `step` counts from 1, `source` is left out
for the first source), so a reload or a link returns to the same view.

The server listens on all interfaces (so a VM's forwarded port works); it has no access control.

## What it does

- **Datasets:** the scans of the days given, read from their folders: every scan that saved both
  spectrometer cameras' `-interpSpec` is one (a spectrum, or with their `-ImageInterp` as well the
  spectrometer's image), titled from its `ScanInfo`. From 2026-09-29 that is Scans 014, 019, 020, 025,
  028, 029 and 030, plus the A-line Scans 023 and 026 and Scan016 from `datasets.json`; from
  2026-10-01, Scans 013 and 014 (downramp-injection noscans, 100 and 3,002 shots, one step each, the
  mean over the shots). Each step is the twin at that step's logged settings. The list is built from
  the folders' names and `ScanInfo` alone, and a scan is read when first selected.
- **`datasets.json`** holds only what the folders do not say, as overrides of those defaults: per
  day, `energy_axis` ("early": the spectrometer's energies rescaled to the early driver setting,
  as for 09-29; "recorded", the default: the driver's own labels, as for 10-01), `slit` ("in": the
  fit's jaw and blade; "out", the default: the slit is not logged) and a `note`; per scan, an entry
  whose fields replace the defaults (`kind` "scan016" for Scan016, which has no raw folder, or
  "aline" for an A-line scan, which needs the file for its background and spectra; `slit`;
  `title`, where HTU's description misleads, as for Scans 029 and 030) or that adds a `variant` of
  the scan (below). A day with no entry in the file gets the defaults.
- **Split noscans:** Scan014 also has three variants (`26_1001/Scan014:charge`, `:time`, `:peak`)
  that regroup its 3,002 shots into steps, each the mean of a group of the shots with an ICT
  charge above 5 pC (125 shots saw no beam): quartiles by charge, thirds in time, or the shots
  whose spectrum peaks below / at or above 92 MeV (the step slider's label says which group).
  Their `split` entries in `datasets.json` define them. The shots are two populations, one peaking
  near 77 MeV (46%, median 21 pC) and one near 105 MeV (54%, median 33 pC), so the mean of all of
  them is a mixture, not one beam.
- **Source:** the fit's source, or the beam at the plasma exit of an fbpic run (`--fbpic`: each
  `*_diags` folder's last `data*.h5`, one per density in a density scan), chosen on the page. The
  fit's corrections to the line (S1H and EMQ scales, offsets, PMQ position, slit) apply to either.
  An fbpic beam has no source knobs to edit, and its table row says "fbpic". Changing the source
  clears any edits of the fit's source knobs.
- **Synoptic:** the electron line in beam order with the twin's value for each element; the
  scanned element is outlined. Hover an element for its logged value and correction.
- **Twin against the data:** the spectrum (measured and twin) for the spectrometer datasets; for
  those that saved the cameras' `-ImageInterp` (most of them) also the measured image (Cam1 and
  Cam2) and the twin's energy against AngleAxis; for the A-line datasets the step-mean frame and
  the twin's spot rendered as the camera sees it. The images keep square pixels (for the
  spectrometer's, one energy bin by one AngleAxis bin) and sit side by side in the middle of the
  row. On a page 2848 px or wider the Values panel moves beside these plots, 1400 px wide, and
  stays in view as they scroll.
- **Values:** the compared quantities (spectrum distance, peak, mean and rms energy; A-line rms
  sizes and centroids) and a settings table: logged value, what the twin ran with, and the fitted
  correction.
- **Edits:** the "Twin ran with" values are inputs. Change one and press Enter (or leave the
  field) to rerun the twin with it; an edited field is outlined, and emptying it restores the fit's
  value. Editable: the source's divergence, pointing, size and energy shape; the PMQ triplet's
  offsets and gradient scale; the magnet currents (S1H, S1V, chicane, EMQ1–3, S3H); the EMQs' offsets;
  the slit's jaw and blade; the A-line pixel size. An edited current is what the twin's magnet
  sees (the fitted scale is not applied to it), and it replaces the logged value at every step,
  so editing the scanned magnet makes every step the same. Edits stay as you move through steps
  and datasets until the reset button ("Reset N edits"). The API takes them as `edits=` JSON on `/api/step`
  (see `server.py`).

- **Camera seam** (spectrometer datasets): the measured image is Cam1 below where Cam2's energy
  axis starts and Cam2 above (the dashed line: 129.2 MeV on 09-29, 122.5 MeV on 10-01). Each
  camera's ImageInterp is in its own raw counts (on 09-29 Cam2 about 6 times Cam1 for the same
  charge) and its own AngleAxis zero (about 3 apart), so two options correct the
  stitch, both on by default: "scale each to its spectrum" scales each camera's image to its
  `-interpSpec`, and "align Cam2 to Cam1" shifts Cam2, by whole 0.5 bins, so that its AngleAxis
  centroid within 4 MeV of the seam matches Cam1's, per step. The shift is shown in the image's
  title. The alignment assumes the beam does not jump at the seam; the fits use neither.

Each step's result is cached; a step not yet run takes a few seconds, and a background thread runs
the remaining steps of the dataset on view.

## Caveats

- 2026-09-29's energies use the early (Scan020) spectrometer axis for every scan: the driver's
  labels changed twice that day while the beam stayed on the same camera pixels, and fitting under
  each labelling favours the early one (see `lpa_source.scans.energy_axis`). 2026-10-01's are the
  driver's own (Cam1 starts at 51.6 MeV, 0.948 of 09-29's early axis): not verified, since that
  day has no scans to compare labels against.
- 2026-10-01 settings the fit never saw: S1V (+0.5 A, with the twin's own calibration, probably far
  too strong as S1H's was: at full strength the twin's beam sits about 9 AngleAxis units above the
  measured one, and near 0 at about 7% of it) and the slit (not logged: assumed out).
- The twin's AngleAxis scale is not the data's, so compare the two images' shapes, not their
  vertical extent.
- The twin's A-line spot is centred on its own centroid, so no twin centroid is shown: comparing
  centroids needs the camera zeros the A-line fit finds per scan.
- 20,000 particles: the twin's images are noisy; raise `--particles` for smoother ones.
