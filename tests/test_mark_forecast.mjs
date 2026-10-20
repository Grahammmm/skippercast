// BP CI6-06: the forecast at a mark or trip spot (web/brief/mark-forecast.ts,
// web/brief/MarkForecast.tsx in web/app/MarkCard.tsx). The region points are
// the committed dist/ region files. The forecast feeds are synthetic, in the
// /api/forecast shape with invented values; each model sample names its own
// cell, as the sampler does.
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
const {CELL_REACH, MODEL_GRIDS, distanceKm, forecastKind, gateGap, markForecast, nearestCell, readingSource} = await import('../web/brief/mark-forecast.ts');

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

test('step 0: Morro Bay and Cambria are gridded; every other committed region is point series', () => {
  const kinds = Object.fromEntries(readdirSync(new URL('../dist/regions/', import.meta.url), {withFileTypes: true}).filter(d => d.isDirectory())
    .map(d => { try { return region(d.name); } catch { return null; } }).filter(r => r?.forecast_points)
    .map(r => [r.id, forecastKind({region_id: r.id, retrieved: NOW, requested_points: r.forecast_points.map(p => [p.id, p.latitude, p.longitude]), models: {}}, r.id)]));
  assert.equal(Object.keys(kinds).length, 15);
  assert.deepEqual(Object.entries(kinds).filter(([, k]) => k === 'grid').map(([id]) => id).sort(), ['cambria-san-simeon', 'morro-bay']);
  assert.ok(Object.entries(kinds).filter(([, k]) => k !== 'grid').every(([, k]) => k === 'points'));
  assert.equal(forecastKind({...morroFeed(), region_id: 'cambria-san-simeon'}, 'morro-bay'), null, 'another region\'s feed is no answer');
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

test('acceptance 2-3: a gridded region reads each model at its own nearest cell, names model, grid and distance, and never averages the families', () => {
  const f = markForecast(parsed(morroFeed()), 'morro-bay', MARK, AT, NOW, TZ);
  assert.equal(f.kind, 'grid');
  assert.equal(f.point, null);
  assert.deepEqual(f.families.map(x => [x.family, x.label, x.rows.map(r => r.label)]), [['gfs', 'NOAA', ['Wind', 'Seas']], ['ecmwf', 'ECMWF', ['Wind', 'Seas']]]);
  const [[gfsWind, gfsSeas], [ifsWind, wamSeas]] = f.families.map(x => x.rows);
  // NOAA GFS: the central sample's cell is 0.9 km away; its index (1) gives 11 kt.
  assert.deepEqual([gfsWind.model, gfsWind.grid, gfsWind.point, gfsWind.value], ['NOAA GFS', MODEL_GRIDS.gfs_global.spacing, 'central', '11 kt from WNW 301° · gusts 17 kt']);
  assert.ok(Math.abs(gfsWind.cell.km - distanceKm(MARK, {lat: 35.37, lon: -120.94})) < 1e-9);
  assert.equal(gfsWind.validAt, AT);
  assert.deepEqual([gfsSeas.model, gfsSeas.grid, gfsSeas.point, gfsSeas.value], ['NOAA GFS-Wave', '0.16°', 'central', '2.1 ft · 11 s from WNW 290°']);
  // ECMWF: north, central and south share one cell; central was requested nearest the mark, so its own values (index 1) are read.
  assert.deepEqual([ifsWind.model, ifsWind.grid, ifsWind.point, ifsWind.value], ['ECMWF IFS', '0.25°', 'central', '21 kt from WNW 301° · gusts 27 kt']);
  assert.ok(Math.abs(ifsWind.cell.km - distanceKm(MARK, {lat: 35.25, lon: -121})) < 1e-9);
  assert.deepEqual([wamSeas.model, wamSeas.point, wamSeas.value], ['ECMWF WAM', 'central', '5.1 ft · 11 s from WNW 290°']);
  assert.notEqual(gfsWind.value, ifsWind.value, 'each family keeps its own value');
  // The surface current: the nearest WCOFS cell at the 3-hourly frame nearest the dock's hour.
  assert.deepEqual([f.current.model, f.current.grid, f.current.point, f.current.value], ['NOAA WCOFS', 'about 4 km', 'central', '0.20 kt toward 101° true']);
  assert.equal(f.current.validAt, Date.parse('2026-10-20T18:00:00Z'));
  assert.equal(readingSource(gfsWind, AT, TZ), `NOAA GFS · about 13 km grid · cell ${(Math.round(gfsWind.cell.km * 10) / 10)} km from this mark · run Oct 20, 6 am`);
  assert.match(readingSource(f.current, AT, TZ), /^NOAA WCOFS · about 4 km grid · cell 0\.9 km from this mark · valid Tue 11 am · run Oct 19, 8 pm$/);
});

test('a mark beyond 1.5 grid lengths of every sampled cell reads gaps, not a far value', () => {
  const f = markForecast(parsed(morroFeed()), 'morro-bay', {lat: 34.3, lon: -122.6}, AT, NOW, TZ);
  for (const r of [...f.families.flatMap(x => x.rows), f.current]) {
    assert.equal(r.value, null, r.model);
    assert.match(r.gap, /^no .+ cell .*lies within [\d.]+ km \(1\.5 grid lengths\) of this mark$/);
  }
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
    assert.equal(readingSource(r, AT, TZ), `${r.model} · ${r.grid} grid · point ${conditions.point.id} · run Oct 20, 6 am`);
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
    assert.match(html, /<span class="ui-eyebrow">Forecast here<\/span> <span class="ui-mono">valid Tue 10 am<\/span>/);
    assert.deepEqual([...html.matchAll(/<dt>([^<]+)<\/dt>/g)].map(m => m[1]), ['NOAA wind', 'NOAA seas', 'ECMWF wind', 'ECMWF seas', 'Surface current']);
    assert.match(html, /<div data-gap="true"><dt>NOAA wind<\/dt><dd class="ui-mono">—<\/dd><dd class="app-mark-forecast-source">Gap: the NOAA GFS sample has no wind value for Tue 10 am\.<\/dd><\/div>/);
    assert.match(html, /<dt>ECMWF wind<\/dt><dd class="ui-mono">21 kt from WNW 301° · gusts 27 kt<\/dd><dd class="app-mark-forecast-source">ECMWF IFS · 0\.25° grid · cell [\d.]+ km from this mark · run /);
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
    assert.match(points, new RegExp(`This region's forecast is a few named points, with no grid to sample at this mark\\. Values at forecast point ${regionalForecast.value.point.id}\\.`));
    assert.match(points, new RegExp(`NOAA GFS · about 13 km grid · point ${regionalForecast.value.point.id} · run`));
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
