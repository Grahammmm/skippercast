// SC0237-01: the advisor's get_conditions holds a Comfortable word at Bumpy on thin evidence, as the brief does
// (web/brief/verdict.ts holds Comfortable at Marginal when listed hours have no forecast or the marine alert check
// is unavailable): "N of M hours have no forecast" and "the marine alert check is unavailable" in comfort_held,
// after any long-period reason. A raw Bumpy / Rough / Unknown / unavailable day is returned exactly as before.
// Synthetic feeds (values invented), offline, injected readers; the network is blocked and restored.
import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
const {windowConditions, withForecastClock, advisoryCheckTime, advisoriesFrom, regionZones, WINDOW} = await import('../server/advisor/answers/conditions.ts');
const {forecastClock} = await import('../server/advisor/answers/forecast-clock.ts');
const {withBarHold} = await import('../server/advisor/answers/bar.ts');
const {tripConditions} = await import('../server/advisor/answers/planning.ts');
const {dailyInputs, hashInputs} = await import('../server/advisor/answers/reports.ts');
const {TOOL_BY_NAME} = await import('../server/advisor/tools/index.ts');
const {advisorSettings} = await import('../server/advisor/settings.ts');

const REGION = REGIONS['morro-bay'];
const POINT = 'central';
const INDEX = REGION.forecast_points.findIndex(p => p.id === POINT);
const DATE = '2026-09-28';                                    // PDT: UTC-7
const NOW = Date.parse('2026-09-28T15:00:00Z');
const BASE = {wind_speed_10m: 6, wind_gusts_10m: 9, wind_direction_10m: 315, ecmwf_wind: 6, ecmwf_gust: 9, wave_height: 2, wave_period: 10, wind_wave_height: 0.3, wind_wave_period: 4,
  swell_wave_height: 2, swell_wave_period: 10, swell_wave_direction: 300, secondary_swell_wave_height: 0.5, secondary_swell_wave_direction: 200, wam: 2};
const NO_WIND = {wind_speed_10m: null, wind_gusts_10m: null, ecmwf_wind: null, ecmwf_gust: null};
const UNIT = k => /direction/.test(k) ? '°' : /period/.test(k) ? 's' : /height/.test(k) ? 'ft' : 'kn';
const HOURS = Array.from({length: 24 * 7}, (_, i) => Date.parse('2026-09-26T00:00:00Z') / 1000 + i * 3600);
const at = (date, h, behind = 7) => Date.UTC(+date.slice(0, 4), +date.slice(5, 7) - 1, +date.slice(8, 10), h + behind) / 1000;
const only = (hours, values, date = DATE) => t => hours.some(h => at(date, h) === t) ? values : {};
const LP = {wave_height: 2.6, wam: 2.6, wave_period: 16};
const LP_9AM = 'long-period swell (2.6 ft at 16 s) at 9 am';
const NO_ALERTS = 'the marine alert check is unavailable';
const HELD = 'comfort_held';

/** An intelligence feed whose every hour reads BASE plus `over`; `by(t)` overrides single hours; `end` is every model's meta.data_end_time; `ageH` the run age. */
function feed({over = {}, by = () => ({}), ageH = 4, reverse = false, times = HOURS, end = null} = {}) {
  const order = reverse ? [...times].reverse() : times;
  const v = t => ({...BASE, ...over, ...by(t)});
  const series = keys => ({hourly_units: {time: 'unixtime', ...Object.fromEntries(keys.map(([k]) => [k, UNIT(k)]))},
    hourly: {time: order, ...Object.fromEntries(keys.map(([k, src]) => [k, order.map(t => v(t)[src ?? k])]))}});
  const model = keys => ({meta: {last_run_initialisation_time: NOW / 1000 - ageH * 3600, ...(end === null ? {} : {data_end_time: end})},
    data: Array.from({length: INDEX + 1}, (_, i) => i === INDEX ? series(keys) : null)});
  const wave = ['wave_height', 'wave_period', 'wind_wave_height', 'wind_wave_period', 'swell_wave_height', 'swell_wave_period', 'swell_wave_direction', 'secondary_swell_wave_height', 'secondary_swell_wave_direction'].map(k => [k]);
  return {region_id: 'morro-bay', completed_at: new Date(NOW - 3600000).toISOString(), forecast: {models: {
    gfs_global: model([['wind_speed_10m'], ['wind_gusts_10m'], ['wind_direction_10m']]),
    ncep_gfswave016: model(wave),
    ecmwf_ifs025: model([['wind_speed_10m', 'ecmwf_wind'], ['wind_gusts_10m', 'ecmwf_gust']]),
    ecmwf_wam: model([['wave_height', 'wam']]),
  }}};
}

