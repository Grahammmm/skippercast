import test from 'node:test';
import assert from 'node:assert/strict';
import {saveSequentially} from '../web/gpx-import-plan.ts';
import {gpxSaveProgress} from '../web/gpx-save-progress.ts';

test('C1: starts at zero without being finished', () => {
  // Applying the completion equality before any update would mark 0 of 0 finished.
  assert.deepEqual(gpxSaveProgress().state(), {done: 0, total: 0, fraction: 0, finished: false});
});

test('C2: tracks accepted steps from zero to completion', () => {
  // Excluding zero or rounding the fraction early would misreport valid steps.
  const {update, state} = gpxSaveProgress();
  assert.equal(update(0, 4), undefined);
  assert.deepEqual(state(), {done: 0, total: 4, fraction: 0, finished: false});
  assert.equal(update(1, 4), undefined);
  assert.deepEqual(state(), {done: 1, total: 4, fraction: 0.25, finished: false});
  assert.equal(update(4, 4), undefined);
  assert.deepEqual(state(), {done: 4, total: 4, fraction: 1, finished: true});
});

test('C2: ignores malformed counts without changing the current state', () => {
  // A range-only guard admits fractions and can miss NaN.
  const {update, state} = gpxSaveProgress();
  update(2, 4);
  for (const [done, total] of [[2.5, 4], [2, 4.5], [NaN, 4], [2, Infinity], [-1, 5], [0, 0], [0, -1], [5, 4]]) {
    assert.equal(update(done, total), undefined);
    assert.deepEqual(state(), {done: 2, total: 4, fraction: 0.5, finished: false}, `update(${done}, ${total})`);
  }
});

test('C2: tracks the last accepted count independently for each total', () => {
  // One global floor would reject a smaller count for a new total; retaining only the current total loses the old floor.
  const {update, state} = gpxSaveProgress();
  update(3, 4);
  assert.equal(update(2, 4), undefined);
  assert.deepEqual(state(), {done: 3, total: 4, fraction: 0.75, finished: false});

  update(1, 2);
  assert.deepEqual(state(), {done: 1, total: 2, fraction: 0.5, finished: false});
  assert.equal(update(2, 4), undefined);
  assert.deepEqual(state(), {done: 1, total: 2, fraction: 0.5, finished: false});

  update(3, 4);
  assert.deepEqual(state(), {done: 3, total: 4, fraction: 0.75, finished: false});
});

test('C3: the saver callback reaches completion despite a rejected save', async () => {
  // A callback that needs a receiver would throw inside the saver and leave progress stale.
  const {update, state} = gpxSaveProgress();
  const items = ['first', 'second', 'third'].map((name, index) => ({name, lat: index, lon: index, note: null}));
  const report = await saveSequentially(items, async waypoint => {
    if (waypoint === items[1]) throw new Error('save rejected');
  }, update);

  assert.deepEqual(report, {saved: 2, failed: [{index: 1, name: 'second', error: 'save rejected'}]});
  assert.deepEqual(state(), {done: 3, total: 3, fraction: 1, finished: true});
});
