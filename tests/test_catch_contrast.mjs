import assert from 'node:assert/strict';
import test from 'node:test';
import {catchContrast} from '../server/catch-contrast.ts';
import {parseConditionsV1} from '../server/conditions-v1.ts';

const gradient = 'temperature_gradient_c_per_km';
const support = 'thermal_contrast_supported';
const fields = Object.freeze(['latitude', 'longitude', support, gradient]);
const at = '2024-02-29T01:02:03Z';
const product = 'SST fixture';
const point = {lat: 0, lon: 0};
const frame = (values = [1, 1], overrides = {}) => Object.freeze({
  sampleAt: at,
  product,
  fields,
  resolution: Object.freeze([1, 1]),
  rows: Object.freeze([Object.freeze([0, 0, ...values])]),
  ...overrides,
});
const item = (value, sample_at = at, source = product) => ({value, unit: 'F/nm', product: source, sample_at});

function expectContrast(input, position, expected) {
  const contrast = catchContrast(input, position);
  assert.deepEqual(contrast, expected);
  const snapshot = {v: 1, at, layers: {contrast}};
  assert.deepEqual(parseConditionsV1(snapshot), {ok: true, value: snapshot});
}

// Keep absent inputs distinct, even when both are absent.
test('C1: no position takes precedence over no archive', () => {
  expectContrast(frame(), null, {missing: 'no position'});
  expectContrast(null, null, {missing: 'no position'});
  expectContrast(null, point, {missing: 'not archived'});
});

for (const omitted of [gradient, support]) {
  test(`C1: missing ${omitted} is a bad tile, not a gap`, () => {
    expectContrast(frame([1], {fields: fields.filter(name => name !== omitted)}), point, {missing: 'bad tile'});
  });
}

for (const [name, overrides] of [
  ['zero resolution', {resolution: [0, 1]}],
  ['negative resolution', {resolution: [1, -1]}],
  ['malformed row', {rows: [[0, 0, 1]]}],
  ['empty product', {product: ''}],
  ['non-string product', {product: 42}],
  ['overlong product', {product: 'p'.repeat(201)}],
  ['offset instead of Z', {sampleAt: '2024-02-29T01:02:03+00:00'}],
  ['missing seconds', {sampleAt: '2024-02-29T01:02Z'}],
  ['4,096 fractional zeros', {sampleAt: `2024-02-29T01:02:03.${'0'.repeat(4096)}Z`}],
  ['impossible date', {sampleAt: '2026-02-30T01:02:03Z'}],
  ['24:00 rollover', {sampleAt: '2024-02-29T24:00:00Z'}],
]) {
  test(`C1: ${name} is a bad tile even with a positioned catch`, () => {
    expectContrast(frame([1, 1], overrides), point, {missing: 'bad tile'});
  });
}

test('C1: Number.MAX_VALUE is a bad tile when a supported conversion overflows', () => {
  expectContrast(frame([1, Number.MAX_VALUE]), point, {missing: 'bad tile'});
});

// The first cell is supported; the next is not. A nearest non-gap fallback or
// an interpolated value/flag would report the wrong item at their shared edge.
test('C2: both fields come from the containing native cell', () => {
  const adjacent = frame([], {rows: [[0, 0, 1, 1], [0, 1, 0, 4]]});
  expectContrast(adjacent, {lat: 0, lon: 0.49}, item(3.334));
  expectContrast(adjacent, {lat: 0, lon: 0.5}, {missing: 'not supported'});
  expectContrast(adjacent, {lat: 0, lon: 1.5}, {missing: 'outside'});
});

test('C2: a hole between indexed cells is a gap, not outside', () => {
  const sparse = frame([], {rows: [[0, 0, 1, 1], [0, 2, 1, 2]]});
  expectContrast(sparse, {lat: 0, lon: 1}, {missing: 'gap'});
});

test('C2: null and negative gradients are gaps, including when unsupported', () => {
  for (const flag of [0, 1]) {
    for (const missingGradient of [null, -0.01]) {
      expectContrast(frame([flag, missingGradient]), point, {missing: 'gap'});
    }
  }
  // A truthiness check would incorrectly treat a supported zero as a gap.
  expectContrast(frame([1, 0]), point, item(0));
});

test('C2: null, zero and non-one finite flags never qualify', () => {
  for (const flag of [null, 0, -1, 0.999, 1.001, 2]) {
    expectContrast(frame([flag, 1]), point, {missing: 'not supported'});
  }
  // An unsupported reading is withheld before conversion, even if it would overflow.
  expectContrast(frame([0, Number.MAX_VALUE]), point, {missing: 'not supported'});
});

test('C1: non-numeric and non-finite readings are sampler errors, not coerced flags or gaps', () => {
  for (const invalid of ['1', true, undefined, NaN, Infinity, -Infinity]) {
    expectContrast(frame([invalid, 1]), point, {missing: 'bad tile'});
    expectContrast(frame([1, invalid]), point, {missing: 'bad tile'});
  }
});

test('C3: converts and rounds a frozen native reading, preserving timestamp and product verbatim', () => {
  const sampleAt = '2024-02-29T01:02:03.12Z';
  const fullProduct = '🌊'.repeat(200);
  expectContrast(frame([1, 0.25], {sampleAt, product: fullProduct}), point, item(0.833, sampleAt, fullProduct));
  expectContrast(frame(), point, item(3.334));
});

test('C3: rounding does not overflow a finite converted value', () => {
  expectContrast(frame([1, 1e307]), point, item(3.3336e307));
});
