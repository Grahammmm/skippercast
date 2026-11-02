// SC2007-07: an hour in the long-period swell rule (web/score.ts LONG_PERIOD_SWELL, 2.5 ft at 15 s
// or more, which already keeps the hour out of every window) holds a Comfortable boat day at
// Marginal and names the first such hour. More cautious only: a Marginal, Rough or alert day is
// unchanged. Synthetic feeds, values invented; the builder mirrors tests/test_brief_verdict.mjs.
import assert from 'node:assert/strict';
import test from 'node:test';
import {boatVerdict, longPeriodHour, ALERT_CHECK_MISSING} from '../web/brief/verdict.ts';
import {LONG_PERIOD_SWELL, THRESHOLDS} from '../web/score.ts';

const TZ = 'America/Los_Angeles';
const NOW = new Date('2026-10-13T12:00:00Z'); // 5 am PDT; the window is 8 am–noon
const START = Date.parse('2026-10-13T07:00:00Z') / 1000;
const TIMES = Array.from({length: 48}, (_, i) => START + i * 3600);
const BASE = {wind_speed_10m: 6, wind_gusts_10m: 9, wind_direction_10m: 315, ecmwf_wind: 6, ecmwf_gust: 9, wave_height: 2.5, wave_period: 11, wind_wave_height: 0.3, wind_wave_period: 4,
  swell_wave_height: 2.4, swell_wave_period: 11, swell_wave_direction: 300, secondary_swell_wave_height: 0.5, secondary_swell_wave_direction: 200, wam: 2.5};
const UNIT = k => /direction/.test(k) ? '°' : /period/.test(k) ? 's' : /height/.test(k) ? 'ft' : 'kn';

function forecast({over = {}, at = () => ({}), drop = [], runAgeH = 4} = {}) {
  const v = t => ({...BASE, ...over, ...at(t)});
  const run = (id, keys) => ({id, issued: NOW.getTime() / 1000 - runAgeH * 3600, end: TIMES.at(-1), data: {utc_offset_seconds: 0,
    hourly_units: {time: 'unixtime', ...Object.fromEntries(keys.map(([k]) => [k, UNIT(k)]))}, hourly: {time: TIMES, ...Object.fromEntries(keys.map(([k, src]) => [k, TIMES.map(t => v(t)[src ?? k])]))}}});
  const models = {
    gfs_global: run('gfs_global', [['wind_speed_10m'], ['wind_gusts_10m'], ['wind_direction_10m']]),
    ncep_gfswave016: run('ncep_gfswave016', ['wave_height', 'wave_period', 'wind_wave_height', 'wind_wave_period', 'swell_wave_height', 'swell_wave_period', 'swell_wave_direction', 'secondary_swell_wave_height', 'secondary_swell_wave_direction'].map(k => [k])),
    ecmwf_ifs025: run('ecmwf_ifs025', [['wind_speed_10m', 'ecmwf_wind'], ['wind_gusts_10m', 'ecmwf_gust']]),
    ecmwf_wam: run('ecmwf_wam', [['wave_height', 'wam']]),
  };
  for (const id of drop) delete models[id];
  return {region: 'morro-bay', retrieved: NOW.getTime(), point: {id: 'morro-bay', lat: 35.37, lon: -120.9}, models};
}
const brief = (over = {}) => ({profile: 'boat', date: '2026-10-13', sunrise: '2026-10-13T14:10:00Z', sunset: '2026-10-14T01:30:00Z', alerts: [], missing: [], bar: null, shore: null, spear: null, kayak: null, tiles: [], ...over});
const hourAt = h => Date.parse(`2026-10-13T${String(h + 7).padStart(2, '0')}:00:00Z`) / 1000; // local hour h → epoch
const only = (hours, values) => t => hours.map(hourAt).includes(t) ? values : {};
const boat = (opts, b = {}) => boatVerdict(brief(b), forecast(opts), NOW, TZ);

test('the rule is read from score.ts, and the calm baseline is Comfortable with nothing held', () => {
  assert.deepEqual({...LONG_PERIOD_SWELL}, {height: 2.5, period: 15});
  const calm = boat({});
  assert.deepEqual([calm.verdict, calm.held], ['comfortable', null]);
});

test('one hour of 2.6 ft at 16 s holds a Comfortable window at Marginal and names the hour', () => {
  const v = boat({at: only([9], {wave_height: 2.6, wam: 2.6, wave_period: 16})});
  assert.equal(v.verdict, 'marginal');
  assert.equal(v.held, 'Held at Marginal: long-period swell (2.6 ft at 16 s) at 9 am.');
  assert.ok(v.score >= THRESHOLDS.go, 'the comfort score itself is unchanged; only the hold applies');
  // The thresholds are inclusive: exactly 2.5 ft at 15 s qualifies.
  assert.match(boat({at: only([10], {wave_period: 15})}).held, /long-period swell \(2\.5 ft at 15 s\) at 10 am/);
});

