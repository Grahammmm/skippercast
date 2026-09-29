// Pure data -> SVG geometry for the 7-day meteogram. No DOM, no network, no
// region state, so every function here runs (and is tested) in node.
//
// Series are columnar arrays of equal length, one entry per forecast hour:
//   {times, wind, gust, sea, period, tide, score, hazard, agreement, provisional}
// A missing value is null. Missing values are never drawn: lines lift the pen,
// bars and ticks are skipped, and the score band shows "unknown" instead of a
// colour. Nothing is interpolated across a gap or substituted with zero.

export const HOUR = 3600;
export const PROVISIONAL_HOUR = 72;
export const LEVELS = ["go", "caution", "rough", "unknown"];

const finite = (n) => typeof n === "number" && Number.isFinite(n);
const r1 = (n) => Math.round(n * 10) / 10;

/** Score colour level: >= 7 go, 4–6.9 caution, < 4 or hazard rough, missing unknown. */
export function scoreLevel(score, hazard = false) {
  if (!finite(score)) return "unknown";
  if (hazard || score < 4) return "rough";
  return score >= 7 ? "go" : "caution";
}

/** Round a maximum up to a readable step; never below `floor`, never zero. */
export function niceCeil(value, step, floor = step) {
  const v = finite(value) ? value : 0;
  return Math.max(floor, Math.ceil(v / step) * step || step);
}

export function extent(values) {
  let min = Infinity, max = -Infinity;
  for (const v of values) if (finite(v)) { if (v < min) min = v; if (v > max) max = v; }
  return min === Infinity ? null : [min, max];
}

export function linearScale(d0, d1, r0, r1) {
  const span = d1 - d0 || 1;
  return (v) => r0 + ((v - d0) / span) * (r1 - r0);
}

/** Runs of consecutive finite values: [[startIndex, endIndex], ...] (inclusive). */
export function segments(values) {
  const out = [];
  let start = -1;
  for (let i = 0; i <= values.length; i++) {
    const ok = i < values.length && finite(values[i]);
    if (ok && start < 0) start = i;
    if (!ok && start >= 0) { out.push([start, i - 1]); start = -1; }
  }
  return out;
}

/** Polyline with a fresh M after every gap. A lone sample draws a short dash so it is visible. */
export function linePath(values, x, y) {
  let d = "";
  for (const [a, b] of segments(values)) {
    if (a === b) { const cx = x(a), cy = r1(y(values[a])); d += `M${r1(cx - 1.5)},${cy}H${r1(cx + 1.5)}`; continue; }
    d += `M${r1(x(a))},${r1(y(values[a]))}`;
    for (let i = a + 1; i <= b; i++) d += `L${r1(x(i))},${r1(y(values[i]))}`;
  }
  return d;
}

/** Filled area to `base` (a y pixel), one closed shape per run of data. */
export function areaPath(values, x, y, base) {
  let d = "";
  const b0 = r1(base);
  for (const [a, b] of segments(values)) {
    const left = a === b ? x(a) - 1.5 : x(a), right = a === b ? x(a) + 1.5 : x(b);
    d += `M${r1(left)},${b0}`;
    if (a === b) d += `L${r1(left)},${r1(y(values[a]))}L${r1(right)},${r1(y(values[a]))}`;
    else for (let i = a; i <= b; i++) d += `L${r1(x(i))},${r1(y(values[i]))}`;
    d += `L${r1(right)},${b0}Z`;
  }
  return d;
}

/** Vertical bars from `base` to y(v), centred on x(i). One path for all bars. */
export function barsPath(values, x, y, base, width) {
  let d = "";
  const half = width / 2, b0 = r1(base);
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (!finite(v) || v <= 0) continue; // 0 kt is a real value but has no bar height
    d += `M${r1(x(i) - half)},${b0}V${r1(y(v))}h${r1(width)}V${b0}Z`;
  }
  return d;
}

/** Short horizontal ticks at y(v), centred on x(i). */
export function ticksPath(values, x, y, width) {
  let d = "";
  const half = width / 2;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (!finite(v)) continue;
    d += `M${r1(x(i) - half)},${r1(y(v))}h${r1(width)}`;
  }
  return d;
}

/** Runs of equal level: [{level, start, end}] (inclusive indices). */
export function runs(levels) {
  const out = [];
  for (let i = 0; i < levels.length; i++) {
    const last = out.at(-1);
    if (last && last.level === levels[i]) last.end = i;
    else out.push({ level: levels[i], start: i, end: i });
  }
  return out;
}

/** First index marked provisional, or null when none is. */
export function provisionalStart(series) {
  const flags = series.provisional || [];
  const i = flags.findIndex(Boolean);
  return i < 0 ? null : i;
}

const formatters = new Map();
function formatter(timeZone, opts) {
  const key = timeZone + JSON.stringify(opts);
  if (!formatters.has(key)) formatters.set(key, new Intl.DateTimeFormat("en-US", { timeZone, ...opts }));
  return formatters.get(key);
}
export const formatTime = (t, timeZone, opts) => formatter(timeZone, opts).format(new Date(t * 1000));

