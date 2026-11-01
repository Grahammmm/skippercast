// SC1537-12: on a DST change day the saved window counts real local hours: local 01:00 occurs
// twice on fall-back day and 02:00 does not exist on spring-forward day.
import test from 'node:test';
import assert from 'node:assert/strict';
import {windowInstants, assessTrip} from '../server/alert-policy.ts';

const LA = 'America/Los_Angeles', MISSING = 'The complete saved window is not populated';
const z = iso => Date.parse(iso) / 1000;
const zs = (date, hours) => hours.map(h => z(`${date}T${String(h).padStart(2, '0')}:00:00Z`));

test('fall-back day: 00..03 has five instants, both 01:00 (PDT and PST) included', () => {
  assert.deepEqual(windowInstants('2026-11-01', LA, 0, 3), zs('2026-11-01', [7, 8, 9, 10, 11]));
});

test('spring-forward day: 01..04 has three instants, no 02:00', () => {
  assert.deepEqual(windowInstants('2027-03-14', LA, 1, 4), zs('2027-03-14', [9, 10, 11]));
  assert.deepEqual(windowInstants('2027-03-14', LA, 2, 2), [], 'a window of only the missing hour is empty');
});

test('ordinary day: 07..13 has end-start+1 instants (pinned)', () => {
  const got = windowInstants('2026-10-20', LA, 7, 13);
  assert.equal(got.length, 7);
  assert.equal(got.length, 13 - 7 + 1);
  assert.deepEqual(got, zs('2026-10-20', [14, 15, 16, 17, 18, 19, 20]));
});

test('no-DST zones: end-start+1 instants on any date, including the far zone edges', () => {
  for (const date of ['2026-11-01', '2027-03-14', '2026-07-04']) {
    assert.equal(windowInstants(date, 'Pacific/Honolulu', 5, 18).length, 14, date);
    assert.equal(windowInstants(date, 'Pacific/Honolulu', 0, 23).length, 24, date);
    assert.equal(windowInstants(date, 'Pacific/Kiritimati', 0, 23).length, 24, date + ' UTC+14');
    assert.equal(windowInstants(date, 'Pacific/Pago_Pago', 0, 23).length, 24, date + ' UTC-11');
  }
});

test('an unreadable trip date or an inverted window has no instants', () => {
  assert.deepEqual(windowInstants('2026-13-45', LA, 0, 23), []);
  assert.deepEqual(windowInstants('not a date', LA, 0, 23), []);
  assert.deepEqual(windowInstants('2026-10-20', LA, 9, 8), []);
});

// assessTrip: synthetic one-point LA region; only the window-completeness issue is judged here.
const region = {id: 'r', timezone: LA, forecast_points: [{id: 'p', latitude: 1, longitude: 2}]};
const NOW = Date.parse('2026-10-31T20:00:00Z');
const tripOn = (date, start_hour, end_hour) => ({point: 'p', date, species: 'rockfish', start_hour, end_hour, wind_limit: 15, gust_limit: 20, sea_limit: 6});
const intel = time => ({region_id: 'r', completed_at: new Date(NOW).toISOString(),
  forecast: {requested_points: [['p', 1, 2]], models: {gfs_global: {data: [{hourly: {time}}]}}}});
const around = (date, from, to) => { const out = []; for (let h = from; h <= to; h++) out.push(z(`${date}T00:00:00Z`) + h * 3600); return out; };
const check = (trip, time, rules = null, advisories = []) => assessTrip(trip, region, intel(time), rules, advisories, NOW);

test('fall-back day: a complete feed for 00..03 is populated (both 01:00 instants present)', () => {
  const out = check(tripOn('2026-11-01', 0, 3), around('2026-11-01', 0, 30));
  assert.ok(!out.issues.includes(MISSING), out.issues.join('; '));
  assert.ok(!check(tripOn('2026-11-01', 0, 3), zs('2026-11-01', [7, 8, 9, 10, 11])).issues.includes(MISSING), 'exactly the window');
});

test('spring-forward day: a complete feed for 01..04 is populated', () => {
  assert.ok(!check(tripOn('2027-03-14', 1, 4), around('2027-03-14', 0, 30)).issues.includes(MISSING));
  assert.ok(!check(tripOn('2027-03-14', 1, 4), zs('2027-03-14', [9, 10, 11])).issues.includes(MISSING), 'exactly the window');
});

test('fall-back day: either 01:00 instant missing raises the issue; duplicates or off-hour instants do not fill it', () => {
  for (const gone of [8, 9]) {
    const feed = zs('2026-11-01', [7, 8, 9, 10, 11].filter(h => h !== gone));
    assert.ok(check(tripOn('2026-11-01', 0, 3), feed).issues.includes(MISSING), 'missing ' + gone + ':00Z');
    const other = zs('2026-11-01', [gone === 8 ? 9 : 8])[0];
    assert.ok(check(tripOn('2026-11-01', 0, 3), [...feed, other]).issues.includes(MISSING), 'duplicate of the other 01:00');
    assert.ok(check(tripOn('2026-11-01', 0, 3), [...feed, z('2026-11-01T08:30:00Z')]).issues.includes(MISSING), 'half-hour instant');
  }
});

test('spring-forward day: a missing real hour raises the issue', () => {
  assert.ok(check(tripOn('2027-03-14', 1, 4), zs('2027-03-14', [9, 11])).issues.includes(MISSING));
  assert.ok(check(tripOn('2027-03-14', 2, 2), around('2027-03-14', 0, 30)).issues.includes(MISSING), 'a window with no real hour is never complete');
});

test('a DST day window clear of the change hours reads like an ordinary day', () => {
  for (const date of ['2026-11-01', '2027-03-14']) {
    const dst = check(tripOn(date, 7, 13), around(date, 0, 30)), plain = check(tripOn('2026-10-20', 7, 13), around('2026-10-20', 0, 30));
    assert.ok(!dst.issues.includes(MISSING), date);
    assert.deepEqual(dst.issues, plain.issues, date);
    assert.equal(dst.status, plain.status, date);
    const holed = check(tripOn(date, 7, 13), around(date, 0, 30).filter(t => t !== windowInstants(date, LA, 7, 13)[3]));
    assert.ok(holed.issues.includes(MISSING), date + ' hole in the window');
  }
});

test('empty feed: issue raised and later season/advisory checks do not throw', () => {
  const rules = {valid_from: '2026-01-01', valid_through: '2027-12-31', sources: {}, checks: {},
    species: {rockfish: {source_ids: [], windows: [{start: '2026-11-01', end: '2026-12-31', start_at: '2026-11-01T00:00:00-07:00'}]}}};
  for (const time of [[], undefined]) {
    let out;
    assert.doesNotThrow(() => { out = check(tripOn('2026-11-01', 0, 3), time, rules, [{onset: '2026-11-01T08:00:00Z'}]); });
    assert.ok(out.issues.includes(MISSING));
    assert.equal(out.status, 'unverified');
    assert.ok(out.issues.includes('Applicable marine advisory'), 'no window hours: advisory applies (unchanged)');
    assert.ok(!out.issues.includes('The saved fishing window starts before the legal season opening time'));
  }
});
