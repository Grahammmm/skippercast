// RF1935-3: a failed Aerial source is detached from the map, so MapLibre has nothing left to request, and its late errors
// are dropped. Real createEngine + real createAerial over a fake MapLibre; no network.
import assert from 'node:assert/strict';
import test from 'node:test';
import {signal} from '@preact/signals';
import {aerialBase, aerialId, aerialOverlay, createAerial} from '../web/map/aerial.ts';
import {ENC_LAYER, chartStyle, markUnavailable, unavailable} from '../web/map/chart.ts';
import {createEngine} from '../web/map/engine.ts';
import {readPalette} from '../web/map/palette.ts';
import {configureStore, setParams, syncFromURL} from '../web/state.ts';
import {readFileSync} from 'node:fs';

const PAGE = 'https://s.test/map';
const MORRO = aerialBase(JSON.parse(readFileSync(new URL('../dist/regions/morro-bay/region.json', import.meta.url), 'utf8')));
const JID = aerialId(MORRO), PID = `${JID}:png32`;

function library() {
  const fake = {maps: []};
  class FakeMap {
    constructor(options) {
      this.handlers = {}; this.sources = {}; this.layers = (options.style.layers ?? []).map(l => l.id); this.log = [];
      this.keyboard = {disableRotation() {}}; this.touchZoomRotate = {disableRotation() {}};
      fake.maps.push(this);
    }
    on(type, fn) { (this.handlers[type] ??= []).push(fn); }
    fire(type, event = {}) { for (const fn of this.handlers[type] ?? []) fn(event); }
    addControl() {}
    getLayer(id) { return this.layers.includes(id) ? {} : undefined; }
    getSource(id) { return this.sources[id]; }
    addSource(id, spec) { this.sources[id] = spec; this.log.push(`+s ${id}`); }
    removeSource(id) { delete this.sources[id]; this.log.push(`-s ${id}`); }
    addLayer(layer, before) { const i = before ? this.layers.indexOf(before) : -1; this.layers.splice(i < 0 ? this.layers.length : i, 0, layer.id); this.log.push(`+l ${layer.id}`); }
    removeLayer(id) { this.layers = this.layers.filter(l => l !== id); this.log.push(`-l ${id}`); }
    remove() {}
  }
  const control = class {};
  fake.module = {lib: {Map: FakeMap, NavigationControl: control, ScaleControl: control, AttributionControl: control, setWorkerUrl() {}, addProtocol() {}},
    workerUrl: '/w.js', Protocol: class { constructor() { this.tile = () => {}; } }};
  return fake;
}

function setup(t, {base = 'aerial'} = {}) {
  const logged = t.mock.method(console, 'error', () => {});
  t.mock.method(console, 'warn', () => {});
  globalThis.location = {href: `${PAGE}?region=morro-bay&base=${base}`};
  globalThis.history = {state: null, pushState(_s, _t, url) { location.href = url; }, replaceState(_s, _t, url) { location.href = url; }};
  globalThis.dispatchEvent = () => true;
  configureStore({v2: true, storage: null});
  syncFromURL(location.href);
  unavailable.value = [];
  const fake = library(), errors = [];
  const style = chartStyle({palette: readPalette(name => `token(${name})`), archive: 'https://s.test/feeds/tiles/basemap/x.pmtiles', page: PAGE, region: 'morro-bay', base});
  const eng = createEngine(fake.module, {host: {}, style, camera: {latitude: 35.37, longitude: -120.86, zoom: 12}, onMove() {},
    onLayerError: (layer, error) => { errors.push([layer, error.message]); markUnavailable(layer); }});
  const [map] = fake.maps;
  return {map, eng, errors, logged, live: signal(eng)};
}

test('terminal failure detaches both failed sources once, layers before sources, and leaves the rest of the chart', t => {
  const {map, eng, errors, live} = setup(t);
  const a = createAerial({engine: live, offer: () => MORRO});
  map.fire('style.load');
  assert.ok(map.getSource(JID));
  const others = map.layers.filter(l => l !== JID);
  map.fire('error', {sourceId: JID, error: new Error('400')});
  assert.equal(map.getSource(JID), undefined);
  assert.ok(!map.layers.includes(JID));
  assert.ok(map.log.indexOf(`-l ${JID}`) < map.log.indexOf(`-s ${JID}`), 'layer first, source second');
  assert.ok(map.getSource(PID) && map.layers.includes(PID), 'the single png32 fallback is installed and not removed by the old cleanup');
  map.fire('error', {sourceId: PID, error: new Error('500')});
  assert.equal(map.getSource(PID), undefined);
  assert.ok(!map.layers.includes(PID));
  assert.ok(map.log.indexOf(`-l ${PID}`) < map.log.indexOf(`-s ${PID}`));
  assert.deepEqual(map.layers, others, 'unrelated layers remain');
  assert.deepEqual(errors, [['aerial', '400'], ['aerial', '500']]);
  assert.deepEqual(unavailable.value, ['aerial'], 'one terminal unavailable entry');
  const adds = map.log.filter(l => l.startsWith('+')).length;
  for (let i = 0; i < 20; i++) { map.fire('error', {sourceId: JID, error: new Error('late')}); map.fire('error', {sourceId: PID, error: new Error('late')}); }
  map.fire('style.load');
  assert.equal(map.log.filter(l => l.startsWith('+')).length, adds, 'nothing re-added');
  assert.equal(errors.length, 2, 'late errors are not passed on again');
  a.destroy();
  eng.destroy();
});

