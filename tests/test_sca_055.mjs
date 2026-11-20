// SCA-055: the advisor samples a forecast point's model row by its manifest index only when the feed requested the
// manifest's points in order at the same coordinates (the saved-trip reader's contract in server/alert-policy.ts).
// Synthetic feeds, offline; values invented.
import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {windowConditions, WINDOW} from '../server/advisor/answers/conditions.ts';
import {advisorBarCheck} from '../server/advisor/answers/bar.ts';

const region = {id: 'synthetic-coast', timezone: 'UTC', forecast_points: [
  {id: 'a', latitude: 1, longitude: 2},
  {id: 'b', latitude: 3, longitude: 4},
]};
const a = ['a', 1, 2], b = ['b', 3, 4];
const time = Date.parse('2026-09-28T09:00:00Z') / 1000;
const wind = kn => ({hourly_units: {time: 'unixtime', wind_speed_10m: 'kn', wind_gusts_10m: 'kn'},
  hourly: {time: [time], wind_speed_10m: [kn], wind_gusts_10m: [kn + 2]}});
const waves = {hourly_units: {time: 'unixtime', wave_height: 'ft', wave_period: 's', wind_wave_height: 'ft', wind_wave_period: 's', swell_wave_height: 'ft', swell_wave_period: 's'},
  hourly: {time: [time], wave_height: [1], wave_period: [8], wind_wave_height: [0.2], wind_wave_period: [4], swell_wave_height: [0.8], swell_wave_period: [8]}};
const read = (points, speeds) => windowConditions({region_id: region.id, forecast: {
  requested_points: points,
  models: {gfs_global: {data: speeds.map(wind)}, ncep_gfswave016: {data: speeds.map(() => waves)}},
}}, region, 'a', '2026-09-28');

test('ordered forecast points preserve the selected port’s reading', () => {
  const day = read([a, b], [1, 27]);
  assert.equal(day.available, true);
  assert.deepEqual(day.wind_kt, [1, 1]);
  assert.equal(day.comfort, 'bumpy'); // The limited wind-and-wave rubric remains unchanged.
});

for (const [label, points, speeds] of [
  ['swapped points and samples', [b, a], [27, 1]],
  ['one point omitted', [b], [27]],
  ['no point list', undefined, [1, 27]],
  ['shifted latitude', [['a', 1.01, 2], b], [1, 27]],
  ['shifted longitude', [['a', 1, 2.01], b], [1, 27]],
]) {
  test(`${label}: the port is unrated and has no numeric readings`, () => {
    const day = read(points, speeds);
    assert.equal(day.available, false);
    assert.equal(day.comfort, 'unknown');
    assert.equal(day.reason, 'forecast locations do not match this regional release');
    for (const key of ['wind_kt', 'gusts_kt', 'seas_ft', 'sea_period_s', 'swell_ft', 'swell_period_s']) {
      assert.equal(day[key], null, key);
    }
  });
}

// ---- the harbour-bar estimate reads the same point rows (server/advisor/answers/bar.ts windowHours) ----

const MORRO = JSON.parse(readFileSync(new URL('../regions/morro-bay/region.json', import.meta.url)));
const DATE = '2026-09-28';                                     // PDT: UTC-7
const NINE = Date.parse('2026-09-28T16:00:00Z') / 1000;        // 9 am PDT, mid-ebb between the tides below
const tide = (t, type) => ({time: t, type, height_ft: type === 'H' ? 5 : 0.5});
const daily = {sources: {tides: {status: 'ok', data: {predictions: [tide('2026-09-28T13:00:00Z', 'H'), tide('2026-09-28T19:00:00Z', 'L'), tide('2026-09-29T01:30:00Z', 'H')]}}}};
const UNIT = k => /direction/.test(k) ? '°' : /period/.test(k) ? 's' : /height/.test(k) ? 'ft' : 'kn';
const HOURS = Array.from({length: 24}, (_, i) => Date.parse('2026-09-28T07:00:00Z') / 1000 + i * 3600);
/** One model row: calm everywhere, or 6.5 ft at 14 s at 9 am (Hazardous mid-ebb on the offshore basis). */
const row = (keys, hazard) => {
  const v = t => {
    const [ft, s] = hazard && t === NINE ? [6.5, 14] : [2, 10];
    return {wind_speed_10m: 6, wind_gusts_10m: 9, wind_direction_10m: 315, wave_height: ft, wave_period: s, swell_wave_height: ft, swell_wave_period: s, swell_wave_direction: 300};
  };
  return {hourly_units: {time: 'unixtime', ...Object.fromEntries(keys.map(k => [k, UNIT(k)]))},
    hourly: {time: HOURS, ...Object.fromEntries(keys.map(k => [k, HOURS.map(t => v(t)[k])]))}};
};
const WIND = ['wind_speed_10m', 'wind_gusts_10m', 'wind_direction_10m'];
const WAVE = ['wave_height', 'wave_period', 'swell_wave_height', 'swell_wave_period', 'swell_wave_direction'];
const manifest = MORRO.forecast_points.map(p => [p.id, p.latitude, p.longitude]);
const CENTRAL = MORRO.forecast_points.findIndex(p => p.id === 'central');
/** A feed whose rows follow `points`; only the central point's own row carries the 9 am hazard. */
const barFeed = points => ({region_id: MORRO.id, forecast: {requested_points: points, models: {
  gfs_global: {data: points.map(() => row(WIND, false))},
  ncep_gfswave016: {data: points.map(([id]) => row(WAVE, id === 'central'))},
}}});
const bar = intel => advisorBarCheck({intel, daily, region: MORRO, port: 'morro-bay', pointId: 'central', date: DATE, window: WINDOW});

test('bar estimate: ordered points read the central point’s own hazardous hour', () => {
  assert.equal(CENTRAL, 1);
  const got = bar(barFeed(manifest));
  assert.equal(got.judged, true);
  assert.equal(got.hazardous_at, '2026-09-28T16:00:00.000Z');
});

test('bar estimate: swapped points give no bar hours, so no reading from another point', () => {
  const swapped = [manifest[1], manifest[0], ...manifest.slice(2)];  // row 1 is now north's calm row
  const got = bar(barFeed(swapped));
  assert.equal(got.judged, false);
  assert.equal(got.hazardous_at, null);
  assert.match(got.note, /missing: forecast hours/);
});
