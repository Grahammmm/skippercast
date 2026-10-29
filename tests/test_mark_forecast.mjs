// BP CI6-06: the forecast at a mark or trip spot (web/brief/mark-forecast.ts,
// web/brief/MarkForecast.tsx in web/app/MarkCard.tsx). The region points are
// the committed dist/ region files. The forecast feeds are synthetic, in the
// /api/forecast shape with invented values; each model sample reports a
// dominant cell, as the sampler does, which the card must never read as the
// value's location. One regression runs the real sampler (server/model-api.js).
import assert from 'node:assert/strict';
import {readFileSync, readdirSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';

const {parseConditionsForecast} = await import('../web/conditions.ts');
const {CELL_REACH, MODEL_GRIDS, distanceKm, gateGap, markForecast, nearestCell, readingSource} = await import('../web/brief/mark-forecast.ts');
const {answer} = await import('../server/model-api.js');

const ROOT = new URL('..', import.meta.url).pathname;
const HOUR = 3_600_000;
const TZ = 'America/Los_Angeles';
const region = id => JSON.parse(readFileSync(new URL(`../dist/regions/${id}/region.json`, import.meta.url), 'utf8'));
const MORRO = region('morro-bay');
const POINTS = MORRO.forecast_points.map(p => [p.id, p.latitude, p.longitude]);
// The dock's hour sits between two 3-hourly WCOFS frames; every model lists hourly.
const NOW = Date.parse('2026-10-20T17:20:00Z'), AT = Date.parse('2026-10-20T17:00:00Z'), T0 = Date.parse('2026-10-20T06:00:00Z') / 1000;
/** Words that would read a forecast as a go/no-go call. */
const VERDICT = /\b(?:safe|unsafe|go\b|no-go|good to go|stay in|fishable|favou?rable|recommended)\b/i;

/** One sample: hourly for three days from T0, `values` constant except `hole` hours of `holeVar`, from `cell`. */
function series(values, cell, {hole = [], holeVar = null} = {}) {
  const time = Array.from({length: 72}, (_, i) => T0 + i * 3600);
  return {latitude: cell[0], longitude: cell[1], utc_offset_seconds: 0,
    hourly_units: {time: 'unixtime', ...Object.fromEntries(Object.entries(values).map(([k, [, u]]) => [k, u]))},
    hourly: {time, ...Object.fromEntries(Object.entries(values).map(([k, [v]]) => [k, time.map(t => k === holeVar && hole.includes(t * 1000) ? null : v)]))}};
}
// The ECMWF cells as the live feed reports them: north, central and south share one 0.25° cell.
const ecmwfCell = ([id, lat, lon]) => ['north', 'central', 'south'].includes(id) ? [35.25, -121] : [Math.floor(lat * 4) / 4, Math.round(lon * 4) / 4];
const wamCell = p => p[0] === 'north' ? [35.5, -121] : ecmwfCell(p);

/** A Morro Bay feed: each point's value encodes its index, so a test can tell which sample was read. */
function morroFeed({runAgeH = 4, retrievedAgeH = 0.3, hole = null, currents = 'ok'} = {}) {
  const meta = {last_run_initialisation_time: NOW / 1000 - runAgeH * 3600, data_end_time: T0 + 71 * 3600};
  const model = (cell, values, opts = () => ({})) => ({meta, data: POINTS.map((p, i) => series(values(i), cell(p), opts(p)))});
  const wind = base => i => ({wind_speed_10m: [base + i, 'kn'], wind_gusts_10m: [base + i + 6, 'kn'], wind_direction_10m: [300 + i, '°']});
  const wave = base => i => ({wave_height: [base + i / 10, 'ft'], wave_period: [11, 's'], wave_direction: [290, '°']});
  const frames = Array.from({length: 24}, (_, k) => T0 + k * 3 * 3600);
  return {region_id: 'morro-bay', retrieved: NOW - retrievedAgeH * HOUR, requested_points: POINTS,
    models: {
      gfs_global: model(p => [p[1] + 0.01, p[2]], wind(10), p => (hole && p[0] === 'central' ? {hole, holeVar: 'wind_speed_10m'} : {})),
      ncep_gfswave016: model(p => [p[1] - 0.02, p[2] - 0.02], wave(2)),
      ecmwf_ifs025: model(ecmwfCell, wind(20)),
      ecmwf_wam: model(wamCell, wave(5)),
    },
    currents: {source: 'wcofs', name: 'NOAA WCOFS surface currents', status: currents, issued_at: new Date(NOW - 14 * HOUR).toISOString(), resolution_km: 4,
      units: {speed: 'kn', direction: '° toward'},
      points: currents === 'ok' ? POINTS.map(([id, lat, lon], i) => ({point_id: id, requested: [lat, lon], samples: frames.map(t => [t, lat + 0.01, lon, 0.1 * (i + 1), 100 + i, 1.11])})) : []}};
}
const parsed = feed => parseConditionsForecast(feed, feed.region_id, [35.34, -120.965]);
const MARK = {lat: 35.37, lon: -120.95};

test('step 0: model wind and seas are point series in every committed region, lattice or not; each reads its regional point, named', () => {
  const regions = readdirSync(new URL('../dist/regions/', import.meta.url), {withFileTypes: true}).filter(d => d.isDirectory())
    .map(d => { try { return region(d.name); } catch { return null; } }).filter(r => r?.forecast_points);
  assert.equal(regions.length, 16);
  const meta = {last_run_initialisation_time: NOW / 1000 - 4 * 3600, data_end_time: T0 + 71 * 3600};
  for (const r of regions) {
    const pts = r.forecast_points.map(p => [p.id, p.latitude, p.longitude]);
    // Every series reports one shared (dominant) cell at the region's centre, as the sampler may.
    const feed = {region_id: r.id, retrieved: NOW - HOUR, requested_points: pts,
      models: {gfs_global: {meta, data: pts.map((p, i) => series({wind_speed_10m: [5 + i, 'kn']}, r.map.center))}}};
    const conditions = parseConditionsForecast(feed, r.id, r.map.center);
    const f = markForecast(conditions, r.id, {lat: r.map.center[0], lon: r.map.center[1]}, AT, NOW, TZ);
    assert.equal(f.kind, 'points', r.id);
    assert.equal(f.point, conditions.point.id, r.id);
    const wind = f.families[0].rows[0], index = pts.findIndex(p => p[0] === conditions.point.id);
    assert.deepEqual([wind.point, wind.cell, wind.value], [conditions.point.id, null, `${5 + index} kt`], r.id);
  }
  assert.equal(markForecast(parsed({...morroFeed(), region_id: 'cambria-san-simeon'}), 'morro-bay', MARK, AT, NOW, TZ), null, 'another region\'s feed is no answer');
});

test('regression: the real sampler interpolates each point and reports a shared dominant cell; the card never calls those values a cell\'s', async () => {
  // Invented 2 x 2 wind tile at 0.25°, unequal cells (wind from the north, 10/20/30/40 m/s), through server/model-api.js answer().
  const t0 = Date.parse('2026-10-20T00:00:00Z') / 1000, now = (t0 + 12 * 3600) * 1000;
  const field = values => ({scale: 1, data: Buffer.from(new Int16Array([...values, ...values]).buffer).toString('base64')});
  const tile = {lat0: 35, lon0: -121, dlat: 0.25, dlon: 0.25, nlat: 2, nlon: 2, times: [t0, t0 + 24 * 3600], sea: Buffer.from([0b11110000]).toString('base64'),
    fields: {u10: field([0, 0, 0, 0]), v10: field([-10, -20, -30, -40])}};
  const meta = {last_run_initialisation_time: t0, data_end_time: t0 + 24 * 3600};
  const store = {manifest: async () => ({tiles: ['35_-121'], meta}), tile: async () => tile};
  const pts = [['a', 35.02, -120.98], ['b', 35.02, -120.96], ['c', 35.04, -120.98], ['d', 35.04, -120.96]];
  const query = (lat, lon) => new URLSearchParams({latitude: lat, longitude: lon, models: 'gfs_global', hourly: 'wind_speed_10m,wind_direction_10m',
    wind_speed_unit: 'kn', timezone: 'UTC', timeformat: 'unixtime', forecast_days: '1'});
  const data = await answer('forecast', query(pts.map(p => p[1]).join(','), pts.map(p => p[2]).join(',')), store, now / 1000);
  const cell = await answer('forecast', query('35', '-121'), store, now / 1000);
  const hour = data[0].hourly.time.indexOf(now / 1000), speeds = data.map(s => s.hourly.wind_speed_10m[hour]);
  // The premise: four points report the same cell but carry four different interpolations, none of them the cell's own value.
  assert.ok(data.every(s => s.latitude === 35 && s.longitude === -121));
  assert.equal(new Set(speeds.map(v => v.toFixed(3))).size, 4);
  assert.ok(speeds.every(v => Math.abs(v - cell.hourly.wind_speed_10m[hour]) > 1), 'no point value is the cell value');
  const conditions = parseConditionsForecast({region_id: 'morro-bay', retrieved: now, requested_points: pts, models: {gfs_global: {meta, data}}}, 'morro-bay', [35, -121]);
  assert.equal(conditions.point.id, 'a');
  // A mark on the reported cell and a mark on another requested point both read the regional point, named, with no cell or distance.
  for (const mark of [{lat: 35, lon: -121}, {lat: 35.04, lon: -120.96}]) {
    const f = markForecast(conditions, 'morro-bay', mark, now, now, 'UTC'), wind = f.families[0].rows[0];
    assert.deepEqual([f.kind, wind.point, wind.cell, wind.value], ['points', 'a', null, `${Math.round(speeds[0])} kt from N 0°`]);
    assert.equal(readingSource(wind, now, 'UTC'), 'NOAA GFS · about 13 km grid · forecast point a · run Oct 20, 12 am');
    assert.doesNotMatch(readingSource(wind, now, 'UTC'), /cell|from this mark/);
  }
});

test('nearest cell: the closest sampled cell wins; a shared cell goes to the point requested nearer; past reach is no cell', () => {
  const mark = {lat: 35.3, lon: -121};
  const c = (index, point, requested, cell) => ({index, point, requested: {lat: requested[0], lon: requested[1]}, cell: {lat: cell[0], lon: cell[1]}});
  const far = c(0, 'far', [35.6, -121], [35.6, -121]), near = c(1, 'near', [35.32, -121], [35.31, -121]);
  assert.equal(nearestCell([far, near], mark, 50).point, 'near');
  assert.ok(Math.abs(nearestCell([far, near], mark, 50).km - distanceKm(mark, {lat: 35.31, lon: -121})) < 1e-9);
  assert.ok(Math.abs(distanceKm({lat: 35, lon: -121}, {lat: 36, lon: -121}) - 111.19) < 0.01, 'one degree of latitude');
  // Two points sampled from one cell: the one requested nearer the mark, whatever the feed order.
  const shared = [c(0, 'outer', [35.4, -121.2], [35.25, -121]), c(1, 'inner', [35.31, -121.01], [35.25, -121])];
  assert.equal(nearestCell(shared, mark, 50).point, 'inner');
  assert.equal(nearestCell([...shared].reverse(), mark, 50).point, 'inner');
  assert.equal(nearestCell([far], mark, 30), null, 'a cell 33 km away is beyond a 30 km reach');
  assert.equal(nearestCell([], mark, 30), null);
});

test('acceptance 2-3: model rows read the regional point with model and grid; the WCOFS current reads the nearest native cell with its distance; families never averaged', () => {
  const f = markForecast(parsed(morroFeed()), 'morro-bay', MARK, AT, NOW, TZ);
  assert.deepEqual([f.kind, f.point], ['points', 'central']);
  assert.deepEqual(f.families.map(x => [x.family, x.label, x.rows.map(r => r.label)]), [['gfs', 'NOAA', ['Wind', 'Seas']], ['ecmwf', 'ECMWF', ['Wind', 'Seas']]]);
  const [[gfsWind, gfsSeas], [ifsWind, wamSeas]] = f.families.map(x => x.rows);
  // Every model row is the regional point's (central, index 1) own series; the cell each series reports is never used.
  assert.deepEqual([gfsWind.model, gfsWind.grid, gfsWind.point, gfsWind.cell, gfsWind.value], ['NOAA GFS', MODEL_GRIDS.gfs_global, 'central', null, '11 kt from WNW 301° · gusts 17 kt']);
  assert.equal(gfsWind.validAt, AT);
  assert.deepEqual([gfsSeas.model, gfsSeas.grid, gfsSeas.point, gfsSeas.value], ['NOAA GFS-Wave', '0.16°', 'central', '2.1 ft · 11 s from WNW 290°']);
  assert.deepEqual([ifsWind.model, ifsWind.grid, ifsWind.point, ifsWind.cell, ifsWind.value], ['ECMWF IFS', '0.25°', 'central', null, '21 kt from WNW 301° · gusts 27 kt']);
  assert.deepEqual([wamSeas.model, wamSeas.point, wamSeas.value], ['ECMWF WAM', 'central', '5.1 ft · 11 s from WNW 290°']);
  assert.notEqual(gfsWind.value, ifsWind.value, 'each family keeps its own value');
  // The surface current: the nearest WCOFS cell at the 3-hourly frame nearest the dock's hour, with its distance.
  assert.deepEqual([f.current.model, f.current.grid, f.current.point, f.current.value], ['NOAA WCOFS', 'about 4 km', 'central', '0.20 kt toward 101° true']);
  assert.ok(Math.abs(f.current.cell.km - distanceKm(MARK, {lat: 35.37, lon: -120.94})) < 1e-9);
  assert.equal(f.current.validAt, Date.parse('2026-10-20T18:00:00Z'));
  assert.equal(readingSource(gfsWind, AT, TZ), 'NOAA GFS · about 13 km grid · forecast point central · run Oct 20, 6 am');
  assert.match(readingSource(f.current, AT, TZ), /^NOAA WCOFS · about 4 km grid · cell 0\.9 km from this mark · valid Tue 11 am · run Oct 19, 8 pm$/);
  // A mark nearer another point's WCOFS cell reads that cell, not the regional point's.
  const south = markForecast(parsed(morroFeed()), 'morro-bay', {lat: 35.26, lon: -120.95}, AT, NOW, TZ);
  assert.deepEqual([south.current.point, south.current.value, south.families[0].rows[0].point], ['south', '0.30 kt toward 102° true', 'central']);
  assert.ok(Math.abs(south.current.cell.km - distanceKm({lat: 35.26, lon: -120.95}, {lat: 35.25, lon: -120.94})) < 1e-9);
});

test('a mark beyond 1.5 grid lengths of every WCOFS cell reads the regional point\'s current, named, with no distance; no sample there is a gap', () => {
  const far = {lat: 34.3, lon: -122.6}, f = markForecast(parsed(morroFeed()), 'morro-bay', far, AT, NOW, TZ);
  assert.deepEqual([f.current.point, f.current.cell, f.current.value], ['central', null, '0.20 kt toward 101° true']);
  assert.equal(readingSource(f.current, AT, TZ), 'NOAA WCOFS · about 4 km grid · forecast point central · valid Tue 11 am · run Oct 19, 8 pm');
  for (const r of f.families.flatMap(x => x.rows)) assert.equal(r.point, 'central');
  const feed = morroFeed();
  feed.currents.points = feed.currents.points.filter(p => p.point_id === 'north');
  const none = markForecast(parsed(feed), 'morro-bay', far, AT, NOW, TZ);
  assert.equal(none.current.value, null);
  assert.equal(none.current.gap, 'no NOAA WCOFS cell sampled for Tue 11 am lies within 6 km (1.5 grid lengths) of this mark, and forecast point central has no sample then');
  assert.equal(CELL_REACH, 1.5);
});

test('acceptance 4: a stale run, a stale feed or a missing value is a gap with its reason; nothing is filled', () => {
  const stale = markForecast(parsed(morroFeed({runAgeH: 37})), 'morro-bay', MARK, AT, NOW, TZ);
  for (const r of stale.families.flatMap(x => x.rows)) {
    assert.equal(r.value, null);
    assert.match(r.gap, /^the .+ run of Oct 18, 9 pm is past its 36-hour age limit$/);
    assert.equal(r.validAt, null);
  }
  assert.ok(stale.current.value, 'WCOFS keeps its own clock');
  const old = markForecast(parsed(morroFeed({retrievedAgeH: 7})), 'morro-bay', MARK, AT, NOW, TZ);
  for (const r of [...old.families.flatMap(x => x.rows), old.current]) assert.equal(r.gap, 'the regional forecast was last retrieved more than 6 hours ago');
  const hole = markForecast(parsed(morroFeed({hole: [AT]})), 'morro-bay', MARK, AT, NOW, TZ);
  assert.equal(hole.families[0].rows[0].value, null);
  assert.equal(hole.families[0].rows[0].gap, 'the NOAA GFS sample has no wind value for Tue 10 am');
  assert.equal(hole.families[1].rows[0].value, '21 kt from WNW 301° · gusts 27 kt', 'the other family is not used to fill it');
  const noCurrent = markForecast(parsed(morroFeed({currents: 'stale'})), 'morro-bay', MARK, AT, NOW, TZ);
  assert.equal(noCurrent.current.gap, 'the regional forecast carries no NOAA WCOFS surface-current forecast (stale)');
  const later = markForecast(parsed(morroFeed()), 'morro-bay', MARK, Date.parse('2026-10-24T17:00:00Z'), NOW, TZ);
  assert.match(later.families[0].rows[0].gap, /^the selected hour is outside the NOAA GFS run of Oct 20, 6 am$/);
  assert.equal(gateGap('X', [], null, NOW, AT, NOW, TZ), 'the X run carries no issue time, so its age cannot be checked');
  assert.equal(markForecast(null, 'morro-bay', MARK, AT, NOW, TZ), null);
});

test('acceptance 1: a point-series region says so, reads the regional point, named, and samples nothing at the mark', () => {
  const info = region('monterey-point-sur'), pts = info.forecast_points.map(p => [p.id, p.latitude, p.longitude]);
  const meta = {last_run_initialisation_time: NOW / 1000 - 4 * 3600, data_end_time: T0 + 71 * 3600};
  const values = {wind_speed_10m: [9, 'kn'], wind_gusts_10m: [14, 'kn'], wind_direction_10m: [300, '°'], wave_height: [5.1, 'ft'], wave_period: [12, 's']};
  const feed = {region_id: info.id, retrieved: NOW - HOUR, requested_points: pts,
    models: Object.fromEntries(['gfs_global', 'ncep_gfswave016', 'ecmwf_ifs025', 'ecmwf_wam'].map(id => [id, {meta, data: pts.map(p => series(values, [p[1], p[2]]))}]))};
  const conditions = parseConditionsForecast(feed, info.id, info.map.center);
  const f = markForecast(conditions, info.id, {lat: 36.55, lon: -122.0}, AT, NOW, TZ);
  assert.equal(f.kind, 'points');
  assert.equal(f.point, conditions.point.id, 'the point the brief reads');
  for (const r of f.families.flatMap(x => x.rows)) {
    assert.equal(r.point, conditions.point.id);
    assert.equal(r.cell, null, 'no distance: the value is the region\'s, not the mark\'s');
    assert.ok(r.value);
    assert.equal(readingSource(r, AT, TZ), `${r.model} · ${r.grid} grid · forecast point ${conditions.point.id} · run Oct 20, 6 am`);
  }
  assert.equal(f.current.gap, 'the regional forecast carries no NOAA WCOFS surface-current forecast');
});

let ui;
async function components() {
  if (ui) return ui;
  const out = join(await mkdtemp(join(tmpdir(), 'mark-forecast-')), 'card.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {MarkForecast} from './web/brief/MarkForecast.tsx';
      export {MarkCard, markPlace} from './web/app/MarkCard.tsx';
      export {markData, markScreen} from './web/map/marks.ts';
      export {assessScreen} from './web/map/habitat.ts';
      export {regionalForecast} from './web/brief/Brief.tsx';
      export {regionInfo} from './web/app/App.tsx';
      export {parseConditionsForecast} from './web/conditions.ts';
      export * as state from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: rendererPlugins,
  });
  ui = await import(pathToFileURL(out).href);
  return ui;
}

