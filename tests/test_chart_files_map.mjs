// RF0850-2 (Cambria 404s part 2b): the Chart's coastline and depth contours skip a file the loaded
// region.json does not list (`chart_files`, web/chart-files.ts). Unknown or listed: today's behaviour.
// Offline: `publishedChartFiles` is set directly and the contour layer gets a fake engine and fetchFn.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {signal} from '@preact/signals';
import {chartFilesPending, publishedChartFiles} from '../web/chart-files.ts';
import {SHORELINE_DETAIL_ZOOM, coastlineFetchPath, coastlineSource, shorelineFor, shorelineOverviewURL, shorelinePublished, shorelineURL} from '../web/map/coastline.ts';
import {DETAIL_ZOOM, contourState, contoursFor, createDepthContours, depthContoursOverviewURL, depthContoursURL} from '../web/map/depth-contours.ts';
import {ZOOM_OFFSET} from '../web/map/engine.ts';
import {camera} from '../web/map/stage.ts';
import {configureStore, syncFromURL} from '../web/state.ts';

const PAGE = 'https://s.test/map';
const fixture = name => JSON.parse(readFileSync(new URL(`../dist/regions/morro-bay/${name}`, import.meta.url), 'utf8'));
const FULL = fixture('depth-contours.geojson'), OVERVIEW = fixture('depth-contours-overview.geojson');
const EMPTY = {type: 'FeatureCollection', features: []};
const ATTRIBUTION = 'NOAA NGS · CUSP shoreline';
const DETAIL = SHORELINE_DETAIL_ZOOM + ZOOM_OFFSET;
const publish = (region, files) => { publishedChartFiles.value = region === null ? null : {region, files}; };
const flush = () => new Promise(resolve => setImmediate(resolve));
test.afterEach(() => publish(null));

test('nothing published: the shoreline and its source are exactly today\'s', () => {
  publish(null);
  assert.deepEqual(coastlineSource('morro-bay', PAGE), {type: 'geojson', data: 'https://s.test/regions/morro-bay/shoreline.geojson', attribution: ATTRIBUTION});
  assert.equal(shorelineFor('morro-bay', DETAIL - 1), shorelineOverviewURL('morro-bay'));
  assert.equal(shorelineFor('morro-bay', DETAIL), shorelineURL('morro-bay'));
  assert.equal(shorelineFor('morro-bay', 1, true), shorelineURL('morro-bay'));
  assert.equal(shorelinePublished('morro-bay'), true);
  assert.equal(coastlineFetchPath('morro-bay', DETAIL - 1), shorelineOverviewURL('morro-bay'));
  publish('morro-bay', null);
  assert.equal(shorelinePublished('morro-bay'), true, 'a region.json without a list fails open');
  assert.deepEqual(coastlineSource('morro-bay', PAGE).data, 'https://s.test/regions/morro-bay/shoreline.geojson');
});

test('neither shoreline listed: an empty source, no fetch path, not published', () => {
  for (const files of [[], ['poster.svg', 'land-water.json'], ['shoreline.geojson.bak', 'Shoreline-overview.geojson']]) {
    publish('cambria-san-simeon', files);
    assert.equal(shorelinePublished('cambria-san-simeon'), false, JSON.stringify(files));
    assert.deepEqual(coastlineSource('cambria-san-simeon', PAGE), {type: 'geojson', data: EMPTY, attribution: ATTRIBUTION});
    assert.deepEqual(coastlineSource('cambria-san-simeon', PAGE, shorelineOverviewURL('cambria-san-simeon')).data, EMPTY, 'a named path is not requested either');
    for (const zoom of [1, DETAIL - 1, DETAIL, 20]) assert.equal(coastlineFetchPath('cambria-san-simeon', zoom), null);
    assert.equal(coastlineFetchPath('cambria-san-simeon', 1, true), null, 'nor after a detail load');
  }
});

test('only the full shoreline listed: the full file at every zoom, never the overview', () => {
  publish('r', ['shoreline.geojson']);
  assert.equal(shorelinePublished('r'), true);
  for (const zoom of [1, DETAIL - 1, DETAIL, 20]) {
    assert.equal(shorelineFor('r', zoom), shorelineURL('r'), `zoom ${zoom}`);
    assert.equal(coastlineFetchPath('r', zoom), shorelineURL('r'));
  }
  assert.equal(coastlineSource('r', PAGE, shorelineFor('r', 1)).data, 'https://s.test/regions/r/shoreline.geojson');
});

