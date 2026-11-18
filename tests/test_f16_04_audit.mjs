// SCA-549 / SCA-206 / F16-04: synthetic held coverage only; no browser, live data or transport.
import assert from 'node:assert/strict';
import test from 'node:test';
import {circleGeometry, geometryCoveredByBounds, PLANNING_MARGIN_M} from '../dist/geo-screen.js';
import {checkPosition} from '../web/position-check.ts';

// Local metre offsets about the equator; strictly synthetic. The planner's
// coversGeometry also withholds the 70 m planning halo at the raw west edge (x=0).
const deg = metres => metres / 111320;
const bounds = [0, deg(-1000), deg(2000), deg(1000)];
const edge = PLANNING_MARGIN_M + 10; // 10 m inside usable coverage, ~80 m inside the raw envelope
const name = 'Synthetic reserve';
const geometry = {type: 'Polygon', coordinates: [[[550, -20], [650, -20], [650, 20], [550, 20], [550, -20]]
  .map(([x, y]) => [deg(x), deg(y)])]};
const screen = {
  coversGeometry: shape => geometryCoveredByBounds(shape, bounds),
  heldBoundaries: () => ({current: true, missing: [], clock: 'ok', checked_at: '2026-01-01T00:00:00Z',
    features: [{properties: {NAME: name}, geometry}]}),
};
const fixAt = async (metresEast, reported = {}, heldScreen = screen) => (await checkPosition(async () => heldScreen, {
  getCurrentPosition: success => success({coords: {latitude: 0, longitude: deg(metresEast), ...reported}}),
})).reading;

// Both the well-covered outside point and the near point have a fully covered 50 m footprint.
// The near point is ~100 m from the held closure: outside the 70 m halo, but within 70 + 50 m.
test('F16-04 controls: covered outside, named near, and raw edge already withheld', async () => {
  const gps = {accuracy: 50};
  for (const [x, expected] of [[250, 'outside'], [450, 'near']]) {
    assert.ok(screen.coversGeometry(circleGeometry(0, deg(x), gps.accuracy)), 'control footprint is covered');
    const result = await fixAt(x, gps);
    assert.equal(result.kind, 'checked');
    assert.equal(result.where, expected);
    if (expected === 'near') {
      assert.equal(result.name, name);
      assert.ok(result.distanceM > PLANNING_MARGIN_M && result.distanceM <= PLANNING_MARGIN_M + gps.accuracy);
    }
  }
  assert.equal((await fixAt(10, gps)).kind, 'not-covered', '10 m inside the raw envelope is already withheld');
});

test('F16-04 controls: omitted accuracy is unknown, explicit zero is not', async () => {
  // Keep the position and held geometry fixed at the affected centre. Zero has
  // no footprint beyond the covered point; unknown must not be normalized to zero.
  const zero = await fixAt(edge, {accuracy: 0});
  assert.equal(zero.kind, 'checked');
  assert.equal(zero.where, 'outside');
  assert.equal(zero.fix.accuracyM, 0);
  assert.equal(zero.lowAccuracy, false);
  const absent = await fixAt(edge);
  assert.equal(absent.kind, 'checked');
  assert.equal(absent.fix.accuracyM, null);
  assert.equal(absent.lowAccuracy, true);
});

test('F16-04 contract: a covered centre cannot clear an uncovered accuracy footprint', async () => {
  assert.ok(screen.coversGeometry({type: 'Point', coordinates: [deg(edge), 0]}), 'centre is covered');
  assert.equal(screen.coversGeometry(circleGeometry(0, deg(edge), 50)), false, '50 m footprint crosses usable coverage edge');
  const {kind, where} = await fixAt(edge, {accuracy: 50});
  assert.ok(kind === 'incomplete' || kind === 'not-covered',
    `50 m accuracy, centre 10 m inside usable coverage: expected incomplete or not-covered, got ${kind}${where ? `/${where}` : ''}`);
});

test('F16-04 contract: a crossing footprint does not hide a known nearby closure', async () => {
  // Move the coverage edge, not the closure or the fix used by the near control above.
  const near = 450;
  const nearEdge = {...screen, coversGeometry: shape => geometryCoveredByBounds(shape, [deg(near - edge), ...bounds.slice(1)])};
  assert.ok(nearEdge.coversGeometry({type: 'Point', coordinates: [deg(near), 0]}), 'centre is covered');
  assert.equal(nearEdge.coversGeometry(circleGeometry(0, deg(near), 50)), false, 'footprint is not covered');
  const result = await fixAt(near, {accuracy: 50}, nearEdge);
  assert.equal(result.kind, 'checked');
  assert.equal(result.where, 'near');
  assert.equal(result.name, name);
});
