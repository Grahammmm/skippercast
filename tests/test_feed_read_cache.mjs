import assert from 'node:assert/strict';
import test from 'node:test';
import {createFeedReadCache} from '../server/feed-read-cache.ts';

test('C1: concurrent gets share a promise and settled gets do not reload', async () => {
  // Caching only settled results would duplicate this pending read.
  const {promise, resolve} = Promise.withResolvers();
  const keys = [];
  const cache = createFeedReadCache(key => { keys.push(key); return promise; });
  assert.equal(cache.loads(), 0);

  const first = cache.get('region/conditions');
  const second = cache.get('region/conditions');
  assert.equal(first, second);
  assert.equal(cache.loads(), 1);

  const value = {hours: [8, 9]};
  resolve(value);
  assert.deepEqual(await Promise.all([first, second]), [value, value]);
  assert.deepEqual(await cache.get('region/conditions'), value);
  assert.deepEqual(keys, ['region/conditions']);
  assert.equal(cache.loads(), 1);
});

test('C1: null is cached and key matching is exact', async () => {
  // A truthiness check would reload null; case-folding or trimming would alias keys.
  const keys = [];
  const cache = createFeedReadCache(async key => {
    keys.push(key);
    return key === 'feed' ? null : {key};
  });
  assert.equal(await cache.get('feed'), null);
  assert.deepEqual(await cache.get('Feed'), {key: 'Feed'});
  assert.deepEqual(await cache.get('feed '), {key: 'feed '});
  assert.equal(await cache.get('feed'), null);
  assert.deepEqual(keys, ['feed', 'Feed', 'feed ']);
  assert.equal(cache.loads(), 3);
});

test('C2: all waiters see the original rejection and the next get retries', async () => {
  // Keeping a rejected promise would poison both retries and the only slot.
  const {promise, reject} = Promise.withResolvers();
  const keys = [];
  const cache = createFeedReadCache(key => {
    keys.push(key);
    return keys.length === 1 ? promise : Promise.resolve({hours: [10]});
  }, 1);
  const failure = new TypeError('read failed');
  const first = cache.get('feed');
  const second = cache.get('feed');
  assert.equal(first, second);
  assert.equal(cache.loads(), 1);
  const waiters = [first, second].map(read => assert.rejects(read, error => {
    assert.equal(error, failure);
    return true;
  }));
  reject(failure);
  await Promise.all(waiters);
  assert.equal(cache.loads(), 1);
  assert.deepEqual(await cache.get('feed'), {hours: [10]});
  assert.deepEqual(keys, ['feed', 'feed']);
  assert.equal(cache.loads(), 2);
});

test('C3: a synchronous throw rejects, counts, and releases the slot for another key', async () => {
  // A loader can throw before returning a promise; it must not escape or occupy the cap.
  const failure = new SyntaxError('invalid input');
  const keys = [];
  const cache = createFeedReadCache(key => {
    keys.push(key);
    if (key === 'broken') throw failure;
    return Promise.resolve({key});
  }, 1);
  await assert.rejects(cache.get('broken'), error => {
    assert.equal(error, failure);
    return true;
  });
  assert.equal(cache.loads(), 1);
  assert.deepEqual(await cache.get('healthy'), {key: 'healthy'});
  assert.deepEqual(keys, ['broken', 'healthy']);
  assert.equal(cache.loads(), 2);
});

test('C3: maxKeys rejects nonintegers and values outside the inclusive bounds', () => {
  // Bounds alone would accept fractions and NaN.
  const load = async key => key;
  for (const limit of [-1, 0, 1.5, 257, NaN, Infinity]) {
    assert.throws(() => createFeedReadCache(load, limit), RangeError);
  }
  assert.equal(createFeedReadCache(load, 1).loads(), 0);
  assert.equal(createFeedReadCache(load, 256).loads(), 0);
});

test('C3: the default cap counts pending and settled keys without blocking held keys', async () => {
  // Counting only settled reads allows overflow while pending; FIFO eviction loses held values.
  const {promise, resolve} = Promise.withResolvers();
  const keys = Array.from({length: 16}, (_, i) => `feed-${i}`);
  const called = [];
  const cache = createFeedReadCache(key => {
    called.push(key);
    return promise.then(() => key);
  });
  const reads = keys.map(key => cache.get(key));
  await assert.rejects(cache.get('overflow'), RangeError);
  assert.equal(cache.get(keys[0]), reads[0]);
  assert.equal(cache.loads(), 16);

  resolve();
  assert.deepEqual(await Promise.all(reads), keys);
  await assert.rejects(cache.get('overflow'), RangeError);
  assert.deepEqual(await Promise.all(keys.map(key => cache.get(key))), keys);
  assert.deepEqual(called, keys);
  assert.equal(cache.loads(), 16);
});
