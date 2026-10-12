// #616: the day verdict (web/brief/verdict.ts). The boat verdict is the one
// conditions model's worst hour from sunrise to noon over the regional
// dual-model feed; caps hold a Comfortable window at Marginal and say why; a
// marine alert makes the day Rough; no forecast reads Unknown. Synthetic feeds,
// values invented.
import assert from 'node:assert/strict';
import test from 'node:test';
import {boatVerdict, briefVerdict, profileVerdict, windowHours, feedReader, ALERT_CHECK_MISSING, VERDICT_WORD} from '../web/brief/verdict.ts';
import {rateComfort, verdictFor, THRESHOLDS} from '../web/score.ts';

const TZ = 'America/Los_Angeles';
const DATE = '2026-10-13';
const NOW = new Date('2026-10-13T12:00:00Z'); // 5 am PDT
const SUNRISE = '2026-10-13T14:10:00Z', SUNSET = '2026-10-14T01:30:00Z'; // 7:10 am, 6:30 pm PDT
const START = Date.parse('2026-10-13T07:00:00Z') / 1000;
const TIMES = Array.from({length: 48}, (_, i) => START + i * 3600);

const BASE = {
  wind_speed_10m: 6, wind_gusts_10m: 9, wind_direction_10m: 315,
  ecmwf_wind: 6, ecmwf_gust: 9, wave_height: 2.5, wave_period: 11, wind_wave_height: 0.3, wind_wave_period: 4,
  swell_wave_height: 2.4, swell_wave_period: 11, swell_wave_direction: 300, secondary_swell_wave_height: 0.5, secondary_swell_wave_direction: 200, wam: 2.5,
};
const UNITS = {wind_speed_10m: 'kn', wind_gusts_10m: 'kn', wind_direction_10m: '°', wave_height: 'ft', wave_period: 's', wind_wave_height: 'ft', wind_wave_period: 's',
  swell_wave_height: 'ft', swell_wave_period: 's', swell_wave_direction: '°', secondary_swell_wave_height: 'ft', secondary_swell_wave_direction: '°'};

/** A parsed ConditionsForecast at one point; `at(epoch)` overrides values per hour; `drop` leaves models out; runs issued `runAgeH` before NOW. */
function forecast({over = {}, at = () => ({}), drop = [], runAgeH = 4} = {}) {
  const v = epoch => ({...BASE, ...over, ...at(epoch)});
  const series = keys => ({utc_offset_seconds: 0, hourly_units: {time: 'unixtime', ...Object.fromEntries(keys.map(([k]) => [k, UNITS[k]]))},
    hourly: {time: TIMES, ...Object.fromEntries(keys.map(([k, src]) => [k, TIMES.map(t => v(t)[src ?? k])]))}});
  const run = (id, keys) => ({id, issued: NOW.getTime() / 1000 - runAgeH * 3600, end: TIMES.at(-1), data: series(keys)});
  const models = {
    gfs_global: run('gfs_global', [['wind_speed_10m'], ['wind_gusts_10m'], ['wind_direction_10m']]),
    ncep_gfswave016: run('ncep_gfswave016', ['wave_height', 'wave_period', 'wind_wave_height', 'wind_wave_period', 'swell_wave_height', 'swell_wave_period', 'swell_wave_direction', 'secondary_swell_wave_height', 'secondary_swell_wave_direction'].map(k => [k])),
    ecmwf_ifs025: run('ecmwf_ifs025', [['wind_speed_10m', 'ecmwf_wind'], ['wind_gusts_10m', 'ecmwf_gust']]),
    ecmwf_wam: run('ecmwf_wam', [['wave_height', 'wam']]),
  };
  for (const id of drop) delete models[id];
  return {region: 'morro-bay', retrieved: NOW.getTime(), point: {id: 'morro-bay', lat: 35.37, lon: -120.9}, models};
}

const brief = (over = {}) => ({profile: 'boat', date: DATE, sunrise: SUNRISE, sunset: SUNSET, alerts: [], missing: [], bar: null, shore: null, spear: null, kayak: null, tiles: [], ...over});
const hourAt = h => Date.parse(`2026-10-13T${String(h + 7).padStart(2, '0')}:00:00Z`) / 1000; // local hour h → epoch

