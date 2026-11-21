import assert from 'node:assert/strict';
import test from 'node:test';
import { CONDITIONS_CSV_COLUMNS, conditionsCsvCells } from '../web/catch-conditions-csv.ts';

const at = '2024-02-29T01:00Z';
const observed = { product: 'fixture', sample_at: at };
const forecast = { run: 'fixture run', valid_at: at };
const snapshot = layers => ({ v: 1, at, layers });
const emptyRow = (note = '') => [...Array(13).fill(''), note];

test('C1: the exact machine headers fix the column order for readers', () => {
  assert.deepEqual(CONDITIONS_CSV_COLUMNS, [
    'water_temp_f', 'contrast_f_per_nm', 'front_nm', 'chlorophyll_mg_m3',
    'current_kn', 'current_toward_deg', 'swell_ft', 'swell_period_s', 'swell_from_deg',
    'wind_kn', 'wind_from_deg', 'tide_stage', 'tide_height_ft', 'conditions_note',
  ]);
});

// Distinguish absent, unvalidated, pending and unavailable data instead of silently collapsing them.
for (const [label, raw, note] of [
  ['null', null, ''],
  ['undefined', undefined, ''],
  ['wrong version', { v: 2, pending: true }, 'invalid'],
  ['invalid layer', snapshot({ water_temp: { ...observed, unit: 'C', value: 56 } }), 'invalid'],
  ['pending', { v: 1, pending: true }, 'pending'],
  ['whole missing', { v: 1, missing: 'no archive, "fixture"' }, 'no archive, "fixture"'],
]) {
  test(`C2: ${label} has the correct whole row`, () => {
    assert.deepEqual(conditionsCsvCells(raw), emptyRow(note));
  });
}

test('C2: failed reflection returns an invalid row instead of throwing', () => {
  const { proxy, revoke } = Proxy.revocable({}, {});
  revoke();
  assert.deepEqual(conditionsCsvCells(proxy), emptyRow('invalid'));
});

test('C3: a full snapshot projects in column order with fixed decimals and half-case rounding', () => {
  // Binary-exact halves isolate rounding from representation error.
  assert.deepEqual(conditionsCsvCells(snapshot({
    water_temp: { ...observed, unit: 'F', value: 56.25 },
    contrast: { ...observed, unit: 'F/nm', value: -0.125 },
    chlorophyll: { ...observed, unit: 'mg/m3', value: 2.625 },
    front_nm: { ...observed, value: 3 },
    current: { ...forecast, kn: 0, toward_deg: 12.5 },
    swell: { ...forecast, ft: 5.75, period_s: 10.5, from_deg: 275.5 },
    wind: { ...forecast, kn: 8.25, from_deg: 320 },
    tide: { stage: '=ebb, "late"', height_ft: -1.25, station: 'fixture station' },
  })), [
    '56.3', '-0.13', '3.0', '2.63', '0.0', '13', '5.8', '11', '276', '8.3', '320',
    "'=ebb, \"late\"", '-1.3', '',
  ]);
});

test('C3: two missing layers are blank and noted in column order, not input order', () => {
  // Insert chlorophyll first: validator field order also differs from CSV order.
  assert.deepEqual(conditionsCsvCells(snapshot({
    chlorophyll: { missing: 'cloud' },
    current: { ...forecast, kn: 1.5, toward_deg: 90 },
    front_nm: { missing: '=no archive' },
    tide: { station: 'fixture station', stage: 'ebb', height_ft: 1 },
  })), [
    '', '', '', '', '1.5', '90', '', '', '', '', '', 'ebb', '1.0',
    'front_nm: =no archive; chlorophyll: cloud',
  ]);
});

test('C3: a missing multi-cell layer does not shift later cells', () => {
  assert.deepEqual(conditionsCsvCells(snapshot({
    swell: { missing: 'no forecast' },
    wind: { ...forecast, kn: 9, from_deg: 325 },
  })), ['', '', '', '', '', '', '', '', '', '9.0', '325', '', '', 'swell: no forecast']);
});

test('C3: omitted layers do not manufacture missing reasons', () => {
  assert.deepEqual(conditionsCsvCells(snapshot({})), emptyRow());
});

test('C3: large finite readings stay in fixed notation', () => {
  assert.deepEqual(conditionsCsvCells(snapshot({
    contrast: { ...observed, unit: 'F/nm', value: -1e21 },
    swell: { ...forecast, ft: 1e21, period_s: 1e21, from_deg: 90 },
  })), [
    '', '-1000000000000000000000.00', '', '', '', '', '1000000000000000000000.0',
    '1000000000000000000000', '90', '', '', '', '', '',
  ]);
});

test('C3: both text cells guard the account CSV prefixes without trimming or adding CSV quotes', () => {
  for (const [text, expected] of [
    [' \n=fixture', "' \n=fixture"], ['+fixture', "'+fixture"], ['-fixture', "'-fixture"],
    ['@fixture', "'@fixture"], [' \tfixture', "' \tfixture"], [' \n\rfixture', "' \n\rfixture"],
    [' \nfixture = note', ' \nfixture = note'],
  ]) {
    assert.deepEqual(conditionsCsvCells({ v: 1, missing: text }), emptyRow(expected));
    assert.deepEqual(conditionsCsvCells(snapshot({ tide: { stage: text, height_ft: 0, station: 'fixture' } })),
      ['', '', '', '', '', '', '', '', '', '', '', expected, '0.0', '']);
  }
});
