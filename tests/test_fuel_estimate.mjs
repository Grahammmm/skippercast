import test from 'node:test';
import assert from 'node:assert/strict';

const {fuelEstimate} = await import('../web/brief/run.ts');
const water = nm => ({name: 'Spot', nm, basis: 'water'});

// The R6 example and whole-gallon edges catch one-way math or rounding to nearest.
test('fuel estimates both legs and rounds up only to whole gallons', () => {
  for (const [nm, cruise, burn, gallons] of [
    [18, 24, 9, 14],
    [10, 20, 10, 10],
    [10.001, 20, 10, 11],
    [0.001, 20, 10, 1],
    [Number.MIN_VALUE, 60, 0.5, 1],
  ]) {
    assert.deepEqual(fuelEstimate(water(nm), cruise, burn), {gallons, thirds: null}, `${nm} nm`);
  }
  assert.deepEqual(fuelEstimate(water(18), 24, 9, null), {gallons: 14, thirds: null});
});

// A strict comparison or comparing display gallons would flag the exact fractional limit.
test('thirds rule compares the unrounded round trip at the inclusive threshold', () => {
  for (const [nm, gallons, thirds] of [
    [15.49, 16, 'ok'],
    [15.5, 16, 'ok'],
    [15.51, 16, 'check'],
  ]) {
    assert.deepEqual(fuelEstimate(water(nm), 20, 10, 23.25), {gallons, thirds}, `${nm} nm`);
  }
  // A supplied zero is not an absent tank; the profile's upper endpoint is valid too.
  assert.deepEqual(fuelEstimate(water(1), 2, 200, 0), {gallons: 200, thirds: 'check'});
  assert.deepEqual(fuelEstimate(water(1), 2, 200, 1500), {gallons: 200, thirds: 'ok'});
});

// A fallback line is not a water route; invalid distance must not produce a gallon count.
test('fuel requires a water basis and a usable positive distance', () => {
  for (const place of [null, undefined, {...water(18), basis: 'straight'}]) {
    assert.equal(fuelEstimate(place, 24, 9, 70), null);
  }
  for (const nm of [undefined, null, '18', NaN, Infinity, -Infinity, 0, -1]) {
    assert.equal(fuelEstimate(water(nm), 24, 9, 70), null, `${String(nm)} nm`);
  }
  assert.equal(fuelEstimate(water(Number.MAX_VALUE), 2, 200, 70), null, 'overflowing round trip');
});

// Invalid supplied profile values are refused, not coerced, clipped or given defaults.
test('fuel rejects missing required settings and nonfinite or out-of-range profile values', () => {
  for (const cruise of [undefined, null, '24', NaN, Infinity, -Infinity, 1.99, 60.01]) {
    assert.equal(fuelEstimate(water(18), cruise, 9, 70), null, `cruise ${String(cruise)}`);
  }
  for (const burn of [undefined, null, '9', NaN, Infinity, -Infinity, 0.49, 200.01]) {
    assert.equal(fuelEstimate(water(18), 24, burn, 70), null, `burn ${String(burn)}`);
  }
  for (const tank of ['70', NaN, Infinity, -Infinity, -0.01, 1500.01]) {
    assert.equal(fuelEstimate(water(18), 24, 9, tank), null, `tank ${String(tank)}`);
  }
});
