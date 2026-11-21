import test from 'node:test';
import assert from 'node:assert/strict';
import { conditionsLine } from '../web/catch-conditions-line.ts';

const at = '2024-02-29T12:00:00Z';
const snapshot = layers => ({ v: 1, at, layers });

// Nullish input is absence, not a malformed snapshot.
test('C1: null and undefined return none', () => {
  assert.deepEqual(conditionsLine(null), { state: 'none' });
  assert.deepEqual(conditionsLine(undefined), { state: 'none' });
});

// Invalid versions and layers must not look like usable data or be salvaged in part.
test('C1: parser failures return invalid', () => {
  assert.deepEqual(conditionsLine({ ...snapshot({}), v: 2 }), { state: 'invalid' });
  assert.deepEqual(conditionsLine(snapshot({
    tide: { stage: 'ebb', height_ft: 1.2, station: 'fixture station' },
    wind: { kn: 9, from_deg: 320, run: 'wind run', valid_at: 'not a date' },
  })), { state: 'invalid' });
});

// Neither sentinel is an empty ready snapshot; whole missing retains its reason.
test('C1: pending and whole missing are separate states', () => {
  assert.deepEqual(conditionsLine({ v: 1, pending: true }), { state: 'pending' });
  assert.deepEqual(conditionsLine({ v: 1, missing: 'no region' }), { state: 'missing', reason: 'no region' });
});

test('C1: empty layers are ready, not missing', () => {
  assert.deepEqual(conditionsLine(snapshot({})), { state: 'ready', at, items: [] });
});

// Input order, metadata left in values, or reuse of another layer's timestamp would break this projection.
test('C2: all eight shuffled layers return fixed order and exact provenance', () => {
  assert.deepEqual(conditionsLine(snapshot({
    wind: { kn: 9, from_deg: 320, run: 'wind run', valid_at: '2024-02-29T15:00:00Z' },
    chlorophyll: { value: 2.4, unit: 'mg/m3', product: 'OCI', sample_at: '2024-02-29T09:00:00Z' },
    tide: { stage: 'ebb', height_ft: 1.2, station: 'fixture station' },
    current: { kn: 0.3, toward_deg: 0, run: 'current run', valid_at: '2024-02-29T14:00:00Z' },
    front_nm: { value: 2.1, product: 'fronts', sample_at: '2024-02-29T10:00:00Z' },
    water_temp: { value: 56.9, unit: 'F', product: 'SST', sample_at: '2024-02-28T06:00:00Z' },
    swell: { ft: 5, period_s: 11, from_deg: 290, run: 'swell run', valid_at: '2024-02-29T13:00:00Z' },
    contrast: { value: -0.4, unit: 'F/nm', product: 'gradient', sample_at: '2024-02-29T11:00:00Z' },
  })), {
    state: 'ready', at, items: [
      { key: 'water_temp', kind: 'value', values: { value: 56.9, unit: 'F' },
        source: { product: 'SST' }, time: '2024-02-28T06:00:00Z', offsetHours: -30 },
      { key: 'contrast', kind: 'value', values: { value: -0.4, unit: 'F/nm' },
        source: { product: 'gradient' }, time: '2024-02-29T11:00:00Z', offsetHours: -1 },
      { key: 'front_nm', kind: 'value', values: { value: 2.1 },
        source: { product: 'fronts' }, time: '2024-02-29T10:00:00Z', offsetHours: -2 },
      { key: 'chlorophyll', kind: 'value', values: { value: 2.4, unit: 'mg/m3' },
        source: { product: 'OCI' }, time: '2024-02-29T09:00:00Z', offsetHours: -3 },
      { key: 'current', kind: 'value', values: { kn: 0.3, toward_deg: 0 },
        source: { run: 'current run' }, time: '2024-02-29T14:00:00Z', offsetHours: 2 },
      { key: 'swell', kind: 'value', values: { ft: 5, period_s: 11, from_deg: 290 },
        source: { run: 'swell run' }, time: '2024-02-29T13:00:00Z', offsetHours: 1 },
      { key: 'wind', kind: 'value', values: { kn: 9, from_deg: 320 },
        source: { run: 'wind run' }, time: '2024-02-29T15:00:00Z', offsetHours: 3 },
      { key: 'tide', kind: 'value', values: { stage: 'ebb', height_ft: 1.2 },
        source: { station: 'fixture station' }, time: null, offsetHours: null },
    ],
  });
});

// Missing items occupy their ordered slots; never fabricate lines for absent keys.
test('C2: two explicit missing layers and a value, with other layers absent', () => {
  assert.deepEqual(conditionsLine(snapshot({
    wind: { missing: 'not archived' },
    chlorophyll: { value: 0, unit: 'mg/m3', product: 'OCI', sample_at: at },
    water_temp: { missing: 'cloud' },
  })), {
    state: 'ready', at, items: [
      { key: 'water_temp', kind: 'missing', reason: 'cloud' },
      { key: 'chlorophyll', kind: 'value', values: { value: 0, unit: 'mg/m3' },
        source: { product: 'OCI' }, time: at, offsetHours: 0 },
      { key: 'wind', kind: 'missing', reason: 'not archived' },
    ],
  });
});

// Half hours distinguish Math.round from truncation and symmetric rounding; freezing catches in-place extraction.
test('C3: offsets round signed half hours without changing the input', () => {
  const sample = '2024-02-29T10:30:00Z';
  const valid = '2024-02-29T13:30:00Z';
  const raw = Object.freeze(snapshot(Object.freeze({
    front_nm: Object.freeze({ value: 2.1, product: 'fronts', sample_at: sample }),
    current: Object.freeze({ kn: 0.3, toward_deg: 0, run: 'current run', valid_at: valid }),
  })));
  assert.deepEqual(conditionsLine(raw), {
    state: 'ready', at, items: [
      { key: 'front_nm', kind: 'value', values: { value: 2.1 },
        source: { product: 'fronts' }, time: sample, offsetHours: -1 },
      { key: 'current', kind: 'value', values: { kn: 0.3, toward_deg: 0 },
        source: { run: 'current run' }, time: valid, offsetHours: 2 },
    ],
  });
});

// Reading raw properties before validation could throw on invalid unknown input.
test('C3: a revoked proxy returns invalid without throwing', () => {
  const { proxy, revoke } = Proxy.revocable({}, {});
  revoke();
  assert.deepEqual(conditionsLine(proxy), { state: 'invalid' });
});
