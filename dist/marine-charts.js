import { getRegion } from "./region.js?v=8.11";
import { directionTo, HOUR } from "./marine-data.js?v=8.11";
import { compass } from "./forecast.js?v=8.11";
export const esc = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
export const num = (n, d = 1) => (Number.isFinite(n) ? n.toFixed(d) : "—");
export const local = (t, opts = {}) =>
  new Intl.DateTimeFormat("en-US", {
    timeZone: getRegion().timezone,
    ...opts,
  }).format(new Date(t * 1000));
export const full = (t) =>
  Number.isFinite(t)
    ? local(t, {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
        timeZoneName: "short",
      })
    : "unavailable";
export const day = (t) =>
  local(t, { weekday: "short", month: "short", day: "numeric" });
export const from = (d) =>
  Number.isFinite(d) ? `${compass(d)} ${Math.round(d)}°` : "unavailable";
export const weatherName = (code) =>
  code === null
    ? "Weather unavailable"
    : code === 0
      ? "Clear"
      : code <= 3
        ? "Partly cloudy / cloudy"
        : [45, 48].includes(code)
          ? "Fog signal"
          : code >= 95
            ? "Thunderstorm signal"
            : code >= 51
              ? "Precipitation signal"
              : "Weather unavailable";

export function lineChart(
  series,
  { label, color = "#198f9e", height = 140, min = 0, max, selected, unit = "" },
) {
  const valid = series.filter((p) => Number.isFinite(p.value));
  if (!valid.length)
    return `<p class="unavailable">${label} unavailable for this interval.</p>`;
  const start = series[0].time,
    end = series.at(-1).time;
  const bottom = Math.min(min, ...valid.map((p) => p.value)),
    top = max ?? Math.max(bottom + 1, ...valid.map((p) => p.value));
  const x = (t) => 42 + ((t - start) / (end - start || 1)) * 560,
    y = (v) =>
      height - 24 - ((v - bottom) / (top - bottom || 1)) * (height - 40);
  let pen = false,
    path = "";
  for (const p of series) {
    if (!Number.isFinite(p.value)) {
      pen = false;
      continue;
    }
    path += `${pen ? "L" : "M"}${x(p.time).toFixed(1)},${y(p.value).toFixed(1)} `;
    pen = true;
  }
  const ticks = [bottom, (bottom + top) / 2, top];
  return `<svg class="data-chart" viewBox="0 0 620 ${height}" role="img" aria-label="${esc(label)}. ${num(Math.min(...valid.map((p) => p.value)))} to ${num(Math.max(...valid.map((p) => p.value)))} ${unit}. Gaps are unavailable data.">${ticks.map((v) => `<path d="M42 ${y(v)}H602" stroke="#dce6e8"/><text x="35" y="${y(v) + 4}" text-anchor="end">${num(v)}</text>`).join("")}<path d="${path}" fill="none" stroke="${color}" stroke-width="2.5"/>${selected >= start && selected <= end ? `<path d="M${x(selected)} 10V${height - 24}" stroke="#123a49" stroke-dasharray="3 4"/>` : ""}${[
    0, 6, 12, 18, 24,
  ]
    .filter((h) => start + h * HOUR <= end)
    .map(
      (h) =>
        `<text x="${x(start + h * HOUR)}" y="${height - 5}" text-anchor="middle">${local(start + h * HOUR, { hour: "numeric" })}</text>`,
    )
    .join("")}</svg>`;
}
export function waveSketch(part, label, color) {
  if (
    !Number.isFinite(part.height) ||
    !Number.isFinite(part.period) ||
    part.period <= 0
  )
    return `<div class="wave-row"><strong>${label}</strong><span>Component unavailable / no resolved period</span></div>`;
  const amp = Math.max(1, Math.min(part.height * 6, 28)),
    wavelength = Math.max(24, part.period * 8),
    points = [];
  for (let x = 0; x <= 360; x += 2)
    points.push(`${x},${32 - amp * Math.sin((x / wavelength) * 2 * Math.PI)}`);
  return `<div class="wave-row"><div><strong>${label}</strong><span>${num(part.height)} ft · ${num(part.period)} s · from ${from(part.from)}</span></div><svg viewBox="0 0 360 65" role="img" aria-label="${label}: ${num(part.height)} feet, period ${num(part.period)} seconds"><path d="M0 32H360" stroke="#dce6e8"/><polyline points="${points.join(" ")}" fill="none" stroke="${color}" stroke-width="2.5"/></svg><small>${num(60 / part.period)} wave cycles / minute at this period</small></div>`;
}
export function rose(c) {
  const parts = [
    ["Wind", c.windFrom, "#315887"],
    ["Primary", c.swell.from, "#198f9e"],
    ["Secondary", c.secondary.from, "#ad5c85"],
    ["Chop", c.chop.from, "#cb883e"],
  ];
  return `<svg class="direction-rose" viewBox="0 0 180 180" role="img" aria-label="Direction compass. Arrows point toward travel; the labels state where waves and wind come from."><circle cx="90" cy="90" r="62" fill="#f1f6f6" stroke="#d6e2e5"/><path d="M90 22V158M22 90H158" stroke="#d6e2e5"/><text x="90" y="17" text-anchor="middle">N</text><text x="90" y="176" text-anchor="middle">S</text><text x="10" y="94">W</text><text x="163" y="94">E</text>${parts.map(([name, d, color], i) => (Number.isFinite(d) ? `<g transform="rotate(${directionTo(d)} 90 90)" stroke="${color}" stroke-width="${i === 0 ? 2 : 3}" fill="${color}"><path d="M${85 + i * 3} 125V${47 + i * 5}"/><path d="m${85 + i * 3} ${44 + i * 5} -4 8h8z"/></g>` : "")).join("")}</svg><div class="rose-legend">${parts.map(([name, d, color]) => `<span><i style="background:${color}"></i>${name} from ${from(d)}</span>`).join("")}</div>`;
}
