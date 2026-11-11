"use strict";

// The HTU twin viewer: a dataset (a recorded scan), a step slider, the beamline synoptic with the
// twin's values at that step, the twin's output beside the measurement, and the values below.

// edits: twin input key -> value, sent with every step (see server.py's docstring)
const state = { datasets: [], dataset: null, edits: {}, request: 0, selecting: null, source: "fit" };

const $ = (id) => document.getElementById(id);
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const plotConfig = { displayModeBar: false, responsive: true };

// The synoptic's element for the twin key a scan steps (the dataset's `scanned`).
const SCANNED_ELEMENT = { chicane_current: "chicane" };

// The step slider's label: its number, and, for a dataset of regrouped shots, the group's description.
function stepLabel(i) {
  const d = state.dataset;
  return `${i + 1} of ${d.steps}` + (d.step_labels ? ` · ${d.step_labels[i]}` : "");
}

async function api(path) {
  const r = await fetch(path);
  const v = await r.json();
  if (!r.ok) throw new Error(v.error || r.statusText);
  return v;
}

function baseLayout(title, x, y) {
  const ink = css("--text-secondary");
  const grid = css("--grid");
  return {
    title: { text: title, font: { size: 13, color: css("--text-primary") }, x: 0, xanchor: "left" },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { color: ink, size: 11 },
    margin: { l: 52, r: 12, t: 34, b: 40 },
    xaxis: { title: { text: x }, gridcolor: grid, zeroline: false },
    yaxis: { title: { text: y }, gridcolor: grid, zeroline: false },
    legend: { orientation: "h", y: 0.98, yanchor: "top", x: 0.98, xanchor: "right" },
  };
}

function colorscale() {
  const ramp = css("--seq").split(",").map((c) => c.trim());
  return ramp.map((c, i) => [i / (ramp.length - 1), c]);
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
}

// A knob's value for its input: four significant digits, empty for none.
function knobValue(v) {
  return v === null || v === undefined ? "" : String(Number(v.toPrecision(4)));
}

function knobsHtml(knobs) {
  return '<div class="knobs">' + knobs.map(([key, label, value, unit]) => {
    const cls = key in state.edits ? ' class="edited"' : "";
    return `<label>${escapeHtml(label)}<input type="number" step="any" data-key="${escapeHtml(key)}"`
      + ` value="${knobValue(value)}"${cls} aria-label="${escapeHtml(label)}">`
      + `<span class="muted">${escapeHtml(unit)}</span></label>`;
  }).join("") + "</div>";
}

function fmt(v) {
  if (v === null || v === undefined) return "—";
  const a = Math.abs(v);
  return a !== 0 && (a < 0.01 || a >= 1e4) ? v.toExponential(2) : v.toFixed(a < 1 ? 3 : 1);
}

// --- the synoptic: the electron line in beam order, each element's twin value below it

function drawSynoptic(settings, scanned) {
  const svg = $("synoptic");
  const w = Math.max(svg.clientWidth, 1060);
  const n = settings.length;
  const gap = w / n;
  const y = 52;
  const bw = Math.min(gap - 8, 96);
  const mark = SCANNED_ELEMENT[scanned] || scanned;
  let s = `<line class="beam" x1="8" y1="${y}" x2="${w - 8}" y2="${y}"/>`;
  settings.forEach((e, i) => {
    const cx = gap * (i + 0.5);
    const cls = `el${e.id === mark ? " scanned" : ""}`;
    s += `<g><title>${escapeHtml(`${e.label}\nlogged: ${e.logged}\ntwin: ${e.twin}\n${e.note}`)}</title>`;
    s += `<rect class="${cls}" x="${cx - bw / 2}" y="${y - 14}" width="${bw}" height="28" rx="4"/>`;
    s += `<text x="${cx}" y="${y + 4}" text-anchor="middle">${escapeHtml(e.label)}</text>`;
    String(e.twin).split(/[,;]\s*/).slice(0, 4).forEach((t, j) => {
      s += `<text class="value" x="${cx}" y="${y + 30 + j * 13}" text-anchor="middle">${escapeHtml(t)}</text>`;
    });
    s += "</g>";
  });
  svg.setAttribute("viewBox", `0 0 ${w} 150`);
  svg.innerHTML = s;
}

