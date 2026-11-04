// Saved-trip assessment: long-period swell is a hazard note beside, never inside, the numeric-limits status.
// Pure synthetic fixtures only (no network, no real records).
import test from 'node:test';
import assert from 'node:assert/strict';
import {assessTrip, alertDecision, alertMessage, windowInstants} from '../server/alert-policy.ts';
import {LONG_PERIOD_SWELL} from '../web/score.ts';

const WAVE = ['ncep_gfswave016', 'ecmwf_wam'], ALL = ['gfs_global', 'ecmwf_ifs025', ...WAVE];
const now = Date.parse('2026-11-01T20:00Z');
const makeRegion = (timezone = 'America/Los_Angeles') => ({id: 'r', timezone, forecast_points: [{id: 'p', name: 'Test point', latitude: 1, longitude: 2}], marine_zones: {coastal: 'TEST'}, harbor: {information_url: 'https://example.test/harbor'}});
const region = makeRegion();
const trip = {point: 'p', date: '2026-11-02', species: 'rockfish', start_hour: 7, end_hour: 11, wind_limit: 15, gust_limit: 20, sea_limit: 6};
const rules = {valid_from: '2026-01-01', valid_through: '2027-12-31', species: {rockfish: {source_ids: [], windows: [{start: '2026-01-01', end: '2027-12-31'}]}}};
const planned = (window, base = trip) => ({...base, plan: JSON.stringify({window})});
const epochAt = (t, h, zone = region.timezone) => windowInstants(t.date, zone, h, h);
// `wave(model, epoch)` may return {height, period} to override the calm 2 ft / 10 s default of that hour.
function intelligence(t = trip, wave = () => null, {reg = region, nowMs = now} = {}) {
  const time = windowInstants(t.date, reg.timezone, 0, 23), models = {}, sources = {};
  for (const id of ALL) {
    const w = time.map(e => (WAVE.includes(id) ? wave(id, e) : null) || {});
    models[id] = {meta: {last_run_initialisation_time: nowMs / 1000, data_end_time: time.at(-1)}, data: [{
      hourly_units: {time: 'unixtime', wind_speed_10m: 'kn', wind_gusts_10m: 'kn', visibility: 'm', weather_code: 'wmo code', wave_height: 'ft', wave_period: 's', wind_wave_height: 'ft'},
      hourly: {time, wind_speed_10m: time.map(() => 4), wind_gusts_10m: time.map(() => 6), visibility: time.map(() => 10000), weather_code: time.map(() => 0),
        wave_height: w.map(x => x.height ?? 2), wave_period: w.map(x => x.period ?? 10), wind_wave_height: time.map(() => .5)}}]};
    sources['model-' + id] = {status: 'ok'};
  }
  return {region_id: 'r', completed_at: new Date(nowMs).toISOString(), forecast: {requested_points: [['p', 1, 2]], models}, sources};
}
const check = (t, intel = intelligence(t), {reg = region, r = rules, adv = [], nowMs = now} = {}) => assessTrip(t, reg, intel, r, adv, nowMs);
const only = (model, epochs, sample) => (m, e) => m === model && epochs.has(e) ? sample : null;
const at = (t, h) => new Set(epochAt(t, h));
const note = (h, height = '2.5', period = '15') => `Long-period swell (${height} ft at ${period} s) at ${h}; surge and entrance conditions need a separate check.`;

