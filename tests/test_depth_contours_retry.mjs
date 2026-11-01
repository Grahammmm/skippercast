// SC1737-04: a dropped depth-contour read (the fetch throws or times out, 429, 5xx) is asked again on the
// first camera move CONTOUR_RETRY_MS after it, not 'did not load' for the whole visit; a 404, an unlisted
// file or a file failing its check is never asked again. Same harness shape as tests/test_depth_contours.mjs.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {signal} from '@preact/signals';
import {publishedChartFiles} from '../web/chart-files.ts';
import {
  CONTOUR_RETRY_MS, DEPTH_EDGE, DEPTH_HIT, DEPTH_LABEL, DEPTH_LABEL_MINOR, DEPTH_LINE, DEPTH_UNRESOLVED_FILL, DEPTH_UNRESOLVED_LINE, DETAIL_ZOOM, NOTES,
  contourState, createDepthContours, depthContoursOverviewURL, depthContoursURL,
} from '../web/map/depth-contours.ts';
import {ZOOM_OFFSET} from '../web/map/engine.ts';
import {DEPTH_CONTOURS_SOURCE} from '../web/map/layers.ts';
import {MPA_FILL} from '../web/map/mpa.ts';
import {readPalette} from '../web/map/palette.ts';
import {camera} from '../web/map/stage.ts';
import {configureStore, region, syncFromURL} from '../web/state.ts';

const ROOT = new URL('..', import.meta.url);
const json = path => JSON.parse(readFileSync(new URL(path, ROOT), 'utf8'));
const FULL = json('dist/regions/morro-bay/depth-contours.geojson');
const OVERVIEW = json('dist/regions/morro-bay/depth-contours-overview.geojson');
const T0 = Date.parse('2026-10-20T18:00:00Z');
const OV = depthContoursOverviewURL('morro-bay'), DETAIL = depthContoursURL('morro-bay');
const IDS = [DEPTH_UNRESOLVED_FILL, DEPTH_UNRESOLVED_LINE, DEPTH_EDGE, DEPTH_LINE, DEPTH_HIT, DEPTH_LABEL, DEPTH_LABEL_MINOR];
const flush = async () => { for (let i = 0; i < 4; i++) await new Promise(resolve => setImmediate(resolve)); };

/** `script[path]` answers that path's requests in order ('throw', 'timeout', a status, or a file for a 200); then `files`, else 404. */
function setup(t, {files = {}, script = {}} = {}) {
  globalThis.location = {href: 'https://s.test/map?region=morro-bay'};
  configureStore({v2: true, storage: null});
  syncFromURL(location.href);
  camera.value = {latitude: 35.35, longitude: -120.95, zoom: 11};
  const asked = [], calls = [], clock = {now: T0};
  const fetchFn = async url => {
    const path = new URL(url).pathname.slice(1), next = script[path]?.shift();
    asked.push(path);
    if (next === 'throw') throw new TypeError('network dropped');
    if (next === 'timeout') throw new DOMException('timed out', 'TimeoutError');
    if (typeof next === 'number') return {ok: next < 300, status: next, json: async () => ({})};
    const body = next ?? files[path];
    return body ? {ok: true, status: 200, json: async () => structuredClone(body)} : {ok: false, status: 404, json: async () => ({})};
  };
  const engine = signal({setOverlay: (layer, o, before) => calls.push(['overlay', layer, o && o.layers.map(l => l.id), before ?? null]),
    setData: (id, data) => calls.push(['data', id, data.features.length])});
  const layer = createDepthContours({engine, fetchFn, page: () => location.href, palette: () => readPalette(n => n), now: () => clock.now});
  t.after(() => { layer.destroy(); camera.value = null; publishedChartFiles.value = null; });
  /** Move the camera a little at `seconds` after the first read. */
  const move = (seconds, zoom = camera.value.zoom) => {
    clock.now = T0 + seconds * 1000;
    camera.value = {...camera.value, latitude: camera.value.latitude + 0.0001, zoom};
  };
  return {asked, calls, move};
}
const drawnUnderMPA = calls => calls.filter(c => c[0] === 'overlay' && c[2]).length === 1
  && calls.some(c => c[0] === 'overlay' && c[2] && c[2].join() === IDS.join() && c[3] === MPA_FILL);

