// SP-17-v1 / SP1711-AIS-SCALE-REFRESH: complete production modules, synthetic inputs only.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test, {after, mock} from 'node:test';
import http from 'node:http';
import https from 'node:https';
import net from 'node:net';
import tls from 'node:tls';

// Install guards BEFORE the product dependency closure is evaluated. Each test file
// is isolated by node --test; restore all mocks at that process's suite teardown.
const forbidden = () => { throw new Error('SP1711 offline boundary: external network/model/live store'); };
mock.method(globalThis, 'fetch', forbidden);
for (const module of [http, https]) for (const key of ['request', 'get']) mock.method(module, key, forbidden);
for (const key of ['connect', 'createConnection']) mock.method(net, key, forbidden);
mock.method(net.Socket.prototype, 'connect', forbidden);
mock.method(tls, 'connect', forbidden);
for (const key of ['WebSocket', 'XMLHttpRequest', 'localStorage', 'indexedDB']) {
  const original = Object.getOwnPropertyDescriptor(globalThis, key);
  Object.defineProperty(globalThis, key, {configurable: true, get: forbidden});
  after(() => { if (original) Object.defineProperty(globalThis, key, original); else delete globalThis[key]; });
}
after(() => mock.restoreAll());

const {signal, batch} = await import('@preact/signals');
const {createCommercialAis, aisOn, aisState, AIS_SOURCE, AIS_HEAT, AIS_LINE} = await import('../web/map/commercial-ais.ts');
const {createEngine} = await import('../web/map/engine.ts');
const {markData, markScreen, MARK_PICK} = await import('../web/map/marks.ts');
const {layers, region} = await import('../web/state.ts');
const {readPalette} = await import('../web/map/palette.ts');
const {layerEntry} = await import('../web/map/layers.ts');
const FIXTURE = JSON.parse(readFileSync(new URL('./fixtures/sp1711_ais_scale_refresh/cells.json', import.meta.url), 'utf8'));
const PALETTE = readPalette(name => `token(${name})`);
const PAGE = 'https://example.invalid/map';
const PATH = 'synthetic/cells.geojson';
const BEFORE = ['fleet-heat', 'fleet-tracks', 'fleet-tracks-dashed', 'fleet-events', MARK_PICK];
const READY = {status: 'ready', note: '', source: 'Synthetic ready screen', boundaries: [], until: Infinity};
const flush = async () => { await new Promise(resolve => setImmediate(resolve)); await new Promise(resolve => setImmediate(resolve)); };
const box = (x, y, radius) => ({type: 'Polygon', coordinates: [[[x-radius,y-radius],[x+radius,y-radius],[x+radius,y+radius],[x-radius,y+radius],[x-radius,y-radius]]]});
const exclude = geometry => ({...READY, boundaries: [{name: 'Synthetic exclusion', federal: false, geometry}]});

// Only the MapLibre surface is doubled. Actual createEngine owns overlay
// replacement, deferred style loading, source updates and insertion order.
function inertEngine(styled = true) {
  const installed = new Map(BEFORE.map(id => [id, {id}]));
  const sources = new Map(), handlers = {}, calls = [];
  class MapDouble {
    keyboard = {disableRotation() {}};
    touchZoomRotate = {disableRotation() {}};
    on(type, listener) { (handlers[type] ??= []).push(listener); }
    addControl() {}
    getLayer(id) { return installed.get(id); }
    getSource(id) { return sources.get(id); }
    addSource(id, spec) {
      assert.ok(!sources.has(id));
      sources.set(id, {spec: structuredClone(spec), data: structuredClone(spec.data), setData(data) { this.data = structuredClone(data); calls.push(['data', id]); }});
      calls.push(['addSource', id]);
    }
    removeSource(id) {
      assert.ok(![...installed.values()].some(l => l.source === id), 'layers must be removed before source');
      sources.delete(id); calls.push(['removeSource', id]);
    }
    addLayer(layer, before) {
      assert.ok(!installed.has(layer.id));
      assert.ok(sources.has(layer.source));
      installed.set(layer.id, structuredClone(layer)); calls.push(['addLayer', layer.id, before]);
    }
    removeLayer(id) { installed.delete(id); calls.push(['removeLayer', id]); }
    remove() {}
  }
  const module = {lib: {Map: MapDouble, NavigationControl: class {}, ScaleControl: class {}, AttributionControl: class {}, setWorkerUrl() {}, addProtocol() {}},
    workerUrl: 'synthetic-worker.js', Protocol: class {tile = forbidden;}};
  const engine = createEngine(module, {host: {}, style: {version: 8, sources: {}, layers: []},
    camera: {latitude: 0, longitude: 0, zoom: 10}, onMove: forbidden, onLayerError: forbidden});
  const ready = () => { for (const handler of handlers['style.load'] ?? []) handler(); };
  if (styled) ready();
  return {engine, installed, sources, calls, ready};
}

