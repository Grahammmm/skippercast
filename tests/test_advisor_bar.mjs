// SC0022-08: the advisor's get_conditions holds a Comfortable word at Bumpy when the shared harbour-bar estimate
// (packages/coast bar-conditions barHours, offshore basis) reads hazardous in the window, names the local hour, and
// says the bar was not (fully) judged when its inputs are missing, as web/brief/verdict.ts barHazard does for the brief.
// Synthetic feeds (values invented), offline, injected readers; the shared barHours is called for real.
import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
const REGION_IDS = ['morro-bay', 'humboldt-bay-cape-mendocino', 'fort-bragg-point-arena', 'crescent-city', 'southern-california'];
globalThis.REGIONS = Object.fromEntries(REGION_IDS.map(id => [id, read(`../regions/${id}/region.json`)]));
globalThis.DEPLOYMENT = read('../deployments/production.json');
const {barHours, entranceFor, BAR_CHECK} = await import('../packages/coast/src/bar-conditions.ts');
const {windowConditions, WINDOW} = await import('../server/advisor/answers/conditions.ts');
const {advisorBarCheck, withBarHold} = await import('../server/advisor/answers/bar.ts');
const {tripConditions} = await import('../server/advisor/answers/planning.ts');
const {TOOL_BY_NAME} = await import('../server/advisor/tools/index.ts');
const {TOOL_RESULT_MAX} = await import('../server/advisor/tools/tool.ts');
const {advisorSettings} = await import('../server/advisor/settings.ts');

const REGION = REGIONS['morro-bay'];
const PORT_ROW = {'morro-bay': 'central'};
const DATE = '2026-09-28';                                    // PDT: UTC-7
const NOW = Date.parse('2026-09-28T15:00:00Z');
const BOAT = {sea: 1.2, wind: 1, chopPeriod: 4};              // a valid caller boat (conditions.ts requestBoat)
const BASE = {wind_speed_10m: 6, wind_gusts_10m: 9, wind_direction_10m: 315, ecmwf_wind: 6, ecmwf_gust: 9, wave_height: 2, wave_period: 10, wind_wave_height: 0.3, wind_wave_period: 4,
  swell_wave_height: 2, swell_wave_period: 10, swell_wave_direction: 300, secondary_swell_wave_height: 0.5, secondary_swell_wave_direction: 200, wam: 2};
const UNIT = k => /direction/.test(k) ? '°' : /period/.test(k) ? 's' : /height/.test(k) ? 'ft' : 'kn';
const HOURS = Array.from({length: 24 * 7}, (_, i) => Date.parse('2026-09-26T00:00:00Z') / 1000 + i * 3600);
const epoch = iso => Date.parse(iso) / 1000;
/** Epoch seconds of local hour `h` on `date` at a fixed UTC offset (hours behind UTC). */
const at = (date, h, behind = 7) => Date.UTC(+date.slice(0, 4), +date.slice(5, 7) - 1, +date.slice(8, 10), h + behind) / 1000;
/** Overrides applied only at the given epoch seconds. */
const onlyAt = (times, values) => t => times.includes(t) ? values : {};
const HAZ = {wave_height: 6.5, wam: 6.5, wave_period: 14};   // 6.5 ft at 14 s: Hazardous mid-ebb, Caution otherwise (offshore thresholds)

