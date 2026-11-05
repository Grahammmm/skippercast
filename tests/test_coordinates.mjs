import test from 'node:test';
import assert from 'node:assert/strict';
import {formatCoordinate, formatCoordinates, parseCoordinate} from '../dist/coordinates.js';
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

test('parseCoordinate reads chartplotter forms', () => {
  const near = (text, axis, want) => { const r = parseCoordinate(text, axis); assert.ok(Math.abs(r.value - want) < 1e-9, `${text} -> ${JSON.stringify(r)}`); };
  near('35 21.456 N', 'latitude', 35 + 21.456 / 60);
  near('35° 21.456′ N', 'latitude', 35 + 21.456 / 60);
  near('N35 21.456', 'latitude', 35 + 21.456 / 60);
  near('n 35 21.456', 'latitude', 35 + 21.456 / 60);
  near('-120 51.5', 'longitude', -(120 + 51.5 / 60));
  near("35d21'27.36\"N", 'latitude', 35 + 21 / 60 + 27.36 / 3600);
  near('35°21′27.36″N', 'latitude', 35 + 21 / 60 + 27.36 / 3600);
  near("35 21' 27.36''  S", 'latitude', -(35 + 21 / 60 + 27.36 / 3600));
  near('35.3576', 'latitude', 35.3576);
  near('+35.3576', 'latitude', 35.3576);
  near('120.5 W', 'longitude', -120.5);
  near('W 120.5°', 'longitude', -120.5);
  near('90 N', 'latitude', 90);
  near('180 W', 'longitude', -180);
  assert.ok(Object.is(parseCoordinate('0 S', 'latitude').value, -0));
});

test('parseCoordinate refuses with a reason in words', () => {
  const bad = [['35 60.0 N', 'latitude'], ['35 21 60 N', 'latitude'], ['35 61 N', 'latitude'], ['-35 N', 'latitude'], ['N -35', 'latitude'],
    ['35 E', 'latitude'], ['W 35', 'latitude'], ['120 N', 'longitude'], ['91 N', 'latitude'], ['90 0.1 N', 'latitude'],
    ['181 W', 'longitude'], ['-181', 'longitude'], ['', 'latitude'], ['   ', 'latitude'], ['abc', 'latitude'], ['NaN', 'latitude'],
    ['Infinity', 'latitude'], ['1e400', 'latitude'], ['35 -21 N', 'latitude'], ['35.5 21 N', 'latitude'], ['35 21.5 10 N', 'latitude'],
    ['N 35 S', 'latitude'], ['35 21 27 10 N', 'latitude'], ['X 35', 'latitude'], ['N', 'latitude'], [null, 'latitude']];
  for (const [text, axis] of bad) {
    const r = parseCoordinate(text, axis);
    assert.ok(!('value' in r), `${text} should be refused`);
    assert.match(r.error, /^[A-Z][^\n]*[.;]$/, `${text}: ${r.error}`);
    assert.ok(!/\bat\b.*:\d+|Error/.test(r.error));
  }
});

test('every formatCoordinate output parses back within the format precision', () => {
  const precision = {dd: 0.000005, ddm: 0.0005 / 60, dms: 0.005 / 3600};
  const lats = [0, -0, 90, -90], lons = [0, -0, 180, -180];
  for (let v = -89.5; v <= 89.5; v += 7.3) lats.push(v);
  for (let v = -179.5; v <= 179.5; v += 13.1) lons.push(v);
  lats.push(35.35760, 12 + 59.999999 / 60); lons.push(-120.858333, 179.9999999);
  for (const format of ['dd', 'ddm', 'dms']) {
    for (const [values, axis] of [[lats, 'latitude'], [lons, 'longitude']]) {
      for (const v of values) {
        const text = formatCoordinate(v, axis, format), r = parseCoordinate(text, axis);
        assert.ok('value' in r, `${text}: ${r.error}`);
        assert.ok(Math.abs(r.value - v) <= precision[format] + 1e-12, `${format} ${v} -> ${text} -> ${r.value}`);
        assert.equal(Object.is(r.value, -0) || r.value < 0, Object.is(v, -0) || v < 0, `sign of ${text}`);
      }
    }
  }
});
