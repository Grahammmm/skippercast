// R4-SC-09: the first view's aerial base is a quarter-pixel preview; the full image is laid over it once the page says the
// first view is in (`sharp`), and the preview goes when the map next settles. Fake engine; no GPU, library or network.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {signal} from '@preact/signals';
import {naipSource} from '../packages/coast/src/map-sources.ts';
import {
  PREVIEW_SIZE, SHARP_WAIT_MAX_MS, aerialBase, aerialId, aerialOverlay, aerialSoft, createAerial, createSharpStart, previewTiles,
} from '../web/map/aerial.ts';
import {ENC_LAYER, markUnavailable, unavailable} from '../web/map/chart.ts';
import {configureStore, setParams, syncFromURL} from '../web/state.ts';

const PAGE = 'https://s.test/map';
const MORRO = aerialBase(JSON.parse(readFileSync(new URL('../dist/regions/morro-bay/region.json', import.meta.url), 'utf8')));
const ID = aerialId(MORRO);
const params = template => new URL(template.replace('{bbox-epsg-3857}', '0,0,1,1')).searchParams;
const shape = overlay => overlay && overlay.layers.map(l => [l.id, params(overlay.sources[l.source].tiles[0]).get('size'), params(overlay.sources[l.source].tiles[0]).get('format')]);

function browser() {
  globalThis.location = {href: `${PAGE}?region=morro-bay&base=aerial`};
  globalThis.history = {state: null, pushState(_s, _t, url) { location.href = url; }, replaceState(_s, _t, url) { location.href = url; }};
  globalThis.dispatchEvent = () => true;
  configureStore({v2: true, storage: null});
  syncFromURL(location.href);
  unavailable.value = [];
}
/** An engine that records the aerial overlays it was given; `settle()` fires the map's `idle`. */
function engine() {
  const e = {overlay: null, before: null, calls: 0, idle: new Set()};
  Object.assign(e, {
    setOverlay(layer, overlay, before) { assert.equal(layer, 'aerial'); e.calls++; e.overlay = overlay; e.before = before; },
    view: {on(type, fn) { assert.equal(type, 'idle'); e.idle.add(fn); return () => e.idle.delete(fn); }},
    settle() { for (const fn of [...e.idle]) fn(); },
  });
  return e;
}

test('the preview is naipSource()\'s own template at a quarter of the pixels; both stages keep the full source\'s id, credit and paint', () => {
  assert.equal(PREVIEW_SIZE, 256);
  const [template] = previewTiles(), [full] = naipSource().tiles;
  assert.equal(template, full.replace('size=512,512', 'size=256,256'), 'only the image size differs: same host, box, format and rendering rule');
  assert.equal(params(previewTiles('png32')[0]).get('format'), 'png32');
  const preview = aerialOverlay(MORRO, undefined, 'preview'), both = aerialOverlay(MORRO, undefined, 'both'), alone = aerialOverlay(MORRO);
  assert.deepEqual(shape(preview), [[`${ID}:preview`, '256,256', 'jpgpng']]);
  assert.deepEqual(shape(both), [[`${ID}:preview`, '256,256', 'jpgpng'], [ID, '512,512', 'jpgpng']], 'the full image above the preview');
  assert.deepEqual(both.sources[ID], alone.sources[ID], 'the full source is the one drawn without a preview');
  assert.deepEqual(both.sources[`${ID}:preview`], {...alone.sources[ID], tiles: previewTiles()}, 'same tile size, zooms and dated credit');
  for (const o of [preview, both]) { assert.equal(o.stopOnError, true); for (const l of o.layers) assert.deepEqual(l.paint, alone.layers[0].paint); }
  assert.deepEqual(shape(aerialOverlay(MORRO, 'png32', 'preview')), [[`${ID}:png32:preview`, '256,256', 'png32']]);
});

test('with `sharp`, a first draw is the preview; sharp lays the full image over it; the next idle drops the preview', () => {
  browser();
  const e = engine(), sharp = signal(false);
  const a = createAerial({engine: signal(e), offer: () => MORRO, sharp: () => sharp.value});
  assert.deepEqual(shape(e.overlay), [[`${ID}:preview`, '256,256', 'jpgpng']]);
  assert.equal(e.before, ENC_LAYER);
  e.settle();
  assert.equal(e.calls, 1, 'an idle before sharp changes nothing');
  sharp.value = true;
  assert.deepEqual(shape(e.overlay), [[`${ID}:preview`, '256,256', 'jpgpng'], [ID, '512,512', 'jpgpng']]);
  assert.equal(e.calls, 2);
  e.settle();
  assert.deepEqual(shape(e.overlay), [[ID, '512,512', 'jpgpng']], 'the full image alone once it has drawn');
  assert.equal(e.idle.size, 0, 'no listener left behind');
  sharp.value = false;
  e.settle();
  assert.equal(e.calls, 3, 'latched: nothing re-holds');
  setParams({base: 'night'});
  setParams({base: 'aerial'});
  assert.deepEqual(shape(e.overlay), [[ID, '512,512', 'jpgpng']], 'chosen again after the first view: the full image at once');
  a.destroy();
});

