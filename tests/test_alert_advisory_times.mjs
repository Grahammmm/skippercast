// SC1537-02: a marine advisory with an unreadable onset/ends/expires time, or an advisory
// entry that is not an object, counts as applicable (fail closed) instead of being dropped.
import test from 'node:test';
import assert from 'node:assert/strict';
import {advisoryApplies, assessTrip} from '../server/alert-policy.ts';

// Saved window 06:00–08:00 UTC on 2026-11-02.
const START = Date.parse('2026-11-02T06:00:00Z'), END = Date.parse('2026-11-02T08:00:00Z');
const BEFORE = '2026-11-02T05:00:00Z', INSIDE = '2026-11-02T07:00:00Z', AFTER = '2026-11-02T09:00:00Z';
const applies = a => advisoryApplies(a, START, END);

test('readable times keep today\'s rule (overlap applies, disjoint does not)', () => {
  assert.equal(applies({onset: BEFORE, ends: AFTER}), true);
  assert.equal(applies({onset: INSIDE, ends: INSIDE}), true);
  assert.equal(applies({onset: AFTER, ends: '2026-11-02T12:00:00Z'}), false, 'onset after the window end');
  assert.equal(applies({onset: '2026-11-02T01:00:00Z', ends: BEFORE}), false, 'ends before the window start');
  assert.equal(applies({onset: '2026-11-02T01:00:00Z', expires: BEFORE}), false, 'expires used when ends is absent');
  assert.equal(applies({onset: '2026-11-02T01:00:00Z', expires: AFTER}), true);
  assert.equal(applies({onset: '2026-11-02T08:00:00Z', ends: '2026-11-02T06:00:00Z'}), true, 'edges are inclusive');
  // A readable ends wins over expires, as before.
  assert.equal(applies({onset: BEFORE, ends: BEFORE, expires: AFTER}), false);
});

test('a present but garbled time applies (fail closed)', () => {
  assert.equal(applies({onset: 'not a date', ends: AFTER}), true);
  assert.equal(applies({onset: 'not a date', ends: BEFORE}), true, 'garbled onset is not rescued by a past ends');
  assert.equal(applies({onset: AFTER, ends: '2026-13-45T99:00', expires: '2026-11-02T12:00:00Z'}), true,
    'garbled ends is not rescued by a valid expires');
  assert.equal(applies({onset: BEFORE, ends: '2026-13-45T99:00', expires: BEFORE}), true);
  assert.equal(applies({onset: '2026-11-02T01:00:00Z', expires: 'soon'}), true, 'garbled expires with ends absent');
  assert.equal(applies({onset: AFTER, ends: ' '}), true, 'whitespace is present, not absent');
});

test('a non-string time applies; null, empty or missing time is open', () => {
  for (const bad of [12345, {}, [], true, 0, Number.NaN]) {
    assert.equal(applies({onset: bad, ends: BEFORE}), true, 'onset ' + JSON.stringify(bad));
    assert.equal(applies({onset: AFTER, ends: bad}), true, 'ends ' + JSON.stringify(bad));
    assert.equal(applies({onset: AFTER, expires: bad}), true, 'expires ' + JSON.stringify(bad));
  }
  for (const open of [null, '', undefined]) {
    assert.equal(applies({onset: open, ends: BEFORE}), false, 'open onset, past ends');
    assert.equal(applies({onset: open, ends: AFTER}), true, 'open onset, future ends');
    assert.equal(applies({onset: AFTER, ends: open, expires: open}), false, 'open end, onset after window');
    assert.equal(applies({onset: BEFORE, ends: open, expires: open}), true, 'open end, onset before window');
    assert.equal(applies({onset: '2026-11-02T01:00:00Z', ends: open, expires: BEFORE}), false, 'absent ends falls back to expires');
  }
  assert.equal(applies({ends: BEFORE}), false, 'missing onset key');
  assert.equal(applies({}), true, 'no times at all is open-ended');
});

test('an advisory that is not an object applies', () => {
  for (const a of [undefined, null, 'x', [], [{onset: AFTER}], 7]) assert.equal(applies(a), true, JSON.stringify(a) ?? 'undefined');
});

test('no window hours applies (unchanged)', () => {
  assert.equal(advisoryApplies({onset: AFTER, ends: '2026-11-02T12:00:00Z'}, null, null), true);
  assert.equal(advisoryApplies({onset: '2026-11-02T01:00:00Z', ends: BEFORE}, null, null), true);
});

// assessTrip: synthetic one-point region in UTC with a populated 06–08 window.
const region = {id: 'r', timezone: 'UTC', forecast_points: [{id: 'p', latitude: 1, longitude: 2}]};
const trip = {point: 'p', date: '2026-11-02', species: 'rockfish', start_hour: 6, end_hour: 8, wind_limit: 15, gust_limit: 20, sea_limit: 6};
const NOW = Date.parse('2026-11-01T20:00:00Z');
function intel(hours = [6, 7, 8]) {
  const time = hours.map(h => Date.parse(`2026-11-02T0${h}:00:00Z`) / 1000);
  return {region_id: 'r', completed_at: new Date(NOW).toISOString(),
    forecast: {requested_points: [['p', 1, 2]], models: {gfs_global: {data: [{hourly: {time}}]}}}};
}
const ADV = 'Applicable marine advisory', UNAVAILABLE = 'Marine advisories unavailable';
const check = (advisories, i = intel()) => assessTrip(trip, region, i, null, advisories, NOW);

test('assessTrip: a non-object or garbled advisory makes the trip unverified, never throws', () => {
  for (const a of [undefined, null, 'x', [], {onset: 'not a date', ends: AFTER}, {onset: AFTER, ends: '2026-13-45T99:00', expires: AFTER}, {onset: 12345}]) {
    let out;
    assert.doesNotThrow(() => { out = check([a]); }, JSON.stringify(a) ?? 'undefined');
    assert.equal(out.status, 'unverified');
    assert.ok(out.issues.includes(ADV), 'advisory issue for ' + (JSON.stringify(a) ?? 'undefined'));
    assert.equal(out.issues.filter(s => s === ADV).length, 1, 'issue listed once');
  }
  // One readable non-applicable advisory does not hide a garbled one next to it.
  assert.ok(check([{onset: AFTER, ends: '2026-11-02T12:00:00Z'}, {onset: 'garbled'}]).issues.includes(ADV));
});

test('assessTrip: readable advisories, empty list and missing feed are unchanged', () => {
  assert.ok(check([{onset: BEFORE, ends: AFTER}]).issues.includes(ADV));
  const outside = check([{onset: AFTER, ends: '2026-11-02T12:00:00Z'}, {onset: '2026-11-02T01:00:00Z', expires: BEFORE}]);
  assert.ok(!outside.issues.includes(ADV), 'disjoint readable advisories do not apply');
  const none = check([]);
  assert.ok(!none.issues.includes(ADV) && !none.issues.includes(UNAVAILABLE));
  for (const feed of [null, undefined, {features: []}, 'x']) {
    const out = check(feed);
    assert.ok(out.issues.includes(UNAVAILABLE) && !out.issues.includes(ADV), 'not an array: ' + JSON.stringify(feed));
  }
});

test('assessTrip: no window hours makes any advisory applicable (unchanged)', () => {
  const out = check([{onset: AFTER, ends: '2026-11-02T12:00:00Z'}], intel([]));
  assert.ok(out.issues.includes(ADV));
  assert.ok(!check([], intel([])).issues.includes(ADV));
});
