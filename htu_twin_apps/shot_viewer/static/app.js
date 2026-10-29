"use strict";

// State of the page: the open scan, the collected columns and their per-shot values, and the
// shot on view.
const state = {
  scan: null,      // /api/scan response
  collected: [],   // column names
  series: {},      // column name -> per-shot values
  shotRow: null,   // row index of the shot on view
  hiddenDevices: new Set(),
  playing: false,
  frameRequests: {}, // device name -> number of the latest frame request, to drop stale replies
};

// A setting counts as changed when it moves by more than this fraction of its typical size, and
// that size is taken as at least SCALE_FLOOR: the power supplies' readbacks jitter in the last
// digits, and a supply that is off reads a few 1e-4 of noise.
const CHANGE_FRACTION = 0.005;
const SCALE_FLOOR = 1;

// The machine settings, grouped for display: [group title, column-name pattern].
const SETTING_GROUPS = [
  ["Quadrupoles (EMQ triplet)", /^U_EMQ/],
  ["Chicane", /^U_Chicane/],
  ["Steering, transport line", /^U_S\d[HV] /],
  ["Steering, VISA undulator", /^U_VS\d[HV] /],
  ["Field probes", /HallProbe|^U_BCaveMagSpec /],
  ["Charge monitors (ICT)", /ICT/],
  ["Screens in/out (VISA plungers)", /^U_VisaPlungers/],
  ["Gas jet and PMQ hexapod", /^U_ESP_JetXYZ|^U_Hexapod|^U_HP_Daq/],
  ["Laser stages", /^U_(CompAerotech|Amp4TelStage|StretchterXMCC|ModeImagerESP) /],
  ["Other stages", /^U_(ESP302_\d+|TRAServer\d+|Zaber|Velmex) /],
  ["Timing", /^U_DG645|^U_1HzShiftedBox/],
  ["Vacuum", /^U_VacuumGauge/],
];

const $ = (id) => document.getElementById(id);

function css(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

async function api(path, params = {}) {
  const query = new URLSearchParams(params).toString();
  const response = await fetch(`/api/${path}${query ? "?" + query : ""}`);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || response.statusText);
  return body;
}

function remember(key, value) {
  try { localStorage.setItem(`htu-shot-viewer:${key}`, JSON.stringify(value)); } catch (e) { /* no storage */ }
}

function recall(key, fallback) {
  try {
    const v = localStorage.getItem(`htu-shot-viewer:${key}`);
    return v === null ? fallback : JSON.parse(v);
  } catch (e) {
    return fallback;
  }
}

function format(v) {
  if (v === null || v === undefined) return "—";
  if (Math.abs(v) >= 1e5 || (Math.abs(v) < 1e-3 && v !== 0)) return v.toExponential(3);
  return Number(v.toPrecision(5)).toString();
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
}

function baseLayout(title, xTitle, yTitle) {
  const text = css("--text-primary"), muted = css("--text-secondary"), grid = css("--grid");
  return {
    title: { text: title, font: { size: 13, color: text }, x: 0.01, xanchor: "left", y: 0.97, yanchor: "top", yref: "container" },
    paper_bgcolor: css("--surface-1"),
    plot_bgcolor: css("--surface-1"),
    font: { color: muted, size: 12 },
    margin: { l: 56, r: 12, t: 58, b: 44 },
    xaxis: { title: { text: xTitle }, gridcolor: grid, zerolinecolor: grid, linecolor: grid },
    yaxis: { title: { text: yTitle }, gridcolor: grid, zerolinecolor: grid, linecolor: grid },
    hoverlabel: { bgcolor: css("--surface-1"), bordercolor: grid, font: { color: text } },
    legend: { orientation: "h", y: 1.02, yanchor: "bottom", x: 1, xanchor: "right", font: { size: 11 } },
    showlegend: false,
  };
}

