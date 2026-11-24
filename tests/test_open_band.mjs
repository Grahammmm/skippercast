// RF0905-1 (phone-pass issue 5): below 1024 px the Chart pads MapLibre so the camera centre draws in the
// open band between the top card and the sheet; desktop and `?view=` are unchanged. Fake MapLibre and DOM.
import assert from 'node:assert/strict';
import test from 'node:test';
import {openBandPadding, toEdge} from '../web/map/open-band.ts';
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

test('phone at peek: the top card pads the top, the sheet the bottom', async t => {
  assert.deepEqual(openBandPadding(HOST, [TOP, SHEET]), {top: 130, bottom: 233, left: 0, right: 0});
  assert.deepEqual(openBandPadding({top: 50, bottom: 894, left: 0, right: 390}, [{...TOP, top: 50, bottom: 180}, {...SHEET, top: 661, bottom: 894}]),
    {top: 130, bottom: 233, left: 0, right: 0}, 'relative to the host');
  assert.deepEqual(openBandPadding(HOST, [{...TOP, bottom: 130.4}]), {...ZERO, top: 130}, 'whole px');
  const brand = {...TOP, bottom: 90};  // two top covers: the lower bottom wins, whichever comes first
  assert.deepEqual(openBandPadding(HOST, [brand, TOP]), {...ZERO, top: 130});
  assert.deepEqual(openBandPadding(HOST, [TOP, brand, SHEET, {...SHEET, top: 700}]), {...ZERO, top: 130, bottom: 233});
  // app.css at 390×844: the 704 px sheet on the 56 px tabs, translated to peek 612..1316, half 366..1070; a hidden sheet has no box.
  const edge = box => toEdge({...SHEET, ...box}, 844);
  assert.deepEqual([{top: 612, bottom: 1316}, {top: 366, bottom: 1070}, {top: 0, bottom: 0}].map(b => openBandPadding(HOST, [TOP, edge(b)]).bottom), [232, 478, 0]);
  // The raw edge can be well outside the 8 px tolerance while the visible cover still meets the host edge.
  const spill = {left: -20, right: 410};
  await t.test('top card spilling past the viewport still pads the top', () => {
    assert.deepEqual(openBandPadding(HOST, [{...TOP, ...spill, top: -24}]), {...ZERO, top: 130});
  });
  await t.test('half-open sheet spilling past the viewport still pads the bottom', () => {
    assert.deepEqual(openBandPadding(HOST, [{...SHEET, ...spill, top: 366, bottom: 1070}]), {...ZERO, bottom: 478});
  });
});

test('no covers, narrow, non-finite, non-overlapping and full-height covers pad nothing', () => {
  assert.deepEqual(openBandPadding(HOST, []), ZERO);
  assert.deepEqual(openBandPadding(HOST, [{top: 0, bottom: 300, left: 346, right: 600}]), ZERO, 'only 44 px of the side control is visible');
  for (const bad of [NaN, Infinity, -Infinity]) assert.deepEqual(openBandPadding(HOST, [{...TOP, bottom: bad}, {...SHEET, left: bad}]), ZERO, String(bad));
  assert.deepEqual(openBandPadding(HOST, [{...TOP, top: -200, bottom: 0}, {...SHEET, top: 844, bottom: 1000}, {...TOP, left: 390, right: 780}]), ZERO, 'outside the host');
  assert.deepEqual(openBandPadding(HOST, [{...SHEET, top: 0}]), ZERO, 'a full-height sheet');
  assert.deepEqual(openBandPadding(HOST, [{...SHEET, top: 0, bottom: 1070}]), ZERO, 'a sheet that fully covers the host and spills below it');
  assert.deepEqual(openBandPadding(HOST, [{...TOP, top: 8, bottom: 4}]), ZERO, 'an inverted rectangle near the top edge');
  assert.deepEqual(openBandPadding(HOST, [{...TOP, top: 8}]), {...ZERO, top: 130}, 'a card within the 8 px tolerance');
  assert.deepEqual(openBandPadding(HOST, [{...TOP, top: 9}]), ZERO, 'a card just outside the 8 px tolerance');
});

