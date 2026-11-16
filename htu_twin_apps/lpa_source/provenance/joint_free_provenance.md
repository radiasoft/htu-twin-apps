# How `aline_slit_spectrometer_free_scale.json` was made (2026-11-16)

`htu_twin_apps/twin_viewer/fits/aline_slit_spectrometer_free_scale.json`, the twin viewer's
default fit, is `joint_free_source.json`, the A-line and
spectrometer fit made together (`aline_vertical`) with the spectrometer cameras' scales free,
plus that fit's camera values (`spectrometer`: Cam1's and Cam2's scale, zero and floor, copied
from its printed result; `aline_vertical --save` now writes them itself). Before it, the default was
`slit_a_rescore.json` (now `fits/aline_slit.json`, [its provenance](slit_a_rescore_provenance.md)),
which is this fit's starting point. Times are UTC; `$F` is the directory the fits were written to.

## Rerunning it

```bash
python htu_twin_apps/lpa_source/provenance/rerun_joint_free.py <data root> <new directory>
```

[`rerun_joint_free.py`](rerun_joint_free.py) writes the start below from
`htu_twin_apps/twin_viewer/fits/aline_slit.json` (or `--start`, such as the
`slit_a_rescore.json` of a rerun of [the chain before it](slit_a_rescore_provenance.md)), runs the
command below, and writes `aline_slit_spectrometer_free_scale.json` in the viewer's format. It
checks the code first: it needs the spectrometer projection below (`--repo` chooses a checkout
of this repository if the installed one differs). The fit is
stochastic: a rerun gives similar, not identical, values.

The chain before it needs the earlier spectrometer model, so the two are rerun with different
code: [`rerun_slit_a_rescore.py`](rerun_slit_a_rescore.py) with this repository at `b09ef43`,
then `rerun_joint_free.py` with the code below. Both run with the stock geecs-lume-twin.

## Start

`$F/joint_aline_start.json`: `slit_a_rescore.json` with `emq3_y_mm` set to 0 (2026-11-15).

## Code

- The spectrometer maps' 1.970 m upstream drift removed. The run did it with a patch to
  geecs-lume-twin (`d43c140` plus `DutchCalibration.upstream_drift_m`, not merged: the twin is
  not this repository's); this repository now does it itself (`pointing.upstream_drift_m`), with
  the same results (checked 2026-11-16: the drift 1.9696 m either way, the viewer's Scan025
  spectrometer images unchanged), and needs only the stock twin. Without it the maps magnify
  vertical angles 6 to 10 times.
- This repository with `pointing`'s thresholded profiles (`pointing.THRESHOLD`, 0.1 of the
  peak), as `aline` measures its spots.

## Command (2026-11-16 02:47 to 11:25)

```bash
python -u -m htu_twin_apps.lpa_source.aline_vertical 26_0929 --root <data root>/Undulator \
    --source $F/joint_aline_start.json \
    --knobs aline_um_per_px,emq1_x_mm,emq1_y_mm,emq2_x_mm,emq2_y_mm,pointing_x_mrad,pointing_slope_x_mrad,divergence_x_mrad,pointing_y_mrad,divergence_y_mrad,s1h_scale,pmq_x_mm,pmq_y_mm,emq1_scale,emq2_scale,chicane_jaw1_mm,emq3_y_mm \
    --scale free --workers 6 --threads 2 \
    --log $F/joint_free.log --save $F/joint_free_source.json
```

## Result

1201 evaluations (best at 787): objective 4539.3 = A-line and Scan019 2671.6 + vertical 1867.7.

| Camera | chi^2 | scale | zero | floor |
|---|---|---|---|---|
| Cam1 | 561.2 | -0.311 | 2.951 | 0.552 |
| Cam2 | 1306.4 | -0.322 | 5.315 | 0.782 |

On the same objective, `slit_a_rescore.json` scores 5360 (2773 + 2587) and the fit with the
scales held at 1 (`joint_scale1_source.json`) 6508 (5033 + 1475).

The scales are the open question: the twin's COSY maps give the AngleAxis about +1.5 mrad per
mrad of angle at the spectrometer's entrance, consistent with a hard-edged dipole of the
trajectory file's geometry, and the fit wants about -0.47. Held at 1, the spectrometer wants a
vertical divergence of 0.42 mrad and the A-line spots 1.3 mrad; free, both fit with 1.41 mrad.
Until the spectrometer's vertical calibration is confirmed (a known vertical steering with the
spectrometer on, the COSY edge-angle convention, or the cameras' orientation), this fit holds on
that factor.
