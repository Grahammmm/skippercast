// SP-15-v1: complete real loader, producer-shaped synthetic products, no live I/O.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {syncBuiltinESMExports} from 'node:module';
import http from 'node:http';
import https from 'node:https';
import net from 'node:net';
import tls from 'node:tls';
import dns from 'node:dns';
import childProcess from 'node:child_process';
import test, {after, beforeEach, afterEach} from 'node:test';

// Install before dynamic import, including the loader's bound global-fetch default.
// These are accidental-I/O sentinels, not a hostile-code sandbox.
const undo = [], unexpected = [];
function guard(object, key) {
  const original = object[key];
  object[key] = (...args) => { unexpected.push(key); throw new Error(`SP1503 offline sentinel: ${key}`); };
  undo.push(() => { object[key] = original; });
}
guard(globalThis, 'fetch');
for (const object of [http, https]) for (const key of ['request', 'get']) guard(object, key);
for (const key of ['connect', 'createConnection']) guard(net, key);
guard(net.Socket.prototype, 'connect');
guard(tls, 'connect');
for (const key of ['lookup', 'resolve']) guard(dns, key);
for (const key of ['spawn', 'spawnSync', 'exec', 'execSync', 'execFile', 'execFileSync', 'fork']) guard(childProcess, key);
syncBuiltinESMExports();
const {
  loadLandWater, ensureLandWater, loadLandWaterLines, landWater, placeFor,
  keepWater, resetLandWater,
} = await import('../web/land-water.ts');
const fixture = JSON.parse(readFileSync(new URL('./fixtures/sp1503_land_water_retry/products.json', import.meta.url), 'utf8'));
const REGION = fixture.region, P = fixture.points, POINTS = Object.values(P);
const linesText = JSON.stringify(fixture.lines);
const index = {...fixture.index, lines: {sha256: createHash('sha256').update(linesText).digest('hex')}};
const mixed = {...index, tiles: {'0/0/0': 'm1'}};
const response = (body = index) => new Response(JSON.stringify(body));
const retry = {retryTransient: true};
const unavailable = {state: 'unknown', reason: 'unavailable'};
const tick = () => new Promise(resolve => setImmediate(resolve));
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}
function withheld(reason) {
  const place = placeFor(landWater.peek(), REGION);
  for (const point of POINTS) assert.deepEqual(place(point), {state: 'unknown', reason});
  assert.deepEqual(keepWater(POINTS, place), {kept: [], withheld: POINTS.length, pending: reason === 'pending'});
}
beforeEach(() => { resetLandWater(); });
afterEach(() => { resetLandWater(); assert.deepEqual(unexpected, [], 'no accidental external/model/process I/O'); });
after(() => { for (const restore of undo.reverse()) restore(); syncBuiltinESMExports(); });

