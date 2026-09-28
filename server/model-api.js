// SkipperCast model API: answers Open-Meteo-style forecast and marine queries
// from SkipperCast's own NOAA/ECMWF tiles (built by skippercast.forecast.build).
// One implementation serves the Worker (/api/om/...) and the Python pipeline
// (through scripts/model_api.mjs), so both always agree.
//
// What it emulates from Open-Meteo:
//  - point sampling: bilinear interpolation between the four surrounding grid
//    cells, restricted to sea cells for marine/`cell_selection=sea` queries
//    (nearest sea cell when none of the four is sea)
//  - hourly output: monotone cubic (Fritsch-Carlson) interpolation between the
//    models' native steps, so 3-hourly and 6-hourly output is smooth without
//    overshoot; wind is interpolated as u/v components, directions as unit vectors
//  - precipitation as the amount in the preceding hour
//  - units, time zones, multi-point and multi-model responses, derived WMO weather codes

export const MODELS = {
  gfs_global: {kind: 'forecast', precipitation: 'rate'},
  ecmwf_ifs025: {kind: 'forecast', precipitation: 'backward'},
  ncep_gfswave016: {kind: 'marine'},
  ecmwf_wam: {kind: 'marine'},
};
const DEFAULT_MODELS = {forecast: ['gfs_global'], marine: ['ncep_gfswave016']};
const MISSING = -32768;
const HOUR = 3600;
const MARINE_VARS = ['wave', 'wind_wave', 'swell_wave', 'secondary_swell_wave'].flatMap(p =>
  ['height', 'period', 'direction'].map(q => `${p}_${q}`)).concat(['wave_peak_period']);
const FORECAST_VARS = ['wind_speed_10m', 'wind_direction_10m', 'wind_gusts_10m', 'visibility', 'precipitation',
  'temperature_2m', 'cloud_cover', 'weather_code'];

export class QueryError extends Error {}

// ---- tile decoding ---------------------------------------------------------------

const decoded = new WeakMap();
function base64Bytes(text) {
  if (typeof Buffer !== 'undefined') return new Uint8Array(Buffer.from(text, 'base64'));
  const raw = atob(text), bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
  return bytes;
}
function tileField(tile, name) {
  let cache = decoded.get(tile);
  if (!cache) decoded.set(tile, cache = {});
  if (!(name in cache)) {
    const field = tile.fields[name];
    if (!field) cache[name] = null;
    else {
      const bytes = base64Bytes(field.data);
      cache[name] = {values: new Int16Array(bytes.buffer, bytes.byteOffset, bytes.byteLength / 2), scale: field.scale};
    }
  }
  return cache[name];
}
function tileSea(tile) {
  let cache = decoded.get(tile);
  if (!cache) decoded.set(tile, cache = {});
  if (!cache.__sea) {
    const bits = base64Bytes(tile.sea), n = tile.nlat * tile.nlon, sea = new Uint8Array(n);
    for (let k = 0; k < n; k++) sea[k] = (bits[k >> 3] >> (7 - (k & 7))) & 1;
    cache.__sea = sea;
  }
  return cache.__sea;
}

// ---- spatial sampling -------------------------------------------------------------

