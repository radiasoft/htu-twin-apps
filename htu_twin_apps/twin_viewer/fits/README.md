# The twin's fits

Each file here is a fit of the HTU twin to the recorded 2026-09-29 scans: the LPA source
(`source`, an `htu_twin_apps.lpa_source.source.LPASource`) and the fitted corrections to the line
(`machine_state`: magnet scales and offsets, the slit's jaws and blade, the A-line camera's pixel
size), and, if the fit measured them, the spectrometer cameras' calibration (`spectrometer`:
Cam1's and Cam2's scale, zero and floor of the AngleAxis). A file is named by what its values were
matched to. How the corrections join a scan step's settings is in
[`docs/machine-state-calls.md`](../../../docs/machine-state-calls.md).

| File | Matched to | Default |
|---|---|---|
| [`aline_slit_spectrometer_free_scale.json`](aline_slit_spectrometer_free_scale.json) | the A-line camera's EMQ scans, Scan019's slit spectra and the spectrometer's vertical profiles, together, with the spectrometer cameras' scales free | yes |
| [`aline_slit.json`](aline_slit.json) | the A-line camera's EMQ scans and Scan019's slit spectra (after a chain of earlier fits) | until 2026-11-16 |

Both scored on one objective (the A-line chi^2 plus Scan019's slit term, plus the spectrometer's
vertical chi^2 with thresholded profiles and the cameras' scales, zeros and floors fitted; 30,000
particles):

| File | A-line + slit | Spectrometer | Total | Camera scales (Cam1, Cam2) |
|---|---|---|---|---|
| `aline_slit_spectrometer_free_scale.json` | 2,672 | 1,868 | 4,539 | -0.311, -0.322 |
| `aline_slit.json` | 2,773 | 2,587 | 5,360 | -0.298, -0.328 |

With the cameras' scales held at 1 (the twin's own spectrometer model), `aline_slit.json`'s
spectrometer chi^2 is 152,500: its vertical divergence (1.32 mrad) and EMQ offsets swing and
widen the twin's beam on the spectrometer far beyond what the cameras saw. The best fit at scale
1 (`joint_scale1_source.json`, not kept here) scores 5,033 + 1,475 = 6,508, with a vertical
divergence of 0.42 mrad that makes the A-line spots a third of their measured size. Both
diagnostics fit together only with the cameras' scales near -0.31, which is the open question
below.

## Starting the viewer

`<repo>` is this repository's clone, `<data root>` the folder holding `Undulator/Y2026/...` (and
here `simulations/`, the fbpic density scan offered as extra sources). One viewer offers every fit
here in its source menu; the commands below differ in the fit it opens with (`--source`) and the
first fit's spectrometer calibration. Without installing the package, from the clone:

### `aline_slit_spectrometer_free_scale.json` (the default)

```bash
cd <repo>
PYTHONPATH=$PWD OMP_NUM_THREADS=4 python -u -m htu_twin_apps.twin_viewer.server 26_0929 26_1001 \
    --root <data root> \
    --source htu_twin_apps/twin_viewer/fits/aline_slit_spectrometer_free_scale.json \
    --fbpic <data root>/simulations/htu_den_scan \
    --port 8010 --particles 50000 --threads 4
```

`--source` can be left out (this is the default). Every fit here is in the page's source menu
whichever `--source` is given; `--source` chooses the one the page opens with. Each fit's cameras'
scales and zeros come from its file's `spectrometer`.

### `aline_slit.json`

```bash
cd <repo>
PYTHONPATH=$PWD OMP_NUM_THREADS=4 python -u -m htu_twin_apps.twin_viewer.server 26_0929 26_1001 \
    --root <data root> \
    --source htu_twin_apps/twin_viewer/fits/aline_slit.json \
    --fbpic <data root>/simulations/htu_den_scan \
    --port 8008 --particles 50000 --threads 4
```

