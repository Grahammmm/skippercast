// RF0905-1 (phone-pass issue 5): below 1024 px the Chart pads MapLibre so the camera centre draws in the
// open band between the top card and the sheet; desktop and `?view=` are unchanged. Fake MapLibre, no DOM.
import assert from 'node:assert/strict';
import test from 'node:test';
import {openBandPadding} from '../web/map/open-band.ts';
import {createEngine} from '../web/map/engine.ts';
import {chartFailed, chartMark, createChart, unavailable} from '../web/map/chart.ts';
import {createStage, terrainFailed} from '../web/map/stage.ts';
import {configureStore, syncFromURL} from '../web/state.ts';
import {readPalette} from '../web/map/palette.ts';

const PAGE = 'https://s.test/map';
const HOST = {top: 0, bottom: 844, left: 0, right: 390};
const TOP = {top: 0, bottom: 130, left: 0, right: 390}, SHEET = {top: 611, bottom: 844, left: 0, right: 390};
const ZERO = {top: 0, bottom: 0, left: 0, right: 0};
const tick = () => new Promise(resolve => setTimeout(resolve, 0));

test('phone at peek: the top card pads the top, the sheet the bottom', () => {
  assert.deepEqual(openBandPadding(HOST, [TOP, SHEET]), {top: 130, bottom: 233, left: 0, right: 0});
  assert.deepEqual(openBandPadding({top: 50, bottom: 894, left: 0, right: 390}, [{...TOP, top: 50, bottom: 180}, {...SHEET, top: 661, bottom: 894}]),
    {top: 130, bottom: 233, left: 0, right: 0}, 'relative to the host');
  assert.deepEqual(openBandPadding(HOST, [{...TOP, bottom: 130.4}]), {...ZERO, top: 130}, 'whole px');
  const brand = {...TOP, bottom: 90};  // two top covers: the lower bottom wins, whichever comes first
  assert.deepEqual(openBandPadding(HOST, [brand, TOP]), {...ZERO, top: 130});
  assert.deepEqual(openBandPadding(HOST, [TOP, brand, SHEET, {...SHEET, top: 700}]), {...ZERO, top: 130, bottom: 233});
});

test('no covers, narrow, non-finite, non-overlapping and full-height covers pad nothing', () => {
  assert.deepEqual(openBandPadding(HOST, []), ZERO);
  assert.deepEqual(openBandPadding(HOST, [{top: 0, bottom: 300, left: 346, right: 390}]), ZERO, 'a 44 px zoom button');
  for (const bad of [NaN, Infinity, -Infinity]) assert.deepEqual(openBandPadding(HOST, [{...TOP, bottom: bad}, {...SHEET, left: bad}]), ZERO, String(bad));
  assert.deepEqual(openBandPadding(HOST, [{...TOP, top: -200, bottom: 0}, {...SHEET, top: 844, bottom: 1000}, {...TOP, left: 390, right: 780}]), ZERO, 'outside the host');
  assert.deepEqual(openBandPadding(HOST, [{...SHEET, top: 0}]), ZERO, 'a full-height sheet');
  assert.deepEqual(openBandPadding(HOST, [{...TOP, top: 20}]), ZERO, 'a card more than 8 px below the top edge');
});

test('a band under 160 px shrinks both in proportion to exactly 160; a host under 160 pads nothing', () => {
  assert.deepEqual(openBandPadding(HOST, [{...TOP, bottom: 400}, {...SHEET, top: 444}]), {...ZERO, top: 342, bottom: 342});
  assert.deepEqual(openBandPadding(HOST, [{...TOP, bottom: 600}, {...SHEET, top: 644}]), {...ZERO, top: 513, bottom: 171}, '3:1 stays 3:1');
  assert.deepEqual(openBandPadding(HOST, [{...TOP, bottom: 2000}]), {...ZERO, top: 684}, 'clamped to the host, then shrunk');
  assert.deepEqual(openBandPadding({top: 0, bottom: 120, left: 0, right: 390}, [{...TOP, bottom: 40}]), ZERO);
  assert.deepEqual(openBandPadding({top: 0, bottom: NaN, left: 0, right: 390}, [TOP]), ZERO);
});

