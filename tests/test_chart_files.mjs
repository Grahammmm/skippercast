// RF0850-1 (web/chart-files.ts): once region.json has loaded, the land-water index, the poster and the
// offline pack's two shoreline forms are not requested when its `chart_files` lacks them; anything
// unknown (nothing loaded, another region, no or a malformed list) fails open and asks as before.
import assert from 'node:assert/strict';
import test from 'node:test';
import {chartFileListed, chartFilesOf, publishedChartFiles} from '../web/chart-files.ts';
import {landWater, loadLandWater, resetLandWater} from '../web/land-water.ts';
import {loadPoster, poster} from '../web/map/poster.ts';
import {shorelineOverviewURL, shorelineURL} from '../web/map/coastline.ts';
import {packFiles} from '../web/trip.ts';

const FOUR = ['land-water.json', 'poster.svg', 'shoreline.geojson', 'shoreline-overview.geojson'];
const PAGE = 'https://s.test/map';
const counting = (respond = () => new Response('', {status: 404})) => {
  const calls = [];
  const fn = async (url, init) => { calls.push(url); return respond(url, init); };
  return {fn, calls};
};
const publish = (region, files) => { publishedChartFiles.value = region === null ? null : {region, files}; };

test('chartFilesOf keeps a list of names, frozen, and refuses anything else', () => {
  const names = chartFilesOf(['poster.svg', 'land-water.json']);
  assert.deepEqual(names, ['poster.svg', 'land-water.json']);
  assert.ok(Object.isFrozen(names));
  const raw = ['poster.svg'], copy = chartFilesOf(raw);
  raw.push('land-water.json');
  assert.deepEqual(copy, ['poster.svg'], 'a copy, not the parsed array');
  assert.deepEqual(chartFilesOf([]), []);
  assert.ok(Object.isFrozen(chartFilesOf([])));
  for (const bad of [null, undefined, 'poster.svg', {}, [1], ['a', 2], [null]]) assert.equal(chartFilesOf(bad), null, JSON.stringify(bad));
});

test('chartFileListed fails open unless this region\'s list is known and lacks the name', () => {
  publish(null);
  for (const name of FOUR) assert.equal(chartFileListed('cambria-san-simeon', name), true, 'nothing published yet');
  publish('a', []);
  for (const name of FOUR) assert.equal(chartFileListed('b', name), true, 'another region\'s list says nothing');
  publish('cambria-san-simeon', null);
  for (const name of FOUR) assert.equal(chartFileListed('cambria-san-simeon', name), true, 'no or a malformed list');
  publish('cambria-san-simeon', []);
  for (const name of FOUR) assert.equal(chartFileListed('cambria-san-simeon', name), false, name);
  publish('r', ['poster.svg']);
  assert.equal(chartFileListed('r', 'poster.svg'), true);
  assert.equal(chartFileListed('r', 'land-water.json'), false);
  assert.equal(chartFileListed('r', 'POSTER.SVG'), false, 'names match exactly');
  publish(null);
});

test('land-water: an unlisted index settles unavailable with no request, memoized, and a retry asks nothing', async () => {
  resetLandWater(); publish('r', ['poster.svg']);
  const {fn, calls} = counting();
  const state = await loadLandWater('r', fn);
  assert.deepEqual([state.region, state.state, state.model], ['r', 'unavailable', null]);
  assert.equal(landWater.value, state);
  assert.equal(await loadLandWater('r', fn), state, 'the memo');
  assert.equal(await loadLandWater('r', fn, {retryTransient: true}), state, 'not a transient failure');
  assert.equal(calls.length, 0);
  publish(null); resetLandWater();
});

test('land-water: a listed index, or none published, is requested once as before', async () => {
  for (const files of [['land-water.json'], null, 'nothing']) {
    resetLandWater();
    if (files === 'nothing') publish(null); else publish('r', files);
    const {fn, calls} = counting();
    const state = await loadLandWater('r', fn);
    assert.equal(state.state, 'unavailable', 'the fake answers 404');
    assert.deepEqual(calls, ['http://localhost/regions/r/land-water.json'], String(files));
  }
  publish(null); resetLandWater();
});

test('land-water: another region is still asked, and an unlisted switch drops the old request', async () => {
  resetLandWater(); publish('a', []);
  const {fn, calls} = counting();
  await loadLandWater('b', fn);
  assert.deepEqual(calls, ['http://localhost/regions/b/land-water.json'], 'fail open for a region whose list has not loaded');
  resetLandWater(); publish(null);
  const gate = Promise.withResolvers();
  const slow = loadLandWater('a', () => gate.promise);
  await Promise.resolve();
  publish('b', []);
  assert.equal((await loadLandWater('b', fn)).state, 'unavailable');
  gate.resolve(new Response('{}'));
  assert.equal((await slow).region, 'b', 'the replaced request writes nothing');
  assert.deepEqual([landWater.value.region, landWater.value.state], ['b', 'unavailable']);
  assert.equal(calls.length, 1);
  publish(null); resetLandWater();
});

test('poster: an unlisted poster is not requested; a listed or unknown one is', async () => {
  poster.value = null; publish('r', []);
  const {fn, calls} = counting();
  await loadPoster('r', PAGE, () => false, fn);
  assert.equal(calls.length, 0);
  assert.equal(poster.value, null);
  publish('r', ['poster.svg']);
  await loadPoster('r', PAGE, () => false, fn);
  publish(null);
  await loadPoster('r', PAGE, () => false, fn);
  assert.deepEqual(calls, ['https://s.test/regions/r/poster.svg', 'https://s.test/regions/r/poster.svg']);
  assert.equal(poster.value, null, 'a 404 shows nothing');
});

test('offline pack: unlisted shoreline forms are left out; everything else keeps its order', () => {
  const urls = () => packFiles('r', PAGE, ['/assets/app.js']).map(([url]) => url);
  const line = new URL(shorelineURL('r'), PAGE).href, overview = new URL(shorelineOverviewURL('r'), PAGE).href;
  publish(null);
  const today = urls();
  assert.equal(today.length, 7);
  assert.deepEqual(today.slice(2, 4), [line, overview]);
  assert.equal(today.at(-1), 'https://s.test/assets/app.js');
  publish('r', FOUR);
  assert.deepEqual(urls(), today, 'all listed: today\'s list');
  publish('other', []);
  assert.deepEqual(urls(), today, 'another region: today\'s list');
  publish('r', []);
  assert.deepEqual(urls(), today.filter(u => u !== line && u !== overview));
  publish('r', ['shoreline.geojson']);
  assert.deepEqual(urls(), today.filter(u => u !== overview));
  publish(null);
});