// --- the plots

function heatmap(div, title, z, x, y, xTitle, yTitle, reversed, seam) {
  const layout = baseLayout(title, xTitle, yTitle);
  if (seam) {
    // where Cam1's image ends and Cam2's begins
    layout.shapes = [{ type: "line", xref: "x", yref: "paper", x0: seam, x1: seam, y0: 0, y1: 1,
      line: { color: css("--text-muted"), width: 1, dash: "dash" } }];
  }
  layout.xaxis.showgrid = layout.yaxis.showgrid = false;
  if (reversed) layout.yaxis.autorange = "reversed";
  // square pixels: the image keeps its shape (a pixel is `x[1] - x[0]` wide and `y[1] - y[0]` tall in
  // axis units, one unit each when the axes are the pixel numbers)
  layout.yaxis.scaleanchor = "x";
  layout.yaxis.scaleratio = x ? (x[1] - x[0]) / (y[1] - y[0]) : 1;
  layout.xaxis.constrain = layout.yaxis.constrain = "domain";
  layout.uirevision = title;
  // the plot area is 286px tall (the div less its margins), square pixels make it that much wide
  // POSIT: 286 is 360px (style.css's .plot) less baseLayout's top and bottom margins; 440px keeps the longest title
  div.style.width = `${Math.max(440, Math.round((286 * z[0].length) / z.length) + 64)}px`;
  const trace = { type: "heatmap", z, colorscale: colorscale(), showscale: false, hoverongaps: false };
  if (x) { trace.x = x; trace.y = y; }
  Plotly.react(div, [trace], layout, plotConfig);
}

function axis(a0, a1, d) {
  const out = [];
  for (let v = a0 + d / 2; v < a1; v += d) out.push(v);
  return out;
}

function drawPlots(r) {
  const plots = $("plots");
  const want = r.kind === "aline" ? ["m", "t"] : r.kind === "magspec" ? ["s", "m", "t"] : ["s"];
  if (plots.dataset.layout !== want.join()) {
    plots.innerHTML = want
      .map((k) => `<div class="plot${k === "s" ? "" : " image"}" id="plot-${k}"></div>`)
      .join("");
    plots.dataset.layout = want.join();
  }
  if (want.includes("s")) {
    const layout = baseLayout(`Spectrum · step ${r.step + 1}`, "Energy [MeV]", "Density [1/MeV]");
    layout.uirevision = r.scan;
    Plotly.react($("plot-s"), [
      { type: "scatter", mode: "lines", name: "measured", x: r.energy_mev, y: r.measured.spectrum,
        line: { color: css("--series-2"), width: 2 } },
      { type: "scatter", mode: "lines", name: "twin", x: r.energy_mev, y: r.twin.spectrum,
        line: { color: css("--series-1"), width: 2 } },
    ], layout, plotConfig);
  }
  if (r.kind === "aline") {
    heatmap($("plot-m"), "Measured: UC_ALineEBeam3 (step mean, background subtracted)",
      r.measured.image, null, null, "column", "row", true);
    if (r.twin.image) {
      heatmap($("plot-t"), "Twin: rendered as the camera sees it (centred on its spot)",
        r.twin.image, null, null, "column", "row", true);
    } else {
      $("plot-t").innerHTML = '<p class="muted">The twin puts nothing on the camera at this step.</p>';
    }
  }
  if (r.kind === "magspec") {
    const [[e0, e1, de], [a0, a1, da]] = r.image_axes;
    const x = axis(e0, e1, de);
    const y = axis(a0, a1, da);
    const st = r.stitch;
    const how = [st.scale ? "each scaled to its spectrum" : "raw counts",
      st.align ? `Cam2 shifted ${st.cam2_shift >= 0 ? "+" : ""}${st.cam2_shift}` : "not aligned"].join(", ");
    heatmap($("plot-m"), `Measured: Cam1 | Cam2 (${how})`, r.measured.image, x, y,
      "Energy [MeV]", "AngleAxis", false, r.seam_mev);
    heatmap($("plot-t"), "Twin: energy against AngleAxis (twin's AngleAxis scale)", r.twin.image, x, y,
      "Energy [MeV]", "AngleAxis", false, r.seam_mev);
  }
  // the images' widths changed the room the spectrum has, and Plotly only follows the window's size
  for (const k of want) if ($(`plot-${k}`).data) Plotly.Plots.resize($(`plot-${k}`));
}

