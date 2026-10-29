"use strict";

// The HTU beamline as a schematic, in beam order and not to scale, with each element marked by
// what the open scan did with it: scanned, changed, saved (images, spectra or traces), logged as
// scalars only, or absent.
//
// The electron line follows geecs-lume-twin's htu/lattice.py (the Cheetah model of the line). The
// laser chain's order, the target-chamber cameras and the ICT positions are inferred from the
// device names, and devices whose place is unknown go in the tray below the drawing.
//
// An element is the devices it is made of: `devices` names their column prefixes, or `cols`
// matches the columns directly when a device serves several elements (the EMQ supply's three
// channels, the plungers of the VISA screens). `knobs` narrows the columns whose change counts as a
// setting change; null for a pure readback.

const BEAMLINE_ROWS = [
  {
    title: "Laser: stretcher, amplifiers, compressor, focus (order approximate)",
    beam: "laser",
    items: [
      { label: "Stretcher", kind: "box", devices: ["UC_Stretcher", "UC_Stretcher_MI", "U_StretchterXMCC"] },
      { label: "Amp2", kind: "box", devices: ["UC_Amp2_IR_input", "UC_Amp2Depletion_South"] },
      { label: "Amp3", kind: "box", devices: ["UC_Amp3_IR_input", "UC_Amp3Depletion_South"] },
      {
        label: "Amp4", kind: "box", devices: ["UC_Amp4_IR_input", "UC_Amp4Depletion_South", "UC_Amp4_IR_output", "U_Amp4TelStage"],
        children: [{ label: "Pump mode", kind: "cam", devices: ["UC_GaiaMode"], note: "Gaia pump-laser mode camera" }],
      },
      { label: "Expander", kind: "box", devices: ["UC_ExpanderIn1", "UC_ExpanderIn1_Pulsed"] },
      { label: "Compressor", kind: "box", devices: ["U_CompAerotech", "UC_GratingMode"] },
      { label: "Pulse diag.", kind: "box", devices: ["U_FROG_Grenouille", "U_HamaSpectro", "UC_ModeImager", "U_ModeImagerESP"], note: "FROG, spectrometer and mode imager" },
      { label: "DM", kind: "box", devices: ["UC_DMSurface"], note: "Deformable mirror" },
      { label: "Steering", kind: "box", devices: ["UC_FinalSteeringLeak"], note: "Final steering (leak-through camera)" },
      { label: "OAP", kind: "box", devices: ["UC_OAPin1", "UC_OAPin2"], note: "Off-axis parabola, focusing onto the jet" },
      { label: "Focus", kind: "box", devices: ["UC_GhostFocus", "U_GhostWFS", "U_GhostLowPowerWFS", "U_HasoLift"], note: "Focal spot and wavefront, from a ghost reflection" },
    ],
  },
  {
    title: "Electron line: plasma target, PMQ triplet, chicane",
    beam: "e",
    bands: [["B1", "B4", "Chicane"]],
    items: [
      {
        label: "Gas jet", kind: "jet", devices: ["U_ESP_JetXYZ", "U_HP_Daq"], note: "Jet XYZ stage; U_HP_Daq is probably the backing pressure",
        children: [
          { label: "TopView", kind: "cam", devices: ["UC_TopView"] },
          { label: "TargetIn", kind: "cam", devices: ["UC_TargetIn"] },
          { label: "TubeIn", kind: "cam", devices: ["UC_TubeIn"] },
          { label: "TC output", kind: "cam", devices: ["UC_TC_Output"], note: "Target-chamber output; place inferred from the name" },
        ],
      },
      { label: "PMQ1–3", kind: "triplet", devices: ["U_Hexapod"], note: "Permanent-magnet triplet on the hexapod" },
      { label: "TCPhos", kind: "screen", devices: [], note: "TC phosphor: in the lattice, no device in these scans" },
      { label: "S1", kind: "steerer", devices: ["U_S1H", "U_S1V"] },
      { label: "B1", kind: "dipole", cols: /^(U_ChicaneOuter |R56)/, knobs: /^U_ChicaneOuter /, note: "Chicane outer dipoles (B1, B4) share a supply" },
      { label: "B2", kind: "dipole", cols: /^(U_ChicaneInner |R56)/, knobs: /^U_ChicaneInner /, note: "Chicane inner dipoles (B2, B3) share a supply" },
      { label: "Slit", kind: "slit", devices: ["UC_ChicaneSlit", "U_ChicaneMotors"], note: "Energy slit jaws and the slit camera, mid-chicane" },
      { label: "B3", kind: "dipole", cols: /^(U_ChicaneInner |R56)/, knobs: /^U_ChicaneInner /, note: "Chicane inner dipoles (B2, B3) share a supply" },
      { label: "B4", kind: "dipole", cols: /^(U_ChicaneOuter |R56)/, knobs: /^U_ChicaneOuter /, note: "Chicane outer dipoles (B1, B4) share a supply" },
      { label: "S2", kind: "steerer", devices: ["U_S2H", "U_S2V"] },
      { label: "DCPhos", kind: "screen", devices: ["UC_DiagnosticsPhosphor"], note: "Diagnostic-chamber phosphor" },
    ],
  },
  {
    title: "Electron line: EMQ triplet, magnetic spectrometer, A-line, VISA undulator",
    beam: "e",
    bands: [["EMQ1", "EMQ3", "EMQ triplet"], ["VS1", "VISA8", "VISA undulator"]],
    items: [
      ...[1, 2, 3].map((i) => ({
        label: `EMQ${i}`, kind: "quad", cols: new RegExp(`^U_EMQTripletBipolar \\S+\\.Ch${i}$`), filter: `u_emqtripletbipolar .ch${i}`,
      })),
      { label: "S3", kind: "steerer", devices: ["U_S3H", "U_S3V"] },
      { label: "Phosphor1", kind: "screen", devices: ["UC_Phosphor1"] },
      { label: "ICT", kind: "ict", devices: ["U_BCaveICT"], knobs: null, note: "B-cave charge monitor; place approximate" },
      {
        label: "MagSpec", kind: "dipole", devices: ["U_BCaveMagSpec", "U_BCaveMagSpecPS", "U_BCaveHallProbe"], knobs: /^U_BCaveMagSpec(PS)? /,
        note: "Dipole spectrometer; off, the beam goes straight on to the A-line",
        children: [
          { label: "Cam1", kind: "cam", devices: ["UC_BCaveMagSpecCam1"] },
          { label: "Cam2", kind: "cam", devices: ["UC_BCaveMagSpecCam2"] },
          { label: "Cam3", kind: "cam", devices: ["UC_BCaveMagSpecCam3"] },
          { label: "HiResMag", kind: "cam", devices: ["UC_HiResMagCam"] },
        ],
      },
      { label: "S4", kind: "steerer", devices: ["U_S4H", "U_S4V"] },
      { label: "ALine1", kind: "screen", devices: ["UC_ALineEbeam1"] },
      { label: "ALine2", kind: "screen", devices: ["UC_ALineEBeam2"] },
      { label: "ALine3", kind: "screen", devices: ["UC_ALineEBeam3", "U_Aline3Filter"] },
      // VISA: steerer, screen, steerer, screen per FODO segment (lattice.py); VS6-8 are not logged
      ...[1, 2, 3, 4, 5, 6, 7, 8].flatMap((i) => [
        ...(i <= 5 ? [{ label: `VS${i}`, kind: "steerer", devices: [`U_VS${i}H`, `U_VS${i}V`] }] : []),
        {
          label: `VISA${i}`, kind: "screen", cols: new RegExp(`^(UC_VisaEBeam${i} |U_VisaPlungers DigitalOutput\\.Channel ${i - 1}$)`),
          filter: `uc_visaebeam${i}`, note: `Screen and its plunger (U_VisaPlungers channel ${i - 1})`,
        },
      ]),
      { label: "Und. light", kind: "cam", devices: ["UC_UndulatorRad2"], note: "Undulator radiation camera" },
      { label: "Exit ICT", kind: "ict", devices: ["U_UndulatorExitICT"], knobs: null },
    ],
  },
];

