// RF0935-1: Spear's distance from shore (web/shore-distance.ts) and the trip export's contour tracks
// (web/planner.ts loadContourFile) make no request for a file the loaded region.json's `chart_files`
// lacks; anything unknown (nothing loaded, another region, no list) fails open and asks as before.
import assert from 'node:assert/strict';
import test from 'node:test';
import {publishedChartFiles} from '../web/chart-files.ts';
import {loadShoreLines, resetShoreLines, shoreLines} from '../web/shore-distance.ts';
import {loadContourFile} from '../web/planner.ts';

const PAGE = 'https://s.test/app/', page = () => PAGE, TODAY = '2026-09-22';
const LINE = {type: 'FeatureCollection', features: [{type: 'Feature', geometry: {type: 'LineString', coordinates: [[-121, 35], [-121.1, 35.1]]}}]};
const counting = (respond = () => new Response(JSON.stringify(LINE))) => {
  const calls = [];
  return {calls, fn: async url => { calls.push(String(url)); return respond(url); }};
};
const publish = (region, files) => { publishedChartFiles.value = region === null ? null : {region, files}; };
const reply = status => () => new Response(status === 200 ? '{}' : '', {status});
const fresh = () => { resetShoreLines(); publish(null); };

test('nothing published: the shoreline and the contours are requested once, as today', async () => {
  fresh();
  const shore = counting();
  await loadShoreLines('r', PAGE, shore.fn);
  assert.deepEqual(shore.calls, ['https://s.test/app/regions/r/shoreline-overview.geojson']);
  assert.equal(shoreLines.value.lines.length, 1);
  const contours = counting(reply(404));
  assert.deepEqual(await loadContourFile('r', TODAY, contours.fn, page), {collection: null});
  assert.deepEqual(contours.calls, ['https://s.test/app/regions/r/depth-contours.geojson']);
});

test('an unlisted overview is not requested and claims no distance; once listed it loads', async () => {
  fresh();
  const shore = counting();
  shoreLines.value = {region: 'r', lines: [[[0, 0], [1, 1]]]};
  publish('r', []);
  await loadShoreLines('r', PAGE, shore.fn);
  assert.equal(shore.calls.length, 0);
  assert.deepEqual(shoreLines.value, {region: 'r', lines: null}, 'stale lines for r are cleared');
  await loadShoreLines('r', PAGE, shore.fn);
  assert.equal(shore.calls.length, 0, 'a repeat visit still asks nothing');
  publish('r', ['shoreline-overview.geojson']);
  await loadShoreLines('r', PAGE, shore.fn);
  assert.equal(shore.calls.length, 1, 'no stale memo from the unlisted visit');
  assert.equal(shoreLines.value.lines.length, 1);
  fresh();
});

test('a list for another region or no list fails open for both files', async () => {
  for (const [region, files] of [['a', []], ['b', null]]) {
    fresh(); publish(region, files);
    const shore = counting(), contours = counting(reply(404));
    await loadShoreLines('b', PAGE, shore.fn);
    assert.equal(shore.calls.length, 1, `${region}/${files}: shoreline asked`);
    assert.equal(shoreLines.value.lines.length, 1);
    assert.deepEqual(await loadContourFile('b', TODAY, contours.fn, page), {collection: null});
    assert.equal(contours.calls.length, 1, `${region}/${files}: contours asked`);
  }
  fresh();
});

test('unlisted contours read as no file with no request; listed contours keep today\'s answers', async () => {
  fresh(); publish('r', ['shoreline-overview.geojson']);
  const none = counting(reply(200));
  assert.deepEqual(await loadContourFile('r', TODAY, none.fn, page), {collection: null});
  assert.equal(none.calls.length, 0);
  publish('r', ['depth-contours.geojson']);
  const missing = counting(reply(404));
  assert.deepEqual(await loadContourFile('r', TODAY, missing.fn, page), {collection: null});
  assert.equal(missing.calls.length, 1);
  const failed = counting(reply(500));
  assert.match((await loadContourFile('r', TODAY, failed.fn, page)).refused, /did not load/);
  assert.equal(failed.calls.length, 1);
  const thrown = await loadContourFile('r', TODAY, async () => { throw new Error('offline'); }, page);
  assert.match(thrown.refused, /did not load/);
  fresh();
});

test('a late listed answer never replaces an unlisted region visited after it', async () => {
  fresh(); publish('r', ['shoreline-overview.geojson']);
  let open;
  const held = new Promise(resolve => { open = resolve; });
  const slow = counting(async () => { await held; return new Response(JSON.stringify(LINE)); });
  const first = loadShoreLines('r', PAGE, slow.fn);
  publish('s', []);
  await loadShoreLines('s', PAGE, slow.fn);
  assert.deepEqual(shoreLines.value, {region: 's', lines: null});
  open(); await first;
  assert.deepEqual(shoreLines.value, {region: 's', lines: null}, 'the obsolete r answer is not published');
  assert.equal(slow.calls.length, 1, 'only r was asked');
  fresh();
});
