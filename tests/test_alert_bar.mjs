// SC0922-02: a saved-trip assessment names the earliest hour the shared harbour-bar estimate reads hazardous, or says the bar was not judged.
// The note sits in Assessment.hazards beside, never inside, the numeric status. Pure synthetic fixtures only (no network, no real records).
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {assessTrip, alertDecision, alertMessage, windowInstants} from '../server/alert-policy.ts';
import {BAR_CHECK, barHours, entranceFor} from '../packages/coast/src/bar-conditions.ts';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
const REGIONS = Object.fromEntries(['morro-bay', 'humboldt-bay-cape-mendocino', 'fort-bragg-point-arena', 'crescent-city', 'monterey-point-sur'].map(id => [id, read(`../regions/${id}/region.json`)]));
const MORRO = REGIONS['morro-bay'], ZONE = MORRO.timezone, HOUR = 3600000;
const DAY = '2026-11-12', NOW = Date.parse('2026-11-11T20:00:00Z');
const rules = {valid_from: '2026-01-01', valid_through: '2027-12-31', species: Object.fromEntries(['lingcod', 'rockfish'].map(id => [id, {source_ids: [], windows: [{start: '2026-01-01', end: '2027-12-31'}]}]))};
const tripFor = (region, extra = {}) => ({point: region.forecast_points[0].id, date: DAY, species: 'reef', start_hour: 7, end_hour: 13, wind_limit: 30, gust_limit: 40, sea_limit: 20, ...extra});
const formats = new Map(); // one formatter per zone: building one per call is what makes a fixture this size slow
const localHour = (e, zone = ZONE) => {
  if (!formats.has(zone)) formats.set(zone, new Intl.DateTimeFormat('en-US', {timeZone: zone, hour: '2-digit', hourCycle: 'h23'}));
  return Number(formats.get(zone).format(new Date(e * 1000)));
};
const words = h => h === 0 ? 'midnight' : h === 12 ? 'noon' : h < 12 ? h + ' am' : (h - 12) + ' pm';
const LEAD = n => `Regional ${n}: the offshore bar estimate reads hazardous at `;
const TAIL = ` this does not establish the trip's launch or crossing. ${BAR_CHECK}`;
const NOT_JUDGED = n => `Regional ${n}: bar not judged for the complete saved window; this does not establish the trip's launch or crossing. ${BAR_CHECK}`;
const PARTIAL = ' The bar was not judged for the complete saved window.', NOWIND = ' Wind against the ebb was not judged.';