async function setup(t, {styled = true} = {}) {
  const previous = {layers: layers.peek(), region: region.peek(), data: markData.peek(), screen: markScreen.peek(), on: aisOn.peek()};
  const map = inertEngine(styled), engine = signal(map.engine), asked = [];
  const payload = structuredClone(FIXTURE);
  batch(() => {
    region.value = 'synthetic-region'; layers.value = ['fleet']; aisOn.value = false;
    markScreen.value = READY;
    markData.value = {region: {id: 'synthetic-region', assets: {commercial_ais: PATH}}, atlas: null, survey: null, geology: null};
  });
  const ais = createCommercialAis({engine, page: () => PAGE, palette: () => PALETTE, fetchFn: async url => {
    assert.equal(url, new URL(PATH, PAGE).href); asked.push(url);
    return {ok: true, json: async () => payload};
  }});
  t.after(() => {
    ais.destroy(); map.engine.destroy();
    batch(() => { layers.value = previous.layers; region.value = previous.region; markData.value = previous.data; markScreen.value = previous.screen; aisOn.value = previous.on; });
  });
  assert.equal(asked.length, 0, 'default off means no feed request');
  aisOn.value = true; await flush();
  assert.equal(asked.length, 1);
  return {map, engine, ais, asked, payload};
}

function check(map, expected, denominator) {
  const source = map.sources.get(AIS_SOURCE);
  assert.ok(source, 'AIS source installed');
  assert.deepEqual(source.data.features.map(f => [f.properties.id, f.properties.hours]), expected);
  assert.deepEqual(source.data.features.map(f => Object.keys(f.properties).sort()), expected.map(() => ['hours', 'id']));
  const heat = map.installed.get(AIS_HEAT), line = map.installed.get(AIS_LINE);
  assert.equal(heat.paint['fill-opacity'][5], denominator, 'SP1711_SCALE_MISMATCH: installed heat denominator must match current displayed cells');
  assert.deepEqual(heat.paint, {'fill-color': PALETTE.amber, 'fill-opacity': ['interpolate', ['linear'], ['get', 'hours'], 0, 0.15, denominator, 0.45]});
  assert.deepEqual(line.paint, {'line-color': PALETTE.amber, 'line-width': 1.5});
  assert.equal(source.spec.attribution, layerEntry('commercial-ais').attribution);
  assert.deepEqual(map.calls.filter(c => c[0] === 'addLayer').slice(-2), [['addLayer', AIS_HEAT, BEFORE[0]], ['addLayer', AIS_LINE, BEFORE[0]]]);
  assert.ok(BEFORE.every(id => map.installed.has(id)), 'unrelated fleet/mark layers survive');
  assert.equal(aisState.value.drawn, expected.length);
}
const BOTH = [['SYNTHETIC-LOW', 2], ['SYNTHETIC-HIGH', 20]];
const LOW = [['SYNTHETIC-LOW', 2]];

test('Healthy control: initial 2 and 20 install matching denominator 20', async t => {
  const {map} = await setup(t); check(map, BOTH, 20);
});

test('A1: primary regression same-engine maximum removal refreshes scale', async t => {
  const {map, engine, asked} = await setup(t); check(map, BOTH, 20);
  markScreen.value = exclude(FIXTURE.features[1].geometry);
  assert.equal(engine.peek(), map.engine); assert.equal(aisOn.peek(), true);
  check(map, LOW, 2); assert.equal(asked.length, 1, 'screen update requires no new download');
});