test('a thrown read fails; a move before the back-off asks nothing; the first move after it asks once and draws', async t => {
  assert.equal(CONTOUR_RETRY_MS, 60_000);
  const {asked, calls, move} = setup(t, {files: {[OV]: OVERVIEW}, script: {[OV]: ['throw']}});
  await flush();
  assert.deepEqual(asked, [OV]);
  assert.equal(contourState.value.status, 'failed');
  assert.equal(contourState.value.note, NOTES.failed);
  move(30); await flush();
  move(59.999); await flush();
  assert.equal(asked.length, 1, 'no request inside the back-off');
  move(61);
  assert.equal(contourState.value.status, 'failed', 'no loading state: the failed note stays until the answer');
  move(61.5);
  await flush();
  assert.deepEqual(asked, [OV, OV], 'one request however many moves come before the answer');
  assert.equal(contourState.value.status, 'drawn');
  assert.ok(drawnUnderMPA(calls), 'drawn under the protected areas, once');
  move(200); await flush();
  assert.equal(asked.length, 2, 'a drawn file is not asked again');
});

for (const drop of [503, 429, 500, 599, 'timeout']) {
  test(`a ${drop} read is retried after the back-off and the retry draws the overlay under the protected areas`, async t => {
    const {asked, calls, move} = setup(t, {files: {[OV]: OVERVIEW}, script: {[OV]: [drop]}});
    await flush();
    assert.equal(contourState.value.status, 'failed');
    assert.equal(calls.some(c => c[2]), false);
    move(45); await flush();
    assert.equal(asked.length, 1);
    move(61); await flush();
    assert.deepEqual(asked, [OV, OV]);
    assert.equal(contourState.value.status, 'drawn');
    assert.ok(drawnUnderMPA(calls));
  });
}

for (const refusal of [404, 403, 400, 410, 600]) {
  test(`a ${refusal} answer is never asked again`, async t => {
    const {asked, move} = setup(t, {script: {[OV]: [refusal]}});
    await flush();
    assert.equal(contourState.value.status, refusal === 404 ? 'none' : 'failed');
    move(61); await flush();
    move(600); await flush();
    assert.deepEqual(asked, [OV]);
  });
}

test('a file failing its check (another region_id) fails and is never asked again', async t => {
  const wrong = structuredClone(OVERVIEW);
  wrong.provenance.region_id = 'cambria-san-simeon';
  const {asked, move} = setup(t, {files: {[OV]: wrong}});
  await flush();
  assert.equal(contourState.value.status, 'failed');
  move(61); await flush();
  move(600); await flush();
  assert.deepEqual(asked, [OV]);
});

test('a file the region does not list settles as none and is never asked, even after the back-off', async t => {
  publishedChartFiles.value = {region: 'morro-bay', files: []};
  const {asked, move} = setup(t, {files: {[OV]: OVERVIEW}});
  move(1); await flush();
  assert.equal(contourState.value.status, 'none');
  move(61); await flush();
  move(600); await flush();
  assert.deepEqual(asked, [], 'the unlisted file is never requested');
});

test('a retry that drops again waits a new back-off: two drops then success is three requests', async t => {
  const {asked, move} = setup(t, {files: {[OV]: OVERVIEW}, script: {[OV]: ['throw', 503]}});
  await flush();
  move(61); await flush();
  assert.equal(asked.length, 2);
  assert.equal(contourState.value.status, 'failed');
  move(100); await flush();
  assert.equal(asked.length, 2, 'the back-off restarts from the second drop (61 s)');
  move(120.999); await flush();
  assert.equal(asked.length, 2);
  move(121); await flush();
  assert.deepEqual(asked, [OV, OV, OV]);
  assert.equal(contourState.value.status, 'drawn');
});

test('a region switch while a drop waits asks the new region at once; the old back-off has no effect there', async t => {
  const other = structuredClone(OVERVIEW);
  other.provenance.region_id = 'cambria-san-simeon';
  const CAMBRIA = depthContoursOverviewURL('cambria-san-simeon');
  const {asked, move} = setup(t, {files: {[OV]: OVERVIEW, [CAMBRIA]: other}, script: {[OV]: ['throw']}});
  await flush();
  assert.equal(contourState.value.status, 'failed');
  region.value = 'cambria-san-simeon';
  await flush();
  assert.deepEqual(asked, [OV, CAMBRIA], 'asked at once, inside the old back-off');
  assert.equal(contourState.value.status, 'drawn');
  move(61); await flush();
  move(600); await flush();
  assert.deepEqual(asked, [OV, CAMBRIA], 'no stray retry for morro-bay, none for the drawn region');
});

test('reaching the detail zoom after an overview drop asks the full file at once', async t => {
  const {asked, calls, move} = setup(t, {files: {[OV]: OVERVIEW, [DETAIL]: FULL}, script: {[OV]: ['throw']}});
  await flush();
  move(5, DETAIL_ZOOM + ZOOM_OFFSET); await flush();
  assert.deepEqual(asked, [OV, DETAIL]);
  assert.equal(contourState.value.status, 'drawn');
  assert.deepEqual(calls.at(-1), ['data', DEPTH_CONTOURS_SOURCE, FULL.features.length]);
  move(61, 9); await flush();
  assert.equal(asked.length, 2, 'the full file stays: the dropped overview is not asked again');
});
