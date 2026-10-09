// Nearshore wave rings (FE-27, docs/plans/front-end/dev-plan.md): the bound coast
// report's nearshore model sites through packages/coast freshNearshore and
// nearshoreAt (web/map/nearshore-model.js), drawn as rings by the Swell layer
// (web/map/swell.ts) over a fake engine. Reports and feeds are synthetic: two
// CDIP MOP-shaped sites in the SLO "central" area. Files run by type stripping;
// the legend is bundled with esbuild and rendered.
import assert from 'node:assert/strict';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {pathToFileURL} from 'node:url';
import {signal} from '@preact/signals';
import {build} from 'esbuild';
import {chartMark} from '../web/map/chart.ts';
import {createEngine} from '../web/map/engine.ts';
import {MPA_FILL} from '../web/map/mpa.ts';
import {NEARSHORE_LAYER, NEARSHORE_SOURCE, nearshoreRings, ringMark, ringRadius, ringSummary} from '../web/map/nearshore.ts';
import {readPalette} from '../web/map/palette.ts';
import {ISOLINE_LABELS, ISOLINE_LAYER, ISOLINE_SOURCE, STROKE_CASING, STROKE_LAYER, STROKE_SOURCE, SWELL_LAYER, SWELL_SOURCE, createSwell, nearshoreState, swellOverlay} from '../web/map/swell.ts';
import {configureStore, setParams, syncFromURL} from '../web/state.ts';

const PAGE = 'https://s.test/map', TZ = 'America/Los_Angeles', HOUR = 3_600_000, MIN = 60_000;
const NOW = new Date('2026-10-09T18:00:00Z'), AT = new Date('2026-10-09T20:00:00Z'), AT_PARAM = '2026-10-09T20:00Z';
const sentinel = readPalette(name => `token(${name})`);
const iso = ms => new Date(ms).toISOString();
const FIELD = [SWELL_LAYER, ISOLINE_LAYER, ISOLINE_LABELS, STROKE_CASING, STROKE_LAYER];

/** A site sampled hourly from 12:00Z for 24 hours, 3 ft rising 0.1 ft an hour, issued 6 h and fetched 1 h before NOW. */
function site(patch = {}, {every = 1, height = k => 3 + k * 0.1} = {}) {
  const first = Date.parse('2026-10-09T12:00:00Z');
  return {id: 'SL345', name: 'Morro Rock', areaId: 'central', lat: 35.36503, lon: -120.87659, sourceId: 'cdip-mop',
    issuedAt: iso(NOW - 6 * HOUR), fetchedAt: iso(NOW - HOUR), url: 'https://example.test/cdip', kind: 'forecast', availability: 'available', freshness: 'current',
    temporalResolutionMinutes: 60 * every, waterDepthM: 15, depthDatum: 'MSL', directionConvention: 'from degrees true', modelInputCycleAt: null, validThrough: null,
    hours: Array.from({length: Math.floor(24 / every) + 1}, (_, i) => ({at: iso(first + i * every * HOUR), waveFt: height(i * every), periodS: 13, directionDeg: 290, qualityFlag: 0, secondaryFlag: 0})), ...patch};
}
const CDIP = {id: 'cdip-mop', label: 'CDIP MOP · nearshore wave model', url: 'https://example.test/cdip', kind: 'forecast', outcome: 'ok', fetchedAt: iso(NOW - HOUR)};
const report = (sites = [site(), site({id: 'SL400', name: 'Cayucos Pier', lat: 35.4458, lon: -120.9})]) => ({schemaVersion: 1, countyId: 'slo', generatedAt: iso(NOW - HOUR),
  forecasts: [], observations: [], tides: [], tideEvents: [], alerts: [], sources: [CDIP], catches: [], catchStatus: '', habitatStatus: '',
  visibility: {status: 'unknown', feet: null, observedAt: null, sourceUrl: null}, nearshore: sites});
const ringsOf = (sites, at = AT, now = NOW) => nearshoreRings(report(sites), 'central', at, now);

