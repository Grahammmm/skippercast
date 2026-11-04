// SC1952-05: the advisor's get_conditions holds a Comfortable window at Bumpy when a rated hour is in the
// long-period swell rule (web/score.ts LONG_PERIOD_SWELL, 2.5 ft at 15 s or more), and names the earliest
// such hour in comfort_held, as the brief has since SC2007-07 (web/brief/verdict.ts longPeriodHour).
// The score is untouched (a day-word policy only). Synthetic feeds, values invented, offline.
import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {longPeriodHour} from '../web/brief/verdict.ts';
import {LONG_PERIOD_SWELL, THRESHOLDS} from '../web/score.ts';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json'), 'southern-california': read('../regions/southern-california/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
const {windowConditions, withForecastClock, readHour, rateHour, requestBoat, WINDOW} = await import('../server/advisor/answers/conditions.ts');
const {forecastClock} = await import('../server/advisor/answers/forecast-clock.ts');
const {TOOL_BY_NAME} = await import('../server/advisor/tools/index.ts');
const {advisorSettings} = await import('../server/advisor/settings.ts');

const REGION = REGIONS['morro-bay'];
const POINT = 'central';
const POINT_INDEX = REGION.forecast_points.findIndex(p => p.id === POINT);
const DATE = '2026-09-28';                                    // PDT: UTC-7
const NOW = Date.parse('2026-09-28T15:00:00Z');
const BASE = {wind_speed_10m: 6, wind_gusts_10m: 9, wind_direction_10m: 315, ecmwf_wind: 6, ecmwf_gust: 9, wave_height: 2, wave_period: 10, wind_wave_height: 0.3, wind_wave_period: 4,
  swell_wave_height: 2, swell_wave_period: 10, swell_wave_direction: 300, secondary_swell_wave_height: 0.5, secondary_swell_wave_direction: 200, wam: 2};
const UNIT = k => /direction/.test(k) ? '°' : /period/.test(k) ? 's' : /height/.test(k) ? 'ft' : 'kn';
const HOURS = Array.from({length: 24 * 7}, (_, i) => Date.parse('2026-09-26T00:00:00Z') / 1000 + i * 3600);

/** Epoch seconds of local hour `h` on `date` at a fixed UTC offset (hours behind UTC). */
const at = (date, h, behind = 7) => Date.UTC(+date.slice(0, 4), +date.slice(5, 7) - 1, +date.slice(8, 10), h + behind) / 1000;

/**
 * An intelligence feed whose every hour reads BASE plus `over`; `by(t)` overrides single hours (epoch seconds);
 * `units` overrides a unit label; `ageH` is each model run's age at NOW; `reverse` lists the hours newest first.
 */
function feed({over = {}, by = () => ({}), units = {}, ageH = 4, reverse = false, times = HOURS} = {}) {
  const order = reverse ? [...times].reverse() : times;
  const v = t => ({...BASE, ...over, ...by(t)});
  const series = keys => ({hourly_units: {time: 'unixtime', ...Object.fromEntries(keys.map(([k]) => [k, units[k] ?? UNIT(k)]))},
    hourly: {time: order, ...Object.fromEntries(keys.map(([k, src]) => [k, order.map(t => v(t)[src ?? k])]))}});
  const model = keys => ({meta: {last_run_initialisation_time: NOW / 1000 - ageH * 3600}, data: Array.from({length: POINT_INDEX + 1}, (_, i) => i === POINT_INDEX ? series(keys) : null)});
  const wave = ['wave_height', 'wave_period', 'wind_wave_height', 'wind_wave_period', 'swell_wave_height', 'swell_wave_period', 'swell_wave_direction', 'secondary_swell_wave_height', 'secondary_swell_wave_direction'].map(k => [k]);
  return {region_id: 'morro-bay', completed_at: new Date(NOW - 3600000).toISOString(), forecast: {models: {
    gfs_global: model([['wind_speed_10m'], ['wind_gusts_10m'], ['wind_direction_10m']]),
    ncep_gfswave016: model(wave),
    ecmwf_ifs025: model([['wind_speed_10m', 'ecmwf_wind'], ['wind_gusts_10m', 'ecmwf_gust']]),
    ecmwf_wam: model([['wave_height', 'wam']]),
  }}};
}
/** Overrides applied only at the given local hours of DATE. */
const only = (hours, values, date = DATE, behind = 7) => t => hours.some(h => at(date, h, behind) === t) ? values : {};
const day = (opts, {date = DATE, window = WINDOW, boat = null, region = REGION} = {}) => windowConditions(feed(opts), region, POINT, date, window, boat);
const LP = {wave_height: 2.6, wam: 2.6, wave_period: 16};   // 2.6 ft at 16 s, calm wind