// A complete synthetic regional feed. `sea(hour, epoch)` -> [height ft, period s] for GFS-Wave (default 2 ft / 10 s); `wind(hour, epoch)` -> [kn, from deg] for GFS (default 4 kn from 90).
function feed(region, {day = DAY, nowMs = NOW, sea = () => null, wind = () => null, reverse = false} = {}) {
  const time = windowInstants(day, region.timezone, 0, 23), last = time.at(-1);
  if (reverse) time.reverse();
  const col = fn => time.map(fn), hr = e => localHour(e, region.timezone);
  const units = {time: 'unixtime', wind_speed_10m: 'kn', wind_direction_10m: '°', wind_gusts_10m: 'kn', visibility: 'm', weather_code: 'wmo code', wave_height: 'ft', wave_period: 's', wind_wave_height: 'ft', swell_wave_height: 'ft', swell_wave_period: 's'};
  const windy = {wind_speed_10m: col(e => (wind(hr(e), e) || [4, 90])[0]), wind_direction_10m: col(e => (wind(hr(e), e) || [4, 90])[1]), wind_gusts_10m: col(() => 6), visibility: col(() => 10000), weather_code: col(() => 0)};
  const waves = {wave_height: col(e => (sea(hr(e), e) || [2, 10])[0]), wave_period: col(e => (sea(hr(e), e) || [2, 10])[1]), wind_wave_height: col(() => .5), swell_wave_height: col(() => 1), swell_wave_period: col(() => 8)};
  const models = {}, sources = {};
  for (const id of ['gfs_global', 'ecmwf_ifs025', 'ncep_gfswave016', 'ecmwf_wam']) {
    const hourly = {time, ...(id.startsWith('gfs_g') || id.startsWith('ecmwf_i') ? windy : id === 'ecmwf_wam' ? {wave_height: col(() => 2), wave_period: col(() => 10)} : waves)};
    models[id] = {meta: {last_run_initialisation_time: nowMs / 1000, data_end_time: last}, data: region.forecast_points.map(() => ({hourly_units: {...units}, hourly: JSON.parse(JSON.stringify(hourly))}))};
    sources['model-' + id] = {status: 'ok'};
  }
  return {region_id: region.id, completed_at: new Date(nowMs).toISOString(), forecast: {requested_points: region.forecast_points.map(p => [p.id, p.latitude, p.longitude]), models}, sources};
}
const dailyFeed = events => ({sources: {tides: {status: 'ok', data: {predictions: events.map(([time, type, height_ft]) => ({time, type, height_ft: height_ft ?? (type === 'H' ? 5 : .5)}))}}}});
// High 06:00 and low 14:00 PST on DAY: mid-ebb is 08:00 to 12:00, flood before 06:00 and after 14:00.
const EVENTS = [['2026-11-11T22:00:00-08:00', 'L'], [DAY + 'T06:00:00-08:00', 'H'], [DAY + 'T14:00:00-08:00', 'L'], [DAY + 'T22:00:00-08:00', 'H'], ['2026-11-13T06:00:00-08:00', 'L']];
const TIDE = dailyFeed(EVENTS);
// Alternating highs and lows every 6 h from 24 h before `nowMs`, for the DST days.
const rolling = nowMs => dailyFeed(Array.from({length: 14}, (_, i) => [new Date(nowMs - 24 * HOUR + i * 6 * HOUR).toISOString(), i % 2 ? 'L' : 'H']));
// 6 ft at 10 s through the 07:00-13:00 window: with the tide above, mid-ebb (08:00-12:00) reads hazardous and 07:00 only a caution.
const mid = hour => hour >= 7 && hour <= 13 ? [6, 10] : null;
const assess = (trip, intel, daily = TIDE, {region = MORRO, nowMs = NOW} = {}) => assessTrip(trip, region, intel, rules, [], nowMs, daily);
const drop = (f, model, epoch) => { // remove one hourly row from every point of a model
  for (const d of f.forecast.models[model].data) { const i = d.hourly.time.indexOf(epoch); for (const k of Object.keys(d.hourly)) d.hourly[k].splice(i, 1); }
};
const epochAtHour = (day, zone, h) => windowInstants(day, zone, h, h);
const forbidden = text => /\b(open|closed|safe|clear|passable)\b/i.test(text);

test('bar_hazard_earliest_extended_window: the earliest hazardous hour is named, from rows in any order, over the full saved window', () => {
  const trip = tripFor(MORRO);
  const a = assess(trip, feed(MORRO, {sea: mid}));
  assert.deepEqual(a.hazards, [LEAD('Morro Bay entrance') + '8 am;' + TAIL]);
  assert.equal(a.status, 'within limits'); assert.deepEqual(a.issues, []);
  // the shared estimate read directly: the first Hazardous hour of the same synthetic hours
  const direct = barHours({hours: windowInstants(DAY, ZONE, 7, 13).map(e => ({at: new Date(e * 1000).toISOString(), windKnots: 4, gustKnots: null, windDirectionDeg: 90, waveFt: 6, wavePeriodS: 10})),
    site: undefined, entrance: entranceFor('morro-bay', 'morro-bay'), tideEvents: EVENTS.map(([at, type]) => ({at, type, heightFt: 1}))});
  const first = direct.filter(h => h.band === 'Hazardous').map(h => Date.parse(h.at))[0];
  assert.equal(words(localHour(first / 1000)), '8 am');
  assert.equal(direct[0].band, 'Caution', 'hour 7 is only a caution and is not named');
  assert.deepEqual(assess(trip, feed(MORRO, {sea: mid, reverse: true})).hazards, a.hazards, 'row order does not matter');
  // the boundary hour counts: a hazard at 13:00 only is named
  assert.deepEqual(assess(trip, feed(MORRO, {sea: h => h === 13 ? [10, 10] : null})).hazards, [LEAD('Morro Bay entrance') + '1 pm;' + TAIL]);
  // hazards outside the window are not named, and the quiet shape is kept
  const outside = assess(trip, feed(MORRO, {sea: h => h === 5 || h === 16 ? [10, 10] : null}));
  assert.equal('hazards' in outside, false);
  // departure and return extensions are part of the window
  const planned = {...trip, plan: JSON.stringify({window: {depart: '05:00', return_by: '16:00'}})};
  assert.deepEqual(assess(planned, feed(MORRO, {sea: h => h === 5 ? [10, 10] : null})).hazards, [LEAD('Morro Bay entrance') + '5 am;' + TAIL]);
  assert.deepEqual(assess(planned, feed(MORRO, {sea: h => h === 16 ? [10, 10] : null})).hazards, [LEAD('Morro Bay entrance') + '4 pm;' + TAIL]);
  assert.equal('hazards' in assess(trip, feed(MORRO, {sea: h => h === 16 ? [10, 10] : null})), false, 'the same return hour is outside a trip without that plan');
  // a hazard at 8 am and another at 10 am: the earlier one
  assert.match(assess(trip, feed(MORRO, {sea: h => h === 10 || h === 8 ? [10, 10] : null})).hazards[0], /hazardous at 8 am;/);
});