test('below either threshold, or outside the window, nothing is held', () => {
  for (const [label, values] of [['2.4 ft at 18 s', {wave_height: 2.4, wam: 2.4, wave_period: 18, swell_wave_period: 18}],
    ['3 ft at 14 s', {wave_height: 3, wam: 3, wave_period: 14, swell_wave_period: 14.9}]]) {
    const v = boat({at: only([8, 9, 10, 11], values)});
    assert.deepEqual([v.verdict, v.held], ['comfortable', null], label);
  }
  // 1 pm is after the 8 am–noon window: not rated, not named.
  const late = boat({at: only([13], {wave_height: 4, wam: 4, wave_period: 18})});
  assert.deepEqual([late.verdict, late.held], ['comfortable', null]);
});

test('the rougher model counts: WAM height with the GFS-Wave period; the swell period alone also qualifies', () => {
  assert.match(boat({at: only([8], {wave_height: 2, wam: 2.7, wave_period: 15})}).held, /long-period swell \(2\.7 ft at 15 s\) at 8 am/);
  assert.match(boat({at: only([11], {wave_height: 2.8, wam: 2.8, wave_period: 9, swell_wave_period: 17})}).held, /long-period swell \(2\.8 ft at 17 s\) at 11 am/);
  // Both periods qualify: the larger is named, rounded to whole seconds.
  assert.match(boat({at: only([8], {wave_period: 15.4, swell_wave_period: 16.6})}).held, /\(2\.5 ft at 17 s\)/);
});

test('a day already Marginal or Rough, or under an alert, is unchanged and gains no held line', () => {
  const lp = only([8, 9, 10, 11], {wave_period: 16});
  const windy = {wind_speed_10m: 16, ecmwf_wind: 16, wind_gusts_10m: 22, ecmwf_gust: 22};
  const marginal = boat({over: windy, at: lp}), marginalBase = boat({over: windy});
  assert.deepEqual([marginal.verdict, marginal.held, marginal.limit], ['marginal', null, marginalBase.limit]);
  const gale = {wind_speed_10m: 30, ecmwf_wind: 30, wind_gusts_10m: 38, ecmwf_gust: 38};
  const rough = boat({over: gale, at: lp});
  assert.deepEqual([rough.verdict, rough.held, rough.limit], ['rough', null, boat({over: gale}).limit]);
  const alert = boat({at: lp}, {alerts: [{event: 'Small Craft Advisory'}]});
  assert.deepEqual([alert.verdict, alert.held, alert.score], ['rough', null, null]);
});

test('the earliest qualifying hour is named, after the other reasons in their order', () => {
  const two = only([10, 9], {wave_height: 2.6, wam: 2.6, wave_period: 16});
  assert.equal(boat({at: two}).held, 'Held at Marginal: long-period swell (2.6 ft at 16 s) at 9 am.');
  const all = boat({at: two, runAgeH: 20}, {missing: [ALERT_CHECK_MISSING], bar: {hazardous: [{at: '2026-10-13T18:00:00Z'}]}});
  assert.equal(all.held, 'Held at Marginal: the forecast run is 20 h old; the marine alert check is unavailable; the bar estimate reads hazardous at 11 am; long-period swell (2.6 ft at 16 s) at 9 am.');
  assert.match(boat({at: two, drop: ['ecmwf_ifs025']}).held, /^Held at Marginal: forecast detail is partial; long-period swell \(2\.6 ft at 16 s\) at 9 am\.$/);
  // Rows given out of order still name the earliest.
  const hour = {sea: 3, other_sea: null, sea_period: 16, swell_period: null};
  assert.equal(longPeriodHour([{ms: hourAt(11) * 1000, hour}, {ms: hourAt(8) * 1000, hour}], TZ), 'long-period swell (3 ft at 16 s) at 8 am');
});

test('null or NaN heights and periods never qualify, and an unrated hour is not named', () => {
  const ms = hourAt(9) * 1000;
  for (const hour of [{sea: null, other_sea: null, sea_period: 16, swell_period: 16}, {sea: NaN, other_sea: NaN, sea_period: 16, swell_period: 16},
    {sea: 3, other_sea: 3, sea_period: null, swell_period: null}, {sea: 3, other_sea: 3, sea_period: NaN, swell_period: NaN},
    {sea: 3, other_sea: 3, sea_period: Infinity, swell_period: undefined}, {sea: '3', other_sea: null, sea_period: '16', swell_period: null}]) {
    assert.equal(longPeriodHour([{ms, hour}], TZ), null, JSON.stringify(hour));
  }
  const gap = boat({at: only([9], {wind_speed_10m: null, ecmwf_wind: null, wave_height: 3, wam: 3, wave_period: 16})});
  assert.equal(gap.held, 'Held at Marginal: 1 of 4 hours have no forecast.');
});