test('the rule is the shared one, and the calm baseline stays Comfortable with nothing held', () => {
  assert.deepEqual({...LONG_PERIOD_SWELL}, {height: 2.5, period: 15});
  const calm = day({});
  assert.equal(calm.comfort, 'comfortable');
  assert.equal('comfort_held' in calm, false);
});

test('2.5 ft at 15 s exactly, and 2.6 ft at 16 s, hold Comfortable at Bumpy and name the local hour; the score is unchanged', () => {
  const exact = day({by: only([10], {wave_height: 2.5, wam: 2.5, wave_period: 15})});
  assert.deepEqual([exact.comfort, exact.comfort_held], ['bumpy', 'long-period swell (2.5 ft at 15 s) at 10 am']);
  const single = day({by: only([9], LP)});
  assert.deepEqual([single.comfort, single.comfort_held, single.available, single.comfort_for], ['bumpy', 'long-period swell (2.6 ft at 16 s) at 9 am', true, 'a mid-size center console']);
  // The hold is a word, not a score penalty: the hour itself still rates comfortable.
  const hour = readHour(feed({by: only([9], LP)}), POINT_INDEX, at(DATE, 9));
  assert.ok(rateHour(hour) >= THRESHOLDS.go, `score ${rateHour(hour)}`);
  // Readings are the ordinary ones.
  const plain = day({});
  assert.deepEqual([single.wind_kt, single.gusts_kt, single.sea_period_s, single.models_agree], [plain.wind_kt, plain.gusts_kt, plain.sea_period_s, plain.models_agree]);
});

test('a boating advisory overrides the long-period Bumpy hold and keeps Rough when the run is held', () => {
  const f = feed({by: only([9], LP)}), advisory = {event: 'Small Craft Advisory'};
  const d = windowConditions(f, REGION, POINT, DATE, WINDOW, null, [advisory]);
  assert.deepEqual([d.comfort, d.advisory, 'comfort_held' in d], ['rough', advisory.event, false]);
  assert.deepEqual(withForecastClock(d, {state: 'held', ageHours: 20}), d);
  assert.equal(windowConditions(f, REGION, POINT, DATE).comfort, 'bumpy');
});

test('just below either threshold nothing is held, including an unrounded 14.9 s', () => {
  for (const [label, values] of [
    ['2.4 ft at 18 s', {wave_height: 2.4, wam: 2.4, wave_period: 18, swell_wave_period: 18}],
    ['3 ft at 14 s', {wave_height: 3, wam: 3, wave_period: 14, swell_wave_period: 14}],
    ['3 ft at 14.9 s', {wave_height: 3, wam: 3, wave_period: 14.9, swell_wave_period: 14.9}],
    ['2.4999 ft at 16 s', {wave_height: 2.4999, wam: 2.4999, wave_period: 16}],
  ]) {
    const d = day({by: only([8, 9, 10, 11], values)});
    assert.deepEqual([d.comfort, 'comfort_held' in d], ['comfortable', false], label);
  }
});

test('the rougher model height counts; the swell period alone qualifies; the larger period is named; measurements must be valid', () => {
  assert.equal(day({by: only([8], {wave_height: 2, wam: 2.7, wave_period: 15})}).comfort_held, 'long-period swell (2.7 ft at 15 s) at 8 am');
  assert.equal(day({by: only([11], {wave_height: 2.8, wam: 2.8, wave_period: 9, swell_wave_period: 17})}).comfort_held, 'long-period swell (2.8 ft at 17 s) at 11 am');
  assert.match(day({by: only([8], {wave_height: 2.5, wam: 2.5, wave_period: 15.4, swell_wave_period: 16.6})}).comfort_held, /\(2\.5 ft at 17 s\)/);
  // A wrong unit, a missing series or a non-finite value is not a measurement.
  assert.equal(day({over: {wave_period: 16, wave_height: 2.6, wam: 2.6}, units: {wave_period: 'min', swell_wave_period: 'min'}}).comfort_held, undefined, 'period in minutes');
  assert.equal(day({over: {wave_period: NaN, swell_wave_period: null, wave_height: 2.6, wam: 2.6}}).comfort_held, undefined, 'no usable period');
  assert.equal(day({over: {wave_period: 16, swell_wave_period: 10, wave_height: null, wam: null}}).comfort_held, undefined, 'no seas');
  assert.equal(day({over: {wave_period: -16, swell_wave_period: 10, wave_height: 3, wam: 3}}).comfort_held, undefined, 'a negative period');
});

