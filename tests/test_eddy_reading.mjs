import test from 'node:test';
import assert from 'node:assert/strict';
import {parseEddiesTile} from '../web/map/eddies-feed.ts';
import {eddyAt, eddyReading} from '../web/map/eddy-reading.ts';

const square = {
  outline: [[10, 2], [14, 2], [14, 6], [10, 6], [10, 2]],
  sense: 'cw', diameterKm: 22.4, owMin: -0.03,
};
const concave = {
  outline: [[10, 2], [14, 2], [14, 6], [12, 4], [10, 6], [10, 2]],
  sense: 'ccw', diameterKm: 18, owMin: -0.02,
};
const nested = {
  outline: [[11, 3], [13, 3], [13, 5], [11, 5], [11, 3]],
  sense: 'ccw', diameterKm: 10.6, owMin: -0.01,
};
const center = {lon: 12, lat: 4};

// Swapped axes, a bounding-box shortcut, or a non-half-open ray would each fail here.
for (const [name, eddy, at, expected] of [
  ['inside the square', square, center, square],
  ['outside the square', square, {lon: 15, lat: 4}, null],
  ['inside the concave outline', concave, {lon: 10.5, lat: 4.5}, concave],
  ['inside the concave notch only', concave, {lon: 12, lat: 5}, null],
  ['on a sloping edge', concave, {lon: 13, lat: 5}, concave],
  ['on a horizontal edge', square, {lon: 12, lat: 2}, square],
  ['on a concave vertex', concave, center, concave],
  ['outside with a ray along the horizontal edge', square, {lon: 9, lat: 2}, null],
  ['outside with a ray through both top vertices', square, {lon: 9, lat: 6}, null],
  ['inside with a ray through a local vertex minimum', concave, {lon: 11, lat: 4}, concave],
  ['at NaN longitude', square, {lon: NaN, lat: 4}, null],
  ['at infinite latitude', square, {lon: 12, lat: Infinity}, null],
]) {
  test(`C1: tests containment ${name}`, () => {
    assert.deepEqual(eddyAt([structuredClone(eddy)], at), expected);
  });
}

test('C1: selects the smallest containing eddy, not the first or the smallest overall', () => {
  const disjoint = {...nested, outline: [[1, 1], [2, 1], [2, 2], [1, 1]], diameterKm: 4};
  const almostAsLarge = {...nested, diameterKm: 22.1};
  // Rounding before selection would incorrectly turn this into a tie.
  assert.deepEqual(eddyAt(structuredClone([square, almostAsLarge, disjoint]), center), almostAsLarge);
});

test('C1: keeps the earlier eddy rather than replacing an equal-size match', () => {
  const tie = {...nested, diameterKm: square.diameterKm};
  assert.deepEqual(eddyAt(structuredClone([square, tie]), center), square);
  assert.deepEqual(eddyAt(structuredClone([tie, square]), center), tie);
});

const frameTime = '2026-01-02T15:00Z';
const issuedAt = '2026-01-01T19:00:00-08:00';

test('C2: projects the exact model reading from a parsed tile, omitting geometry and OW', () => {
  const tile = parseEddiesTile({frame_time: frameTime, features: [{
    outline: nested.outline, sense: 'ccw', diameter_km: 10.6, ow_min: -0.01,
  }]});
  assert.deepEqual(eddyReading(tile, issuedAt, center), {
    kind: 'eddy', sense: 'ccw', diameterKm: 11, frameTime, runHourUtc: 3, leadHours: 12, basis: 'model',
  });
});

test('C3: returns only none for an empty tile or a tap outside every eddy', () => {
  assert.deepEqual(eddyReading({frameTime, eddies: []}, issuedAt, center), {kind: 'none'});
  assert.deepEqual(eddyReading({frameTime, eddies: [square]}, issuedAt, {lon: 8, lat: 4}), {kind: 'none'});
});

test('C3: an unparseable run leaves both time facts null without losing the eddy', () => {
  assert.deepEqual(eddyReading({frameTime, eddies: [square]}, 'invalid', center), {
    kind: 'eddy', sense: 'cw', diameterKm: 22, frameTime, runHourUtc: null, leadHours: null, basis: 'model',
  });
});

test('C3: rounds elapsed hours across dates and leaves frozen inputs in their original order', () => {
  const laterFrame = '2026-01-03T02:40Z';
  const eddies = structuredClone([square, nested]);
  for (const eddy of eddies) {
    for (const pair of eddy.outline) Object.freeze(pair);
    Object.freeze(eddy.outline);
    Object.freeze(eddy);
  }
  const tile = Object.freeze({frameTime: laterFrame, eddies: Object.freeze(eddies)});
  const at = Object.freeze({...center});
  assert.deepEqual(eddyReading(tile, '2026-01-02T23:00Z', at), {
    kind: 'eddy', sense: 'ccw', diameterKm: 11, frameTime: laterFrame, runHourUtc: 23, leadHours: 4, basis: 'model',
  });
  assert.deepEqual(tile, {frameTime: laterFrame, eddies: [square, nested]});
  assert.deepEqual(at, center);
});

test('C3: a throwing coordinate accessor cannot escape the reading boundary', () => {
  const unreadable = {get lon() { throw new Error('unreadable'); }, lat: 4};
  assert.deepEqual(eddyReading({frameTime, eddies: [square]}, issuedAt, unreadable), {kind: 'none'});
});
