import { getRegion, acceptsFeed, localContext, assetURL } from "./region.js?v=8.12";
import { fetchJSON, compass } from "./forecast.js?v=8.12";
import { esc, num, local, from } from "./marine-charts.js?v=8.12";

export const OBSERVATION_REFRESH = 5 * 60 * 1000;
export const FORECAST_REFRESH = 30 * 60 * 1000;
const FEED = getRegion().conditions_feed;
const AIRPORT = `https://api.weather.gov/stations/${getRegion().stations.airport}/observations/latest`;
const WATER = `https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?product=water_level&application=SkipperCast&station=${getRegion().stations.tide}&date=latest&datum=MLLW&time_zone=gmt&units=english&format=json`;
const STATION = "https://www.ndbc.noaa.gov/station_page.php?station=";
const finite = (n) => typeof n === "number" && Number.isFinite(n);
const time = (value) => typeof value === "string" && /(?:Z|[+-]\d\d:\d\d)$/.test(value) ? Date.parse(value) : NaN;
const measuredAt = (epoch) => Number.isFinite(epoch) ? local(epoch / 1000, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) + " PT" : "Time unavailable";
const sourceCurrent = (feed, source, now) => {
  const age = (now - time(feed?.generated_at)) / 60000;
  return source?.status === "ok" && age >= -5 && age <= 90;
};

export function freshness(epoch, now = Date.now(), sourceOK = true) {
  if (!Number.isFinite(epoch)) return { fresh: false, label: "Unavailable" };
  const age = (now - epoch) / 60000;
  if (age < -5) return { fresh: false, label: "Check source time" };
  if (age > 120) return { fresh: false, label: "Stale" };
  if (!sourceOK) return { fresh: false, label: "Update unavailable" };
  return { fresh: true, label: Math.max(0, Math.round(age)) + " min ago" };
}

export function buoyReading(feed, id = "diablo", now = Date.now()) {
  const source = feed?.schema_version === 1 ? feed.sources?.[id] : null;
  const data = source?.data, units = data?.units || {};
  const rows = Array.isArray(data?.observations) ? data.observations.slice().sort((a, b) => time(b.time) - time(a.time)) : [];
  const value = (row, key, unit, factor = 1) => units[key] === unit && finite(row?.[key]) && row[key] >= 0 ? row[key] * factor : null;
  const wave = rows.find((r) => value(r, "WVHT", "m") !== null),
    wind = rows.find((r) => value(r, "WSPD", "m/s") !== null),
    waveTime = time(wave?.time), windTime = time(wind?.time);
  const ok = sourceCurrent(feed, source, now);
  const direction = (row, key) => {
    const n = value(row, key, "degT");
    return n !== null && n <= 360 ? n : null;
  };
  return {
    height: value(wave, "WVHT", "m", 3.28084),
    period: value(wave, "DPD", "sec"), from: direction(wave, "MWD"), waveTime,
    waveState: freshness(waveTime, now, ok),
    wind: value(wind, "WSPD", "m/s", 1.943844),
    gust: value(wind, "GST", "m/s", 1.943844), windFrom: direction(wind, "WDIR"), windTime,
    windState: freshness(windTime, now, ok),
    issue: source?.issue || (!ok ? "Buoy refresh is unavailable or delayed." : null),
  };
}

export function airportReading(response, now = Date.now()) {
  const p = response?.properties || {}, epoch = time(p.timestamp);
  const val = (key, unit, factor = 1, offset = 0) => {
    const q = p[key];
    return q?.unitCode === unit && finite(q.value) && !["X", "Z"].includes(q.qualityControl) ? q.value * factor + offset : null;
  };
  const wind = val("windSpeed", "wmoUnit:km_h-1", 1 / 1.852),
    gust = val("windGust", "wmoUnit:km_h-1", 1 / 1.852),
    direction = val("windDirection", "wmoUnit:degree_(angle)"),
    visibility = val("visibility", "wmoUnit:m", 1 / 1609.344);
  return { epoch, state: freshness(epoch, now), description: p.textDescription || "Weather unavailable",
    air: val("temperature", "wmoUnit:degC", 1.8, 32),
    wind: wind !== null && wind >= 0 ? wind : null,
    gust: gust !== null && gust >= 0 ? gust : null,
    from: direction !== null && direction >= 0 && direction <= 360 ? direction : null,
    visibility: visibility !== null && visibility >= 0 ? visibility : null };
}

export function parseLiveAlerts(response) {
  if (response?.type !== "FeatureCollection" || !Array.isArray(response.features)) return null;
  if (response.features.some((f) => !f?.properties)) return null;
  return response.features.map((f) => ({
    title: f.properties?.headline || f.properties?.event || "Marine alert",
    starts: time(f.properties?.onset || f.properties?.effective) / 1000,
    ends: time(f.properties?.ends || f.properties?.expires) / 1000,
    url: f.id,
  }));
}

