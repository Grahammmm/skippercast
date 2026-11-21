import assert from 'node:assert/strict';
import test from 'node:test';
import {fromFeedValue, toFeedCondition} from '../server/spot-watch-feed-units.ts';
import {conditionMet} from '../server/spot-watch-state.ts';

// Stored and tile anchors, paired at the specified floating-point precision.
const anchors = [
  {layer: 'water-temp', stored: [28, 58, 95], feed: [-2.2222222222222223, 14.444444444444445, 35]},
  {layer: 'sst-contrast', stored: [0, 1, 10], feed: [0, 0.2999760019198464, 2.999760019198464]},
  {layer: 'chlorophyll', stored: [0.01, 2, 100], feed: [0.01, 2, 100]},
];
const nonFinite = [NaN, Infinity, -Infinity];

// A wrong scale, offset or omitted second threshold changes the whole condition.
for (const {layer, stored: [lo, mid, hi], feed: [low, middle, high]} of anchors) {
  test(`C1: ${layer} preserves each op and the shape of b`, () => {
    assert.deepEqual(toFeedCondition(layer, {op: '>=', a: lo}), {op: '>=', a: low});
    assert.deepEqual(toFeedCondition(layer, {op: '<=', a: mid, b: null}), {op: '<=', a: middle, b: null});
    assert.deepEqual(toFeedCondition(layer, {op: '<=', a: hi, b: undefined}), {op: '<=', a: high, b: undefined});
    assert.deepEqual(toFeedCondition(layer, {op: '>=', a: lo, b: mid}), {op: '>=', a: low, b: middle});
    assert.deepEqual(toFeedCondition(layer, {op: 'between', a: lo, b: hi}), {op: 'between', a: low, b: high});
  });
}

// Even a pass-through layer or an unused numeric b must reject a bad threshold.
test('C1: rejects unknown layers and non-finite thresholds', () => {
  assert.equal(toFeedCondition('unknown', {op: '>=', a: 28}), null);
  for (const {layer, stored: [a, , b]} of anchors) {
    for (const bad of nonFinite) {
      assert.equal(toFeedCondition(layer, {op: 'between', a: bad, b}), null);
      assert.equal(toFeedCondition(layer, {op: 'between', a, b: bad}), null);
      assert.equal(toFeedCondition(layer, {op: '>=', a, b: bad}), null);
    }
  }
});

// Exact inverse outputs catch a missing Fahrenheit offset or a reversed distance factor.
test('C2: converts a reading from each tile field back to its stored units', () => {
  assert.equal(fromFeedValue('water-temp', 0), 32);
  assert.equal(fromFeedValue('water-temp', 35), 95);
  assert.equal(fromFeedValue('sst-contrast', 1), 3.3336);
  assert.equal(fromFeedValue('chlorophyll', 2), 2);
});

test('C2: refuses missing, non-finite and unknown readings rather than treating them as measurements', () => {
  assert.equal(fromFeedValue('unknown', 0), null);
  for (const {layer} of anchors) {
    for (const bad of [null, ...nonFinite]) {
      assert.equal(fromFeedValue(layer, bad), null);
    }
  }
});

// One nanounit in stored units separates floating-point boundary noise from
// comparison changes. The inverse at 1 °F/nm is one representable step above 1.
const tolerance = 1e-9;
test('C3: pins the exact tile anchors and their round trips', () => {
  for (const {layer, stored, feed} of anchors) {
    for (const [i, a] of stored.entries()) {
      const converted = toFeedCondition(layer, {op: '>=', a});
      assert.deepEqual(converted, {op: '>=', a: feed[i]});
      const expected = layer === 'sst-contrast' && a === 1 ? 1.0000000000000002 : a;
      assert.equal(fromFeedValue(layer, converted.a), expected);
    }
  }
});

// A comparison flip or conversion drift changes results above/below an edge;
// checking exact tile edges separately catches accidentally exclusive bounds.
for (const {layer, stored: [lo, mid, hi], feed: [low, middle, high]} of anchors) {
  test(`C3: ${layer} comparisons agree away from thresholds and tile bounds are inclusive`, () => {
    const grid = [low - 0.005, low, (low + middle) / 2, middle, (middle + high) / 2, high, high + 0.005];
    for (const cond of [{op: '>=', a: mid}, {op: '<=', a: mid}, {op: 'between', a: lo, b: hi}]) {
      const feedCond = toFeedCondition(layer, cond);
      assert.equal(conditionMet(feedCond.a, feedCond), true);
      if (cond.op === 'between') assert.equal(conditionMet(feedCond.b, feedCond), true);
      for (const v of grid) {
        const storedValue = fromFeedValue(layer, v);
        if ([cond.a, cond.b].some(t => typeof t === 'number' && Math.abs(storedValue - t) <= tolerance)) continue;
        assert.equal(conditionMet(v, feedCond), conditionMet(storedValue, cond), `${cond.op} at ${v}`);
      }
    }
  });
}

// A converter that rewrites its caller's thresholds in place breaks later evaluations.
test('C4: repeated conversions of a frozen condition have no effect on the input', () => {
  const stored = Object.freeze({op: 'between', a: 32, b: 95});
  const expected = {op: 'between', a: 0, b: 35};
  for (let i = 0; i < 2; i++) {
    assert.deepEqual(toFeedCondition('water-temp', stored), expected);
    assert.equal(fromFeedValue('water-temp', 35), 95);
  }
  assert.deepEqual(stored, {op: 'between', a: 32, b: 95});
});
