// RF0708-2: web/units.ts is the one kt/ft source for the landing readout, the habitat
// feed and the brief model. Its exact factors leave every number a visitor sees as it was
// with the old rounded spellings (wind/gust 1.943844, swell 3.28084), by sweep and through
// buoyReadings; a missing wind still reads "No reading".
import assert from 'node:assert/strict';
import test from 'node:test';
import {FT_PER_M, KT_PER_MS, M_PER_FT, M_PER_NMI} from '../web/units.ts';
import {airportReading, buoyReading} from '../dist/live-conditions.js';
import {buoyReadings} from '../web/landing/readings.ts';

test('units: exact definitions', () => {
  assert.equal(M_PER_FT, 0.3048);
  assert.equal(M_PER_NMI, 1852);
  assert.ok(Math.abs(FT_PER_M * M_PER_FT - 1) <= 1e-15);
  assert.ok(Math.abs(KT_PER_MS - 1.9438444924406) <= 1e-12);
});

test('units: wind and gust knots unchanged for 0.0..60.0 m/s by 0.1', () => {
  for (let i = 0; i <= 600; i++) {
    const v = i / 10;
    assert.equal(Math.round(v * KT_PER_MS), Math.round(v * 1.943844), `${v} m/s`);
  }
});

test('units: swell feet unchanged for 0.00..15.00 m by 0.01', () => {
  for (let i = 0; i <= 1500; i++) {
    const v = i / 100;
    assert.equal((v * FT_PER_M).toFixed(1), (v * 3.28084).toFixed(1), `${v} m`);
  }
});

const NOW = Date.parse('2026-10-07T20:00:00Z');
const AT = new Date(NOW - 20 * 60000).toISOString();
const source = (station, units, row) => ({name: 'x', status: 'ok', max_age_hours: 2, data: {station, units, observations: [{time: AT, ...row}]}});
const feed = wspd => ({schema_version: 1, region_id: 'morro-bay', generated_at: AT, sources: {
  offshore: source('46028', {WSPD: 'm/s', GST: 'm/s'}, {WSPD: wspd, GST: 10.3}),
  'diablo-spectrum': source('46215', {SwH: 'm'}, {SwH: 1.52}),
}});
const shown = f => Object.fromEntries(buoyReadings(f, {}, NOW).map(r => [r.id, [r.reading, r.unit, r.detail]]));

test('units: buoyReadings shows the strings main showed (7.7 m/s, gust 10.3 m/s, swell 1.52 m)', () => {
  const r = shown(feed(7.7));
  assert.deepEqual(r.wind, ['15', 'kt', 'gusts 20']);
  assert.deepEqual(r.swell, ['5.0', 'ft', undefined]);
});

test('units: a missing wind speed still reads No reading', () => {
  const r = shown(feed(null));
  assert.deepEqual(r.wind, ['No reading', undefined, undefined]);
  assert.deepEqual(r.swell, ['5.0', 'ft', undefined]);
});

// RF1949-1: dist/live-conditions.js and dist/bite-evidence.js take their factors from
// web/units.ts; the strings they show are the ones the old literals showed.
test('units: dist current speed kt (toFixed 2) unchanged for 0.000..5.000 m/s by 0.001', () => {
  for (let i = 0; i <= 5000; i++) {
    const v = i / 1000;
    assert.equal((v * KT_PER_MS).toFixed(2), (v * 1.943844).toFixed(2), `${v} m/s`);
  }
  assert.equal((Math.hypot(0, 0) * KT_PER_MS).toFixed(2), '0.00');
});

test('units: dist airport wind kt (rounded) unchanged for 0..200 km/h by 0.1', () => {
  for (let i = 0; i <= 2000; i++) {
    const v = i / 10;
    assert.equal(Math.round(v * (1000 / M_PER_NMI)), Math.round(v * (1 / 1.852)), `${v} km/h`);
  }
});

const airport = (kmh) => airportReading({properties: {
  timestamp: new Date(NOW).toISOString(),
  windSpeed: {unitCode: 'wmoUnit:km_h-1', value: kmh},
  windGust: {unitCode: 'wmoUnit:km_h-1', value: kmh},
}}, NOW);

test('units: dist airport wind converts km/h to kt through units.ts; 0 stays 0, not -0', () => {
  const r = airport(37.04);
  assert.ok(Math.abs(r.wind - 20) < 1e-9 && Math.abs(r.gust - 20) < 1e-9);
  const calm = airport(0);
  assert.ok(Object.is(calm.wind, 0) && Object.is(calm.gust, 0));
  assert.equal(airport(-1).wind, null);
});

test('units: dist buoy reading converts m and m/s through units.ts; calm wind is 0, not -0', () => {
  const f = feed(0);
  f.sources.offshore.data.units.WVHT = 'm';
  f.sources.offshore.data.observations[0].WVHT = 1;
  const r = buoyReading(f, 'offshore', NOW);
  assert.ok(Math.abs(r.height - FT_PER_M) < 1e-9);
  assert.ok(Object.is(r.wind, 0));
  assert.ok(Math.abs(r.gust - 10.3 * KT_PER_MS) < 1e-9);
});
