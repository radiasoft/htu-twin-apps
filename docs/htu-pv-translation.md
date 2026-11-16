# HTU PV names: the twin's, GEECS's and the machine state's

How the HTU transport line's devices are named in GEECS (HTU's control system), in the EPICS names
its gateway builds, in the HTU twin's PVs (`geecs-lume-twin`, prefix `HTU:SIM:`) and in this
repository's machine state (`htu_twin_apps.machine_state`), with what is known of each one's
calibration, and pointers to the questions for HTU that the recorded data could not answer.

Sources:

- GEECS-Plugins code, tests and configs.
- Recorded HTU data from 2026-09-29 (scans 14 to 31) and 2026-10-01: the per-shot scan tables
  (`ScanDataScanNNN.txt`, `analysis/sNN.txt`) log about 460 device variables, the
  `ScanInfoScanNNN.ini` files name the variable each scan stepped, and the data's README.
- The twin fitted to that data: the fitted values are in `htu_twin_apps/twin_viewer/fits/`,
  described in its README and traced by `htu_twin_apps/lpa_source/provenance/`.
- The Genesis meeting slides of 2026-10-14 (the PMQ triplet's pulsed-wire alignment, slides 8 to
  12; HTU shots' ICT charge, slides 25 to 32).

Nothing here has been checked against the GEECS database or a live IOC. The sample data is two days
of scans, and a device that saved nothing those days is absent from it, not proven missing.

The GEECS names are the authoritative ones: the author of GEECS provides the EPICS interface. The
twin's names are the ones to map or change, not the GEECS ones.

## The machine state in code

`htu_twin_apps.machine_state.KEYS` names every value of the transport line's machine state. A
**setting** is logged by GEECS for each shot; `from_geecs()` reads a scan step's settings, and
`htu_twin_apps.pv_access` reads them live over PV Access (`Live`) or from a scan folder
(`archive()`). The table below is the code's (`tests/docs_test.py` checks that they agree):

| Key | GEECS scan-table column | EPICS name (`pv_name`) | Twin PV (`twin_name`) | Unit | Nominal |
|---|---|---|---|---|---|
| `chicane_current` | `U_ChicaneInner Current` | `undulator:u_chicaneinner:current` | `HTU:SIM:ChicaneDipole_Current` | A |  |
| `EMQ1H` | `U_EMQTripletBipolar Current_Limit.Ch1` | `undulator:u_emqtripletbipolar:current_limit_ch1` | `HTU:SIM:EMQ1H_Current` | A | 1.5 |
| `EMQ2V` | `U_EMQTripletBipolar Current_Limit.Ch2` | `undulator:u_emqtripletbipolar:current_limit_ch2` | `HTU:SIM:EMQ2V_Current` | A | -0.82 |
| `EMQ3H` | `U_EMQTripletBipolar Current_Limit.Ch3` | `undulator:u_emqtripletbipolar:current_limit_ch3` | `HTU:SIM:EMQ3H_Current` | A | 0 |
| `S1H` | `U_S1H Current` | `undulator:u_s1h:current` | `HTU:SIM:S1H_Current` | A |  |
| `S1V` | `U_S1V Current` | `undulator:u_s1v:current` | `HTU:SIM:S1V_Current` | A |  |
| `S2H` | `U_S2H Current` | `undulator:u_s2h:current` | `HTU:SIM:S2H_Current` | A |  |
| `S2V` | `U_S2V Current` | `undulator:u_s2v:current` | `HTU:SIM:S2V_Current` | A |  |
| `S3H` | `U_S3H Current` | `undulator:u_s3h:current` | `HTU:SIM:S3H_Current` | A |  |
| `S3V` | `U_S3V Current` | `undulator:u_s3v:current` | `HTU:SIM:S3V_Current` | A |  |
| `S4H` | `U_S4H Current` | `undulator:u_s4h:current` | `HTU:SIM:S4H_Current` | A |  |
| `S4V` | `U_S4V Current` | `undulator:u_s4v:current` | `HTU:SIM:S4V_Current` | A |  |
| `VS1H` | `U_VS1H Current` | `undulator:u_vs1h:current` | `HTU:SIM:VS1H_Current` | A |  |
| `VS1V` | `U_VS1V Current` | `undulator:u_vs1v:current` | `HTU:SIM:VS1V_Current` | A |  |
| `VS2H` | `U_VS2H Current` | `undulator:u_vs2h:current` | `HTU:SIM:VS2H_Current` | A |  |
| `VS2V` | `U_VS2V Current` | `undulator:u_vs2v:current` | `HTU:SIM:VS2V_Current` | A |  |
| `VS3H` | `U_VS3H Current` | `undulator:u_vs3h:current` | `HTU:SIM:VS3H_Current` | A |  |
| `VS3V` | `U_VS3V Current` | `undulator:u_vs3v:current` | `HTU:SIM:VS3V_Current` | A |  |
| `VS4H` | `U_VS4H Current` | `undulator:u_vs4h:current` | `HTU:SIM:VS4H_Current` | A |  |
| `VS4V` | `U_VS4V Current` | `undulator:u_vs4v:current` | `HTU:SIM:VS4V_Current` | A |  |
| `VS5H` | `U_VS5H Current` | `undulator:u_vs5h:current` | `HTU:SIM:VS5H_Current` | A |  |
| `VS5V` | `U_VS5V Current` | `undulator:u_vs5v:current` | `HTU:SIM:VS5V_Current` | A |  |
| `VS6H` | `U_VS6H Current` | `undulator:u_vs6h:current` | `HTU:SIM:VS6H_Current` | A |  |
| `VS6V` | `U_VS6V Current` | `undulator:u_vs6v:current` | `HTU:SIM:VS6V_Current` | A |  |
| `VS7H` | `U_VS7H Current` | `undulator:u_vs7h:current` | `HTU:SIM:VS7H_Current` | A |  |
| `VS7V` | `U_VS7V Current` | `undulator:u_vs7v:current` | `HTU:SIM:VS7V_Current` | A |  |
| `VS8H` | `U_VS8H Current` | `undulator:u_vs8h:current` | `HTU:SIM:VS8H_Current` | A |  |
| `VS8V` | `U_VS8V Current` | `undulator:u_vs8v:current` | `HTU:SIM:VS8V_Current` | A |  |

A nominal value is the one a step takes when its scan does not log the setting (HTU's 2026-09-29
EMQ setpoints). The EPICS names are the readbacks; a setpoint adds `:SP`. `VS6H` to `VS8V` are twin
inputs with no device found at HTU (see "Magnets").

A **correction** is fitted to the recorded scans, not logged; its fitted value is in
each fit file of `htu_twin_apps/twin_viewer/fits/`, and the twin applies it (`htu_twin_apps/lpa_source/twin.to_spectrometer`):

| Key | Unit | What it is |
|---|---|---|
| `emq1_scale` | 1 | EMQ1H's strength over the twin's |
| `emq1_x_mm` | mm | EMQ1H's x offset |
| `emq1_y_mm` | mm | EMQ1H's y offset |
| `emq2_scale` | 1 | EMQ2V's strength over the twin's |
| `emq2_x_mm` | mm | EMQ2V's x offset |
| `emq2_y_mm` | mm | EMQ2V's y offset |
| `emq3_scale` | 1 | EMQ3H's strength over the twin's |
| `emq3_x_mm` | mm | EMQ3H's x offset |
| `emq3_y_mm` | mm | EMQ3H's y offset |
| `s1h_scale` | 1 | S1H's strength over the twin's |
| `pmq_x_mm` | mm | PMQ triplet's x offset |
| `pmq_y_mm` | mm | PMQ triplet's y offset |
| `pmq_z_mm` | mm | PMQ triplet's z offset |
| `pmq_scale` | 1 | every PMQ's gradient over the twin's |
| `pmq1_roll_deg` | deg | PMQ 1's roll |
| `pmq1_dx_mm` | mm | PMQ 1's x offset in the triplet |
| `pmq1_dy_mm` | mm | PMQ 1's y offset in the triplet |
| `pmq2_roll_deg` | deg | PMQ 2's roll |
| `pmq2_dx_mm` | mm | PMQ 2's x offset in the triplet |
| `pmq2_dy_mm` | mm | PMQ 2's y offset in the triplet |
| `pmq3_roll_deg` | deg | PMQ 3's roll |
| `pmq3_dx_mm` | mm | PMQ 3's x offset in the triplet |
| `pmq3_dy_mm` | mm | PMQ 3's y offset in the triplet |
| `chicane_jaw1_mm` | mm | chicane slit jaw 1's edge |
| `chicane_jaw2_mm` | mm | chicane slit jaw 2's edge |
| `slit_blade_low_mm` | mm | chicane slit blade's low edge |
| `slit_blade_high_mm` | mm | chicane slit blade's high edge |

## How real names are built

A GEECS variable is `Device:Variable`, for example `U_S1H:Current`. The EPICS gateway turns it into
`experiment:device:variable` (`geecs_core/pv_naming.py`): each part lowercased, and every character
other than letters, digits and `_` (space, `.`, `-`) replaced by `_`. A setpoint PV adds `:SP`.
Test example: `undulator:u_s1h:current`. For the EMQ triplet that gives
`undulator:u_emqtripletbipolar:current_limit_ch1` (set) and `...:current_ch1` (measured).

The scan tables write the same variables as `Device Variable` (a space, not a colon), for example
`U_EMQTripletBipolar Current_Limit.Ch1`. The data sits under `Undulator/Y2026/...`, the same
experiment name the GEECS tests use for the PV prefix.

The twin's names are flat and CamelCase (`HTU:SIM:EMQ1H_Current`): no experiment or device part.

## Status key

- **recorded**: the device and variable are logged in the sample data.
- **confirmed**: the real device and variable appear in GEECS-Plugins code, tests or configs.
- **inferred**: the device exists, but the variable or the pairing is my reading, not stated.
- **unknown**: no counterpart found. Needs the HTU controls team.

"Fitted" in the tables below means a value or correction the twin's fits to the recorded scans
found; those are calibration findings, not names, and are to be confirmed by HTU's measurements.

## Magnets

| Twin PV (`HTU:SIM:`) | Unit | GEECS `Device:Variable` | Conversion | Status |
|---|---|---|---|---|
| `EMQ1H_Current` | A | `U_EMQTripletBipolar:Current_Limit.Ch1` (set, signed), `Current.Ch1` (measured, unsigned) | none (amps both sides); take the sign from the setpoint | recorded; Scans 23 and 25 step `Current_Limit.Ch1`. Nominal 1.5 A from Scan022 on, off before (README). The scans span 1.0 to 2.2 A, outside the Badger range [0.5, 1.3] A; the twin default is 0.68 A. Fitted strength: `emq1_scale` |
| `EMQ2V_Current` | A | `U_EMQTripletBipolar:Current_Limit.Ch2`, `Current.Ch2` | as EMQ1 | recorded; Scans 26 and 28 step `Current_Limit.Ch2`. Nominal -0.82 A, inside the Badger range [-1.5, -0.4] A, near the twin default -0.88 A. Fitted strength: `emq2_scale` |
| `EMQ3H_Current` | A | `U_EMQTripletBipolar:Current_Limit.Ch3`, `Current.Ch3` | as EMQ1 | recorded; Scans 29 to 31 step `Current_Limit.Ch3` (-0.6 to 0.6 A; nominal 0; not powered in Scan029). Pairing with EMQ3H inferred from the channel order |
| `S1H_Current` ... `S4V_Current` | A | `U_S1H:Current`, `U_S1V`, `U_S2H`, `U_S2V`, `U_S3H`, `U_S3V`, `U_S4H`, `U_S4V` (`:Current`) | the twin's datasheet calibration; see S1H | recorded (also `:Voltage`). On 9/29 S1H = -2.7 A (from Scan002 on) and S3H = -2.0 A (from Scan022 on, with the EMQs), the rest about 0 |
| `S1H_Current` (calibration) | A | `U_S1H:Current` | the twin's kick per amp is too strong, or S1H was not acting: fitted at a few percent of the twin's calibration (`s1h_scale`), with the logged sign | fitted (A-line scans 23 and 26 with Scan019): at full strength the twin steers the beam 6 to 8 mm off axis through the EMQs, which the measured spot positions rule out |
| `VS1H_Current` ... `VS4V_Current` | A | `U_VS1H:Current` ... `U_VS4V:Current` | none | recorded (also `:Voltage`) |
| `VS5H_Current`, `VS5V_Current` | A | `U_VS5H:Current`, `U_VS5V:Current` | none | recorded |
| `VS6H_Current` ... `VS8V_Current` | A | none found | | not in the data or in GEECS-Plugins; probably no such magnets. Confirm with HTU |
| `ChicaneDipole_Current` | A | `U_ChicaneInner:Current` and `U_ChicaneOuter:Current` | one twin knob is two real supplies, with Outer = -Inner | recorded; Scan019 shows Outer = -Inner to within 0.001 A at every step. See "Chicane calibration" below |
| `Chicane_R56_um` (read-only) | um | `R56_at_100MeV` (a composite variable, logged as a scan column with no device part) | `I_inner = sqrt(100^2 * R56 / 560968.636)` (the constant is in `GUI_HTU_Chicane.vi`) | recorded; Scan019 steps it from 50 to 275 um, and the logged currents follow the formula |
| `ChicaneSlit_Jaw1_mm`, `ChicaneSlit_Jaw2_mm` | mm | none logged; `U_ChicaneMotors` (`Ch1Ax1`, `Ch1Ax2`, Newport 8752 open-loop picomotors) logs only `Ch1Ax1StepSize`; its driver keeps a step-count `Position` | the twin's jaw positions are lab-frame offsets from the R56 = 0 axis | unknown. Fitted: one jaw and a narrow blade inside it (`chicane_jaw1_mm`, `slit_blade_low_mm`, `slit_blade_high_mm`) |
| `PMQTriplet_{X,Y,Z}_mm` | mm | `U_Hexapod:ypos` (horizontal), `zpos` (vertical), `xpos` (along the beam) | frame, sign and zero unknown (y = 18.1 mm taken literally puts the beam outside the 6 mm bore) | recorded (x = 0, y = 18.1, z = -0.26 on 9/29); the axis names are from the pulsed-wire alignment (inferred; see below). Fitted, in the twin's frame: `pmq_x_mm`, `pmq_y_mm`, `pmq_z_mm` |
| none (the twin has no triplet yaw or pitch) | deg | `U_Hexapod:wangle` (yaw), `vangle` (pitch), `uangle` (roll) | deg to mrad; the sign conventions unknown | recorded: yaw -0.1224 deg (-2.14 mrad), pitch +0.0138 deg (+0.24 mrad), roll 0 on 9/29. The axis names are from the pulsed-wire alignment, which also found an axis named "pitch" to be roll: to confirm. The fitted horizontal beam pointing (-2.0 to -2.6 mrad) matches the yaw in size; the twin should take these angles |
| `PMQ{1V,2H,3V}_Tilt_mrad` | mrad | none per quad (the hexapod tilts the whole triplet) | | no PV. Measured on the pulsed-wire bench (2026-10-08): rolls relative to PMQ1 of 0.38 +- 0.05 deg (PMQ2) and 1.86 +- 0.06 deg (PMQ3); fixed values for the twin, not knobs. Whether the bench state matches 9/29 is not known |
| none (the twin offsets the triplet as one) | mm | none | | no PV. Measured on the bench: PMQ2 0.273 mm off the PMQ1-PMQ3 axis horizontally and 0.074 mm vertically (an energy-dependent kick of about 4.9 and 1.3 mrad at 100 MeV with the twin's PMQ2 strength) |
| PMQ field values (lattice constants: -1.242, 1.242, -1.107 T at the 6 mm bore) | T | none | | no PV. Bench field maps give relative peak gradients 1 : 1.07 : 1.08 (the twin's 1 : 1.00 : 0.89) and the fringe profiles; their absolute T/m are a quarter of the twin's, probably uncalibrated |
| none (the twin fixes source to PMQ1 at 0.052 m "at Jetz = 6.8") | mm | `U_ESP_JetXYZ:Position.Axis 1`, `2`, `3` | which axis is z, and its zero, unknown | recorded (5.25, -7.75, 9.5 from Scan011 on; Scan006 stepped axis 3, Scans 007 and 008 axis 1). The twin has no jet input; only `pmq_z` changes the source-to-PMQ1 drift |
| `VisaBump_{X,Y,Xp,Yp}` | mm, mrad | none: a composite of the S3 and S4 currents | needs the S3/S4 kick geometry | derived in the twin only |
| `MagSpec_On`, `MagSpec_B_T` | bool, T | `U_BCaveMagSpec:DeltaAngle` is the only spectrometer variable logged (empty in every scan); `U_BCaveMagSpecPS` logs only a timestamp; `U_MagSpec` is not in the data | the field sets the energy axis | unknown. The Hall probes (`U_ACaveHallProbe`, `U_BCaveHallProbe`: `Field`, `RawField`) read 0.0 in every scan. **The field changed during the day** (see "Spectrometer energy axis") |

## Cameras, spectrometer and charge

| Twin PV | GEECS device | Status |
|---|---|---|
| `TCPhosphor_image` | `UC_TC_Phosphor` | confirmed in GEECS-Plugins; not in the sample data |
| `ChicaneSlit_image` | `UC_ChicaneSlit` | recorded (`exposure`, `triggerdelay` only; no images saved) |
| `DCPhosphor_image` | `UC_DiagnosticsPhosphor`? | the device is recorded (its centroid and moment columns are empty); the pairing is still a guess |
| `Phosphor1_image` | `UC_Phosphor1` | recorded |
| `UC_ALineEbeam1_image`, `UC_ALineEBeam2_image`, `UC_ALineEBeam3_image` | `UC_ALineEbeam1`, `UC_ALineEBeam2`, `UC_ALineEBeam3` | recorded. The real first name does have the lowercase `b`, so the twin's names match. `UC_ALineEBeam3`'s images saved in Scans 022 (background), 023 and 026 |
| none | `UC_HiResMagCam` | recorded (images in Scans 019, 020, 025, 028 to 030): a high-resolution spectrometer camera centred near 100 MeV, too narrow for these beams (README); no energy calibration in the data |
| none (the twin's source charge) | `U_BCaveICT:Python Results.ChA` (and `ChB`) | recorded every shot. Most likely already in pC: Scan016's median 36.7 matches the 26 to 37 pC quoted for HTU shots in the Genesis slides. To confirm |
| `Source_*` (energy, charge, Twiss, centroid, pointing) | none: the LPA has no PVs | no one-to-one PV; the fitted source is in the status document |

The twin's screen geometry is a placeholder for every camera except the slit camera
(`screens.DEFAULT_GEOMETRY`, 7 um per pixel, 1024 x 1024). For `UC_ALineEBeam3` the A-line fits
give: axes not swapped, both image axes reversed against the twin's x and y (column increases
toward -x, row toward -y), and a pixel size between 90 and 230 um (it trades off against the beam's
size; not determined). The image variable name was not found; in the sample data the images are
saved per device as HDF5 stacks (`<device>/<device>.h5`, dataset `entry/data/data`, per-frame
`frame_acq_timestamp`, matched to the table's LabVIEW-epoch `acq_timestamp` by an offset of
2,082,844,800 s), not as scan-table variables.

The magnetic spectrometer (`UC_BCaveMagSpecCam1`, `Cam2`; `Cam3` sees no beam) is saved as images
plus derived stacks: `-interpSpec` (spectrum: energy, value), `-interpDiv` (vertical profile:
AngleAxis, value) and `-ImageInterp` (the image on those axes: rows are `-interpDiv`'s AngleAxis in
reverse order, columns `-interpSpec`'s energies, every 0.25). The AngleAxis is the vertical screen
position over the trajectory's total path for each momentum (the `MagSpecCamera` driver, which
reads the same calibration files as the twin's `DutchMagSpec`); its driver has a `CameraFlipped`
setting, consistent with the fitted negative scales. The twin has no PV for any of these.

### Spectrometer energy axis

The `-interpSpec` energy axis is not the same in every scan:

| Scans | Cam1 [MeV] | Cam2 [MeV] | Scale against Scan020 |
|---|---|---|---|
| 014, 019, 020 | 54.45 to 129.45 | 129.24 to 244.49 | 1 |
| 025 | 45.38 to 107.88 | 107.72 to 203.72 | 0.833 |
| 028, 029, 030 | 44.87 to 106.62 | 106.49 to 201.49 | 0.824 |

Both ends of both cameras scale by the same factor, as the driver's axis does when its field
setting changes. **But the magnet did not change: the energies in Scans 025 to 030 are labelled
about 17% low.** With the chicane and slit as in Scan020, Scan025's slit-cut spectrum peaks at 80
MeV on its own axis against Scan020's 95 MeV, the ratio of the two axes (0.84); the beam's features
stay on the same pixels while the labels move. Rescaled by 1/0.833, Scan025's peak returns to 96
MeV and the twin's spectrum distance halves (0.35-0.43 to 0.17-0.20; checked 2026-11-02 against
the fitted twin). So the camera driver's field
setting was changed (lowered about 17%) between Scan020 and Scan025 without the magnet changing,
or the driver's setting was not the magnet's. The fitting code now rescales those axes to the
trusted calibration (`htu_twin_apps/lpa_source/scans.energy_axis`). The driver also uses its
setting for the AngleAxis (each momentum's total path), so those scans' AngleAxis values are
computed at the wrong momentum too, which may account for part of the vertical camera-scale
problem. To confirm with HTU: the spectrometer's current or field on 9/29 and the driver's B
setting in each scan.

## Chicane calibration

The twin's calibration (measured B-I table) and the GEECS R56 formula give different currents for
the same R56, assuming both use micrometres at 100 MeV. The machine runs on the formula: Scan019
steps `R56_at_100MeV`, and the logged currents follow it.

| R56 [um] | twin I [A] | GEECS formula I [A] | recorded `U_ChicaneInner:Current` [A] | twin / recorded |
|---|---|---|---|---|
| 50 | 1.094 | 0.944 | 0.944 | 1.16 |
| 97.4 | | 1.317 | 1.317 | |
| 203.9 | | 1.907 | 1.907 | |
| 275.0 | | 2.214 | 2.214 | |

(The 100, 200 and 300 um twin values were 1.540, 2.169 and 2.646 A, about 1.15 times the formula.)

So a twin driven from the real `U_ChicaneInner:Current` sees about 15% less current than its own
table expects for that R56. That the formula is the operators' convention does not make its R56
correct, and the recorded data cannot decide which calibration is right: both make the bend angle
proportional to current (0.01077 rad/A at 100 MeV for the formula, 0.00934 for the table), so
against a slit of unknown position they differ only in the jaw position they imply (15% further out
under the formula). The jaw positions are not logged and `UC_ChicaneSlit` saved no images. Until
it is decided, the twin's chicane knob should not be driven from the real current without stating
which calibration is meant.

Scan019's spectra (the per-step mean of the stitched `-interpSpec` spectra) show a sharp edge that
moves only from 94 to 101 MeV over the scan, where a fixed jaw on a straight beam would move it from
94 to 120 MeV. The fits reproduce it with one fixed jaw on a horizontally narrow beam whose
pointing depends on energy (possibly the triplet's yaw and PMQ2's offset; see the hexapod and PMQ
rows), under the twin's calibration. A notch at 95 to 99 MeV at low R56 and a low-energy hump at
1.79 to 1.91 A are not reproduced; a narrow blocker inside the jaw makes the notch roughly. To
decide the calibration and the slit's geometry, any one of these would do: the jaw positions
(motor readbacks or a drawing), `UC_ChicaneSlit` images during an R56 scan, or the provenance of the
formula's 560968.636 against the 2026-08-25 B-I measurement.

## Settled by the sample data

- **EMQ set versus measured.** `Current_Limit.ChN` is the knob (every EMQ scan steps it);
  `Current.ChN` the readback, which is the magnitude: in Scan022 `Current_Limit.Ch2` = -0.82 reads
  back as +0.82, so a mapping that reads `Current.ChN` loses the sign.
- **EMQ state.** Off before Scan022, then nominally 1.5 / -0.82 / 0 A (README); in Scans 23 to 31
  only the scanned channel is logged, the others assumed at nominal.
- **Scan descriptions.** Scans 29 to 31 are labelled "emq2" in `ScanStartInfo` but step
  `Current_Limit.Ch3`. Trust the `.ini` scan parameter, not the description.

- **EMQ polarity.** The twin's sign (`QUAD_POLARITY = -1`, which also sets the PMQ planes): the
  flipped sign fits far worse on the spectrometer EMQ scans (chi^2 about 1,050 against 3,500 or
  more) and on the A-line scans (6,584 against 3,365 at the same evaluations). The bench field
  maps' signs (PMQ1 negative, PMQ2 positive, PMQ3 negative) match the twin's PMQs.

## Open questions for HTU

The questions the recorded data could not settle are in
[`htu-twin-questions.md`](htu-twin-questions.md) (the ones we most need answered) and
[`htu-twin-other-questions.md`](htu-twin-other-questions.md) (the rest). The twin works around
each with a fitted or assumed value; an answer replaces it with a measured one.