const CHECKED = '2026-09-28T14:00:00Z';
const zoneSource = (zone, over = {}) => ({id: `alerts-${zone}`, name: `NWS ${zone} advisories`, kind: 'advisory', url: `https://api.weather.gov/alerts/active/zone/${zone}`,
  checked_at: CHECKED, max_age_hours: 36, status: 'ok', data: {issued_at: CHECKED, alerts: []}, ...over});
/** The daily fixture with only the named zones' alert sources: a complete empty check by default, `over[zone]` replacing fields of one. */
function daily({zones = ['PZZ645', 'PZZ670'], over = {}} = {}) {
  const d = read('./fixtures/feeds/daily-latest.json');
  for (const k of Object.keys(d.sources)) if (k.startsWith('alerts-')) delete d.sources[k];
  for (const zone of zones) d.sources[`alerts-${zone}`] = zoneSource(zone, over[zone] ?? {});
  return d;
}
const SCA = {event: 'Small Craft Advisory', headline: 'synthetic', onset: '2026-09-28T05:00:00-07:00', ends: '2026-09-28T20:00:00-07:00'};

const readers = (intel, dailyFeed, reads = {}) => async url => {
  reads[url] = (reads[url] ?? 0) + 1;
  return /intelligence\.json$/.test(url) ? intel : /latest\.json$/.test(url) && dailyFeed !== null ? dailyFeed : Promise.reject(Error('no feed'));
};
const run = (intel, dailyFeed, input = {}, over = {}) => tripConditions({port: 'morro-bay', date: DATE, ...input},
  {now: NOW, language: 'en', deps: {feeds: readers(intel, dailyFeed)}, contact: null, settings: advisorSettings({}), ...over});
const day0 = async (intel, dailyFeed, input) => (await run(intel, dailyFeed, input)).days[0];
const stmt = {bind: () => stmt, all: async () => ({results: []}), first: async () => null, run: async () => ({meta: {changes: 0}})};
const STUB_DB = {prepare: () => stmt};
const inputs = (intel, dailyFeed, now = NOW) => dailyInputs({DB: STUB_DB}, 'morro-bay', DATE, {feeds: readers(intel, dailyFeed)}, now);
const direct = (intel, over = {}) => windowConditions(intel, REGION, POINT, DATE, over.window ?? WINDOW, over.boat ?? null, over.advisories ?? [], over.checked ?? true);

const realFetch = globalThis.fetch;
test.before(() => { globalThis.fetch = () => { throw new Error('network is blocked in test_advisor_thin_evidence'); }; });
test.after(() => { globalThis.fetch = realFetch; });

test('thin_unrated_window: listed hours with no forecast hold a Comfortable day at Bumpy with the exact count', () => {
  const calm = direct(feed());
  assert.deepEqual([calm.comfort, HELD in calm], ['comfortable', false], 'the calm baseline is unchanged');
  const one = direct(feed({by: only([7], NO_WIND)}));
  assert.deepEqual([one.comfort, one[HELD]], ['bumpy', '1 of 9 hours have no forecast']);
  assert.deepEqual([one.wind_kt, one.gusts_kt, one.seas_ft], [calm.wind_kt, calm.gusts_kt, calm.seas_ft], 'the measured ranges are not touched by the hold');
  assert.equal(direct(feed({by: only([7, 8, 12], NO_WIND)}))[HELD], '3 of 9 hours have no forecast');
  // Timestamp order does not matter, and the count is of the asked window's hours only.
  assert.equal(direct(feed({by: only([7], NO_WIND), reverse: true}))[HELD], '1 of 9 hours have no forecast');
  assert.equal(direct(feed({by: only([9, 10], NO_WIND)}), {window: {start: 9, end: 11}})[HELD], '2 of 3 hours have no forecast', 'a custom window counts its own hours');
});

