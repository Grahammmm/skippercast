import assert from 'node:assert/strict';
import test from 'node:test';
import {createHistoryCache} from '../web/map/history-cache.ts';

const DAY = ['test-coast', 'sst', '2026-11-18T00:00:00Z'];
const READY = {state: 'ready', rows: [[35, -121, 14]]};
const NONE = {state: 'none'};
const ERROR = {state: 'error'};

function fixture(max) {
  const calls = [];
  const cache = createHistoryCache((region, layer, sampleAt, signal) => {
    const {promise, resolve, reject} = Promise.withResolvers();
    calls.push({key: [region, layer, sampleAt], signal, resolve, reject});
    return promise;
  }, max);
  return {cache, calls};
}

for (const max of [0, -1, 1.5, NaN, Infinity]) {
  test(`C1: rejects invalid capacity ${max}`, () => {
    assert.throws(() => fixture(max), RangeError);
  });
}

test('C1: keys distinguish region, layer, exact sample time and separator collisions', async () => {
  const {cache, calls} = fixture();
  const keys = [DAY, ['other-coast', DAY[1], DAY[2]], [DAY[0], 'chl', DAY[2]], [DAY[0], DAY[1], '2026-11-17T16:00:00-08:00'],
    ['test|coast', 'sst', DAY[2]], ['test', 'coast|sst', DAY[2]]];
  const values = keys.map((_, index) => ({state: 'ready', rows: [[index]]}));
  const pending = keys.map(key => cache.get(...key));
  assert.deepEqual(calls.map(call => call.key), keys);
  calls.forEach((call, index) => call.resolve(values[index]));
  assert.deepEqual(await Promise.all(pending), values);
  assert.deepEqual(await Promise.all(keys.map(key => cache.get(...key))), values);
  assert.equal(calls.length, keys.length);
});

test('C1: the default limit evicts the oldest result on the 33rd insert', async () => {
  let loads = 0;
  const cache = createHistoryCache(async (_region, _layer, sampleAt) => ({state: 'ready', sampleAt, load: ++loads}));
  for (let i = 0; i < 33; i++) {
    assert.deepEqual(await cache.get('test-coast', 'sst', String(i)), {state: 'ready', sampleAt: String(i), load: i + 1});
  }
  assert.equal(cache.size(), 32);
  assert.deepEqual(await cache.get('test-coast', 'sst', '1'), {state: 'ready', sampleAt: '1', load: 2});
  assert.deepEqual(await cache.get('test-coast', 'sst', '0'), {state: 'ready', sampleAt: '0', load: 34});
});

for (const value of [READY, NONE]) {
  test(`C2: concurrent callers share one load and later hits reuse its ${value.state} result`, async () => {
    const {cache, calls} = fixture();
    const first = cache.get(...DAY);
    const second = cache.get(...DAY);
    assert.equal(calls.length, 1);
    assert.equal(cache.size(), 0);
    calls[0].resolve(value);
    assert.deepEqual(await Promise.all([first, second]), [value, value]);
    assert.equal(cache.size(), 1);
    assert.deepEqual(await cache.get(...DAY), value);
    assert.equal(calls.length, 1);
  });
}

for (const value of [ERROR, {state: 'unrecognised'}]) {
  test(`C2: delivers ${value.state} to all callers without caching it`, async () => {
    const {cache, calls} = fixture();
    const first = cache.get(...DAY);
    const second = cache.get(...DAY);
    assert.equal(calls.length, 1);
    calls[0].resolve(value);
    assert.deepEqual(await Promise.all([first, second]), [value, value]);
    assert.equal(cache.size(), 0);
    const retry = cache.get(...DAY);
    assert.equal(calls.length, 2);
    calls[1].resolve(READY);
    assert.deepEqual(await retry, READY);
  });
}

test('C2: a loader rejection reaches all waiters unchanged and permits retry', async () => {
  const {cache, calls} = fixture();
  const error = new TypeError('fixture failed');
  const first = assert.rejects(cache.get(...DAY), received => received === error);
  const second = assert.rejects(cache.get(...DAY), received => received === error);
  assert.equal(calls.length, 1);
  calls[0].reject(error);
  await Promise.all([first, second]);
  assert.equal(cache.size(), 0);
  const retry = cache.get(...DAY);
  assert.equal(calls.length, 2);
  calls[1].resolve(NONE);
  assert.deepEqual(await retry, NONE);
});

test('C3: a pre-aborted caller neither starts nor joins a load nor takes a hit', async () => {
  const {cache, calls} = fixture();
  const reason = {why: 'selection already changed'};
  const signal = AbortSignal.abort(reason);
  const aborted = () => assert.rejects(cache.get(...DAY, signal), received => received === reason);
  await aborted();
  assert.equal(calls.length, 0);
  const active = cache.get(...DAY);
  await aborted();
  assert.equal(calls.length, 1);
  calls[0].resolve(READY);
  assert.deepEqual(await active, READY);
  await aborted();
  assert.deepEqual(await cache.get(...DAY), READY);
  assert.equal(calls.length, 1);
});