test('long_period_threshold_and_pairing', () => {
  assert.deepEqual(LONG_PERIOD_SWELL, {height: 2.5, period: 15});
  const calm = check(trip);
  assert.equal(calm.status, 'within limits');
  assert.ok(!('hazards' in calm), 'quiet assessment keeps its old shape');
  for (const model of WAVE) {
    const hit = check(trip, intelligence(trip, only(model, at(trip, 9), {height: 2.5, period: 15})));
    assert.deepEqual(hit.hazards, [note('9 am')], model);
    assert.equal(hit.status, 'within limits', 'a hazard note does not turn the status');
    assert.deepEqual(hit.issues, []);
    for (const miss of [{height: 2.4999, period: 15}, {height: 2.5, period: 14.999}, {height: 20, period: 14}, {height: 1, period: 25}])
      assert.ok(!('hazards' in check(trip, intelligence(trip, only(model, at(trip, 9), miss)))), model + JSON.stringify(miss));
  }
  // height from one model never combines with another model's period, and maxima of different hours never combine
  const cross = (m, e) => at(trip, 9).has(e) ? (m === 'ncep_gfswave016' ? {height: 4, period: 8} : {height: 1, period: 18}) : null;
  assert.ok(!('hazards' in check(trip, intelligence(trip, cross))));
  const hours = (m, e) => m !== 'ecmwf_wam' ? null : at(trip, 8).has(e) ? {height: 4, period: 8} : at(trip, 9).has(e) ? {height: 1, period: 18} : null;
  assert.ok(!('hazards' in check(trip, intelligence(trip, hours))));
  // display rounds, decision uses the raw value
  assert.deepEqual(check(trip, intelligence(trip, only('ecmwf_wam', at(trip, 9), {height: 3.04, period: 15.4}))).hazards, [note('9 am', '3', '15')]);
  assert.deepEqual(check(trip, intelligence(trip, only('ecmwf_wam', at(trip, 9), {height: 2.5, period: 15.4}))).hazards, [note('9 am', '2.5', '15')]);
  // invalid samples keep the existing issues and fabricate no hit
  for (const bad of [{period: -16, height: 3}, {period: 0, height: 3}, {period: NaN, height: 3}, {period: 16, height: NaN}, {period: 16, height: -3}]) {
    const a = check(trip, intelligence(trip, only('ecmwf_wam', at(trip, 9), bad)));
    assert.ok(!('hazards' in a), JSON.stringify(bad));
  }
  const bare = intelligence(trip, only('ecmwf_wam', at(trip, 9), {height: 3, period: 16}));
  bare.forecast.models.ecmwf_wam.data[0].hourly_units.wave_height = 'm';
  const wrongUnit = check(trip, bare);
  assert.ok(!('hazards' in wrongUnit)); assert.equal(wrongUnit.status, 'unverified'); assert.ok(wrongUnit.issues.includes('Required sea sample missing'));
  const badPeriod = check(trip, intelligence(trip, only('ecmwf_wam', at(trip, 9), {height: 3, period: -16})));
  assert.equal(badPeriod.status, 'unverified'); assert.ok(badPeriod.issues.includes('Combined wave period unavailable or invalid'));
  // saved limits and boat factors never scale the physical threshold
  const swell = intelligence(trip, only('ncep_gfswave016', at(trip, 9), {height: 2.5, period: 15}));
  for (const t of [{...trip, sea_limit: 20}, {...trip, sea_limit: 2.5}, {...trip, boat_sea: .45}, {...trip, boat_sea: 2.6, sea_limit: 30}])
    assert.deepEqual(check(t, swell).hazards, [note('9 am')]);
  assert.equal(check({...trip, sea_limit: 2}, swell).status, 'above limits');
  assert.deepEqual(check({...trip, sea_limit: 2}, swell).hazards, [note('9 am')]);
});