// Devices whose place on the line is not known, or that serve the whole machine.
const BEAMLINE_TRAY = [
  { label: "A-cave Hall probe", devices: ["U_ACaveHallProbe"], knobs: null },
  { label: "BCaveIn camera", devices: ["UC_BCaveIn"] },
  { label: "ESP302 #1", devices: ["U_ESP302_01"] },
  { label: "ESP302 #2", devices: ["U_ESP302_02"] },
  { label: "TRA server 1", devices: ["U_TRAServer01"] },
  { label: "TRA server 3", devices: ["U_TRAServer03"] },
  { label: "Zaber", devices: ["U_Zaber"] },
  { label: "Velmex", devices: ["U_Velmex"] },
  { label: "PLCs", devices: ["U_PLC", "U_148_PLC"], knobs: null },
  { label: "Shot timing (DG645)", devices: ["U_DG645_ShotControl", "U_1HzShiftedBox"] },
  { label: "Vacuum gauge", devices: ["U_VacuumGauge"], knobs: null },
];

// A supply's voltage and power follow its current (and drift as the coil warms), so they are
// readbacks: only set points and currents count as a changed setting.
const READBACK = / (Voltage|Power)(\.Ch\d)?$/;

const BL = {
  axis: 60,      // the beam axis, below a row's top
  child: 62,     // child glyphs (cameras off the axis), below the axis
  childWidth: 64,
  fitScale: 0.9,  // the drawing may shrink to this to fit on fewer lines
  margin: 18,
  minWidth: 46,
  rowGap: 16,
  segmentGap: 40, // between two segments that share a line
};

