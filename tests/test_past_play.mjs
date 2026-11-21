import assert from 'node:assert/strict';
import test from 'node:test';
import {play} from '../web/hour.ts';
import {nextPlayDay, pastPlayOrder, pastStep} from '../web/past-play.ts';

const today = '2024-03-04';
const older = '2024-02-29';
const newer = '2024-03-02';
const future = '2024-03-05';
const past = [newer, older].map(day => ({day}));

test('C1: sorts distinct observed dates without filling gaps or accepting invalid dates', () => {
  // A shape-only check accepts Feb 30; a date-only parse accepts noncanonical input.
  const extras = [future, today, older, '2024-02-30', '2024-00-10', '2024-02-9', '2024-01-01\n', ''].map(day => ({day}));
  assert.deepEqual(pastPlayOrder([...past, ...extras], today), [older, newer, today]);
});

test('C1: keeps Today even without history', () => {
  // An empty-history early return could drop the endpoint.
  assert.deepEqual(pastPlayOrder([], today), [today]);
});

test('C2: takes the first strictly later listed day, even from a missing selection', () => {
  // Index-based stepping can restart at the oldest day when the selection is missing.
  assert.equal(nextPlayDay('2024-02-28', past, today), older);
  assert.equal(nextPlayDay(older, past, today), newer);
  assert.equal(nextPlayDay('2024-03-01', past, today), newer);
  assert.equal(nextPlayDay(newer, past, today), today);
  assert.equal(nextPlayDay(older, [], today), today);
});

test('C2: stops at or after Today instead of wrapping or entering the future', () => {
  const withFuture = [...past, {day: future}];
  assert.equal(nextPlayDay(today, withFuture, today), null);
  assert.equal(nextPlayDay(future, withFuture, today), null);
});

test('C3: reads the selection each time, steps onto Today, then returns false without writing', () => {
  // Capturing the initial selection or returning false on arrival would break the step protocol.
  let selected = older;
  const writes = [];
  const step = pastStep(() => selected, day => { writes.push(day); selected = day; }, past, today);
  assert.deepEqual([step(), step(), step()], [true, true, false]);
  assert.deepEqual(writes, [newer, today]);
});

test('C3: real play under reduced motion steps once across the gap, then calls onStop', () => {
  // Starting a normal loop or announcing a stop before the step changes this event sequence.
  const events = [];
  const doc = {hidden: false, addEventListener() { events.push('listen'); }, removeEventListener() {}};
  const stop = play({
    step: pastStep(() => older, day => events.push(day), past, today),
    onStop: () => events.push('stop'),
    doc,
    motion: {matches: true, addEventListener() {}, removeEventListener() {}},
  });
  try {
    assert.deepEqual(events, [newer, 'stop']);
  } finally {
    stop();
  }
});