test('long_period_earliest_and_window', () => {
  const swell = (hours, sample = {height: 3, period: 16}) => (m, e) => hours.some(h => at(trip, h).has(e)) && m === 'ncep_gfswave016' ? sample : null;
  const intel = intelligence(trip, swell([10, 8, 9]));
  const before = JSON.stringify(intel);
  const reversed = JSON.parse(before);
  for (const m of WAVE) { const h = reversed.forecast.models[m].data[0].hourly; for (const k of Object.keys(h)) h[k].reverse(); }
  assert.deepEqual(check(trip, intel).hazards, [note('8 am', '3', '16')]);
  assert.deepEqual(check(trip, reversed).hazards, [note('8 am', '3', '16')], 'feed order does not matter');
  assert.equal(JSON.stringify(intel), before, 'inputs are not mutated');
  // same hour: greater height, then greater period, from either model
  const tie = (a, b) => (m, e) => at(trip, 9).has(e) ? (m === 'ncep_gfswave016' ? a : b) : null;
  assert.deepEqual(check(trip, intelligence(trip, tie({height: 2.6, period: 17}, {height: 3.1, period: 15}))).hazards, [note('9 am', '3.1', '15')]);
  assert.deepEqual(check(trip, intelligence(trip, tie({height: 3, period: 15}, {height: 3, period: 18}))).hazards, [note('9 am', '3', '18')]);
  assert.deepEqual(check(trip, intelligence(trip, tie({height: 3, period: 18}, {height: 3, period: 15}))).hazards, [note('9 am', '3', '18')]);
  // inclusive window boundaries; hours outside never name a note
  assert.deepEqual(check(trip, intelligence(trip, swell([7]))).hazards, [note('7 am', '3', '16')]);
  assert.deepEqual(check(trip, intelligence(trip, swell([11]))).hazards, [note('11 am', '3', '16')]);
  for (const h of [6, 12]) assert.ok(!('hazards' in check(trip, intelligence(trip, swell([h])))), 'hour ' + h);
  // noon, midnight and afternoon words
  const noon = {...trip, start_hour: 11, end_hour: 13};
  assert.deepEqual(check(noon, intelligence(noon, (m, e) => m === 'ecmwf_wam' && at(noon, 12).has(e) ? {height: 3, period: 16} : null)).hazards, [note('noon', '3', '16')]);
  const night = {...trip, start_hour: 0, end_hour: 2};
  assert.deepEqual(check(night, intelligence(night, (m, e) => m === 'ecmwf_wam' && at(night, 0).has(e) ? {height: 3, period: 16} : null)).hazards, [note('midnight', '3', '16')]);
  const pm = {...trip, start_hour: 13, end_hour: 15};
  assert.deepEqual(check(pm, intelligence(pm, (m, e) => m === 'ecmwf_wam' && at(pm, 13).has(e) ? {height: 3, period: 16} : null)).hazards, [note('1 pm', '3', '16')]);
  // another zone reads its own local hour
  const east = makeRegion('America/New_York'), eastTrip = {...trip, start_hour: 9, end_hour: 12};
  const eastHit = (m, e) => m === 'ecmwf_wam' && new Set(windowInstants(eastTrip.date, east.timezone, 10, 10)).has(e) ? {height: 3, period: 16} : null;
  assert.deepEqual(check(eastTrip, intelligence(eastTrip, eastHit, {reg: east}), {reg: east}).hazards, [note('10 am', '3', '16')]);
  // planned departure and return extend the window; fishing-hours-only trips ignore them
  const both = planned({depart: '05:00', return_by: '14:00'});
  assert.deepEqual(check(both, intelligence(both, swell([5]))).hazards, [note('5 am', '3', '16')]);
  assert.deepEqual(check(both, intelligence(both, swell([14]))).hazards, [note('2 pm', '3', '16')]);
  assert.ok(!('hazards' in check(trip, intelligence(both, swell([5, 14])))), 'no extension without a plan window');
  assert.ok(!('hazards' in check(both, intelligence(both, swell([4, 15])))));
  // fall-back day repeats 01:00; the earlier real epoch is chosen. Spring-forward has no 02:00 to invent.
  const fall = {...trip, date: '2026-11-01', start_hour: 0, end_hour: 3};
  const [first, second] = [Date.parse('2026-11-01T08:00Z') / 1000, Date.parse('2026-11-01T09:00Z') / 1000];
  assert.deepEqual(windowInstants(fall.date, region.timezone, 1, 1), [first, second]);
  assert.deepEqual(check(fall, intelligence(fall, (m, e) => m === 'ecmwf_wam' && e === second ? {height: 3, period: 16} : null)).hazards, [note('1 am', '3', '16')]);
  assert.deepEqual(check(fall, intelligence(fall, (m, e) => m === 'ecmwf_wam' && (e === first || e === second) ? {height: e === first ? 2.6 : 4, period: 16} : null)).hazards, [note('1 am', '2.6', '16')]);
  const spring = {...trip, date: '2027-03-14', start_hour: 0, end_hour: 4};
  const springHit = (m, e) => m === 'ecmwf_wam' ? {height: 3, period: 16} : null;
  const springHours = windowInstants(spring.date, region.timezone, 0, 4);
  assert.equal(springHours.length, 4, 'one hour of the local day does not exist');
  assert.deepEqual(check(spring, intelligence(spring, springHit)).hazards, [note('midnight', '3', '16')]);
  const lateSpring = (m, e) => m === 'ecmwf_wam' && e >= springHours[2] ? {height: 3, period: 16} : null;
  assert.deepEqual(check(spring, intelligence(spring, lateSpring)).hazards, [note('3 am', '3', '16')]);
});

