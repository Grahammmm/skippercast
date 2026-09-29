// Meteogram renderer: one inline SVG for the hourly series, a readout for the
// selected hour, and a visually hidden data table. The geometry comes from
// meteogram-core.js; this file only owns the DOM and input handling.
import { meteogramSVG, summaryText, indexAt, layout, hasData, formatTime, scoreLevel } from "./meteogram-core.js";

const views = new WeakMap();
const fmt = (n, d = 1) => (Number.isFinite(n) ? n.toFixed(d) : "—");
let uid = 0;

function readout(series, i, timeZone) {
  const t = series.times[i];
  if (!Number.isFinite(t)) return "";
  const when = formatTime(t, timeZone, { weekday: "short", hour: "numeric" });
  const score = series.score[i];
  const level = scoreLevel(score, series.hazard?.[i]);
  const parts = [
    `Wind ${fmt(series.wind[i], 0)}${Number.isFinite(series.gust[i]) ? `–${fmt(series.gust[i], 0)}` : ""} kt`,
    `Seas ${fmt(series.sea[i])} ft${Number.isFinite(series.period[i]) ? ` @ ${fmt(series.period[i], 0)} s` : ""}`,
    `Tide ${fmt(series.tide[i])} ft`,
    Number.isFinite(score) ? `${fmt(score)}/10${series.hazard?.[i] ? " · hazard" : ""}` : "No score",
  ];
  if (series.agreement?.[i] === "differ") parts.push("models differ");
  if (series.provisional?.[i]) parts.push("outlook");
  return { when, text: parts.join(" · "), level };
}

function tableHTML(series, timeZone) {
  const rows = series.times.map((t, i) => `<tr><th scope="row">${formatTime(t, timeZone, { weekday: "short", month: "short", day: "numeric", hour: "numeric" })}</th><td>${fmt(series.wind[i], 0)}</td><td>${fmt(series.gust[i], 0)}</td><td>${fmt(series.sea[i])}</td><td>${fmt(series.period[i], 0)}</td><td>${fmt(series.tide[i])}</td><td>${fmt(series.score[i])}${series.hazard?.[i] ? " hazard" : ""}</td><td>${series.agreement?.[i] === "differ" ? "Differ" : series.agreement?.[i] === "agree" ? "Agree" : "Unknown"}</td><td>${series.provisional?.[i] ? "Outlook" : "Forecast"}</td></tr>`).join("");
  return `<table><caption>Hourly forecast data. A dash means the value is unavailable.</caption><thead><tr><th scope="col">Hour</th><th scope="col">Wind kt</th><th scope="col">Gust kt</th><th scope="col">Seas ft</th><th scope="col">Period s</th><th scope="col">Tide ft</th><th scope="col">Score /10</th><th scope="col">Models</th><th scope="col">Status</th></tr></thead><tbody>${rows}</tbody></table>`;
}

/**
 * Render (or update) a meteogram inside `container`.
 * options: {selected, now (epoch s), timeZone, onSelect(index)}
 * Re-calling with the same `series` object and width only moves the cursor.
 */
export function renderMeteogram(container, series, options = {}) {
  let view = views.get(container);
  if (!view) {
    view = { id: `mg${++uid}`, series: null, width: 0, selected: 0, options: {} };
    container.classList.add("meteogram");
    container.innerHTML = `<div class="meteogram-plot" tabindex="0" role="group" aria-roledescription="meteogram" aria-label="Seven-day forecast graph. Left and right arrow keys change the forecast hour; Page Up and Page Down move a day."></div><p class="meteogram-readout" aria-live="polite"></p><div class="sr-only meteogram-table"></div>`;
    view.plot = container.querySelector(".meteogram-plot");
    view.readout = container.querySelector(".meteogram-readout");
    view.table = container.querySelector(".meteogram-table");
    const choose = (i, focus = false) => {
      const n = view.series?.times.length || 0;
      if (!n) return;
      i = Math.max(0, Math.min(n - 1, i));
      if (i === view.selected && !focus) return;
      moveCursor(view, i);
      view.options.onSelect?.(i);
    };
    const fromPointer = (e) => {
      const box = view.plot.querySelector("svg")?.getBoundingClientRect();
      if (!box || !box.width) return;
      const px = ((e.clientX - box.left) / box.width) * view.width;
      choose(indexAt(px, view.width, view.series.times.length));
    };
    let dragging = false;
    view.plot.addEventListener("pointerdown", (e) => { if (e.button !== 0 && e.pointerType === "mouse") return; dragging = true; view.plot.setPointerCapture?.(e.pointerId); fromPointer(e); });
    view.plot.addEventListener("pointermove", (e) => { if (dragging) fromPointer(e); });
    for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) view.plot.addEventListener(type, () => { dragging = false; });
    view.plot.addEventListener("keydown", (e) => {
      const n = view.series?.times.length || 0;
      const step = { ArrowLeft: -1, ArrowRight: 1, PageUp: -24, PageDown: 24 }[e.key];
      if (step) choose(view.selected + step);
      else if (e.key === "Home") choose(0);
      else if (e.key === "End") choose(n - 1);
      else return;
      e.preventDefault();
    });
    if (typeof ResizeObserver === "function") {
      view.resize = new ResizeObserver(() => {
        const w = Math.round(view.plot.clientWidth);
        if (w && Math.abs(w - view.width) >= 4 && view.series) draw(view);
      });
      view.resize.observe(view.plot);
    }
    views.set(container, view);
  }
  view.options = options;
  const selected = Number.isFinite(options.selected) ? options.selected : view.selected;
  const width = Math.round(view.plot.clientWidth) || options.width || 360;
  if (series !== view.series || width !== view.width || options.now !== view.now) {
    view.series = series;
    view.now = options.now;
    view.selected = selected;
    draw(view);
  } else moveCursor(view, selected);
  return view;
}

function draw(view) {
  const { series, options } = view;
  const timeZone = options.timeZone || "America/Los_Angeles";
  view.width = Math.round(view.plot.clientWidth) || options.width || 360;
  if (!hasData(series)) {
    view.plot.innerHTML = `<p class="meteogram-empty">Forecast graph unavailable. No wind, seas, tide or score data for these hours.</p>`;
    view.readout.textContent = "";
    view.table.innerHTML = "";
    return;
  }
  view.plot.innerHTML = meteogramSVG(series, { width: view.width, now: options.now, selected: view.selected, timeZone, id: view.id, label: summaryText(series, { timeZone }) });
  if (view.tableFor !== series) { view.table.innerHTML = tableHTML(series, timeZone); view.tableFor = series; }
  moveCursor(view, view.selected, true);
}

function moveCursor(view, i, force = false) {
  const n = view.series?.times.length || 0;
  if (!n) return;
  i = Math.max(0, Math.min(n - 1, i));
  if (i === view.selected && !force && view.plot.dataset.selected === String(i)) return;
  view.selected = i;
  view.plot.dataset.selected = String(i);
  const g = view.plot.querySelector(".mg-cursor");
  if (g) g.setAttribute("transform", `translate(${layout(view.width, n).x(i).toFixed(1)},0)`);
  const r = readout(view.series, i, view.options.timeZone || "America/Los_Angeles");
  if (r) {
    view.readout.innerHTML = `<strong></strong> <span class="mg-chip mg-${r.level}" aria-hidden="true"></span><span></span>`;
    view.readout.querySelector("strong").textContent = r.when;
    view.readout.querySelector("span:last-child").textContent = r.text;
  }
}
