// RF1100-1: tideTrend reads no trend (null) from a bad curve pair, never "Falling":
// a non-finite height, or a next point whose time is unreadable, earlier or the same.
import assert from 'node:assert/strict';
import test from 'node:test';

const {tideTrend} = await import('../web/tides.ts');

const MIN = 60_000;
const START = '2026-10-08T18:00:00Z';
const T0 = Date.parse(START);
const iso = ms => new Date(ms).toISOString();
const pair = (h0, h1, stepMs = 6 * MIN) => [{at: START, heightFt: h0}, {at: iso(T0 + stepMs), heightFt: h1}];

test('a non-finite height on either point reads no trend', () => {
  for (const bad of [NaN, Infinity, -Infinity, undefined, null, '1.2']) {
    assert.equal(tideTrend(pair(bad, 1), START), null, `matched ${String(bad)}`);
    assert.equal(tideTrend(pair(1, bad), START), null, `next ${String(bad)}`);
  }
});

test('an unreadable, earlier or same-time next point reads no trend', () => {
  assert.equal(tideTrend([{at: START, heightFt: 1}, {at: 'not a time', heightFt: 0.5}], START), null);
  assert.equal(tideTrend([{at: START, heightFt: 1}, {at: iso(T0 - 6 * MIN), heightFt: 0.5}], START), null);
  assert.equal(tideTrend([{at: START, heightFt: 1}, {at: START, heightFt: 0.5}], START), null);
  // The earlier next point stays out of order when the matched point is not the first.
  const curve = [{at: iso(T0 - 30 * MIN), heightFt: 2}, {at: START, heightFt: 1}, {at: iso(T0 - 6 * MIN), heightFt: 1.5}];
  assert.equal(tideTrend(curve, START), null);
});

test('well-formed six-minute pairs keep Rising, Falling and Turning', () => {
  assert.equal(tideTrend(pair(1, 1.1), START), 'Rising');
  assert.equal(tideTrend(pair(1, 0.9), START), 'Falling');
  assert.equal(tideTrend(pair(1, 1.004), START), 'Turning');
  assert.equal(tideTrend(pair(1, 0.996), START), 'Turning');
  assert.equal(tideTrend(pair(-0.5, -0.6), T0), 'Falling');
});

test('the 15-minute step boundary is unchanged', () => {
  assert.equal(tideTrend(pair(1, 0.9, 15 * MIN), START), 'Falling');
  assert.equal(tideTrend(pair(1, 1.1, 15 * MIN), START), 'Rising');
  assert.equal(tideTrend(pair(1, 0.9, 15 * MIN + 1), START), null);
  assert.equal(tideTrend(pair(1, 0.9, 1), START), 'Falling');
});

test('an unreadable selected time or an empty curve reads no trend', () => {
  assert.equal(tideTrend(pair(1, 1.1), 'x'), null);
  assert.equal(tideTrend(pair(1, 1.1), NaN), null);
  assert.equal(tideTrend([], START), null);
  assert.equal(tideTrend([{at: START, heightFt: 1}], START), null);
});
