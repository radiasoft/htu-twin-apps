# LPA source

An adjustable laser-plasma (LPA) electron source for the HTU twin (`geecs-lume-twin`), tracked to
the magnetic spectrometer's entrance and compared with a spectrum HTU measured. The aim is a
source that can be tuned until the twin reproduces the measurement, starting where the fewest
uncalibrated parts of the line are involved.

## Run

Install the repository with the `lpa-source` extra (see the [top-level README](../../README.md)),
and the HTU twin's `htu` package from geecs-lume-twin, which is not on PyPI. Then:

```bash
htu-lpa-source <data directory> --nersc <path>/runs/initial_sample/sample_dataset/sample_dataset.json
```

It prints a table and writes `lpa_source_compare.png` (`--out` to change it). It compares the
twin's default Gaussian source, sources made from the NERSC runs given by `--runs` (default the
nominal `sim_0000`, `sim_0003`, `sim_0004`) and the `LPASource` defaults; without `--nersc`, the
NERSC sources are left out. `--particles N` sets the particles per source (default 50,000).

To also fit knobs to the measurement, name them with `--fit`; the fit starts from a saved source
(`--source`), the first `--runs` source, or the `LPASource` defaults, in that order, and is added
to the table and plot:

```bash
htu-lpa-source <data directory> --nersc <path>/sample_dataset.json --runs sim_0003 \
    --fit energy_mev,energy_sigma_mev,energy_tail_mev,divergence_x_mrad,divergence_y_mrad,divergence_power \
    --save scan016_source.json
```

That fit takes about 500 evaluations, 4 to 5 minutes. `--save` writes the fitted source, and the
twin machine state it was fitted with, as JSON; `--source` reads it back, so later runs need not
refit.

`--pointing` then fits the source's vertical pointing and divergence, and the PMQ triplet's
vertical offset, to the spectrometer's EMQ scans (see below), starting from the fitted or saved
source; it writes a second plot, `<out>_pointing.png`, and adds the source it ends with to the
Scan016 table. It takes one to two hours (two Nelder-Mead starts of up to 60 evaluations, each
tracking 45 scan steps):

```bash
htu-lpa-source <data directory> --source scan016_source.json --pointing --save pointing_source.json
```

`--slit jaws` or `--slit blade` fits Scan019 (an R56 scan with the slit in; `slit.py`): the
slit's two edges (`chicane_jaw1_mm`, `chicane_jaw2_mm`), the source's horizontal pointing, its
slope with energy and its horizontal divergence, and the PMQ triplet's z, with the slit as the
twin's two jaws or as a blade, comparing each of the 20 steps' spectra (the two cameras'
`-interpSpec` stitched) and minimizing the mean distance. About 27 s an evaluation, hours a fit;
it writes `<out>_slit_<shape>.png`.

`--joint` fits the source's energy and divergence knobs, its vertical pointing and the PMQ
triplet's y and z to Scan016's spectrum and Scans 025 and 028's vertical profiles together
(`joint.py`), then predicts Scan030 with the per-camera scale, zero and floor fitted on 025 and
028 held fixed. The objective is the profiles' chi^2 plus `(distance / 0.01) ** 2` of the
spectrum. About 40 s an evaluation, many hours a fit.

`--slit jaws_blade` adds a blade inside the jaws (`slit_blade_low_mm`, `slit_blade_high_mm`),
which Scan019's narrow notch needs; `--slit-knobs` narrows the fit to the slit's own edges.