test('the window runs from the sunrise hour to noon, from the current hour on; past noon it is the rest of the daylight', () => {
  const ms = TIMES.map(t => t * 1000);
  const morning = windowHours(ms, DATE, TZ, SUNRISE, SUNSET, NOW);
  assert.equal(morning.label, '7 am–noon');
  assert.equal(morning.hours.length, 5);
  const late = windowHours(ms, DATE, TZ, SUNRISE, SUNSET, new Date('2026-10-13T17:30:00Z')); // 10:30 am
  assert.equal(late.label, '10 am–noon');
  const afternoon = windowHours(ms, DATE, TZ, SUNRISE, SUNSET, new Date('2026-10-13T20:30:00Z')); // 1:30 pm
  assert.equal(afternoon.label, '1 pm–6 pm');
});

test('each verdict maps to the disclosed score bands over the worst hour', () => {
  for (const wind of [5, 10, 14, 18, 24, 30]) {
    const f = forecast({over: {wind_speed_10m: wind, ecmwf_wind: wind, wind_gusts_10m: wind + 5, ecmwf_gust: wind + 5}});
    const v = boatVerdict(brief(), f, NOW, TZ);
    const {read, times} = feedReader(f, NOW);
    const worst = Math.min(...windowHours(times, DATE, TZ, SUNRISE, SUNSET, NOW).hours.map(ms => rateComfort(read(ms)).score));
    const expected = {go: 'comfortable', marginal: 'marginal', 'no-go': 'rough'}[verdictFor({conditions: worst})];
    assert.equal(v.verdict, expected, `wind ${wind} kt scores ${worst}`);
    assert.equal(v.score, worst);
    assert.equal(v.held, null);
  }
  const calm = boatVerdict(brief(), forecast(), NOW, TZ);
  assert.equal(calm.verdict, 'comfortable');
  assert.ok(calm.score >= THRESHOLDS.go);
  assert.equal(calm.limit, 'Wind to 6 kt and seas to 2.5 ft through noon.');
});

test('the limit sentence names the worst input at its hour', () => {
  const windy = boatVerdict(brief(), forecast({at: t => t === hourAt(10) ? {wind_speed_10m: 20, ecmwf_wind: 19, wind_gusts_10m: 26, ecmwf_gust: 25} : {}}), NOW, TZ);
  assert.equal(windy.verdict, 'marginal');
  assert.match(windy.limit, /^20 kt wind gusting 26 at 10 am\.$/);
  const seas = boatVerdict(brief(), forecast({over: {wave_height: 7, wam: 7.4, wave_period: 8, swell_wave_height: 6.5}}), NOW, TZ);
  assert.match(seas.limit, /^7\.4 ft seas at 8 s at 7 am/);
  const chop = boatVerdict(brief(), forecast({over: {wind_wave_height: 2.2, wind_wave_period: 3, wind_speed_10m: 12, ecmwf_wind: 12, wind_gusts_10m: 15, ecmwf_gust: 15}}), NOW, TZ);
  assert.match(chop.limit, /short, steep wind chop/);
  // A crossing swell alone costs 0.7: the day stays Comfortable and the sentence gives the range.
  const cross = boatVerdict(brief(), forecast({over: {secondary_swell_wave_height: 3, secondary_swell_wave_direction: 200, wave_height: 3.5, wam: 3.5}}), NOW, TZ);
  assert.deepEqual([cross.verdict, cross.limit], ['comfortable', 'Wind to 6 kt and seas to 3.5 ft through noon.']);
});

test('the limited cap: partial detail, missing hours, an old run or no alert check hold Comfortable at Marginal and say why', () => {
  const noEcmwf = boatVerdict(brief(), forecast({drop: ['ecmwf_ifs025', 'ecmwf_wam']}), NOW, TZ);
  assert.equal(noEcmwf.verdict, 'marginal');
  assert.ok(noEcmwf.score <= THRESHOLDS.capLimited);
  assert.match(noEcmwf.held, /^Held at Marginal: forecast detail is partial\.$/);
  const gap = boatVerdict(brief(), forecast({at: t => t === hourAt(9) ? {wind_speed_10m: null, ecmwf_wind: null} : {}}), NOW, TZ);
  assert.equal(gap.verdict, 'marginal');
  assert.match(gap.held, /1 of 5 hours have no forecast/);
  const old = boatVerdict(brief(), forecast({runAgeH: 20}), NOW, TZ);
  assert.equal(old.verdict, 'marginal');
  assert.match(old.held, /forecast run is 20 h old/);
  const noCheck = boatVerdict(brief({missing: [ALERT_CHECK_MISSING]}), forecast(), NOW, TZ);
  assert.equal(noCheck.verdict, 'marginal');
  assert.match(noCheck.held, /marine alert check is unavailable/);
  const bar = boatVerdict(brief({bar: {hazardous: [{at: '2026-10-13T15:00:00Z'}]}}), forecast(), NOW, TZ);
  assert.match(bar.held, /bar estimate reads hazardous at 8 am/);
  // A cap only holds a Comfortable window; a Rough one stays Rough without a held line.
  const rough = boatVerdict(brief({missing: [ALERT_CHECK_MISSING]}), forecast({over: {wind_speed_10m: 30, ecmwf_wind: 30, wind_gusts_10m: 38, ecmwf_gust: 38}}), NOW, TZ);
  assert.deepEqual([rough.verdict, rough.held], ['rough', null]);
});

