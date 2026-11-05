import test from 'node:test';
import assert from 'node:assert/strict';
import {featuresGPX, geometryTrack} from '../dist/gpx.js';
import {checkGpx} from '../web/gpx-check.ts';
import {createPlanner} from '../web/planner.ts';

const wpt = (latitude, longitude) => ({id: 'u1', name: 'Tiny', category: 'other', latitude, longitude, user_waypoint: true});
const gpx = pts => featuresGPX({}, {selected: pts, waypoints: pts, areas: [], drifts: []}, 'Day');
const attrs = xml => [...xml.matchAll(/(?:lat|lon)="([^"]*)"/g)].map(m => m[1]);

for (const [lat, lon, expLat, expLon] of [
  [1e-7, -1e-7, '0.0000001', '-0.0000001'],
  [-1e-7, 1e-7, '-0.0000001', '0.0000001'],
  [1.2345678901234568e-7, -1.2345678901234568e-7, '0.00000012345678901234568', '-0.00000012345678901234568'],
  [0.000001, 0.0000001, '0.000001', '0.0000001'],
  [Number.MIN_VALUE, -Number.MIN_VALUE, '0.' + '0'.repeat(323) + '5', '-0.' + '0'.repeat(323) + '5'],
  [0, -0, '0', '0'],
  [90, -180, '90', '-180'],
  [12.5, -122.25, '12.5', '-122.25'],
]) {
  test(`waypoint ${lat},${lon} is written as an XML decimal and round-trips`, () => {
    const a = attrs(gpx([wpt(lat, lon)]));
    assert.deepEqual(a, [expLat, expLon]);
    assert.ok(a.every(v => /^-?\d+(\.\d+)?$/.test(v)));
    assert.equal(Number(a[0]), Object.is(lat, -0) ? 0 : lat);
    assert.equal(Number(a[1]), Object.is(lon, -0) ? 0 : lon);
  });
}

test('ranked/atlas waypoint branches and tracks avoid exponent notation', () => {
  const atlas = {id: 'a1', name: 'Atlas', latitude: 1e-7, longitude: -1e-7, neighborhood_depth_ft: [100, 200], source_url: 'https://example.org/s'};
  assert.deepEqual(attrs(gpx([atlas])), ['0.0000001', '-0.0000001']);
  const line = {type: 'LineString', coordinates: [[-1e-7, 1e-7], [2e-7, -2e-7]]};
  const copy = structuredClone(line);
  assert.deepEqual(attrs(geometryTrack('T', 'd', line)), ['0.0000001', '-0.0000001', '-0.0000002', '0.0000002']);
  assert.deepEqual(line, copy);
  const ring = [[1e-7, 1e-7], [1, 1e-7], [1, 1], [1e-7, 1e-7]];
  const a = attrs(geometryTrack('P', 'd', {type: 'MultiPolygon', coordinates: [[ring]]}));
  assert.equal(a.length, 8); assert.ok(a.every(v => !/e/i.test(v)));
});

test('existing refusals and escaping are preserved', () => {
  assert.throws(() => geometryTrack('T', 'd', {type: 'LineString', coordinates: [[0, 0], [NaN, 1]]}), /Invalid export geometry/);
  assert.throws(() => geometryTrack('T', 'd', {type: 'LineString', coordinates: [[0, 0]]}), /Invalid export geometry/);
  assert.match(gpx([{...wpt(1e-7, 1e-7), name: '<b>&"'}]), /<name>&lt;b&gt;&amp;&quot;<\/name>/);
});

test('real planner export of a near-zero waypoint is decimal and passes the delivery check', async () => {
  const region = {id: 'test-coast', name: 'Test Coast', timezone: 'UTC', mpa: {bounds: [-1, -1, 1, 1]}};
  const screen = {ready: () => true, pointAllowed: () => true, geometryAllowed: () => true, exportExclusions: () => ({features: [], checked_at: new Date().toISOString()})};
  const map = {getSize: () => ({x: 10, y: 10}), getBounds: () => ({getWest: () => -1, getEast: () => 1, getNorth: () => 1, getSouth: () => -1})};
  const store = new Map();
  const p = createPlanner({atlas: {targets: [], areas: [], drifts: []}, screen, region, map, getVisible: () => [],
    storage: {getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, v)}, now: () => new Date(),
    loadPorts: async () => ({ports: []}), emit() {}, nav: {open() {}, showMap() {}, conditions() {}}});
  try {
    assert.ok(p.addPlace({id: 'survey:tiny', name: 'Near zero', latitude: 1e-7, longitude: -1e-7}));
    const xml = await (await p.exportFile('gpx')).text();
    assert.match(xml, /lat="0\.0000001" lon="-0\.0000001"/);
    assert.equal(checkGpx(xml, {waypoints: 1}).ok, true);
  } finally { p.dispose(); }
});