/** Local calendar-day starts within the series: [{index, key, label}]. */
export function dayStarts(times, timeZone = "America/Los_Angeles") {
  const keyOf = formatter(timeZone, { year: "numeric", month: "2-digit", day: "2-digit" });
  const out = [];
  let prev = null;
  for (let i = 0; i < times.length; i++) {
    const key = keyOf.format(new Date(times[i] * 1000));
    if (key !== prev) out.push({ index: i, key, label: formatTime(times[i], timeZone, { weekday: "short", day: "numeric" }) });
    prev = key;
  }
  return out;
}

/** Layout for a given pixel width. Lanes share the time axis; each lane has its own single y-axis. */
export function layout(width = 360, n = 169) {
  const left = 30, right = 8, plotW = Math.max(60, width - left - right), step = plotW / Math.max(1, n);
  const lanes = {
    days: { top: 0, bottom: 14 },
    score: { top: 17, bottom: 27 },
    agree: { top: 29, bottom: 32 },
    wind: { top: 42, bottom: 106 },
    sea: { top: 118, bottom: 160 },
    tide: { top: 172, bottom: 202 },
    foot: { top: 204, bottom: 218 },
  };
  return { width, height: 218, left, right, plotW, step, lanes, x: (i) => left + (i + 0.5) * step };
}

export function agreementLevel(a, b) {
  const ok = (m) => finite(m?.wind) && finite(m?.sea);
  if (!ok(a) || !ok(b)) return "unknown";
  return Math.abs(a.wind - b.wind) > 4 || Math.abs(a.sea - b.sea) > 1 ? "differ" : "agree";
}

const fmt = (n, d = 1) => (finite(n) ? n.toFixed(d) : "—");

/** One-sentence summary for aria-label. States gaps and the provisional boundary. */
export function summaryText(series, { timeZone = "America/Los_Angeles" } = {}) {
  const t = series.times, n = t.length;
  if (!n) return "Forecast graph unavailable.";
  const when = (i) => formatTime(t[i], timeZone, { weekday: "short", month: "short", day: "numeric", hour: "numeric" });
  const parts = [`Hourly forecast from ${when(0)} to ${when(n - 1)}.`];
  const w = extent(series.wind), g = extent(series.gust), s = extent(series.sea), td = extent(series.tide);
  parts.push(w ? `Wind ${fmt(w[0], 0)} to ${fmt(w[1], 0)} knots${g ? `, gusts up to ${fmt(g[1], 0)}` : ", gusts unavailable"}.` : "Wind unavailable.");
  parts.push(s ? `Seas ${fmt(s[0])} to ${fmt(s[1])} feet.` : "Seas unavailable.");
  parts.push(td ? `Tide ${fmt(td[0])} to ${fmt(td[1])} feet.` : "Tide unavailable.");
  let best = -1;
  series.score.forEach((v, i) => { if (finite(v) && !series.hazard?.[i] && (best < 0 || v > series.score[best])) best = i; });
  parts.push(best >= 0 ? `Best hourly score ${fmt(series.score[best])} of 10 at ${when(best)}.` : "No hourly score available.");
  const p = provisionalStart(series);
  if (p !== null) parts.push(`From ${when(p)} the forecast is a provisional outlook.`);
  const missing = t.filter((_, i) => !finite(series.wind[i]) && !finite(series.sea[i])).length;
  if (missing) parts.push(`${missing} of ${n} hours have no wind or seas data.`);
  return parts.join(" ");
}

export function hasData(series) {
  return ["wind", "sea", "tide", "score"].some((k) => (series[k] || []).some(finite));
}

/**
 * The complete SVG markup (a string) for one series. The selected-hour cursor is
 * a <g> positioned by transform so moving it never rebuilds the paths.
 */