test('bar_hazard_earliest_extended_window: repeated fall-back hours stay distinct and spring-forward invents no 02:00', () => {
  const fall = '2026-11-01', fallNow = Date.parse('2026-10-31T19:00:00Z'), fallTrip = tripFor(MORRO, {date: fall, start_hour: 0, end_hour: 3});
  assert.equal(windowInstants(fall, ZONE, 0, 3).length, 5, 'two 01:00 hours');
  assert.equal('hazards' in assess(fallTrip, feed(MORRO, {day: fall, nowMs: fallNow}), rolling(fallNow), {nowMs: fallNow}), false, 'a complete feed reads no note');
  const second = windowInstants(fall, ZONE, 1, 1)[1], missing = feed(MORRO, {day: fall, nowMs: fallNow});
  drop(missing, 'ncep_gfswave016', second);
  assert.equal(assess(fallTrip, missing, rolling(fallNow), {nowMs: fallNow}).hazards[0], NOT_JUDGED('Morro Bay entrance'), 'the second 01:00 alone is missing');
  const spring = '2026-03-08', springNow = Date.parse('2026-03-07T20:00:00Z'), springTrip = tripFor(MORRO, {date: spring, start_hour: 1, end_hour: 3});
  assert.deepEqual(windowInstants(spring, ZONE, 1, 3).map(e => localHour(e)), [1, 3], 'no 02:00 exists');
  assert.equal('hazards' in assess(springTrip, feed(MORRO, {day: spring, nowMs: springNow}), rolling(springNow), {nowMs: springNow}), false, 'no invented 02:00 hour is left unjudged');
  assert.match(assess(springTrip, feed(MORRO, {day: spring, nowMs: springNow, sea: h => h === 3 ? [10, 10] : null}), rolling(springNow), {nowMs: springNow}).hazards[0], /hazardous at 3 am;/);
});

test('bar_inputs_missing_are_notes_not_issues: missing tide inputs say the bar was not judged and change nothing else', () => {
  const trip = tripFor(MORRO), f = () => feed(MORRO), base = assess(trip, f());
  assert.equal('hazards' in base, false, 'a complete calm window has no bar note');
  const note = [NOT_JUDGED('Morro Bay entrance')];
  const tides = (mutate) => { const d = dailyFeed(EVENTS); mutate(d.sources.tides); return d; };
  const cases = {
    'no daily feed': null, 'empty daily feed': {}, 'tide source not ok': tides(t => { t.status = 'error'; }),
    'predictions not an array': tides(t => { t.data.predictions = {}; }), 'no predictions at all': dailyFeed([]),
    'one event, no bracket': dailyFeed([[DAY + 'T06:00:00-08:00', 'H']]),
    'offsetless times are not read as local': dailyFeed(EVENTS.map(([t, type]) => [t.slice(0, 19), type])),
    'invalid times': dailyFeed(EVENTS.map(([, type]) => ['not a time', type])),
    'conflicting H and L at the bracket': dailyFeed([...EVENTS, [DAY + 'T06:00:00-08:00', 'L']]),
    'two highs in a row': dailyFeed([['2026-11-11T22:00:00-08:00', 'H'], [DAY + 'T06:00:00-08:00', 'H'], [DAY + 'T14:00:00-08:00', 'H']]),
  };
  for (const [name, daily] of Object.entries(cases)) {
    const a = assess(trip, f(), daily);
    assert.deepEqual(a.hazards, note, name);
    const {hazards, ...rest} = a; assert.deepEqual(rest, base, name + ': status, issues, values, legal and runs are unchanged');
    assert.equal(a.issues.some(i => /bar/i.test(i)), false, name);
  }
  // negative tide heights are valid predictions
  const negative = assess(trip, f(), dailyFeed(EVENTS.map(([t, type]) => [t, type, type === 'L' ? -.8 : 4.2])));
  assert.equal('hazards' in negative, false);
});