test('a ring draws only inside its site\'s freshness window and sample window', () => {
  const drawn = (patch, options, at, now) => ringsOf([site(patch, options)], at, now)?.rings.length ?? 0;
  assert.equal(drawn(), 1, 'fresh: issued 6 h ago, fetched 1 h ago, a sample at the hour');
  assert.equal(drawn({issuedAt: iso(NOW - 48 * HOUR + MIN)}), 1, 'issued just under 48 h ago');
  assert.equal(drawn({issuedAt: iso(NOW - 48 * HOUR)}), 0, 'issued 48 h ago');
  assert.equal(drawn({issuedAt: iso(NOW.getTime() + 6 * MIN)}), 0, 'issued over 5 min ahead');
  assert.equal(drawn({issuedAt: null}), 0, 'no issue time');
  assert.equal(drawn({fetchedAt: iso(NOW - 3 * HOUR + MIN)}), 1, 'fetched just under 3 h ago');
  assert.equal(drawn({fetchedAt: iso(NOW - 3 * HOUR)}), 0, 'fetched 3 h ago');
  assert.equal(drawn({availability: 'error'}), 0);
  assert.equal(drawn({freshness: 'stale'}), 0);
  assert.equal(drawn({areaId: 'south'}), 0, 'another area');
  assert.equal(drawn({}, {}, new Date('2026-10-10T13:00:00Z')), 0, 'after the site\'s last sample');
  assert.equal(drawn({validThrough: '2026-10-09T19:00:00Z'}), 0, 'past its declared validity');
  assert.equal(drawn({}, {every: 6}, new Date('2026-10-09T15:00:00Z')), 0, 'no sample within 90 minutes');
  assert.equal(drawn({}, {height: () => null}), 0, 'a sample without a height');
  // The same fresh site leaves once the clock passes its window.
  assert.equal(drawn({}, {}, AT, new Date(NOW.getTime() + 2 * HOUR + MIN)), 0, 'its retrieval passed 3 hours while drawn');
  assert.equal(nearshoreRings(null, 'central', AT, NOW), null, 'no bound report');
  assert.equal(nearshoreRings(report(), null, AT, NOW), null, 'no binding');
});

test('rings are sized by height on the stated scale; the card names the site, the model sample and the run\'s age', () => {
  assert.deepEqual([0, 5, 15, 30, -1].map(ringRadius), [4, 19, 49, 49, 4]);
  const r = ringsOf();
  assert.equal(r.product, 'CDIP MOP');
  assert.deepEqual(r.collection.features.map(f => [f.properties.id, +f.properties.radius.toFixed(6), f.geometry.coordinates]),
    [['SL345', 15.4, [-120.87659, 35.36503]], ['SL400', 15.4, [-120.9, 35.4458]]]);
  assert.equal(ringSummary(r, NOW), '2 nearshore model sites · CDIP MOP · issued 6 h ago · ring 4 px + 3 px per ft');
  const mark = ringMark(r, 'SL345', NOW, TZ);
  assert.deepEqual([mark.id, mark.name, mark.kind, mark.reading], ['nearshore:SL345|2026-10-09T20:00:00.000Z', 'Morro Rock', 'Nearshore model site', '3.8 ft · 13.0 s · from WNW 290°']);
  assert.match(mark.source, /^CDIP MOP · sample Oct 9, 1:00\s?PM PDT · 1h model sampling · issued 6 h ago$/);
  assert.match(mark.basis, /Model output, not a buoy observation and not breakers at a beach\. Ring radius 4 px plus 3 px per foot; 15 ft and above draw alike\. The site is in 15 m of water \(MSL\)\.$/);
  assert.equal(ringMark(r, 'nope', NOW, TZ), null);
});

