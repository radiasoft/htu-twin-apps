# How `slit_a_rescore.json` was made

## What this produced in this repository

`slit_a_rescore.json` is the fit result that `htu_twin_apps/twin_viewer/twin-fit-values.json`
holds: the two files are byte-identical (checked 2026-11-04). The twin viewer reads it with
`htu-twin-viewer <data directory> --source twin-fit-values.json`. This document traces how that
file was made, from the NERSC sample through 17 steps, and `rerun_slit_a_rescore.py` in this
directory reruns the whole chain (writing `slit_a_rescore.json` to a directory you choose).

Reconstructed 2026-11-04 from the fit runs' output directory, its queue scripts and the
2026-10-30..11-03 session history. Times are UTC. `$D` is the HTU sample data directory, `$F` the
directory the fits were written to, and every command runs from the repository root. `compare` is
`python -u -m htu_twin_apps.lpa_source.compare` (the `htu-lpa-source` entry point).

## The chain

```
NERSC sim_0003 (sample_dataset.json)
  -> scratch fit script .......... fit_scan016_b.json  (scratchpad)      [1]
  -> scan016_source.json (hard edge, = $F/scan016_hard_edge_source.json) [2]
  -> compare --fit ............... scan016_fringe_source.json            [3]
  -> compare --pointing .......... pointing_spectrometer_source.json     [4]
  -> compare --joint ............. joint_source.json                     [5]
       |-> compare --joint-no-spectrum .. vertical_scales_source.json    [6]
  scan016_fringe_source.json
  -> compare --slit jaws ......... slit_jaws_source.json                 [7]
  -> compare --slit jaws_blade ... slit_jaws_blade_source.json           [8]
  vertical_scales + slit_jaws_blade
  -> inline python ............... aline_start_plus.json                 [9]
  -> compare --aline ............. aline_plus_source.json                [10]
  -> compare --aline (+EMQ offsets) aline_offsets_source.json            [11]
  -> compare --aline (+pixel size)  aline_image_source.json              [12]
  -> inline python ............... aline_axis_start.json                 [13]
  -> compare --aline ............. aline_axis.log -> aline_axis_source.json [14]
  -> queue_slit_ab.sh:
       aline_axis_source.json -> slit_a_start.json                       [15]
       compare --slit jaws_blade .. slit_a_source.json                   [16]
       aline_axis_source.json + slit_a_source.json -> slit_a_rescore.json [17]
```

(The file the queue script reads is `aline_axis_source.json`; its loop variable `$2` is `axis`.
`slit_a` means "energy axis A", not a file name stem for the A-line.)

## Steps

**[1] Scan016 fit, hard-edged PMQs** (2026-10-30 19:07). Scratch script `fit_scan016_b.py`
(its logic now lives in `rerun_slit_a_rescore.py` (this directory), step 1). Starts from the NERSC FBPIC sample `sim_0003`.
```
PYTHONPATH=$PWD python -u fit_scan016_b.py $D \
  <path>/runs/initial_sample/sample_dataset/sample_dataset.json \
  fit_scan016_b.json
```

**[2]** Key `"energy + divergence"` of `fit_scan016_b.json` wrapped as a start file:
```
python3 -c "import json; d=json.load(open('fit_scan016_b.json'))['energy + divergence']['source']; \
  json.dump({'source':d,'machine_state':{}}, open('scan016_source.json','w'), indent=1)"
cp scan016_source.json $F/scan016_hard_edge_source.json
```

**[3] Refit with the 3 mm PMQ fringe** (2026-10-30 21:38):
```
compare $D --source scan016_source.json \
  --fit energy_mev,energy_sigma_mev,energy_tail_mev,divergence_x_mrad,divergence_y_mrad,divergence_power \
  --save scan016_fringe_source.json --out scan016_fringe.png        # copied to $F
```