test('runs over 36 h old are not used, and with none left the verdict is Unknown', () => {
  assert.equal(boatVerdict(brief(), forecast({runAgeH: 40}), NOW, TZ).verdict, 'unknown');
});

test('a marine alert makes the day Rough and leads the sentence', () => {
  const v = boatVerdict(brief({alerts: [{event: 'Small Craft Advisory'}]}), forecast(), NOW, TZ);
  assert.equal(v.verdict, 'rough');
  assert.match(v.limit, /^Small Craft Advisory in effect\. /);
  assert.ok(v.score <= THRESHOLDS.capHazard);
});

test('Unknown without a forecast, or with no wind and seas in the window', () => {
  const none = boatVerdict(brief(), null, NOW, TZ);
  assert.deepEqual([none.verdict, none.limit], ['unknown', 'No forecast for this morning yet.']);
  const blank = boatVerdict(brief(), forecast({over: {wind_speed_10m: null, ecmwf_wind: null}}), NOW, TZ);
  assert.equal(blank.verdict, 'unknown');
  assert.equal(briefVerdict(null, forecast(), NOW, TZ), null);
  assert.equal(VERDICT_WORD.unknown, 'Unknown');
});

test('buoy readings never enter the verdict: a stale buoy tile cannot raise it', () => {
  const f = forecast({over: {wind_speed_10m: 16, ecmwf_wind: 16, wind_gusts_10m: 22, ecmwf_gust: 22}});
  const fresh = boatVerdict(brief({tiles: [{id: 'water', state: 'fresh'}]}), f, NOW, TZ);
  const stale = boatVerdict(brief({tiles: [{id: 'water', state: 'stale'}], gaps: [{id: 'buoy', status: 'stale'}]}), f, NOW, TZ);
  assert.deepEqual(stale, fresh);
});

test('Shore, Spear and Kayak take their own hourly grade: the roughest hour in the window, Calmer read as Comfortable', () => {
  const at = h => `2026-10-13T${String(h + 7).padStart(2, '0')}:00:00Z`;
  const hours = [7, 8, 9, 10, 11].map(h => ({at: at(h), verdict: h === 10 ? 'Marginal' : 'Calmer', reasons: h === 10 ? ['moderate wind (12 kt) onshore', 'rough seas (3 ft at 8 s)'] : ['light wind']}));
  const kayak = profileVerdict(brief({profile: 'kayak', kayak: {hours}}), NOW, TZ);
  assert.deepEqual([kayak.verdict, kayak.limit, kayak.basis], ['marginal', 'Moderate wind (12 kt) onshore, rough seas (3 ft at 8 s) at 10 am.', 'kayak']);
  const calm = profileVerdict(brief({profile: 'shore', shore: {hours: hours.map(h => ({...h, verdict: 'Calmer', reasons: ['small surf']}))}}), NOW, TZ);
  assert.deepEqual([calm.verdict, calm.limit], ['comfortable', 'Small surf through noon.']);
  const thin = profileVerdict(brief({profile: 'spear', spear: {hours: hours.map((h, i) => ({...h, verdict: i ? 'Calmer' : 'Unknown'}))}}), NOW, TZ);
  assert.equal(thin.verdict, 'marginal');
  assert.match(thin.held, /1 of 5 hours are unknown/);
  assert.equal(profileVerdict(brief({profile: 'shore', shore: null}), NOW, TZ).verdict, 'unknown');
});