test('thin_unrated_window: gaps outside the window or the date hold nothing; the model end counts, equal to it is still read', () => {
  for (const hour of [5, 15, 20]) assert.equal(HELD in direct(feed({by: only([hour], NO_WIND)})), false, `${hour}:00 is outside the window`);
  assert.equal(HELD in direct(feed({by: only([9], NO_WIND, '2026-09-29')})), false, 'another date');
  // data_end_time at 10 am: 11 am to 2 pm read unknown (4 hours); at 2 pm: every hour is still read.
  assert.equal(direct(feed({end: at(DATE, 10)}))[HELD], '4 of 9 hours have no forecast');
  const equalToEnd = direct(feed({end: at(DATE, 14)}));
  assert.deepEqual([equalToEnd.comfort, HELD in equalToEnd], ['comfortable', false]);
  assert.equal(direct(feed({end: at(DATE, 14) - 1}))[HELD], '1 of 9 hours have no forecast');
});

test('thin_unrated_window: an all-unrated or unmeasured window keeps Unknown and its availability exactly', () => {
  const allUnrated = direct(feed({over: NO_WIND}));
  assert.deepEqual([allUnrated.available, allUnrated.comfort, HELD in allUnrated], [true, 'unknown', false]);
  assert.ok(JSON.stringify(allUnrated) === JSON.stringify(direct(feed({over: NO_WIND}), {checked: false})), 'a missing alert check changes nothing on an Unknown day');
  const unmeasured = direct(feed({over: Object.fromEntries(Object.keys(BASE).map(k => [k, null]))}), {checked: false});
  assert.deepEqual([unmeasured.available, unmeasured.comfort, unmeasured.reason, HELD in unmeasured], [false, 'unknown', 'no usable forecast measurements for this window', false]);
});

test('thin_alert_evidence: each missing or malformed zone check holds a Comfortable day; an unrelated good zone cannot clear it', async () => {
  const intel = feed();
  const complete = await run(intel, daily());
  assert.deepEqual([complete.days[0].comfort, HELD in complete.days[0], complete.advisories_checked, complete.advisories_as_of], ['comfortable', false, true, CHECKED]);
  const broken = {
    'a zone with no record': daily({zones: ['PZZ645']}),
    'the other zone with no record': daily({zones: ['PZZ670']}),
    'no zone at all': daily({zones: []}),
    'a failed status': daily({over: {PZZ670: {status: 'error'}}}),
    'alerts that are not an array': daily({over: {PZZ645: {data: {alerts: null}}}}),
    'no checked_at': daily({over: {PZZ670: {checked_at: undefined}}}),
    'an unparseable checked_at': daily({over: {PZZ670: {checked_at: 'yesterday'}}}),
    'a record that is an array': Object.assign(daily(), {sources: {...daily().sources, 'alerts-PZZ670': []}}),
  };
  for (const [label, d] of Object.entries(broken)) {
    const out = await run(intel, d);
    assert.deepEqual([out.days[0].comfort, out.days[0][HELD], out.advisories_checked, out.advisories_as_of], ['bumpy', NO_ALERTS, false, null], label);
  }
  // No daily feed at all (a failed read) is the same: no alert check.
  const none = await run(intel, null);
  assert.deepEqual([none.days[0].comfort, none.days[0][HELD], none.advisories_checked], ['bumpy', NO_ALERTS, false]);
  assert.match(none.note, /could not be checked/);
});