/** A browser just big enough for navigate(). */
function browser(href) {
  globalThis.location = {href};
  globalThis.history = {state: null, pushState(_s, _t, url) { location.href = url; }, replaceState(_s, _t, url) { location.href = url; }};
  globalThis.dispatchEvent = () => true;
  configureStore({v2: true, storage: null});
  syncFromURL(href);
}
function engine() {
  const e = {overlay: null, calls: []};
  return Object.assign(e, {
    setOverlay(layer, overlay, before) { e.overlay = overlay; e.calls.push(['overlay', overlay && overlay.layers.map(l => l.id), before ?? null]); },
    setImage(id) { e.calls.push(['image', id]); },
    setData(id, data) { e.calls.push(['data', id, id === NEARSHORE_SOURCE ? data.features.map(f => f.properties.id) : undefined]); },
    setRasterOpacity() {}, setCamera() {}, setVisible() {}, destroy() {},
  });
}
/** A forecast feed whose region has no grid (Santa Cruz shape), so only rings can draw. */
const noGrid = {region_id: 'morro-bay', retrieved: NOW - HOUR, requested_points: [['a', 35.4, -121.0], ['b', 35.3, -121.1]], models: {}};
const flush = () => new Promise(resolve => setImmediate(resolve));
async function swell(t, {place = undefined, data = undefined, body = noGrid, href = `${PAGE}?region=morro-bay&layers=swell&hour=${AT_PARAM}`, clock = () => NOW} = {}) {
  try { t.mock.timers.enable({apis: ['setTimeout']}); } catch { /* already on for this test */ }
  browser(href);
  const e = engine(), asked = [];
  const s = createSwell({engine: signal(e), zone: () => TZ, fetchFn: async () => ({ok: true, json: async () => body}), page: () => PAGE, palette: () => sentinel, now: clock,
    ...place ? {place} : {}, ...data ? {data: {...data, setPlace: p => { asked.push(['place', p.regionId]); }, load: async product => { asked.push(['load', product]); }}} : {}});
  t.after(() => s.destroy());
  await flush();
  return {s, e, asked};
}

test('outside a report binding Swell renders exactly as before FE-27', async t => {
  const before = await swell(t);
  const unbound = await swell(t, {place: () => ({regionId: 'santa-cruz-monterey-bay'}), data: {coastReport: signal(null), coastBinding: signal(null)}});
  assert.deepEqual(unbound.e.calls, before.e.calls, 'the same engine calls as without a place');
  assert.equal(unbound.e.calls.some(c => c[0] === 'data' && c[1] === NEARSHORE_SOURCE), false);
  assert.equal(nearshoreState.value, null);
  // A report without a binding area (a stale snapshot, a place that binds none) draws no ring either.
  const stray = await swell(t, {place: () => ({regionId: 'morro-bay'}), data: {coastReport: signal({data: report()}), coastBinding: signal(null)}});
  assert.deepEqual(stray.e.calls, before.e.calls);
  // And with a grid, the field's overlay is FE-17's, with no ring source.
  assert.deepEqual(swellOverlay(sentinel), swellOverlay(sentinel, {field: true, rings: false}));
  assert.deepEqual(Object.keys(swellOverlay(sentinel).sources), [SWELL_SOURCE, ISOLINE_SOURCE, STROKE_SOURCE]);
});

test('in a binding the rings draw above the field, follow the hour, leave with their window and open the card', async t => {
  let clock = NOW.getTime();
  const reportSignal = signal({data: report()}), binding = signal({areaId: 'central', localAreaId: 'morro-bay'});
  const {s, e, asked} = await swell(t, {place: () => ({regionId: 'morro-bay'}), data: {coastReport: reportSignal, coastBinding: binding}, clock: () => new Date(clock)});
  assert.deepEqual(asked, [['place', 'morro-bay'], ['load', 'report']], 'the report is asked for while Swell is on');
  assert.deepEqual(e.calls.at(-2), ['overlay', [NEARSHORE_LAYER], MPA_FILL], 'without a grid, the rings alone');
  assert.deepEqual(e.calls.at(-1), ['data', NEARSHORE_SOURCE, ['SL345', 'SL400']]);
  assert.deepEqual(swellOverlay(sentinel, {rings: true}).layers.map(l => l.id), [...FIELD, NEARSHORE_LAYER], 'with a grid, above the field');
  const ring = swellOverlay(sentinel, {rings: true}).layers.at(-1);
  assert.deepEqual([ring.type, ring.paint['circle-radius'], ring.paint['circle-stroke-color'], ring.paint['circle-opacity']], ['circle', ['get', 'radius'], 'token(blue)', 0]);

  chartMark.value = s.pick.mark(NEARSHORE_LAYER, {id: 'SL400'});
  assert.equal(chartMark.value.name, 'Cayucos Pier');
  assert.equal(s.pick.mark('other', {id: 'SL400'}), null);

  e.calls.length = 0;
  setParams({hour: '2026-10-09T23:00Z'});
  assert.deepEqual(e.calls, [['overlay', [NEARSHORE_LAYER], MPA_FILL], ['data', NEARSHORE_SOURCE, ['SL345', 'SL400']]], 'a new hour, new rings at once');
  assert.equal(nearshoreState.value.rings[0].waveFt.toFixed(1), '4.1');
  assert.equal(chartMark.value, null, 'the card of the previous hour goes');

  // One site's retrieval passes 3 hours: the timer re-judges and its ring goes.
  reportSignal.value = {data: report([site({fetchedAt: iso(NOW - 2 * HOUR)}), site({id: 'SL400', name: 'Cayucos Pier', lat: 35.4458, lon: -120.9})])};
  e.calls.length = 0;
  clock += HOUR + 2 * MIN;
  t.mock.timers.tick(HOUR + 2 * MIN);
  assert.deepEqual(e.calls.at(-1), ['data', NEARSHORE_SOURCE, ['SL400']]);
  binding.value = null;
  assert.deepEqual(e.calls.at(-1), ['overlay', null, null], 'leaving the binding removes the rings');
  setParams({layers: 'none'});
  assert.equal(nearshoreState.value, null);
});