/** An intelligence feed for `region`'s `pointId` whose every hour reads BASE plus `over`; `by(t)` overrides single hours; `units` a unit label; `ageH` is each run's age at `now`. */
function feed({region = REGION, pointId = 'central', over = {}, by = () => ({}), units = {}, ageH = 4, reverse = false, times = HOURS, now = NOW, drop = []} = {}) {
  const index = region.forecast_points.findIndex(p => p.id === pointId);
  const order = reverse ? [...times].reverse() : times;
  const v = t => ({...BASE, ...over, ...by(t)});
  const series = keys => ({hourly_units: {time: 'unixtime', ...Object.fromEntries(keys.map(([k]) => [k, units[k] ?? UNIT(k)]))},
    hourly: {time: order, ...Object.fromEntries(keys.filter(([k]) => !drop.includes(k)).map(([k, src]) => [k, order.map(t => v(t)[src ?? k])]))}});
  const model = keys => ({meta: {last_run_initialisation_time: now / 1000 - ageH * 3600}, data: Array.from({length: index + 1}, (_, i) => i === index ? series(keys) : null)});
  const wave = ['wave_height', 'wave_period', 'wind_wave_height', 'wind_wave_period', 'swell_wave_height', 'swell_wave_period', 'swell_wave_direction', 'secondary_swell_wave_height', 'secondary_swell_wave_direction'].map(k => [k]);
  return {region_id: region.id, completed_at: new Date(now - 3600000).toISOString(), forecast: {models: {
    gfs_global: model([['wind_speed_10m'], ['wind_gusts_10m'], ['wind_direction_10m']]),
    ncep_gfswave016: model(wave),
    ecmwf_ifs025: model([['wind_speed_10m', 'ecmwf_wind'], ['wind_gusts_10m', 'ecmwf_gust']]),
    ecmwf_wam: model([['wave_height', 'wam']]),
  }}};
}
const tide = (time, type, height_ft = type === 'H' ? 5 : 0.5) => ({time, height_ft, type});
/** H at 06:00 PDT (13:00Z), L at 12:00 PDT (19:00Z), H after midnight: 09:00 PDT (16:00Z) is the middle of the ebb (0.5). */
const TIDES = [tide('2026-09-28T13:00:00Z', 'H'), tide('2026-09-28T19:00:00Z', 'L'), tide('2026-09-29T01:30:00Z', 'H')];
/** The daily fixture with no alerts and the given tide source. */
function daily({predictions = TIDES, status = 'ok', alerts = [], regionId = 'morro-bay'} = {}) {
  const d = read('./fixtures/feeds/daily-latest.json');
  d.region_id = regionId;
  for (const s of Object.values(d.sources)) if (Array.isArray(s.data?.alerts)) s.data.alerts = alerts;
  // SC0237-01: a complete check for the region's second configured zone too (the fixture supplies only PZZ645), so bar-only cases stay free of the missing-alert-check hold.
  const first = d.sources['alerts-PZZ645'];
  d.sources['alerts-PZZ670'] = {...first, id: 'alerts-PZZ670', name: 'NWS PZZ670 advisories', url: first.url.replace('PZZ645', 'PZZ670'), data: {...first.data, alerts}};
  d.sources.tides.status = status;
  d.sources.tides.data.predictions = predictions;
  return d;
}
const check = (over = {}) => advisorBarCheck({intel: feed(), daily: daily(), region: REGION, port: 'morro-bay', pointId: 'central', date: DATE, window: WINDOW, ...over});
const NO_CLAIM = /\b(open|closed|safe|clear to cross)\b/i;
const HAZARD_9AM = {by: onlyAt([at(DATE, 9)], HAZ)};
const run = (intel, dailyFeed, input, over = {}) => tripConditions({port: 'morro-bay', date: DATE, ...input},
  {now: NOW, language: 'en', deps: {feeds: async url => /intelligence\.json$/.test(url) ? intel : /latest\.json$/.test(url) ? dailyFeed : Promise.reject(Error('no feed'))}, ...over});

// Nothing in this suite may reach the network.
const realFetch = globalThis.fetch;
test.before(() => { globalThis.fetch = () => { throw new Error('network is blocked in test_advisor_bar'); }; });
test.after(() => { globalThis.fetch = realFetch; });