const plotConfig = { responsive: true, displaylogo: false, modeBarButtonsToRemove: ["select2d", "lasso2d"] };

// --- scans

async function loadScans() {
  const scans = await api("scans");
  const select = $("scan-select");
  select.innerHTML = "";
  for (const s of scans) {
    const option = document.createElement("option");
    option.value = s.id;
    option.textContent = `${s.id} — ${s.description || "no description"} (${s.shots} shots)`;
    select.appendChild(option);
  }
  const link = new URLSearchParams(location.hash.slice(1));
  const wanted = link.get("scan") || recall("scan", null);
  if (wanted && scans.some((s) => s.id === wanted)) select.value = wanted;
  select.addEventListener("change", () => openScan(select.value));
  if (!scans.length) return;
  await openScan(select.value);
  if (link.get("scan") === select.value) {
    if (link.has("collect")) await setCollected(link.get("collect").split("\t").filter((c) => state.scan.columns.includes(c)));
    if (link.has("x") && [...$("x-select").options].some((o) => o.value === link.get("x"))) {
      $("x-select").value = link.get("x");
      renderCharts();
    }
    if (link.has("shot")) await openShot(Math.max(0, state.scan.shot.indexOf(Number(link.get("shot")))));
  }
}

// The view as a link: scan, collected columns, x axis and shot, in the URL's hash.
function writeLink() {
  if (!state.scan) return;
  const link = new URLSearchParams({ scan: state.scan.id, collect: state.collected.join("\t"), x: $("x-select").value });
  if (state.shotRow !== null) link.set("shot", state.scan.shot[state.shotRow]);
  history.replaceState(null, "", `#${link}`);
}

async function openScan(id) {
  stop();
  state.scan = await api("scan", { scan: id });
  state.shotRow = null;
  state.hiddenDevices.clear();
  remember("scan", id);
  const s = state.scan;
  const parameter = s.parameter ? `scanning ${s.parameter}` : "no scan parameter (a noscan)";
  $("scan-info").textContent =
    `${s.shots} shots · ${parameter} · ${s.device_list.length} device stack(s) · ${s.columns.length} scalars`;
  $("device-frames").innerHTML = "";
  $("shot-slider").max = String(s.shot.length - 1);
  $("timeline").hidden = s.shot.length === 0;
  buildColumnList();
  const wanted = recall("collected", []);
  const defaults = s.parameter ? [s.parameter] : [];
  await setCollected((wanted.length ? wanted : defaults).filter((c) => s.columns.includes(c)));
  renderDeviceToggles();
  renderBeamline();
  if (s.shot.length) await openShot(0);
}

// --- collecting columns

function buildColumnList() {
  const groups = new Map();
  for (const column of state.scan.columns) {
    if (["Bin #", "scan", "Shotnumber", ""].includes(column)) continue;
    const device = column.includes(" ") ? column.slice(0, column.indexOf(" ")) : column;
    if (!groups.has(device)) groups.set(device, []);
    groups.get(device).push(column);
  }
  const list = $("column-list");
  list.innerHTML = "";
  for (const [device, columns] of groups) {
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = `${device} (${columns.length})`;
    details.appendChild(summary);
    for (const column of columns) {
      const label = document.createElement("label");
      label.dataset.column = column.toLowerCase();
      const box = document.createElement("input");
      box.type = "checkbox";
      box.value = column;
      box.addEventListener("change", () => {
        const next = box.checked
          ? [...state.collected, column]
          : state.collected.filter((c) => c !== column);
        setCollected(next);
      });
      label.append(box, document.createTextNode(column.slice(device.length).trim() || column));
      details.appendChild(label);
    }
    list.appendChild(details);
  }
  filterColumns();
}

function filterColumns() {
  const words = $("column-filter").value.toLowerCase().split(/\s+/).filter(Boolean);
  for (const details of $("column-list").children) {
    let any = false;
    for (const label of details.querySelectorAll("label")) {
      const show = words.every((w) => label.dataset.column.includes(w));
      label.hidden = !show;
      any = any || show;
    }
    details.hidden = !any;
    details.open = words.length > 0 && any;
  }
}