**[4] Vertical pointing through the spectrometer model** (2026-10-30 22:28):
```
compare $D --source $F/scan016_fringe_source.json --pointing \
  --save pointing_spectrometer_source.json --out pointing_spectrometer.png   # copied to $F
```

**[5] Joint fit** (Scan016 spectrum plus Scans 025, 028 vertical profiles; queued after [4]):
```
compare $D --source $F/pointing_spectrometer_source.json --joint \
  --log $F/joint.log --save $F/joint_source.json --out $F/joint.png
```

**[6] Vertical scales** (2026-10-31 21:54):
```
compare $D --source $F/joint_source.json --joint --joint-no-spectrum \
  --joint-knobs pointing_y_mrad,pmq_y_mm,divergence_y_mrad,emq1_scale,emq2_scale,magspec_b \
  --joint-train Scan025,Scan028 --joint-held-out Scan030 \
  --log $F/vertical_scales.log --save $F/vertical_scales_source.json --out $F/vertical_scales.png
```
It crashed in the final comparison; `vertical_scales_source.json` was written afterwards from the
best line of the log on top of `joint_source.json` (see README).

**[7] Slit as two jaws** (2026-10-30 23:04):
```
compare $D --source $F/scan016_fringe_source.json --slit jaws \
  --log $F/slit_jaws.log --save $F/slit_jaws_source.json --out $F/slit_jaws.png
```

**[8] Jaws plus blade** (2026-10-31 21:56):
```
compare $D --source $F/slit_jaws_source.json --slit jaws_blade \
  --log $F/slit_jaws_blade.log --save $F/slit_jaws_blade_source.json --out $F/slit_jaws_blade.png
```

**[9] A-line starts** (2026-11-01 19:53), inline Python: the `vertical_scales` source and machine
state (minus `magspec_b`), with `divergence_x_mrad`, `pointing_x_mrad`, `pointing_slope_x_mrad` and the
four slit keys (`chicane_jaw1_mm`, `chicane_jaw2_mm`, `slit_blade_low_mm`, `slit_blade_high_mm`)
taken from `slit_jaws_blade_source.json`; `s1h_scale` = +1 (plus) or -1 (minus). Written to
`aline_start_plus.json` and `aline_start_minus.json`. Only plus continues.

**[10] A-line fit** (2026-11-01 20:11; the plus run started with the default `--aline` knobs):
```
compare $D --source $F/aline_start_plus.json --aline --workers 3 --threads 2 \
  --log $F/aline_plus.log --save $F/aline_plus_source.json --out $F/aline_plus.png
```

**[11] EMQ offsets added** (2026-11-02 08:57; 13 knobs):
```
compare $D --source $F/aline_plus_source.json --aline \
  --aline-knobs emq1_x_mm,emq1_y_mm,emq2_x_mm,emq2_y_mm,pointing_x_mrad,pointing_slope_x_mrad,divergence_x_mrad,pointing_y_mrad,s1h_scale,pmq_x_mm,emq1_scale,emq2_scale,chicane_jaw1_mm \
  --workers 5 --threads 2 --log $F/aline_offsets.log --save $F/aline_offsets_source.json --out $F/aline_offsets.png
```
(`fit.py` EMQ offset bounds were widened to +-5 mm just before this.)

**[12] Camera pixel size and vertical divergence added** (2026-11-02 16:51; 15 knobs). `fit.py`
got an `aline_um_per_px` bound (50..500) just before:
```
compare $D --source $F/aline_offsets_source.json --aline \
  --aline-knobs aline_um_per_px,emq1_x_mm,emq1_y_mm,emq2_x_mm,emq2_y_mm,pointing_x_mrad,pointing_slope_x_mrad,divergence_x_mrad,pointing_y_mrad,divergence_y_mrad,s1h_scale,pmq_x_mm,emq1_scale,emq2_scale,chicane_jaw1_mm \
  --workers 5 --threads 2 --log $F/aline_image.log --save $F/aline_image_source.json --out $F/aline_image.png
```