test('thin_alert_evidence: the oldest check is reported with no age cutoff; a known warning from an incomplete check still forces Rough', async () => {
  assert.equal(advisoryCheckTime(daily().sources, ['PZZ645', 'PZZ670']), CHECKED);
  const mixed = daily({over: {PZZ645: {checked_at: '2026-09-28T10:00:00-07:00'}, PZZ670: {checked_at: '2026-09-28T16:30:00Z'}}});   // 17:00Z and 16:30Z
  assert.equal(advisoryCheckTime(mixed.sources, ['PZZ645', 'PZZ670']), '2026-09-28T16:30:00Z', 'the oldest instant, not the first or the largest string');
  assert.equal(advisoryCheckTime(mixed.sources, ['PZZ645', 'PZZ645', 'PZZ670'].filter((z, i, a) => a.indexOf(z) === i)), '2026-09-28T16:30:00Z');
  assert.equal(advisoryCheckTime(daily({over: {PZZ645: {checked_at: '2020-01-01T00:00:00Z'}}}).sources, ['PZZ645', 'PZZ670']), '2020-01-01T00:00:00Z', 'an old check is still a complete check');
  assert.equal(advisoryCheckTime(daily().sources, []), null, 'no configured zones is incomplete');
  assert.equal(advisoryCheckTime(undefined, ['PZZ645']), null);
  // A retained warning (the zone's latest read failed) is still a warning: Rough, no held reason, check reported as unavailable.
  const retained = daily({over: {PZZ645: {status: 'error', data: {alerts: [SCA]}}}});
  const out = await run(feed(), retained);
  assert.deepEqual([out.days[0].comfort, out.days[0].advisory, HELD in out.days[0], out.advisories_checked, out.advisories.length, out.lead_with_advisory], ['rough', 'Small Craft Advisory', false, false, 1, true]);
  assert.equal(advisoriesFrom(retained, regionZones(REGION), at(DATE, 6) * 1000, at(DATE, 14) * 1000).length, 1);
});

test('thin_precedence: a day that is not raw Comfortable is returned exactly as before, whatever the evidence', async () => {
  const rawBumpy = {over: {wind_speed_10m: 15, wind_gusts_10m: 20, ecmwf_wind: 15, ecmwf_gust: 20, wave_height: 5, wam: 5, wave_period: 7, wind_wave_height: 2.5, swell_wave_height: 3}}, rawRough = {over: {wind_speed_10m: 30, wind_gusts_10m: 40, ecmwf_wind: 30, ecmwf_gust: 40}};
  for (const [label, opts] of [['bumpy', rawBumpy], ['rough', rawRough]]) {
    const full = direct(feed(opts)), thin = direct(feed({...opts, by: only([7], NO_WIND)}), {checked: false});
    assert.notEqual(full.comfort, 'comfortable', `${label} fixture is not comfortable`);
    assert.equal(thin.comfort, full.comfort, label);
    assert.equal(HELD in thin, false, `${label}: no reason appended to a naturally ${label} day`);
    assert.deepEqual(direct(feed(opts), {checked: false}), full, `${label}: a missing alert check alone changes nothing`);
  }
  // A listed Rough advisory wins over every hold.
  const sca = direct(feed({by: only([7], NO_WIND)}), {advisories: [{event: 'Small Craft Advisory'}], checked: false});
  assert.deepEqual([sca.comfort, sca.advisory, HELD in sca], ['rough', 'Small Craft Advisory', false]);
  // Boat factors never bypass the evidence holds.
  for (const boat of [{sea: 2.6, wind: 1.8, chopPeriod: 4}, {sea: 1.2, wind: 1, chopPeriod: 4}]) {
    assert.equal(direct(feed({by: only([7], NO_WIND)}), {boat})[HELD], '1 of 9 hours have no forecast');
    assert.equal(direct(feed(), {boat, checked: false})[HELD], NO_ALERTS);
  }
});

