import assert from 'node:assert/strict';
import test from 'node:test';
import {reasonsFor} from '../web/area-reasons.ts';

const record = (date, text = 'Rocky reef.', extra = {}) => ({
  area: 'A', kind: 'survey', date, text, source: 'Fixture survey', ...extra,
});
const reason = (date, text = 'Rocky reef.', sourceURL = null) => ({
  date, text, source: 'Fixture survey', sourceURL,
});
const at = (evidence, now, timeZone) => reasonsFor('A', evidence, Date.parse(now), timeZone);

// UTC midnight used to admit the next Pacific day during the previous evening.
for (const [season, date, evening, before, midnight, after] of [
  ['PST', '2026-11-22', '01:00:00Z', '07:59:59.999Z', '08:00:00Z', '08:00:00.001Z'],
  ['PDT', '2026-07-22', '00:30:00Z', '06:59:59.999Z', '07:00:00Z', '07:30:00Z'],
]) {
  test(`C1: ${season} bare dates switch at Pacific midnight, not UTC midnight`, () => {
    const evidence = [record(date)];
    for (const time of [evening, before]) assert.deepEqual(at(evidence, `${date}T${time}`), []);
    for (const time of [midnight, after]) assert.deepEqual(at(evidence, `${date}T${time}`), [reason(date)]);
  });
}

test('C1: a zone ahead of UTC admits its calendar date before UTC midnight', () => {
  assert.deepEqual(at([record('2026-11-22')], '2026-11-21T15:00:00Z', 'Asia/Tokyo'), [reason('2026-11-22')]);
});

test('C2: a bare year switches at Pacific New Year, not UTC New Year', () => {
  for (const date of ['2027', 2027]) {
    const evidence = [record(date)];
    assert.deepEqual(at(evidence, '2026-12-31T23:30:00-08:00'), []);
    assert.deepEqual(at(evidence, '2026-12-31T23:59:59.999-08:00'), []);
    assert.deepEqual(at(evidence, '2027-01-01T00:00:00-08:00'), [reason('2027')]);
  }
});

test('C2: a full timestamp compares instants rather than dates and keeps its written day', () => {
  const now = '2026-11-22T01:00:00Z';
  assert.deepEqual(at([record('2026-11-21T17:01:00-08:00')], now), []);
  assert.deepEqual(at([record('2026-11-22T00:59:00Z')], now), [reason('2026-11-22')]);
  assert.deepEqual(at([record('2026-11-21T17:00:00-08:00')], now), [reason('2026-11-21')]);
});

test('C3: invalid zones fall back to Pacific midnight, not UTC or host time', () => {
  const evidence = [record('2026-11-22')];
  assert.deepEqual(at(evidence, '2026-11-22T01:00:00Z', 'Invalid/Zone'), []);
  assert.deepEqual(at(evidence, '2026-11-22T08:00:00Z', 'Invalid/Zone'), [reason('2026-11-22')]);
});

test('C3: local admission never changes UTC sorting, ties, dedupe, kind limits or the cap', () => {
  // Replacing the bare-date sort key with local midnight would put it first,
  // rather than tying the timestamp and falling behind it by kind.
  const evidence = [
    record('2026-11-22', 'Bare day', {id: 'day'}),
    record('2026-11-22T00:00:00Z', 'Exact tie', {id: 'tie', kind: 'report'}),
    record('2026-11-22T00:00:00Z', 'Exact tie', {id: 'tie', kind: 'report', sourceURL: 'https://example.test/report'}),
    record('2026-11-21T23:59:59Z', 'Duplicate ID', {id: 'day', kind: 'current'}),
    record('2026-11-20', 'Same kind'),
    record(2026, 'Bare year', {kind: 'screen'}),
    record('2025-12-31', 'Fourth eligible kind', {kind: 'tide'}),
  ];
  assert.deepEqual(at(evidence, '2026-11-22T08:00:00Z'), [
    reason('2026-11-22', 'Exact tie', 'https://example.test/report'),
    reason('2026-11-22', 'Bare day'),
    reason('2026', 'Bare year'),
  ]);
});

test('C4: explicit UTC reproduces UTC midnight boundaries for bare dates and years', () => {
  for (const [date, before, starts] of [
    ['2026-11-22', '2026-11-21T23:59:59.999Z', '2026-11-22T00:00:00Z'],
    ['2027', '2026-12-31T23:59:59.999Z', '2027-01-01T00:00:00Z'],
  ]) {
    assert.deepEqual(at([record(date)], before, 'UTC'), []);
    assert.deepEqual(at([record(date)], starts, 'UTC'), [reason(date)]);
  }
});

test('C1: malformed dates and nonfinite clocks still yield no reasons', () => {
  for (const date of ['tomorrow', '2026-02-30', '2026-11-22T29:00:00Z']) {
    assert.deepEqual(at([record(date)], '2026-11-23T08:00:00Z'), []);
  }
  assert.deepEqual(reasonsFor('A', [record('2026-11-22')], NaN), []);
  assert.deepEqual(at([record('2026-11-22')], '2026-11-20T00:00:00Z'), []);
});
