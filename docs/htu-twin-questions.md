# HTU twin: spectrometer drift bug and open questions

2026-11-16

Two things for the GEECS team: a bug in the twin's spectrometer model, and six questions we most
need answered. The rest are in [`htu-twin-other-questions.md`](htu-twin-other-questions.md).

## Bug: the spectrometer maps count a 1.97 m drift twice

The Dutch magnet's COSY maps start at the e-beam source. At the highest momentum each map is a
2.684 m drift, while the trajectory table's total path is 0.715 m. `DutchCalibration.map_to_screens`
applies the maps at the twin's MagSpec entrance, so the source-to-magnet drift is counted twice.

On the side screen this magnifies vertical angles 6 to 10 times, against 1.5 times with the drift
removed. The fix is small: drift the particles back 1.970 m before applying the maps. We have it
locally and can send it; htu-twin-apps works around it meanwhile (`pointing.upstream_drift_m`).

## Questions

Our main open problem: fitting the A-line camera and the spectrometer together needs each
spectrometer camera's AngleAxis at about -0.31 times the twin's, inverted and a third the size.
We've checked the camera driver (its AngleAxis is screen height over total path, as the twin
assumes) and the map's vertical optics, and neither explains it (see
[`twin_viewer/fits/README.md`](../htu_twin_apps/twin_viewer/fits/README.md)).

1. **Camera orientation.** Is the top of each spectrometer camera's frame up in the lab, or is
   there a mirror between screen and camera? That would explain the sign.
2. **A vertical calibration scan.** Is there a scan, or could one be taken, that steers the beam
   vertically by a known angle with the spectrometer on? It would measure the scale directly.
3. **The spectrometer field.** What are the units of `U_BCaveHallProbe RawField` (about 747 in the
   2026-09-29 spectrometer scans)? The twin assumes 0.825 T. Between Scans 020 and 025 the energy
   labels dropped about 17% with the beam on the same pixels: was the field changed, or only the
   driver's setting?
4. **The magnet documents.** Can we get `DutchMagnetV0b-2.pdf` (2013) and the 2018 reinstall
   slides? Can someone confirm the maps start at the source?
5. **EMQ strengths.** The fits want EMQ1 at 1.08 and EMQ2 at 1.27 times the twin's gradients. How
   do the test reports' current-to-gradient curves compare?
6. **S1H steerer.** It fits at 0.076 of the twin's calibration. What is its real calibration and
   sign?