test('thin_precedence: long-period, unrated hours and the missing check each appear once, in order; the bar hold appends once; age overrides all', () => {
  const by = t => t === at(DATE, 9) ? LP : t === at(DATE, 7) ? NO_WIND : {};
  const all = direct(feed({by}), {checked: false});
  assert.deepEqual([all.comfort, all[HELD]], ['bumpy', `${LP_9AM}; 1 of 9 hours have no forecast; ${NO_ALERTS}`]);
  assert.deepEqual([direct(feed({by: only([9], LP)}), {checked: false})[HELD]], [`${LP_9AM}; ${NO_ALERTS}`]);
  assert.equal(direct(feed({by: only([9], LP)}))[HELD], LP_9AM, 'the long-period reason alone is as before');
  const bar = {date: DATE, entrance: 'Morro Bay entrance', basis: 'offshore', judged: true, hazardous_at: '2026-09-28T16:00:00Z', note: 'n'};
  const hazard = 'the bar estimate reads hazardous at 9 am';
  const barred = withBarHold(all, bar, REGION.timezone);
  assert.equal(barred[HELD], `${all[HELD]}; ${hazard}`, 'all four reasons, each once');
  assert.equal(withBarHold(barred, bar, REGION.timezone), barred, 'no duplicate bar text');
  for (const held of ['1 of 9 hours have no forecast', NO_ALERTS, `3 of 9 hours have no forecast; ${NO_ALERTS}`]) {
    const out = withBarHold({...all, comfort: 'bumpy', [HELD]: held}, bar, REGION.timezone);
    assert.equal(out[HELD], `${held}; ${hazard}`, held);
  }
  const comfortable = direct(feed()), onBar = withBarHold(comfortable, bar, REGION.timezone);
  assert.deepEqual([onBar.comfort, onBar[HELD]], ['bumpy', hazard], 'a bar hold alone is as before');
  // A day held for something else, or naturally Bumpy, is not touched by the bar.
  for (const d of [{...all, [HELD]: 'forecast run is 20 h old', comfort: 'bumpy'}, {...all, [HELD]: undefined}]) assert.equal(withBarHold(d, bar, REGION.timezone), d);
  // An old run: Unknown with the exact age reason only. An unusable run: no readings at all.
  const old = withForecastClock(all, forecastClock(feed({by, ageH: 20}), NOW));
  assert.deepEqual([old.comfort, old[HELD], old.wind_kt], ['unknown', 'forecast run is 20 h old', all.wind_kt]);
  const gone = withForecastClock(all, forecastClock(feed({by, ageH: 40}), NOW));
  assert.deepEqual([gone.available, gone.comfort, gone.wind_kt, gone.seas_ft, HELD in gone], [false, 'unknown', null, null, false]);
});