test('bar_offshore_matches_shared_hours: the adapter reads the hours and tide events barHours reads, hazardous only where it does', () => {
  // The hours the adapter must map (web/conditions.ts briefForecast), built by hand, through the real shared function.
  const hand = (t, over = {}) => ({at: new Date(t * 1000).toISOString(), windKnots: 6, gustKnots: 9, windDirectionDeg: 315, waveFt: 2, wavePeriodS: 10, swellFt: 2, swellPeriodS: 10, ...over});
  const events = TIDES.map(e => ({at: e.time, heightFt: e.height_ft, type: e.type}));
  const hourly = [6, 7, 8, 9, 10, 11, 12, 13, 14].map(h => at(DATE, h));
  const shared = barHours({hours: hourly.map(t => hand(t, t === at(DATE, 9) ? {waveFt: 6.5, wavePeriodS: 14} : {})), site: undefined, entrance: entranceFor('morro-bay', 'morro-bay'), tideEvents: events});
  const expect = shared.filter(h => h.band === 'Hazardous');
  assert.equal(expect.length, 1);
  assert.equal(expect[0].tide.midEbb, true);
  const got = check({intel: feed(HAZARD_9AM)});
  assert.equal(got.hazardous_at, expect[0].at, 'the earliest hazardous hour is the shared one');
  assert.equal(got.hazardous_at, '2026-09-28T16:00:00.000Z');
  assert.deepEqual([got.date, got.entrance, got.basis, got.judged], [DATE, 'Morro Bay entrance', 'offshore', true]);
  assert.match(got.note, /^Offshore bar estimate; nearshore conditions were not judged\./);
  assert.ok(got.note.endsWith(BAR_CHECK), 'ends with the standing line, verbatim');
  assert.doesNotMatch(got.note, NO_CLAIM);
  // 14 s carries the long-period rule, so an ebb hour is hazardous; the same 6.5 ft on the flood (14:00 PDT), or at early ebb (07:00 PDT, 0.17) with a 12 s period, is a caution, not a hazard.
  assert.equal(check({intel: feed({by: onlyAt([at(DATE, 7)], HAZ)})}).hazardous_at, '2026-09-28T14:00:00.000Z');
  assert.equal(check({intel: feed({by: t => t === at(DATE, 7) ? {...HAZ, wave_period: 12} : t === at(DATE, 14) ? HAZ : {}})}).hazardous_at, null);
  // 10 ft is hazardous on any tide.
  assert.equal(check({intel: feed({by: onlyAt([at(DATE, 14)], {...HAZ, wave_height: 10, wam: 10})})}).hazardous_at, '2026-09-28T21:00:00.000Z');
  // Just under the thresholds: 5.9 ft mid-ebb is not hazardous.
  assert.equal(check({intel: feed({by: onlyAt([at(DATE, 9)], {...HAZ, wave_height: 5.9, wam: 5.9})})}).hazardous_at, null);
  // The earliest hit wins whatever the feed's order; hours outside the window never count (the strict one-hour rule against the window's own hours).
  const two = {by: onlyAt([at(DATE, 8), at(DATE, 10)], HAZ)};
  assert.equal(check({intel: feed({...two, reverse: true})}).hazardous_at, '2026-09-28T15:00:00.000Z');
  assert.equal(check({intel: feed(HAZARD_9AM), window: {start: 10, end: 14}}).hazardous_at, null);
  assert.equal(check({intel: feed(HAZARD_9AM), window: {start: 9, end: 9}}).hazardous_at, '2026-09-28T16:00:00.000Z');
  // Same-hour primary seas and period only: a calm primary sea with a high WAM sea, or a high sea whose period is unusable, is not a hazard.
  assert.equal(check({intel: feed({by: onlyAt([at(DATE, 9)], {wam: 9, wave_height: 2})})}).hazardous_at, null);
  assert.equal(check({intel: feed({by: onlyAt([at(DATE, 9)], {...HAZ, wave_period: 0})})}).hazardous_at, null);
});

test('bar_port_is_not_region: the four regulated ports get their own entrance; no other port, point or region does', () => {
  const named = {'morro-bay': 'Morro Bay entrance', 'humboldt-bay': 'Humboldt Bay entrance', 'noyo-harbor': 'Noyo River entrance', 'crescent-city': 'Crescent City Harbor entrance'};
  const ports = read('../catalog/home-ports.json').ports;
  for (const [port, name] of Object.entries(named)) {
    const row = ports.find(p => p.id === port), region = REGIONS[row.region];
    const got = advisorBarCheck({intel: feed({region, pointId: row.forecast_point}), daily: null, region, port, pointId: row.forecast_point, date: DATE, window: WINDOW});
    assert.equal(got?.entrance, name, port);
    // The other three have no entrance bearing, so wind against the ebb is said not to be judged there.
    assert.equal(got.note.includes('Wind against the ebb was not judged.'), port !== 'morro-bay', port);
  }
  // Port San Luis shares Morro Bay's region (a different forecast point): it never gets Morro Bay's bar.
  const avila = ports.find(p => p.id === 'port-san-luis');
  assert.equal(avila.region, 'morro-bay');
  assert.equal(advisorBarCheck({intel: feed({pointId: 'avila'}), daily: daily(), region: REGION, port: 'port-san-luis', pointId: 'avila', date: DATE, window: WINDOW}), null);
  // Other ports, unknown and inherited ids, a port in the wrong region, the right port at the wrong point.
  for (const port of ['monterey', 'santa-barbara', 'shelter-cove', 'constructor', '__proto__', 'toString', '', 'Morro Bay']) {
    assert.equal(check({port}), null, port);
  }
  assert.equal(check({region: REGIONS['southern-california']}), null, 'Morro Bay in the wrong region');
  assert.equal(check({pointId: 'avila'}), null, 'Morro Bay at Avila\'s point');
  assert.equal(check({port: 'humboldt-bay'}), null, 'Humboldt Bay in Morro Bay\'s region');
  // Through tripConditions: a non-regulated port gets no new output at all.
  const sb = REGIONS['southern-california'];
  return run(feed({region: sb, pointId: 'santa-barbara'}), daily({regionId: 'southern-california'}), {port: 'santa-barbara'}).then(out => {
    assert.equal('bar_checks' in out, false);
    assert.doesNotMatch(out.note, /bar_checks/);
  });
});