// Weights over the four surrounding cells; `sea` restricts to sea cells and falls
// back to the nearest sea cell in the tile.
export function cellWeights(tile, latitude, longitude, seaOnly) {
  const y = (latitude - tile.lat0) / tile.dlat, x = (longitude - tile.lon0) / tile.dlon;
  const j0 = Math.max(0, Math.min(tile.nlat - 2, Math.floor(y))), i0 = Math.max(0, Math.min(tile.nlon - 2, Math.floor(x)));
  const fy = Math.max(0, Math.min(1, y - j0)), fx = Math.max(0, Math.min(1, x - i0));
  const sea = tileSea(tile);
  let cells = [[j0, i0, (1 - fy) * (1 - fx)], [j0, i0 + 1, (1 - fy) * fx], [j0 + 1, i0, fy * (1 - fx)], [j0 + 1, i0 + 1, fy * fx]];
  if (seaOnly) cells = cells.filter(([j, i]) => sea[j * tile.nlon + i]);
  if (!cells.length && seaOnly) {
    let best = null;
    for (let j = 0; j < tile.nlat; j++) for (let i = 0; i < tile.nlon; i++) {
      if (!sea[j * tile.nlon + i]) continue;
      const d = (j - y) ** 2 + (i - x) ** 2;
      if (!best || d < best[2]) best = [j, i, d];
    }
    if (best && best[2] <= 9) cells = [[best[0], best[1], 1]];
  }
  const total = cells.reduce((sum, c) => sum + c[2], 0);
  if (!cells.length) return null;
  cells = total > 0 ? cells.map(([j, i, w]) => [j, i, w / total]) : cells.map(([j, i]) => [j, i, 1 / cells.length]);
  const [nj, ni] = cells.reduce((a, c) => (c[2] > a[2] ? c : a), [0, 0, -1]);
  return {cells, grid: {latitude: round(tile.lat0 + nj * tile.dlat, 4), longitude: round(tile.lon0 + ni * tile.dlon, 4)}};
}

// Native-time series of one field at the weighted cells; per-time renormalized over
// cells with data. Direction fields average unit vectors.
function nativeSeries(tile, name, weights, direction = false) {
  const field = tileField(tile, name);
  const nt = tile.times.length, out = new Array(nt).fill(null);
  if (!field || !weights) return out;
  const plane = tile.nlat * tile.nlon;
  for (let t = 0; t < nt; t++) {
    let sum = 0, sx = 0, sy = 0, wsum = 0;
    for (const [j, i, w] of weights.cells) {
      const raw = field.values[t * plane + j * tile.nlon + i];
      if (raw === MISSING) continue;
      const v = raw * field.scale;
      if (direction) { sx += w * Math.sin(v * Math.PI / 180); sy += w * Math.cos(v * Math.PI / 180); }
      else sum += w * v;
      wsum += w;
    }
    if (wsum > 0) out[t] = direction ? (Math.atan2(sx, sy) * 180 / Math.PI + 360) % 360 : sum / wsum;
  }
  return out;
}

// ---- temporal interpolation -------------------------------------------------------

// Monotone cubic Hermite (Fritsch-Carlson) from native times to `targets`.
// Gaps (nulls) break the curve; hours outside the native range are null.
export function hermite(times, values, targets) {
  const n = times.length, slopes = new Array(n).fill(0), delta = new Array(n - 1).fill(null);
  for (let k = 0; k < n - 1; k++) {
    if (values[k] != null && values[k + 1] != null) delta[k] = (values[k + 1] - values[k]) / (times[k + 1] - times[k]);
  }
  for (let k = 0; k < n; k++) {
    const a = k > 0 ? delta[k - 1] : null, b = k < n - 1 ? delta[k] : null;
    if (a == null && b == null) slopes[k] = 0;
    else if (a == null) slopes[k] = b;
    else if (b == null) slopes[k] = a;
    else slopes[k] = a * b <= 0 ? 0 : (a + b) / 2;
  }
  for (let k = 0; k < n - 1; k++) {
    if (delta[k] == null) continue;
    if (delta[k] === 0) { slopes[k] = 0; slopes[k + 1] = 0; continue; }
    const a = slopes[k] / delta[k], b = slopes[k + 1] / delta[k], s = a * a + b * b;
    if (s > 9) { const tau = 3 / Math.sqrt(s); slopes[k] = tau * a * delta[k]; slopes[k + 1] = tau * b * delta[k]; }
  }
  let k = 0;
  return targets.map(t => {
    if (t < times[0] || t > times[n - 1]) return null;
    while (k < n - 2 && times[k + 1] < t) k++;
    while (k > 0 && times[k] > t) k--;
    if (t === times[k]) return values[k];
    if (t === times[k + 1]) return values[k + 1];
    if (values[k] == null || values[k + 1] == null) return null;
    const h = times[k + 1] - times[k], s = (t - times[k]) / h;
    const h00 = 2 * s ** 3 - 3 * s ** 2 + 1, h10 = s ** 3 - 2 * s ** 2 + s, h01 = -2 * s ** 3 + 3 * s ** 2, h11 = s ** 3 - s ** 2;
    return h00 * values[k] + h10 * h * slopes[k] + h01 * values[k + 1] + h11 * h * slopes[k + 1];
  });
}