test('aerialSoft reads true from the preview until the full image is alone, and never for a failed or removed base', t => {
  t.mock.method(console, 'warn', () => {});
  browser();
  const e = engine(), sharp = signal(false);
  const a = createAerial({engine: signal(e), offer: () => MORRO, sharp: () => sharp.value});
  assert.equal(aerialSoft.value, true, 'the preview alone');
  sharp.value = true;
  assert.equal(aerialSoft.value, true, 'the full image still arriving over the preview');
  e.settle();
  assert.equal(aerialSoft.value, false, 'the full image alone');
  a.destroy();

  browser();
  const f = engine(), b = createAerial({engine: signal(f), offer: () => MORRO, sharp: () => false});
  assert.equal(aerialSoft.value, true);
  setParams({base: 'night'});
  assert.equal(aerialSoft.value, false, 'another base: nothing left to refine');
  b.destroy();

  browser();
  const g = engine(), c = createAerial({engine: signal(g), offer: () => MORRO, sharp: () => false});
  markUnavailable('aerial');
  assert.equal(aerialSoft.value, true, 'the png32 preview after one failure');
  markUnavailable('aerial');
  assert.equal(aerialSoft.value, false, 'a base that failed for good never holds the Chart busy');
  c.destroy();
  unavailable.value = [];

  browser();
  const h = engine(), d = createAerial({engine: signal(h), offer: () => MORRO});
  assert.equal(aerialSoft.value, false, 'without `sharp` the full image is drawn at once');
  d.destroy();
});

test('without `sharp` the full image is drawn at once, as before', () => {
  browser();
  const e = engine(), a = createAerial({engine: signal(e), offer: () => MORRO});
  assert.deepEqual(shape(e.overlay), [[ID, '512,512', 'jpgpng']]);
  a.destroy();
});

test('a failed preview falls back once to the png32 preview, still sharpens, and a failed fallback never sharpens', t => {
  t.mock.method(console, 'warn', () => {});
  browser();
  const e = engine(), sharp = signal(false);
  const a = createAerial({engine: signal(e), offer: () => MORRO, sharp: () => sharp.value});
  markUnavailable('aerial');
  assert.deepEqual(shape(e.overlay), [[`${ID}:png32:preview`, '256,256', 'png32']], 'the first view stays a preview');
  assert.deepEqual(unavailable.value, []);
  sharp.value = true;
  e.settle();
  assert.deepEqual(shape(e.overlay), [[`${ID}:png32`, '512,512', 'png32']]);
  a.destroy();

  browser();
  const f = engine(), later = signal(false);
  const b = createAerial({engine: signal(f), offer: () => MORRO, sharp: () => later.value});
  markUnavailable('aerial');
  markUnavailable('aerial');
  assert.deepEqual(unavailable.value, ['aerial']);
  const calls = f.calls;
  later.value = true;
  f.settle();
  assert.equal(f.calls, calls, 'a base that failed for good asks for nothing more');
  b.destroy();

  browser();
  const g = engine(), now = signal(false);
  const c = createAerial({engine: signal(g), offer: () => MORRO, sharp: () => now.value});
  now.value = true;
  markUnavailable('aerial');
  assert.deepEqual(shape(g.overlay), [[`${ID}:png32:preview`, '256,256', 'png32'], [`${ID}:png32`, '512,512', 'png32']], 'a failure while sharpening keeps the preview under the fallback');
  markUnavailable('aerial');
  const before = g.calls;
  g.settle();
  assert.equal(g.calls, before, 'a failed fallback is not redrawn at the next idle');
  c.destroy();
  assert.equal(g.idle.size, 0);
  unavailable.value = [];
});

test('the sharp start waits for the first settled view, then for the seafloor\'s first view or SHARP_WAIT_MAX_MS, and never re-holds', t => {
  t.mock.timers.enable({apis: ['setTimeout']});
  const idle = signal(false), busy = signal(true);
  const s = createSharpStart(() => idle.value, () => busy.value);
  busy.value = false;
  assert.equal(s.ready.value, false, 'nothing before the map has first settled');
  busy.value = true;
  idle.value = true;
  assert.equal(s.ready.value, false);
  busy.value = false;
  assert.equal(s.ready.value, true, 'the seafloor\'s first view is in');
  busy.value = true;
  assert.equal(s.ready.value, true, 'latched');
  s.destroy();

  const capped = createSharpStart(() => true, () => true);
  t.mock.timers.tick(SHARP_WAIT_MAX_MS - 1);
  assert.equal(capped.ready.value, false);
  t.mock.timers.tick(1);
  assert.equal(capped.ready.value, true, 'a seafloor that never lands holds the full image at most SHARP_WAIT_MAX_MS');
  capped.destroy();

  const stopped = createSharpStart(() => true, () => true);
  stopped.destroy();
  t.mock.timers.tick(SHARP_WAIT_MAX_MS);
  assert.equal(stopped.ready.value, false, 'destroyed: the timer is cancelled');
});
