import test from 'node:test';
import assert from 'node:assert/strict';
import {forecastFixture} from '../e2e/forecast-fixture.ts';

test('offline browser fixture matches requested points, units and finite forecast horizon', () => {
  const now = Date.UTC(2026, 9, 1, 21);
  const rows = forecastFixture(new URL('http://local/api/om/v1/forecast?latitude=35.45,35.36&longitude=-121.02,-120.94&hourly=wind_speed_10m,wind_gusts_10m,visibility,unknown_field'), now);
  assert.equal(rows.length, 2);
  assert.deepEqual(rows.map(r => [r.latitude, r.longitude]), [[35.45, -121.02], [35.36, -120.94]]);
  const meta = forecastFixture(new URL('http://local/api/om/data/gfs_global/static/meta.json'), now);
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

test('offline marine fixture uses feet, seconds and direction degrees', () => {
  const row = forecastFixture(new URL('http://local/api/om/v1/marine?latitude=35.36&longitude=-120.94&hourly=wave_height,wave_period,wave_direction'));
  assert.deepEqual([row.hourly_units.wave_height, row.hourly_units.wave_period, row.hourly_units.wave_direction], ['ft', 's', '°']);
  assert.deepEqual([row.hourly.wave_height[0], row.hourly.wave_period[0], row.hourly.wave_direction[0]], [2.5, 12, 290]);
});
