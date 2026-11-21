import test from 'node:test';
import assert from 'node:assert/strict';
import { CONDITIONS_MAX_BYTES, parseConditionsV1 } from '../server/conditions-v1.ts';

const at = '2024-02-29T01:02:03Z';
const sample_at = '2024-02-28T18:00:00.125Z';
const valid_at = '2024-02-29T01:00Z';
const snapshot = (layers = {}) => ({ v: 1, at, layers });
const fullLayers = {
  water_temp: { value: 56.9, unit: 'F', product: 'SST', sample_at },
  contrast: { value: -0.4, unit: 'F/nm', product: 'SST', sample_at },
  chlorophyll: { value: 0, unit: 'mg/m3', product: 'OCI', sample_at },
  front_nm: { value: 0, product: 'fronts', sample_at },
  current: { kn: 0.3, toward_deg: 0, run: 'current run', valid_at },
  swell: { ft: 5, period_s: 11, from_deg: 359.9, run: 'swell run', valid_at },
  wind: { kn: 9, from_deg: 320, run: 'wind run', valid_at },
  tide: { stage: 'ebb', height_ft: -1.2, station: 'fixture station' },
};
const accept = raw => {
  const result = parseConditionsV1(raw);
  assert.deepEqual(result, { ok: true, value: raw });
  assert.notEqual(result.value, raw);
};
const reject = (raw, error) => assert.deepEqual(parseConditionsV1(raw), { ok: false, error });

// An accidental limit change would alter the persisted-format budget.
test('C1: exported byte limit', () => assert.equal(CONDITIONS_MAX_BYTES, 4096));

// All success branches must use the same envelope, including the sentinels and empty layers.
test('C2: accept each snapshot variant', () => {
  accept({ v: 1, pending: true });
  accept({ v: 1, missing: 'no region' });
  accept(snapshot());
});

// Non-record input and failed reflection must return a path, not escape as an exception.
test('C2: non-records and throwing proxies return errors', () => {
  for (const value of [null, undefined, 1, 'snapshot', [], new Date(at)]) reject(value, '$');
  const revoked = Proxy.revocable({}, {});
  revoked.revoke();
  reject(revoked.proxy, '$');
  reject(snapshot({ wind: revoked.proxy }), 'layers.wind');
});

// Accessors are not data; none should execute even if they could return a valid value.
test('C2: an accessor is rejected at its field path without invocation', () => {
  let invoked = false;
  const raw = { v: 1, get pending() { invoked = true; return true; } };
  reject(raw, 'pending');
  assert.equal(invoked, false);
});

// Copying just the root would leave mutable input layer records attached to the result.
test('C3: all full layers are accepted and deeply copied', () => {
  const raw = snapshot(structuredClone(fullLayers));
  const result = parseConditionsV1(raw);
  assert.deepEqual(result, { ok: true, value: snapshot(fullLayers) });
  assert.notEqual(result.value, raw);
  assert.notEqual(result.value.layers, raw.layers);
  for (const key of Object.keys(fullLayers)) assert.notEqual(result.value.layers[key], raw.layers[key], key);
});

// A validator that requires data fields even in a missing layer would discard valid snapshots.
test('C3: every layer supports the missing form and can appear alone', () => {
  for (const key of Object.keys(fullLayers)) accept(snapshot({ [key]: { missing: 'not archived' } }));
});

// Open objects would silently admit unversioned data or allow two variants to overlap.
test('C3: reject extra fields at each level and in each variant', () => {
  reject({ v: 1, pending: true, missing: 'no region' }, 'missing');
  reject({ v: 1, missing: 'no region', pending_since: at }, 'pending_since');
  reject({ ...snapshot(), extra: true }, 'extra');
  reject(snapshot({ cloud: { missing: 'unknown' } }), 'layers.cloud');
  reject(snapshot({ ['__proto__']: {} }), 'layers.__proto__');
  reject(snapshot({ water_temp: { ...fullLayers.water_temp, extra: 1 } }), 'layers.water_temp.extra');
  reject(snapshot({ tide: { missing: 'not archived', station: 'fixture station' } }), 'layers.tide.station');
  reject(Object.defineProperty(snapshot(), 'hidden', { value: true }), 'hidden');
  reject({ ...snapshot(), [Symbol('extra')]: true }, 'Symbol(extra)');
});