test('bar_unknown_is_not_clearance: missing inputs make the bar unjudged and name what is missing, never a clearance', () => {
  const hazard = feed(HAZARD_9AM);
  const unjudged = (label, got, missing) => {
    assert.equal(got.judged, false, label);
    assert.match(got.note, /^The bar was not fully judged from the available inputs/, label);
    if (missing) assert.ok(got.note.includes(missing), `${label}: names ${missing}`);
    assert.ok(got.note.endsWith(BAR_CHECK), label);
    assert.doesNotMatch(got.note, NO_CLAIM, label);
  };
  // Tide: no daily feed, a tide source that is not ok, malformed arrays and rows, no explicit offset, a conflicting bracket, a missing next event.
  const tideCases = {
    'no daily feed': null, retained: daily({status: 'retained'}), failed: daily({status: 'error'}), 'not an array': daily({predictions: 'x'}),
    'malformed rows': daily({predictions: [null, 7, {time: 5, type: 'H', height_ft: 1}, {time: TIDES[0].time, type: 'X', height_ft: 1}, {time: TIDES[0].time, type: 'H', height_ft: 'tall'}]}),
    'no offsets': daily({predictions: TIDES.map(e => ({...e, time: e.time.replace('Z', '')}))}),
    conflicting: daily({predictions: [...TIDES, tide('2026-09-28T13:00:00Z', 'L')]}),
    'missing adjacent event': daily({predictions: [tide('2026-09-28T13:00:00Z', 'H')]}),
  };
  for (const [label, d] of Object.entries(tideCases)) {
    const got = check({intel: hazard, daily: d});
    unjudged(label, got, 'tide phase');
    assert.equal(got.hazardous_at, null, `${label}: no phase, no invented hazard at 6.5 ft`);
  }
  // Forecast: no intelligence feed, another region's feed, a missing point or date, bad units, an unusable period, no wind direction.
  unjudged('no intel', check({intel: null}), 'forecast hours');
  unjudged('other region', check({intel: {...feed(), region_id: 'elsewhere'}}), 'forecast hours');
  unjudged('no date', check({date: '2026-12-25'}), 'forecast hours');
  unjudged('bad units', check({intel: feed({units: {wave_height: 'm'}})}), 'forecast swell');
  unjudged('no period', check({intel: feed({over: {wave_period: 0}})}), 'forecast swell');
  const noDir = check({intel: feed({drop: ['wind_direction_10m']})});
  assert.equal(noDir.judged, true, 'wind direction alone does not make the swell or tide unknown');
  assert.match(noDir.note, /Wind against the ebb was not judged\./);
  assert.equal(check().note.includes('Wind against the ebb'), false, 'Morro Bay with wind and direction: judged for the wind');
  // A hazard that is known stays known when another driver is unknown: no tide phase at 10 ft is still Hazardous.
  const tenFt = check({intel: feed({by: onlyAt([at(DATE, 9)], {wave_height: 10, wam: 10, wave_period: 14})}), daily: null});
  assert.equal(tenFt.judged, false);
  assert.equal(tenFt.hazardous_at, '2026-09-28T16:00:00.000Z');
  // The tide bracket may sit in the adjacent days.
  const next = check({intel: feed(HAZARD_9AM), daily: daily({predictions: [tide('2026-09-27T20:00:00Z', 'H'), tide('2026-09-29T02:00:00Z', 'L')]})});
  assert.equal(next.judged, true);
  // Input is not mutated or reordered.
  const events = [...TIDES].reverse(), d = daily({predictions: events}), before = JSON.stringify(d);
  check({intel: hazard, daily: d});
  assert.ok(JSON.stringify(d) === before && events[0].time === TIDES[2].time, 'feed left as it was');
});