/** A fake MapLibre just big enough for the engine and the Chart; `withPadding` gives it a recorded setPadding. */
function library(withPadding) {
  const fake = {maps: []};
  class FakeMap {
    constructor(options) {
      this.options = options; this.handlers = {}; this.paddings = []; this.keyboard = this.touchZoomRotate = {disableRotation() {}};
      this.center = {lat: options.center[1], lng: options.center[0]}; this.zoom = options.zoom;
      if (withPadding) this.setPadding = p => { this.paddings.push(p); this.fire('moveend'); };  // as MapLibre's: a jump that keeps the centre
      fake.maps.push(this);
    }
    on(type, fn) { (this.handlers[type] ??= []).push(fn); }
    off(type, fn) { this.handlers[type] = (this.handlers[type] ?? []).filter(f => f !== fn); }
    fire(type) { for (const fn of this.handlers[type] ?? []) fn({}); }
    getCenter() { return this.center; } getZoom() { return this.zoom; } addControl() {} getLayer() {} getSource() {} remove() {}
    jumpTo({center, zoom}) { this.center = {lat: center[1], lng: center[0]}; this.zoom = zoom; this.fire('moveend'); }
  }
  const Control = class {};
  fake.module = {lib: {Map: FakeMap, NavigationControl: Control, ScaleControl: Control, AttributionControl: Control, setWorkerUrl() {}, addProtocol() {}},
    workerUrl: '/w.js', Protocol: class { tile() {} }};
  return fake;
}

test('the engine passes the padding to MapLibre once, and a library without setPadding ignores it', () => {
  const camera = {latitude: 35.37, longitude: -120.86, zoom: 12}, style = {version: 8, sources: {}, layers: []};
  const bare = library(false), padded = library(true), p = {top: 130, bottom: 233, left: 0, right: 0};
  assert.doesNotThrow(() => createEngine(bare.module, {host: {}, style, camera, onMove() {}, onLayerError() {}}).setPadding(p));
  createEngine(padded.module, {host: {}, style, camera, onMove() {}, onLayerError() {}}).setPadding(p);
  assert.equal(padded.maps[0].paddings.length, 1);
  assert.equal(padded.maps[0].paddings[0], p, 'the exact object');
});

function chartAt(width) {
  globalThis.location = {href: `${PAGE}?region=morro-bay&presentation=chart`};
  globalThis.history = {state: null, pushState(_s, _t, url) { location.href = url; }, replaceState(_s, _t, url) { location.href = url; }};
  globalThis.dispatchEvent = () => true; configureStore({v2: true, storage: null}); syncFromURL(location.href);
  const fake = library(true);
  const host = {dataset: {}, clientWidth: width, clientHeight: 844, getBoundingClientRect: () => ({...HOST, right: host.clientWidth})};
  terrainFailed.value = false; chartFailed.value = false; chartMark.value = null; unavailable.value = [];
  const fetchFn = async () => ({ok: false, status: 404, json: async () => ({})}), sheet = {...SHEET};
  const land = {styles: [], mountCoast: () => ({load: async () => true, destroy() {}, setOverlay() {}, removeOverlay() {}})};
  const stage = createStage({host: {dataset: {}, shadowRoot: {replaceChildren() {}}}, load: async () => land, center: () => [35.37, -120.86], viewDelay: 0,
    doc: {hidden: false, addEventListener() {}, removeEventListener() {}},
    renderers: [() => createChart({host, load: async () => fake.module, fetchFn, page: () => PAGE, palette: () => readPalette(n => `token(${n})`), viewDelay: 0,
      covers: () => [TOP, sheet], flyoverGate: () => ({reduced: true, saveData: false, hidden: false, linked: false, seen: true})})]});
  return {fake, host, stage, sheet, view: () => new URL(location.href).searchParams.get('view')};
}

test('Chart wiring: a phone pads at mount and on resize, desktop never, phone then desktop ends at zero; the camera stays', async t => {
  for (const name of ['warn', 'error']) t.mock.method(console, name, () => {});
  let run = chartAt(390);
  await tick(); await tick(); let [map] = run.fake.maps;
  const band = {top: 130, bottom: 233, left: 0, right: 0};
  assert.deepEqual(map.paddings, [band], 'once at mount');
  assert.deepEqual(map.center, {lat: 35.37, lng: -120.86}, 'the region centre');
  assert.equal(run.host.dataset.view, '35.37000,-120.86000,12', 'the first moveend after mount reads the same centre');
  assert.equal(run.view(), null, 'and writes no new ?view=');
  run.sheet.top = 400;  // the sheet opens to half: no padding until the next resize, so the map never jumps under the finger
  await tick();
  assert.deepEqual(map.paddings, [band], 'not on a detent change');
  run.sheet.top = 611;
  map.fire('resize');
  assert.deepEqual(map.paddings, [band, band], 'again after a resize');
  run.host.clientWidth = 1280;
  map.fire('resize');
  assert.deepEqual(map.paddings, [band, band, ZERO], 'phone then desktop: a final all-zero call');
  map.fire('resize'); assert.equal(map.paddings.length, 3, 'only once');
  run.stage.destroy();

  run = chartAt(1280);
  await tick(); await tick(); [map] = run.fake.maps;
  map.fire('resize'); assert.deepEqual(map.paddings, [], 'desktop never pads');
  assert.equal(run.host.dataset.view, '35.37000,-120.86000,12');
  run.stage.destroy();
});
