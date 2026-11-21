import assert from 'node:assert/strict';
import test from 'node:test';
import {geometryCoveredByBounds, placeRefused, screenPlace} from '../dist/geo-screen.js';
import {SCREEN_MAX_AGE_MS, SCREEN_MAX_AHEAD_MS, screenGpxCandidates} from '../web/gpx-import-screen.ts';

const now = Date.UTC(2026, 0, 1);
const oldEdge = now - 129_600_000;
const aheadEdge = now + 300_000;
const point = (name, lon = 0, lat = 10) => ({name, lat, lon, note: null});
const mark = Object.freeze({...point('Mark'), note: 'Keep this note'});
const fresh = {checkedAt: now, verdict: () => ({}), refused: () => false};

test('C1: exported freshness limits are in milliseconds', () => {
  assert.deepEqual([SCREEN_MAX_AGE_MS, SCREEN_MAX_AHEAD_MS], [129_600_000, 300_000]);
});

test('C2: an empty eligible batch returns both empty lists without querying the screen', () => {
  let queried = false;
  const verdict = () => { queried = true; return {}; };
  assert.deepEqual(screenGpxCandidates([], {...fresh, verdict}, now), {ok: true, clear: [], refused: []});
  assert.equal(queried, false);
});

test('C3: missing or invalid callbacks are unavailable even at the time limits', () => {
  let queried = false;
  const verdict = () => { queried = true; return {}; };
  for (const checkedAt of [oldEdge, aheadEdge]) {
    for (const screen of [null, {...fresh, checkedAt, verdict: null}, {...fresh, checkedAt, verdict, refused: true},
      {...fresh, checkedAt, get verdict() { throw Error('cannot load callback'); }}]) {
      assert.deepEqual(screenGpxCandidates([mark], screen, now), {ok: false, error: 'screen-unavailable'});
    }
  }
  assert.equal(queried, false);
});

test('C3: the 36-hour and five-minute limits are inclusive', () => {
  for (const checkedAt of [oldEdge, aheadEdge]) {
    assert.deepEqual(screenGpxCandidates([mark], {...fresh, checkedAt}, now), {ok: true, clear: [mark], refused: []});
  }
});

test('C3: a millisecond outside either limit or a non-finite clock fails closed', () => {
  let queried = false;
  const verdict = () => { queried = true; return {}; };
  for (const [checkedAt, clock] of [[oldEdge - 1, now], [aheadEdge + 1, now], [NaN, now], [Infinity, now], [now, NaN], [now, -Infinity]]) {
    assert.deepEqual(screenGpxCandidates([mark], {...fresh, checkedAt, verdict}, clock), {ok: false, error: 'screen-stale'});
  }
  const unreadable = {...fresh, verdict, get checkedAt() { throw Error('no timestamp'); }};
  assert.deepEqual(screenGpxCandidates([mark], unreadable, now), {ok: false, error: 'screen-stale'});
  assert.equal(queried, false);
});

test('C4: verdict and refusal failures refuse only their waypoint and preserve batch order', () => {
  const verdicts = [
    ['Null', null, 'unchecked'],
    ['Boolean', false, 'unchecked'],
    ['Missing verdict', undefined, 'unchecked'],
    ['Function', () => ({}), 'unchecked'],
    ['Inside takes priority', {inside: true, screened: false}, 'inside'],
    ['Near', {inside: false, screened: true}, 'near'],
    ['Not strictly screened', {inside: 'yes', screened: 1}, 'unchecked'],
    ['First clear', {}, null],
    ['Verdict throws', new Error('verdict failed'), 'unchecked'],
    ['Refusal throws', {refusalFails: true}, 'unchecked'],
    ['Unreadable verdict field', {get inside() { throw Error('unreadable verdict'); }}, 'unchecked'],
    ['Second clear', {}, null],
  ];
  const waypoints = Object.freeze(verdicts.map(([name], i) => Object.freeze(point(name, i))));
  const calls = [];
  const screen = {
    checkedAt: now,
    verdict({latitude, longitude}) {
      calls.push([latitude, longitude]);
      const [, v] = verdicts[longitude];
      if (v instanceof Error) throw v;
      return v;
    },
    refused(v) {
      if (v?.refusalFails) throw Error('refusal failed');
      return v?.inside !== undefined || v?.screened !== undefined;
    },
  };
  assert.deepEqual(screenGpxCandidates(waypoints, screen, now), {
    ok: true,
    clear: verdicts.flatMap(([, , reason], i) => reason === null ? [waypoints[i]] : []),
    refused: verdicts.flatMap(([, , reason], i) => reason === null ? [] : [{waypoint: waypoints[i], reason}]),
  });
  assert.deepEqual(calls, waypoints.map(({lat, lon}) => [lat, lon]));
});

test('C4: the real screen refuses points in, near, and outside coverage of a synthetic closure screen', () => {
  const polygon = {type: 'Polygon', coordinates: [[[-.01, 9.99], [.01, 9.99], [.01, 10.01], [-.01, 10.01], [-.01, 9.99]]]};
  const fixture = {
    coversGeometry: g => geometryCoveredByBounds(g, [-1, 9, 1, 11]),
    exportExclusions: () => ({features: [{type: 'Feature', properties: {NAME: 'Fixture closure'}, geometry: polygon}]}),
  };
  const inside = point('Inside'), near = point('Near', .0105), outsideCoverage = point('Outside coverage', 2), clear = point('Clear', .02);
  assert.deepEqual(screenGpxCandidates([inside, clear, near, outsideCoverage], {
    checkedAt: now, verdict: screenPlace.bind(null, fixture), refused: placeRefused,
  }, now), {
    ok: true, clear: [clear], refused: [
      {waypoint: inside, reason: 'inside'}, {waypoint: near, reason: 'near'}, {waypoint: outsideCoverage, reason: 'unchecked'},
    ],
  });
});
