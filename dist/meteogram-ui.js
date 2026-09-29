// Mounts the meteogram at the top of the Conditions view. It follows the
// forecast the app already loaded (the "skippercast:forecast" event from
// weather-ui.js) and selects hours through the existing #detail-hour range
// input, so the scrubber, day strip, map and this graph share one hour.
//
// Loaded as its own module script. Nothing region-dependent is imported until
// the first forecast event, which only fires after boot.js has set the region.
import { renderMeteogram } from "./meteogram.js";

const HOUR = 3600;

export function initMeteogram(root = document.getElementById("meteogram")) {
  if (!root) return null;
  let key = "", series = null;
  const hourInput = () => document.getElementById("detail-hour");
  const select = (i) => {
    const input = hourInput();
    if (!input) return;
    input.value = String(i);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  };
  let deps = null, pending = null;
  const update = (detail) => {
    const { buildSeries, getRegion } = deps;
    const { bundle, time, family, point, species } = detail;
    // weather-ui's timeline starts at hours[0] = time - index hours.
    const index = Math.max(0, Math.min(168, Number(hourInput()?.value) || 0));
    const start = time - index * HOUR, now = Date.now();
    const next = `${getRegion().id}:${bundle.retrieved}:${point}:${species}:${family}:${start}:${Math.floor(now / 600000)}`;
    if (next !== key) { series = buildSeries(bundle, point, species, family, start, now); key = next; }
    renderMeteogram(root, series, { selected: index, now: now / 1000, timeZone: getRegion().timezone, onSelect: select });
  };
  document.addEventListener("skippercast:forecast", (event) => {
    const detail = event.detail || {};
    if (!detail.bundle || !Number.isFinite(detail.time)) return;
    if (deps) return update(detail);
    const first = !pending;
    pending = detail;
    if (!first) return;
    Promise.all([import("./meteogram-series.js"), import("./region.js")])
      .then(([series, region]) => { deps = { buildSeries: series.buildSeries, getRegion: region.getRegion }; update(pending); })
      .catch((error) => { console.warn("Forecast graph unavailable", error); root.textContent = "Forecast graph unavailable."; });
  });
  return root;
}

initMeteogram();