test('long_period_evidence_precedence', () => {
  const hit = {height: 3, period: 16}, wave = (model) => only(model, at(trip, 9), hit);
  const broken = {
    'source not ok': i => { i.sources['model-ecmwf_wam'] = {status: 'stale'}; },
    'model error': i => { i.forecast.models.ecmwf_wam.error = 'boom'; },
    'run missing': i => { delete i.forecast.models.ecmwf_wam.meta.last_run_initialisation_time; },
    'run over 36 h old': i => { i.forecast.models.ecmwf_wam.meta.last_run_initialisation_time = now / 1000 - 36 * 3600 - 1; },
    'run in the future': i => { i.forecast.models.ecmwf_wam.meta.last_run_initialisation_time = now / 1000 + 3601; },
    'horizon missing': i => { delete i.forecast.models.ecmwf_wam.meta.data_end_time; },
    'horizon before the hour': i => { i.forecast.models.ecmwf_wam.meta.data_end_time = epochAt(trip, 8)[0]; },
  };
  for (const [name, mutate] of Object.entries(broken)) {
    const i = intelligence(trip, wave('ecmwf_wam')); mutate(i);
    const a = check(trip, i);
    assert.ok(!('hazards' in a), name + ': stale or unusable cached numbers create no hazard');
    assert.equal(a.status, 'unverified', name);
    // another model that is fine still names the hour, with the first model's existing issue untouched
    const j = intelligence(trip, (m, e) => at(trip, 9).has(e) ? hit : null); mutate(j);
    const b = check(trip, j);
    assert.deepEqual(b.hazards, [note('9 am', '3', '16')], name);
    assert.equal(b.status, 'unverified', name);
    assert.deepEqual(b.issues, a.issues, name + ': the hazard adds no issue and removes none');
  }
  // an exact-end horizon still counts the hour (later hours raise the existing issue)
  const exact = intelligence(trip, wave('ecmwf_wam')); exact.forecast.models.ecmwf_wam.meta.data_end_time = epochAt(trip, 9)[0];
  const e = check(trip, exact);
  assert.deepEqual(e.hazards, [note('9 am', '3', '16')]); assert.ok(e.issues.includes('ecmwf_wam published horizon does not cover the full window'));
  // unrelated missing rules, advisories and an applicable advisory keep their own wording and add no hazard of their own
  const swell = intelligence(trip, wave('ncep_gfswave016')), plain = check(trip, intelligence(trip));
  const noRules = check(trip, swell, {r: null}), noAdv = check(trip, swell, {adv: null});
  assert.deepEqual(noRules.hazards, [note('9 am', '3', '16')]); assert.equal(noRules.legal, 'unverified'); assert.equal(noRules.status, 'unverified');
  assert.deepEqual(noAdv.hazards, [note('9 am', '3', '16')]); assert.deepEqual(noAdv.issues, ['Marine advisories unavailable']);
  assert.deepEqual(check(trip, swell, {adv: [{}]}).issues, ['Applicable marine advisory']);
  // adding the hazard changes nothing else in the assessment
  const withHazard = check(trip, swell), {hazards, ...rest} = withHazard;
  assert.deepEqual(rest.values, {wind: 4, gust: 6, sea: 3, chop: .5});
  assert.equal(JSON.stringify({...rest, values: plain.values}), JSON.stringify(plain));
  assert.ok(Array.isArray(hazards) && hazards.length === 1);
  // above limits stays above; an old calm assessment stays the same quiet shape
  const rough = intelligence(trip, (m, e) => at(trip, 9).has(e) ? {height: 9, period: 16} : null);
  const above = check(trip, rough); assert.equal(above.status, 'above limits'); assert.deepEqual(above.hazards, [note('9 am', '9', '16')]);
  assert.ok(!('hazards' in plain));
  const early = assessTrip(trip, region, {...swell, region_id: 'x'}, rules, [], now);
  assert.ok(!('hazards' in early) && early.status === 'unverified', 'early unavailable return carries no hazard');
});

