// RF1500-22: equivalent +180/-180 longitudes give the same approximate shoreline distance.
import test from 'node:test';
import assert from 'node:assert/strict';
import {linesOf, yardsFromShore} from '../web/shore-distance.ts';

const YD = 111_320 / 0.9144;
const fc = (...coords) => ({type: 'FeatureCollection', features: coords.map(c => ({type: 'Feature', properties: {}, geometry: {type: 'LineString', coordinates: c}}))});
const near = (a, b, tol, msg) => assert.ok(Math.abs(a - b) <= tol, `${msg}: ${a} vs ${b}`);
const at = (lines, longitude, latitude = 0) => yardsFromShore({latitude, longitude}, lines);

test('seam_same_position_is_zero', () => {
  for (const lon of [-180, 180]) {
    const lines = linesOf(fc([[lon, -1], [lon, 1]]));
    near(at(lines, 180), 0, 1e-6, `source ${lon} query 180`);
    near(at(lines, -180), 0, 1e-6, `source ${lon} query -180`);
  }
});

test('seam_nearby_opposite_side', () => {
  const want = 0.02 * YD;
  const west = linesOf(fc([[-179.99, -1], [-179.99, 1]]));
  const east = linesOf(fc([[179.99, -1], [179.99, 1]]));
  near(at(west, 179.99), want, 1e-5, 'east query');
  near(at(east, -179.99), want, 1e-5, 'west query');
});

test('seam_endpoint_projection', () => {
  const lines = linesOf(fc([[-180, 0.01], [-180, 0.02]]));
  near(at(lines, 180), 0.01 * YD, 1e-6, 'east');
  near(at(lines, -180), 0.01 * YD, 1e-6, 'west');
  // two-axis offset: query 0.01 deg east of the seam, 0 lat; endpoint (-180, 0.01) is 0.01 east-equivalent... lon gap 0.01, lat gap 0.01
  const off = at(linesOf(fc([[-179.99, 0.01], [-179.99, 0.02]])), 180);
  near(off, Math.hypot(0.01 * YD, 0.01 * YD), 1e-5, 'hypotenuse');
});

test('seam_reversal_and_split_members', () => {
  const a = [[-179.99, 0.01], [-179.99, 0.02]], b = [[-179.98, 0.03], [-179.98, 0.05]], dup = [[-179.99, 0.01], [-179.99, 0.01], [-179.99, 0.02]];
  const base = at(linesOf(fc(a, b)), 179.99);
  near(at(linesOf(fc(b, a)), 179.99), base, 1e-6, 'reordered');
  near(at(linesOf(fc([...a].reverse(), [...b].reverse())), 179.99), base, 1e-6, 'reversed');
  near(at(linesOf(fc(dup, b)), 179.99), base, 1e-6, 'repeated vertices');
  const multi = {type: 'FeatureCollection', features: [{type: 'Feature', geometry: {type: 'MultiLineString', coordinates: [b, a]}}]};
  near(at(linesOf(multi), 179.99), base, 1e-6, 'multi');
});

test('opposite_meridian_does_not_bridge', () => {
  const fwd = at(linesOf(fc([[179, 0], [180, 0]])), 0);
  const rev = at(linesOf(fc([[180, 0], [179, 0]])), 0);
  assert.ok(fwd > 1_000_000, `forward ${fwd}`);
  assert.ok(rev > 1_000_000, `reverse ${rev}`);
});

test('ordinary_local_distance_and_null_unchanged', () => {
  const lat = 34, kx = YD * Math.cos(lat * Math.PI / 180);
  const lines = linesOf(fc([[-119.5, 33.9], [-119.5, 34.1]], [[-119.0, 34.0], [-118.9, 34.0]]));
  near(at(lines, -119.49, lat), 0.01 * kx, 1e-6, 'interior');
  near(at(linesOf(fc([[-119.5, 34.1], [-119.5, 34.2]])), -119.5, lat), 0.1 * YD, 1e-6, 'endpoint');
  near(at(linesOf(fc([[-119.0, 34.0], [-118.9, 34.0]], [[-119.499, 34.0], [-119.499, 34.1]])), -119.5, lat), 0.001 * kx, 1e-6, 'nearest not first');
  assert.equal(yardsFromShore({latitude: 0, longitude: 0}, []), null);
  assert.equal(yardsFromShore({latitude: 0, longitude: 0}, linesOf({})), null);
});

test('frozen_inputs_stay_unchanged', () => {
  const deep = o => { if (o && typeof o === 'object') { Object.values(o).forEach(deep); Object.freeze(o); } return o; };
  const json = deep(fc([[-180, -1, 5], [-180, 1, 5]]));
  const query = deep({latitude: 0, longitude: 180});
  const lines = linesOf(json);
  near(yardsFromShore(query, lines), 0, 1e-6, 'frozen');
  assert.deepEqual(lines, [[[-180, -1, 5], [-180, 1, 5]]]);
  assert.deepEqual(linesOf(fc([[181, 0], [182, 0]])), []);
  assert.deepEqual(linesOf(fc([[-180.5, 0], [-180, 0]])), []);
});
