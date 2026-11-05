// RF1330-2: a finite but Date-unrepresentable listed forecast epoch must not throw from the
// model-disagreement display; valid hours still count. Synthetic series, values invented.
import assert from 'node:assert/strict';
import test from 'node:test';
import {disagreements} from '../web/model-disagreement.ts';

const TZ = 'America/Los_Angeles';
const NOW = new Date('2026-11-04T16:00:00Z'); // Wednesday 8 am PST
const HOUR = 3600;
const START = Date.parse('2026-11-04T14:00:00Z') / 1000; // 6 am PST
const GOOD = [START, START + HOUR]; // 6 am and 7 am PST on 2026-11-04
const ITEM = {date: '2026-11-04', quantity: 'wind', noaa: 10, ecmwf: 20, hours: 2};

const deepFreeze = o => { if (o && typeof o === 'object' && !Object.isFrozen(o)) { Object.freeze(o); Object.values(o).forEach(deepFreeze); } return o; };

/** A ConditionsForecast whose NOAA wind reads 10 kt and ECMWF 20 kt at every listed epoch; `times` is the listed clock. */
function forecast(times) {
  const series = (cols, v) => ({utc_offset_seconds: 0, hourly_units: {time: 'unixtime', ...Object.fromEntries(cols.map(k => [k, k.startsWith('wave') ? 'ft' : 'kn']))},
    hourly: {time: times, ...Object.fromEntries(cols.map(k => [k, times.map(() => v)]))}});
  const run = (id, cols, v) => ({id, issued: NOW.getTime() / 1000 - 4 * HOUR, end: START + 48 * HOUR, data: series(cols, v)});
  return deepFreeze({region: 'morro-bay', retrieved: NOW.getTime(), point: {id: 'morro-bay', lat: 35.37, lon: -120.9}, models: {
    gfs_global: run('gfs_global', ['wind_speed_10m', 'wind_gusts_10m'], 10),
    ncep_gfswave016: run('ncep_gfswave016', ['wave_height'], 3),
    ecmwf_ifs025: run('ecmwf_ifs025', ['wind_speed_10m', 'wind_gusts_10m'], 20),
    ecmwf_wam: run('ecmwf_wam', ['wave_height'], 3),
  }});
}
const run = times => disagreements(forecast(times), NOW, TZ);
// Finite seconds whose millisecond value is outside +/-8.64e15, or overflows to Infinity.
const BAD = [1e20, -1e20, 8.64e12 + 1, -8.64e12 - 1, 1e306, -1e306];

test('control: two disagreeing morning hours give the item', () => {
  assert.deepEqual(run(GOOD), [ITEM]);
});

test('disagreement_rejects_positive_and_negative_unrepresentable_epochs', () => {
  for (const bad of BAD) assert.deepEqual(run([bad]), [], `sole ${bad}`);
  assert.deepEqual(run([1e20, -1e20, NaN, Infinity, '1.8e9']), []);
});

test('disagreement_mixed_hours_preserve_valid_item', () => {
  for (const bad of BAD) {
    assert.deepEqual(run([bad, ...GOOD]), [ITEM], `front ${bad}`);
    assert.deepEqual(run([GOOD[0], bad, GOOD[1]]), [ITEM], `middle ${bad}`);
    assert.deepEqual(run([...GOOD, bad]), [ITEM], `end ${bad}`);
  }
});

test('disagreement_invalid_hours_cannot_meet_two_hour_threshold', () => {
  assert.deepEqual(run([GOOD[0], 1e20, -1e20, 1e306]), []);
  assert.deepEqual(run([1e20, -1e20]), []);
});

test('disagreement_date_range_edges_do_not_throw', () => {
  const MAX = 8.64e12; // seconds: Date's largest representable epoch is 8.64e15 ms
  assert.doesNotThrow(() => run([MAX, -MAX]));
  assert.deepEqual(run([MAX, -MAX]), [], 'valid but far-away samples miss the requested local dates');
  assert.deepEqual(run([MAX, -MAX, ...GOOD]), [ITEM]);
  assert.deepEqual(run([MAX + 1, -MAX - 1, ...GOOD]), [ITEM]);
});