function beamlineGlyph(item, cx, cy) {
  switch (item.kind) {
    case "box": {
      const w = Math.max(44, labelWidth(item.label) + 8);
      return `<rect class="glyph" x="${cx - w / 2}" y="${cy - 11}" width="${w}" height="22" rx="5"/>`;
    }
    case "cam":
      return `<rect class="glyph" x="${cx - 12}" y="${cy - 8}" width="24" height="16" rx="3"/>` +
        `<circle class="lens" cx="${cx}" cy="${cy}" r="3.5"/>`;
    case "dipole":
      return `<rect class="glyph" x="${cx - 13}" y="${cy - 11}" width="26" height="22" rx="2"/>`;
    case "ict":
      return `<circle class="glyph ring" cx="${cx}" cy="${cy}" r="10"/>`;
    case "jet":
      return `<path class="glyph" d="M${cx - 9} ${cy - 26} h18 l-6 16 h-6 z"/>` +
        `<circle class="glyph" cx="${cx}" cy="${cy}" r="4"/>`;
    case "quad":
      return `<rect class="glyph" x="${cx - 7}" y="${cy - 16}" width="14" height="32" rx="2"/>`;
    case "screen":
      return `<rect class="glyph" x="${cx - 3}" y="${cy - 16}" width="6" height="32" rx="1.5" transform="rotate(-20 ${cx} ${cy})"/>`;
    case "slit":
      return `<rect class="glyph" x="${cx - 5}" y="${cy - 17}" width="10" height="13" rx="1"/>` +
        `<rect class="glyph" x="${cx - 5}" y="${cy + 4}" width="10" height="13" rx="1"/>`;
    case "steerer":
      return `<rect class="glyph" x="${cx - 7}" y="${cy - 7}" width="14" height="14" rx="2"/>`;
    case "triplet":
      return [-15, 0, 15].map((dx) => `<rect class="glyph" x="${cx + dx - 5}" y="${cy - 15}" width="10" height="30" rx="2"/>`).join("");
    default:
      return "";
  }
}

// What the open scan did with an element: its columns and stacks, and whether it was scanned,
// changed, saved, collected or absent.
function beamlineStatus(item) {
  const s = state.scan;
  const match = item.cols || new RegExp(`^(${item.devices.join("|") || "(?!)"})( |$)`);
  const columns = s.columns.filter((c) => match.test(c));
  const stacks = s.device_list.filter((d) => match.test(`${d.name.split("-")[0]} `));
  const knobs = item.knobs === undefined ? match : item.knobs;
  const varied = new Set(s.settings.filter((x) => settingRange(x.values).varies).map((x) => x.name));
  const scanned = Boolean(s.parameter && match.test(s.parameter));
  const changed = knobs
    ? columns.filter((c) => c !== s.parameter && varied.has(c) && knobs.test(c) && !READBACK.test(c))
    : [];
  const status = scanned ? "scanned" : stacks.length ? "saved" : columns.length ? "logged" : "absent";
  return {
    columns,
    stacks,
    scanned,
    changed,
    collected: state.collected.some((c) => match.test(c)),
    status,
    classes: `bl-${status}${changed.length ? " bl-changed" : ""}${state.collected.some((c) => match.test(c)) ? " bl-collected" : ""}`,
  };
}