// Original selector executes unchanged with the same pre-import offline guards.
if (process.argv.includes('--original-regression')) {
  await import('./test_land_water.mjs');
} else {
// Frozen baseline pair: register exactly these two in --baseline-pair mode.
test('primary regression', async t => {
  let calls = 0;
  const fetchFn = async () => { if (++calls === 1) throw new TypeError('synthetic transport rejection'); return response(); };
  const first = await loadLandWater(REGION, fetchFn);
  assert.equal(first.state, 'unavailable');
  withheld('unavailable');
  const recovered = await loadLandWater(REGION, fetchFn, retry);
  t.diagnostic(`SP1503_OBSERVED ${JSON.stringify({first: first.state, recovered: recovered.state, calls})}`);
  assert.equal(recovered.state, 'ready', 'SP1503_A1_EXPLICIT_TRANSIENT_RECOVERY');
  assert.equal(calls, 2);
  assert.deepEqual(placeFor(recovered, REGION)(P.water), {state: 'water'});
});
test('healthy control', async () => {
  let calls = 0;
  const fetchFn = async () => { calls++; return response(); };
  const ready = await loadLandWater(REGION, fetchFn);
  assert.equal(ready.state, 'ready');
  assert.deepEqual(placeFor(ready, REGION)(P.water), {state: 'water'});
  assert.equal(await loadLandWater(REGION, fetchFn), ready);
  assert.equal(calls, 1);
});

if (!process.argv.includes('--baseline-pair')) {
  test('A1 transport rejection, synchronous throw, HTTP 429 and every HTTP 5xx recover only on explicit true', async () => {
    const failures = [
      () => Promise.reject(new TypeError('synthetic transport rejection')),
      () => { throw new TypeError('synthetic synchronous transport rejection'); },
      ...[429, ...Array.from({length: 100}, (_, i) => 500 + i)].map(status => () => new Response('', {status})),
    ];
    for (const fail of failures) {
      resetLandWater();
      let calls = 0;
      const fetchFn = (...args) => { calls++; return calls === 1 ? fail() : Promise.resolve(response()); };
      assert.equal((await loadLandWater(REGION, fetchFn)).state, 'unavailable');
      withheld('unavailable');
      const ready = await loadLandWater(REGION, fetchFn, retry);
      assert.equal(ready.state, 'ready');
      assert.equal(calls, 2);
      assert.deepEqual(placeFor(ready, REGION)(P.water), {state: 'water'});
      assert.equal(await loadLandWater(REGION, fetchFn, retry), ready);
      assert.equal(calls, 2, 'even explicit retry cannot refetch ready');
    }
  });

  test('A2 simultaneous explicit retries, ordinary load and ensure share one job and stay withheld in flight', async () => {
    await loadLandWater(REGION, async () => { throw new Error('synthetic offline'); });
    const held = deferred(); let calls = 0, settled = false;
    const fetchFn = () => { calls++; return held.promise; };
    const first = loadLandWater(REGION, fetchFn, retry);
    const second = loadLandWater(REGION, fetchFn, retry);
    const third = loadLandWater(REGION, fetchFn);
    const fourth = ensureLandWater(REGION, POINTS, fetchFn);
    first.then(() => { settled = true; });
    assert.equal(first, second); assert.equal(first, third);
    await tick();
    assert.equal(calls, 1); assert.equal(settled, false);
    withheld('pending');
    held.resolve(response());
    const [a, b, c, place] = await Promise.all([first, second, third, fourth]);
    assert.equal(a, b); assert.equal(a, c); assert.equal(a.state, 'ready');
    assert.deepEqual(place(P.water), {state: 'water'});
    assert.equal(calls, 1);
  });

  test('A2 stale retry success or failure cannot overwrite region switch, reset or A-B-A job', async () => {
    for (const ending of ['success', 'transport', 'http']) for (const switchTo of ['other', 'reset', 'aba']) {
      resetLandWater();
      await loadLandWater(REGION, async () => { throw new Error('synthetic offline'); });
      const old = deferred(); let calls = 0;
      const stale = loadLandWater(REGION, () => { calls++; return old.promise; }, retry);
      await tick();
      assert.equal(calls, 1);
      if (switchTo === 'reset') resetLandWater();
      else await loadLandWater('other-synthetic', async () => new Response('', {status: 404}));
      if (switchTo === 'aba') await loadLandWater(REGION, async () => response());
      const selected = landWater.peek();
      if (ending === 'transport') old.reject(new Error('synthetic delayed rejection'));
      else old.resolve(ending === 'success' ? response() : new Response('', {status: 503}));
      assert.equal(await stale, selected);
      assert.equal(landWater.peek(), selected);
      if (switchTo !== 'aba') assert.notEqual(placeFor(selected, REGION)(P.water).state, 'water');
      // A stale transient failure must not mark the selected memoized 404 retryable.
      if (switchTo === 'other') {
        await loadLandWater('other-synthetic', () => { calls++; return Promise.resolve(response()); }, retry);
        assert.equal(calls, 1);
      }
    }
  });

  test('A3 defaults, ensure, false and non-boolean truthy options do not retry or schedule later work', async () => {
    let calls = 0;
    const fetchFn = async () => { calls++; throw new Error('synthetic offline'); };
    const failed = await loadLandWater(REGION, fetchFn);
    for (const options of [undefined, {}, {retryTransient: false}, {retryTransient: 1}, {retryTransient: 'true'}]) {
      assert.equal(await loadLandWater(REGION, fetchFn, options), failed);
      assert.deepEqual((await ensureLandWater(REGION, POINTS, fetchFn))(P.water), unavailable);
    }
    await tick(); await tick();
    assert.equal(calls, 1);
    withheld('unavailable');
  });

  test('A3 permanent HTTP, malformed JSON, invalid schema and explicitly unavailable products stay memoized', async () => {
    const permanent = [
      ...[400, 401, 403, 404, 408, 410, 499, 300].map(status => () => new Response('', {status})),
      () => new Response('not JSON'),
      () => response({...index, schema_version: 2}),
      () => response({...index, region_id: 'wrong-synthetic-region'}),
      () => response({...index, status: 'unavailable', causes: ['synthetic gap']}),
    ];
    for (const answer of permanent) {
      resetLandWater(); let calls = 0;
      const fetchFn = async () => { calls++; return answer(); };
      const failed = await loadLandWater(REGION, fetchFn);
      assert.equal(failed.state, 'unavailable');
      assert.equal(await loadLandWater(REGION, fetchFn, retry), failed);
      assert.deepEqual((await ensureLandWater(REGION, POINTS, fetchFn))(P.water), unavailable);
      withheld('unavailable'); assert.equal(calls, 1);
    }
  });

  test('A1/A3 failed retries settle once; a later explicit call alone may retry a new transient failure', async () => {
    let calls = 0;
    const fetchFn = async () => { calls++; return new Response('', {status: 503}); };
    await loadLandWater(REGION, fetchFn);
    await loadLandWater(REGION, fetchFn, retry);
    withheld('unavailable');
    await loadLandWater(REGION, fetchFn);
    await ensureLandWater(REGION, POINTS, fetchFn);
    await tick(); assert.equal(calls, 2);
    const final = await loadLandWater(REGION, async () => { calls++; return response({...index, status: 'unavailable'}); }, retry);
    assert.equal(final.state, 'unavailable');
    await loadLandWater(REGION, fetchFn, retry);
    assert.equal(calls, 3, 'a permanent retry result clears retry eligibility');
  });

  test('A4 after recovery mixed-cell lines are unchanged: valid hash and shoreline pass; tampering stays withheld', async () => {
    for (const variant of ['valid', 'hash', 'shoreline', 'region', 'malformed', 'transport']) {
      resetLandWater(); let calls = 0;
      await loadLandWater(REGION, async () => { throw new Error('synthetic offline'); });
      withheld('unavailable');
      let text = linesText;
      if (variant === 'hash') text += ' ';
      if (variant === 'shoreline') text = JSON.stringify({...fixture.lines, derived_from: {sha256: 'wrong-synthetic-source'}});
      if (variant === 'region') text = JSON.stringify({...fixture.lines, region_id: 'wrong-synthetic-region'});
      if (variant === 'malformed') text = JSON.stringify({...fixture.lines, edge: [[1, 2, 'invalid', 4]]});
      const modelIndex = {...mixed, lines: {sha256: createHash('sha256').update(variant === 'hash' ? linesText : text).digest('hex')}};
      await loadLandWater(REGION, async () => { calls++; return response(modelIndex); }, retry);
      const loaded = placeFor(landWater.peek(), REGION);
      assert.deepEqual(loaded(P.water), {state: 'unknown', reason: 'pending'});
      const place = await ensureLandWater(REGION, POINTS, async url => {
        calls++; assert.ok(url.endsWith('/land-water-lines.json'));
        if (variant === 'transport') throw new Error('synthetic lines rejection');
        return new Response(text);
      });
      if (variant === 'valid') {
        assert.deepEqual(place(P.water), {state: 'water'});
        assert.deepEqual(place(P.land), {state: 'land'});
        assert.deepEqual(place(P.edge), {state: 'unknown', reason: 'edge'});
        assert.deepEqual(keepWater(POINTS, place), {kept: [P.water], withheld: 3, pending: false});
      } else {
        assert.equal(landWater.peek().lines, false);
        for (const point of [P.water, P.land, P.edge]) assert.deepEqual(place(point), unavailable);
      }
      await loadLandWaterLines(REGION, async () => { calls++; return new Response(linesText); });
      await loadLandWater(REGION, async () => { calls++; return response(); }, retry);
      assert.equal(calls, 2, 'no change to once-only lines or ready memoization');
    }
  });
}
}