export async function loadObservations(fetcher = fetchJSON, now = Date.now(), context = localContext()) {
  const stations=context.stations, zones=context.marine_zones;
  const AIRPORT=`https://api.weather.gov/stations/${stations.airport}/observations/latest`;
  const WATER=`https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?product=water_level&application=SkipperCast&station=${stations.tide}&date=latest&datum=MLLW&time_zone=gmt&units=english&format=json`;
  async function get(url) {
    try { return { value: await fetcher(url) }; }
    catch (error) { return { error: error.name === "AbortError" ? "Request timed out" : error.message }; }
  }
  const [buoys, airport, water, coastal, offshore] = await Promise.all([
    get(FEED + "?refresh=" + Math.floor(now / OBSERVATION_REFRESH)), get(AIRPORT), get(WATER),
    get(`https://api.weather.gov/alerts/active?zone=${zones.coastal}`),
    get(`https://api.weather.gov/alerts/active?zone=${zones.offshore}`),
  ]);
  if(!buoys.value && assetURL('observations')) {
    const saved=await get(assetURL('observations'));
    if(saved.value && acceptsFeed(saved.value)){buoys.value=saved.value;buoys.error='Using the dated packaged observation snapshot; live refresh unavailable.';}
  }
  if (buoys.value && !acceptsFeed(buoys.value)) { buoys.value=undefined;buoys.error="Observation feed belongs to another region"; }
  if(buoys.value && context.id!=='default') {
    const sources=buoys.value.sources||{};
    buoys.value={...buoys.value,sources:{...sources,diablo:sources['buoy-'+stations.nearshore_buoy],'diablo-spectrum':sources['buoy-'+stations.nearshore_buoy+'-spectrum'],offshore:sources['buoy-'+stations.offshore_buoy]}};
  }
  return { stations, zones, context_id:context.id, buoys: buoys.value, buoyError: buoys.error,
    airport: airport.value, airportError: airport.error,
    water: water.value?.data?.[0], waterError: water.error,
    alerts: { coastal: parseLiveAlerts(coastal.value), offshore: parseLiveAlerts(offshore.value) },
    alertError: coastal.error || offshore.error, retrieved: Date.now() };
}

function stamp(epoch, state) {
  return `<span class="observation-age ${state.fresh ? "fresh" : "stale"}">${esc(state.label)}</span><span class="small">Observed ${measuredAt(epoch)}</span>`;
}
function spectrumHTML(feed, now) {
  const s = feed?.sources?.["diablo-spectrum"], d = s?.data, r = d?.observations?.[0], u = d?.units || {};
  const epoch = time(r?.time), state = freshness(epoch, now, sourceCurrent(feed, s, now));
  const field = (key, unit, factor = 1) => u[key] === unit && finite(r?.[key]) && r[key] >= 0 ? num(r[key] * factor) : "—";
  return `<details class="observed-components" data-live-disclosure="components"><summary>Measured swell &amp; wind waves</summary><p>Swell ${field("SwH", "m", 3.28084)} ft · ${field("SwP", "sec")} s · from ${esc(r?.SwD || "—")}</p><p>Wind waves ${field("WWH", "m", 3.28084)} ft · ${field("WWP", "sec")} s · from ${esc(r?.WWD || "—")}</p>${stamp(epoch, state)}<p class="small">NOAA’s spectral separation; components do not add directly to total wave height.</p></details>`;
}

export function observedDock(observations, offshore = false, now = Date.now()) {
  const stations=observations?.stations||getRegion().stations;
  const r = buoyReading(observations?.buoys, offshore ? "offshore" : "diablo", now);
  if (!r.waveState.fresh || r.height === null) return null;
  return `<strong>Observed · ${num(r.height)} ft <span>@ ${num(r.period)} s</span></strong><span>${offshore ? stations.offshore_buoy_name + " reference" : stations.nearshore_buoy_name + " buoy reference"} · ${local(r.waveTime / 1000, { hour: "numeric", minute: "2-digit" })} PT</span>`;
}

