import test from 'node:test';
import assert from 'node:assert/strict';
import {formatCoordinate, formatCoordinates} from '../dist/coordinates.js';
import {configureStore, coordinates, loadCoordinateFormat, setCoordinateFormat, STORAGE_KEYS, syncFromURL} from '../web/state.ts';

test('three display formats and all hemispheres', () => {
  assert.equal(formatCoordinates(35.125, -120.5), '35.12500° N, 120.50000° W');
  assert.equal(formatCoordinates(-35.125, 120.5, 'ddm'), '35° 07.500′ S, 120° 30.000′ E');
  assert.equal(formatCoordinates(35.125, -120.5, 'dms'), '35° 07′ 30.00″ N, 120° 30′ 00.00″ W');
});

test('rounding carries without 60 minutes or seconds at poles and antimeridian', () => {
  for (const [axis, boundary] of [['latitude', 90], ['longitude', 180]]) {
    for (const sign of [1, -1]) {
      const suffix = axis === 'latitude' ? (sign > 0 ? 'N' : 'S') : (sign > 0 ? 'E' : 'W');
      for (const value of [boundary, boundary - 0.0000001]) {
        assert.equal(formatCoordinate(value * sign, axis, 'ddm'), `${boundary}° 00.000′ ${suffix}`);
        assert.equal(formatCoordinate(value * sign, axis, 'dms'), `${boundary}° 00′ 00.00″ ${suffix}`);
        assert.equal(formatCoordinate(value * sign, axis), `${boundary}.00000° ${suffix}`);
      }
    }
  }
  assert.equal(formatCoordinate(12 + 59.999999 / 60, 'latitude', 'ddm'), '13° 00.000′ N');
  assert.equal(formatCoordinate(12 + 34 / 60 + 59.9999 / 3600, 'latitude', 'dms'), '12° 35′ 00.00″ N');
});

test('zero and tiny values retain their supplied hemisphere, invalid positions are absent', () => {
  for (const mode of ['dd', 'ddm', 'dms']) {
    for (const axis of ['latitude', 'longitude']) {
      assert.match(formatCoordinate(0, axis, mode), axis === 'latitude' ? / N$/ : / E$/);
      for (const n of [-0, -0.000000001]) assert.match(formatCoordinate(n, axis, mode), axis === 'latitude' ? / S$/ : / W$/);
      for (const n of [NaN, Infinity, -Infinity, 181]) assert.equal(formatCoordinate(n, axis, mode), '—');
    }
  }
  assert.equal(formatCoordinate(91, 'latitude'), '—');
});

test('format persists, rejects malformed storage and survives navigation with blocked storage', () => {
  const saved = new Map();
  configureStore({storage: {getItem: k => saved.get(k) ?? null, setItem: (k, v) => saved.set(k, v)}});
  for (const mode of ['dd', 'ddm', 'dms']) {
    setCoordinateFormat(mode);
    assert.equal(saved.get(STORAGE_KEYS.coordinates), mode);
    coordinates.value = 'dd'; loadCoordinateFormat(); assert.equal(coordinates.value, mode);
  }
  saved.set(STORAGE_KEYS.coordinates, 'bad'); loadCoordinateFormat(); assert.equal(coordinates.value, 'dd');
  configureStore({storage: {getItem() { throw Error('blocked'); }, setItem() { throw Error('blocked'); }}});
  setCoordinateFormat('dms'); syncFromURL('https://example.org/?region=test'); assert.equal(coordinates.value, 'dms');
  loadCoordinateFormat(); assert.equal(coordinates.value, 'dd');
  configureStore({storage: null});
});