test('bar_inputs_missing_are_notes_not_issues: missing, stale or mismatched forecast inputs are notes, and existing issues keep their wording', () => {
  const trip = tripFor(MORRO), at = h => epochAtHour(DAY, ZONE, h)[0], f = () => feed(MORRO);
  const wave = f => f.forecast.models.ncep_gfswave016, last = f => f.forecast.models.gfs_global.data[0].hourly.time.at(-1);
  const cases = {
    'wave height in metres': f => { for (const d of wave(f).data) d.hourly_units.wave_height = 'm'; },
    'zero wave period': f => { for (const d of wave(f).data) d.hourly.wave_period = d.hourly.wave_period.map(() => 0); },
    'negative wave height': f => { for (const d of wave(f).data) d.hourly.wave_height = d.hourly.wave_height.map(() => -1); },
    'one GFS-Wave hour missing': f => drop(f, 'ncep_gfswave016', at(10)),
    'published horizon ends mid-window': f => { wave(f).meta.data_end_time = at(9); },
    'wave source failed': f => { f.sources['model-ncep_gfswave016'].status = 'error'; },
    'wave model error': f => { wave(f).error = 'bad'; },
    'wave run 37 h old': f => { wave(f).meta.last_run_initialisation_time = NOW / 1000 - 37 * 3600; },
    'wave run in the future': f => { wave(f).meta.last_run_initialisation_time = NOW / 1000 + 2 * 3600; },
    'feed 4 h old': f => { f.completed_at = new Date(NOW - 4 * HOUR).toISOString(); },
    'feed from the future': f => { f.completed_at = new Date(NOW + 2 * HOUR).toISOString(); },
    'feed time invalid': f => { f.completed_at = 'garbage'; },
  };
  for (const [name, mutate] of Object.entries(cases)) {
    const f1 = f(); mutate(f1);
    const a = assess(trip, f1), ok = a.hazards ?? [];
    assert.equal(ok.length, 1, name); assert.ok(ok[0].startsWith(NOT_JUDGED('Morro Bay entrance')), name + ': ' + ok[0]);
    assert.equal(a.issues.some(i => /bar/i.test(i)), false, name + ': never an issue');
  }
  // the feed's own identity checks: the existing early returns keep status and issues, and gain the note
  const wrongPoints = f(); wrongPoints.forecast.requested_points = [...wrongPoints.forecast.requested_points].reverse();
  const e1 = assess(trip, wrongPoints); assert.equal(e1.status, 'unverified'); assert.deepEqual(e1.issues, ['Forecast locations do not match this regional release']); assert.deepEqual(e1.hazards, note1());
  const wrongRegion = f(); wrongRegion.region_id = 'elsewhere';
  const e2 = assess(trip, wrongRegion); assert.deepEqual(e2.issues, ['Regional forecast unavailable']); assert.deepEqual(e2.hazards, note1()); assert.deepEqual(e2.runs, {});
  const e3 = assess({...trip, point: 'nowhere'}, f()); assert.deepEqual(e3.issues, ['Regional forecast unavailable']); assert.deepEqual(e3.hazards, note1());
  const e4 = assess(trip, null); assert.deepEqual(e4.issues, ['Regional forecast unavailable']); assert.deepEqual(e4.hazards, note1());
  // nothing at all can be read from a feed that fails its identity checks, so wind against the ebb is unjudged too
  function note1() { return [NOT_JUDGED('Morro Bay entrance') + NOWIND]; }
  // a window with no real hour is not judged either
  assert.deepEqual(assess({...trip, date: 'not-a-date'}, f()).hazards, note1());
});

test('bar_inputs_missing_are_notes_not_issues: a known hazard survives another missing hour or driver', () => {
  const trip = tripFor(MORRO), haz = LEAD('Morro Bay entrance') + '8 am;' + TAIL;
  const missingHour = feed(MORRO, {sea: mid}); drop(missingHour, 'ncep_gfswave016', epochAtHour(DAY, ZONE, 10)[0]);
  assert.deepEqual(assess(trip, missingHour).hazards, [haz + PARTIAL]);
  const noWindDirection = feed(MORRO, {sea: mid}); for (const d of noWindDirection.forecast.models.gfs_global.data) d.hourly_units.wind_direction_10m = 'rad';
  const w = assess(trip, noWindDirection);
  assert.deepEqual(w.hazards, [haz + NOWIND], 'unknown GFS wind does not suppress the GFS-Wave hazard, and is recorded');
  // no tide phase: a swell that is hazardous on any tide is still named
  const noTide = assess(trip, feed(MORRO, {sea: () => [10, 10]}), null);
  assert.deepEqual(noTide.hazards, [LEAD('Morro Bay entrance') + '7 am;' + TAIL + PARTIAL]);
  // the wave model fails but its hours would have read hazardous: not judged, not hazardous
  const failed = feed(MORRO, {sea: mid}); failed.sources['model-ncep_gfswave016'].status = 'error';
  assert.ok(assess(trip, failed).hazards[0].startsWith(NOT_JUDGED('Morro Bay entrance')));
});