test('C3: one abort rejects only that caller, even when the remaining waiter has no signal', async () => {
  const {cache, calls} = fixture();
  const caller = new AbortController();
  const reason = new RangeError('caller changed day');
  const aborted = assert.rejects(cache.get(...DAY, caller.signal), received => received === reason);
  const survivor = cache.get(...DAY);
  assert.equal(calls.length, 1);
  caller.abort(reason);
  await aborted;
  assert.equal(calls[0].signal.aborted, false);
  calls[0].resolve(READY);
  assert.deepEqual(await survivor, READY);
  assert.deepEqual(await cache.get(...DAY), READY);
  assert.equal(calls.length, 1);
});

for (const settle of ['resolve', 'reject']) {
  test(`C3: last abort cancels a shared load; its late ${settle} leaves a replacement intact`, async () => {
    const {cache, calls} = fixture();
    const first = new AbortController(), second = new AbortController();
    const firstReason = new Error('first caller left'), secondReason = new Error('last caller left');
    const a = assert.rejects(cache.get(...DAY, first.signal), received => received === firstReason);
    const b = assert.rejects(cache.get(...DAY, second.signal), received => received === secondReason);
    assert.equal(calls.length, 1);
    first.abort(firstReason);
    assert.equal(calls[0].signal.aborted, false);
    second.abort(secondReason);
    assert.equal(calls[0].signal.aborted, true);
    await Promise.all([a, b]);

    const replacement = cache.get(...DAY);
    assert.equal(calls.length, 2);
    calls[0][settle](settle === 'resolve' ? READY : new TypeError('stale load failed'));
    await Promise.resolve(); // Let the abandoned load's continuation run before another caller joins.
    assert.equal(cache.size(), 0);
    const joined = cache.get(...DAY);
    assert.equal(calls.length, 2);
    calls[1].resolve(NONE);
    assert.deepEqual(await Promise.all([replacement, joined]), [NONE, NONE]);
    assert.deepEqual(await cache.get(...DAY), NONE);
    assert.equal(calls.length, 2);
  });
}

test('C3: a synchronous abort inside load sees the first waiter already registered', async () => {
  const caller = new AbortController();
  const reason = new Error('superseded during load startup');
  let abortedDuringLoad;
  const cache = createHistoryCache(async (_region, _layer, _sampleAt, signal) => {
    caller.abort(reason);
    abortedDuringLoad = signal.aborted;
    return READY;
  });
  await assert.rejects(cache.get(...DAY, caller.signal), received => received === reason);
  assert.equal(abortedDuringLoad, true);
  assert.equal(cache.size(), 0);
});

test('C3: aborting a settled caller cannot cancel or unregister a later load for the key', async () => {
  const {cache, calls} = fixture();
  const caller = new AbortController();
  const old = cache.get(...DAY, caller.signal);
  calls[0].resolve(ERROR);
  assert.deepEqual(await old, ERROR);
  const replacement = cache.get(...DAY);
  assert.equal(calls.length, 2);
  caller.abort();
  assert.equal(calls[0].signal.aborted, false);
  assert.equal(calls[1].signal.aborted, false);
  const joined = cache.get(...DAY);
  assert.equal(calls.length, 2);
  calls[1].resolve(READY);
  assert.deepEqual(await Promise.all([replacement, joined]), [READY, READY]);
});

test('C4: hits refresh recency, pending loads do not count, and insertion evicts LRU rather than FIFO', async () => {
  const {cache, calls} = fixture(2);
  const secondDay = [DAY[0], DAY[1], '2026-11-17T00:00:00Z'];
  const thirdDay = [DAY[0], DAY[1], '2026-11-16T00:00:00Z'];
  const value = {state: 'ready', rows: [[35, -121, 12]]};
  assert.equal(cache.size(), 0);
  const first = cache.get(...DAY);
  calls[0].resolve(READY);
  assert.deepEqual(await first, READY);
  const second = cache.get(...secondDay);
  calls[1].resolve(NONE);
  assert.deepEqual(await second, NONE);
  const third = cache.get(...thirdDay);
  assert.equal(cache.size(), 2);
  assert.deepEqual(await cache.get(...DAY), READY);
  calls[2].resolve(value);
  assert.deepEqual(await third, value);
  assert.equal(cache.size(), 2);
  assert.deepEqual(await cache.get(...DAY), READY);
  assert.deepEqual(await cache.get(...thirdDay), value);
  const reread = cache.get(...secondDay);
  assert.equal(calls.length, 4);
  calls[3].resolve(READY);
  assert.deepEqual(await reread, READY);
  assert.equal(cache.size(), 2);
});

test('C4: clear drops saved results and prevents pending results from refilling the cache', async () => {
  const {cache, calls} = fixture(1);
  const otherDay = [DAY[0], DAY[1], '2026-11-17T00:00:00Z'];
  const saved = cache.get(...otherDay);
  calls[0].resolve(NONE);
  assert.deepEqual(await saved, NONE);
  const old = cache.get(...DAY);
  assert.equal(cache.size(), 1);
  cache.clear();
  assert.equal(cache.size(), 0);

  const joined = cache.get(...DAY);
  assert.equal(calls.length, 2);
  assert.equal(calls[1].signal.aborted, false);
  calls[1].resolve(READY);
  assert.deepEqual(await Promise.all([old, joined]), [READY, READY]);
  assert.equal(cache.size(), 0);

  const fresh = cache.get(...DAY);
  assert.equal(calls.length, 3);
  calls[2].resolve(NONE);
  assert.deepEqual(await fresh, NONE);
  assert.deepEqual(await cache.get(...DAY), NONE);
  assert.equal(cache.size(), 1);
});