function beamlineTip(item, st) {
  const lines = [`<strong>${escapeHtml(item.label)}</strong>`];
  if (item.note) lines.push(`<span class="muted">${escapeHtml(item.note)}</span>`);
  if (st.status === "absent") {
    const names = item.devices && item.devices.length ? item.devices.join(", ") : "no logged device";
    lines.push(`Not in this scan (${escapeHtml(names)})`);
  } else {
    if (st.scanned) lines.push(`<b>Scanned:</b> ${escapeHtml(state.scan.parameter)}`);
    for (const c of st.changed) lines.push(`<b>Changed:</b> ${escapeHtml(c)}`);
    for (const d of st.stacks) lines.push(`Saved ${escapeHtml(d.kind)}: ${escapeHtml(d.name)}`);
    const devices = [...new Set(st.columns.map((c) => c.split(" ")[0]))];
    lines.push(`${st.columns.length} scalar column(s)${devices.length ? ` from ${escapeHtml(devices.join(", "))}` : ""}`);
    if (st.collected) lines.push("Collected in the charts");
    lines.push('<span class="muted">Click to list its columns</span>');
  }
  return lines.join("<br>");
}

function labelWidth(text) {
  return text.length * 6.4;
}

// Pack the segments (BEAMLINE_ROWS) into lines no wider than `available` pixels, in beam order: a
// wide view puts several segments on one line rather than scaling the drawing up. Sets each item's
// x and each segment's line, offset and top; returns the lines and the drawing's size.
function layoutBeamline(available) {
  for (const row of BEAMLINE_ROWS) {
    let x = 0;
    for (const item of row.items) {
      const own = Math.max(BL.minWidth, labelWidth(item.label) + 14, item.kind === "box" ? labelWidth(item.label) + 22 : 0);
      item.width = Math.max(own, (item.children || []).length * BL.childWidth);
      item.dx = x + item.width / 2;
      x += item.width;
    }
    row.width = x;
    row.height = row.items.some((i) => i.children) ? BL.axis + BL.child + 36 : BL.axis + 40;
  }
  const lines = [];
  for (const row of BEAMLINE_ROWS) {
    const line = lines[lines.length - 1];
    const end = line ? line.width + BL.segmentGap + row.width + BL.margin : Infinity;
    if (end > available) lines.push({ rows: [row], width: BL.margin + row.width });
    else { line.rows.push(row); line.width += BL.segmentGap + row.width; }
  }
  let top = 0;
  for (const line of lines) {
    line.top = top;
    line.height = Math.max(...line.rows.map((r) => r.height));
    let x = BL.margin;
    for (const row of line.rows) {
      row.line = line;
      row.left = x;
      for (const item of row.items) item.x = x + item.dx;
      x += row.width + BL.segmentGap;
    }
    top += line.height + BL.rowGap;
  }
  const width = Math.max(...lines.map((l) => l.width)) + BL.margin;
  return { lines, width, height: top - BL.rowGap };
}

