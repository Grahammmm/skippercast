// SC1938-12: printed seas maxima round UP (brief to 0.1 ft, advisor to whole feet), so a printed maximum is never below the value the window rule used.
import assert from 'node:assert/strict';
import test from 'node:test';
import {boatVerdict} from '../web/brief/verdict.ts';
import {withinWindowLimits, WINDOW_LIMITS} from '../web/score.ts';
import {windowConditions} from '../server/advisor/answers/conditions.ts';

const NOW = new Date('2026-10-13T12:00:00Z'), TZ = 'America/Los_Angeles', START = Date.parse('2026-10-13T07:00:00Z') / 1000;
const TIMES = Array.from({length: 48}, (_, i) => START + i * 3600);
const U = {wind_speed_10m: 'kn', wind_gusts_10m: 'kn', wind_direction_10m: '°', wave_height: 'ft', wave_period: 's', wind_wave_height: 'ft', wind_wave_period: 's', swell_wave_height: 'ft', swell_wave_period: 's', swell_wave_direction: '°', secondary_swell_wave_height: 'ft', secondary_swell_wave_direction: '°'};
const series = vals => ({utc_offset_seconds: 0, hourly_units: {time: 'unixtime', ...Object.fromEntries(Object.keys(vals).map(k => [k, U[k]]))}, hourly: {time: TIMES, ...Object.fromEntries(Object.entries(vals).map(([k, v]) => [k, TIMES.map(() => v)]))}});
const run = (id, vals) => ({id, issued: NOW.getTime() / 1000 - 4 * 3600, end: TIMES.at(-1), data: series(vals)});
/** A brief forecast whose every hour reads `sea` ft in both wave models. */
const forecast = sea => ({region: 'morro-bay', retrieved: NOW.getTime(), point: {id: 'morro-bay', lat: 35.37, lon: -120.9}, models: {
  gfs_global: run('gfs_global', {wind_speed_10m: 6, wind_gusts_10m: 9, wind_direction_10m: 315}),
  ncep_gfswave016: run('ncep_gfswave016', {wave_height: sea, wave_period: 11, wind_wave_height: 0.3, wind_wave_period: 4, swell_wave_height: 2.4, swell_wave_period: 11, swell_wave_direction: 300, secondary_swell_wave_height: 0.5, secondary_swell_wave_direction: 200}),
  ecmwf_ifs025: run('ecmwf_ifs025', {wind_speed_10m: 6, wind_gusts_10m: 9}), ecmwf_wam: run('ecmwf_wam', {wave_height: sea})}});
const brief = {profile: 'boat', date: '2026-10-13', sunrise: '2026-10-13T14:10:00Z', sunset: '2026-10-14T01:30:00Z', alerts: [], missing: [], bar: null, shore: null, spear: null, kayak: null, tiles: []};
const seasText = sea => { const v = boatVerdict(brief, forecast(sea), NOW, TZ); return {v, text: JSON.stringify(v), said: /seas to ([\d.]+) ft/.exec(v.limit)?.[1]}; };
/** The advisor's seas_ft for two hours reading `lo` and `hi` ft in the one wave model; wind and swell ranges ride along. */
function advisor(lo, hi) {
  const t = [1790600400, 1790604000], one = (k, u, v) => ({[k]: {u, v}});
  const model = parts => ({data: [{hourly_units: {time: 'unixtime', ...Object.fromEntries(Object.entries(parts).map(([k, p]) => [k, p.u]))}, hourly: {time: t, ...Object.fromEntries(Object.entries(parts).map(([k, p]) => [k, p.v]))}}]});
  const feed = {region_id: 'synthetic-coast', forecast: {models: {
    gfs_global: model(one('wind_speed_10m', 'kn', [4.6, 5.4])), ncep_gfswave016: model({...one('wave_height', 'ft', [lo, hi]), ...one('swell_wave_height', 'ft', [2.4, 3.6])}), ecmwf_ifs025: {data: []}, ecmwf_wam: {data: []}}}};
  return windowConditions(feed, {id: 'synthetic-coast', timezone: 'America/Los_Angeles', forecast_points: [{id: 'central'}], marine_zones: {coastal: 'PZZ645'}}, 'central', '2026-09-28');
}

test('1 4.0026 ft: the brief says 4.1 ft and the advisor upper is 5', () => {
  assert.equal(seasText(4.0026).said, '4.1');
  assert.equal(advisor(4.0026, 4.0026).seas_ft[1], 5);
});
test('2 exactly 4.0 ft: the brief says 4 ft and the advisor upper stays 4 (no spurious bump)', () => {
  assert.equal(seasText(4).said, '4');
  assert.deepEqual(advisor(4, 4).seas_ft, [4, 4]);
});
test('3 float noise: 0.1 * 3 reads 0.3 and 3.9999999999 reads 4', () => {
  assert.equal(seasText(0.1 * 3).said, '0.3');
  assert.equal(seasText(3.9999999999).said, '4');
  assert.equal(advisor(3.9999999999, 3.9999999999).seas_ft[1], 4);
});
test('4 4.4 is 5 in the advisor and 4.4 in the brief; 4.5 and 4.51 are 5', () => {
  assert.equal(advisor(4.4, 4.4).seas_ft[1], 5);
  assert.equal(seasText(4.4).said, '4.4');
  for (const sea of [4.5, 4.51]) assert.equal(advisor(sea, sea).seas_ft[1], 5, String(sea));
});
test('5 a window the 4 ft rule rejected never reads "seas to 4 ft" anywhere in the verdict', () => {
  const hour = {wind: 6, gust: 9, wave: 4.0026, period: 11};
  assert.equal(withinWindowLimits(hour, WINDOW_LIMITS.boat), false, 'the 4 ft window rule rejects 4.0026 ft');
  const {v, text} = seasText(4.0026);
  assert.match(v.limit, /seas to 4\.1 ft/);
  assert.doesNotMatch(text, /seas to 4 ft/);
});
test('6 the lower end rounds to nearest and never exceeds the upper', () => {
  assert.deepEqual(advisor(3.4, 3.6).seas_ft, [3, 4]);
  assert.deepEqual(advisor(3.6, 3.6).seas_ft, [4, 4]);
});
test('7 no seas gives null; wind and swell ranges still round to nearest', () => {
  assert.equal(advisor(null, null).seas_ft, null);
  assert.equal(advisor(Number.NaN, Number.NaN).seas_ft, null);
  const day = advisor(2.4, 3.6);
  assert.deepEqual([day.wind_kt, day.swell_ft, day.seas_ft], [[5, 5], [2, 4], [2, 4]]);
});