export function observationsHTML(data, offshore = false, now = Date.now()) {
  if (!data) return '<p class="live-loading" role="status">Loading current NOAA observations…</p>';
  const stations=data.stations||getRegion().stations, zones=data.zones||getRegion().marine_zones;
  const AIRPORT=`https://api.weather.gov/stations/${stations.airport}/observations/latest`;
  const seas = buoyReading(data.buoys, offshore ? "offshore" : "diablo", now),
    outer = buoyReading(data.buoys, "offshore", now), air = airportReading(data.airport, now),
    water = data.water, waterTime = water?.t ? time(water.t.replace(" ", "T") + "Z") : NaN,
    height = typeof water?.v === "string" && water.v.trim() !== "" ? Number(water.v) : NaN,
    waterState = freshness(Number.isFinite(height) ? waterTime : NaN, now, !data.waterError),
    alerts = data.alerts?.[offshore ? "offshore" : "coastal"],
    active = alerts?.filter((a) => (!Number.isFinite(a.starts) || a.starts <= now / 1000) && (!Number.isFinite(a.ends) || a.ends >= now / 1000)),
    alertFresh = now - data.retrieved <= 10 * 60000;
  const alertHTML = !alertFresh || !Array.isArray(alerts)
    ? '<p class="live-alert">Current marine advisories could not be confirmed. Check the official forecast.</p>'
    : active.length ? `<div class="live-alert" role="status"><strong>Active marine alert</strong>${active.map((a) => `<p>${esc(a.title)}</p>`).join("")}</div>` : "";
  return `<div class="live-check"><span>Latest measurements</span><span>Checked ${local(data.retrieved / 1000, { hour: "numeric", minute: "2-digit" })} PT</span></div>${alertHTML}
    <div class="live-cards"><section class="live-card"><div class="live-card-title"><h3>${offshore ? stations.offshore_buoy_name + " · " + stations.offshore_buoy : stations.nearshore_buoy_name + " · " + stations.nearshore_buoy}</h3><a href="${STATION}${offshore ? stations.offshore_buoy : stations.nearshore_buoy}" target="_blank" rel="noopener">NOAA ↗</a></div><strong class="observed-number">${num(seas.height)}<small> ft</small></strong><p>${num(seas.period)} s dominant period · from ${from(seas.from)}</p><div class="observation-stamp">${stamp(seas.waveTime, seas.waveState)}</div>${!seas.waveState.fresh ? `<p class="small">${esc(data.buoyError || seas.issue || "No recent wave reading available.")}</p>` : ""}${offshore ? `<p class="small">${esc(stations.offshore_buoy_note || "Regional offshore reference; see station position.")}</p>` : spectrumHTML(data.buoys, now)}</section>
    <section class="live-card"><div class="live-card-title"><h3>Reference weather · ${esc(stations.airport_name)}</h3><a href="${AIRPORT}" target="_blank" rel="noopener">NWS ↗</a></div><strong class="observed-number">${num(air.air, 0)}<small> °F</small></strong><p>${esc(air.description)} · ${num(air.visibility)} mi visibility</p><p>Wind ${num(air.wind, 0)} kt from ${compass(air.from)}${air.gust === null ? " · gust not reported" : ` · gust ${num(air.gust, 0)} kt`}</p><div class="observation-stamp">${stamp(air.epoch, air.state)}</div><p class="small">${esc(stations.airport)} airport is on land. Wind and fog can differ at sea and at the entrance.</p></section>
    <section class="live-card water-observation"><div class="live-card-title"><h3>${esc(stations.tide_name)} reference level</h3><a href="https://tidesandcurrents.noaa.gov/stationhome.html?id=${stations.tide}" target="_blank" rel="noopener">NOAA ↗</a></div><strong class="observed-number">${Number.isFinite(height) ? num(height) : "—"}<small> ft MLLW</small></strong><div class="observation-stamp">${stamp(waterTime, waterState)}</div><p class="small">Measured water level. ${esc(stations.tide_note)}</p></section></div>
    <details class="live-more" data-live-disclosure="sources"><summary>Offshore wind &amp; source details</summary><p>Buoy ${esc(stations.offshore_buoy)} · wind ${num(outer.wind)} kt, gust ${num(outer.gust)} kt from ${compass(outer.windFrom)}.</p><div class="observation-stamp">${stamp(outer.windTime, outer.windState)}</div><p class="small">${esc(stations.offshore_buoy_note || "Regional offshore reference; not harbor wind.")} Buoys update through a cloud job scheduled every 30 minutes; NOAA and scheduler delays are possible. This page checks for new observations and marine alerts every 5 minutes while open. Readings over 2 hours old are marked stale.</p><p class="small">${alertFresh && Array.isArray(alerts) && !active.length ? "No active issued marine alerts returned for " + (offshore ? zones.offshore : zones.coastal) + ". " : ""}Observations do not confirm a future forecast or entrance safety.</p><a href="https://forecast.weather.gov/MapClick.php?TextType=2&amp;zoneid=${offshore ? zones.offshore : zones.coastal}" target="_blank" rel="noopener">Official marine forecast ↗</a> · <a href="https://github.com/Grahammmm/skippercast/actions/workflows/live-conditions.yml" target="_blank" rel="noopener">Buoy feed status ↗</a></details>`;
}