test('seas and period in different hours do not combine; an unrated hour cannot hold another hour', () => {
  const split = day({by: t => t === at(DATE, 8) ? {wave_height: 3, wam: 3, wave_period: 10, swell_wave_period: 10} : t === at(DATE, 9) ? {wave_height: 2, wam: 2, wave_period: 17, swell_wave_period: 17} : {}});
  assert.deepEqual([split.comfort, 'comfort_held' in split], ['comfortable', false]);
  // 7 am has the long swell but no wind at all, so the hour is not rated (the brief excludes unrated rows too).
  const noWind = feed({by: only([7], {...LP, wind_speed_10m: null, wind_gusts_10m: null, ecmwf_wind: null, ecmwf_gust: null})});
  assert.equal(rateHour(readHour(noWind, POINT_INDEX, at(DATE, 7))), null, 'the fixture hour is unrated');
  const d = windowConditions(noWind, REGION, POINT, DATE);
  assert.deepEqual([d.comfort, 'comfort_held' in d], ['comfortable', false]);
});

test('the earliest hit wins whatever the timestamp order; only the asked date and window count; custom windows are inclusive', () => {
  const two = {by: t => t === at(DATE, 12) ? {wave_height: 3, wam: 3, wave_period: 18} : t === at(DATE, 9) ? LP : {}};
  for (const reverse of [false, true]) assert.equal(day({...two, reverse}).comfort_held, 'long-period swell (2.6 ft at 16 s) at 9 am', `reverse ${reverse}`);
  assert.equal(day({by: only([12], LP)}).comfort_held, 'long-period swell (2.6 ft at 16 s) at noon');
  // Outside the 06:00-14:00 window, or on another date, is ignored.
  for (const hour of [5, 15, 20]) assert.equal(day({by: only([hour], LP)}).comfort, 'comfortable', `${hour}:00 is outside the window`);
  assert.equal(day({by: only([9], LP, '2026-09-29')}).comfort, 'comfortable', 'another date');
  assert.equal(day({by: only([9], LP, '2026-09-29')}, {date: '2026-09-29'}).comfort_held, 'long-period swell (2.6 ft at 16 s) at 9 am');
  // Inclusive start and end of the default and a custom window.
  assert.equal(day({by: only([6], LP)}).comfort_held, 'long-period swell (2.6 ft at 16 s) at 6 am');
  assert.equal(day({by: only([14], LP)}).comfort_held, 'long-period swell (2.6 ft at 16 s) at 2 pm');
  const evening = {start: 17, end: 19};
  assert.equal(day({by: only([19], LP)}, {window: evening}).comfort_held, 'long-period swell (2.6 ft at 16 s) at 7 pm');
  assert.equal(day({by: only([9], LP)}, {window: evening}).comfort, 'comfortable', 'the 9 am hour is outside an evening window');
});

test('the region time zone names the hour: standard time after the fall-back, and another zone', () => {
  const fall = '2026-11-01';   // PST from 2 am: 9 am local is 17:00 UTC
  const november = Array.from({length: 24 * 4}, (_, i) => Date.parse('2026-10-31T00:00:00Z') / 1000 + i * 3600);
  assert.equal(day({times: november, by: only([9], LP, fall, 8)}, {date: fall}).comfort_held, 'long-period swell (2.6 ft at 16 s) at 9 am');
  const honolulu = {...REGION, timezone: 'Pacific/Honolulu'};   // UTC-10, no daylight saving
  assert.equal(day({by: only([9], LP, DATE, 10)}, {region: honolulu}).comfort_held, 'long-period swell (2.6 ft at 16 s) at 9 am');
  assert.equal(day({by: only([12], LP, DATE, 10)}, {region: honolulu}).comfort_held, 'long-period swell (2.6 ft at 16 s) at noon');
});

