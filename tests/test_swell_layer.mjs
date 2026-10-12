// Swell as a field (FE-17, docs/plans/front-end/dev-plan.md): the regional
// forecast grid reader (web/map/forecast-grid.ts, pinned to v1's sample), the
// dock-hour gate (web/map/frames.ts forecastTime, FE-12's forecast gate), the
// height texture, period isolines and direction strokes (web/map/swell.ts) and
// the Chart layer over a fake engine, so no GPU, MapLibre or network is needed.
// Feeds are synthetic, in the shape /api/forecast serves: a 3 × 3 grid 0.25°
// apart where Morro Bay's offshore forecast points lie, plus two inshore
// points off that grid. web/map/*.ts run by type stripping; the legend and rail
// are bundled with esbuild and rendered.
import assert from 'node:assert/strict';
import {mkdtemp, readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {pathToFileURL} from 'node:url';
import {signal} from '@preact/signals';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import {sample as v1Sample} from '../dist/marine-data.js';
import {fieldColor} from '../packages/coast/src/map/surface-field.ts';
import {FILES, luminance, themes} from '../scripts/check_contrast.mjs';
import {chartMark} from '../web/map/chart.ts';
import {createEngine} from '../web/map/engine.ts';
import {WAVE_MODEL, latticePoints, parseForecast, sample, swellPoints} from '../web/map/forecast-grid.ts';
import {forecastTime} from '../web/map/frames.ts';
import {railNotes} from '../web/map/layers.ts';
import {MPA_FILL} from '../web/map/mpa.ts';
import {ramps, readPalette} from '../web/map/palette.ts';
import {CONTOUR_LABELS, CONTOUR_LAYER, SST_LAYER, waterTempOverlay} from '../web/map/sst.ts';
import {
  HEIGHT_SCALE, ISOLINE_LABELS, ISOLINE_LAYER, ISOLINE_SOURCE, STROKE_CASING, STROKE_LAYER, STROKE_SOURCE, SWELL_BASIS, SWELL_LAYER, SWELL_SOURCE,
  createSwell, directionStrokes, frameSummary, periodLines, swellFrame, swellMark, swellOverlay, swellState, swellStatus,
} from '../web/map/swell.ts';
import {configureStore, setParams, syncFromURL} from '../web/state.ts';

const PAGE = 'https://s.test/map', TZ = 'America/Los_Angeles', HOUR = 3_600_000;
const NOW = new Date('2026-10-09T18:00:00Z'), ISSUED = Date.parse('2026-10-09T06:00:00Z');
const AT = new Date('2026-10-09T20:00:00Z'), AT_PARAM = '2026-10-09T20:00Z';
const LATS = [35.05, 35.3, 35.55], LONS = [-121.75, -121.5, -121.25];
const sentinel = readPalette(name => `token(${name})`);
const times = Array.from({length: 48}, (_, k) => ISSUED / 1000 + k * 3600);
const kOf = at => (at - ISSUED) / HOUR;

/**
 * The feed: per grid point (column i west to east, row j south to north) and hour index k, the height
 * rises east and north and by 0.5 ft an hour; the period crosses 12 s between the first two columns; the
 * swell comes from 290° plus 5° a row. `values(i, j, k)` may return nulls; inshore points sit off the grid.
 */
function feed({region = 'morro-bay', retrieved = NOW.getTime() - HOUR, issued = ISSUED / 1000, values = (i, j, k) => [2 + i * 0.5 + j * 0.3 + k * 0.5, 11.2 + i * 1.2, 290 + j * 5], model = {}, hours = times} = {}) {
  const points = [['north', 35.45, -121.02], ['central', 35.36, -120.94]], series = [];
  const at = (i, j) => ({utc_offset_seconds: 0, hourly_units: {time: 'unixtime', swell_wave_height: 'ft', swell_wave_period: 's', swell_wave_direction: '°'},
    hourly: {time: hours, ...Object.fromEntries(['swell_wave_height', 'swell_wave_period', 'swell_wave_direction'].map((v, n) => [v, hours.map((_, k) => values(i, j, k)[n])]))}});
  series.push(at(0, 0), at(0, 0));
  for (let j = 0; j < 3; j++) for (let i = 0; i < 3; i++) { points.push([`offshore-${j}-${i}`, LATS[j], LONS[i]]); series.push(at(i, j)); }
  return {region_id: region, requested_points: points, retrieved,
    models: {[WAVE_MODEL.id]: {data: series, meta: {last_run_initialisation_time: issued, data_end_time: hours.at(-1)}, ...model}, gfs_global: {data: [], meta: {}}}};
}
const parsed = (o = {}) => parseForecast(feed(o), 'morro-bay');
const ready = forecast => ({state: 'ready', region: 'morro-bay', forecast, at: NOW.getTime()});
const status = (f = parsed(), at = AT, now = NOW) => swellStatus(true, ready(f), at, now, TZ);
const region = async name => JSON.parse(await readFile(new URL(`../regions/${name}/region.json`, import.meta.url), 'utf8'));

test('the sample reader is v1\'s: unit-checked, the exact hour, never past the run, never negative', () => {
  const series = (values, extra = {}) => ({utc_offset_seconds: 0, hourly_units: {time: 'unixtime', swell_wave_height: 'ft', swell_wave_direction: '°'},
    hourly: {time: [100, 3700, 7300], swell_wave_height: values, swell_wave_direction: [10, 400, 359]}, ...extra});
  const cases = [
    [series([0, 2, 3]), 'swell_wave_height', 100, 'ft'], [series([0, 2, 3]), 'swell_wave_height', 3700, 'm'],
    [series([0, 2, 3]), 'swell_wave_height', 3700, 'ft', {data_end_time: 3699}], [series([0, 2, 3]), 'swell_wave_height', 4000, 'ft'],
    [series([-1, null, '3']), 'swell_wave_height', 100, 'ft'], [series([1, null, 3]), 'swell_wave_height', 3700, 'ft'], [series([1, 2, '3']), 'swell_wave_height', 7300, 'ft'],
    [series([1, 2]), 'swell_wave_height', 100, 'ft'], [series([1, 2, 3], {utc_offset_seconds: 3600}), 'swell_wave_height', 100, 'ft'],
    [series([1, 2, 3]), 'swell_wave_direction', 3700, '°'], [series([1, 2, 3]), 'swell_wave_direction', 7300, '°'],
    [{...series([1, 2, 3]), hourly: {time: [100, 100, 7300], swell_wave_height: [1, 2, 3]}}, 'swell_wave_height', 100, 'ft'], [null, 'swell_wave_height', 100, 'ft'],
  ];
  for (const [data, variable, epoch, unit, meta] of cases) assert.equal(sample(data, variable, epoch, unit, meta), v1Sample(data, variable, epoch, unit, meta), JSON.stringify([variable, epoch, unit, meta]));
  assert.equal(sample(series([0, 2, 3]), 'swell_wave_height', 100, 'ft'), 0, 'zero stays zero');
});

test('the grid is the points sharing a latitude and a longitude: Morro Bay\'s 3 × 3, Cambria\'s 2 × 2, none in Santa Cruz', async () => {
  const grid = async name => latticePoints((await region(name)).forecast_points.map(p => ({id: p.id, lat: p.latitude, lon: p.longitude}))).map(p => p.id);
  assert.deepEqual(await grid('morro-bay'), (await region('morro-bay')).forecast_points.filter(p => p.offshore).map(p => p.id));
  assert.deepEqual(await grid('cambria-san-simeon'), ['offshore-0-0', 'offshore-0-1', 'offshore-1-0', 'offshore-1-1']);
  assert.deepEqual(await grid('santa-cruz-monterey-bay'), []);
  const f = parsed();
  assert.deepEqual(f.lattice.map(p => p.index), [2, 3, 4, 5, 6, 7, 8, 9, 10], 'each point keeps its series index');
  assert.deepEqual(f.step, [0.25, 0.25]);
  assert.equal(f.model.issued, ISSUED / 1000);
  assert.equal(parseForecast(feed({region: 'cambria-san-simeon'}), 'morro-bay'), null, 'another region\'s feed');
  assert.equal(parseForecast({...feed(), retrieved: 'soon'}, 'morro-bay'), null);
  assert.equal(parseForecast({...feed(), requested_points: [['x', 35, 'w']]}, 'morro-bay'), null);
  const santaCruz = parseForecast({...feed(), requested_points: [['a', 36.9, -122.1], ['b', 36.8, -122.0], ['c', 36.6, -121.9]], region_id: 'santa-cruz'}, 'santa-cruz');
  assert.equal(santaCruz.step, null);
  assert.equal(parsed({model: {data: []}}).model, null, 'series that do not match the points');
  assert.equal(parsed({model: {meta: {}}}).model, null, 'a run without its time');
});

test('forecastTime is the currents\' forecast gate over a model\'s listed hours', () => {
  const ms = times.map(t => t * 1000), fetched = NOW.getTime() - HOUR;
  assert.equal(forecastTime(ms, ISSUED, fetched, AT, NOW), AT.getTime(), 'the listed hour itself');
  assert.equal(forecastTime(ms.filter((_, k) => k % 3 === 0), ISSUED, fetched, new Date(ISSUED + 4 * HOUR), NOW), ISSUED + 3 * HOUR, 'the nearest within 90 min');
  assert.equal(forecastTime(ms.filter((_, k) => k % 6 === 0), ISSUED, fetched, new Date(ISSUED + 9 * HOUR), NOW), null, 'none within 90 min');
  assert.equal(forecastTime(ms, ISSUED, fetched, new Date(ISSUED - HOUR), NOW), null, 'before the run');
  assert.equal(forecastTime(ms, ISSUED, fetched, new Date(ms.at(-1) + HOUR), NOW), null, 'past its end');
  assert.equal(forecastTime(ms, NOW.getTime() - 36 * HOUR, fetched, AT, NOW), AT.getTime(), 'issued 36 h ago');
  assert.equal(forecastTime(ms, NOW.getTime() - 36 * HOUR - 60_000, fetched, AT, NOW), null, 'issued over 36 h ago');
  assert.equal(forecastTime(ms, ISSUED, NOW.getTime() - 6 * HOUR - 60_000, AT, NOW), null, 'retrieved over 6 h ago');
  assert.equal(forecastTime(ms, Number.NaN, fetched, AT, NOW), null);
});

test('nothing draws off the gate, and the reason names the run', () => {
  assert.deepEqual(swellStatus(false, ready(parsed()), AT, NOW, TZ), {drawn: null, note: '', reason: '', basis: SWELL_BASIS});
  assert.equal(swellStatus(true, {state: 'loading', region: 'morro-bay', forecast: null, at: 0}, AT, NOW, TZ).note, 'loading');
  assert.equal(swellStatus(true, {state: 'error', region: 'morro-bay', forecast: null, at: 0}, AT, NOW, TZ).reason, 'Swell unavailable: the regional wave forecast failed to load.');
  const flat = parseForecast({...feed(), requested_points: feed().requested_points.map(([id, lat, lon], n) => [id, lat + n * 0.01, lon])}, 'morro-bay');
  assert.equal(status(flat).note, 'no forecast grid for this region');
  assert.equal(status(parsed({model: {data: []}})).reason, 'Swell unavailable: the regional forecast carries no NOAA GFS-Wave run.');
  const old = status(parsed({issued: (NOW.getTime() - 37 * HOUR) / 1000}));
  assert.equal(old.note, 'no fresh forecast · run Oct 7, 10 pm');
  assert.equal(old.reason, 'Swell unavailable: the latest NOAA GFS-Wave run, of Oct 7, 10 pm, is past its 36-hour age limit.');
  assert.equal(status(parsed({retrieved: NOW.getTime() - 7 * HOUR})).reason, 'Swell unavailable: the regional forecast was last retrieved more than 6 hours ago.');
  const late = status(parsed(), new Date(ISSUED + 60 * HOUR));
  assert.equal(late.note, 'no forecast for this hour');
  assert.equal(late.reason, 'Swell unavailable: the selected hour is outside the NOAA GFS-Wave run of Oct 8, 11 pm, which ends Sat Oct 10, 10 pm.');
  // A run or a retrieval dated over 5 minutes ahead of the clock, and a run listing no hour within 90 minutes, each say so.
  const early = status(parsed({issued: (NOW.getTime() + 10 * 60_000) / 1000}));
  assert.equal(early.note, 'run ahead of the clock · Oct 9, 11 am');
  assert.equal(early.reason, 'Swell unavailable: the NOAA GFS-Wave run of Oct 9, 11 am is dated more than 5 minutes ahead of this device\'s clock, so its age cannot be checked.');
  const fetchedAhead = status(parsed({retrieved: NOW.getTime() + 10 * 60_000}));
  assert.equal(fetchedAhead.note, 'forecast ahead of the clock · run Oct 8, 11 pm');
  assert.equal(fetchedAhead.reason, 'Swell unavailable: the regional forecast\'s retrieval is dated more than 5 minutes ahead of this device\'s clock, so its age cannot be checked.');
  const sparse = status(parsed({hours: times.filter((_, k) => k % 6 === 0)}));
  assert.equal(sparse.note, 'no forecast hour near Fri 1 pm');
  assert.equal(sparse.reason, 'Swell unavailable: the NOAA GFS-Wave run of Oct 8, 11 pm lists no hour within 90 minutes of Fri Oct 9, 1 pm.');
  for (const s of [early, fetchedAhead, sparse]) assert.equal(s.drawn, null);
  const gone = status(parsed({values: () => [null, 12, 290]}));
  assert.equal(gone.note, 'no complete grid cell · valid Fri 1 pm');
  assert.match(gone.reason, /missing samples stay blank\.$/);
  for (const s of [old, late, gone]) assert.equal(s.drawn, null);
});

test('the field covers complete grid cells only; a missing sample leaves its cells blank', () => {
  const s = status(), f = s.drawn;
  assert.equal(s.note, 'valid Fri 1 pm · run 12 h old');
  assert.equal(f.stamp, 'run Oct 8, 11 pm · 12 h old · valid Fri Oct 9, 1 pm');
  assert.deepEqual(f.field.bounds, [-121.75, 35.05, -121.25, 35.55]);
  assert.equal(f.field.quads.length, 4);
  const k = kOf(AT.getTime());
  assert.deepEqual(f.height.map(h => +h.toFixed(6)), [2 + k * 0.5, +(2 + 1 + 0.6 + k * 0.5).toFixed(6)]);
  assert.deepEqual(f.period.map(p => +p.toFixed(6)), [11.2, 13.6]);
  assert.equal(Math.round(f.from), 295, 'directions blend as unit vectors');
  assert.equal(frameSummary(f), '9.0–10.6 ft · 11.2–13.6 s · from WNW');
  assert.match(s.basis, /^NOAA GFS-Wave \(0\.16°\) model forecast of the primary swell, sampled on the region's 0\.25° forecast grid; run of Oct 8, 11 pm \(12 h old\), valid Fri Oct 9, 1 pm\. A model forecast, not a buoy observation\./);
  assert.ok(f.field.sample(-121.6, 35.4) && !f.field.sample(-121.0, 35.4), 'nothing past the grid: the inshore points are not in it');
  // The south-east corner's sample is missing: its one cell goes, the other three stay.
  const holed = status(parsed({values: (i, j, kk) => (i === 2 && j === 0 ? [null, 12, 290] : [2 + kk * 0.5, 12, 290])})).drawn;
  assert.equal(holed.field.quads.length, 3);
  assert.equal(holed.field.sample(-121.3, 35.1), null);
  assert.equal(swellMark(holed, {lon: -121.3, lat: 35.1}, NOW, TZ), null, 'a click in the hole reads nothing');
  const mark = swellMark(f, {lon: -121.75, lat: 35.05}, NOW, TZ);
  assert.deepEqual([mark.name, mark.kind, mark.reading, mark.source], ['Primary swell', 'Model forecast · valid Fri Oct 9, 1 pm', '9.0 ft · 11.2 s · from WNW 290°',
    'NOAA GFS-Wave · run Oct 8, 11 pm · 12 h old · valid Fri Oct 9, 1 pm']);
  assert.match(mark.basis, /Display interpolation between adjacent grid samples, which adds no measurements\.$/);
});

test('period isolines run at whole seconds with the unit; strokes point the way the swell travels, never where corners disagree', () => {
  const f = status().drawn, lines = periodLines(f);
  assert.deepEqual([...new Set(lines.features.map(l => l.properties.label))].sort(), ['12 s', '13 s']);
  for (const line of lines.features) for (const [lon] of line.geometry.coordinates) assert.ok(lon > -121.75 && lon < -121.25);
  assert.equal(periodLines(status(parsed({values: () => [3, 12.2, 290]})).drawn).features.length, 0, 'no whole second inside the range');

  const strokes = directionStrokes(f);
  assert.equal(strokes.features.length, 4 * 4 * 2, 'one stroke every half grid step, as a tail and a head');
  const [tail, head] = strokes.features;
  assert.deepEqual([tail.properties.part, head.properties.part], ['tail', 'head']);
  assert.deepEqual(tail.geometry.coordinates[1], head.geometry.coordinates[0], 'the head continues the tail');
  const [[x0, y0]] = tail.geometry.coordinates, [, [x1, y1]] = head.geometry.coordinates;
  const toward = (Math.atan2((x1 - x0) * Math.cos(35.1 * Math.PI / 180) * 111.32, (y1 - y0) * 110.57) * 180 / Math.PI + 360) % 360;
  assert.ok(Math.abs(toward - (290 + 180 - 360 + 1.25)) < 1, `travels toward the east-south-east (${toward})`);
  // From the west at the south-west corner, from the east elsewhere: the stroke nearest that corner blends to almost nothing.
  const crossed = status(parsed({values: (i, j, kk) => [3 + kk * 0.1, 12, i === 0 && j === 0 ? 270 : 90]})).drawn;
  assert.equal(directionStrokes(crossed).features.length, (4 * 4 - 1) * 2, 'no stroke where the corners\' directions cancel');
  const mixed = status(parsed({values: (i, j, kk) => [3 + kk * 0.1, 12, (i + j) % 2 ? 90 : 270]})).drawn;
  assert.equal(frameSummary(mixed), '4.4 ft · 12.0 s · direction mixed');
});

test('the texture is height on the --swell-* ramp over a fixed 0–15 ft scale, a sequential ramp in every theme', async () => {
  const css = await readFile(new URL('../web/tokens.css', import.meta.url), 'utf8');
  for (const [theme, colours] of Object.entries(themes(css, FILES['web/tokens.css']))) {
    const swell = ramps(readPalette(name => colours[name] ?? '0')).swell;
    assert.equal(swell.length, 4, theme);
    for (let i = 1; i < swell.length; i++) assert.ok(luminance(swell[i]) > luminance(swell[i - 1]), `${theme}: --swell-${i} is lighter than --swell-${i - 1}`);
  }
  const o = swellOverlay(sentinel);
  assert.deepEqual(o.layers.map(l => l.id), [SWELL_LAYER, ISOLINE_LAYER, ISOLINE_LABELS, STROKE_CASING, STROKE_LAYER], 'the texture, the isolines and the strokes only');
  assert.deepEqual(Object.keys(o.sources), [SWELL_SOURCE, ISOLINE_SOURCE, STROKE_SOURCE]);
  assert.equal(o.sources[SWELL_SOURCE].type, 'image');
  assert.equal(o.sources[SWELL_SOURCE].url, undefined, 'no request: the pixels come from setImage');
  for (const l of o.layers) for (const [k, v] of Object.entries(l.paint ?? {})) if (k.endsWith('-color')) assert.match(v, /^token\(/, `${l.id} ${k}`);
  assert.deepEqual(HEIGHT_SCALE, [0, 15]);
  // A uniform 6 ft field paints 6/15 of the way along the ramp, at every hour.
  const flat = status(parsed({values: () => [6, 12, 290]})).drawn, ramp = ['#000000', '#555555', '#aaaaaa', '#ffffff'];
  const {fieldTexture} = await import('../web/map/field.ts');
  const tex = fieldTexture(flat.field, HEIGHT_SCALE, ramp, v => v[0]);
  const mid = (Math.floor(tex.height / 2) * tex.width + Math.floor(tex.width / 2)) * 4;
  assert.deepEqual([...tex.data.subarray(mid, mid + 3)], fieldColor(6, 0, 15, ramp));
});

/** A browser just big enough for navigate() (as tests/test_field_texture.mjs). */
function browser(href) {
  globalThis.location = {href};
  globalThis.history = {state: null, pushState(_s, _t, url) { location.href = url; }, replaceState(_s, _t, url) { location.href = url; }};
  globalThis.dispatchEvent = () => true;
  configureStore({v2: true, storage: null});
  syncFromURL(href);
}
/** An engine that records what the layer drew, in order. */
function engine() {
  const e = {overlay: null, before: null, calls: [], images: [], data: []};
  return Object.assign(e, {
    setOverlay(layer, overlay, before) { assert.equal(layer, 'swell'); e.overlay = overlay; e.before = before; e.calls.push(['overlay', overlay && overlay.layers.map(l => l.id)]); },
    setImage(id, texture) { e.images.push([id, texture]); e.calls.push(['image', id]); },
    setData(id, data) { e.data.push([id, data]); e.calls.push(['data', id]); },
    setRasterOpacity() {}, setCamera() {}, setVisible() {}, destroy() {},
  });
}
const flush = () => new Promise(resolve => setImmediate(resolve));
/** Hex colours, so textures differ by height: black to white for the swell ramp. */
const grey = readPalette(name => ({'swell-0': '#000000', 'swell-1': '#555555', 'swell-2': '#aaaaaa', 'swell-3': '#ffffff'})[name] ?? '#123456');
async function layer(t, {href = `${PAGE}?region=morro-bay&layers=swell&hour=${AT_PARAM}`, body = feed(), palette = sentinel} = {}) {
  t.mock.timers.enable({apis: ['setTimeout']});
  browser(href);
  const e = engine(), asked = [];
  const fetchFn = async url => { asked.push(url); return {ok: true, json: async () => body}; };
  const s = createSwell({engine: signal(e), zone: () => TZ, fetchFn, page: () => PAGE, palette: () => palette, now: () => NOW});
  t.after(() => s.destroy());
  await flush();
  return {s, e, asked};
}

test('toggling Swell adds the texture, isolines and strokes only; off removes them; the feed is read only while it is on', async t => {
  const {s, e, asked} = await layer(t, {href: `${PAGE}?region=morro-bay&layers=none&hour=${AT_PARAM}`});
  assert.deepEqual(asked, [], 'nothing is read while Swell is off');
  assert.deepEqual(e.calls, [['overlay', null]], 'nothing is drawn');
  e.calls.length = 0;
  setParams({layers: 'swell'});
  await flush();
  assert.deepEqual(asked, ['https://s.test/api/forecast?region=morro-bay']);
  assert.deepEqual(e.calls, [['overlay', [SWELL_LAYER, ISOLINE_LAYER, ISOLINE_LABELS, STROKE_CASING, STROKE_LAYER]], ['image', SWELL_SOURCE], ['data', ISOLINE_SOURCE], ['data', STROKE_SOURCE]]);
  assert.equal(e.before, MPA_FILL, 'under the protected areas (§ 9 order)');
  assert.equal(railNotes.value.swell, 'valid Fri 1 pm · run 12 h old');
  assert.equal(swellState.value.drawn.field.quads.length, 4);
  chartMark.value = s.reading({lon: -121.5, lat: 35.3});
  assert.equal(chartMark.value.name, 'Primary swell');
  setParams({layers: 'none'});
  assert.equal(e.overlay, null, 'off removes the texture, isolines and strokes');
  assert.equal(chartMark.value, null, 'and a reading of them');
  assert.equal(railNotes.value.swell, '');
  assert.equal(s.reading({lon: -121.5, lat: 35.3}), null);
});

test('an hour change replaces the texture, isolines and strokes in the same turn, before the next frame', async t => {
  const {e} = await layer(t, {palette: grey});
  const first = e.images.at(-1)[1], key = swellState.value.drawn.key;
  e.calls.length = 0;
  setParams({hour: '2026-10-09T23:00Z'});
  // Synchronous: no await between the hour and the new pixels, so MapLibre's next frame draws them.
  assert.deepEqual(e.calls, [['overlay', [SWELL_LAYER, ISOLINE_LAYER, ISOLINE_LABELS, STROKE_CASING, STROKE_LAYER]], ['image', SWELL_SOURCE], ['data', ISOLINE_SOURCE], ['data', STROKE_SOURCE]]);
  assert.notEqual(swellState.value.drawn.key, key);
  assert.notDeepEqual(e.images.at(-1)[1].data, first.data, 'three hours later the swell is 1.5 ft higher: new pixels');
  assert.equal(swellState.value.note, 'valid Fri 4 pm · run 12 h old');
  e.calls.length = 0;
  setParams({hour: '2026-10-12T23:00Z'});
  assert.deepEqual(e.calls, [['overlay', null]], 'an hour past the run removes the field at once');
});

test('a failed refresh keeps the last good run; a region change withdraws the field at once', async t => {
  t.mock.timers.enable({apis: ['setTimeout']});
  browser(`${PAGE}?region=morro-bay&layers=swell&hour=${AT_PARAM}`);
  let clock = NOW.getTime(), fail = false;
  const e = engine(), asked = [];
  const fetchFn = async url => { asked.push(url); return fail ? {ok: false, json: async () => ({})} : {ok: true, json: async () => feed()}; };
  const s = createSwell({engine: signal(e), zone: () => TZ, fetchFn, page: () => PAGE, palette: () => sentinel, now: () => new Date(clock)});
  t.after(() => s.destroy());
  await flush();
  assert.equal(asked.length, 1);
  assert.equal(e.images.length, 1);
  fail = true; clock += 30 * 60_000;
  t.mock.timers.tick(31 * 60_000);
  await flush();
  assert.equal(asked.length, 2, 'read again after 30 minutes');
  assert.ok(swellState.value.drawn, 'the last good run still draws');
  assert.equal(e.images.length, 1, 'and is not repainted');
  setParams({region: 'santa-cruz-monterey-bay'});
  assert.equal(e.overlay, null, 'the field goes with the region, before its feed answers');
  await flush();
  assert.equal(swellState.value.reason, 'Swell unavailable: the regional wave forecast failed to load.');
  fail = false;
  setParams({region: 'morro-bay'});
  await flush();
  assert.ok(e.overlay, 'back in Morro Bay, its feed draws again');
  assert.equal(e.images.length, 2);
});

test('in the stack the water temperature sits under the swell field, whichever is drawn first', () => {
  const maps = [];
  class FakeMap {
    constructor(options) { this.handlers = {}; this.sources = {}; this.layers = options.style.layers.map(l => l.id); this.keyboard = this.touchZoomRotate = {disableRotation() {}}; maps.push(this); }
    on(type, fn) { (this.handlers[type] ??= []).push(fn); }
    fire(type) { for (const fn of this.handlers[type] ?? []) fn({}); }
    addControl() {}
    getLayer(id) { return this.layers.includes(id) ? {} : undefined; }
    getSource(id) { return this.sources[id]; }
    addSource(id, spec) { this.sources[id] = {spec, updateImage() {}, setData() {}}; }
    removeSource(id) { delete this.sources[id]; }
    addLayer(l, before) { const i = before ? this.layers.indexOf(before) : -1; this.layers.splice(i < 0 ? this.layers.length : i, 0, l.id); }
    removeLayer(id) { this.layers = this.layers.filter(l => l !== id); }
    remove() {}
  }
  const control = class {}, module = {lib: {Map: FakeMap, NavigationControl: control, ScaleControl: control, AttributionControl: control, setWorkerUrl() {}, addProtocol() {}},
    workerUrl: '/w.js', Protocol: class { constructor() { this.tile = () => {}; } }};
  const swellIds = [SWELL_LAYER, ISOLINE_LAYER, ISOLINE_LABELS, STROKE_CASING, STROKE_LAYER], sstIds = [SST_LAYER, CONTOUR_LAYER, CONTOUR_LABELS];
  for (const order of [['sst', 'swell'], ['swell', 'sst']]) {
    const eng = createEngine(module, {host: {}, style: {version: 8, sources: {}, layers: [{id: 'water'}, {id: MPA_FILL}, {id: 'coastline'}]},
      camera: {latitude: 35.3, longitude: -120.9, zoom: 10}, onMove() {}, onLayerError() {}});
    const map = maps.at(-1);
    map.fire('style.load');
    for (const which of order) {
      if (which === 'sst') eng.setOverlay('water-temp', waterTempOverlay(sentinel), [SWELL_LAYER, MPA_FILL]);
      else eng.setOverlay('swell', swellOverlay(sentinel), MPA_FILL);
    }
    assert.deepEqual(map.layers, ['water', ...sstIds, ...swellIds, MPA_FILL, 'coastline'], order.join(' then '));
    eng.setOverlay('swell', null);
    assert.deepEqual(map.layers, ['water', ...sstIds, MPA_FILL, 'coastline']);
  }
});

test('the legend gives the hour\'s reading, the fixed scale and the model run as a model forecast; the rail gives the valid hour', async () => {
  const out = join(await mkdtemp(join(tmpdir(), 'swell-')), 'legend.mjs');
  await build({
    stdin: {resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts', contents: `
      export {Legend} from './web/app/Legend.tsx';
      export {LayerRail} from './web/app/LayerRail.tsx';
      export {swellState} from './web/map/swell.ts';
      export {railNotes} from './web/map/layers.ts';
      export * as state from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: rendererPlugins,
  });
  const m = await import(pathToFileURL(out).href);
  m.state.configureStore({v2: true, storage: null});
  m.state.syncFromURL(`${PAGE}?region=morro-bay&layers=swell`);
  m.swellState.value = status();
  m.railNotes.value = {swell: 'valid Fri 1 pm · run 12 h old'};
  const legend = m.render(m.h(m.Legend));
  assert.match(legend, /data-layer="swell" aria-hidden="true"><\/span>Swell<details/);
  assert.match(legend, /<p class="app-legend-note app-legend-range ui-mono" data-range="swell">9\.0–10\.6 ft · 11\.2–13\.6 s · from WNW<\/p>/);
  assert.match(legend, /data-scale="swell">0 ft<span class="app-swatch" data-layer="swell" aria-hidden="true"><\/span><span class="app-visually-hidden"> to <\/span>15\+ ft</);
  assert.match(legend, /data-stamp="swell">NOAA GFS-Wave model forecast · run Oct 8, 11 pm · 12 h old · valid Fri Oct 9, 1 pm</);
  assert.match(legend, /A model forecast, not a buoy observation\./);
  assert.match(m.render(m.h(m.LayerRail)), /Swell<\/span><span class="ui-rail-note ui-mono">valid Fri 1 pm · run 12 h old<\/span>/);
  m.swellState.value = swellStatus(true, {state: 'error', region: 'morro-bay', forecast: null, at: 0}, AT, NOW, TZ);
  const none = m.render(m.h(m.Legend));
  assert.doesNotMatch(none, /data-range="swell"|data-stamp="swell"/);
  assert.match(none, /data-reason="swell">Swell unavailable: the regional wave forecast failed to load\.</);
});
