// SCA-585 / F15-09: among comparable same-station tide products, selected-time eligibility is tested before the newest
// retrieval is preferred. Offline synthetic fixture; no network, no real station data.
// Valid controls must satisfy the contract. The affected control is only *observed* (diagnostic): the test neither
// asserts the gap is desirable nor fails when it is fixed. A synthetic negative control proves the detector.
import assert from 'node:assert/strict';
import test from 'node:test';
import catalog from '../catalog/station-locations.json' with {type: 'json'};
import {stationPins} from '../web/map/station-model.ts';

const NOW = new Date('2026-10-20T18:00:00Z'), HOUR = 3_600_000;
const ago = h => new Date(+NOW - h * HOUR).toISOString();
const region = {id: 'fixture', stations: {tide: '9412553'}};
const product = (id, patch) => ({id, kind: 'prediction', name: id, url: 'https://example.test', status: 'ok', station: '9412553', checked_at: ago(1), ...patch,
  data: {station: '9412553', units: 'ft', note: 'Synthetic curve.', ...patch.data}});
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

const reading = (...sources) => stationPins({region, catalog, feed: {region_id: 'fixture', sources: Object.fromEntries(sources.map(s => [s.id, s]))}, now: NOW, at: NOW})
  .find(p => p.key === 'coops:9412553').mark.reading;

// Contract: an eligible product is shown with its OWN time, datum and state; with none eligible, no tide value is shown.
function contract(text, eligible) {
  if (!eligible) return /unavailable/i.test(text) && !/Tide (high|low) event:|Tide prediction:/.test(text);
  const m = text.match(/Tide [a-z ]+: [\d.]+ ft (\S+) · valid (\S+); retrieved (\S+) · (fresh|stale)( \/ last good)?/);
  return !!m && m[1] === eligible.datum && m[3] === eligible.fetched && m[4] === eligible.state && !!m[5] === eligible.lastGood;
}

test('valid controls satisfy the contract', () => {
  // single eligible product
  assert.ok(contract(reading(OLDER_FRESH), {datum: 'MLLW', fetched: ago(2), state: 'fresh', lastGood: false}), reading(OLDER_FRESH));
  // newer product that also covers the time stays preferred, with its own datum
  const newerOk = {...NEWER_OUT, data: {...NEWER_OUT.data, coverage_start: ago(5), coverage_end: ago(-5), predictions: [ev(5, 1, 'L'), ev(-1, 5, 'H'), ev(-5, 2, 'L')]}};
  assert.ok(contract(reading(newerOk, OLDER_OK), {datum: 'MSL', fetched: ago(1), state: 'fresh', lastGood: false}), reading(newerOk, OLDER_OK));
  // neither qualifies: omitted, no borrowed value
  assert.ok(contract(reading(NEWER_OUT, OLDER_OUT), null), reading(NEWER_OUT, OLDER_OUT));
});

test('checker detects the stated gap on synthetic readings', () => {
  // independent negative control: fabricated text, no dependence on the station model
  const older = {datum: 'MLLW', fetched: ago(30), state: 'stale', lastGood: true};
  assert.equal(contract('Tide prediction unavailable for selected time; retrieved X', older), false, 'unavailable while an older product qualifies must be detected');
  assert.equal(contract(`Tide high event: 4.0 ft MSL · valid ${ago(-1)}; retrieved ${ago(1)} · fresh`, older), false, 'borrowed newer datum/time must be detected');
  assert.equal(contract(`Tide high event: 4.0 ft MLLW · valid ${ago(-1)}; retrieved ${ago(30)} · stale / last good`, older), true);
  assert.equal(contract('Tide prediction unavailable for selected time; retrieved X', null), true);
});

test('affected control: baseline observation only (passes before and after a fix)', t => {
  // Newer out-of-coverage product + older eligible retained product. Expected after a fix: older product with its own
  // retrieval time, MLLW datum and "stale / last good". Not asserted, so a correct fix needs no edit here.
  const text = reading(NEWER_OUT, OLDER_OK);
  t.diagnostic(`newer out-of-coverage + older eligible: contractHolds=${contract(text, {datum: 'MLLW', fetched: ago(30), state: 'stale', lastGood: true})} reading=${text}`);
});