test('overview_only_never_upgrades: only the overview listed -> the overview at every zoom and after a detail load', () => {
  publish('r', ['shoreline-overview.geojson']);
  assert.equal(shorelinePublished('r'), true);
  for (const zoom of [1, DETAIL - 1, DETAIL, 20]) {
    assert.equal(shorelineFor('r', zoom), shorelineOverviewURL('r'), `zoom ${zoom}`);
    assert.equal(shorelineFor('r', zoom, true), shorelineOverviewURL('r'), `detail latch, zoom ${zoom}`);
    assert.equal(coastlineFetchPath('r', zoom, true), shorelineOverviewURL('r'));
  }
  publish('r', ['shoreline-overview.geojson', 'shoreline.geojson']);
  assert.equal(shorelineFor('r', DETAIL - 1), shorelineOverviewURL('r'), 'both listed: unchanged');
  assert.equal(shorelineFor('r', DETAIL), shorelineURL('r'), 'both listed: full from the detail zoom');
  assert.equal(shorelineFor('r', 1, true), shorelineURL('r'), 'both listed: the detail latch stays full');
});

test('another region\'s list says nothing about this one (fail open)', () => {
  publish('a', []);
  assert.equal(shorelinePublished('b'), true);
  assert.deepEqual(coastlineSource('b', PAGE), {type: 'geojson', data: 'https://s.test/regions/b/shoreline.geojson', attribution: ATTRIBUTION});
  assert.equal(shorelineFor('b', DETAIL - 1), shorelineOverviewURL('b'));
  assert.equal(shorelineFor('b', DETAIL), shorelineURL('b'));
  assert.equal(coastlineFetchPath('b', DETAIL - 1), shorelineOverviewURL('b'));
});

test('pending: only this region\'s loading list waits; a pending list fails open for every file, and an empty path draws nothing', () => {
  publishedChartFiles.value = {region: 'r', files: null, pending: true};
  assert.equal(chartFilesPending('r'), true);
  assert.equal(chartFilesPending('b'), false, 'another region is not waiting');
  assert.equal(shorelinePublished('r'), true, 'pending is not a list: chartFileListed still fails open');
  assert.deepEqual(coastlineSource('r', PAGE, '').data, EMPTY, 'no shoreline yet: no request');
  publish('r', ['shoreline.geojson']);
  assert.equal(chartFilesPending('r'), false);
  publish(null);
  assert.equal(chartFilesPending('r'), false, 'nothing published: not waiting (the landing page, tests)');
});

/** The contour layer for region `r` over a fake engine; every fetch answers 404 unless the test serves it. */
function contours(t, {serve = () => null, id = 'r'} = {}) {
  globalThis.location = {href: `https://s.test/map?region=${id}`};
  configureStore({v2: true, storage: null});
  syncFromURL(location.href);
  camera.value = {latitude: 35.35, longitude: -120.95, zoom: 11};
  const asked = [];
  const fetchFn = async url => {
    const path = new URL(url).pathname.slice(1);
    asked.push(path);
    const body = serve(path);
    return body ? {ok: true, status: 200, json: async () => body} : {ok: false, status: 404, json: async () => ({})};
  };
  const overlays = [];
  const engine = signal({setOverlay(_id, o) { overlays.push(o); }, setData() {}});
  const layer = createDepthContours({engine, fetchFn, page: () => location.href, palette: () => ({mapContourWidth: '1'}), now: () => Date.parse('2026-10-20T18:00:00Z')});
  t.after(() => { layer.destroy(); camera.value = null; });
  const detail = async () => { camera.value = {...camera.value, zoom: DETAIL_ZOOM + ZOOM_OFFSET}; await flush(); await flush(); };
  return {asked, detail, layer, overlays};
}

test('contours unlisted: no request at any zoom, and the layer settles as none with no row', async t => {
  publish('r', []);
  const {asked, detail} = contours(t);
  await flush(); await flush();
  assert.deepEqual(asked, []);
  assert.equal(contourState.value.status, 'none');
  assert.equal(contourState.value.note, '');
  await detail();
  assert.deepEqual(asked, [], 'the full form is not asked for either');
  assert.equal(contourState.value.status, 'none');
});

test('contours: only the overview listed — fetched once, drawn, and kept (not none) at the detail zoom with no full request', async t => {
  publish('morro-bay', ['depth-contours-overview.geojson']);
  const {asked, detail, overlays} = contours(t, {id: 'morro-bay', serve: path => path.endsWith('overview.geojson') ? OVERVIEW : null});
  await flush(); await flush();
  assert.deepEqual(asked, [depthContoursOverviewURL('morro-bay')]);
  assert.equal(contourState.value.status, 'drawn');
  await detail();
  assert.deepEqual(asked, [depthContoursOverviewURL('morro-bay')]);
  assert.equal(contourState.value.status, 'drawn');
  assert.ok(contourState.value.sources.length > 0, 'sources retained');
  assert.ok(overlays.some(o => o !== null) && !overlays.slice(overlays.findIndex(o => o !== null)).includes(null), 'drawn, then never cleared');
});