// Mean rate over the preceding native interval applied to every hour in it.
function backward(times, values, targets) {
  return targets.map(t => {
    if (t < times[0] || t > times[times.length - 1]) return null;
    const k = times.findIndex(x => x >= t);
    return values[k];
  });
}

function directionSeries(times, values, targets) {
  const sx = hermite(times, values.map(v => (v == null ? null : Math.sin(v * Math.PI / 180))), targets);
  const sy = hermite(times, values.map(v => (v == null ? null : Math.cos(v * Math.PI / 180))), targets);
  return sx.map((x, i) => (x == null || sy[i] == null ? null : (Math.atan2(x, sy[i]) * 180 / Math.PI + 360) % 360));
}

// ---- time axis and units ----------------------------------------------------------

function offsetSeconds(zone, epoch) {
  if (zone === 'UTC' || zone === 'GMT') return 0;
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-US', {timeZone: zone, hourCycle: 'h23', year: 'numeric',
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit'})
    .formatToParts(new Date(epoch * 1000)).map(p => [p.type, p.value]));
  const asUTC = Date.UTC(+parts.year, +parts.month - 1, +parts.day, +parts.hour % 24, +parts.minute, +parts.second) / 1000;
  return Math.round((asUTC - epoch) / 60) * 60;
}
function localMidnight(zone, now) {
  const offset = offsetSeconds(zone, now);
  const local = now + offset, midnight = local - (((local % 86400) + 86400) % 86400);
  return midnight - offsetSeconds(zone, midnight - offset);
}
function isoLocal(epoch, zone) {
  return new Date((epoch + offsetSeconds(zone, epoch)) * 1000).toISOString().slice(0, 16);
}
function zoneAbbreviation(zone, epoch) {
  if (zone === 'UTC' || zone === 'GMT') return zone;
  const part = new Intl.DateTimeFormat('en-US', {timeZone: zone, timeZoneName: 'short'}).formatToParts(new Date(epoch * 1000))
    .find(p => p.type === 'timeZoneName');
  return part ? part.value : zone;
}
function validZone(zone) {
  try { new Intl.DateTimeFormat('en-US', {timeZone: zone}); return true; } catch { return false; }
}

const SPEED = {kmh: [3.6, 'km/h'], ms: [1, 'm/s'], mph: [2.2369362921, 'mp/h'], kn: [1.9438444924, 'kn']};
const round = (v, d = 2) => (v == null || !Number.isFinite(v) ? null : Math.round(v * 10 ** d) / 10 ** d);

export function weatherCode(precipitation, cloud, visibility, temperature) {
  if (cloud == null && precipitation == null) return null;
  if (visibility != null && visibility < 1000) return 45;
  if (precipitation != null && precipitation >= 0.1) {
    if (temperature != null && temperature <= 0) return precipitation < 1 ? 71 : precipitation < 4 ? 73 : 75;
    return precipitation < 0.5 ? 51 : precipitation < 2.5 ? 61 : precipitation < 7.6 ? 63 : 65;
  }
  if (cloud == null) return null;
  return cloud < 20 ? 0 : cloud < 50 ? 1 : cloud < 80 ? 2 : 3;
}

// ---- query handling ---------------------------------------------------------------