// --- the values

function drawTables(r, scanned) {
  $("numbers").tBodies[0].innerHTML = r.numbers
    .map(([q, m, t]) => `<tr><td>${escapeHtml(q)}</td><td class="num">${fmt(m)}</td><td class="num">${fmt(t)}</td></tr>`)
    .join("");
  const mark = SCANNED_ELEMENT[scanned] || scanned;
  // keep the focus on the input being worked on across the rebuild
  const focused = document.activeElement && document.activeElement.dataset
    ? document.activeElement.dataset.key : null;
  $("settings").tBodies[0].innerHTML = r.settings
    .map((e) => `<tr class="${e.id === mark ? "scanned" : ""}"><td>${escapeHtml(e.label)}</td><td>${escapeHtml(e.logged)}</td>`
      + `<td>${e.knobs && e.knobs.length ? knobsHtml(e.knobs) : escapeHtml(e.twin)}</td>`
      + `<td class="muted">${escapeHtml(e.note)}</td></tr>`)
    .join("");
  if (focused) {
    const i = $("settings").querySelector(`input[data-key="${CSS.escape(focused)}"]`);
    if (i) i.focus();
  }
}

function drawEdits() {
  const n = Object.keys(state.edits).length;
  $("reset").disabled = n === 0;
  $("reset").textContent = n ? `Reset ${n} edit${n > 1 ? "s" : ""}` : "No edits";
}

// --- loading

async function loadStep() {
  const d = state.dataset;
  const i = Number($("step").value);
  $("step-label").textContent = stepLabel(i);
  syncUrl(i);
  const id = ++state.request;
  $("status").textContent = "running the twin…";
  $("controls").classList.add("busy");
  try {
    const e = Object.keys(state.edits).length ? `&edits=${encodeURIComponent(JSON.stringify(state.edits))}` : "";
    const c = `&scale=${$("stitch-scale").checked ? 1 : 0}&align=${$("stitch-align").checked ? 1 : 0}`;
    const r = await api(`/api/step?scan=${encodeURIComponent(d.scan)}&step=${i}${e}${c}&source=${encodeURIComponent(state.source)}`);
    if (id !== state.request) return; // a later step was asked for meanwhile
    drawSynoptic(r.settings, d.scanned);
    drawPlots(r);
    drawTables(r, d.scanned);
    $("status").textContent = "";
  } catch (e) {
    if (id === state.request) $("status").textContent = `error: ${e.message}`;
  } finally {
    if (id === state.request) $("controls").classList.remove("busy");
  }
}

// Keeps the address bar at the view: the dataset, its step (from 1) and a source other than the first.
function syncUrl(i) {
  const q = new URLSearchParams({ scan: state.dataset.scan, step: String(i + 1) });
  if (state.source !== $("source-select").options[0].value) q.set("source", state.source);
  try {
    history.replaceState(null, "", `?${q}`);
  } catch (e) {
    // POSIT: a page that may not change its address (a sandboxed frame) just goes without
  }
}

