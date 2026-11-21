import assert from 'node:assert/strict';
import test from 'node:test';
import { composeSnapshot, SNAPSHOT_LAYERS } from '../server/catch-snapshot.ts';
import { CONDITIONS_MAX_BYTES, parseConditionsV1 } from '../server/conditions-v1.ts';

const order = ['water_temp', 'contrast', 'front_nm', 'chlorophyll', 'current', 'swell', 'wind', 'tide'];
const at = '2024-02-29T01:02:03.000Z';
const sample_at = '2024-02-28T18:00:00Z';
const valid_at = '2024-02-29T01:00Z';
const input = { startedAt: at, now: new Date(at), region: 'fixture', coverage: 'inside', layers: {} };
const full = {
  water_temp: { value: 56.9, unit: 'F', product: 'fixture SST', sample_at },
  contrast: { value: -0.4, unit: 'F/nm', product: 'fixture SST', sample_at },
  front_nm: { value: 2.1, product: 'fixture fronts', sample_at },
  chlorophyll: { value: 2.4, unit: 'mg/m3', product: 'fixture OCI', sample_at },
  current: { kn: 0.3, toward_deg: 0, run: 'fixture current', valid_at },
  swell: { ft: 5, period_s: 11, from_deg: 359.9, run: 'fixture swell', valid_at },
  wind: { kn: 9, from_deg: 320, run: 'fixture wind', valid_at },
  tide: { stage: 'ebb', height_ft: -1.2, station: 'fixture station' },
};
const missingLayers = reason => Object.fromEntries(order.map(key => [key, { missing: reason }]));

function expectSnapshot(raw, expected) {
  const actual = composeSnapshot(raw);
  assert.deepEqual(actual, expected);
  assert.deepEqual(parseConditionsV1(actual), { ok: true, value: expected });
  return actual;
}

// Using feed arrival order would make the stored snapshot order variable.
test('C1: exports and stores the fixed layer order', () => {
  assert.deepEqual(SNAPSHOT_LAYERS, order);
  const layers = Object.fromEntries(Object.entries(full).reverse());
  const actual = expectSnapshot({ ...input, layers }, { v: 1, at, layers: full });
  assert.deepEqual(Object.keys(actual.layers), order);
});

// Applying coverage or region checks first can mask a more specific time failure.
for (const [label, startedAt, region, coverage, missing] of [
  ['invalid time alone', 'not a time', 'fixture', 'inside', 'invalid time'],
  ['invalid time before no region', 'not a time', null, 'inside', 'invalid time'],
  ['invalid time before outside coverage', 'not a time', 'fixture', 'outside', 'invalid time'],
  ['future time alone', '2024-02-29T01:02:03.001Z', 'fixture', 'inside', 'future time'],
  ['future time before no region', '2024-02-29T01:02:03.001Z', null, 'inside', 'future time'],
  ['future time before outside coverage', '2024-02-29T01:02:03.001Z', 'fixture', 'outside', 'future time'],
  ['no region for null', at, null, 'inside', 'no region'],
  ['no region for empty string', at, '', 'inside', 'no region'],
  ['null region before outside coverage', at, null, 'outside', 'no region'],
  ['empty region before outside coverage', at, '', 'outside', 'no region'],
  ['outside coverage with a known region', at, 'fixture', 'outside', 'outside coverage'],
]) {
  test(`C2: ${label}`, () => {
    expectSnapshot({ ...input, startedAt, region, coverage }, { v: 1, missing });
  });
}

// A string comparison or >= would reject the catch at the exact supplied instant.
test('C3: normalizes a non-UTC spelling at the clock boundary and copies all eight layers', () => {
  const layers = structuredClone(full);
  for (const layer of Object.values(layers)) Object.freeze(layer);
  Object.freeze(layers);
  const raw = Object.freeze({ ...input, startedAt: '2024-02-28T17:02:03-08:00', layers });
  const actual = expectSnapshot(raw, { v: 1, at, layers: full });
  for (const key of order) assert.notStrictEqual(actual.layers[key], layers[key], key);
  assert.deepEqual(raw, { ...input, startedAt: '2024-02-28T17:02:03-08:00', layers: full });
});

// An assembler that accepts only measurements would overwrite valid missing reasons.
test('C3: preserves missing reasons for every layer, including a chlorophyll cloud gap', () => {
  const expected = { ...missingLayers('not archived'), chlorophyll: { missing: 'no retrieval' } };
  expectSnapshot({ ...input, layers: structuredClone(expected) }, { v: 1, at, layers: expected });
});

// One refused reading must not discard other readings or borrow another layer's schema.
for (const [key, value] of [
  ['water_temp', { ...full.water_temp, unit: 'C' }],
  ['contrast', { ...full.contrast, value: NaN }],
  ['front_nm', { ...full.front_nm, value: -1 }],
  ['chlorophyll', { ...full.chlorophyll, sample_at: 'yesterday' }],
  ['current', full.wind],
  ['swell', { ...full.swell, from_deg: 360 }],
  ['wind', null],
  ['tide', { missing: 'not archived', ...full.tide }],
]) {
  test(`C3: replaces only the refused ${key} reading`, () => {
    expectSnapshot({ ...input, layers: { ...full, [key]: value } },
      { v: 1, at, layers: { ...full, [key]: { missing: 'invalid value' } } });
  });
}

// Iterating only supplied keys would omit required slots or forward unknown fields.
test('C3: fills absent and undefined slots and ignores extra keys without reading them', () => {
  const layers = { wind: undefined, tide: full.tide, get extra() { throw new Error('unused'); } };
  expectSnapshot({ ...input, layers },
    { v: 1, at, layers: { ...missingLayers('not computed'), tide: full.tide } });
});

// Checking each layer in isolation is necessary but does not enforce the aggregate UTF-8 cap.
test('C4: accepts the exact byte cap and refuses an aggregate one byte over', () => {
  const bytes = raw => new TextEncoder().encode(JSON.stringify(raw)).byteLength;
  const layers = Object.fromEntries(order.map((key, i) => [key, { missing: '🌊'.repeat(i < 4 ? 200 : 1) }]));
  const padding = CONDITIONS_MAX_BYTES - bytes({ v: 1, at, layers });
  order.slice(4).forEach((key, i) => {
    layers[key].missing += 'x'.repeat(Math.floor((padding + i) / 4));
  });
  const atCap = { v: 1, at, layers };
  assert.equal(bytes(atCap), CONDITIONS_MAX_BYTES);
  expectSnapshot({ ...input, layers: structuredClone(layers) }, atCap);

  const over = { ...layers, tide: { missing: `${layers.tide.missing}x` } };
  assert.equal(bytes({ v: 1, at, layers: over }), CONDITIONS_MAX_BYTES + 1);
  for (const [key, value] of Object.entries(over)) {
    const single = { v: 1, at, layers: { [key]: value } };
    assert.deepEqual(parseConditionsV1(single), { ok: true, value: single });
  }
  expectSnapshot({ ...input, layers: over }, { v: 1, missing: 'too large' });
});

// An exception at either input boundary must not escape into the writer.
test('C4: isolates an unreadable layer and fails closed on an unreadable input', () => {
  const layers = { ...full, get wind() { throw new Error('unreadable layer'); } };
  expectSnapshot({ ...input, layers },
    { v: 1, at, layers: { ...full, wind: { missing: 'invalid value' } } });
  expectSnapshot(null, { v: 1, missing: 'too large' });
});
