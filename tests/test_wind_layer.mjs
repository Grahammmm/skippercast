// Synthetic tile-derived feed only; no network or GPU.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import {signal} from '@preact/signals';
import {parseForecast} from '../web/map/forecast-grid.ts';
import {createWind, windGeometry, windOverlay, windPoints, windState, windStatus, WIND_MODEL} from '../web/map/wind.ts';
import {layerEntry, railLayers, sourceLayer} from '../web/map/layers.ts';
import {readPalette} from '../web/map/palette.ts';
import {configureStore, setParams, syncFromURL} from '../web/state.ts';

const H = 3600000, NOW = new Date('2026-10-20T12:00:00Z'), TZ = 'UTC';
const issued = NOW.getTime() - 12 * H;
const times = Array.from({length: 49}, (_, i) => issued / 1000 + i * 3600);
const palette = readPalette(() => '#123456');
function feed() {
  return {region_id: 'morro-bay', retrieved: NOW.getTime(), requested_points: [['a', 35, -122], ['b', 35, -121.75], ['c', 35.25, -122], ['d', 35.25, -121.75]],
    models: {[WIND_MODEL]: {meta: {last_run_initialisation_time: issued / 1000, data_end_time: times.at(-1)},
      data: Array.from({length: 4}, () => ({utc_offset_seconds: 0, hourly_units: {time: 'unixtime', wind_speed_10m: 'kn', wind_direction_10m: '°'},
        hourly: {time: [...times], wind_speed_10m: times.map((_, i) => i), wind_direction_10m: times.map(() => 0)}}))}}};
}
const parse = f => parseForecast(f, 'morro-bay', WIND_MODEL);
const status = (f = feed(), at = NOW, now = NOW) => windStatus(true, parse(f), at, now, TZ);

test('GFS only, dock hour selection, model/grid/run/age basis and knot labels', () => {
  const s = status();
  assert.equal(s.drawn.validAt, NOW.getTime());
  assert.equal(s.drawn.points[0].knots, 12);
  assert.equal(status(feed(), new Date(NOW.getTime() + H)).drawn.points[0].knots, 13);
  assert.match(s.basis, /NOAA GFS.*13 km/);
  assert.match(s.basis, /0.25° × 0.25°; run Oct 20, 12 am · 12 h old/);
  assert.equal(windGeometry(s.drawn).labels.features[0].properties.label, '12 kt');
  const f = feed(); f.models.ecmwf_ifs025 = f.models[WIND_MODEL]; delete f.models[WIND_MODEL];
  assert.equal(status(f).drawn, null, 'no fallback model');
  assert.equal(parseForecast(feed(), 'other', WIND_MODEL), null);
});

test('wind uses the existing forecast age and hour gate, including the exact age boundary', () => {
  let f = feed(); f.models[WIND_MODEL].meta.last_run_initialisation_time = (NOW.getTime() - 36 * H) / 1000;
  assert.ok(status(f).drawn);
  f.models[WIND_MODEL].meta.last_run_initialisation_time -= 1;
  assert.equal(status(f).drawn, null); assert.match(status(f).reason, /36-hour/);
  f = feed(); f.retrieved -= 6 * H;
  assert.ok(status(f).drawn); f.retrieved -= 1;
  assert.equal(status(f).drawn, null); assert.match(status(f).reason, /6-hour/);
  f = feed(); f.retrieved += 6 * 60000;
  assert.match(status(f).reason, /ahead/);
  assert.equal(status(feed(), new Date(issued - H)).drawn, null);
  assert.equal(status(feed(), new Date(issued + 49 * H)).drawn, null);
  f = feed(); f.models[WIND_MODEL].data.forEach(d => {
    d.hourly.time = [times[0], times[6]]; d.hourly.wind_speed_10m = [1, 2]; d.hourly.wind_direction_10m = [0, 0];
  });
  assert.equal(status(f, new Date(issued + 3 * H)).drawn, null);
  assert.equal(status(f, new Date(issued + H)).drawn.validAt, issued);
});

test('wrong units, missing, invalid and duplicate samples stay blank; calm has no arrow', () => {
  for (const value of [null, -1, NaN, '12']) {
    const f = feed(); f.models[WIND_MODEL].data.forEach(d => { d.hourly.wind_speed_10m[12] = value; });
    assert.equal(status(f).drawn, null);
  }
  const f = feed(); f.models[WIND_MODEL].data[0].hourly_units.wind_speed_10m = 'm/s';
  f.models[WIND_MODEL].data[1].hourly.wind_direction_10m[12] = 361;
  f.models[WIND_MODEL].data[2].hourly.time[13] = times[12];
  assert.equal(windPoints(parse(f), times[12]).length, 1);
  const calm = status(feed(), new Date(issued)).drawn;
  assert.equal(windGeometry(calm).arrows.features.length, 0);
  assert.equal(windGeometry(calm).labels.features[0].properties.label, '0 kt');
});