The file has no `spectrometer` (the fit did not use the spectrometer cameras), so the viewer
shows the twin's spectrometer image at scale 1 and zero 0, with the vertical spot far larger than
measured and moving the other way. To show it with the calibration this fit scores best with
(the cameras' scales, zeros and floors fitted to it alone, 2026-11-16):

```bash
cd <repo>
PYTHONPATH=$PWD OMP_NUM_THREADS=4 python -u -m htu_twin_apps.twin_viewer.server 26_0929 26_1001 \
    --root <data root> \
    --source htu_twin_apps/twin_viewer/fits/aline_slit.json \
    --fbpic <data root>/simulations/htu_den_scan \
    --port 8008 --particles 50000 --threads 4 \
    --spectrometer-scale -0.298,-0.328 --spectrometer-zero 2.640,5.194
```

With the package installed, `htu-twin-viewer` replaces `python -u -m
htu_twin_apps.twin_viewer.server` (and `PYTHONPATH` is not needed); `--source` then takes the
file's path in the clone or the installed package.

## `aline_slit_spectrometer_free_scale.json`

Made 2026-11-16 by `aline_slit.json`'s values refitted with the A-line camera, Scan019 and the
spectrometer together (`htu_twin_apps.lpa_source.aline_vertical`, `--scale free`): the run, its
command and its code state are in
[`lpa_source/provenance/joint_free_provenance.md`](../../lpa_source/provenance/joint_free_provenance.md).
[`rerun_joint_free.py`](../../lpa_source/provenance/rerun_joint_free.py) reruns it (with the
code it was made with: it checks). It started from `aline_slit.json` with EMQ3's vertical offset at
0 and fitted 17 knobs: the
A-line camera's pixel size; EMQ1's and EMQ2's x and y offsets and scales; EMQ3's y offset; the
PMQ triplet's x and y offsets; the source's horizontal pointing, pointing slope and divergence and
its vertical pointing and divergence; S1H's scale; the chicane's first jaw. 1,201 evaluations,
the best at 787.

The data: the A-line camera's Scans 023 (EMQ1) and 026 (EMQ2), each step's spot centroid and rms
in x and y; Scan019's spectra through the chicane slit; the spectrometer's Scans 025, 028 (the same
EMQ1 and EMQ2 currents with the spectrometer on) and 030 (EMQ3), each step's vertical profile
centroid and rms on Cam1 and Cam2.

Assumptions:

- **Everything `aline_slit.json` assumed** that this fit did not refit (below): the source's
  energy spectrum, size and charge, the PMQ fringe, the slit's second jaw and blade, EMQ3's x
  offset and scale, the energy labels.
- **The spectrometer model.** `htu.magspec.DutchCalibration`: HTU's COSY third-order maps of the
  Dutch magnet per momentum, at 0.825 T (the field was not logged), with the maps' 1.970 m
  upstream drift removed (they start at the source plane, not the magnet's entrance;
  `pointing.upstream_drift_m`: the twin's own `map_to_screens` leaves it in). Each particle's AngleAxis is its vertical
  screen position over its momentum's total path, as the GEECS MagSpecCamera driver computes it
  (checked 2026-11-16 on Scan025's raw frames against the driver's interpolated images: (centre
  row - row) x pixel size / total path, to about 20%; see `pointing`'s docstring); only what falls
  in each camera's AngleAxis range counts.
- **Each camera's AngleAxis is a scale times the twin's, plus a zero, with its rms widened by a
  resolution floor**, all three fitted per camera. The scales came out -0.311 and -0.322: the
  cameras see the beam's vertical angle about 0.31 times as large as the twin's map gives, and
  inverted. The map itself agrees with a hard-edged dipole of the trajectory file's geometry
  (+1.4 to +1.5 mrad per mrad), and the driver's AngleAxis is what the twin assumes (above), so
  this factor is **not explained**. Ruled out: the driver's definition, and (less firmly) a
  reversed edge-angle convention in the maps, since the design defocuses vertically where it
  focuses in the bend plane (Nakamura et al., Rev. Sci. Instrum. 79, 053301, 2008). Left: for the
  sign, whether the top of each camera's frame is up in the lab (`CameraFlipped` is off; a mirror
  between screen and camera would invert it); for the factor of about 3, the beam or optics
  before the screen (the real vertical focusing in the 25 mm gap, the field, 0.825 T assumed,
  where the beam enters the magnet, or the twin's line upstream). The fit stands on it until the
  spectrometer's vertical calibration is checked (a known vertical steering with the spectrometer
  on would settle it); the questions for HTU are in
  [`docs/htu-twin-questions.md`](../../../docs/htu-twin-questions.md).
- **Profiles thresholded.** A spectrometer profile's centroid and rms count only its bins above
  10% of its peak, the twin's particles binned onto the camera's AngleAxis first
  (`pointing.THRESHOLD`), as the A-line spots are measured: the measured profiles have broad,
  nearly constant wings that held the whole profile's rms at 3 to 4.5.
- **The spectrometer steps are reweighted** to each step's measured spectrum on that camera, in
  2 MeV bins, with the chicane slit out (the slit is not logged; its cut is horizontal, by
  energy, which the reweighting stands in for). The A-line steps are reweighted to the partner
  spectrometer scan's spectrum at the same step.
- **One objective, summed**: the A-line chi^2 and Scan019's slit term (each step's spectral
  distance with an error of 0.02) plus the spectrometer's vertical chi^2, unweighted. The A-line
  part has 120 numbers, the spectrometer part 180.

Fitted (selected): vertical divergence 1.41 mrad, vertical pointing -0.10 mrad; EMQ1, EMQ2, EMQ3 y
offsets 0.60, 0.41, 0.51 mm; EMQ1, EMQ2 x offsets 1.43, 0.87 mm; EMQ1, EMQ2 scales 1.08, 1.27;
horizontal divergence 6.95 mrad; A-line pixel size 83.2 um. Camera zeros 2.95 (Cam1) and 5.31
(Cam2), floors 0.55 and 0.78.

## `aline_slit.json`

Byte-identical to `slit_a_rescore.json`, the end of a 17-step chain of fits (2026-10-30 to
11-03) traced step by step, with the commands, in
[`lpa_source/provenance/slit_a_rescore_provenance.md`](../../lpa_source/provenance/slit_a_rescore_provenance.md);
[`rerun_slit_a_rescore.py`](../../lpa_source/provenance/rerun_slit_a_rescore.py) reruns the
chain, with the code it was made with (this repository at `b09ef43`, before its spectrometer
projection removed the maps' upstream drift: the provenance says how; the script refuses the later
code for the steps that use the spectrometer). It was the viewer's default fit, `twin-fit-values.json`, until
2026-11-16. In short:

1. The source from the NERSC FBPIC sample (`sim_0003`), fitted to Scan016's spectrum (energy
   spectrum and divergences), then refitted with the PMQs' 3 mm fringe fields.