test('bar_hold_never_calms: Comfortable becomes Bumpy with the local hour; every other day is returned as it was', () => {
  const day = (over = {}) => ({date: DATE, window: '06:00-14:00', available: true, wind_kt: [6, 6], wind_from: 'NW', gusts_kt: 9, seas_ft: [2, 2], sea_period_s: 10, swell_ft: [2, 2], swell_period_s: 10,
    swell_from: 'WNW', comfort: 'comfortable', comfort_for: 'your boat', models_agree: true, ...over});
  const hit = iso => ({date: DATE, entrance: 'Morro Bay entrance', basis: 'offshore', judged: true, hazardous_at: iso, note: 'n'});
  const tz = REGION.timezone;
  const held = withBarHold(day(), hit('2026-09-28T16:00:00Z'), tz);
  assert.deepEqual([held.comfort, held.comfort_held], ['bumpy', 'the bar estimate reads hazardous at 9 am']);
  assert.deepEqual({...held, comfort: 'comfortable', comfort_held: undefined}, {...day(), comfort_held: undefined}, 'measurements, score fields and boat identity untouched');
  assert.equal(withBarHold(day(), hit('2026-09-28T19:00:00Z'), tz).comfort_held, 'the bar estimate reads hazardous at noon');
  assert.equal(withBarHold(day(), hit('2026-09-28T07:00:00Z'), tz).comfort_held, 'the bar estimate reads hazardous at midnight');
  assert.equal(withBarHold(day(), hit('2026-09-28T22:00:00Z'), tz).comfort_held, 'the bar estimate reads hazardous at 3 pm');
  // Not Comfortable, not available, or no hazard: the same object comes back.
  for (const d of [day({comfort: 'bumpy'}), day({comfort: 'rough', advisory: 'Small Craft Advisory'}), day({comfort: 'unknown'}), day({available: false, comfort: 'unknown', reason: 'x'}), day({comfort: 'bumpy', comfort_held: 'forecast run is 20 h old'})]) {
    assert.equal(withBarHold(d, hit('2026-09-28T16:00:00Z'), tz), d);
  }
  const plain = day();
  for (const c of [null, undefined, hit(null)]) assert.equal(withBarHold(plain, c, tz), plain);
  // A long-period hold keeps its reason and gains the bar's, once.
  const lp = day({comfort: 'bumpy', comfort_held: 'long-period swell (2.6 ft at 16 s) at 7 am'});
  const both = withBarHold(lp, hit('2026-09-28T16:00:00Z'), tz);
  assert.equal(both.comfort, 'bumpy');
  assert.equal(both.comfort_held, 'long-period swell (2.6 ft at 16 s) at 7 am; the bar estimate reads hazardous at 9 am');
  assert.equal(withBarHold(both, hit('2026-09-28T16:00:00Z'), tz), both, 'no duplicate text');
  // Through tripConditions: the caller boat reads Comfortable without the bar and Bumpy with it; a partly unknown bar alone never invents a hazard.
  const calm = feed({over: {wave_height: 2, wam: 2, wave_period: 10}});
  const sea = {...HAZ, wave_height: 6, wam: 6};
  const onBar = feed({by: onlyAt([at(DATE, 9)], sea)});
  return Promise.all([run(feed({by: onlyAt([at(DATE, 9)], sea)}), daily({predictions: []}), {boat: BOAT}), run(onBar, daily(), {boat: BOAT}), run(calm, daily(), {boat: BOAT})]).then(([noTide, withTide, quiet]) => {
    assert.equal(noTide.days[0].comfort, windowConditions(onBar, REGION, 'central', DATE, WINDOW, BOAT).comfort, 'an unknown tide leaves the word as it was');
    assert.equal(noTide.bar_checks[0].hazardous_at, null);
    assert.equal(windowConditions(onBar, REGION, 'central', DATE, WINDOW, BOAT).comfort, 'comfortable', 'the caller boat reads Comfortable on this day without the bar');
    assert.deepEqual([withTide.days[0].comfort, withTide.days[0].comfort_held], ['bumpy', 'the bar estimate reads hazardous at 9 am']);
    assert.equal(withTide.bar_checks[0].hazardous_at, '2026-09-28T16:00:00.000Z');
    assert.deepEqual([quiet.days[0].comfort, 'comfort_held' in quiet.days[0], quiet.bar_checks[0].hazardous_at], ['comfortable', false, null]);
    // The held day differs from the direct reading only in the word and its reason.
    const direct = windowConditions(onBar, REGION, 'central', DATE, WINDOW, BOAT);
    assert.deepEqual({...withTide.days[0], comfort: 0, comfort_held: 0}, {...direct, comfort: 0, comfort_held: 0});
  });
});

