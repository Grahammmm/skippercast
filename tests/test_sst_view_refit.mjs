import test from 'node:test';
import assert from 'node:assert/strict';
import {createViewRefit, REFIT_DELAY_MS} from '../web/map/sst-view-refit.ts';

const a = [0, 0, 32, 32];
const b = [32, 10, 64, 42];
const c = [64, 20, 96, 52];
const rangeA = {min: 1, max: 63};
const rangeB = {min: 43, max: 105};
const rangeC = {min: 85, max: 147};

function fixture({sample = (lon, lat) => lon + lat, onRange, delayMs, opaqueHandle} = {}) {
  const timers = [];
  const events = [];
  const ranges = [];
  let samples = 0;
  const refit = createViewRefit({
    sample(lon, lat) {
      samples++;
      return sample(lon, lat);
    },
    onRange(range) {
      ranges.push(range);
      onRange?.(range);
    },
    setTimer(fn, ms) {
      const id = timers.push(fn) - 1;
      events.push(['set', id, ms]);
      return opaqueHandle ? undefined : id;
    },
    clearTimer(handle) {
      events.push(['clear', handle]);
    },
    delayMs,
  });
  return {
    ...refit, events, ranges,
    get samples() { return samples; },
    // Deliberately retain cleared callbacks to replay stale or duplicate delivery.
    fire: (id) => timers[id](),
  };
}

for (const [label, delayMs, expected] of [['default', undefined, 250], ['custom', 0, 0]]) {
  test(`C1: schedule one fit with the ${label} delay, without an eager sample or publish`, () => {
    const f = fixture({delayMs});
    assert.equal(REFIT_DELAY_MS, 250);
    assert.equal(f.moveEnd(a), undefined);
    assert.deepEqual(f.events, [['set', 0, expected]]);
    assert.deepEqual({samples: f.samples, ranges: f.ranges}, {samples: 0, ranges: []});
    assert.equal(f.fire(0), undefined);
    assert.deepEqual(f.ranges, [rangeA]);
    assert.equal(f.dispose(), undefined);
    assert.deepEqual(f.events, [['set', 0, expected]]);
  });
}

test('C2: three quick moves replace timers in order; stale and duplicate callbacks fit nothing', () => {
  const f = fixture();
  for (const bounds of [a, b, c]) assert.equal(f.moveEnd(bounds), undefined);
  assert.deepEqual(f.events, [['set', 0, 250], ['clear', 0], ['set', 1, 250], ['clear', 1], ['set', 2, 250]]);
  assert.equal(f.fire(0), undefined);
  assert.equal(f.fire(1), undefined);
  assert.deepEqual({samples: f.samples, ranges: f.ranges}, {samples: 0, ranges: []});
  assert.equal(f.fire(2), undefined);
  const samples = f.samples;
  assert.equal(f.fire(2), undefined);
  assert.equal(f.fire(1), undefined);
  assert.deepEqual({samples: f.samples, ranges: f.ranges}, {samples, ranges: [rangeC]});
});

test('C2: an equal or within-tolerance view skips; a change outside tolerance on one edge fits', () => {
  const f = fixture();
  f.moveEnd(a);
  f.fire(0);
  assert.equal(f.moveEnd([...a]), undefined);
  assert.equal(f.moveEnd([1e-9, -1e-9, 32 + 5e-10, 32 - 5e-10]), undefined);
  assert.deepEqual(f.events, [['set', 0, 250]]);
  assert.deepEqual(f.ranges, [rangeA]);
  assert.equal(f.moveEnd([0, 0, 32, 32 + 2e-9]), undefined);
  assert.deepEqual(f.events, [['set', 0, 250], ['set', 1, 250]]);
  const height = 32 + 2e-9;
  f.fire(1);
  assert.deepEqual(f.ranges, [rangeA, {min: 0.5 + height / 64, max: 31.5 + height * 63 / 64}]);
});

test('C2: matching a queued view, rather than a fitted view, still restarts the debounce', () => {
  const f = fixture();
  f.moveEnd(a);
  assert.equal(f.moveEnd([...a]), undefined);
  assert.deepEqual(f.events, [['set', 0, 250], ['clear', 0], ['set', 1, 250]]);
  f.fire(0);
  assert.deepEqual(f.ranges, []);
  f.fire(1);
  assert.deepEqual(f.ranges, [rangeA]);
});

test('C2: returning to the fitted view cancels a queued fit for a different view', () => {
  const f = fixture({opaqueHandle: true});
  f.moveEnd(a);
  f.fire(0);
  f.moveEnd(b);
  assert.equal(f.moveEnd(a), undefined);
  assert.deepEqual(f.events, [['set', 0, 250], ['set', 1, 250], ['clear', undefined]]);
  assert.equal(f.fire(1), undefined);
  assert.deepEqual(f.ranges, [rangeA]);
});

test('C2: a no-water fit publishes null and still remembers the fitted view', () => {
  const f = fixture({sample: () => null});
  f.moveEnd(a);
  f.fire(0);
  assert.equal(f.moveEnd(a), undefined);
  assert.deepEqual(f.events, [['set', 0, 250]]);
  assert.deepEqual(f.ranges, [null]);
});

test('C2: invalid input neither schedules a fit nor cancels pending valid bounds', () => {
  const f = fixture();
  f.moveEnd(b);
  for (const bounds of [null, [0, 0, 32], [...a, 1], [0, , 32, 32], ['0', 0, 32, 32],
    [0, NaN, 32, 32], [0, 0, Infinity, 32], [0, 0, 0, 32], [0, 32, 32, 0]]) {
    assert.equal(f.moveEnd(bounds), undefined);
  }
  assert.deepEqual(f.events, [['set', 0, 250]]);
  assert.deepEqual({samples: f.samples, ranges: f.ranges}, {samples: 0, ranges: []});
  f.fire(0);
  assert.deepEqual(f.ranges, [rangeB]);
});

test('C3: dispose clears the pending timer once and prevents all later sampling', () => {
  const f = fixture();
  f.moveEnd(a);
  assert.equal(f.dispose(), undefined);
  assert.equal(f.moveEnd(b), undefined);
  assert.equal(f.fire(0), undefined);
  assert.equal(f.dispose(), undefined);
  assert.deepEqual(f.events, [['set', 0, 250], ['clear', 0]]);
  assert.deepEqual({samples: f.samples, ranges: f.ranges}, {samples: 0, ranges: []});
});

test('C3: a throwing onRange does not escape the timer or prevent retrying the view', () => {
  let fail = true;
  const f = fixture({onRange() {
    if (fail) throw new TypeError('delivery failed');
  }});
  f.moveEnd(a);
  assert.equal(f.fire(0), undefined);
  fail = false;
  assert.equal(f.moveEnd(a), undefined);
  assert.deepEqual(f.events, [['set', 0, 250], ['set', 1, 250]]);
  assert.equal(f.fire(1), undefined);
  assert.deepEqual(f.ranges, [rangeA, rangeA]);
});

test('C3: a throwing sampler cannot strand a pending fit or suppress the next view', () => {
  const f = fixture({sample(lon, lat) {
    if (lon < 32) throw new TypeError('sample failed');
    return lon + lat;
  }});
  f.moveEnd(a);
  assert.equal(f.fire(0), undefined);
  assert.deepEqual(f.ranges, [null]);
  assert.equal(f.moveEnd(b), undefined);
  assert.deepEqual(f.events, [['set', 0, 250], ['set', 1, 250]]);
  assert.equal(f.fire(1), undefined);
  assert.deepEqual(f.ranges, [null, rangeB]);
});