test('long_period_decision_legacy', () => {
  const a = check(trip), h = check(trip, intelligence(trip, only('ecmwf_wam', at(trip, 9), {height: 2.5, period: 15})));
  assert.equal(alertDecision(a, {...a, hazards: []}), null, 'absent and empty hazards are equal');
  assert.equal(alertDecision({...a, hazards: []}, a), null);
  assert.equal(alertDecision(a, h), 'update', 'appearance sends below every numeric delta');
  assert.equal(alertDecision(h, a), 'update', 'clearance sends');
  assert.equal(alertDecision(h, {...h, checked_at: '2026-11-01T21:00:00.000Z'}), null, 'time-only change is quiet');
  assert.equal(alertDecision(h, JSON.parse(JSON.stringify(h))), null, 'identical note suppresses the repeat');
  const earlier = check(trip, intelligence(trip, only('ecmwf_wam', at(trip, 8), {height: 2.5, period: 15})));
  assert.equal(alertDecision(h, earlier), 'update', 'earlier hour');
  const stronger = check(trip, intelligence(trip, only('ecmwf_wam', at(trip, 9), {height: 2.6, period: 15})));
  assert.equal(alertDecision(h, stronger), 'update', 'displayed severity');
  // priorities: missed-final, final, initial, retraction stay above the hazard rule
  assert.equal(alertDecision(a, h, {missed: true}), 'missed-final');
  assert.equal(alertDecision(a, h, {final: true}), 'final');
  assert.equal(alertDecision(null, h), 'initial');
  const bad = {...h, status: 'above limits'};
  assert.equal(alertDecision(h, bad), 'retraction', 'a status retraction wins over an unchanged note');
  assert.equal(alertDecision(a, bad), 'retraction');
  assert.equal(alertDecision({...a, status: 'above limits'}, {...h, status: 'above limits'}), 'update');
  // a hazard alone never produces a retraction or an unverified status
  assert.notEqual(alertDecision(a, h), 'retraction'); assert.equal(h.status, 'within limits');
});

test('long_period_message_plain', () => {
  const calm = check(trip), h = check(trip, intelligence(trip, only('ecmwf_wam', at(trip, 9), {height: 3.06, period: 15.2})));
  const plain = alertMessage(trip, region, calm, 'update'), msg = alertMessage(trip, region, h, 'update');
  assert.equal(plain.includes('Hazard note'), false);
  assert.equal(alertMessage(trip, region, {...calm, hazards: []}, 'update'), plain, 'empty hazards leave the message byte-identical');
  const line = 'Hazard note: ' + note('9 am', '3.1', '15');
  const lines = msg.split('\n');
  assert.ok(lines[2].startsWith('Wind ')); assert.equal(lines[3], line, 'the note follows the wind/seas/chop line');
  assert.equal(msg.replace(line + '\n', ''), alertMessage(trip, region, {...h, hazards: undefined}, 'update'), 'removing the hazard line leaves the quiet message');
  assert.ok(msg.includes('Within your numerical preferences; this does not evaluate route, entrance or catch success.'));
  assert.ok(msg.includes('https://example.test/harbor') && msg.includes('Rules: reviewed season.'));
  assert.ok(!/missing|unavailable data|clear to|safe/i.test(line.replace('surge and entrance conditions need a separate check', '')), 'plain wording only');
  // boat line and leg labels keep their place after the note
  const boat = {...trip, boat_sea: 1, boat_name: 'Test boat', ...planned({depart: '05:00'})};
  const bm = alertMessage(boat, region, {...h, legs: {depart: true, return: false}}, 'initial').split('\n');
  assert.equal(bm[3], line); assert.ok(bm[4].startsWith('Boat: Test boat')); assert.ok(bm.at(-1).startsWith('Departure at 05:00: above saved limits'));
  assert.ok(alertMessage(trip, region, {...h, status: 'above limits'}, 'retraction').startsWith('No longer within saved limits'));
  // the hazard survives the 1600-character push truncation even with long names and issue lists
  const long = {...h, issues: Array.from({length: 40}, (_, i) => 'Issue number ' + i + ' ' + 'x'.repeat(40))};
  const longRegion = makeRegion(); longRegion.forecast_points[0].name = 'N'.repeat(300);
  const body = alertMessage(boat, longRegion, long, 'update');
  assert.ok(body.length > 1600); assert.ok(body.slice(0, 1600).includes(line));
});