async function setCollected(columns) {
  state.collected = columns;
  remember("collected", columns);
  if (state.series._scan !== state.scan.id) state.series = { _scan: state.scan.id };
  // the scan parameter is fetched too: it can be the x axis without being collected
  const wanted = state.scan.parameter ? [...columns, state.scan.parameter] : columns;
  const missing = [...new Set(wanted)].filter((c) => !(c in state.series));
  if (missing.length) Object.assign(state.series, await api("series", { scan: state.scan.id, columns: missing.join("\t") }));
  for (const box of $("column-list").querySelectorAll("input")) box.checked = columns.includes(box.value);
  renderCollected();
  renderXOptions();
  renderCharts();
  renderTable();
  if (state.shotRow !== null) renderShotCollected();
  renderBeamline();
  $("empty-hint").hidden = columns.length > 0;
  writeLink();
}

function renderCollected() {
  const chips = $("collected");
  chips.innerHTML = "";
  $("collected-count").textContent = state.collected.length ? `(${state.collected.length})` : "";
  for (const column of state.collected) {
    const chip = document.createElement("button");
    chip.className = "chip";
    chip.type = "button";
    chip.title = "Remove";
    chip.textContent = `${column} ×`;
    chip.addEventListener("click", () => setCollected(state.collected.filter((c) => c !== column)));
    chips.appendChild(chip);
  }
  const download = $("download");
  download.href = `/api/export.csv?${new URLSearchParams({ scan: state.scan.id, columns: state.collected.join("\t") })}`;
  download.toggleAttribute("aria-disabled", state.collected.length === 0);
}

function renderXOptions() {
  const select = $("x-select");
  const previous = select.value;
  const options = [["shot", "Shot number"]];
  if (state.scan.parameter) options.push(["parameter", `Scan parameter: ${state.scan.parameter}`]);
  options.push(["bin", "Scan step (Bin #)"]);
  options.push(["time", "Time"]);
  for (const c of state.collected) if (c !== state.scan.parameter) options.push([`col:${c}`, c]);
  select.innerHTML = "";
  for (const [value, label] of options) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    select.appendChild(option);
  }
  select.value = options.some(([v]) => v === previous) ? previous : (state.scan.parameter ? "parameter" : "shot");
}

function xValues() {
  const choice = $("x-select").value;
  if (choice === "parameter") return { title: state.scan.parameter, values: state.series[state.scan.parameter] };
  if (choice === "bin") return { title: "Scan step", values: state.scan.bin };
  if (choice === "time") return { title: "Time", values: state.scan.time.map((t) => (t === null ? null : new Date(t * 1000))) };
  if (choice.startsWith("col:")) return { title: choice.slice(4), values: state.series[choice.slice(4)] };
  return { title: "Shot number", values: state.scan.shot };
}

// --- charts: one per collected column (one measure per chart, so no second y-axis)

function stepStats(x, y) {
  const bins = state.scan.bin;
  if (!bins || bins.every((b) => b === null)) return null;
  const groups = new Map();
  bins.forEach((b, i) => {
    if (b === null || y[i] === null || x[i] === null) return;
    if (!groups.has(b)) groups.set(b, { x: [], y: [] });
    groups.get(b).x.push(x[i]);
    groups.get(b).y.push(y[i]);
  });
  const out = { x: [], y: [], sd: [], n: [] };
  for (const [, g] of [...groups].sort((a, b) => a[0] - b[0])) {
    const mean = (a) => a.reduce((s, v) => s + v, 0) / a.length;
    const my = mean(g.y);
    out.x.push(mean(g.x));
    out.y.push(my);
    out.sd.push(Math.sqrt(mean(g.y.map((v) => (v - my) ** 2))));
    out.n.push(g.y.length);
  }
  return out;
}

