import assert from 'node:assert/strict';
import test from 'node:test';
import {WATCH_RANGES, displayRange, fromStored, toStored, unitSymbol} from '../web/spot-watch-units.ts';

test('C1: stored limits match the API ranges, not the display ranges', () => {
  assert.deepEqual(WATCH_RANGES, {'water-temp': [28, 95], chlorophyll: [0.01, 100], 'sst-contrast': [0, 10]});
});

test('C1: every helper rejects unknown and inherited layer keys before doing unit work', () => {
  for (const layer of ['unknown', 'constructor', '__proto__', ['water-temp']]) {
    assert.throws(() => toStored(layer, NaN, 'F'), TypeError);
    assert.throws(() => fromStored(layer, 32, 'F'), TypeError);
    assert.throws(() => displayRange(layer, 'F'), TypeError);
    assert.throws(() => unitSymbol(layer, 'F'), TypeError);
  }
});

// Display inputs one step below, at each endpoint, and one step above.
const rangeCases = [
  ['water-temp', 'F', [27.9, 28, 95, 95.1], [null, 28, 95, null]],
  ['water-temp', 'C', [-2.3, -2.2, 35, 35.1], [null, 28, 95, null]],
  ['chlorophyll', 'F', [0, 0.01, 100, 100.01], [null, 0.01, 100, null]],
  ['chlorophyll', 'C', [0, 0.01, 100, 100.01], [null, 0.01, 100, null]],
  ['sst-contrast', 'F', [-0.01, 0, 10, 10.01], [null, 0, 10, null]],
  ['sst-contrast', 'C', [-0.01, 0, 5.55, 5.56], [null, 0, 9.99, null]],
];

for (const [layer, temp, inputs, expected] of rangeCases) {
  test(`C2: ${layer} (${temp}) accepts both endpoints but not a step outside`, () => {
    assert.deepEqual(inputs.map(value => toStored(layer, value, temp)), expected);
  });

  test(`C4: ${layer} (${temp}) returns inward endpoints that save successfully`, () => {
    const range = displayRange(layer, temp);
    assert.deepEqual(range, inputs.slice(1, 3));
    assert.deepEqual(range.map(value => toStored(layer, value, temp)), expected.slice(1, 3));
  });
}

test('C2: Celsius rounds on either side of a half step and checks the rounded value', () => {
  assert.deepEqual([0.249, 0.25, 0.251, -2.24].map(value => toStored('water-temp', value, 'C')), [32.4, 32.5, 32.5, 28]);
  assert.deepEqual([0.6249, 0.625, 0.6251, 5.557].map(value => toStored('sst-contrast', value, 'C')), [1.12, 1.13, 1.13, 10]);
});

test('C2: Fahrenheit and chlorophyll preserve precision, rather than quantizing all inputs', () => {
  assert.equal(toStored('water-temp', 55.123, 'F'), 55.123);
  assert.equal(toStored('sst-contrast', 1.2345, 'F'), 1.2345);
  for (const temp of ['F', 'C']) assert.equal(toStored('chlorophyll', 0.01234, temp), 0.01234);
});

test('C2: non-finite values are rejected even on the unchanged paths', () => {
  for (const [layer, temp] of rangeCases) {
    assert.deepEqual([NaN, Infinity, -Infinity].map(value => toStored(layer, value, temp)), [null, null, null]);
  }
});

test('C3: display conversion uses nearest steps, including .05 and .005 ties', () => {
  assert.deepEqual([28, 32.089, 32.09, 32.091, 34.25, 95].map(value => fromStored('water-temp', value, 'C')), [-2.2, 0, 0.1, 0.1, 1.3, 35]);
  assert.deepEqual([0, 1.1249, 1.125, 1.1251, 10].map(value => fromStored('sst-contrast', value, 'C')), [0, 0.62, 0.63, 0.63, 5.56]);
});

test('C3: Fahrenheit and chlorophyll display without quantizing stored values', () => {
  assert.equal(fromStored('water-temp', 55.123, 'F'), 55.123);
  assert.equal(fromStored('sst-contrast', 1.2345, 'F'), 1.2345);
  for (const temp of ['F', 'C']) assert.equal(fromStored('chlorophyll', 0.01234, temp), 0.01234);
});

test('C3: interior samples round trip within one stored step, even when quantization changes the value', () => {
  for (const [layer, stored, expectedC, scale] of [
    ['water-temp', 50.1, 50.2, 10],
    ['chlorophyll', 0.17, 0.17, 100],
    ['sst-contrast', 1, 1.01, 100],
  ]) {
    const actual = toStored(layer, fromStored(layer, stored, 'C'), 'C');
    assert.equal(actual, expectedC);
    assert.ok(Math.abs(Math.round(actual * scale) - Math.round(stored * scale)) <= 1);
    assert.equal(toStored(layer, fromStored(layer, stored, 'F'), 'F'), stored);
  }
});

test('C5: symbols distinguish absolute temperatures, gradients and chlorophyll', () => {
  assert.deepEqual(rangeCases.map(([layer, temp]) => unitSymbol(layer, temp)), ['°F', '°C', 'mg/m³', 'mg/m³', '°F/nm', '°C/nm']);
});

test('C5: rounding small negative results produces positive zero', () => {
  const results = [
    toStored('sst-contrast', -0.001, 'C'),
    fromStored('water-temp', 31.99, 'C'),
    fromStored('sst-contrast', -0.001, 'C'),
  ];
  assert.deepEqual(results, [0, 0, 0]);
  assert.deepEqual(results.map(value => Object.is(value, -0)), [false, false, false]);
  assert.equal(Object.is(toStored('sst-contrast', -0, 'F'), -0), true);
});