`--aline` fits the beam's path to the A-line camera's EMQ scans (Scans 023 and 026 on
`UC_ALineEBeam3`, each step's spectrum from its spectrometer partner, Scans 025 and 028) and
Scan019 together (`aline.py`): the model is rendered and measured as the camera's frames are
(pixel size `aline_um_per_px` fitted, a 2 px blur, a 10% threshold), the camera's zeros and a
resolution floor fitted per evaluation. `--aline-knobs` chooses the knobs; `--workers` tracks
the steps in parallel (each with `--threads`). Many hours a fit.

`--profiles` fits the spectrometer EMQ scans' energy-resolved vertical profiles
(`energy_profiles.py`: `-ImageInterp` in 5 MeV slices), with `--profiles-spectrum` adding
Scan016's spectrum and `--profiles-knobs` choosing the knobs.

`--energy-reference early|late` picks which of the spectrometer driver's two field settings is
taken as right for every scan's energy axis (`scans.energy_axis`): the driver's axis in Scans
025 to 030 is Scan020's scaled by 0.833 and 0.824 while the beam stays on the same pixels.
`early` (the default) is the one the fits favour.

`python -m htu_twin_apps.lpa_source.aline_vertical <data> --source <saved>` (`aline_vertical.py`)
fits the A-line objective and the spectrometer EMQ scans' vertical profiles together, one set of
knobs for both (`--scale free`, the default, fits each camera's scale; a number fixes it).

`--log FILE` appends every evaluation of every fit to `FILE`, one JSON object a line, so a long
run can be followed and its best point recovered if it dies; every tenth is also printed.

`--threads` (default 4) sets torch's threads. Torch's default, one per core, makes tracking about
50 times slower on a 16-core machine (thread contention); with 4, five sources take about 10 s.

## How it works

- **Source** (`source.py`): `LPASource` is a handful of knobs sampled into an openPMD
  `ParticleGroup` at the plasma exit:
  - **Energy:** a Gaussian peak with an exponential high-energy tail (an exponentially modified
    Gaussian). Particles below a cut are dropped (15 MeV by default, fbpic's `uz > 30`).
  - **Size and divergence:** per plane, a waist at the plasma exit with an rms size, and an rms
    divergence that scales with energy as `E ** -divergence_power`.
  - **Pointing:** per plane, an angle plus a slope with energy.
  - Charge and bunch duration.

  `from_nersc()` sets the knobs from one run of the NERSC `initial_sample` dataset, which holds
  moments (means, the 6x6 covariance, charge), not particles. Its mean and rms energy are split
  evenly between the peak width and the tail; that split is a choice, not in the data.
- **Transport** (`twin.py`): the twin's line is built only up to `PIPE_AP8`, the end of the beam
  pipe at the spectrometer's entrance. Machine settings go through the twin's own
  `htu.model._apply_machine_state`. `SCAN016_STATE` is Scan016's: chicane, EMQs and steerers off
  except S1H at -2.7 A, whose sign convention against the twin's is not validated.

  Changes to the twin's line (all listed in `twin.py`'s docstring): the slit's shapes, magnet
  strength scales (`SCALES`), EMQ offsets (`OFFSETS`), a PMQ strength scale, per-PMQ rolls and
  offsets (`PMQ_ERROR_KEYS`, from Sam Barber's bench measurements), and the three below. The
  line built for a machine state is cached (`SEGMENT_CACHE` lines). First, the PMQs get fringe
  fields
  (`to_spectrometer(pmq_fringe_mm=3.0)`, the default; None keeps the twin's hard-edged PMQs). The
  PMQs are 16 to 29 mm long with a 6 mm bore radius, so their fringe is a large part of them.
  Each PMQ's gradient steps up and down as a logistic of width `pmq_fringe_mm` centred on the
  twin's hard edges, which keeps its integrated gradient exactly; the triplet's region is
  tracked as 2 mm slices whose gradient is the three profiles' sum, offset with the triplet,
  with the bore apertures at the magnets' ends. The 3 mm width (half the bore radius; 90% to 10%
  over about one bore diameter) is assumed: HTU has not given the PMQs' field profiles.
  Checks: the integrated gradient is kept to 0.014% (0.14% in |k1 L|, the tails cut 8 widths
  out); 1 mm slices give the same optics as 2 mm; a 0.1 mm width reproduces the hard-edged
  triplet's transfer matrix. At 100 MeV the 3 mm fringe weakens the triplet's vertical focusing
  (R43 -5.85 to -4.64 /m) and changes R33 from -0.26 to +0.06; the horizontal plane changes
  little. It makes tracking about 2.3 times slower. The fits below were made with hard-edged
  PMQs (before the fringe was added), except where marked; see "PMQ fringe: refit to Scan016".

  Second, the chicane dipoles get pole-face edges
  (`to_spectrometer(chicane_edges=True)`, the default; the twin's are sector bends). The magnets'
  shape is not known; assumed are rectangular magnets with every pole face perpendicular to the
  straight-through axis (BEND1 and BEND3 entered square and left at the bend angle, BEND2 and
  BEND4 the reverse), which cancels the bends' horizontal focusing and adds vertical focusing.
  The pole gap is not known either: `chicane_gap_m` 0 is a hard edge. At the 2026-09-29 setting
  (1.58 A, 14.8 mrad per bend in the twin) each magnet's vertical focal length is about 600 m,
  and the edges change the pointing fit's best chi^2 from 721.7 to 724.7 (724.1 with an assumed
  30 mm gap), within its seed noise; Scan016, with the chicane off, is unchanged.

  Third, the PMQ triplet's bore apertures (6 mm radius, at entrance and exit of each PMQ) move
  with the triplet. The twin offsets the PMQs by `pmq_x_mm` and `pmq_y_mm`
  but leaves those apertures on the axis. The difference is small: with the Scan016-fitted
  source, the distance changes by at most 0.04 for offsets within +-1 mm, and transmission only
  starts to differ at +-2 mm (0.000 to 0.002, 0.001 to 0.014). The strong sensitivity of the
  spectrum to the triplet's offset comes from the offset triplet steering the beam into the
  10 mm beam pipe downstream, not from the bores.
- **Comparison** (`compare.py`): the measured spectrum is the scan's averaged stitched
  `-interpSpec` spectrum (the GEECS ScanAnalysis `UC_BCaveMagSpecStitcher` output in
  `analysis/ScanNNN/`), in 2 MeV bins. The prediction is the transported charge's energies in the
  same bins. Both are normalized over the spectrometer's window (about 55 to 243 MeV), so shapes
  are compared, not charge; HTU's charge units are not known. `distance` is half the integral of
  the absolute difference: 0 for identical spectra, 1 for disjoint ones. Shot noise contributes
  about 0.005 at 50,000 particles.

  Comparing in energy needs neither the spectrometer's field, which is not logged, nor the twin's
  screen map, because HTU's analysis has already converted the screens to energy.
- **Fit** (`fit.py`): `fit()` minimizes `distance` over any `LPASource` knobs and twin
  machine-state keys with Nelder-Mead, restarting from where it stopped while that helps (the
  binned objective is flat in places, and one simplex can collapse early). Every evaluation
  samples with the same seed, so the objective is deterministic; `check()` resamples the fitted
  source with other seeds to show how much of the fit is that seed's noise. The line is built
  once, at a 100 MeV reference energy.
- **Vertical pointing** (`pointing.py`): the spectrometer cameras also record, per shot, a
  vertical profile (`UC_BCaveMagSpec<cam>-interpDiv`, against an "AngleAxis"). The spectrometer's
  LabVIEW driver (GEECS-Device-Drivers `MagSpecCamera`) makes the AngleAxis from each pixel's
  vertical screen position over its momentum's "total path" in the trajectory calibration file:
  an apparent angle in mrad, through the magnet's vertical optics. In the scans that step one EMQ
  while the spectrometer records (Scans 025, 028 and 030), the profiles' centroids and widths move
  with the EMQ current, which depends on where the beam is in the EMQs. For every step and camera:
  - each step's twin machine state is read from the scan table (EMQ setpoints, chicane, steerers);
    only the scanned EMQ channel is logged, so the others are taken at their nominal 1.5 / -0.82 /
    0 A;
  - the source is tracked with the slit's jaws out and reweighted, in 2 MeV bins, to the step's
    measured spectrum on that camera. The slit cuts horizontally, by energy, so this stands in for
    it; the twin's slit model does not reproduce Scan019;
  - the particles are projected (`--pointing-projection`):
    - `spectrometer` (the default): through the twin's model of this spectrometer
      (`htu.magspec.DutchCalibration`, built from HTU's own calibration files for its "Dutch
      magnet"): each particle's vertical screen position from the per-momentum map at its p / B,
      divided by that momentum's total path, as the driver does. B is the twin's `magspec_b`
      (0.825 T by default; the field was not logged). Only particles within the camera's
      AngleAxis range count, as on the camera (Cam1 +-23.5 mrad, Cam2 -17.5 to 19.75 mrad: the
      screen's height over the total path). Checked: the screen positions match the twin's own
      `map_to_screens` exactly. The magnet magnifies vertically: 1 mrad at its entrance appears
      as 6 to 10 mrad on the AngleAxis, 1 mm as 2.4 to 4.4 mrad;
    - `stand-in`: `Y = y + d y'` at the spectrometer entrance, with `d` from 0 to 0.45 m (what
      the fit used before the spectrometer was modelled);
  - per camera, a scale, a zero and a resolution floor are fitted (both cameras' scales of one
    sign), and the chi^2 that remains is minimized over `pointing_y_mrad`, `divergence_y_mrad`
    and `pmq_y_mm`.

  Frames are matched to shots with `htu_twin_apps.stacks`, shared with the shot viewer. Only the
  vertical plane is measured this way; horizontal is the spectrometer's dispersive plane.

## Why Scan016

Scan016 (2026-09-29, 5002 shots) is the only long scan with the chicane off, the slit out and the
EMQs off, so the PMQ triplet is the only optics between the source and the spectrometer. Its raw
folder is not in the sample data; its averaged spectrum and per-shot spectrum statistics
(`analysis/s16.txt`) are.

## First results (Scan016, 50,000 particles)

| Source | Transmitted | Peak (MeV) | Mean (MeV) | rms (MeV) | Distance |
|---|---|---|---|---|---|
| Measured | | 93.3 | 114.8 | 29.8 | |
| Twin default Gaussian (100 MeV, 5%) | 0.32 | 105.3 | 104.3 | 4.2 | 0.71 |
| NERSC `sim_0000` | 0.21 | 91.3 | 130.1 | 41.9 | 0.15 |
| NERSC `sim_0003` | 0.20 | 91.3 | 126.2 | 39.6 | 0.12 |
| NERSC `sim_0004` | 0.22 | 89.3 | 131.0 | 38.6 | 0.18 |
| `LPASource` defaults | 0.31 | 93.3 | 111.4 | 25.0 | 0.24 |

"Transmitted" is the fraction of the source charge reaching the spectrometer entrance; peak, mean
and rms are within the window.

## Fit to Scan016 (2026-10-30)

Fitting the energy and divergence knobs from `sim_0003` (other knobs, pointing and the PMQ
triplet's position at their `sim_0003` and twin values):

| | Distance | Other seeds | Peak / mean / rms at spectrometer (MeV) | Transmitted |
|---|---|---|---|---|
| `sim_0003` | 0.124 | | 91.3 / 126.2 / 39.6 | 0.20 |
| Fitted | 0.060 | 0.069 +- 0.004 | 93.3 / 117.7 / 32.4 | 0.24 |

Fitted knobs: `energy_mev` 56.6, `energy_sigma_mev` 41.7, `energy_tail_mev` 26.3 (a source
spectrum of mean 90 MeV, rms 43 MeV), `divergence_x_mrad` 12.9, `divergence_y_mrad` 3.1,
`divergence_power` 1.13.

What the fits show:

- **The measured peak is mostly the PMQ triplet's.** In the twin, the triplet and the beam pipe
  pass nothing below about 60 MeV, rise steeply to about 0.4 near 90 MeV and stay near 0.3 above.
  The fitted source spectrum has no 93 MeV peak; the transmission makes it. The source's peak
  energy and low-energy content are therefore poorly determined by this measurement.
- **The divergence is constrained.** Refitting the energy with the divergence held at 0.5 or 1.5
  times the fitted values only reaches 0.091 to 0.092 (0.096 to 0.102 with other seeds), against
  0.069. The source's mean energy (90 to 92 MeV) and rms (41 to 47 MeV) hardly move across those
  refits; its mode does (74 to 88 MeV).
- **Pointing, the PMQ triplet's x offset and S1H matter as much as the source.** Around the fit,
  1 mm of PMQ x offset raises the distance to 0.5 to 0.8, 3 mrad of pointing to about 0.15, and
  S1H at 0 to 0.146 (at +2.7 A, the opposite sign, 0.085). A spectrum alone cannot separate these
  from the divergence, so they are held fixed; the S1H result mildly favours the twin's sign
  convention, but pointing could absorb it.
- **What is left is not sampling noise.** The fitted 0.06 to 0.07 is well above the noise (about
  0.005). It includes a measured feature the twin cannot produce: the step at 129 MeV where the
  spectrometer's two cameras meet.

## PMQ fringe: refit to Scan016 (2026-10-30)

With the 3 mm fringe, the hard-edge fit's source is worse (distance 0.060 to 0.083; the spectrum's
peak moves from 93.3 to 87.3 MeV, as the softer vertical focusing shifts the triplet's
transmission edge). Refitting the same six knobs from it:

| PMQs | Distance | Other seeds | Peak / mean / rms (MeV) | `divergence_x` / `_y` (mrad) / power | `energy_mev` / `_sigma` / `_tail` |
|---|---|---|---|---|---|
| Hard-edged | 0.060 | 0.069 +- 0.004 | 93.3 / 117.7 / 32.4 | 12.9 / 3.1 / 1.13 | 56.6 / 41.7 / 26.3 |
| 3 mm fringe | 0.069 | 0.072 +- 0.002 | 91.3 / 116.6 / 32.0 | 16.2 / 2.7 / 1.38 | 52.8 / 43.4 / 25.0 |

The spectrum fits about equally well either way (the other-seed distances overlap): Scan016
cannot tell a hard edge from a 3 mm fringe, which the source's divergence absorbs (horizontal
25% larger, vertical 11% smaller with the fringe). The fringe matters for the fitted source, not
for the quality of the fit. It also trades off against the triplet's distance from the source:
before the refit, `pmq_z_mm` +10 alone brought the fringe's distance to 0.058. The vertical
pointing fit below was made with hard-edged PMQs; at its best point the fringe raises chi^2 from
724.7 to 760.1, and it has not been refitted with the fringe (about two hours at the fringe's
tracking cost).

## Vertical pointing fit (2026-10-30)

This fit used the `y + d y'` stand-in projection and hard-edged PMQs, before the spectrometer
was modelled. Through the spectrometer model, its best point scores chi^2 3,077 (against 725
through the stand-in), with camera scales of -0.04 and -0.15 rather than the +-1 expected: the
twin predicts much more variation across the scans' steps than the cameras saw. A fit through
the spectrometer model is the test of whether any source and offsets match.

From the Scan016-fitted source, with the twin's EMQ polarity; two starts agree:

| | Best fit | Rough 68% range |
|---|---|---|
| `pointing_y_mrad` | -1.67 | -2.06 to -1.52 |
| `pmq_y_mm` (twin frame) | -0.069 | -0.072 to -0.057 |
| `divergence_y_mrad` at 100 MeV | 4.1 (3.1 from the Scan016 fit) | 3.8 to 4.4 |

chi^2 723 over 180 measured numbers (Cam1 322, Cam2 401), at `d` = 0. The ranges are the points
the fit visited within 3.53 (68% for three parameters) times the chi^2 per degree of freedom of
the best, not a proper profile, and may understate the range; pointing and divergence are
correlated along a valley.

- **EMQ polarity.** Over a grid of pointing and divergence, flipping every EMQ current
  (`emq_sign=-1`) never fits better than chi^2 3,500, against about 1,050 with the twin's sign (at
  that stage, without the PMQ offset).
- **Scan029 is not used**: its EMQ3 steps change nothing on either camera, consistent with
  Scan030's description "(repeat, emq3 was not on)".
- **The PMQ offset is needed**: without it, chi^2 is about 1,050 and the two cameras' scales come
  out of opposite sign; +-0.3 mm raises chi^2 to 1,900 to 2,600. Moving the PMQ bore apertures
  with the triplet (see Transport) leaves the best point's chi^2 unchanged (721.7).
- **The widths constrain little**: the fitted floors (2.9 and 3.3) are most of the measured widths
  (3 to 4.5), so the centroids carry most of the information.
- **Open**: the best `d` is 0, the edge of its range, so the profiles behave more like a position
  than an angle at the entrance (the AngleAxis definition, or the spectrometer's own vertical
  focusing); the fit is poor, chi^2 about 4 per number; Scan030's Cam1 centroid and Scan025's
  widths at 2.1 to 2.2 A are the largest misfits.

## Not yet done

- Horizontal pointing and the PMQ triplet's horizontal and longitudinal position (`pmq_x_mm`,
  `pmq_z_mm`), which no measurement used here constrains.
- The vertical plane: the A-line scans need the EMQ fields 0.6 to 0.9 mm off the beam vertically,
  which the spectrometer scans' vertical profiles do not show, and through the spectrometer
  model the fitted camera scale is -0.07 to -0.26 where 1 is expected. The fits' results after
- Tests: none yet.
- Shot-to-shot spread: averages are compared, not single shots.