function highlightTrace(x, y) {
  const row = state.shotRow;
  const visible = row !== null && y[row] !== null && y[row] !== undefined;
  return {
    type: "scatter",
    mode: "markers",
    name: row === null ? "Shot" : `Shot ${state.scan.shot[row]}`,
    x: visible ? [x.values[row]] : [],
    y: visible ? [y[row]] : [],
    marker: { size: 13, color: "rgba(0,0,0,0)", line: { color: css("--text-primary"), width: 2 } },
    hoverinfo: "skip",
  };
}

function renderCharts() {
  const charts = $("charts");
  charts.innerHTML = "";
  const x = xValues();
  const xChoice = $("x-select").value;
  for (const column of state.collected) {
    if (`col:${column}` === xChoice) continue;
    const div = document.createElement("div");
    div.className = "chart";
    div.dataset.column = column;
    charts.appendChild(div);
    const y = state.series[column] || [];
    const traces = [{
      type: "scatter",
      mode: "markers",
      name: "Shots",
      x: x.values,
      y,
      customdata: state.scan.shot,
      marker: { size: 6, color: css("--series-1"), opacity: 0.75 },
      hovertemplate: `Shot %{customdata}<br>${x.title}: %{x}<br>${column}: %{y}<extra></extra>`,
    }];
    const stats = $("show-steps").checked && !["bin", "time"].includes(xChoice) ? stepStats(x.values, y) : null;
    if (stats && stats.x.length > 1) {
      traces.push({
        type: "scatter",
        mode: "lines+markers",
        name: "Step mean ± sd",
        x: stats.x,
        y: stats.y,
        error_y: { type: "data", array: stats.sd, color: css("--series-2"), thickness: 1.5, width: 3 },
        line: { color: css("--series-2"), width: 2 },
        marker: { size: 8, color: css("--series-2"), line: { color: css("--surface-1"), width: 2 } },
        customdata: stats.n,
        hovertemplate: `Step mean<br>${x.title}: %{x:.4g}<br>${column}: %{y:.4g} ± %{error_y.array:.3g}<br>%{customdata} shots<extra></extra>`,
      });
    }
    traces.push(highlightTrace(x, y)); // always last, so a shot change restyles only it
    const layout = baseLayout(column, x.title, "");
    layout.showlegend = traces.length > 2;
    Plotly.newPlot(div, traces, layout, plotConfig);
    div.on("plotly_click", (event) => {
      const point = event.points.find((p) => p.curveNumber === 0);
      if (point) { stop(); openShot(state.scan.shot.indexOf(point.customdata)); }
    });
  }
}

// Move the ring that marks the shot on view, without redrawing the charts.
function updateChartHighlights() {
  const x = xValues();
  for (const div of $("charts").children) {
    if (!div.data) continue;
    const t = highlightTrace(x, state.series[div.dataset.column] || []);
    Plotly.restyle(div, { x: [t.x], y: [t.y], name: [t.name] }, [div.data.length - 1]);
  }
}

