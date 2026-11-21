import test from 'node:test';
import assert from 'node:assert/strict';
import {planGpxImport, saveSequentially} from '../web/gpx-import-plan.ts';

const waypoint = (name, lat, lon, note = null) => Object.freeze({name, lat, lon, note});

test('C1: an empty file has an empty plan', () => {
  // Empty input must not produce a separate return shape.
  assert.deepEqual(planGpxImport([{lat: 1, lon: 2}], []), {save: [], duplicates: [], invalid: []});
});

test('C1: groups rounded duplicates against both sources in file order', () => {
  // Exact equality, truncation, or comparing only one axis misclassifies these points.
  const existing = Object.freeze([{lat: 12.345679, lon: -34.567889}]);
  const savedMatch = waypoint('existing match', 12.345681, -34.567891);
  const first = waypoint('same name', 12.345674, -34.567891, 'first note');
  const fileMatch = waypoint('file match', 12.345671, -34.567889, 'different note');
  const lonDiff = waypoint('same name', 12.345681, -34.567884);
  const repeat = waypoint('repeat', 12.345674, -34.567891);
  const candidates = Object.freeze([savedMatch, first, fileMatch, lonDiff, repeat]);
  assert.deepEqual(planGpxImport(existing, candidates), {
    save: [first, lonDiff], duplicates: [savedMatch, fileMatch, repeat], invalid: [],
  });
});

test('C1: validates both axes before deduplication and keeps inclusive endpoints', () => {
  // A just-outside value can share a rounded key with a valid endpoint.
  const invalid = [
    waypoint('high latitude', 90.000001, 180), waypoint('low latitude', -90.000001, -180),
    waypoint('high longitude', 90, 180.000001), waypoint('low longitude', -90, -180.000001),
    waypoint('NaN latitude', NaN, 1), waypoint('NaN longitude', 1, NaN),
    waypoint('infinite latitude', Infinity, 1), waypoint('infinite longitude', 1, -Infinity),
  ];
  const north = waypoint('north', 90, 180);
  const south = waypoint('south', -90, -180);
  assert.deepEqual(planGpxImport([], [...invalid.slice(0, 2), north, south, ...invalid.slice(2)]), {
    save: [north, south], duplicates: [], invalid,
  });
});

test('C1: uses the exact rounded key near zero without applying a capacity limit', () => {
  // Negative values that round to -0.00000 are not equivalent to exact -0.
  const zero = waypoint('exact signed zero', -0, 0);
  const negative = waypoint('negative fraction', -0.000001, 0);
  const unique = Array.from({length: 101}, (_, i) => waypoint(`point ${i}`, 1, i));
  assert.deepEqual(planGpxImport([{lat: 0, lon: 0}], [zero, negative, ...unique]), {
    save: [negative, ...unique], duplicates: [zero], invalid: [],
  });
});

const items = Object.freeze([waypoint('first', 1, 1), waypoint('second', 2, 2), waypoint('third', 3, 3)]);

test('C2: no save or progress for an empty selection', async () => {
  // No implicit initial or final progress event should fire on empty input.
  const calls = [];
  assert.deepEqual(await saveSequentially([], async () => calls.push('save'), (...args) => calls.push(args)), {
    saved: 0, failed: [],
  });
  assert.deepEqual(calls, []);
});

test('C2: waits for both fulfillment and rejection before advancing', async () => {
  // Concurrent starts or premature progress would appear before a deferred promise settles.
  const gates = items.map(() => Promise.withResolvers());
  const events = [];
  const report = saveSequentially(items, w => {
    events.push(w);
    return gates[items.indexOf(w)].promise;
  }, (done, total) => events.push([done, total]));
  const nextTurn = () => new Promise(resolve => setImmediate(resolve));

  await nextTurn();
  assert.deepEqual(events, [items[0]]);
  gates[0].resolve(undefined);
  await nextTurn();
  assert.deepEqual(events, [items[0], [1, 3], items[1]]);
  gates[1].reject(new Error('second failed'));
  await nextTurn();
  assert.deepEqual(events, [items[0], [1, 3], items[1], [2, 3], items[2]]);
  gates[2].resolve(undefined);
  assert.deepEqual(await report, {saved: 2, failed: [{index: 1, name: 'second', error: 'second failed'}]});
  assert.deepEqual(events, [items[0], [1, 3], items[1], [2, 3], items[2], [3, 3]]);
});

test('C2: reports synchronous and non-Error failures despite throwing progress', async () => {
  // A progress exception must neither count as a failure nor stop later attempts.
  const progress = [];
  const report = await saveSequentially(items, w => {
    if (w === items[0]) throw new Error('');
    if (w === items[1]) return Promise.reject(429);
    return Promise.resolve();
  }, (...args) => {
    progress.push(args);
    throw new Error('progress failed');
  });
  assert.deepEqual(report, {saved: 1, failed: [
    {index: 0, name: 'first', error: ''}, {index: 1, name: 'second', error: '429'},
  ]});
  assert.deepEqual(progress, [[1, 3], [2, 3], [3, 3]]);
});

test('C2: a rejection without a string representation still returns a report', async () => {
  // String(Object.create(null)) throws; formatting must not turn a failed save into a rejected import.
  assert.deepEqual(await saveSequentially([items[0]], () => Promise.reject(Object.create(null))), {
    saved: 0, failed: [{index: 0, name: 'first', error: 'Unknown error'}],
  });
});