test('bar_region_and_profile_scope: only the four regulated harbours get a note, whatever the saved profile', () => {
  const names = {'morro-bay': 'Morro Bay entrance', 'humboldt-bay-cape-mendocino': 'Humboldt Bay entrance', 'fort-bragg-point-arena': 'Noyo River entrance', 'crescent-city': 'Crescent City Harbor entrance'};
  for (const [id, name] of Object.entries(names)) {
    const region = REGIONS[id], trip = tripFor(region), a = assess(trip, feed(region, {sea: () => [10, 10]}), rolling(NOW), {region});
    assert.equal(a.hazards.length, 1, id);
    assert.equal(a.hazards[0], LEAD(name) + '7 am;' + TAIL + (id === 'morro-bay' ? '' : NOWIND), id + ': only Morro Bay has an entrance bearing');
    assert.equal(a.issues.length, 0, id); assert.equal(a.status, 'within limits', id);
    // a calm complete window: Morro Bay is quiet; the others cannot judge wind against the ebb and say so
    const calm = assess(trip, feed(region), rolling(NOW), {region});
    if (id === 'morro-bay') assert.equal('hazards' in calm, false);
    else assert.deepEqual(calm.hazards, [NOT_JUDGED(name) + NOWIND], id);
  }
  const other = REGIONS['monterey-point-sur'], quiet = assess(tripFor(other), feed(other, {sea: () => [10, 10]}), rolling(NOW), {region: other});
  assert.equal('hazards' in quiet, false, 'a region without a regulated bar keeps the old assessment shape');
  assert.equal('hazards' in assess(tripFor(other), null, null, {region: other}), false, 'including its early return');
  // the saved profile is not stored and does not change which trips have a bar or what the note says
  const expected = assess(tripFor(MORRO), feed(MORRO, {sea: mid})).hazards;
  for (const extra of [{boat_sea: null, boat_name: null}, {boat_sea: .5, boat_name: 'Small skiff'}, {boat_sea: 2.4, boat_name: 'Big boat', wind_limit: 5, gust_limit: 6, sea_limit: 1},
    {species: 'rockfish', launch_point: 'some-slug'}, {launch_point: 'north-harbor-ramp', plan: null}, {species: 'lingcod', point: MORRO.forecast_points[0].id}]) {
    const a = assess(tripFor(MORRO, extra), feed(MORRO, {sea: mid}));
    assert.deepEqual(a.hazards, expected, JSON.stringify(extra));
  }
  for (const text of [expected[0], NOT_JUDGED('Morro Bay entrance'), LEAD('Morro Bay entrance') + '8 am;' + TAIL + PARTIAL + NOWIND]) assert.equal(forbidden(text), false, text);
  assert.match(expected[0], /Morro Bay entrance/); assert.match(expected[0], /does not establish the trip's launch or crossing/);
  // missing wind or bearing is disclosed, never read as calm
  const noWind = feed(MORRO); for (const d of noWind.forecast.models.gfs_global.data) d.hourly.wind_speed_10m = d.hourly.wind_speed_10m.map(() => null);
  assert.deepEqual(assess(tripFor(MORRO), noWind).hazards, [NOT_JUDGED('Morro Bay entrance') + NOWIND]);
});

test('bar_swell_order_and_decision: the bar note follows the swell note, once, and only a change in the notes sends an update', () => {
  const trip = tripFor(MORRO);
  // 2.5 ft at 15 s on the second wave model at 09:00 only: the long-period note, and (a 2.5 ft swell, no tide trouble) no bar note
  const swellOnly = feed(MORRO), nine = epochAtHour(DAY, ZONE, 9)[0];
  for (const d of swellOnly.forecast.models.ecmwf_wam.data) { const i = d.hourly.time.indexOf(nine); d.hourly.wave_height[i] = 2.5; d.hourly.wave_period[i] = 15; }
  const s = assess(trip, swellOnly); assert.equal(s.hazards.length, 1); assert.match(s.hazards[0], /^Long-period swell \(2\.5 ft at 15 s\) at 9 am/);
  const bar = assess(trip, feed(MORRO, {sea: mid})); assert.equal(bar.hazards.length, 1); assert.match(bar.hazards[0], /^Regional Morro Bay entrance/);
  const both = assess(trip, feed(MORRO, {sea: () => [6, 15]}));
  assert.equal(both.hazards.length, 2); assert.match(both.hazards[0], /^Long-period swell/); assert.match(both.hazards[1], /^Regional Morro Bay entrance: the offshore bar estimate reads hazardous at 7 am;/);
  const missing = assess(trip, feed(MORRO), null); assert.deepEqual(missing.hazards, [NOT_JUDGED('Morro Bay entrance')]);
  const swellAndMissing = assess(trip, feed(MORRO, {sea: () => [3, 15]}), null);
  assert.equal(swellAndMissing.hazards.length, 2); assert.match(swellAndMissing.hazards[0], /^Long-period swell/); assert.ok(swellAndMissing.hazards[1].startsWith('Regional Morro Bay entrance: bar not judged'));
  // numerical status is untouched by the bar
  const quiet = assess(trip, feed(MORRO));
  for (const a of [bar, missing]) { assert.equal(a.status, quiet.status); assert.deepEqual(a.issues, quiet.issues); assert.equal(a.legal, quiet.legal); }
  assert.equal(assess({...trip, wind_limit: 2}, feed(MORRO, {sea: mid})).status, 'above limits');
  assert.equal(assess({...trip, wind_limit: 2}, feed(MORRO, {sea: mid})).hazards.length, 1);
  // the message names the note once, with the standing check line once
  const msg = alertMessage(trip, MORRO, both, 'update');
  assert.equal(msg.split(BAR_CHECK).length - 1, 1);
  assert.ok(msg.indexOf('Hazard note: Long-period') < msg.indexOf('Hazard note: Regional Morro Bay entrance'));
  assert.ok(msg.includes('\nHazard note: ' + both.hazards[1] + '\n'));
  assert.equal(alertMessage(trip, MORRO, quiet, 'initial').includes('Hazard note'), false, 'a quiet message is unchanged');
  const otherRegion = REGIONS['monterey-point-sur'], otherQuiet = assess(tripFor(otherRegion), feed(otherRegion), null, {region: otherRegion});
  assert.equal(alertMessage(tripFor(otherRegion), otherRegion, otherQuiet, 'initial').includes('Hazard note'), false);

  // decisions: an appearing, changing, degrading, clearing note is one update; the same note is quiet
  const at8 = assess(trip, feed(MORRO, {sea: h => h === 8 ? [10, 10] : null})), at9 = assess(trip, feed(MORRO, {sea: h => h === 9 ? [10, 10] : null}));
  assert.equal(alertDecision(quiet, at8), 'update', 'appearance');
  assert.equal(alertDecision(at9, at8), 'update', 'an earlier hour');
  assert.equal(alertDecision(at8, missing), 'update', 'inputs go missing');
  assert.equal(alertDecision(missing, quiet), 'update', 'inputs return');
  assert.equal(alertDecision(at8, quiet), 'update', 'disappearance');
  const later = assessTrip(trip, MORRO, feed(MORRO, {sea: h => h === 8 ? [10, 10] : null}), rules, [], NOW + 15 * 60000, TIDE);
  assert.notEqual(later.checked_at, at8.checked_at);
  assert.equal(alertDecision(at8, later), null, 'an identical note with only checked_at changed is quiet');
  assert.equal(alertDecision(quiet, assess(trip, feed(MORRO))), null);
  // retraction, final and missed-final still win over the note
  const stale = feed(MORRO, {sea: mid}); stale.completed_at = new Date(NOW - 4 * HOUR).toISOString();
  const retracted = assess(trip, stale); assert.equal(retracted.status, 'unverified'); assert.equal(retracted.hazards.length, 1);
  assert.equal(alertDecision(quiet, retracted), 'retraction');
  assert.equal(alertDecision(at8, at8, {final: true}), 'final');
  assert.equal(alertDecision(at8, missing, {missed: true}), 'missed-final');
  assert.equal(alertDecision(null, at8), 'initial');
});
