// RF1920-12: briefForecast skips finite but Date-unrepresentable hourly epochs, one hour at a time.
// Synthetic one-point NOAA / ECMWF models (values invented, /api/forecast shape); no network.
import test from 'node:test';
import assert from 'node:assert/strict';

const {briefForecast} = await import('../web/conditions.ts');

const UNITS = {wind_speed_10m: 'kn', wind_gusts_10m: 'kn', wind_direction_10m: '°', temperature_2m: '°F', cloud_cover: '%', wave_height: 'ft', wave_period: 's', swell_wave_height: 'ft', swell_wave_period: 's'};
/** One model's series: every variable listed at each of `time` (values keyed to the epoch's index). */
function run(time, values, issued = 1_000_000) {
  const hourly = {time, ...Object.fromEntries(Object.entries(values).map(([k, v]) => [k, time.map((_, i) => (typeof v === 'function' ? v(i) : v))]))};
  const hourly_units = {time: 'unixtime', ...Object.fromEntries(Object.keys(values).map(k => [k, UNITS[k]]))};
  return {issued, end: null, data: {utc_offset_seconds: 0, hourly_units, hourly}};
}
const WIND = {wind_speed_10m: i => 8 + i, wind_gusts_10m: i => 12 + i, wind_direction_10m: 270, temperature_2m: 61, cloud_cover: 40};
const WAVE = {wave_height: 4, wave_period: 11, swell_wave_height: 3, swell_wave_period: 13};
function feed(time, {wave = WAVE, wind = WIND, waveIssued = 1_000_000} = {}) {
  return {region: 'morro-bay', retrieved: 1_800_000_000_000, point: {id: 'central', lat: 35.3, lon: -120.9}, models: {
    gfs_global: run(time, wind), ncep_gfswave016: run(time, wave, waveIssued), ecmwf_ifs025: run(time, wind), ecmwf_wam: run(time, wave)}};
}
const iso = s => new Date(s * 1000).toISOString();
const ORDINARY = [1_800_000_000, 1_800_003_600];
const BAD = [8_640_000_000_001, -8_640_000_000_001, 1e308];
const rowsOf = (time, family = 'gfs', opts) => briefForecast(feed(time, opts), family).hours;

test('brief_forecast_skips_finite_out_of_date_range_epochs', () => {
  const control = rowsOf(ORDINARY);
  const mixed = rowsOf([BAD[0], ORDINARY[0], BAD[1], ORDINARY[1], BAD[2]]);
  assert.equal(control.length, 2);
  // Values are sampled by index, so compare the epochs' ISO instants and the values that do not depend on the position.
  assert.deepEqual(mixed.map(h => h.at), control.map(h => h.at));
  assert.deepEqual(mixed.map(h => h.windDirectionDeg), control.map(h => h.windDirectionDeg));
  assert.deepEqual(mixed.map(h => h.wavePeriodS), [11, 11]);
  // The unrepresentable hours sit in the series, so the valid ones read their own indexes, not shifted ones.
  assert.deepEqual(mixed.map(h => h.windKnots), [9, 11]);
});

test('brief_forecast_rejects_non_numeric_hour_values_without_coercion', () => {
  const time = [NaN, Infinity, -Infinity, null, undefined, '1800000000', true, false, 0, -86_400, 8_640_000_000_000, -8_640_000_000_000];
  assert.deepEqual(rowsOf(time).map(h => h.at), [iso(0), iso(-86_400), '+275760-09-13T00:00:00.000Z', '-271821-04-20T00:00:00.000Z']);
  assert.deepEqual(rowsOf([8_640_000_000_001, -8_640_000_000_001]), []);
});

test('brief_forecast_all_invalid_hours_is_empty_and_inputs_unchanged', () => {
  const f = feed(Object.freeze([...BAD, NaN]));
  const before = JSON.stringify(f);
  Object.freeze(f.models.gfs_global.data.hourly.time);
  const out = briefForecast(f, 'gfs');
  assert.deepEqual(out.hours, []);
  assert.equal(out.label, 'NOAA GFS model · central');
  assert.equal(out.issuedAt, iso(1_000_000));
  assert.equal(out.fetchedAt, new Date(1_800_000_000_000).toISOString());
  assert.equal(JSON.stringify(f), before);
});

test('brief_forecast_preserves_dst_and_midnight_instants', () => {
  // 2026-03-08 spring-forward hours, 2026-11-01 fall-back hours (both local 1 am), a Pacific midnight pair, and a repeated instant.
  const time = ['2026-03-08T09:00Z', '2026-03-08T10:00Z', '2026-11-01T08:00Z', '2026-11-01T09:00Z', '2026-03-09T07:00Z', '2026-11-01T08:00Z', '2026-11-02T08:00Z', '2026-11-02T09:00Z'].map(s => Date.parse(s) / 1000);
  for (const family of ['gfs', 'ecmwf']) {
    const hours = rowsOf([...time, ...BAD], family);
    assert.deepEqual(hours.map(h => h.at), time.map(iso), family);
    assert.ok(hours.some(h => h.at === '2026-11-01T08:00:00.000Z') && hours.some(h => h.at === '2026-11-01T09:00:00.000Z'), 'both repeated 1 am hours');
    assert.ok(hours.some(h => h.at === '2026-03-08T09:00:00.000Z') && hours.some(h => h.at === '2026-03-08T10:00:00.000Z'));
    // Duplicate epochs have no unique sample (existing rule): the null stays, the row stays.
    assert.deepEqual(hours.map(h => h.windKnots), [8, 9, null, 11, 12, null, 14, 15]);
  }
});

test('brief_forecast_existing_period_gust_and_clock_rules_unchanged', () => {
  const t = ORDINARY;
  const gustBelow = rowsOf(t, 'gfs', {wind: {...WIND, wind_gusts_10m: 1}})[0];
  assert.equal(gustBelow.gustKnots, null);
  for (const period of [0, -3]) assert.equal(rowsOf(t, 'gfs', {wave: {...WAVE, wave_period: period}})[0].waveFt, null);
  const noPeriod = rowsOf(t, 'gfs', {wave: {wave_height: 4}})[0];
  assert.equal(noPeriod.waveFt, null); assert.equal(noPeriod.wavePeriodS, null);
  const older = briefForecast(feed(t, {waveIssued: 900_000}), 'gfs');
  assert.equal(older.issuedAt, iso(900_000));
  assert.equal(briefForecast({...feed(t), models: {...feed(t).models, ncep_gfswave016: {...feed(t).models.ncep_gfswave016, issued: null}}}, 'gfs'), null);
});