test('an already Bumpy, Rough or unavailable day is unchanged and gains no swell explanation', () => {
  const lp = only([8, 9, 10, 11], {wave_period: 16, swell_wave_period: 16, wave_height: 2.6, wam: 2.6});
  const calmSea = only([8, 9, 10, 11], {wave_height: 2.6, wam: 2.6});
  for (const [label, over, word] of [['bumpy', {wind_speed_10m: 16, ecmwf_wind: 16, wind_gusts_10m: 22, ecmwf_gust: 22}, 'bumpy'],
    ['rough', {wind_speed_10m: 30, ecmwf_wind: 30, wind_gusts_10m: 38, ecmwf_gust: 38}, 'rough']]) {
    const withSwell = day({over, by: lp}), without = day({over, by: calmSea});
    assert.equal(withSwell.comfort, word, label);
    assert.equal('comfort_held' in withSwell, false, label);
    assert.deepEqual(withSwell, {...without, sea_period_s: withSwell.sea_period_s, swell_period_s: withSwell.swell_period_s}, label);
  }
  const noData = windowConditions(feed({}), REGION, POINT, '2026-12-25');
  assert.deepEqual([noData.available, noData.comfort, 'comfort_held' in noData], [false, 'unknown', false]);
  const elsewhere = windowConditions({...feed({by: only([9], LP)}), region_id: 'elsewhere'}, REGION, POINT, DATE);
  assert.deepEqual([elsewhere.available, elsewhere.comfort, 'comfort_held' in elsewhere], [false, 'unknown', false]);
  const unmeasured = windowConditions(feed({over: Object.fromEntries(Object.keys(BASE).map(k => [k, null]))}), REGION, POINT, DATE);
  assert.deepEqual([unmeasured.available, 'comfort_held' in unmeasured], [false, false]);
});

test('boat factors: the reference boat and a looser or stricter caller boat use the same physical thresholds', () => {
  const ref = day({by: only([9], LP)});
  const loose = requestBoat({sea: 2.6, wind: 1.8, chopPeriod: 8});
  const own = day({by: only([9], LP)}, {boat: loose});
  assert.deepEqual([own.comfort, own.comfort_held, own.comfort_for], ['bumpy', ref.comfort_held, 'your boat'], 'a looser boat cannot suppress the hold');
  // A boat that finds the same hour calm still holds; below the threshold it never invents a hold.
  assert.equal(day({by: only([9], {wave_height: 2.4, wam: 2.4, wave_period: 18})}, {boat: loose}).comfort, 'comfortable');
  // A strict boat that already rates the day Bumpy or worse carries no swell text.
  const strict = requestBoat({sea: 0.45, wind: 0.6, chopPeriod: 6});
  const tight = day({by: only([9], LP)}, {boat: strict});
  assert.notEqual(tight.comfort, 'comfortable');
  assert.equal('comfort_held' in tight, false);
});

test('the forecast clock: fresh Bumpy and reason, held Unknown with its exact age reason, unusable unavailable; a Rough day never turns calmer', () => {
  const run = (ageH, opts = {}) => { const f = feed({by: only([9], LP), ageH, ...opts}); return withForecastClock(windowConditions(f, REGION, POINT, DATE), forecastClock(f, NOW)); };
  const fresh = run(4);
  assert.deepEqual([fresh.comfort, fresh.comfort_held], ['bumpy', 'long-period swell (2.6 ft at 16 s) at 9 am']);
  const held = run(20);
  assert.deepEqual([held.available, held.comfort, held.comfort_held, held.seas_ft !== null], [true, 'unknown', 'forecast run is 20 h old', true]);
  const gone = run(40);
  assert.deepEqual([gone.available, gone.comfort, gone.wind_kt, gone.seas_ft, 'comfort_held' in gone], [false, 'unknown', null, null, false]);
  // A Rough day stays Rough when held, and never gains a swell line.
  const gale = {wind_speed_10m: 30, ecmwf_wind: 30, wind_gusts_10m: 38, ecmwf_gust: 38};
  const f = feed({over: gale, by: only([9], LP), ageH: 20});
  const rough = withForecastClock(windowConditions(f, REGION, POINT, DATE), forecastClock(f, NOW));
  assert.deepEqual([rough.comfort, 'comfort_held' in rough], ['rough', false]);
});