test('the card block: one row per family and model, the current, gaps as "—" with the reason, no go/no-go words; a withheld mark has none', async () => {
  const {MarkForecast, markPlace, regionalForecast, regionInfo, parseConditionsForecast: parse, state, render, h} = await components();
  state.configureStore({v2: true, storage: null});
  state.syncFromURL('https://s.test/map?region=morro-bay');
  regionInfo.value = {id: 'morro-bay', name: MORRO.name, center: MORRO.map.center, timezone: TZ};
  regionalForecast.value = parse(morroFeed({hole: [AT]}), 'morro-bay', MORRO.map.center);
  try {
    const html = render(h(MarkForecast, {place: MARK, now: new Date(NOW)}));
    assert.match(html, /<section class="app-mark-forecast" aria-label="Forecast at this mark">/);
    assert.match(html, /<span class="ui-eyebrow">Regional forecast<\/span> <span class="ui-mono">valid Tue 10 am<\/span>/);
    assert.match(html, /This region's wind and seas forecast is a few named points, with no model grid to sample at this mark\. Wind and seas at forecast point central\./);
    assert.deepEqual([...html.matchAll(/<dt>([^<]+)<\/dt>/g)].map(m => m[1]), ['NOAA wind', 'NOAA seas', 'ECMWF wind', 'ECMWF seas', 'Surface current']);
    assert.match(html, /<div data-gap="true"><dt>NOAA wind<\/dt><dd class="ui-mono">—<\/dd><dd class="app-mark-forecast-source">Gap: the NOAA GFS sample has no wind value for Tue 10 am\.<\/dd><\/div>/);
    assert.match(html, /<dt>ECMWF wind<\/dt><dd class="ui-mono">21 kt from WNW 301° · gusts 27 kt<\/dd><dd class="app-mark-forecast-source">ECMWF IFS · 0\.25° grid · forecast point central · run /);
    assert.match(html, /<dt>Surface current<\/dt><dd class="ui-mono">0\.20 kt toward 101° true<\/dd><dd class="app-mark-forecast-source">NOAA WCOFS · about 4 km grid · cell 0\.9 km from this mark · /);
    assert.doesNotMatch(html, /Each value is a model grid cell/);
    assert.match(html, /<details class="ui-popover"/, 'the basis sits in a disclosure');
    assert.doesNotMatch(html.replace(/<[^>]+>/g, ' '), VERDICT);
    // No feed yet: the block says so rather than guessing.
    regionalForecast.value = null;
    assert.match(render(h(MarkForecast, {place: MARK, now: new Date(NOW)})), /The regional forecast has not loaded, so these rows are empty\./);
    // Point series: the note names the regional point and no row gives a distance.
    const info = region('monterey-point-sur'), pts = info.forecast_points.map(p => [p.id, p.latitude, p.longitude]);
    const meta = {last_run_initialisation_time: NOW / 1000 - 4 * 3600, data_end_time: T0 + 71 * 3600};
    const wind = {wind_speed_10m: [9, 'kn'], wind_gusts_10m: [14, 'kn'], wind_direction_10m: [300, '°']};
    regionInfo.value = {id: info.id, name: info.name, center: info.map.center, timezone: TZ};
    regionalForecast.value = parse({region_id: info.id, retrieved: NOW - HOUR, requested_points: pts, models: {gfs_global: {meta, data: pts.map(p => series(wind, [p[1], p[2]]))}}}, info.id, info.map.center);
    const points = render(h(MarkForecast, {place: {lat: 36.55, lon: -122}, now: new Date(NOW)}));
    assert.match(points, /<span class="ui-eyebrow">Regional forecast<\/span>/);
    assert.match(points, new RegExp(`This region's wind and seas forecast is a few named points, with no model grid to sample at this mark\\. Wind and seas at forecast point ${regionalForecast.value.point.id}\\.`));
    assert.match(points, new RegExp(`NOAA GFS · about 13 km grid · forecast point ${regionalForecast.value.point.id} · run`));
    assert.doesNotMatch(points, /from this mark/);
    assert.match(points, /<dt>ECMWF wind<\/dt><dd class="ui-mono">—<\/dd><dd class="app-mark-forecast-source">Gap: the regional forecast carries no ECMWF IFS samples\.<\/dd>/);
  } finally { regionalForecast.value = null; regionInfo.value = null; }
  assert.equal(markPlace({id: 'spot:SC26-001', name: 'Reef mark withheld', kind: '', reading: '', source: '', basis: '', withheld: true}), null, 'never for a withheld mark');
  assert.equal(markPlace({id: 'coastline:x', name: 'Shoreline', kind: '', reading: '', source: '', basis: ''}), null, 'only marks and trip spots');
});

test('the mark card carries the block for a reef mark the screen shows, and drops it when the screen withholds the mark', async () => {
  const {MarkCard, markData, markScreen, assessScreen, regionalForecast, regionInfo, parseConditionsForecast: parse, state, render, h} = await components();
  const read = path => JSON.parse(readFileSync(new URL(`../dist/${path}`, import.meta.url), 'utf8'));
  const ATLAS = read('data/atlas.json'), MPAS = read('data/protected-areas.geojson'), mark = ATLAS.targets[0];
  state.configureStore({v2: true, storage: null});
  state.syncFromURL(`https://s.test/map?region=morro-bay&target=reef&spot=${mark.id}`);
  markData.value = {region: MORRO, atlas: ATLAS, survey: null, geology: null};
  regionInfo.value = {id: 'morro-bay', name: MORRO.name, center: MORRO.map.center, timezone: TZ};
  regionalForecast.value = parse(morroFeed(), 'morro-bay', MORRO.map.center);
  try {
    markScreen.value = assessScreen({areas: MPAS.features, checkedAt: new Date(Date.now() - HOUR).toISOString(), live: true}, Date.now());
    const card = render(h(MarkCard, {}));
    assert.match(card, /<section class="app-mark-forecast" aria-label="Forecast at this mark">/);
    assert.ok(card.indexOf('app-mark-forecast') < card.indexOf('app-mark-actions'), 'between the rules and the actions');
    markScreen.value = assessScreen({areas: MPAS.features, checkedAt: new Date(Date.now() - 40 * HOUR).toISOString(), live: false}, Date.now());
    const withheld = render(h(MarkCard, {}));
    assert.match(withheld, /<h2 tabindex="-1">Reef mark withheld<\/h2>/);
    assert.doesNotMatch(withheld, /app-mark-forecast/, 'a withheld mark keeps its position, and so its forecast, to itself');
  } finally { markData.value = null; regionalForecast.value = null; regionInfo.value = null; }
});