test('late errors from retired sources are not Chart errors, but an unknown source still is', t => {
  const {map, errors, logged, live} = setup(t);
  const a = createAerial({engine: live, offer: () => MORRO});
  map.fire('style.load');
  map.fire('error', {sourceId: JID, error: new Error('400')});
  map.fire('error', {sourceId: PID, error: new Error('500')});
  setParams({base: 'night'});
  for (let i = 0; i < 10; i++) { map.fire('error', {sourceId: JID, error: new Error('late')}); map.fire('error', {sourceId: PID, error: new Error('late')}); }
  assert.equal(logged.mock.callCount(), 0, 'no Chart-error storm');
  assert.equal(errors.length, 2);
  map.fire('error', {sourceId: 'mystery', error: new Error('x')});
  assert.equal(logged.mock.callCount(), 1, 'an unknown source keeps the generic Chart error');
  a.destroy();
});

test('the same failed overlay object is not re-armed; off then on is a fresh attempt', t => {
  const {map, eng, errors} = setup(t);
  map.fire('style.load');
  const o = aerialOverlay(MORRO);
  eng.setOverlay('aerial', o, ENC_LAYER);
  map.fire('error', {sourceId: JID, error: new Error('400')});
  eng.setOverlay('aerial', o, ENC_LAYER);
  map.fire('style.load');
  assert.equal(map.getSource(JID), undefined, 'the same failed object is a no-op');
  eng.setOverlay('aerial', null, ENC_LAYER);
  eng.setOverlay('aerial', aerialOverlay(MORRO), ENC_LAYER);
  assert.ok(map.getSource(JID), 'a new activation installs');
  map.fire('error', {sourceId: JID, error: new Error('again')});
  assert.equal(map.getSource(JID), undefined);
  assert.equal(errors.length, 2);
});

test('before style.load nothing is installed, and a failed overlay queued earlier is not installed later; destroy ignores errors', t => {
  const {map, eng, errors, logged} = setup(t);
  const o = aerialOverlay(MORRO);
  eng.setOverlay('aerial', o, ENC_LAYER);
  assert.equal(map.getSource(JID), undefined, 'deferred until style.load');
  map.fire('style.load');
  map.fire('error', {sourceId: JID, error: new Error('400')});
  eng.destroy();
  map.fire('error', {sourceId: JID, error: new Error('after destroy')});
  map.fire('error', {sourceId: 'mystery', error: new Error('after destroy')});
  assert.equal(errors.length, 1);
  assert.equal(logged.mock.callCount(), 0);
});

test('non-opted-in overlays keep today\'s behaviour: the source stays installed and each error reaches the owner', t => {
  const {map, eng, errors} = setup(t);
  map.fire('style.load');
  const o = {sources: {x: {type: 'raster', tiles: ['https://s.test/{z}/{x}/{y}.png']}}, layers: [{id: 'x', type: 'raster', source: 'x'}]};
  eng.setOverlay('clouds', o);
  map.fire('error', {sourceId: 'x', error: new Error('1')});
  map.fire('error', {sourceId: 'x', error: new Error('2')});
  assert.ok(map.getSource('x'));
  assert.deepEqual(errors, [['clouds', '1'], ['clouds', '2']]);
});

test('base off then Aerial again starts a fresh jpgpng attempt', t => {
  const {map, live, errors} = setup(t);
  const a = createAerial({engine: live, offer: () => MORRO});
  map.fire('style.load');
  map.fire('error', {sourceId: JID, error: new Error('400')});
  map.fire('error', {sourceId: PID, error: new Error('500')});
  assert.deepEqual(unavailable.value, ['aerial']);
  setParams({base: 'night'});
  assert.deepEqual(unavailable.value, []);
  setParams({base: 'aerial'});
  assert.ok(map.getSource(JID), 'fresh attempt installs the dated source again');
  assert.equal(errors.length, 2);
  a.destroy();
});