test('inputs are not modified, and repeated calls agree', () => {
  const f = feed({by: only([9], LP)});
  const before = JSON.stringify(f);
  const a = windowConditions(f, REGION, POINT, DATE), b = windowConditions(f, REGION, POINT, DATE);
  assert.equal(JSON.stringify(f), before);
  assert.deepEqual(a, b);
  const reversed = feed({by: only([9], LP), reverse: true});
  const rbefore = JSON.stringify(reversed);
  windowConditions(reversed, REGION, POINT, DATE);
  assert.equal(JSON.stringify(reversed), rbefore, 'the timestamp array is not sorted in place');
});

test('the text agrees with the brief\'s own longPeriodHour on the same hours', () => {
  const cases = [
    ['single', only([9], LP)], ['exact', only([10], {wave_height: 2.5, wam: 2.5, wave_period: 15})],
    ['wam height', only([8], {wave_height: 2, wam: 2.7, wave_period: 15})], ['swell period', only([11], {wave_height: 2.8, wam: 2.8, wave_period: 9, swell_wave_period: 17})],
    ['two periods', only([8], {wave_height: 2.5, wam: 2.5, wave_period: 15.4, swell_wave_period: 16.6})], ['noon', only([12], LP)],
    ['rounding', only([7], {wave_height: 2.55, wam: 2.5, wave_period: 15.5})], ['none', only([9], {wave_height: 2.4, wam: 2.4, wave_period: 20})],
    ['early and late', t => t === at(DATE, 13) ? {wave_height: 4, wam: 4, wave_period: 18} : t === at(DATE, 7) ? LP : {}],
  ];
  for (const [label, by] of cases) {
    const f = feed({by}), d = windowConditions(f, REGION, POINT, DATE);
    const rows = [6, 7, 8, 9, 10, 11, 12, 13, 14].map(h => at(DATE, h)).map(t => ({ms: t * 1000, hour: readHour(f, POINT_INDEX, t)})).filter(r => rateHour(r.hour) !== null);
    const brief = longPeriodHour(rows, REGION.timezone);
    assert.equal(d.comfort_held, brief ?? undefined, label);
    assert.equal(d.comfort, brief ? 'bumpy' : 'comfortable', label);
  }
});

// ---- the public tool: both branches, and a two-day ask --------------------------------------------------

const ctx = (intel, over = {}) => ({env: {}, contact: {id: 'c1', role: 'angler', home_port: 'morro-bay'}, message: {id: 'in1'},
  deps: {feeds: async url => /intelligence\.json$/.test(url) ? intel : Promise.reject(Error('no feed'))}, db: null, language: 'en', settings: advisorSettings({}), now: NOW, ...over});

test('get_conditions without species exposes the Bumpy word and the hour; a two-day ask holds only the matching day', async () => {
  const sat = '2026-10-03', sun = '2026-10-04';
  const times = Array.from({length: 24 * 8}, (_, i) => Date.parse('2026-10-01T00:00:00Z') / 1000 + i * 3600);
  const intel = feed({times, by: only([9], LP, sun)});
  const when = Date.parse('2026-10-01T17:00:00Z');
  const issued = {...intel, forecast: {models: Object.fromEntries(Object.entries(intel.forecast.models).map(([id, m]) => [id, {...m, meta: {last_run_initialisation_time: when / 1000 - 4 * 3600}}]))}};
  const out = (await TOOL_BY_NAME.get('get_conditions').run({port: 'morro-bay', date: 'this weekend'}, ctx(issued, {now: when}))).result;
  assert.deepEqual(out.dates, [sat, sun]);
  assert.deepEqual(out.days.map(d => [d.date, d.comfort, d.comfort_held]), [[sat, 'comfortable', undefined], [sun, 'bumpy', 'long-period swell (2.6 ft at 16 s) at 9 am']]);
  assert.doesNotMatch(JSON.stringify(out), /\d\s*%/);
  const one = (await TOOL_BY_NAME.get('get_conditions').run({port: 'morro-bay', date: sun}, ctx(issued, {now: when}))).result;
  assert.deepEqual([one.days[0].comfort, one.days[0].comfort_held], ['bumpy', 'long-period swell (2.6 ft at 16 s) at 9 am']);
});