**[13] `aline_axis_start.json`** (2026-11-02 22:28), after `scans.energy_axis` fixed Scans 025-030's
17%-low energy labels (code change at 22:26): `aline_image_source.json` plus the pixel size of the
best line of `aline_image.log`:
```
python3 - <<'PY'
import json, pathlib
F = pathlib.Path("<fits directory>")
j = json.loads((F / "aline_image_source.json").read_text())
r = [json.loads(x) for x in open(F / "aline_image.log")]
j["machine_state"]["aline_um_per_px"] = min(r, key=lambda x: x["value"])["values"]["aline_um_per_px"]
(F / "aline_axis_start.json").write_text(json.dumps(j, indent=1))
PY
```

**[14] A-line fit on the corrected axis A** (same 15 knobs as [12]; 3 workers):
```
compare $D --source $F/aline_axis_start.json --aline --aline-knobs <the 15 knobs of [12]> \
  --workers 3 --threads 2 --log $F/aline_axis.log --save $F/aline_axis_source.json --out $F/aline_axis.png
```
It was killed at 1,121 evaluations by the memory/OOM problem (README, 2026-11-03 06:40), so **the
`aline_axis_source.json` on disk was not written by this command**. It was rebuilt on 2026-11-03
06:54 from the lowest-`value` line of `aline_axis.log` (3,340.3 at evaluation 1,095) laid over
`aline_axis_start.json` by a one-off `start` shell function (a copy of the one in
`queue_multistart.sh`, which runs inline Python), as
`start $F/aline_axis.log 0 $F/aline_axis_source.json`. Each log value goes into `source` if it is a
field of `LPASource`, else into `machine_state`; the `0` means no random kick of the knobs.
`rerun_slit_a_rescore.py` (this directory) does the same in `_from_log`.

**[15]-[17]** `queue_slit_ab.sh` (waited for `aline_noyoff`, PID 3583560, to end; ran 12:26-14:07):
```
# [15] drop the A-line-only pixel size
j = json.load(open("$F/aline_axis_source.json")); j['machine_state'].pop('aline_um_per_px', None)
json.dump(j, open("$F/slit_a_start.json", "w"), indent=1)

# [16]
compare $D --source $F/slit_a_start.json --slit jaws_blade \
    --slit-knobs chicane_jaw1_mm,chicane_jaw2_mm --threads 2 --log $F/slit_a.log \
    --save $F/slit_a_source.json --out $F/slit_a.png

# [17] overwrite the jaw and blade entries
j = json.load(open("$F/aline_axis_source.json"))
k = json.load(open("$F/slit_a_source.json"))['machine_state']
j['machine_state'].update({x: v for x, v in k.items() if 'jaw' in x or 'blade' in x})
json.dump(j, open("$F/slit_a_rescore.json", "w"), indent=1)
```
Then `rescore_ab.py` scored it (it reads the file, does not write it).

## Caveats

- **Code version.** Everything ran from the working tree, which was uncommitted until commit
  `3c1b8e5` (2026-11-02 22:04) and then edited again (step [13]'s energy-axis fix at 22:26, the
  `twin.SEGMENT_CACHE` bound, and more) before `33144ef` (2026-11-03 17:49). The closest commit to
  steps [14]-[17] is `33144ef`; it also holds later additions (PMQ roll keys, `aline_vertical`)
  that should not change results at their defaults, but that is not tested.
- **Not reproducible from the repo alone:** step [1] (a scratch script, now folded into
  `rerun_slit_a_rescore.py` (this directory), and the external NERSC sample), steps [9], [13] and [17] (inline snippets), step [14]'s rebuilt
  output, and the manual crash recoveries in the README. `compare` fits are also stochastic
  (seeded sampling, multi-restart), so rerunning gives similar but not identical values.
- `joint_source.json` (step [5]) was queued by a one-off shell loop rather than a saved script.
