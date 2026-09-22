import { getRegion } from "./region.js?v=8.9";
import {
  POINTS,
  MODELS,
  HOUR,
  readConditions,
  tideAt,
  distanceNm,
  angleBetween,
} from "./marine-data.js?v=8.9";
import {
  esc,
  num,
  local,
  full,
  day,
  from,
  weatherName,
  lineChart,
  waveSketch,
  rose,
} from "./marine-charts.js?v=8.9";

export function detailHTML({
  bundle,
  hours,
  index,
  point,
  family,
  requested,
  c,
  other,
  status,
  sourcesOpen,
  heading,
}) {
  const t = hours[index],
    p = POINTS[point],
    provisional = index >= 72;
  const begin = Math.max(
      hours[0],
      Math.min(t - 6 * HOUR, hours.at(-1) - 24 * HOUR),
    ),
    end = begin + 24 * HOUR;
  const interval = hours.filter((h) => h >= begin && h <= end);
  const conditions = interval.map((time) => ({
    time,
    c: readConditions(bundle, point, time, family),
  }));
  const tide = bundle.tides
    .filter((x) => x.time >= begin && x.time <= end)
    .map((x) => ({ time: x.time, value: x.height }));
  const extreme = bundle.extremes.filter(
    (x) => x.time >= begin && x.time <= end,
  );
  const water = bundle.water,
    waterEpoch = water
      ? Date.parse(water.t.replace(" ", "T") + "Z") / 1000
      : null;
  const waterFresh =
    Number.isFinite(waterEpoch) &&
    Date.now() / 1000 - waterEpoch <= 7200 &&
    Date.now() / 1000 >= waterEpoch;
  const waveId = family === "gfs" ? "ncep_gfswave025" : "ecmwf_wam025",
    waveGrid = bundle.models[waveId]?.data?.[point];
  const short = c.chop.period > 0 && c.chop.period <= 6 && c.chop.height >= 1;
  const crossed =
    c.secondary.height >= 1 &&
    angleBetween(c.swell.from, c.secondary.from) >= 60;
  return `${requested ? `<p class="small">Selected ${esc(requested.label || "map location")}: nearest requested forecast sample is ${num(distanceNm(requested, p))} nm away. Values are regional, not reef-scale.</p>` : ""}
    <div class="conditions-hero"><div><span class="eyebrow">COMBINED SIGNIFICANT SEAS</span><strong class="sea-number">${num(c.sea.height)}<small> ft</small></strong><span>${num(c.sea.period)} s ${family === "gfs" ? "primary-wave" : "mean"} period · from ${from(c.sea.from)}</span></div><div class="hero-wind"><span>${weatherName(c.weatherCode)}</span><strong>${num(c.wind, 0)}<small> kt wind</small></strong><span>Gust ${num(c.gust, 0)} kt · from ${from(c.windFrom)}</span><details class="weather-extra" data-disclosure="air"><summary>Air, visibility &amp; rain</summary><span>${num(c.air, 0)}°F air · ${c.visibility === null ? "Visibility unavailable" : `${num(c.visibility / 1609.344)} mi visibility`}</span><span>${num(c.rain)} mm precipitation</span></details></div></div>
    <details class="comfort-explainer ${status.level}"><summary>${status.label}${provisional ? " · provisional" : ""} · why</summary><p>${status.flags.map(esc).join(". ")}.</p><p class="small">Preferred screen: wind ≤8 kt, gusts ≤12 kt, combined seas ≤3 ft, chop ≤1 ft. Wind, gust, and combined-height thresholds use the rougher of both models. It is not a 9/10 trip rating or a harbor clearance. ${p.offshore ? "Check the coastal entrance and every offshore return hour." : "Tide height alone cannot determine bar safety or slack current."}</p></details>
    <div data-condition-panel="waves"><div class="ocean-detail-grid"><section class="marine-card wave-card"><div class="eyebrow">UNDERSTAND THE MOTION</div><h3>What makes up the sea</h3>${family === "ecmwf" ? '<p class="small">This ECMWF feed provides combined seas. Select NOAA GFS above for available swell and chop components.</p>' : ""}${waveSketch(c.swell, "Primary swell", "#198f9e")}${waveSketch(c.secondary, "Secondary swell", "#ad5c85")}${waveSketch(c.chop, "Wind chop", "#cb883e")}<details data-disclosure="wave-guide"><summary>How to read the wave diagram</summary><p class="small">Schematic: height changes amplitude; period changes spacing. Period is seconds per cycle, not a countdown for individual waves. ${short ? "Short chop may make the ride sharp. " : ""}${crossed ? "Crossing swell directions may increase roll. " : ""}Combined significant height is not the sum of component heights; larger individual waves occur. GFS supplies a primary-wave period and direction; ECMWF supplies mean values, so those headline periods are not like-for-like.</p></details></section><details class="marine-card direction-card" data-disclosure="direction"><summary>Wave direction &amp; boat heading</summary>${rose(c)}<label>Boat heading (true)<input id="boat-heading" type="number" min="0" max="359" step="1" value="${Number.isFinite(heading) ? heading : ""}" inputmode="numeric"/></label><p id="encounter-note" class="small"></p><p class="small">Arrows travel toward; source directions are FROM. Actual encounter frequency also depends on speed, depth, and wave length. This is not a vessel-motion simulation.</p></details></div>
    </div><div data-condition-panel="wind" hidden><section class="marine-card"><div class="section-title"><div><div class="eyebrow">24-HOUR CONTEXT · ${day(begin)}</div><h3>Wind &amp; sea trend</h3></div><span>${family === "gfs" ? "NOAA GFS" : "ECMWF"}</span></div><div class="trend-label">Combined seas (ft)</div>${lineChart(
      conditions.map((x) => ({ time: x.time, value: x.c.sea.height })),
      { label: "Combined significant seas", selected: t, unit: "ft" },
    )}<div class="trend-label">Wind (kt) · gusts listed in the hourly table</div>${lineChart(
      conditions.map((x) => ({ time: x.time, value: x.c.wind })),
      { label: "Sustained wind", color: "#315887", selected: t, unit: "kt" },
    )}<details><summary>Read hourly values</summary><div class="forecast-table-wrap"><table><thead><tr><th>Pacific</th><th>Wind / gust kt</th><th>Seas ft @ s</th><th>Chop ft @ s</th></tr></thead><tbody>${conditions.map(({ time, c }) => `<tr ${time === t ? 'class="current-hour"' : ""}><th>${local(time, { weekday: "short", hour: "numeric" })}</th><td>${num(c.wind)} / ${num(c.gust)}</td><td>${num(c.sea.height)} @ ${num(c.sea.period)}</td><td>${num(c.chop.height)} @ ${num(c.chop.period)}</td></tr>`).join("")}</tbody></table></div></details></section>
    </div><div data-condition-panel="tides" hidden><section class="marine-card tide-card"><div class="section-title"><div><div class="eyebrow">NOAA · ${esc((bundle.stations||getRegion().stations).tide_name)} ${esc((bundle.stations||getRegion().stations).tide)}</div><h3>Tides</h3></div><strong>${num(tideAt(bundle.tides, t))} ft <small>MLLW</small></strong></div>${lineChart(tide, { label: (bundle.stations||getRegion().stations).tide_name + " predicted tide", color: "#775eab", selected: t, unit: "ft", min: 0 })}<div class="tide-extremes">${extreme.map((x) => `<span><strong>${x.type === "H" ? "High" : "Low"} ${num(x.height)} ft</strong>${local(x.time, { weekday: "short", hour: "numeric", minute: "2-digit" })}</span>`).join("")}</div><p class="small">Astronomical tide prediction. ${esc((bundle.stations||getRegion().stations).tide_note)} High/low water does not establish slack current.</p><p class="observation">${waterFresh ? `Latest observed water level: <strong>${num(Number(water.v))} ft MLLW</strong> · ${full(waterEpoch)} (NOAA preliminary). This observation stays at its recorded time as you scrub.` : "Latest water-level observation unavailable or older than two hours; predicted tide remains separate."}</p><a href="https://tidesandcurrents.noaa.gov/noaatidepredictions.html?id=${(bundle.stations||getRegion().stations).tide}" target="_blank" rel="noopener">NOAA tide station ↗</a></section>
    </div><div data-condition-panel="sources" hidden><div class="ocean-detail-grid"><section class="marine-card"><div class="eyebrow">INDEPENDENT MODEL CHECK</div><h3>${family === "gfs" ? "ECMWF comparison" : "NOAA GFS comparison"}</h3><p><strong>${num(other.wind)} / ${num(other.gust)} kt</strong> wind / gust<br><strong>${num(other.sea.height)} ft @ ${num(other.sea.period)} s</strong> combined seas<br>Chop ${num(other.chop.height)} ft @ ${num(other.chop.period)} s</p><p class="small">${family === "gfs" ? "ECMWF headline period is a mean; GFS is primary-wave period." : "GFS headline period is primary-wave; ECMWF is a mean."} Same requested location and hour; each model uses its own grid. Disagreement is uncertainty, not a reason to select the calmer model.</p></section><section class="marine-card"><div class="eyebrow">OCEAN CONTEXT</div><h3>Temperature &amp; surface current</h3><p><strong>${num(c.sst)}°F</strong> sea surface<br><strong>${num(c.current)} kt</strong> surface current toward ${from(c.currentTo)}</p><p class="small">Météo-France / Copernicus · about 8 km. Modeled surface temperature is not bottom temperature or satellite SST. Surface current is not bottom drift or a usable harbor-current prediction.</p></section></div>
    <section class="marine-card"><h3>Before you go</h3><p>Inspect the full trip, including the return. A pleasant hour at a fishing spot does not establish a comfortable passage or safe entrance.</p><div class="forecast-links"><a href="https://forecast.weather.gov/MapClick.php?TextType=2&zoneid=${(bundle.marine_zones||getRegion().marine_zones).coastal}" target="_blank" rel="noopener">NWS coastal forecast ↗</a><a href="https://forecast.weather.gov/MapClick.php?TextType=2&zoneid=${(bundle.marine_zones||getRegion().marine_zones).offshore}" target="_blank" rel="noopener">NWS offshore forecast ↗</a><a href="https://www.ndbc.noaa.gov/station_page.php?station=${(bundle.stations||getRegion().stations).nearshore_buoy}" target="_blank" rel="noopener">${esc((bundle.stations||getRegion().stations).nearshore_buoy_name)} reference buoy ↗</a><a href="${getRegion().harbor.information_url}" target="_blank" rel="noopener">${esc(getRegion().harbor.name)} Harbor ↗</a><a href="https://wildlife.ca.gov/Fishing/Ocean/Regulations/Fishing-Map/Central" target="_blank" rel="noopener">Current fishing rules ↗</a></div><p class="small">Daily buoy samples appear in the recent fishing-evidence panel. Live entrance conditions are not loaded here. Active-alert checks do not cover unissued warnings later in the forecast.</p></section>
    <details id="marine-sources" class="marine-card" ${sourcesOpen ? "open" : ""}><summary>Model runs, grid coordinates &amp; coverage</summary><p>Retrieved ${full(bundle.retrieved / 1000)}. Retrieval is not model initialization. Hourly values may interpolate a provider’s coarser output; absent values stay blank.</p>${MODELS.map(
      (m) => {
        const source = bundle.models[m.id],
          d = source?.data?.[point],
          meta = source?.meta;
        const times = d?.hourly?.time || [];
        return `<div class="model-source"><h4>${m.name} · ${m.resolution}</h4><p>Run initialized ${full(meta?.last_run_initialisation_time)}<br>Available ${full(meta?.last_run_availability_time)}<br>Published end ${full(meta?.data_end_time)}<br>Returned grid ${num(d?.latitude, 4)}, ${num(d?.longitude, 4)}<br>Returned time axis ${full(times[0])} – ${full(times.at(-1))}; individual fields may end sooner.</p>${source?.error ? `<p class="error">Forecast unavailable: ${esc(source.error)}</p>` : ""}<a href="${m.meta}" target="_blank" rel="noopener">Provider run metadata ↗</a></div>`;
      },
    ).join(
      "",
    )}<p>Wave sample is ${waveGrid ? num(distanceNm(p, waveGrid)) : "—"} nm from the requested coordinate. Colored circles show regional samples, not reef-scale predictions or a continuous analysis. Coastline shelter and the entrance are unresolved.</p><p><a href="https://open-meteo.com/en/docs/marine-weather-api" target="_blank" rel="noopener">Forecast data via Open-Meteo</a> · ECMWF, NOAA, Météo-France / Copernicus · <a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noopener">CC BY 4.0</a>. SkipperCast converts units, draws charts, and applies a disclosed comfort screen. NOAA supplies tide predictions and observations.</p></details></div>`;
}