test('a ring is asked before the Chart\'s own pick layers, so it opens over a protected area', () => {
  const maps = [], picks = [];
  class FakeMap {
    constructor(options) { this.handlers = {}; this.layers = options.style.layers.map(l => l.id); this.keyboard = this.touchZoomRotate = {disableRotation() {}}; maps.push(this); }
    on(type, fn) { (this.handlers[type] ??= []).push(fn); }
    fire(type, event = {}) { for (const fn of this.handlers[type] ?? []) fn(event); }
    addControl() {}
    getLayer(id) { return this.layers.includes(id) ? {} : undefined; }
    queryRenderedFeatures(_point, {layers}) { return [MPA_FILL, NEARSHORE_LAYER].filter(id => layers.includes(id)).map(id => ({layer: {id}, properties: {id: `${id}-feature`}})); }
    remove() {}
  }
  const control = class {}, module = {lib: {Map: FakeMap, NavigationControl: control, ScaleControl: control, AttributionControl: control, setWorkerUrl() {}, addProtocol() {}},
    workerUrl: '/w.js', Protocol: class { constructor() { this.tile = () => {}; } }};
  createEngine(module, {host: {}, style: {version: 8, sources: {}, layers: [{id: MPA_FILL}, {id: NEARSHORE_LAYER}]}, camera: {latitude: 35.3, longitude: -120.9, zoom: 10},
    onMove() {}, onLayerError() {}, pickLayers: [MPA_FILL], pickFirst: () => [NEARSHORE_LAYER], onPick: (layer, properties) => picks.push([layer, properties.id])});
  maps[0].fire('click', {point: {x: 1, y: 1}, lngLat: {lng: -120.9, lat: 35.3}});
  maps[0].layers = [MPA_FILL];
  maps[0].fire('click', {point: {x: 1, y: 1}, lngLat: {lng: -120.9, lat: 35.3}});
  assert.deepEqual(picks, [[NEARSHORE_LAYER, `${NEARSHORE_LAYER}-feature`], [MPA_FILL, `${MPA_FILL}-feature`]]);
});

test('the legend names the rings\' model, run age and scale, and its basis says what they are not', async () => {
  const out = join(await mkdtemp(join(tmpdir(), 'nearshore-')), 'legend.mjs');
  await build({
    stdin: {resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts', contents: `
      export {Legend} from './web/app/Legend.tsx';
      export {swellState, nearshoreState} from './web/map/swell.ts';
      export {nearshoreRings} from './web/map/nearshore.ts';
      export * as state from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: [{name: 'renderers', setup: b => b.onResolve({filter: /^\.\/(?:terrain|maplibre)\.js$/}, args => ({path: args.path, external: true}))}],
  });
  const m = await import(pathToFileURL(out).href);
  m.state.configureStore({v2: true, storage: null});
  m.state.syncFromURL(`${PAGE}?region=morro-bay&layers=swell`);
  const plain = m.render(m.h(m.Legend));
  assert.doesNotMatch(plain, /data-nearshore/);
  m.nearshoreState.value = m.nearshoreRings(report(), 'central', AT, NOW);
  const legend = m.render(m.h(m.Legend));
  assert.match(legend, /data-nearshore="swell"><span class="app-ring" aria-hidden="true"><\/span>2 nearshore model sites · CDIP MOP · issued \d+ h ago · ring 4 px \+ 3 px per ft</);
  assert.match(legend, /CDIP MOP nearshore model sites from the bound coast report: modelled significant wave height .* Model output, not a buoy observation and not breakers at a beach\./);
});
