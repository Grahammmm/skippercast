import test from 'node:test';
import assert from 'node:assert/strict';
import {globSync, readFileSync} from 'node:fs';
import {regionForEntry, regionList} from '../server/catch-region.ts';

// Rejecting legal world edges or sorting this projection would drop or reorder docs.
test('C1: keeps valid bounds and ids in input order', () => {
  const bounds = Object.freeze([-180, -90, 180, 90]);
  const docs = Object.freeze([
    Object.freeze({id: 'z-2', bounds, unrelated: true}),
    null,
    {id: 'a', bounds: [0, 1, 2, 3]},
    {id: 'z-2', bounds: [0, 0, 1, 1]},
  ]);
  assert.deepEqual(regionList(docs), {
    regions: [
      {id: 'z-2', bounds: [-180, -90, 180, 90]},
      {id: 'a', bounds: [0, 1, 2, 3]},
      {id: 'z-2', bounds: [0, 0, 1, 1]},
    ],
    skipped: 1,
  });
});

// Coercing keys or coordinates, ignoring an axis, or checking only shape admits bad docs.
test('C1: counts every malformed document without throwing', () => {
  const bounds = [0, 0, 1, 1];
  const invalid = [
    undefined, false, 1, 'region', [], {}, {id: 'ok'}, {bounds},
    ...[1, '', 'Upper', 'has space', 'under_score', 'a/b'].map(id => ({id, bounds})),
    ...[
      null, {0: 0, 1: 0, 2: 1, 3: 1, length: 4}, [0, 0, 1], [0, 0, 1, 1, 2],
      [0, , 1, 1], ['0', 0, 1, 1], [0, 0, NaN, 1], [0, 0, 1, Infinity],
      [-181, 0, 1, 1], [0, -91, 1, 1], [0, 0, 181, 1], [0, 0, 1, 91],
      [1, 0, 1, 1], [2, 0, 1, 1], [0, 1, 1, 1], [0, 2, 1, 1],
    ].map(bounds => ({id: 'ok', bounds})),
    {get id() { throw new Error('unreadable'); }},
  ];
  assert.deepEqual(regionList(invalid), {regions: [], skipped: invalid.length});
  assert.deepEqual(regionList([]), {regions: [], skipped: 0});
});

const regions = [
  {id: 'wide', bounds: [0, 0, 10, 10]},
  {id: 'z-bay', bounds: [2, 3, 4, 4]},
  {id: 'a-bay', bounds: [4, 3, 5, 5]},
  {id: 'far', bounds: [20, 20, 30, 30]},
];

// Treating a partial pair, a non-number or a boundary as a position suppresses trip fallback.
test('C2: rejects incomplete, non-finite and globally out-of-range positions', () => {
  for (const [lat, lon] of [
    [null, 3], [3, null], [NaN, 3], [3, NaN], [Infinity, 3], [3, -Infinity],
    ['3', 3], [3, '3'], [90, 3], [-90, 3], [91, 3], [3, 180], [3, -180], [3, -181],
  ]) {
    assert.deepEqual(regionForEntry({lat, lon, tripRegion: 'far'}, regions), {region: 'far', via: 'trip'}, String([lat, lon]));
  }
  assert.deepEqual(regionForEntry({lat: 89.99, lon: -179.99, tripRegion: 'far'}, regions), {missing: 'outside coverage'});
});

// A first-match scan would choose the wider bounds; swapping axes loses the bay.
test('C3: selects the smallest containing region and ignores a non-containing trip', () => {
  const point = {lat: 3.5, lon: 2.5};
  for (const tripRegion of [undefined, 'far', 'unknown']) {
    assert.deepEqual(regionForEntry({...point, tripRegion}, regions), {region: 'z-bay', via: 'position'});
  }
});

// Width or height alone ranks differently from area in these overlaps.
test('C3: compares bounds area rather than a single dimension', () => {
  const overlap = [
    {id: 'tall', bounds: [0, 0, 1, 6]},
    {id: 'wide', bounds: [0, 0, 6, 1]},
    {id: 'small', bounds: [0, 0, 2, 2]},
  ];
  assert.deepEqual(regionForEntry({lat: 0.5, lon: 0.5}, overlap), {region: 'small', via: 'position'});
});

// First/last wins or strict containment makes the shared-edge answer depend on order.
test('C3: includes a shared edge and breaks equal-area ties by id', () => {
  const point = {lat: 3, lon: 4};
  for (const order of [regions, [...regions].reverse()]) {
    assert.deepEqual(regionForEntry(point, order), {region: 'a-bay', via: 'position'});
    assert.deepEqual(regionForEntry({...point, tripRegion: 'z-bay'}, order), {region: 'z-bay', via: 'trip'});
  }
  assert.deepEqual(regionForEntry({lat: 4, lon: 2}, regions), {region: 'z-bay', via: 'position'});
});

// Ranking by area before checking the trip would pick a bay over its containing trip.
test('C3: prefers a containing trip even when its bounds are wider', () => {
  assert.deepEqual(regionForEntry({lat: 3.5, lon: 2.5, tripRegion: 'wide'}, [...regions].reverse()), {region: 'wide', via: 'trip'});
});

// An unconditional trip fallback would silently attach an out-of-coverage position.
test('C3: an uncovered position does not fall back to a trip', () => {
  for (const [lat, lon] of [[5, -1], [5, 11], [-1, 5], [11, 5]]) {
    for (const tripRegion of [undefined, 'wide']) {
      assert.deepEqual(regionForEntry({lat, lon, tripRegion}, regions), {missing: 'outside coverage'}, String([lat, lon]));
    }
  }
  assert.deepEqual(regionForEntry({lat: 0, lon: 0}, []), {missing: 'outside coverage'});
});

// Trusting the trip id alone would attach a stale region; ignoring it loses a known region.
test('C4: without a position, only a listed trip supplies the region', () => {
  const noPosition = {lat: null, lon: null};
  assert.deepEqual(regionForEntry({...noPosition, tripRegion: 'far'}, regions), {region: 'far', via: 'trip'});
  for (const tripRegion of [undefined, null, '', 'unknown']) {
    assert.deepEqual(regionForEntry({...noPosition, tripRegion}, regions), {missing: 'no region'});
  }
  assert.deepEqual(regionForEntry({lat: 3, lon: null}, regions), {missing: 'no region'});
  assert.deepEqual(regionForEntry({...noPosition, tripRegion: 'far'}, []), {missing: 'no region'});
});

// The synthetic cases alone cannot catch the checked-in docs drifting from the parser contract.
test('C3: resolves Morro Bay harbour using the committed region documents', t => {
  const root = new URL('../', import.meta.url);
  const docs = globSync('regions/*/region.json', {cwd: root}).sort()
    .map(path => JSON.parse(readFileSync(new URL(path, root), 'utf8')));
  const list = regionList(docs);
  assert.equal(list.skipped, 0);
  const point = {lat: 35.37, lon: -120.86};
  const containing = list.regions.filter(({bounds: [w, s, e, n]}) =>
    w <= point.lon && point.lon <= e && s <= point.lat && point.lat <= n);
  t.diagnostic(`Containing region ids (of ${docs.length} documents): ${containing.map(({id}) => id).join(', ')}`);
  assert.deepEqual(regionForEntry(point, list.regions), {region: 'morro-bay', via: 'position'});
});