function renderTable() {
  const view = $("table-view");
  view.hidden = !$("show-table").checked || state.collected.length === 0;
  if (view.hidden) return;
  const columns = state.collected;
  const rows = state.scan.shot.map((shot, i) =>
    `<tr data-row="${i}"${i === state.shotRow ? ' class="selected"' : ""}><td>${shot}</td><td>${state.scan.bin[i] ?? "—"}</td>` +
    columns.map((c) => `<td>${format((state.series[c] || [])[i])}</td>`).join("") + "</tr>");
  view.innerHTML = `<table><thead><tr><th>Shot</th><th>Step</th>${columns.map((c) => `<th>${escapeHtml(c)}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table>`;
  view.querySelector("tbody").addEventListener("click", (event) => {
    const tr = event.target.closest("tr");
    if (tr) { stop(); openShot(Number(tr.dataset.row)); }
  });
}

function updateTableHighlight() {
  const view = $("table-view");
  if (view.hidden) return;
  for (const tr of view.querySelectorAll("tr.selected")) tr.classList.remove("selected");
  const tr = view.querySelector(`tr[data-row="${state.shotRow}"]`);
  if (tr) {
    tr.classList.add("selected");
    tr.scrollIntoView({ block: "nearest" });
  }
}

// --- one shot: timeline, collected values, device frames, machine settings and all its scalars

let shotScalars = null;

function shotTime(row) {
  const t = state.scan.time[row];
  return t === null ? null : new Date(t * 1000);
}

function renderTimeline() {
  const row = state.shotRow, s = state.scan;
  $("shot-slider").value = String(row);
  const time = shotTime(row), start = shotTime(0);
  const clock = time
    ? `${time.toLocaleDateString()} ${time.toLocaleTimeString([], { hour12: false })}.${String(time.getMilliseconds()).padStart(3, "0")}` +
      (start ? ` (+${((time - start) / 1000).toFixed(1)} s)` : "")
    : "no time recorded";
  const parameter = s.parameter ? ` · ${s.parameter} = <strong>${format((state.series[s.parameter] || [])[row])}</strong>` : "";
  $("timeline-label").innerHTML =
    `<strong>Shot ${s.shot[row]}</strong> of ${s.shot.length} · step ${s.bin[row] ?? "—"}${parameter} · ${clock}`;
}

async function openShot(row) {
  if (!state.scan || row < 0 || row >= state.scan.shot.length) return;
  state.shotRow = row;
  const shot = state.scan.shot[row];
  $("shot-panel").hidden = false;
  $("shot-title").textContent = `Shot ${shot}`;
  $("shot-meta").textContent = `step ${state.scan.bin[row] ?? "—"} of the scan`;
  renderTimeline();
  renderShotCollected();
  renderSettings();
  updateChartHighlights();
  updateTableHighlight();
  writeLink();
  const scalars = api("shot", { scan: state.scan.id, shot }).then((body) => {
    if (state.shotRow === row) { shotScalars = body.values; renderScalarTable(); }
  });
  await Promise.all([scalars, renderFrames()]);
}

function renderShotCollected() {
  const row = state.shotRow;
  $("shot-collected").innerHTML = state.collected.map((c) =>
    `<div class="stat"><div class="label">${escapeHtml(c)}</div><div class="value">${format((state.series[c] || [])[row])}</div></div>`).join("");
}

// A setting's range over the scan, the change below which it counts as steady, and whether it varies.
function settingRange(values) {
  const finite = values.filter((v) => v !== null);
  const min = Math.min(...finite), max = Math.max(...finite);
  const tolerance = CHANGE_FRACTION * settingScale(values);
  return { min, max, tolerance, varies: max - min > tolerance };
}

function settingScale(values) {
  const finite = values.filter((v) => v !== null).map(Math.abs).sort((a, b) => a - b);
  return finite.length ? Math.max(finite[Math.floor(finite.length / 2)], SCALE_FLOOR) : 1;
}

function renderSettings() {
  const row = state.shotRow;
  const onlyVarying = $("settings-varying").checked;
  const groups = SETTING_GROUPS.map(([title, pattern]) => ({ title, pattern, rows: [] }));
  for (const setting of state.scan.settings) {
    const group = groups.find((g) => g.pattern.test(setting.name));
    if (!group) continue;
    const values = setting.values;
    const { min, max, tolerance, varies } = settingRange(values);
    if (onlyVarying && !varies) continue;
    const value = values[row], before = row > 0 ? values[row - 1] : null;
    const changed = value !== null && before !== null && Math.abs(value - before) > tolerance;
    group.rows.push(
      `<tr${changed ? ' class="changed" title="Changed since the previous shot"' : ""}>` +
      `<td class="name">${escapeHtml(setting.name)}</td>` +
      `<td>${format(value)}${changed ? `<div class="badge">was ${format(before)}</div>` : ""}</td>` +
      `<td class="range">${varies ? `${format(min)} … ${format(max)}` : "steady"}</td></tr>`);
  }
  const html = groups.filter((g) => g.rows.length).map((g) =>
    `<div><h4>${escapeHtml(g.title)}</h4><table><tbody>${g.rows.join("")}</tbody></table></div>`).join("");
  $("settings").innerHTML = html || '<p class="muted">No setting changes during this scan.</p>';
}

function renderScalarTable() {
  const words = $("scalar-filter").value.toLowerCase().split(/\s+/).filter(Boolean);
  const rows = Object.entries(shotScalars || {})
    .filter(([name]) => words.every((w) => name.toLowerCase().includes(w)))
    .map(([name, value]) => `<tr><td>${escapeHtml(name)}</td><td>${format(value)}</td></tr>`);
  $("scalar-table").innerHTML = `<tbody>${rows.join("")}</tbody>`;
}

function renderDeviceToggles() {
  const box = $("device-toggles");
  box.innerHTML = "";
  if (!state.scan.device_list.length) {
    box.innerHTML = '<span class="muted">This scan saved no device stacks.</span>';
    return;
  }
  for (const device of state.scan.device_list) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "chip";
    chip.textContent = `${device.name} (${device.kind})`;
    chip.setAttribute("aria-pressed", String(!state.hiddenDevices.has(device.name)));
    chip.addEventListener("click", () => {
      if (state.hiddenDevices.has(device.name)) state.hiddenDevices.delete(device.name);
      else state.hiddenDevices.add(device.name);
      renderDeviceToggles();
      renderFrames();
    });
    box.appendChild(chip);
  }
}

// One panel per shown device, kept between shots so that stepping updates the plot in place.
function frameDiv(device) {
  const frames = $("device-frames");
  let div = frames.querySelector(`[data-device="${CSS.escape(device.name)}"]`);
  if (!div) {
    div = document.createElement("div");
    div.className = "frame";
    div.dataset.device = device.name;
    frames.appendChild(div);
  }
  return div;
}

async function renderFrames() {
  const frames = $("device-frames");
  for (const div of [...frames.children]) {
    if (state.hiddenDevices.has(div.dataset.device)) { Plotly.purge(div); div.remove(); }
  }
  if (state.shotRow === null) return;
  const shot = state.scan.shot[state.shotRow];
  const shown = state.scan.device_list.filter((d) => !state.hiddenDevices.has(d.name));
  // keep the panels in the device order
  for (const device of shown) frames.appendChild(frameDiv(device));
  await Promise.all(shown.map(async (device) => {
    const div = frameDiv(device);
    const request = (state.frameRequests[device.name] || 0) + 1;
    state.frameRequests[device.name] = request;
    try {
      const frame = await api("frame", { scan: state.scan.id, shot, device: device.name });
      if (state.frameRequests[device.name] === request) drawFrame(div, device, frame);
    } catch (error) {
      div.textContent = `${device.name}: ${error.message}`;
    }
  }));
}

function drawFrame(div, device, frame) {
  if (frame === null) {
    Plotly.purge(div);
    div.innerHTML = `<p class="muted" style="padding:12px">${escapeHtml(device.name)}: no frame for this shot</p>`;
    return;
  }
  if (!div.data) div.innerHTML = "";
  const title = `${device.name} · frame ${frame.frame + 1}`;
  if (device.kind === "image") {
    const ramp = css("--seq").split(",").map((c) => c.trim());
    const colorscale = ramp.map((c, i) => [i / (ramp.length - 1), c]);
    const layout = baseLayout(title, "x [px]", "y [px]");
    layout.yaxis.autorange = "reversed";
    layout.yaxis.scaleanchor = "x";
    layout.xaxis.constrain = "domain";
    layout.yaxis.constrain = "domain";
    layout.xaxis.showgrid = layout.yaxis.showgrid = false;
    layout.margin.r = 8;
    layout.uirevision = device.name; // keep the user's zoom while stepping through shots
    const step = frame.step;
    const nx = frame.z[0] ? frame.z[0].length : 0;
    Plotly.react(div, [{
      type: "heatmap",
      z: frame.z,
      x: Array.from({ length: nx }, (_, i) => i * step + step / 2),
      y: frame.z.map((_, i) => i * step + step / 2),
      colorscale,
      colorbar: { thickness: 10, outlinewidth: 0, tickfont: { size: 10 } },
      hovertemplate: "x %{x:.0f} px, y %{y:.0f} px<br>%{z:.1f} counts<extra></extra>",
    }], layout, plotConfig);
    return;
  }
  const isSpectrum = /interpSpec$/i.test(device.name);
  const layout = baseLayout(title, isSpectrum ? "Energy [MeV]" : "x", isSpectrum ? "Charge density" : "value");
  layout.uirevision = device.name;
  Plotly.react(div, [{
    type: "scatter",
    mode: "lines",
    x: frame.x,
    y: frame.y,
    line: { color: css("--series-1"), width: 2 },
    hovertemplate: "%{x:.4g}: %{y:.4g}<extra></extra>",
  }], layout, plotConfig);
}

// --- playback: step through the shots in time order, waiting for each shot's frames

function stop() {
  state.playing = false;
  $("play").textContent = "▶ Play";
  $("play").setAttribute("aria-label", "Play");
}

async function play() {
  if (state.playing || !state.scan) return;
  if (state.shotRow === null || state.shotRow >= state.scan.shot.length - 1) await openShot(0);
  state.playing = true;
  $("play").textContent = "⏸ Pause";
  $("play").setAttribute("aria-label", "Pause");
  while (state.playing && state.shotRow < state.scan.shot.length - 1) {
    const started = performance.now();
    await openShot(state.shotRow + 1);
    const wait = 1000 / Number($("speed").value) - (performance.now() - started);
    if (wait > 0) await new Promise((resolve) => setTimeout(resolve, wait));
  }
  stop();
}

function step(delta) {
  stop();
  if (state.shotRow !== null) openShot(Math.min(Math.max(state.shotRow + delta, 0), state.scan.shot.length - 1));
}

// --- wiring

$("column-filter").addEventListener("input", filterColumns);
$("x-select").addEventListener("change", () => { renderCharts(); writeLink(); });
$("show-steps").addEventListener("change", renderCharts);
$("show-table").addEventListener("change", renderTable);
$("scalar-filter").addEventListener("input", renderScalarTable);
$("settings-varying").addEventListener("change", renderSettings);
$("first-shot").addEventListener("click", () => { stop(); openShot(0); });
$("last-shot").addEventListener("click", () => { stop(); openShot(state.scan.shot.length - 1); });
$("prev-shot").addEventListener("click", () => step(-1));
$("next-shot").addEventListener("click", () => step(1));
$("play").addEventListener("click", () => (state.playing ? stop() : play()));
$("shot-slider").addEventListener("input", (event) => { stop(); openShot(Number(event.target.value)); });
$("download").addEventListener("click", (event) => {
  if (!state.collected.length) event.preventDefault();
});
document.addEventListener("keydown", (event) => {
  if (state.shotRow === null || ["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement.tagName)) return;
  if (event.key === "ArrowLeft") { event.preventDefault(); step(-1); }
  if (event.key === "ArrowRight") { event.preventDefault(); step(1); }
  if (event.key === " ") { event.preventDefault(); state.playing ? stop() : play(); }
});
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  renderCharts();
  $("device-frames").innerHTML = "";
  if (state.shotRow !== null) renderFrames();
});

loadScans().catch((error) => { $("scan-info").textContent = `Could not load the scans: ${error.message}`; });