test('bar_clock_and_advisory_precedence: a Rough advisory wins, an old run reads Unknown with its age, an unusable run reads no forecast', async () => {
  const sea = {...HAZ, wave_height: 6, wam: 6};
  const by = onlyAt([at(DATE, 9)], sea);
  const fresh = await run(feed({by}), daily(), {boat: BOAT});
  assert.deepEqual([fresh.days[0].comfort, fresh.days[0].comfort_held], ['bumpy', 'the bar estimate reads hazardous at 9 am']);
  // An advisory in the window: Rough as measured, no bar line on the day; the check still reports the hour.
  const sca = daily({alerts: [{event: 'Small Craft Advisory', headline: 'synthetic', onset: '2026-09-28T05:00:00-07:00', ends: '2026-09-28T20:00:00-07:00'}]});
  const rough = await run(feed({by}), sca, {boat: BOAT});
  assert.deepEqual([rough.days[0].comfort, rough.days[0].advisory, 'comfort_held' in rough.days[0]], ['rough', 'Small Craft Advisory', false]);
  assert.equal(rough.bar_checks[0].hazardous_at, '2026-09-28T16:00:00.000Z');
  assert.ok(Object.keys(rough).indexOf('advisories') < Object.keys(rough).indexOf('days'), 'advisory keys stay before days');
  // An old run (20 h): the calmer word is held at unknown with the exact age reason, as before; a hazard never calms it.
  const old = await run(feed({by, ageH: 20}), daily(), {boat: BOAT});
  assert.deepEqual([old.days[0].comfort, old.days[0].comfort_held], ['unknown', 'forecast run is 20 h old']);
  assert.equal(old.bar_checks[0].hazardous_at, '2026-09-28T16:00:00.000Z');
  // An unusable run (40 h): no readings, and the bar is unjudged with no hour carried over.
  const gone = await run(feed({by, ageH: 40}), daily(), {boat: BOAT});
  assert.deepEqual([gone.days[0].available, gone.days[0].comfort, gone.days[0].wind_kt, gone.days[0].seas_ft], [false, 'unknown', null, null]);
  assert.deepEqual([gone.bar_checks[0].judged, gone.bar_checks[0].hazardous_at], [false, null]);
  assert.match(gone.bar_checks[0].note, /^The bar was not fully judged/);
  // A date the forecast does not reach: the day is unavailable and still has an unjudged check.
  const far = await run(feed({by}), daily(), {date: '2026-09-30', boat: BOAT, port: 'morro-bay'}, {now: NOW});
  assert.equal(far.days.length, 1);
  assert.equal(far.bar_checks.length, 1);
  assert.equal(far.bar_checks[0].judged, false);
});

const ctx = (intel, dailyFeed, over = {}) => ({env: {}, contact: {id: 'c1', role: 'angler', home_port: 'morro-bay'}, message: {id: 'in1'},
  deps: {feeds: async url => { (ctx.reads[url] = (ctx.reads[url] ?? 0) + 1); return /intelligence\.json$/.test(url) ? intel : /latest\.json$/.test(url) ? dailyFeed : Promise.reject(Error('no feed')); }},
  db: null, language: 'en', settings: advisorSettings({}), now: NOW, ...over});
ctx.reads = {};
const dailyReads = () => Object.entries(ctx.reads).filter(([url]) => /latest\.json$/.test(url)).reduce((n, [, c]) => n + c, 0);
const tool = TOOL_BY_NAME.get('get_conditions');

