// RF0145-8: the land/water index waits for explicitly pending region.json before it is requested.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import test, {afterEach, beforeEach} from 'node:test';
import {loadLandWater, ensureLandWater, landWater, resetLandWater} from '../web/land-water.ts';
import {publishedChartFiles} from '../web/chart-files.ts';

const fixture = JSON.parse(readFileSync(new URL('./fixtures/sp1503_land_water_retry/products.json', import.meta.url), 'utf8'));
const REGION = fixture.region;
const linesText = JSON.stringify(fixture.lines);
const index = {...fixture.index, lines: {sha256: createHash('sha256').update(linesText).digest('hex')}};
const pending = region => ({region, files: null, pending: true});
const recorder = (make = () => new Response(JSON.stringify(index))) => {
  const urls = [];
  const fetchFn = async url => { urls.push(url); return make(); };
  return {urls, fetchFn};
};
const tick = async () => { for (let i = 0; i < 5; i++) await new Promise(resolve => setImmediate(resolve)); };

beforeEach(() => { resetLandWater(); publishedChartFiles.value = null; });
afterEach(() => { resetLandWater(); publishedChartFiles.value = null; });

test('pending_then_omitted_never_requests', async () => {
  const {urls, fetchFn} = recorder();
  publishedChartFiles.value = pending(REGION);
  const point = Object.values(fixture.points)[0];
  const ensured = ensureLandWater(REGION, [point], fetchFn);
  const calls = [loadLandWater(REGION, fetchFn), loadLandWater(REGION, fetchFn)];
  let settled = false;
  calls[0].then(() => { settled = true; });
  await tick();
  assert.equal(urls.length, 0, 'no request while pending');
  assert.equal(settled, false, 'callers keep waiting');
  assert.equal(landWater.peek().state, 'loading');
  publishedChartFiles.value = {region: REGION, files: ['poster.svg', 'Land-Water.json']};
  for (const state of await Promise.all(calls)) { assert.equal(state.state, 'unavailable'); assert.equal(state.model, null); }
  assert.deepEqual((await ensured)(point), {state: 'unknown', reason: 'unavailable'});
  assert.equal(urls.length, 0, 'omitted list never requests');
  await loadLandWater(REGION, fetchFn, {retryTransient: true});
  assert.equal(urls.length, 0, 'retry of an omission stays memoized');
});

test('pending_then_listed_coalesces', async () => {
  const {urls, fetchFn} = recorder();
  publishedChartFiles.value = pending(REGION);
  const calls = [loadLandWater(REGION, fetchFn), loadLandWater(REGION, fetchFn)];
  await tick();
  assert.equal(urls.length, 0);
  publishedChartFiles.value = {region: REGION, files: ['land-water.json']};
  const states = await Promise.all(calls);
  assert.equal(urls.length, 1, 'one request for all callers');
  assert.ok(states.every(s => s.state === 'ready'));
  publishedChartFiles.value = {region: REGION, files: ['land-water.json', 'poster.svg']};
  await tick();
  assert.equal(urls.length, 1, 'later publication writes read nothing');
});

test('metadata_failure_ends_wait_fail_open', async () => {
  const {urls, fetchFn} = recorder();
  publishedChartFiles.value = pending(REGION);
  const call = loadLandWater(REGION, fetchFn);
  await tick();
  publishedChartFiles.value = {region: REGION, files: null};
  assert.equal((await call).state, 'ready');
  assert.equal(urls.length, 1);
});

test('non_pending_initial_state_requests_at_once', async () => {
  for (const initial of [null, {region: 'other-region', files: null, pending: true}]) {
    resetLandWater();
    publishedChartFiles.value = initial;
    const {urls, fetchFn} = recorder();
    assert.equal((await loadLandWater(REGION, fetchFn)).state, 'ready');
    assert.equal(urls.length, 1);
  }
});

test('superseded_wait_never_revives', async () => {
  const {urls, fetchFn} = recorder();
  publishedChartFiles.value = pending(REGION);
  const call = loadLandWater(REGION, fetchFn);
  await tick();
  publishedChartFiles.value = pending('region-b');
  const state = await call;
  assert.notEqual(state.state, 'ready');
  publishedChartFiles.value = {region: REGION, files: ['land-water.json']};
  await tick();
  assert.equal(urls.length, 0, 'old wait does not revive');
  assert.notEqual(landWater.peek().state, 'unavailable', 'old A is not memoized unavailable');
  assert.equal((await loadLandWater(REGION, fetchFn)).state, 'ready', 'a fresh load works');
  assert.equal(urls.length, 1);
});

test('reset_or_replacement_disposes_now', async () => {
  const {urls, fetchFn} = recorder();
  publishedChartFiles.value = pending(REGION);
  const call = loadLandWater(REGION, fetchFn);
  await tick();
  resetLandWater();
  await call; // settles without another metadata write
  publishedChartFiles.value = {region: REGION, files: ['land-water.json']};
  await tick();
  assert.equal(urls.length, 0);
  assert.notEqual(landWater.peek().state, 'ready');

  publishedChartFiles.value = pending(REGION);
  const first = loadLandWater(REGION, fetchFn);
  await tick();
  const second = loadLandWater('region-b', fetchFn);
  await first;
  publishedChartFiles.value = {region: REGION, files: ['land-water.json']};
  assert.equal((await second).region, 'region-b');
  assert.equal(landWater.peek().region, 'region-b');
  assert.ok(urls.every(u => u.includes('region-b')), 'only the replacement fetched');
});

test('real_transport_retry_stays_explicit', async () => {
  let n = 0;
  const {urls, fetchFn} = recorder(() => (++n === 1 ? new Response('x', {status: 503}) : new Response(JSON.stringify(index))));
  publishedChartFiles.value = pending(REGION);
  const call = loadLandWater(REGION, fetchFn);
  await tick();
  publishedChartFiles.value = {region: REGION, files: ['land-water.json']};
  assert.equal((await call).state, 'unavailable');
  await tick();
  assert.equal(urls.length, 1, 'no automatic retry');
  const retries = await Promise.all([loadLandWater(REGION, fetchFn, {retryTransient: true}), loadLandWater(REGION, fetchFn, {retryTransient: true})]);
  assert.ok(retries.every(s => s.state === 'ready'));
  assert.equal(urls.length, 2, 'explicit retries share one read');
});