test('a band under 160 px shrinks both in proportion to leave at least 160; a host under 160 pads nothing', () => {
  assert.deepEqual(openBandPadding(HOST, [{...TOP, bottom: 400}, {...SHEET, top: 444}]), {...ZERO, top: 342, bottom: 342});
  assert.deepEqual(openBandPadding(HOST, [{...TOP, bottom: 500}, {...SHEET, top: 544}]), {...ZERO, top: 428, bottom: 256}, '5:3 stays 5:3 while the centre (508) stays in the 500..544 gap');
  // The old 3:1 split of this 600..644 gap put the centre at 593, behind the top card; it now stays on the gap midpoint 622.
  assert.deepEqual(openBandPadding(HOST, [{...TOP, bottom: 600}, {...SHEET, top: 644}]), {...ZERO, top: 542, bottom: 142}, 'centre kept in the gap');
  assert.deepEqual(openBandPadding(HOST, [TOP, {...SHEET, top: 290}]), {...ZERO, top: 130, bottom: 554}, 'an exact-fit 160 px band');
  // Rounding the two shares against a fractional remainder can spend 14 px of a 13.75 px allowance.
  const short = {...HOST, bottom: 173.75};
  assert.deepEqual(openBandPadding(short, [{...TOP, bottom: 90}, {...short, top: 143.75}]),
    {...ZERO, top: 10, bottom: 3}, 'a 3:1 split fits the 13 px budget and exposes 160.75 px');
  assert.deepEqual(openBandPadding({...HOST, bottom: 400}, [{...TOP, bottom: 70}]), {...ZERO, top: 70}, 'the taller host still exposes 330 px');
  assert.deepEqual(openBandPadding({top: 0, bottom: 120, left: 0, right: 390}, [{...TOP, bottom: 40}]), ZERO);
  assert.deepEqual(openBandPadding({top: 0, bottom: NaN, left: 0, right: 390}, [TOP]), ZERO);
});

