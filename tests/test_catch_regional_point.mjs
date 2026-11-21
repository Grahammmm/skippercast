import test from 'node:test';
import assert from 'node:assert/strict';
import { POSITION_ONLY_LAYERS, positionlessLayers, regionalPoint } from '../server/catch-regional-point.ts';
import { parseConditionsV1 } from '../server/conditions-v1.ts';

const first = Object.freeze({ id: 'outer', latitude: 12, longitude: -34 });
const second = Object.freeze({ id: 'inner', latitude: 13, longitude: -35 });
const defaultPoint = { pointId: 'outer', lat: 12, lon: -34, via: 'region-default', basis: 'region' };
const missingPoint = { missing: 'no forecast point' };

// Defaulting before scanning the whole list would miss the later trip point.
test('C1: a valid trip point takes priority over the first configured point', () => {
  assert.deepEqual(regionalPoint({ forecast_points: [first, second] }, 'inner'),
    { pointId: 'inner', lat: 13, lon: -35, via: 'trip-point', basis: 'region' });
});

// Choosing the last point or sorting by ID would both pick inner over outer.
test('C1: an absent or another-region trip ID uses the first valid point in config order', () => {
  for (const trip of [null, 'other-region-point']) {
    assert.deepEqual(regionalPoint({ forecast_points: [first, second] }, trip), defaultPoint);
  }
});

// Inclusive limits admit the poles and antimeridian on both signs.
test('C1: coordinates exactly on the geographic limits are valid', () => {
  for (const [lat, lon] of [[90, -180], [-90, 180]]) {
    assert.deepEqual(regionalPoint({ forecast_points: [{ id: 'edge', latitude: lat, longitude: lon }] }, 'edge'),
      { pointId: 'edge', lat, lon, via: 'trip-point', basis: 'region' });
  }
});

// Matching the ID alone, coercing numbers, or checking only one axis could select a bad point.
test('C1: skip trip and default candidates with non-finite, non-numeric, or out-of-range coordinates', () => {
  for (const [field, invalid] of [
    ['latitude', [NaN, Infinity, 90.01, -90.01, '12']],
    ['longitude', [NaN, -Infinity, 180.01, -180.01, '-34']],
  ]) {
    for (const value of invalid) {
      const bad = { ...second, [field]: value };
      for (const trip of ['inner', null]) {
        assert.deepEqual(regionalPoint({ forecast_points: [bad, first] }, trip), defaultPoint);
      }
    }
  }
});

// No default may be manufactured from an empty list or an invalid entry.
test('C1: an empty or all-invalid list has no forecast point', () => {
  assert.deepEqual(regionalPoint({ forecast_points: [] }, null), missingPoint);
  assert.deepEqual(regionalPoint({ forecast_points: [{ ...first, longitude: 181 }] }, 'outer'), missingPoint);
});

// Including regional keys here would mask their separately sourced readings.
test('C2: only the ordered position-only keys get fresh missing values accepted by the parser', () => {
  assert.deepEqual(POSITION_ONLY_LAYERS, ['water_temp', 'contrast', 'chlorophyll', 'front_nm', 'current']);
  const expected = {
    water_temp: { missing: 'no position' },
    contrast: { missing: 'no position' },
    chlorophyll: { missing: 'no position' },
    front_nm: { missing: 'no position' },
    current: { missing: 'no position' },
  };
  const layers = positionlessLayers();
  const fresh = positionlessLayers();
  assert.deepEqual(layers, expected);
  assert.deepEqual(fresh, expected);
  assert.notStrictEqual(layers, fresh);
  for (const key of POSITION_ONLY_LAYERS) assert.notStrictEqual(layers[key], fresh[key]);
  const at = '2024-02-29T01:02:03Z';
  assert.deepEqual(parseConditionsV1({ v: 1, at, layers }), { ok: true, value: { v: 1, at, layers: expected } });
});

const unreadable = () => { throw new Error('unreadable fixture'); };

// Array-like objects are not config lists; even checking a revoked proxy can throw.
test('C3: malformed or unreadable region and list shapes have no forecast point', () => {
  const revoked = Proxy.revocable([], {});
  revoked.revoke();
  for (const region of [null, undefined, 1, {}, { forecast_points: null }, { forecast_points: 'not a list' },
    { forecast_points: { 0: first, length: 1 } }, { get forecast_points() { return unreadable(); } },
    { forecast_points: revoked.proxy }, { forecast_points: new Proxy([first], { get: unreadable }) },
    { forecast_points: new Proxy([first], { get: () => '1' }) },
  ]) {
    assert.deepEqual(regionalPoint(region, 'outer'), missingPoint);
  }
});

// A throwing slot or field must not abort selection of an otherwise valid point.
test('C3: malformed entries and throwing getters do not hide readable neighbours', () => {
  const points = [null, 7, 'outer', { latitude: 12, longitude: -34 },
    { ...second, get longitude() { return unreadable(); } }, first, second];
  Object.defineProperty(points, 0, { get: unreadable });
  assert.deepEqual(regionalPoint({ forecast_points: points }, null), defaultPoint);
  assert.deepEqual(regionalPoint({ forecast_points: points }, 'inner'),
    { pointId: 'inner', lat: 13, lon: -35, via: 'trip-point', basis: 'region' });
});

// Sorting the caller's config or annotating its points would mutate frozen inputs.
test('C3: point selection leaves the region, list, and points unchanged', () => {
  const region = Object.freeze({ forecast_points: Object.freeze([first, second]) });
  assert.deepEqual(regionalPoint(region, 'unknown'), defaultPoint);
  assert.deepEqual(region, { forecast_points: [
    { id: 'outer', latitude: 12, longitude: -34 },
    { id: 'inner', latitude: 13, longitude: -35 },
  ] });
});