test('north wind arrows point south, labels carry units, registry shares Swell', () => {
  const g = windGeometry(status().drawn);
  const [tail, head] = g.arrows.features[0].geometry.coordinates[0];
  assert.ok(head[1] < tail[1]); assert.ok(Math.abs(head[0] - tail[0]) < 1e-6);
  assert.deepEqual(layerEntry('wind').time, ['hour']);
  assert.equal(sourceLayer('wind-arrows'), 'wind');
  assert.ok(railLayers('swell').some(e => e.id === 'wind'));
  assert.equal(windOverlay(palette).sources['wind-arrows'].attribution, 'NOAA NCEP');
});

const flush = () => new Promise(resolve => setImmediate(resolve));
function browser() {
  const href = 'https://s.test/map?region=morro-bay&layers=swell&hour=2026-10-20T12:00Z';
  globalThis.location = {href};
  globalThis.history = {state: null, pushState(_s, _t, url) { location.href = url; }, replaceState(_s, _t, url) { location.href = url; }};
  globalThis.dispatchEvent = () => true;
  configureStore({v2: true, storage: null}); syncFromURL(href);
}

test('live layer replaces hour, expires without interaction, hides on region/off and destroys', async t => {
  t.mock.timers.enable({apis: ['setTimeout']}); browser();
  let clock = NOW.getTime(), fail = false;
  const e = {overlay: null, data: {}, before: null, setOverlay(id, value, before) { assert.equal(id, 'wind'); this.overlay = value; this.before = before; }, setData(id, value) { this.data[id] = value; }};
  const engine = signal(e);
  const s = createWind({engine, zone: () => TZ, page: () => location.href, palette: () => palette, now: () => new Date(clock),
    fetchFn: async () => ({ok: !fail, json: async () => feed()})});
  t.after(() => s.destroy()); await flush();
  assert.deepEqual(e.before, ['depth-contours-edge', 'mpa-fill'], 'wind inserts below depth contours, else MPAs');
  assert.equal(e.data['wind-labels'].features[0].properties.label, '12 kt');
  engine.value = null; assert.equal(e.overlay, null);
  engine.value = e; assert.ok(e.overlay, 'same engine remount restores the frame');
  setParams({hour: '2026-10-20T13:00Z'});
  assert.equal(e.data['wind-labels'].features[0].properties.label, '13 kt');
  fail = true; clock += 6 * H + 1000; t.mock.timers.tick(6 * H + 1000); await flush();
  assert.equal(e.overlay, null); assert.match(windState.value.reason, /6-hour/);
  clock = NOW.getTime(); fail = false;
  setParams({region: 'cambria-san-simeon'}); assert.equal(e.overlay, null); await flush();
  setParams({region: 'morro-bay'}); await flush(); assert.ok(e.overlay);
  setParams({layers: 'none'}); assert.equal(e.overlay, null);
  setParams({layers: 'swell'}); assert.ok(e.overlay);
  s.destroy(); assert.equal(e.overlay, null); assert.equal(windState.value.drawn, null);
});

test('shared rail legend renders wind basis and valid time, replacing the time with a stale reason', async () => {
  const out = join(await mkdtemp(join(tmpdir(), 'wind-legend-')), 'legend.mjs');
  await build({stdin: {resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts', contents: `
    export {Legend} from './web/app/Legend.tsx';
    export {windState} from './web/map/wind.ts';
    export * as state from './web/state.ts';
    export {h} from 'preact';
    export {default as render} from 'preact-render-to-string';
  `}, outfile: out, bundle: true, platform: 'node', format: 'esm', plugins: rendererPlugins, logLevel: 'silent'});
  const m = await import(pathToFileURL(out).href);
  m.state.configureStore({v2: true, storage: null});
  m.state.syncFromURL('https://s.test/map?region=morro-bay&layers=swell&presentation=chart');
  m.windState.value = status();
  const html = m.render(m.h(m.Legend));
  assert.match(html, /Wind · arrows toward · knots/);
  assert.match(html, /Wind basis/);
  assert.match(html, /data-stamp="wind"/);
  assert.match(html, /0.25° × 0.25°/);
  assert.match(html, /NOAA GFS 10 m wind/);
  const stale = feed(); stale.retrieved -= 7 * H;
  m.windState.value = status(stale);
  const held = m.render(m.h(m.Legend));
  assert.doesNotMatch(held, /data-stamp="wind"/);
  assert.match(held, /data-reason="wind".*6-hour age limit/);
});
