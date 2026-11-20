import test from 'node:test';
import assert from 'node:assert/strict';
import * as fixture from '../e2e/forecast-fixture.ts';
const {forecastFixture, sharedForecastPoint} = fixture;

const forecast = search => new URL(`/api/om/v1/forecast?${search}`, 'https://fixture.invalid');
const now = Date.UTC(2026, 9, 1, 21);

test('offline browser fixture matches requested points, units and finite forecast horizon', () => {
  const rows = forecastFixture(forecast('latitude=0,1&longitude=2,-3&hourly=wind_speed_10m,wind_gusts_10m,visibility,unknown_field&wind_speed_unit=kn&timeformat=unixtime'), now);
  assert.equal(rows.length, 2);
  assert.deepEqual(rows.map(r => [r.latitude, r.longitude]), [[0, 2], [1, -3]]);
  const meta = forecastFixture(new URL('https://fixture.invalid/api/om/data/gfs_global/static/meta.json'), now);
  for (const row of rows) {
    assert.equal(row.hourly_units.wind_speed_10m, 'kn');
    assert.equal(row.hourly_units.visibility, 'm');
    assert.equal(row.hourly.time.length, 216);
    assert.equal(row.hourly.time.at(-1), meta.data_end_time);
    assert.equal(new Set(row.hourly.time).size, 216);
    assert.ok(row.hourly.unknown_field.every(v => v === null));
    assert.ok(row.hourly.wind_gusts_10m.every((v, i) => v >= row.hourly.wind_speed_10m[i]));
  }
});

test('offline marine fixture uses feet, seconds and direction degrees when requested', () => {
  const row = forecastFixture(new URL('https://fixture.invalid/api/om/v1/marine?latitude=0&longitude=2&hourly=wave_height,wave_period,wave_direction&length_unit=imperial'), now);
  assert.deepEqual([row.hourly_units.wave_height, row.hourly_units.wave_period, row.hourly_units.wave_direction], ['ft', 's', '°']);
  assert.deepEqual([row.hourly.wave_height[0], row.hourly.wave_period[0], row.hourly.wave_direction[0]], [2.5, 12, 290]);
});

test('invalid coordinates or wind units cannot produce a calm synthetic forecast', () => {
  for (const search of ['', 'latitude=0', 'latitude=0,1&longitude=2', 'latitude=0,,1&longitude=2,3,4',
    'latitude=Infinity&longitude=2', 'latitude=0&longitude=181']) {
    assert.throws(() => forecastFixture(forecast(search), now), /latitude and longitude/, search || 'both absent');
  }
  assert.throws(() => forecastFixture(forecast('latitude=0&longitude=2&wind_speed_unit=wrong'), now), /wind_speed_unit/);
});

test('default and explicit km/h requests return converted readings, not relabelled knots', () => {
  for (const unit of ['', '&wind_speed_unit=kmh']) {
    const rows = forecastFixture(forecast(`latitude=0,1&longitude=2,-3&hourly=wind_speed_10m${unit}`), now);
    assert.deepEqual(rows.map(r => [r.latitude, r.longitude, r.hourly_units.wind_speed_10m, r.hourly.wind_speed_10m[0]]),
      [[0, 2, 'km/h', 11.1], [1, -3, 'km/h', 11.1]]);
    assert.equal(rows[0].hourly_units.time, 'iso8601');
    assert.equal(rows[0].hourly.time[0], '2026-10-01T00:00');
  }
});

test('the shared-feed builder preserves the units required by the brief', () => {
  const point = {latitude: 0, longitude: 2};
  const wind = sharedForecastPoint({...point, hourly: {wind_speed_10m: [], visibility: [], temperature_2m: []}}, now);
  const waves = sharedForecastPoint({...point, hourly: {wave_height: []}}, now);
  assert.deepEqual(wind.hourly_units, {time: 'unixtime', wind_speed_10m: 'kn', visibility: 'm', temperature_2m: '°F'});
  assert.deepEqual(waves.hourly_units, {time: 'unixtime', wave_height: 'ft'});
});
