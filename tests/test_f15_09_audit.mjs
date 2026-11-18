// SCA-585 / SCA-438 / F15-09: among comparable same-station tide products, selected-time eligibility is tested before the newest
// retrieval is preferred. Offline synthetic fixture; no network, no real station data.
import assert from 'node:assert/strict';
import test from 'node:test';
import {stationPins} from '../web/map/station-model.ts';

const NOW = new Date('2026-10-20T18:00:00Z'), HOUR = 3_600_000;
const ago = h => new Date(+NOW - h * HOUR).toISOString();
const STATION = 'fixture-tide';
const region = {id: 'fixture', stations: {tide: STATION}};
const county = {tideStation: {id: STATION, note: 'Synthetic county report.'}, buoys: [], temperatureStationId: 'fixture-buoy'};
const product = (id, patch) => ({id, kind: 'prediction', name: id, url: 'https://example.test', status: 'ok', station: STATION, checked_at: ago(1), ...patch,
  data: {station: STATION, units: 'ft', note: 'Synthetic station feed.', ...patch.data}});
const ev = (h, v, type) => ({time: ago(h), height_ft: v, type});
// Newest retrieval, but its coverage starts after the selected time (NOW).
const NEWER_OUT = product('newer-out', {checked_at: ago(1), data: {datum: 'MSL', coverage_start: ago(-10), coverage_end: ago(-30),
  predictions: [ev(-10, 9, 'H'), ev(-20, 8, 'L'), ev(-30, 9, 'H')]}});
// Older retained product that does cover the selected time, with its own datum and retrieval clock.
const OLDER_OK = product('older-ok', {status: 'retained', data_retrieved_at: ago(30), last_success_at: ago(30), data: {datum: 'MLLW', coverage_start: ago(5), coverage_end: ago(-5),
  predictions: [ev(5, 1, 'L'), ev(-1, 4, 'H'), ev(-5, 2, 'L')]}});
const OLDER_OUT = product('older-out', {checked_at: ago(20), data: {datum: 'MLLW', coverage_start: ago(-40), coverage_end: ago(-50),
  predictions: [ev(-40, 1, 'L'), ev(-50, 4, 'H')]}});
const OLDER_FRESH = {...OLDER_OK, status: 'ok', checked_at: ago(2), data_retrieved_at: undefined, last_success_at: undefined};

const pin = (sources, report = null) => stationPins({region, catalog: {stations: {}},
  feed: {region_id: region.id, sources: Object.fromEntries(sources.map(s => [s.id, s]))}, now: NOW, at: NOW, report, county: report ? county : null})
  .find(p => p.key === `coops:${STATION}`);

// Height, type, datum, sample time, retrieval time, and freshness must all come from the selected product.
function expectReading({mark, stale}, value, valid, fetched, freshness) {
  assert.ok(mark.reading.startsWith(`Tide ${value} · valid ${valid}; retrieved ${fetched} · ${freshness} · coverage `), mark.reading);
  assert.equal(stale, freshness.startsWith('stale'));
}

test('valid controls satisfy the contract', () => {
  expectReading(pin([OLDER_FRESH]), 'high event: 4.0 ft MLLW', ago(-1), ago(2), 'fresh');
  const newerOk = {...NEWER_OUT, data: {...NEWER_OUT.data, coverage_start: ago(5), coverage_end: ago(-5), predictions: [ev(5, 1, 'L'), ev(-1, 5, 'H'), ev(-5, 2, 'L')]}};
  expectReading(pin([OLDER_OK, newerOk]), 'high event: 5.0 ft MSL', ago(-1), ago(1), 'fresh');
});

test('skip a newer product outside the selected time; omit the value if neither qualifies', () => {
  expectReading(pin([NEWER_OUT, OLDER_OK]), 'high event: 4.0 ft MLLW', ago(-1), ago(30), 'stale / last good');
  const {mark, stale} = pin([NEWER_OUT, OLDER_OUT]);
  assert.match(mark.reading, /^Tide prediction unavailable for selected time;/);
  assert.doesNotMatch(mark.reading, / ft .* · valid /);
  assert.equal(stale, true);
});

test('coverage alone is insufficient: skip a newer curve gap or an event list with no next event', () => {
  for (const predictions of [[ev(4, 8), ev(-4, 9)], [ev(4, 8, 'L'), ev(1, 9, 'H')]]) {
    const gap = {...NEWER_OUT, data: {...NEWER_OUT.data, coverage_start: ago(5), coverage_end: ago(-5), predictions}};
    expectReading(pin([gap, OLDER_OK]), 'high event: 4.0 ft MLLW', ago(-1), ago(30), 'stale / last good');
    assert.match(pin([gap, OLDER_OUT]).mark.reading, /^Tide prediction gap;/);
  }
});

test('the bound county-report curve can win over an ineligible station-feed event product', () => {
  const report = {tides: [{at: ago(4), heightFt: 1}, {at: ago(1), heightFt: 2.5}, {at: ago(-4), heightFt: 3}],
    tideEvents: [{at: ago(-1), heightFt: 7, type: 'H'}], sources: [{kind: 'prediction', fetchedAt: ago(40), outcome: 'ok'}]};
  expectReading(pin([NEWER_OUT], report), 'prediction: 2.5 ft MLLW', ago(1), ago(40), 'stale');
});