test('thin_all_advisor_paths: get_conditions with and without a species, custom windows and two dates agree', async () => {
  const get = TOOL_BY_NAME.get('get_conditions');
  const ctx = (intel, dailyFeed, over = {}) => ({env: {}, contact: {id: 'c1', role: 'angler', home_port: 'morro-bay'}, message: {id: 'in1'}, deps: {feeds: readers(intel, dailyFeed, over.reads)},
    db: STUB_DB, language: 'en', settings: advisorSettings({}), now: NOW});
  const thinIntel = feed({by: only([7], NO_WIND)});
  for (const input of [{port: 'morro-bay', date: DATE}, {port: 'morro-bay', date: DATE, species: 'rockfish'}]) {
    const ok = (await get.run(input, ctx(feed(), daily()))).result, unrated = (await get.run(input, ctx(thinIntel, daily()))).result, noCheck = (await get.run(input, ctx(feed(), daily({zones: ['PZZ645']})))).result;
    assert.deepEqual([ok.days[0].comfort, HELD in ok.days[0]], ['comfortable', false], JSON.stringify(input));
    assert.deepEqual([unrated.days[0].comfort, unrated.days[0][HELD]], ['bumpy', '1 of 9 hours have no forecast'], JSON.stringify(input));
    assert.deepEqual([noCheck.days[0].comfort, noCheck.days[0][HELD], noCheck.advisories_checked], ['bumpy', NO_ALERTS, false], JSON.stringify(input));
    assert.doesNotMatch(JSON.stringify([ok, unrated, noCheck]), /\d\s*%/);
  }
  // Custom inclusive windows: the hold counts the asked hours.
  const early = (await get.run({port: 'morro-bay', date: DATE, start_hour: 7, end_hour: 8}, ctx(thinIntel, daily()))).result;
  assert.deepEqual([early.days[0].comfort, early.days[0][HELD]], ['bumpy', '1 of 2 hours have no forecast']);
  const late = (await get.run({port: 'morro-bay', date: DATE, start_hour: 8, end_hour: 14}, ctx(thinIntel, daily()))).result;
  assert.deepEqual([late.days[0].comfort, HELD in late.days[0]], ['comfortable', false], 'the unrated hour is outside this window');
  // Two dates: only the date with the gap is held, and the daily feed is read once.
  const times = Array.from({length: 24 * 8}, (_, i) => Date.parse('2026-10-01T00:00:00Z') / 1000 + i * 3600);
  const weekend = feed({times, by: only([9], NO_WIND, '2026-10-04')}), when = Date.parse('2026-10-01T17:00:00Z'), reads = {};
  const intel = {...weekend, forecast: {models: Object.fromEntries(Object.entries(weekend.forecast.models).map(([id, m]) => [id, {...m, meta: {last_run_initialisation_time: when / 1000 - 4 * 3600}}]))}};
  const two = (await get.run({port: 'morro-bay', date: 'this weekend'}, {...ctx(intel, daily(), {reads}), now: when})).result;
  assert.deepEqual(two.days.map(d => [d.date, d.comfort, d[HELD]]), [['2026-10-03', 'comfortable', undefined], ['2026-10-04', 'bumpy', '1 of 9 hours have no forecast']]);
  assert.equal(Object.entries(reads).filter(([u]) => /latest\.json$/.test(u)).reduce((n, [, c]) => n + c, 0), 1, 'no extra daily feed read');
});

test('thin_all_advisor_paths: daily inputs hold the same way, project the reason, and hash stably until a check recovers', async () => {
  const ok = await inputs(feed(), daily());
  assert.deepEqual([ok.conditions.available, ok.conditions.day.comfort, HELD in ok.conditions.day], [true, 'comfortable', false]);
  const unrated = await inputs(feed({by: only([7], NO_WIND)}), daily());
  assert.deepEqual([unrated.conditions.day.comfort, unrated.conditions.day[HELD]], ['bumpy', '1 of 9 hours have no forecast']);
  const missing = await inputs(feed(), daily({zones: ['PZZ645']})), failed = await inputs(feed(), null);
  for (const out of [missing, failed]) assert.deepEqual([out.conditions.available, out.conditions.day.comfort, out.conditions.day[HELD]], [true, 'bumpy', NO_ALERTS]);
  assert.deepEqual(Object.keys(missing.conditions.day).sort(), ['comfort', 'comfort_held', 'sea_period_s', 'seas_ft', 'wind_from', 'wind_kt'], 'no new day key');
  assert.deepEqual(Object.keys(missing.conditions).sort(), ['advisories', 'available', 'day']);
  // A known warning wins over the holds here too, and an old run is Unknown with its age.
  const warned = await inputs(feed(), daily({zones: ['PZZ645'], over: {PZZ645: {data: {alerts: [SCA]}}}}));
  assert.deepEqual([warned.conditions.day.comfort, HELD in warned.conditions.day, warned.conditions.advisories], ['rough', false, ['Small Craft Advisory']]);
  const old = await inputs(feed({ageH: 20}), daily({zones: ['PZZ645']}));
  assert.deepEqual([old.conditions.day.comfort, old.conditions.day[HELD]], ['unknown', 'forecast run is 20 h old']);
  // Stable repeated inputs; the hash changes when the missing check recovers.
  const again = await inputs(feed(), daily({zones: ['PZZ645']}));
  assert.equal(await hashInputs(again), await hashInputs(missing), 'the same feeds hash the same');
  assert.notEqual(await hashInputs(missing), await hashInputs(ok), 'a recovered check changes the hash');
});
