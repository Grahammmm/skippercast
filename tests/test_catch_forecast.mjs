import test from 'node:test';
import assert from 'node:assert/strict';
import {catchForecastLayers} from '../server/catch-forecast.ts';
import {parseConditionsV1} from '../server/conditions-v1.ts';

const at = '2026-02-28T12:15:00Z';
const run = 'fixture run';
const validAt = '2026-02-28T12:00:00Z';
const hour = Object.freeze({
  wind: 8.125, gust: 13, wind_from: 315.625,
  sea: 7, sea_period: 10, chop: 2, chop_period: 4,
  swell: 5.375, swell_period: 11.625, swell_from: 291.125,
  secondary: 2.5, secondary_from: 200,
  other_wind: 18, other_sea: 9, other_gust: 23,
});
const full = {
  wind: {kn: 8.125, from_deg: 315.625, run, valid_at: validAt},
  swell: {ft: 5.375, period_s: 11.625, from_deg: 291.125, run, valid_at: validAt},
};
const noValue = {missing: 'no value'};
const badFrame = {wind: {missing: 'bad frame'}, swell: {missing: 'bad frame'}};

function expectLayers(actual, expected) {
  assert.deepEqual(actual, expected);
  assert.deepEqual(parseConditionsV1({v: 1, at, layers: actual}), {
    ok: true, value: {v: 1, at, layers: expected},
  });
}

// Archive absence takes precedence over frame validation.
test('C1: null hour is not archived even with bad frame metadata', () => {
  expectLayers(catchForecastLayers(null, '', 'not a date'), {
    wind: {missing: 'not archived'}, swell: {missing: 'not archived'},
  });
});

// Reject unusable run IDs instead of coercing them into provenance.
for (const [label, badRun] of [['empty', ''], ['non-string', 123], ['over 200 characters', 'r'.repeat(201)],
  ['over 400 code units', '🌊'.repeat(201)]]) {
  test(`C1: ${label} run is a bad frame`, () => {
    expectLayers(catchForecastLayers(hour, badRun, validAt), badFrame);
  });
}

// Date.parse alone admits rolled times and fractions too long for the storage budget.
for (const [label, badTime] of [
  ['non-string', null], ['malformed', 'not a date'], ['offset', '2026-02-28T12:00:00+00:00'],
  ['missing seconds', '2026-02-28T12:00Z'], ['trailing newline', `${validAt}\n`],
  ['nonexistent day', '2026-02-30T12:00:00Z'], ['rolled clock', '2026-02-28T24:00:00Z'],
  ['unparseable clock', '2026-02-28T12:61:00Z'],
  ['long fraction', `2026-02-28T12:00:00.${'1'.repeat(2100)}Z`],
]) {
  test(`C1: ${label} timestamp is a bad frame`, () => {
    expectLayers(catchForecastLayers(hour, run, badTime), badFrame);
  });
}

// Keep the accepted metadata unchanged, even when its spelling isn't Date#toISOString's.
test('C1: leap-day UTC timestamps and a 200-character run are copied verbatim', () => {
  const maxRun = '🌊'.repeat(200);
  for (const stamp of ['2024-02-29T00:00:00.1Z', '2024-02-29T00:00:00.12Z', '2024-02-29T00:00:00.123Z']) {
    expectLayers(catchForecastLayers(hour, maxRun, stamp), {
      wind: {...full.wind, run: maxRun, valid_at: stamp},
      swell: {...full.swell, run: maxRun, valid_at: stamp},
    });
  }
});

// A frozen full hour catches in-place edits; distinct values catch rounding or model/partition mix-ups.
test('C2: full hour with an ordinary UTC frame gives unrounded primary model items', () => {
  expectLayers(catchForecastLayers(hour, run, validAt), full);
});

// Calm and flat seas are valid; a north bearing at 360 must fit the snapshot's exclusive upper bound.
test('C2: zero wind and swell are retained and 360-degree bearings become zero', () => {
  expectLayers(catchForecastLayers({...hour, wind: 0, wind_from: 360, swell: 0, swell_from: 360}, run, validAt), {
    wind: {...full.wind, kn: 0, from_deg: 0},
    swell: {...full.swell, ft: 0, from_deg: 0},
  });
});

// A missing primary component must not borrow the second wind model or drop the valid swell.
const absentOrInvalid = [['null', null], ['negative', -0.125], ['NaN', NaN], ['infinite', Infinity],
  ['negative infinite', -Infinity]];
const invalidBearing = [...absentOrInvalid, ['above 360', 360.125]];
for (const [field, values] of [['wind', absentOrInvalid], ['wind_from', invalidBearing]]) {
  for (const [label, value] of values) {
    test(`C2: ${label} ${field} leaves wind missing despite other_wind`, () => {
      expectLayers(catchForecastLayers({...hour, [field]: value}, run, validAt), {wind: noValue, swell: full.swell});
    });
  }
}

// Validate each swell component separately so a bad period or bearing can't leak through a valid height.
for (const [field, values] of [
  ['swell', absentOrInvalid], ['swell_period', [...absentOrInvalid, ['zero', 0]]], ['swell_from', invalidBearing],
]) {
  for (const [label, value] of values) {
    test(`C3: ${label} ${field} leaves only swell missing`, () => {
      expectLayers(catchForecastLayers({...hour, [field]: value}, run, validAt), {wind: full.wind, swell: noValue});
    });
  }
}

test('C3: missing readings in both layers still form a valid snapshot', () => {
  expectLayers(catchForecastLayers({...hour, wind: null, swell: null}, run, validAt), {
    wind: noValue, swell: noValue,
  });
});