test('A2: growth removal and unchanged maximum keep data and scale aligned', async t => {
  const {map} = await setup(t);
  markScreen.value = exclude(FIXTURE.features[1].geometry); check(map, LOW, 2);
  markScreen.value = READY; check(map, BOTH, 20);
  markScreen.value = exclude(FIXTURE.features[0].geometry); check(map, [BOTH[1]], 20);
  markScreen.value = READY; check(map, BOTH, 20);
});

test('A2: empty then nonempty and zero hours preserve floor one', async t => {
  const {map, payload} = await setup(t);
  markScreen.value = {...READY, status: 'checking'};
  assert.ok(!map.sources.has(AIS_SOURCE)); assert.ok(!map.installed.has(AIS_HEAT));
  // The feed double owns this synthetic payload; signal invalidation goes through the real screen.
  payload.features = [structuredClone(FIXTURE.features[0])]; payload.features[0].properties.apparent_fishing_hours = 0;
  markScreen.value = READY; check(map, [['SYNTHETIC-LOW', 0]], 1);
  markScreen.value = {...READY, status: 'stale'};
  payload.features[0].properties.apparent_fishing_hours = 0.5;
  markScreen.value = READY; check(map, [['SYNTHETIC-LOW', 0.5]], 1);
});

test('A2: engine replacement and null interval install the current scale', async t => {
  const {engine} = await setup(t);
  engine.value = null;
  markScreen.value = exclude(FIXTURE.features[1].geometry);
  const replacement = inertEngine(); t.after(() => replacement.engine.destroy());
  engine.value = replacement.engine; check(replacement, LOW, 2);
  markScreen.value = READY; check(replacement, BOTH, 20);
  const third = inertEngine(); t.after(() => third.engine.destroy());
  engine.value = third.engine; check(third, BOTH, 20);
});

test('A2: pending style load installs latest data and scale together', async t => {
  const {map} = await setup(t, {styled: false});
  assert.ok(!map.sources.has(AIS_SOURCE));
  markScreen.value = exclude(FIXTURE.features[1].geometry);
  map.ready(); check(map, LOW, 2);
});

test('A3: anchor and geometry exclusions off toggles and order remain intact', async t => {
  const {map, asked} = await setup(t);
  markScreen.value = exclude(box(20, 20, 0.01)); check(map, LOW, 2); // anchor inside
  markScreen.value = exclude(box(20.1, 20, 0.01)); check(map, LOW, 2); // geometry intersection only
  markScreen.value = READY; check(map, BOTH, 20);
  aisOn.value = false;
  assert.ok(!map.sources.has(AIS_SOURCE)); assert.ok(!map.installed.has(AIS_HEAT)); assert.ok(!map.installed.has(AIS_LINE));
  aisOn.value = true; check(map, BOTH, 20);
  layers.value = [];
  assert.ok(!map.sources.has(AIS_SOURCE)); assert.equal(aisState.value.drawn, 0);
  layers.value = ['fleet']; check(map, BOTH, 20); assert.equal(asked.length, 1);
});

test('A4: aggregate-only feed guard and existing destroy behavior preserved', async t => {
  const {map, ais, asked} = await setup(t);
  check(map, BOTH, 20);
  assert.throws(() => fetch('https://example.invalid/never-requested'), /SP1711 offline boundary/);
  assert.throws(() => globalThis.localStorage, /SP1711 offline boundary/);
  assert.deepEqual(asked, [new URL(PATH, PAGE).href], 'no charter-vessel feed or model endpoint');
  assert.deepEqual([...map.sources.keys()], [AIS_SOURCE]);
  assert.deepEqual(ais.pick.layers, [AIS_HEAT]); assert.equal(ais.pick.ordered, true);
  assert.match(ais.pick.mark(AIS_HEAT, {id: 'SYNTHETIC-LOW'}).reading, /Apparent fishing activity, not a verified catch spot/);
  assert.equal(ais.pick.mark(AIS_HEAT, {id: 'not-a-cell'}), null);
  ais.destroy();
  assert.deepEqual(aisState.value, {offered: false, drawn: 0, note: ''});
  const count = map.calls.length;
  markScreen.value = exclude(FIXTURE.features[1].geometry); aisOn.value = false; layers.value = [];
  assert.equal(map.calls.length, count, 'destroy disposes effects without adding overlay teardown behavior');
});