test('contours: only the full form listed — asked once at low zoom, drawn, stays drawn; the overview is never asked for', async t => {
  publish('morro-bay', ['depth-contours.geojson']);
  const {asked, detail, overlays} = contours(t, {id: 'morro-bay', serve: path => path.endsWith('/depth-contours.geojson') ? FULL : null});
  await flush(); await flush();
  assert.deepEqual(asked, [depthContoursURL('morro-bay')]);
  assert.equal(contourState.value.status, 'drawn');
  await detail();
  assert.deepEqual(asked, [depthContoursURL('morro-bay')]);
  assert.equal(contourState.value.status, 'drawn');
  assert.ok(overlays.some(o => o !== null) && !overlays.slice(overlays.findIndex(o => o !== null)).includes(null), 'drawn, then never cleared');
});

test('contours: a single form at initial high zoom, and lookalike filenames, select only a real listed form', async t => {
  for (const [files, want] of [[['depth-contours.geojson'], depthContoursURL], [['depth-contours-overview.geojson'], depthContoursOverviewURL]]) {
    publish('morro-bay', files);
    assert.equal(contoursFor('morro-bay', 1), want('morro-bay'));
    assert.equal(contoursFor('morro-bay', DETAIL_ZOOM + ZOOM_OFFSET), want('morro-bay'));
    assert.equal(contoursFor('morro-bay', 1, true), want('morro-bay'));
  }
  publish('morro-bay', ['depth-contours.geojson.bak', 'Depth-contours-overview.geojson']);
  assert.equal(contoursFor('morro-bay', 1), depthContoursOverviewURL('morro-bay'), 'neither listed: the zoom rule');
  assert.equal(contoursFor('morro-bay', DETAIL_ZOOM + ZOOM_OFFSET), depthContoursURL('morro-bay'));
  publish('other', ['depth-contours.geojson']);
  assert.equal(contoursFor('morro-bay', 1), depthContoursOverviewURL('morro-bay'), 'another region\'s list: fail open');
  publish('morro-bay', null);
  assert.equal(contoursFor('morro-bay', 1), depthContoursOverviewURL('morro-bay'), 'no list: fail open');
});

test('contours: a single listed form that 404s stays none and does not fall back to the other form', async t => {
  publish('r', ['depth-contours.geojson']);
  const {asked, detail} = contours(t);
  await flush(); await flush();
  await detail();
  assert.deepEqual(asked, [depthContoursURL('r')]);
  assert.equal(contourState.value.status, 'none');
});

test('contours: the effect runs while region.json is loading, then the list arrives without them — no request ever', async t => {
  publishedChartFiles.value = {region: 'r', files: null, pending: true};
  const {asked, detail} = contours(t);
  await flush(); await flush();
  assert.deepEqual(asked, [], 'nothing is asked while the list is pending');
  assert.equal(contourState.value.status, 'loading');
  publish('r', []);
  await flush(); await flush();
  assert.deepEqual(asked, [], 'the published list lacks both forms: still no request');
  assert.equal(contourState.value.status, 'none');
  await detail();
  assert.deepEqual(asked, []);
});

test('contours: pending, then listed — one overview request; pending, then a failed load — fails open as before', async t => {
  publishedChartFiles.value = {region: 'r', files: null, pending: true};
  const listed = contours(t);
  await flush();
  assert.deepEqual(listed.asked, []);
  publish('r', ['depth-contours-overview.geojson', 'depth-contours.geojson']);
  await flush(); await flush();
  assert.deepEqual(listed.asked, [depthContoursOverviewURL('r')]);
  listed.layer.destroy();
  publishedChartFiles.value = {region: 'r', files: null, pending: true};
  const failed = contours(t);
  await flush();
  assert.deepEqual(failed.asked, []);
  publish('r', null);  // App.tsx loadRegion: a failed read leaves no list
  await flush(); await flush();
  assert.deepEqual(failed.asked, [depthContoursOverviewURL('r')]);
});

test('contours listed or unknown: today\'s sequence (one overview, then one full at the detail zoom)', async t => {
  for (const files of ['unknown', 'other', null, ['depth-contours-overview.geojson', 'depth-contours.geojson']]) {
    if (files === 'unknown') publish(null); else if (files === 'other') publish('a', []); else publish('r', files);
    const {asked, detail, layer} = contours(t);
    await flush(); await flush();
    assert.deepEqual(asked, [depthContoursOverviewURL('r')], String(files));
    await detail();
    assert.deepEqual(asked, [depthContoursOverviewURL('r')], 'a 404 overview: the full form is not asked (today)');
    layer.destroy();
  }
  publish('r', ['depth-contours.geojson', 'depth-contours-overview.geojson']);
  const served = contours(t, {serve: () => ({type: 'FeatureCollection', features: []})});
  await flush(); await flush();
  await served.detail();
  assert.deepEqual(served.asked, [depthContoursOverviewURL('r'), depthContoursURL('r')]);
});
