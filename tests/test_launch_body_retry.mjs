// RF0220-8: a Kayak launch response whose body dies in transit (stream error, abort) is asked again on the
// next call; malformed JSON, a wrong-shape file and HTTP 403/404 stay remembered. Synthetic fixtures only.
import assert from 'node:assert/strict';
import test from 'node:test';
import {launchChoice} from '../web/reach.ts';
import {launchOrigin, launchPoints, loadLaunchPoints, resetLaunchPoints} from '../web/launches.ts';

const PAGE = 'https://example.test/';
const good = region => JSON.stringify({region_id: region, launch_points: [{id: 'ramp', name: 'Ramp', latitude: 35.3, longitude: -120.8}]});
const ok = region => new Response(good(region));
/** A 200 response whose body stream errors with `err` once `settle` runs (or at once when no settle is wanted). */
function failingBody(err, deferNow = false) {
  let ctl;
  const body = new ReadableStream({start(c) { ctl = c; if (!deferNow) c.error(err); }});
  return {response: new Response(body, {status: 200}), fail: () => ctl.error(err)};
}
/** A fetch answering from `answers` in order (a function is called) and counting calls. */
function scripted(answers) {
  const f = async url => { const a = answers[f.calls++]; return typeof a === 'function' ? a(url) : a; };
  f.calls = 0;
  return f;
}
const deferred = () => { let resolve, reject; const promise = new Promise((y, n) => { resolve = y; reject = n; }); return {promise, resolve, reject}; };

/** Run `body` with global fetch blocked and every shared signal reset afterwards. */
async function isolated(body) {
  const realFetch = globalThis.fetch;
  globalThis.fetch = () => { throw new Error('global fetch must not be used'); };
  resetLaunchPoints();
  launchChoice.value = {};
  try { await body(); } finally { globalThis.fetch = realFetch; launchChoice.value = {}; resetLaunchPoints(); }
}

for (const [label, make] of [
  ['stream TypeError', () => failingBody(new TypeError('network error')).response],
  ['body AbortError', () => failingBody(new DOMException('aborted', 'AbortError')).response],
]) {
  test(`launch_body_transport_failure_retries_on_next_call (${label})`, () => isolated(async () => {
    const f = scripted([make(), ok('r'), ok('r')]);
    await loadLaunchPoints('r', PAGE, f);
    assert.equal(f.calls, 1);
    assert.equal(launchPoints.value.region, 'r');
    assert.equal(launchPoints.value.points.length, 0, 'empty after the interrupted body');
    await loadLaunchPoints('r', PAGE, f);
    assert.equal(f.calls, 2, 'asked again on the next call');
    assert.equal(launchPoints.value.points.length, 1, 'the ramp shows after the retry');
    launchChoice.value = {r: 'ramp'};
    assert.deepEqual(launchOrigin('r'), {latitude: 35.3, longitude: -120.8, name: 'Ramp'});
    await loadLaunchPoints('r', PAGE, f);
    assert.equal(f.calls, 2, 'the good read is remembered');
  }));
}

for (const [label, first] of [
  ['malformed JSON', () => new Response('{not json')],
  ['wrong region', () => new Response(good('other'))],
  ['missing list', () => new Response(JSON.stringify({region_id: 'r'}))],
  ['HTTP 403', () => new Response('', {status: 403})],
  ['HTTP 404', () => new Response('', {status: 404})],
]) {
  test(`launch_body_syntax_and_shape_failures_stay_memoized (${label})`, () => isolated(async () => {
    const f = scripted([first(), ok('r')]);
    await loadLaunchPoints('r', PAGE, f);
    const before = launchPoints.value;
    assert.equal(before.points.length, 0);
    await loadLaunchPoints('r', PAGE, f);
    await loadLaunchPoints('r', PAGE, f);
    assert.equal(f.calls, 1, 'not asked again');
    assert.equal(launchPoints.value, before, 'nothing republished');
  }));
}

test('launch_body_syntax_and_shape_failures_stay_memoized (success stays cached)', () => isolated(async () => {
  const f = scripted([ok('r'), ok('r')]);
  await loadLaunchPoints('r', PAGE, f);
  await loadLaunchPoints('r', PAGE, f);
  assert.equal(f.calls, 1);
  assert.equal(launchPoints.value.points.length, 1);
}));

test('launch_body_failure_is_shared_until_settled', () => isolated(async () => {
  const body = failingBody(new TypeError('dropped'), true);
  const f = scripted([body.response, ok('r')]);
  const a = loadLaunchPoints('r', PAGE, f), b = loadLaunchPoints('r', PAGE, f);
  assert.equal(f.calls, 1, 'shared while in flight');
  body.fail();
  await Promise.all([a, b]);
  assert.equal(f.calls, 1, 'no automatic retry');
  assert.equal(launchPoints.value.points.length, 0);
  await loadLaunchPoints('r', PAGE, f);
  assert.equal(f.calls, 2, 'exactly one more fetch on the next call');
  assert.equal(launchPoints.value.points.length, 1);
}));

test('launch_body_failure_keeps_newer_read_and_latest_region', () => isolated(async () => {
  const oldBody = failingBody(new TypeError('late'), true), newer = deferred();
  const f = scripted([oldBody.response, () => newer.promise, ok('b'), ok('a')]);
  const lateOld = loadLaunchPoints('a', PAGE, f);
  resetLaunchPoints();
  const pendingNew = loadLaunchPoints('a', PAGE, f);
  assert.equal(f.calls, 2, 'a new read after the reset');
  await loadLaunchPoints('b', PAGE, f);
  assert.equal(launchPoints.value.region, 'b');
  assert.equal(launchPoints.value.points.length, 1);
  oldBody.fail();
  await lateOld;
  assert.equal(launchPoints.value.region, 'b', 'the late body failure does not publish over b');
  const again = loadLaunchPoints('a', PAGE, f);
  assert.equal(f.calls, 3, 'the newer read for a is still shared, not removed');
  newer.resolve(ok('a'));
  await Promise.all([pendingNew, again]);
  assert.equal(launchPoints.value.region, 'a');
  assert.equal(launchPoints.value.points.length, 1);
  assert.equal(f.calls, 3);
}));