// Truthy or coerced discriminants, absent fields, and non-object containers must not validate.
test('C3: reject malformed variants and layer records at the first failing path', () => {
  for (const v of [2, '1', undefined]) reject({ v, pending: true }, 'v');
  reject({ pending: true }, 'v');
  reject({ v: 1, pending: false }, 'pending');
  reject({ v: 1 }, 'at');
  reject({ v: 1, at }, 'layers');
  for (const layers of [null, [], 'empty']) reject(snapshot(layers), 'layers');
  reject(snapshot({ wind: null }), 'layers.wind');
  reject(snapshot({ wind: { run: 'wind run', from_deg: 360 } }), 'layers.wind.kn');
  for (const [key, layer] of Object.entries(fullLayers)) {
    for (const field of Object.keys(layer)) {
      const incomplete = { ...layer };
      delete incomplete[field];
      reject(snapshot({ [key]: incomplete }), `layers.${key}.${field}`);
    }
  }
});

// Permissive date parsing would accept offsets, non-ISO text, and rolled calendar dates.
test('C3: timestamps must be parseable ISO UTC dates ending in Z', () => {
  for (const bad of ['yesterday', '2024-02-29T01:02:03+00:00', '2024/02/29 01:02:03Z',
    '2024-02-30T01:02:03Z', '2024-02-29T25:02:03Z', `${at}\n`]) {
    reject({ ...snapshot(), at: bad }, 'at');
  }
  reject(snapshot({ front_nm: { ...fullLayers.front_nm, sample_at: '2024-13-01T00:00:00Z' } }), 'layers.front_nm.sample_at');
  reject(snapshot({ swell: { ...fullLayers.swell, valid_at: '2024-02-29T01:02:03z' } }), 'layers.swell.valid_at');
});

// JSON would otherwise silently serialize nonfinite scalars as null or accept the wrong units.
test('C3: numbers must be finite, and observed units must match', () => {
  for (const [key, layer] of Object.entries(fullLayers)) {
    for (const [field, value] of Object.entries(layer)) {
      if (typeof value !== 'number') continue;
      for (const bad of [NaN, Infinity, -Infinity, String(value)]) {
        reject(snapshot({ [key]: { ...layer, [field]: bad } }), `layers.${key}.${field}`);
      }
    }
    if ('unit' in layer) reject(snapshot({ [key]: { ...layer, unit: 'C' } }), `layers.${key}.unit`);
  }
});

// Distance and concentration cannot be negative; bearings cannot wrap past a full turn.
test('C3: enforce nonnegative measurements and half-open bearings', () => {
  for (const key of ['chlorophyll', 'front_nm']) {
    reject(snapshot({ [key]: { ...fullLayers[key], value: -0.001 } }), `layers.${key}.value`);
  }
  for (const [key, field] of [['current', 'toward_deg'], ['swell', 'from_deg'], ['wind', 'from_deg']]) {
    for (const bad of [-0.01, 360]) reject(snapshot({ [key]: { ...fullLayers[key], [field]: bad } }), `layers.${key}.${field}`);
  }
});

// Bounds must apply equally to both sentinel forms and every provenance text field.
test('C3: require non-empty bounded text', () => {
  const cases = [
    [missing => ({ v: 1, missing }), 'missing'],
    [missing => snapshot({ wind: { missing } }), 'layers.wind.missing'],
    ...[['water_temp', 'product'], ['current', 'run'], ['tide', 'stage'], ['tide', 'station']]
      .map(([key, field]) => [value => snapshot({ [key]: { ...fullLayers[key], [field]: value } }), `layers.${key}.${field}`]),
  ];
  for (const [build, path] of cases) {
    accept(build('a'.repeat(200)));
    for (const bad of ['', 'a'.repeat(201), 42]) reject(build(bad), path);
  }
  accept({ v: 1, missing: '🌊'.repeat(200) });
  reject({ v: 1, missing: '🌊'.repeat(201) }, 'missing');
});

// A code-unit check, an off-by-one comparison, or checking size before the shape would fail here.
test('C3: UTF-8 size boundary', () => {
  const layers = Object.fromEntries(Object.keys(fullLayers).map((key, i) => [key, { missing: '界'.repeat(i < 6 ? 200 : 1) }]));
  const raw = snapshot(layers);
  const bytes = value => new TextEncoder().encode(JSON.stringify(value)).byteLength;
  const padding = 4096 - bytes(raw);
  layers.wind.missing += 'x'.repeat(Math.floor(padding / 2));
  layers.tide.missing += 'x'.repeat(Math.ceil(padding / 2));
  assert.equal(bytes(raw), 4096);
  assert.ok(JSON.stringify(raw).length < 4096);
  accept(raw);

  layers.tide.missing += 'x';
  assert.equal(bytes(raw), 4097);
  assert.ok(JSON.stringify(raw).length < 4096);
  reject(raw, '$');
  reject({ ...raw, at: '2024-02-30T01:02:03Z' }, 'at');
});