// Selects a dataset: its steps are read when it is first selected, not when the list is built.
// `step` is the 0-based step to show, 0 unless a link asked for another.
async function selectDataset(scan, step = 0) {
  const d = state.datasets.find((x) => x.scan === scan);
  state.selecting = scan;
  $("controls").classList.add("busy");
  $("status").textContent = "reading the scan…";
  if (d.steps === undefined) {
    try {
      Object.assign(d, await api(`/api/dataset?scan=${encodeURIComponent(scan)}`));
    } catch (e) {
      if (state.selecting === scan) {
        $("status").textContent = `error: ${e.message}`;
        $("controls").classList.remove("busy");
      }
      return;
    }
  }
  if (state.selecting !== scan) return; // another dataset was selected meanwhile
  state.dataset = d;
  const s = $("step");
  s.max = String(state.dataset.steps - 1);
  s.value = String(Math.min(Math.max(step, 0), state.dataset.steps - 1));
  s.disabled = state.dataset.steps < 2;
  $("stitch").hidden = state.dataset.kind !== "magspec";
  $("plots").dataset.layout = "";
  loadStep();
}

let timer = null;

async function init() {
  $("status").textContent = "Loading datasets…";
  const v = await api("/api/datasets");
  if (! v.datasets || ! v.datasets.length) {
    $("status").textContent = "Error loading datasets";
    return;
  }
  state.datasets = v.datasets;
  $("source").textContent = `Twin: geecs-lume-twin with the line corrections from ${v.source}; the LPA source is chosen below`;
  $("dataset").innerHTML = v.datasets
    .map((d) => `<option value="${d.scan}">${d.scan}: ${escapeHtml(d.title)}</option>`)
    .join("");
  $("dataset").addEventListener("change", (e) => selectDataset(e.target.value));
  // the sources: the fit's, and any fbpic runs; a source edit only applies to the fit's
  $("source-select").innerHTML = v.sources
    .map((s) => `<option value="${escapeHtml(s.id)}">${escapeHtml(s.label)}</option>`)
    .join("");
  $("source-select").hidden = v.sources.length < 2;
  $("source-select").parentElement.hidden = v.sources.length < 2;
  $("source-select").addEventListener("change", (e) => {
    state.source = e.target.value;
    for (const k of Object.keys(state.edits)) if (k.startsWith("source.")) delete state.edits[k];
    drawEdits();
    loadStep();
  });
  // an input's change (Enter or leaving it) reruns the twin with it; an emptied one is unedited
  $("settings").addEventListener("change", (e) => {
    const k = e.target.dataset.key;
    if (!k) return;
    const v = e.target.value.trim() === "" ? NaN : Number(e.target.value);
    if (Number.isFinite(v)) state.edits[k] = v;
    else delete state.edits[k];
    drawEdits();
    loadStep();
  });
  $("reset").addEventListener("click", () => {
    state.edits = {};
    drawEdits();
    loadStep();
  });
  for (const k of ["stitch-scale", "stitch-align"]) $(k).addEventListener("change", loadStep);
  drawEdits();
  $("step").addEventListener("input", () => {
    $("step-label").textContent = stepLabel(Number($("step").value));
    clearTimeout(timer);
    timer = setTimeout(loadStep, 150);
  });
  const q = new URLSearchParams(location.search).get("scan");
  const d = v.datasets.find((x) => x.scan === q || x.scan.endsWith(`/${q}`)) || v.datasets[0];
  const src = new URLSearchParams(location.search).get("source");
  if (src && v.sources.some((x) => x.id === src)) {
    state.source = src;
    $("source-select").value = src;
  }
  $("dataset").value = d.scan;
  // the link's step counts from 1; one that is not a number is the first
  selectDataset(d.scan, (parseInt(new URLSearchParams(location.search).get("step"), 10) || 1) - 1);
}

init();