export function meteogramSVG(series, { width = 360, now = null, selected = 0, timeZone = "America/Los_Angeles", id = "mg", label = "" } = {}) {
  const n = series.times.length;
  const L = layout(width, n), { lanes, x, left, plotW } = L, right = left + plotW;
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const windMax = niceCeil(Math.max(extent(series.wind)?.[1] ?? 0, extent(series.gust)?.[1] ?? 0), 5, 15);
  const seaMax = niceCeil(extent(series.sea)?.[1], 2, 4);
  const te = extent(series.tide) || [0, 4];
  const tideMin = Math.min(0, Math.floor(te[0])), tideMax = Math.max(tideMin + 4, Math.ceil(te[1]));
  const yWind = linearScale(0, windMax, lanes.wind.bottom, lanes.wind.top);
  const ySea = linearScale(0, seaMax, lanes.sea.bottom, lanes.sea.top);
  const yTide = linearScale(tideMin, tideMax, lanes.tide.bottom, lanes.tide.top);
  const barW = Math.max(1, L.step * 0.72);
  const xEdge = (i) => left + i * L.step;
  const out = [];
  out.push(`<svg class="meteogram-svg" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${L.height}" width="${width}" height="${L.height}" role="img" aria-label="${esc(label || summaryText(series, { timeZone }))}" focusable="false">`);
  out.push(`<defs><pattern id="${id}-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="6" class="mg-hatch-line"/></pattern></defs>`);
  // Lane frames, axis labels (one y-axis per lane; lanes share only time).
  const lane = (key, max, min, unit, name) => {
    const { top, bottom } = lanes[key];
    out.push(`<path class="mg-grid" d="M${left},${bottom}H${right}M${left},${top}H${right}"/>`);
    out.push(`<text class="mg-axis" x="${left - 4}" y="${top + 4}" text-anchor="end">${max}</text><text class="mg-axis" x="${left - 4}" y="${bottom}" text-anchor="end">${min}</text>`);
    out.push(`<text class="mg-lane" x="${left + 6}" y="${top - 3}">${name} <tspan class="mg-unit">${unit}</tspan></text>`);
  };
  lane("wind", windMax, 0, "kt", "Wind · gust");
  lane("sea", seaMax, 0, "ft", "Seas");
  lane("tide", tideMax, tideMin, "ft", "Tide");
  // Day separators and labels.
  const days = dayStarts(series.times, timeZone);
  days.forEach((d, k) => {
    const dx = r1(xEdge(d.index));
    if (d.index > 0) out.push(`<path class="mg-day" d="M${dx},${lanes.score.top}V${lanes.tide.bottom}"/>`);
    // Label a day only when its column is wide enough (a short first or last day stays unlabelled).
    const room = ((days[k + 1]?.index ?? n) - d.index) * L.step;
    if (room >= 34) out.push(`<text class="mg-daylabel" x="${r1(dx + 2)}" y="11">${esc(d.label)}</text>`);
  });
  // Score band + model agreement strip.
  const levels = series.times.map((_, i) => scoreLevel(series.score[i], series.hazard?.[i]));
  for (const r of runs(levels))
    out.push(`<rect class="mg-score mg-${r.level}" x="${r1(xEdge(r.start))}" y="${lanes.score.top}" width="${r1((r.end - r.start + 1) * L.step)}" height="${lanes.score.bottom - lanes.score.top}"><title>${r.level === "unknown" ? "No score" : r.level === "go" ? "Good · 7+" : r.level === "caution" ? "Fair · 4–6.9" : "Rough · under 4 or hazard"}</title></rect>`);
  for (const r of runs(series.agreement || []))
    if (r.level === "differ") out.push(`<rect class="mg-differ" x="${r1(xEdge(r.start))}" y="${lanes.agree.top}" width="${r1((r.end - r.start + 1) * L.step)}" height="${lanes.agree.bottom - lanes.agree.top}"/>`);
  // Data layers.
  out.push(`<path class="mg-tide" d="${areaPath(series.tide, x, yTide, yTide(Math.max(tideMin, Math.min(0, tideMax))))}"/>`);
  out.push(`<path class="mg-tide-line" d="${linePath(series.tide, x, yTide)}"/>`);
  out.push(`<path class="mg-wind" d="${barsPath(series.wind, x, yWind, lanes.wind.bottom, barW)}"/>`);
  out.push(`<path class="mg-gust" d="${ticksPath(series.gust, x, yWind, Math.max(3, L.step * 1.6))}"/>`);
  out.push(`<path class="mg-sea" d="${linePath(series.sea, x, ySea)}"/>`);
  // Provisional hatch over every data lane from the first provisional hour.
  const p = provisionalStart(series);
  if (p !== null) {
    const px = r1(xEdge(p));
    out.push(`<rect class="mg-provisional" x="${px}" y="${lanes.score.top}" width="${r1(right - px)}" height="${lanes.tide.bottom - lanes.score.top}" fill="url(#${id}-hatch)"/>`);
    out.push(`<text class="mg-foot" x="${r1(px + 3)}" y="${lanes.foot.bottom - 2}">Outlook →</text>`);
  }
  // Now marker (continuous time, not snapped to an hour).
  if (finite(now) && n) {
    const pos = (now - series.times[0]) / HOUR;
    if (pos >= 0 && pos <= n) {
      const nx = r1(left + (pos + 0.5) * L.step);
      out.push(`<path class="mg-now" d="M${nx},${lanes.score.top}V${lanes.tide.bottom}"/><text class="mg-foot mg-now-label" x="${nx}" y="${lanes.foot.bottom - 2}" text-anchor="${pos < 8 ? "start" : "middle"}">Now</text>`);
    }
  }
  // Selected-hour cursor. The transparent rect is the 44 px touch target.
  const cx = r1(x(Math.max(0, Math.min(n - 1, selected))));
  out.push(`<g class="mg-cursor" transform="translate(${cx},0)"><rect class="mg-hit" x="-22" y="0" width="44" height="${L.height}"/><path class="mg-cursor-line" d="M0,${lanes.score.top - 2}V${lanes.tide.bottom + 2}"/><path class="mg-cursor-knob" d="M-5,${lanes.score.top - 3}h10l-5,6z"/></g>`);
  out.push("</svg>");
  return out.join("");
}

/** Pixel x -> hour index for a rendered layout (clamped). */
export function indexAt(px, width, n = 169) {
  const L = layout(width, n);
  return Math.max(0, Math.min(n - 1, Math.floor((px - L.left) / L.step)));
}