function list(params, key) {
  const v = params.get(key);
  return v == null || v === '' ? [] : v.split(',').map(s => s.trim()).filter(Boolean);
}
function parseQuery(kind, params) {
  const lats = list(params, 'latitude').map(Number), lons = list(params, 'longitude').map(Number);
  if (!lats.length || lats.length !== lons.length || lats.length > 50 || [...lats, ...lons].some(v => !Number.isFinite(v)))
    throw new QueryError('latitude and longitude must be matching lists of up to 50 numbers');
  const models = list(params, 'models').length ? list(params, 'models') : DEFAULT_MODELS[kind];
  for (const m of models) if (MODELS[m]?.kind !== kind) throw new QueryError(`Model ${m} is not available for ${kind}`);
  const hourly = list(params, 'hourly');
  const known = kind === 'marine' ? MARINE_VARS : FORECAST_VARS;
  for (const v of hourly) if (!known.includes(v)) throw new QueryError(`Variable ${v} is not available`);
  const days = params.has('forecast_days') ? Number(params.get('forecast_days')) : 7;
  if (!Number.isInteger(days) || days < 1 || days > 8) throw new QueryError('forecast_days must be 1 to 8');
  let zone = params.get('timezone') || 'GMT';
  if (zone === 'auto') zone = 'GMT';
  if (!validZone(zone)) throw new QueryError('Invalid timezone');
  const speed = params.get('wind_speed_unit') || 'kmh';
  if (!SPEED[speed]) throw new QueryError('Invalid wind_speed_unit');
  const cell = params.get('cell_selection') || (kind === 'marine' ? 'sea' : 'land');
  return {lats, lons, models, hourly, days, zone, speed, cell,
    imperial: params.get('length_unit') === 'imperial', fahrenheit: params.get('temperature_unit') === 'fahrenheit',
    inch: params.get('precipitation_unit') === 'inch', unixtime: params.get('timeformat') === 'unixtime'};
}

function unitFor(q, v) {
  if (v.endsWith('_height')) return q.imperial ? 'ft' : 'm';
  if (v.endsWith('_period')) return 's';
  if (v.endsWith('_direction') || v === 'wind_direction_10m') return '°';
  if (v === 'wind_speed_10m' || v === 'wind_gusts_10m') return SPEED[q.speed][1];
  if (v === 'temperature_2m') return q.fahrenheit ? '°F' : '°C';
  if (v === 'precipitation') return q.inch ? 'inch' : 'mm';
  if (v === 'visibility') return q.imperial ? 'ft' : 'm';
  if (v === 'cloud_cover') return '%';
  if (v === 'weather_code') return 'wmo code';
  return '';
}

// Hourly values for one model at one point, in canonical units.
function modelSeries(model, tile, q, lat, lon, targets) {
  const empty = () => targets.map(() => null);
  const weights = tile ? cellWeights(tile, lat, lon, q.cell === 'sea' || MODELS[model].kind === 'marine') : null;
  const out = {grid: weights?.grid ?? null};
  const T = tile?.times ?? [0];
  const get = (name, dir = false) => (weights ? nativeSeries(tile, name, weights, dir) : null);
  const smooth = (name) => { const s = get(name); return s ? hermite(T, s, targets) : empty(); };
  if (MODELS[model].kind === 'marine') {
    for (const v of q.hourly) {
      const name = v;
      out[v] = !weights || !tile.fields[name] ? empty()
        : v.endsWith('_direction') ? directionSeries(T, get(name, true), targets) : hermite(T, get(name), targets);
    }
    return out;
  }
  const u = weights ? hermite(T, get('u10'), targets) : empty(), vv = weights ? hermite(T, get('v10'), targets) : empty();
  const speed = u.map((x, i) => (x == null || vv[i] == null ? null : Math.hypot(x, vv[i])));
  const gust = smooth('gust').map((g, i) => (g == null ? null : speed[i] == null ? g : Math.max(g, speed[i])));
  const temperature = smooth('t2m'), cloud = smooth('cloud_cover').map(c => (c == null ? null : Math.min(100, Math.max(0, c))));
  const visibility = tile?.fields?.visibility ? smooth('visibility').map(v => (v == null ? null : Math.max(0, v))) : empty();
  const rawPrecip = get('precipitation');
  const precip = !rawPrecip ? empty() : (MODELS[model].precipitation === 'backward' ? backward(T, rawPrecip, targets)
    : hermite(T, rawPrecip, targets)).map(p => (p == null ? null : Math.max(0, p)));
  const all = {
    wind_speed_10m: speed,
    wind_direction_10m: u.map((x, i) => (x == null || vv[i] == null ? null : (Math.atan2(-x, -vv[i]) * 180 / Math.PI + 360) % 360)),
    wind_gusts_10m: gust, temperature_2m: temperature, cloud_cover: cloud, visibility, precipitation: precip,
    weather_code: precip.map((p, i) => weatherCode(p, cloud[i], visibility[i], temperature[i])),
  };
  for (const v of q.hourly) out[v] = all[v];
  return out;
}

