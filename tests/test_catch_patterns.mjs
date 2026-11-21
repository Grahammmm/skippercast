import test from 'node:test';
import assert from 'node:assert/strict';
import {catchPatterns, PATTERN_MIN_N, PATTERN_MAX_ENTRIES} from '../web/catch-patterns.ts';

function entry(outcome, value, stage) {
  return {outcome, conditions: {v: 1, layers: {water_temp: {value, unit: 'F'}, tide: {stage}}}};
}

test('C1: exported bounds cannot drift from the caller contract', () => {
  assert.deepEqual({PATTERN_MIN_N, PATTERN_MAX_ENTRIES}, {PATTERN_MIN_N: 10, PATTERN_MAX_ENTRIES: 2000});
});

test('C2: empty and unreadable inputs use the same result shape', () => {
  const unreadable = () => { throw new Error('unreadable fixture'); };
  const inaccessible = new Proxy([], {get: unreadable});
  assert.deepEqual(catchPatterns([]), {n: 0, shown: false, bands: []});
  assert.deepEqual(catchPatterns(inaccessible), {n: 0, shown: false, bands: []});
  const entries = [{outcome: 'fish', get conditions() { return unreadable(); }}, entry('blank', 55, 'ebb')];
  Object.defineProperty(entries, 2, {get: unreadable});
  assert.deepEqual(catchPatterns(entries), {n: 1, shown: false, bands: []});
});

test('C3: hides bands at nine but not ten, counting entries rather than fish caught', () => {
  const fish = {...entry('fish', 56.75, 'ebb'), count: 4};
  const nine = Object.freeze(Array(9).fill(fish));
  assert.deepEqual(catchPatterns(nine), {n: 9, shown: false, bands: []});
  assert.deepEqual(catchPatterns([...nine, entry('blank', 56, 'ebb')]), {
    n: 10, shown: true, bands: [{bandF: 56, tide: 'ebb', fish: 9, blank: 1}],
  });
});

test('C3: invalid records cannot raise n or unlock the bands', () => {
  const valid = entry('fish', 52, 'ebb');
  const withTemp = water_temp => ({outcome: 'fish', conditions: {v: 1, layers: {water_temp}}});
  const invalid = [
    entry('unknown', 52, 'ebb'),
    entry('FISH', 52, 'ebb'),
    {outcome: 'fish'},
    {outcome: 'blank', conditions: null},
    {outcome: 'fish', conditions: {...valid.conditions, v: 2}},
    {outcome: 'fish', conditions: {...valid.conditions, v: '1'}},
    {outcome: 'fish', conditions: {v: 1}},
    {outcome: 'fish', conditions: {v: 1, layers: {}}},
    withTemp({missing: 'not archived'}),
    withTemp({value: 52}),
    withTemp({value: 12, unit: 'C'}),
    withTemp({value: '52', unit: 'F'}),
    ...[NaN, Infinity, -Infinity].map(value => withTemp({value, unit: 'F'})),
  ];
  for (const [i, bad] of invalid.entries()) {
    assert.deepEqual(catchPatterns([...Array(9).fill(valid), bad]), {n: 9, shown: false, bands: []},
      `invalid fixture ${i} must not count`);
  }
});

test('C3: floors temperatures, groups absent stages, and sorts by number then plain string order', () => {
  const noTide = {outcome: 'blank', conditions: {v: 1, layers: {water_temp: {value: 2, unit: 'F'}}}};
  assert.deepEqual(catchPatterns([
    entry('fish', 10.01, 'ebb'),
    entry('blank', 2.999, 'ebb'),
    entry('blank', -0.001, 'ebb'),
    entry('fish', 2.5, 'Flood'),
    entry('fish', -1.01, 'ebb'),
    entry('fish', 2.2, 'ebb'),
    entry('fish', 2.8),
    entry('blank', 2.1, ''),
    entry('fish', 2.9, 1),
    noTide,
  ]), {
    n: 10, shown: true, bands: [
      {bandF: -2, tide: 'ebb', fish: 1, blank: 0},
      {bandF: -1, tide: 'ebb', fish: 0, blank: 1},
      {bandF: 2, tide: 'Flood', fish: 1, blank: 0},
      {bandF: 2, tide: 'ebb', fish: 1, blank: 1},
      {bandF: 2, tide: 'unknown', fish: 2, blank: 2},
      {bandF: 10, tide: 'ebb', fish: 1, blank: 0},
    ],
  });
});

test('C3: the cap is on rows read, not on eligible rows counted', () => {
  const rows = Array(2002).fill(entry('unknown', 58, 'ebb'));
  rows.fill(entry('fish', 58, 'ebb'), 0, 9);
  rows[1999] = entry('blank', 58, 'ebb');
  rows[2000] = entry('blank', 59, 'flood');
  let readPastCap = false;
  Object.defineProperty(rows, 2001, {get() { readPastCap = true; }});
  assert.deepEqual({result: catchPatterns(rows), readPastCap}, {
    result: {n: 10, shown: true, bands: [{bandF: 58, tide: 'ebb', fish: 9, blank: 1}]},
    readPastCap: false,
  });
});
