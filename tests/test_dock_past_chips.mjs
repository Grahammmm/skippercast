import assert from 'node:assert/strict';
import test from 'node:test';
import {pastChips, chipKey} from '../web/dock-past-chips.ts';
import {localParts, pastDays} from '../web/hour.ts';

// Unsorted, sparse observations across New Year catch rank-based offsets and reversed order.
const past = Object.freeze([
  Object.freeze({day: '2026-01-03', weekday: 'Sat'}),
  Object.freeze({day: '2025-12-28', weekday: 'Sun'}),
  Object.freeze({day: '2025-12-31', weekday: 'Wed'}),
]);
const today = '2026-01-04';
const chips = [
  {day: '2025-12-28', weekday: 'Sun', offset: 7, date: 28, selected: false},
  {day: '2025-12-31', weekday: 'Wed', offset: 4, date: 31, selected: false},
  {day: '2026-01-03', weekday: 'Sat', offset: 1, date: 3, selected: false},
];
const empty = {chips: [], pastSelected: false};

test('C1: orders sparse chips oldest first across a year boundary', () => {
  assert.deepEqual(pastChips(past, today, null), {chips, pastSelected: false});
});

test('C1: retains only the first weekday for a date and excludes offsets 0, 8 and future days', () => {
  const entries = [
    {day: today, weekday: 'Sun'},
    ...past,
    {day: '2025-12-31', weekday: 'Duplicate'},
    {day: '2025-12-27', weekday: 'Sat'},
    {day: '2026-01-05', weekday: 'Mon'},
  ];
  assert.deepEqual(pastChips(entries, today, null), {chips, pastSelected: false});
});

test('C1: keeps a real leap day across February and March', () => {
  assert.deepEqual(pastChips([{day: '2024-02-29', weekday: 'Thu'}], '2024-03-01', null), {
    chips: [{day: '2024-02-29', weekday: 'Thu', offset: 1, date: 29, selected: false}],
    pastSelected: false,
  });
});

test('C1: rejects malformed observation dates rather than accepting parser rollover or coercion', () => {
  const valid = {day: '2026-03-01', weekday: 'Sun'};
  const invalid = [
    '2026-02-29', '2026-02-30', '2026-03-00', '2026-03-32', '2026-13-01',
    '2026-03-1', '2026/03/01', '2026-03-01T00:00:00Z', '2026-03-01\n', '',
  ].map(day => ({day, weekday: 'Invalid'}));
  assert.deepEqual(pastChips([...invalid, valid], '2026-03-03', null), {
    chips: [{...valid, offset: 2, date: 1, selected: false}],
    pastSelected: false,
  });
});

test('C1: malformed Today yields no chips even if normalizing it would match a valid day', () => {
  for (const bad of ['2026-02-30', '2026-03-2', '2026-03-02\n', '2026-13-02', '']) {
    assert.deepEqual(pastChips([{day: '2026-03-01', weekday: 'Sun'}], bad, '2026-03-01'), empty, bad);
  }
});

// Measure both a 23-hour and a 25-hour local day: host-local midnight math
// would produce fractional or rounded offsets instead of calendar-day counts.
test('C1: uses calendar offsets through both DST transitions', () => {
  const zone = 'America/Los_Angeles';
  const priorZone = process.env.TZ;
  process.env.TZ = zone;
  try {
    for (const [nowIso, available, expected] of [
      ['2026-03-09T07:00:00Z', ['2026-03-06T08:00:00Z', '2026-03-08T08:00:00Z'], [
        {day: '2026-03-06', weekday: 'Fri', offset: 3, date: 6, selected: false},
        {day: '2026-03-08', weekday: 'Sun', offset: 1, date: 8, selected: false},
      ]],
      ['2026-11-02T08:00:00Z', ['2026-10-31T07:00:00Z', '2026-11-01T07:00:00Z'], [
        {day: '2026-10-31', weekday: 'Sat', offset: 2, date: 31, selected: false},
        {day: '2026-11-01', weekday: 'Sun', offset: 1, date: 1, selected: false},
      ]],
    ]) {
      const now = new Date(nowIso);
      const {day} = localParts(now, zone);
      assert.deepEqual(pastChips(pastDays(now, zone, available), day, null), {chips: expected, pastSelected: false});
    }
  } finally {
    if (priorZone === undefined) delete process.env.TZ;
    else process.env.TZ = priorZone;
  }
});

test('C2: marks only the matching chip and sets the past flag', () => {
  assert.deepEqual(pastChips(past, today, '2025-12-31'), {
    chips: [chips[0], {...chips[1], selected: true}, chips[2]],
    pastSelected: true,
  });
});

test('C2: null, missing, or filtered selections never set the past flag', () => {
  const entries = [...past, {day: '2025-12-27', weekday: 'Sat'}];
  for (const selected of [null, '2026-01-02', '2025-12-27']) {
    assert.deepEqual(pastChips(entries, today, selected), {chips, pastSelected: false});
  }
  assert.deepEqual(pastChips([], today, '2026-01-03'), empty);
});

const keys = ['ArrowLeft', 'ArrowRight', 'Home', 'End'];
const [oldest, middle, newest] = chips.map(chip => chip.day);
// The matrix catches wraparound, skipping Today, and walking calendar gaps instead of chips.
for (const [label, current, expected] of [
  ['oldest', oldest, [oldest, middle, oldest, 'today']],
  ['middle', middle, [oldest, newest, oldest, 'today']],
  ['newest', newest, [middle, 'today', oldest, 'today']],
  ['Today', 'today', [newest, 'today', oldest, 'today']],
  ['an unknown day', '2026-01-01', [newest, 'today', oldest, 'today']],
]) {
  test(`C3: each key moves correctly from ${label}`, () => {
    for (const [i, key] of keys.entries()) assert.equal(chipKey(chips, current, key), expected[i], key);
  });
}

test('C3: every key returns Today when no chips exist', () => {
  for (const key of keys) assert.equal(chipKey([], oldest, key), 'today', key);
});