function openBeamlineItem(item, st) {
  if (st.status === "absent") return;
  $("column-filter").value = item.filter || st.columns[0].split(" ")[0].toLowerCase();
  filterColumns();
  $("column-filter").scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function renderBeamline() {
  if (!state.scan) return;
  const handlers = [];
  const out = [];
  const add = (item, markup) => {
    handlers.push(item);
    return `<g class="bl-item ${item.st.classes}" data-i="${handlers.length - 1}" tabindex="0" role="button" aria-label="${escapeHtml(item.label)}: ${item.st.status}">${markup}</g>`;
  };
  const scroll = $("beamline").querySelector(".beamline-scroll");
  const available = scroll.clientWidth || 1400;
  const fewer = layoutBeamline(available / BL.fitScale).lines.length < layoutBeamline(available).lines.length;
  const { width, height } = layoutBeamline(fewer ? available / BL.fitScale : available);
  BEAMLINE_ROWS.forEach((row, r) => {
    const top = row.line.top, ay = top + BL.axis;
    const first = row.items[0], last = row.items[row.items.length - 1];
    out.push(`<text class="bl-title" x="${row.left}" y="${top + 13}">${escapeHtml(row.title)}</text>`);
    for (const [from, to, label] of row.bands || []) {
      const a = row.items.find((i) => i.label === from), b = row.items.find((i) => i.label === to);
      const x0 = a.x - a.width / 2 + 3, x1 = b.x + b.width / 2 - 3;
      out.push(`<rect class="bl-band" x="${x0}" y="${ay - 24}" width="${x1 - x0}" height="48" rx="6"/>` +
        `<text class="bl-band-label" x="${(x0 + x1) / 2}" y="${ay - 28}">${escapeHtml(label)}</text>`);
    }
    out.push(`<line class="bl-beam bl-beam-${row.beam}" x1="${first.x}" y1="${ay}" x2="${last.x + 14}" y2="${ay}"/>`);
    // the beam continues into the next segment: straight on when it shares this line; otherwise
    // down from this line's end, back left along the gap between the lines, down the left margin
    // and into the next line's first element
    const next = BEAMLINE_ROWS[r + 1];
    if (next) {
      const start = next.items[0];
      const kind = row.beam === next.beam ? row.beam : "laser";
      if (next.line === row.line) {
        out.push(`<line class="bl-beam bl-beam-${kind}" x1="${last.x + 14}" y1="${ay}" x2="${start.x - 6}" y2="${ay}"/>`);
      } else {
        const gapY = top + row.line.height + BL.rowGap / 2, entryY = next.line.top + BL.axis;
        const right = row.line.width + BL.margin / 2;
        out.push(`<path class="bl-beam bl-beam-${kind}" d="M${last.x + 14} ${ay} H${right} V${gapY} H6 V${entryY} H${start.x - 8}"/>`);
      }
    }
    for (const item of row.items) {
      item.st = beamlineStatus(item);
      const children = item.children || [];
      let markup = `<rect class="hit" x="${item.x - item.width / 2}" y="${ay - 26}" width="${item.width}" height="58"/>` +
        beamlineGlyph(item, item.x, ay) +
        `<text class="bl-label" x="${item.x}" y="${ay + 30}">${escapeHtml(item.label)}</text>` +
        `<circle class="bl-dot" cx="${item.x}" cy="${ay + 37}" r="2.5"/>`;
      out.push(add(item, markup));
      children.forEach((child, c) => {
        child.st = beamlineStatus(child);
        const cx = item.x + (c - (children.length - 1) / 2) * BL.childWidth, cy = ay + BL.child;
        out.push(`<path class="bl-stalk" d="M${item.x} ${ay + 40} V${cy - 18} H${cx} V${cy - 8}"/>`);
        out.push(add(child,
          `<rect class="hit" x="${cx - BL.childWidth / 2}" y="${cy - 12}" width="${BL.childWidth}" height="42"/>` +
          beamlineGlyph(child, cx, cy) +
          `<text class="bl-label" x="${cx}" y="${cy + 22}">${escapeHtml(child.label)}</text>` +
          `<circle class="bl-dot" cx="${cx}" cy="${cy + 29}" r="2.5"/>`));
      });
    }
  });
  // drawn at one unit per pixel, or a little smaller when that saves a line; shrinks to fit a
  // narrow view, down to a floor, then scrolls
  const svg = $("beamline-svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.style.width = `${width}px`;
  svg.style.minWidth = `${Math.round(width * 0.68)}px`;
  svg.innerHTML = out.join("");

  const tray = $("beamline-tray");
  tray.innerHTML = '<span class="muted small">Place on the line not known, or machine-wide:</span>';
  for (const item of BEAMLINE_TRAY) {
    item.st = beamlineStatus(item);
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = `chip bl-chip ${item.st.classes}`;
    chip.textContent = item.label;
    chip.dataset.i = String(handlers.length);
    handlers.push(item);
    tray.appendChild(chip);
  }

  const tip = $("beamline-tip");
  const box = $("beamline");
  const show = (el, event) => {
    const item = handlers[Number(el.dataset.i)];
    tip.innerHTML = beamlineTip(item, item.st);
    tip.hidden = false;
    const area = box.getBoundingClientRect();
    const anchor = event && event.clientX !== undefined ? { x: event.clientX, y: event.clientY } : (() => {
      const r = el.getBoundingClientRect();
      return { x: r.left + r.width / 2, y: r.bottom };
    })();
    const left = Math.min(anchor.x - area.left + 14, area.width - tip.offsetWidth - 8);
    tip.style.left = `${Math.max(8, left)}px`;
    tip.style.top = `${anchor.y - area.top + 16}px`;
  };
  for (const el of box.querySelectorAll("[data-i]")) {
    const item = handlers[Number(el.dataset.i)];
    el.addEventListener("mousemove", (event) => show(el, event));
    el.addEventListener("focus", () => show(el));
    el.addEventListener("mouseleave", () => { tip.hidden = true; });
    el.addEventListener("blur", () => { tip.hidden = true; });
    el.addEventListener("click", () => openBeamlineItem(item, item.st));
    el.addEventListener("keydown", (event) => {
      if (event.key === "Enter") openBeamlineItem(item, item.st);
    });
  }
}

// Repack the lines when the view's width changes.
{
  let width = 0, timer = null;
  new ResizeObserver(([entry]) => {
    const next = Math.round(entry.contentRect.width);
    if (next === width) return;
    width = next;
    clearTimeout(timer);
    timer = setTimeout(renderBeamline, 120);
  }).observe(document.querySelector("#beamline .beamline-scroll"));
}
