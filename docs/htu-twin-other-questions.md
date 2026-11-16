# HTU twin: other open questions

2026-11-16

Lower-priority questions for HTU, following [`htu-twin-questions.md`](htu-twin-questions.md). The
twin works around each one with a fitted or assumed value.

## Spectrometer

- 2026-10-01's energy labels: Cam1 starts at 51.6 MeV, 0.948 of 2026-09-29's early axis. Right?
- Cam2's AngleAxis zero sits about 4.5 rows above its `Y center pixel` (75.5). Should the twin use
  `230215Dutch1Cam.txt` or the later `241029` file?
- Where does the beam enter the magnet, relative to the pole centre the maps assume?
- The twin has 1600 map files but 1597 trajectory rows; it pairs `1001.txt` with the lowest
  momentum and drops the last three. Is that the right pairing?

## Chicane and slit

- The GEECS R56 formula and the twin's measured B-I table differ by about 15% in current. Which is
  right?
- The slit jaw positions aren't logged and `UC_ChicaneSlit` saved no images. Is there a readback or
  a drawing? The fit puts jaw 1 at 6.25 mm with a blade at 2.47 to 4.07 mm.

## Magnets

- An EMQ scan logs only its stepped channel; the twin takes the others at 1.5, -0.82 and 0 A.
  Correct for 2026-09-29?
- The fit puts the EMQs 0.87 to 1.43 mm off the beam horizontally and 0.41 to 0.60 mm vertically.
  Any survey or alignment data?
- S1V's and S3H's calibrations and signs. Do `VS6` to `VS8` exist?

## Geometry and cameras

- `UC_ALineEBeam3`: pixel size (fitted at 78 to 83 um), orientation, and distance from the
  spectrometer magnet (the twin uses 1.685 m). Were `UC_ALineEbeam1` and `Ebeam2` retracted in
  Scans 023, 026 and 031?
- Screen geometry of the other cameras (a placeholder in the twin), and the device behind
  `DCPhosphor_image`.
- `U_Hexapod` axis names, signs and zero: y = 18.1 mm taken literally puts the beam outside the
  6 mm PMQ bore.
- Which `U_ESP_JetXYZ` axis is along the beam, and its zero? The twin fixes the source 0.052 m
  before PMQ1.
- The spectrometer magnet's absolute position along the line, against the 354.6 mm and 170 mm
  chamber geometry.

## Controls

- Which IOCs serve the GEECS gateway's EPICS names, and does it serve PV Access as well as Channel
  Access?
- `U_BCaveICT` looks like pC already (Scan016's median 36.7 matches the Genesis slides' 26 to
  37 pC). Confirm.
