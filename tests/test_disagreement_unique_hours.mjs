// RF0015-17: repeated entries in the forecast's selected wind clock must not count one independent
// wave-model sample twice toward the two-hour disagreement threshold. Synthetic series, values invented.
import assert from 'node:assert/strict';
import test from 'node:test';
import {disagreements} from '../web/model-disagreement.ts';

const TZ = 'America/Los_Angeles';
const NOW = new Date('2026-11-04T16:00:00Z');
const HOUR = 3600;
const T = Date.parse('2026-11-04T14:00:00Z') / 1000; // 6 am PST
const U = T + HOUR;
const V = T + 2 * HOUR;

const deepFreeze = o => { if (o && typeof o === 'object' && !Object.isFrozen(o)) { Object.freeze(o); Object.values(o).forEach(deepFreeze); } return o; };

/** Wind clock `windTimes` (GFS, selected as the feed clock); each other series has its own clock. Wind agrees (10 vs 10); seas 3 vs 6 ft. */
function forecast({windTimes, noaaWave, ecmwfWave, ecmwfWind = windTimes, windValues = [10, 10]}) {
  const series = (times, cols, v) => ({utc_offset_seconds: 0, hourly_units: {time: 'unixtime', ...Object.fromEntries(cols.map(k => [k, k.startsWith('wave') ? 'ft' : 'kn']))},
    hourly: {time: times, ...Object.fromEntries(cols.map(k => [k, times.map(() => v)]))}});
  const run = (id, times, cols, v) => ({id, issued: NOW.getTime() / 1000 - 4 * HOUR, end: T + 48 * HOUR, data: series(times, cols, v)});
  return deepFreeze({region: 'morro-bay', retrieved: NOW.getTime(), point: {id: 'morro-bay', lat: 35.37, lon: -120.9}, models: {
    gfs_global: run('gfs_global', windTimes, ['wind_speed_10m', 'wind_gusts_10m'], windValues[0]),
    ncep_gfswave016: run('ncep_gfswave016', noaaWave, ['wave_height'], 3),
    ecmwf_ifs025: run('ecmwf_ifs025', ecmwfWind, ['wind_speed_10m', 'wind_gusts_10m'], windValues[1]),
    ecmwf_wam: run('ecmwf_wam', ecmwfWave, ['wave_height'], 6),
  }});
}
const SEAS = hours => ({date: '2026-11-04', quantity: 'seas', noaa: 3, ecmwf: 6, hours});
const run = o => disagreements(forecast(o), NOW, TZ);

test('one distinct instant repeated in the wind clock is not a two-hour disagreement', () => {
  for (const clock of [[T, T], [T, T, T], [T, T, T, T]]) {
    assert.deepEqual(run({windTimes: clock, noaaWave: [T], ecmwfWave: [T]}), [], `clock ${clock.length}`);
  }
});

test('two distinct instants report hours 2 whatever the clock multiplicity or order', () => {
  for (const clock of [[T, U], [T, T, U, U], [U, T, U, T], [T, T, T, U, U, U], [U, U, T]]) {
    assert.deepEqual(run({windTimes: clock, noaaWave: [T, U], ecmwfWave: [T, U]}), [SEAS(2)], JSON.stringify(clock));
  }
});

test('three distinct instants with repeats report 3', () => {
  assert.deepEqual(run({windTimes: [T, T, U, V, V], noaaWave: [T, U, V], ecmwfWave: [T, U, V]}), [SEAS(3)]);
});

test('unique controls and missing peers are unchanged', () => {
  assert.deepEqual(run({windTimes: [T], noaaWave: [T], ecmwfWave: [T]}), []);
  assert.deepEqual(run({windTimes: [], noaaWave: [], ecmwfWave: []}), []);
  assert.deepEqual(run({windTimes: [T, U], noaaWave: [T, U], ecmwfWave: []}), []);
});

test('duplicates inside a wave model own series are still refused, not repaired', () => {
  assert.deepEqual(run({windTimes: [T, T, U], noaaWave: [T, T, U], ecmwfWave: [T, U]}), []);
  assert.deepEqual(run({windTimes: [T, T, U], noaaWave: [T, U], ecmwfWave: [T, U, U]}), []);
});

test('unrepresentable and non-finite listed epochs cannot inflate the count', () => {
  assert.deepEqual(run({windTimes: [T, T, 1e20, 1e20, NaN, Infinity], noaaWave: [T], ecmwfWave: [T]}), []);
  assert.deepEqual(run({windTimes: [1e20, T, T, U, -1e20, NaN], noaaWave: [T, U], ecmwfWave: [T, U]}), [SEAS(2)]);
});

test('with unique wind data the larger relative gap still wins', () => {
  // wind 10 vs 20 (gap 10 kt, rel 1.67) beats seas 3 vs 6 ft (gap 3 ft, rel 1.5)
  assert.deepEqual(run({windTimes: [T, U], noaaWave: [T, U], ecmwfWave: [T, U], windValues: [10, 20]}),
    [{date: '2026-11-04', quantity: 'wind', noaa: 10, ecmwf: 20, hours: 2}]);
});