test('bar_get_conditions_both_branches: the public tool shows the same checks with and without a species, and never calms an already-Bumpy day', async () => {
  const sea = {...HAZ, wave_height: 6, wam: 6};
  const intel = feed({by: onlyAt([at(DATE, 9)], sea)}), d = daily();
  const before = JSON.stringify([intel, d]);
  ctx.reads = {};
  const plain = (await tool.run({port: 'morro-bay', date: DATE}, ctx(intel, d))).result;
  assert.equal(dailyReads(), 1, 'the daily feed is read once');
  // The default boat already reads Bumpy at 6 ft; the check still names the hour and the word is not calmed.
  assert.equal(plain.days[0].comfort, 'bumpy');
  assert.equal(plain.bar_checks[0].hazardous_at, '2026-09-28T16:00:00.000Z');
  assert.match(plain.note, /Use bar_checks to name a hazardous hour or say the bar was not judged; it is not an official bar report\./);
  assert.match(plain.note, /Never say the harbor bar is open or closed/);
  assert.ok(JSON.stringify(plain).length < TOOL_RESULT_MAX, 'inside the tool-result limit');
  assert.doesNotMatch(JSON.stringify(plain.bar_checks), NO_CLAIM);
  const again = (await tool.run({port: 'morro-bay', date: DATE}, ctx(intel, d))).result;
  assert.ok(JSON.stringify(again) === JSON.stringify(plain), 'repeated calls agree');
  assert.ok(JSON.stringify([intel, d]) === before, 'the feeds were not mutated');
  if (sqliteUnavailable) return;
  const {db} = advisorDatabase();
  ctx.reads = {};
  const planned = (await tool.run({port: 'morro-bay', date: DATE, species: 'rockfish'}, ctx(intel, d, {db}))).result;
  assert.equal(dailyReads(), 1, 'the planning branch reads the daily feed once as well');
  assert.ok(planned.planning, 'the planning brief is still there');
  assert.ok(JSON.stringify(planned.bar_checks) === JSON.stringify(plain.bar_checks), 'the same checks with a species');
  assert.equal(planned.days[0].comfort, 'bumpy');
  // A custom window that misses the hazardous hour: no hazard, same word source; a window that holds it, a two-day ask.
  const early = (await tool.run({port: 'morro-bay', date: DATE, start_hour: 6, end_hour: 8}, ctx(intel, d))).result;
  assert.equal(early.bar_checks[0].hazardous_at, null);
  const weekend = (await tool.run({port: 'morro-bay', date: 'this weekend'}, ctx(feed({by: onlyAt([at('2026-10-03', 9)], sea)}), d, {now: Date.parse('2026-10-01T17:00:00Z')}))).result;
  assert.deepEqual(weekend.dates, ['2026-10-03', '2026-10-04']);
  assert.deepEqual(weekend.bar_checks.map(c => c.date), weekend.dates, 'one check per requested date, in order');
  // Other ports: the same tool call returns nothing new.
  const santa = (await tool.run({port: 'santa-barbara', date: DATE}, ctx(feed({region: REGIONS['southern-california'], pointId: 'santa-barbara'}), daily({regionId: 'southern-california'})))).result;
  assert.equal('bar_checks' in santa, false);
});

test('bar_get_conditions_both_branches: the hour is named in local time across the November clock change', async () => {
  // Sat 31 Oct is PDT and Sun 1 Nov is PST: 6 am local is 13:00Z then 14:00Z, and the check carries the real instant.
  const times = Array.from({length: 24 * 6}, (_, i) => epoch('2026-10-30T00:00:00Z') + i * 3600);
  const events = [tide('2026-10-31T13:00:00Z', 'H'), tide('2026-10-31T19:00:00Z', 'L'), tide('2026-11-01T14:00:00Z', 'H'), tide('2026-11-01T20:00:00Z', 'L'), tide('2026-11-02T02:00:00Z', 'H')];
  const now = Date.parse('2026-10-31T15:00:00Z');
  const intel = feed({times, now, over: {...HAZ, wave_height: 6, wam: 6}});
  const out = await run(intel, daily({predictions: events}), {date: 'this weekend', boat: BOAT}, {now});
  assert.deepEqual(out.dates, ['2026-10-31', '2026-11-01']);
  assert.deepEqual(out.bar_checks.map(c => c.hazardous_at), ['2026-10-31T13:00:00.000Z', '2026-11-01T14:00:00.000Z']);
  assert.deepEqual(out.days.map(d => d.comfort_held ?? null).map(s => s && s.replace(/^.*hazardous at /, '')), ['6 am', '6 am']);
  assert.deepEqual(out.days.map(d => d.comfort), ['bumpy', 'bumpy']);
});
