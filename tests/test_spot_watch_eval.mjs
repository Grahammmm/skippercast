import assert from 'node:assert/strict';
import test from 'node:test';
import {evaluateWatch, evaluateWatches, indexFrame} from '../server/spot-watch-eval.ts';
import {HabitatGridError} from '../web/map/habitat-sample.ts';

const before = '2026-11-19T12:00:00Z';
const published = '2026-11-20T12:00:00Z';
const watch = {
  id: 'ridge', layer: 'water-temp', cond: {op: '>=', a: 18},
  prev: Object.freeze({state: 'false', lastSampleAt: before}), lat: 35.01, lon: -120.98,
};
const frame = {
  sampleAt: published,
  fields: ['latitude', 'longitude', 'temperature_c', 'temperature_gradient_c_per_km'],
  resolution: [0.05, 0.1],
  rows: [[35.025, -120.975, 19, 0.8], [35.025, -120.875, null, 0.2], [35.125, -120.975, 17, 0.1]],
};
const badFrame = {...frame, rows: [...frame.rows, frame.rows[0]]};
const crossed = {id: 'ridge', next: {state: 'true', lastSampleAt: published}, fire: true, value: 19, reason: null};

// C1: The whole value catches leaked sampler metadata or a nested fire field;
// TypeScript checks the exported types separately.
test('C1: a rising evaluation has only the public result fields', () => {
  assert.deepEqual(evaluateWatch(watch, frame), crossed);
});

// C2: An empty frame is a valid index, not a withheld layer or an error.
test('C2: indexes an empty frame', () => {
  assert.deepEqual(indexFrame({...frame, rows: []}), {axes: null, north: 0, east: 0, cells: new Map()});
});

test('C2: preserves the grid error type for duplicate cells', () => {
  assert.throws(() => indexFrame(badFrame), error => error.constructor === HabitatGridError);
});

// C2/C3: The named wire column must survive indexing, and a supplied index
// must be used instead of trying to index the frame again.
test('C3: samples the selected field through a supplied index', () => {
  const selected = {...frame, valueField: 'temperature_gradient_c_per_km'};
  assert.deepEqual(evaluateWatch(watch, badFrame, indexFrame(selected)), {
    id: 'ridge', next: {state: 'false', lastSampleAt: published}, fire: false, value: 0.8, reason: null,
  });
});

// C3: Refiring on a steady true or firing before a false baseline are both bugs.
for (const state of ['true', 'unknown']) {
  test(`C3: a true reading from ${state} sets the snapshot without firing`, () => {
    const prev = {state, lastSampleAt: state === 'unknown' ? null : before};
    assert.deepEqual(evaluateWatch({...watch, prev}, frame), {...crossed, fire: false});
  });
}

// C3: A false reading must re-arm an already-true watch.
test('C3: a new below-threshold reading changes true to false', () => {
  const prev = {state: 'true', lastSampleAt: before};
  assert.deepEqual(evaluateWatch({...watch, prev, lat: 35.125}, frame), {
    id: 'ridge', next: {state: 'false', lastSampleAt: published}, fire: false, value: 17, reason: null,
  });
});

// C3: A stale timestamp must not change state, but the sampled value is still reported.
for (const [label, sampleAt] of [['older', '2026-11-18T12:00:00Z'], ['equal instant', '2026-11-19T13:00:00+01:00']]) {
  test(`C3: a true reading with an ${label} timestamp cannot fire`, () => {
    assert.deepEqual(evaluateWatch(watch, {...frame, sampleAt}), {...crossed, next: watch.prev, fire: false});
  });
}

// C3: Neither kind of gap may borrow a neighboring reading, and outside must
// remain distinguishable; all are dated evaluations, not skipped frames.
for (const [label, position, reason] of [
  ['empty cell within the bounds', {lat: 35.075}, 'gap'],
  ['occupied cell with a null value', {lon: -120.875}, 'gap'],
  ['position beyond the grid', {lat: 36}, 'outside'],
]) {
  test(`C3: ${label} preserves the last known state and advances the clock`, () => {
    assert.deepEqual(evaluateWatch({...watch, ...position}, frame), {
      id: 'ridge', next: {state: 'false', lastSampleAt: published}, fire: false, value: null, reason,
    });
  });
}

// C3: Unlike a dated unknown reading, neither of these exits advances the clock.
for (const [label, input, reason] of [['withheld frame', null, 'withheld'], ['duplicate-cell frame', badFrame, 'bad-tile']]) {
  test(`C3: ${label} leaves the prior snapshot unchanged`, () => {
    assert.deepEqual(evaluateWatch(watch, input), {id: 'ridge', next: watch.prev, fire: false, value: null, reason});
  });
}

// C4: Grouping by layer could reorder results; a missing layer must not fall
// back to another layer, and a bad frame must not stop neighboring evaluations.
test('C4: default indexing returns a whole result for each watch in input order', () => {
  const watches = [watch, {...watch, id: 'missing', layer: 'chlorophyll'},
    {...watch, id: 'broken', layer: 'sst-contrast'}, {...watch, id: 'edge', lat: 35.125}];
  const frames = new Map([['sst-contrast', badFrame], ['water-temp', frame]]);
  assert.deepEqual(evaluateWatches(watches, frames), [
    crossed,
    {id: 'missing', next: watch.prev, fire: false, value: null, reason: 'withheld'},
    {id: 'broken', next: watch.prev, fire: false, value: null, reason: 'bad-tile'},
    {id: 'edge', next: {state: 'false', lastSampleAt: published}, fire: false, value: 17, reason: null},
  ]);
  assert.deepEqual(evaluateWatches([], frames), []);
});

// C4: A cache keyed by layer or timestamp, a failure that is retried, or a
// cache surviving a call boundary would produce different index counts.
test('C4: indexes each frame object once per batch, including thrown failures', () => {
  const distinct = {...frame};
  const frames = new Map([['water-temp', frame], ['alias', frame], ['distinct', distinct], ['broken', badFrame]]);
  const calls = new Map();
  const deps = {index: f => {
    calls.set(f, (calls.get(f) ?? 0) + 1);
    if (f === badFrame) throw new Error('index failed');
    return indexFrame(f);
  }};
  const watches = [watch, {...watch, id: 'bad-1', layer: 'broken'}, {...watch, id: 'alias', layer: 'alias'},
    {...watch, id: 'distinct', layer: 'distinct'}, {...watch, id: 'bad-2', layer: 'broken'}];
  const expected = [
    crossed,
    {id: 'bad-1', next: watch.prev, fire: false, value: null, reason: 'bad-tile'},
    {...crossed, id: 'alias'},
    {...crossed, id: 'distinct'},
    {id: 'bad-2', next: watch.prev, fire: false, value: null, reason: 'bad-tile'},
  ];
  for (const count of [1, 2]) {
    assert.deepEqual(evaluateWatches(watches, frames, deps), expected);
    assert.equal(calls.size, 3);
    for (const f of [frame, distinct, badFrame]) assert.equal(calls.get(f), count);
  }
});