2. The vertical pointing, PMQ y offset and vertical divergence fitted to the spectrometer's
   vertical profiles (Scans 025, 028), then jointly with Scan016's spectrum, then the vertical
   scales.
3. The chicane slit fitted to Scan019's spectra, as two jaws and then jaws plus a blade.
4. The A-line camera's Scans 023 and 026 fitted with Scan019 (`compare --aline`), adding the EMQ
   offsets, then the camera's pixel size and the vertical divergence; refitted on the corrected
   energy axis.
5. The slit's jaws refitted on that result (`compare --slit jaws_blade`), and laid over it.

Assumptions:

- **The source** is `LPASource`'s model: a peaked energy spectrum with a low-energy tail and a
  minimum, an energy-dependent divergence (a power of energy), Gaussian size and pointing with a
  horizontal pointing slope across energy. It started from one FBPIC run.
- **The line** is the twin's (`geecs-lume-twin`): the PMQ triplet with 3 mm fringe fields, the
  chicane with rectangular pole-face edges, the slit as two jaws and a blade (its effective
  positions fitted: the slit is not logged), the EMQ triplet with fitted scales and offsets (bounds
  +-5 mm), a field-free drift of 1.685 m to the A-line camera with the spectrometer off.
- **The A-line camera**: its pixel size fitted (one for both axes: the twin's geometry for it is a
  placeholder), its orientation fixed, the rendered spot blurred by 2 px and thresholded at 10% of
  its peak like the camera's frames, a zero per axis and a resolution floor fitted per evaluation.
- **The energy labels**: Scans 025 to 030's spectra relabelled to the 2026-09-29 early driver
  setting (their recorded labels were 17% low).
- **The spectrometer did not constrain the final values.** Step 2 used the twin's spectrometer
  model before the upstream drift was removed, when it magnified vertical angles 6 to 10 times;
  the later steps refitted the vertical divergence and pointing and the EMQ y offsets from the
  A-line camera alone. Seen through today's spectrometer model at scale 1 it fits the
  spectrometer badly (above).
- **Code state**: the working tree between commits `3c1b8e5` and `33144ef`, and some steps were
  inline snippets or rebuilt from logs after crashes (the provenance's caveats); `compare` fits
  are stochastic, so a rerun gives similar, not identical, values.

Fitted (selected): vertical divergence 1.32 mrad, vertical pointing -0.09 mrad; EMQ1, EMQ2 y
offsets 0.69, 0.60 mm (EMQ3's not fitted, 0); EMQ1, EMQ2 x offsets 1.38, 1.11 mm; EMQ1, EMQ2
scales 1.07, 1.28; horizontal divergence 7.69 mrad; A-line pixel size 79.3 um.