function convertValue(q, v, x) {
  if (x == null) return null;
  if (v.endsWith('_height')) return round(q.imperial ? x * 3.28084 : x, 2);
  if (v.endsWith('_period')) return round(x, 2);
  if (v.endsWith('_direction') || v === 'wind_direction_10m') return Math.round(x) % 360;
  if (v === 'wind_speed_10m' || v === 'wind_gusts_10m') return round(x * SPEED[q.speed][0], 1);
  if (v === 'temperature_2m') return round(q.fahrenheit ? x * 9 / 5 + 32 : x, 1);
  if (v === 'precipitation') return round(q.inch ? x / 25.4 : x, q.inch ? 3 : 2);
  if (v === 'visibility') return round(q.imperial ? x * 3.28084 : x, 0);
  if (v === 'cloud_cover') return Math.round(x);
  return x;
}

/**
 * Answer an Open-Meteo-style query.
 * @param {'forecast'|'marine'} kind
 * @param {URLSearchParams} params
 * @param {{manifest:(model)=>Promise<object>, tile:(model,key)=>Promise<object|null>}} store
 * @param {number} [now] epoch seconds
 */
export async function answer(kind, params, store, now = Math.floor(Date.now() / 1000)) {
  const started = Date.now();
  const q = parseQuery(kind, params);
  const start = localMidnight(q.zone, now);
  const targets = Array.from({length: q.days * 24}, (_, i) => start + i * HOUR);
  const manifests = Object.fromEntries(await Promise.all(q.models.map(async m => [m, await store.manifest(m)])));
  const results = [];
  for (let p = 0; p < q.lats.length; p++) {
    const lat = q.lats[p], lon = q.lons[p];
    const key = `${Math.floor(lat)}_${Math.floor(lon)}`;
    const hourly = {time: q.unixtime ? targets : targets.map(t => isoLocal(t, q.zone))};
    const units = {time: q.unixtime ? 'unixtime' : 'iso8601'};
    let grid = null;
    for (const m of q.models) {
      const tile = manifests[m]?.tiles?.includes(key) ? await store.tile(m, key) : null;
      const series = modelSeries(m, tile, q, lat, lon, targets);
      grid = grid || series.grid;
      for (const v of q.hourly) {
        const name = q.models.length > 1 ? `${v}_${m}` : v;
        hourly[name] = series[v].map(x => convertValue(q, v, x));
        units[name] = unitFor(q, v);
      }
    }
    const offset = offsetSeconds(q.zone, now);
    results.push({latitude: grid?.latitude ?? round(lat, 4), longitude: grid?.longitude ?? round(lon, 4),
      generationtime_ms: Date.now() - started, utc_offset_seconds: offset, timezone: q.zone,
      timezone_abbreviation: zoneAbbreviation(q.zone, now), elevation: 0, hourly_units: units, hourly});
  }
  return results.length === 1 ? results[0] : results;
}

// Open-Meteo-compatible /data/<model>/static/meta.json
export async function meta(model, store) {
  if (!MODELS[model]) throw new QueryError('Unknown model');
  const manifest = await store.manifest(model);
  if (!manifest?.meta) throw new QueryError('Model not yet published');
  return {...manifest.meta, provider: manifest.provider, source: manifest.documentation, cycle_iso: manifest.cycle_iso};
}