// Contract: the camera centre MapLibre draws is (top + height - bottom) / 2. When the covers leave a visible gap the shrink to the
// 160 px budget must keep that centre inside the gap, or the point the user centred on is hidden behind a cover.
test('a narrow gap between tall covers keeps the padded camera centre inside the gap', () => {
  const centre = pad => (pad.top + HOST.bottom - pad.bottom) / 2;
  const sheetAt = top => toEdge({...SHEET, top, bottom: top + 704}, HOST.bottom);  // the 704 px phone sheet translated to `top`
  // Catches: the proportional shrink alone, which moved this 130..144 gap's centre to 187, behind the sheet.
  const narrow = openBandPadding(HOST, [TOP, sheetAt(144)]);
  assert.ok(centre(narrow) > 130 && centre(narrow) < 144, `centre ${centre(narrow)} must lie in the 130..144 gap`);
  assert.deepEqual(narrow, {...ZERO, top: 57, bottom: 627}, 'a 160 px band around the gap midpoint 137');
  // Catches: a fix that spends more than the 160 px minimum-band budget (padding sum above host - 160) to centre the gap.
  assert.equal(HOST.bottom - narrow.top - narrow.bottom, 160, 'the minimum band is still exactly kept');
  // Catches: the fix changing a layout that needed no shrink (control: sheet at half).
  const control = openBandPadding(HOST, [TOP, sheetAt(366)]);
  assert.deepEqual(control, {...ZERO, top: 130, bottom: 478});
  assert.equal(centre(control), 248);
  // Catches: a gap at the top edge, where centring on the midpoint needs a negative top pad (must clamp to 0, centre still in the gap).
  const edge = openBandPadding(HOST, [{...TOP, bottom: 0.5}, sheetAt(144)]);
  assert.ok(centre(edge) > 0 && centre(edge) < 144, `edge-clamped centre ${centre(edge)}`);
  assert.ok(edge.top >= 0 && edge.bottom >= 0 && edge.top + edge.bottom <= 684);
  // Catches: any sheet position where the shrink hides the centre, or breaks the budget, or pads more than the cover.
  for (let top = 131; top < 700; top++) {
    const pad = openBandPadding(HOST, [TOP, sheetAt(top)]), c = centre(pad);
    assert.ok(pad.top + pad.bottom <= 684, `sheet at ${top}: budget`);
    assert.ok(pad.top <= 130 && pad.bottom <= HOST.bottom - top, `sheet at ${top}: no more than the cover`);
    assert.ok(c > 130 && c < top, `sheet at ${top}: centre ${c} in ${130}..${top}`);
  }
  // Catches: rounding the pads to the whole budget, which puts a 1 px gap's centre on the sheet edge (131) instead of 130.5,
  // on an even and an odd host height. The centre must be strictly inside, with the pads still whole px and within budget.
  for (const bottom of [844, 843, 845]) {
    const host = {...HOST, bottom}, pad = openBandPadding(host, [TOP, toEdge({...SHEET, top: 131, bottom: 131 + 704}, bottom)]);
    const c = (pad.top + bottom - pad.bottom) / 2;
    assert.ok(c > 130 && c < 131, `host ${bottom}: centre ${c} must lie strictly inside the 130..131 gap`);
    assert.ok(Number.isInteger(pad.top) && Number.isInteger(pad.bottom) && pad.top + pad.bottom <= bottom - 160, `host ${bottom}: whole px within budget`);
  }
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
    // The flyover (#646): eases are recorded, as in test_map_layers.mjs.
    easeTo(o) { (this.eases ??= []).push(o); } stop() {} getPitch() { return 0; } getBearing() { return 0; } setMaxPitch(p) { this.maxPitch = p; }
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

function chartAt(width, dom = false, flyoverGate = () => ({reduced: true, saveData: false, hidden: false, linked: false, seen: true}),
  {height = HOST.bottom, top = TOP, theme = 'dark'} = {}) {
  globalThis.location = {href: `${PAGE}?region=morro-bay&presentation=chart`};
  globalThis.history = {state: null, pushState(_s, _t, url) { location.href = url; }, replaceState(_s, _t, url) { location.href = url; }};
  globalThis.dispatchEvent = () => true; configureStore({v2: true, storage: null}); syncFromURL(location.href);
  const fake = library(true);
  const host = {dataset: {}, clientWidth: width, clientHeight: Math.floor(height), getBoundingClientRect: () => ({...HOST, right: host.clientWidth, bottom: height})};
  terrainFailed.value = false; chartFailed.value = false; chartMark.value = null; unavailable.value = [];
  const fetchFn = async () => ({ok: false, status: 404, json: async () => ({})}), sheet = {...SHEET};
  const land = {styles: [], mountCoast: () => ({load: async () => true, destroy() {}, setOverlay() {}, removeOverlay() {}})};
  const stage = createStage({host: {dataset: {}, shadowRoot: {replaceChildren() {}}}, load: async () => land, center: () => [35.37, -120.86], viewDelay: 0,
    doc: {hidden: false, addEventListener() {}, removeEventListener() {}},
    renderers: [() => createChart({host, load: async () => fake.module, fetchFn, page: () => PAGE, palette: () => readPalette(n => /^map-.*-(?:opacity|width)$/.test(n) ? '1' : `${theme}(${n})`), viewDelay: 0,
      covers: dom ? undefined : () => [top, sheet], flyoverGate})]});
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

test('Chart wiring: a fractional phone host keeps the minimum open band in either theme', async t => {
  for (const name of ['warn', 'error']) t.mock.method(console, name, () => {});
  for (const theme of ['light', 'dark']) await t.test(theme, async t => {
    const height = 160.75;
    const run = chartAt(390, false, undefined, {height, top: {...TOP, bottom: 70}, theme});
    t.after(() => run.stage.destroy());
    await tick(); await tick(); const [map] = run.fake.maps;
    const [pad] = map.paddings;
    // Rounding the 0.75 px margin up to one pixel would expose only 159.75 px.
    assert.ok(height - pad.top - pad.bottom >= 160, 'at least 160 px remain open');
    assert.deepEqual(map.paddings, [ZERO]);
    assert.deepEqual(map.center, {lat: 35.37, lng: -120.86});
    assert.equal(map.zoom, map.options.zoom, 'mount padding preserves the opening zoom');
    assert.equal(run.view(), null);
  });
});

test('the mount padding is not a camera move: a phone keeps ?view= unwritten and still flies on the first idle', async t => {
  for (const name of ['warn', 'error']) t.mock.method(console, name, () => {});
  const open = linked => ({reduced: false, saveData: false, hidden: false, linked, seen: false});
  for (const width of [390, 1280]) {
    const run = chartAt(width, false, open);
    await tick(); await tick(); const [map] = run.fake.maps;
    await tick(); await tick();  // past the 0 ms ?view= delay
    assert.equal(run.view(), null, `${width} px: no ?view= from the mount`);
    map.fire('idle');
    assert.equal(run.host.dataset.flyover, 'flying', `${width} px: the first idle flies`);
    assert.equal(map.eases?.length, 1);
    run.stage.destroy();
  }
});

test('the default covers read the CSS-translated peek sheet (612..1316) down to the host bottom', async t => {
  for (const name of ['warn', 'error']) t.mock.method(console, name, () => {});
  const el = (box, sheet) => ({getBoundingClientRect: () => box, matches: s => sheet && s === '.ui-sheet'});
  globalThis.document = {hidden: false, addEventListener() {}, removeEventListener() {},
    querySelectorAll: s => s === '.app-top, .ui-sheet' ? [el(TOP, false), el({...SHEET, top: 612, bottom: 1316}, true)] : []};
  t.after(() => { delete globalThis.document; });
  const run = chartAt(390, true);
  t.after(() => run.stage.destroy());
  await tick(); await tick();
  assert.deepEqual(run.fake.maps[0].paddings, [{...ZERO, top: 130, bottom: 232}]);
});
