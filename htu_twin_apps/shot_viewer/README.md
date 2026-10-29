# HTU shot viewer

A small local web app for HTU scan folders: pick a scan, collect the scalars you want, and look at
them shot by shot, with each device's image or spectrum for that shot, and a schematic of the
beamline that marks what the scan changed and saved.

## Run

Install the repository (see the [top-level README](../../README.md)), then:

```bash
htu-shot-viewer <data directory>        # or set $HTU_DATA; --port N to change the port
```

Open <http://127.0.0.1:8050>. The server only listens on this machine. The page loads Plotly from
cdn.jsdelivr.net, so the browser needs internet access.

## What it does

- **Scans:** every `scans/Scan*` folder with a `ScanDataScan*.txt`, found anywhere under the data
  directory. The menu shows each scan's description from its
  `ScanInfoScan*.ini`.
- **Collect:** tick scalar columns of the scan table, grouped by device (filter to find them). Each
  collected column gets a chart against the x axis you choose: shot number, the scan parameter, the
  scan step or another collected column. The step mean ± standard deviation is drawn on top. A table
  view lists the collected values per shot, and "Download CSV" saves them, one row per shot.
- **A shot:** opening a scan opens its first shot; click a point (or a table row) to open another.
  The shot panel shows the collected values, the frame of every device stack for that shot
  (images as heatmaps, spectra as lines; toggle devices on and off), the machine settings, and all
  the shot's scalars. The charts mark the shot with a ring.
- **Moving through time:** the timeline bar stays at the top of the page. It shows the shot, its
  scan step, the scan parameter's value and the shot's time (and the seconds since the scan
  started). Drag the slider, use the first/previous/next/last buttons or the arrow keys, or press
  Play (or the space bar) to step through the shots at 0.5 to 4 shots per second. Playback waits
  for each shot's images before moving on. Zooming into an image keeps the zoom while stepping.
- **Machine settings:** the shot's magnet currents and voltages (EMQ triplet, chicane, steerers),
  Hall probes, ICT charge monitors, VISA screen plungers, gas jet, PMQ hexapod, laser and other
  motion stages, timing and vacuum, grouped by system. By
  default only those that change during the scan are listed, with their range over the scan; a
  value that changed since the previous shot is highlighted with its previous value. A change
  counts only above 0.5 % of the setting's typical size, and at least 0.005 in its units, so the
  readback jitter of the power supplies is ignored.
- **Beamline:** a schematic of the line in beam order (not to scale): the laser chain, the
  plasma target, PMQ triplet and chicane, then the EMQ triplet, magnetic spectrometer, A-line and
  VISA undulator. Each element is marked by what the scan did with it: scanned, a setting changed,
  images, spectra or traces saved, scalars logged only, or absent; a dot marks the elements whose
  columns are collected. Hover for its devices and changes, click to list its columns. The
  electron line follows geecs-lume-twin's `htu/lattice.py`; the laser chain's order, the
  target-chamber cameras and the ICT positions are inferred from the device names, and devices
  whose place is unknown sit in a tray below. A wide window puts more of the line on each row.
- **Links:** the address bar holds the view (scan, collected columns, x axis and shot), so a view
  can be bookmarked or shared.

## How shots are matched

The scalar table has one row per shot. A device stack (`<device>/<device>.h5`, dataset
`entry/data/data`) holds one frame per saved shot, with its acquisition time in
`entry/instrument/NDAttributes/*frame_acq_timestamp`. A frame belongs to the shot whose
`<device> acq_timestamp` column is within 50 ms of it. The table's times are LabVIEW times (seconds
since 1904), 2 082 844 800 s ahead of the stack's Unix times. Shot and frame counts can differ
(Scan029 has 301 rows and 300 frames), so frames are not matched by position.

Images wider or taller than 400 pixels are block-averaged before they are sent to the browser; the
axes stay in camera pixels.
