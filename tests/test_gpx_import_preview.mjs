import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {gpxFileCheck, gpxImportPreview, IMPORT_CAPACITY} from '../web/gpx-import-preview.ts';
import {MAX_GPX_BYTES, readGpxWaypoints} from '../web/gpx-waypoints.ts';
import {screenGpxCandidates} from '../web/gpx-import-screen.ts';

for (const [label, name, size, expected] of [
  ['empty takes precedence over a wrong extension', 'marks.txt', 0, 'empty'],
  ['negative is not a valid file size', 'marks.gpx', -1, 'empty'],
  ['NaN does not pass size validation', 'marks.gpx', NaN, 'empty'],
  ['infinite size is empty rather than too large', 'marks.gpx', Infinity, 'empty'],
  ['oversize takes precedence over a wrong extension', 'marks.txt', MAX_GPX_BYTES + 1, 'too-large'],
  ['the suffix must be at the end', 'marks.gpx.txt', 1, 'not-gpx'],
  ['an extension needs its dot', 'marksgpx', 1, 'not-gpx'],
  ['exact byte limit and mixed-case extension are accepted', 'marks.GpX', MAX_GPX_BYTES, 'ok'],
]) {
  test(`C1: ${label}`, () => assert.equal(gpxFileCheck({name, size}), expected));
}

const readOk = (waypoints = []) => ({ok: true, waypoints, rejected: [], ignoredTrackPoints: 0});
const screenOk = (clear = []) => ({ok: true, clear, refused: []});

test('C2: the capacity is 100 and matches the server limit', () => {
  // A client-only limit change would offer a selection the store does not allow (or needlessly truncate it).
  const server = readFileSync(new URL('../server/routes/spots.ts', import.meta.url), 'utf8');
  assert.deepEqual([IMPORT_CAPACITY, Number(/MAX_SPOTS = (\d+)/.exec(server)?.[1])], [100, 100]);
});

test('C2: the read error code wins over a failed screen, without forwarding the message', () => {
  const read = readGpxWaypoints('<gpx');
  assert.deepEqual(gpxImportPreview(read, {ok: false, error: 'screen-stale'}, []), {ok: false, error: 'invalid-xml'});
});

for (const error of ['screen-unavailable', 'screen-stale']) {
  test(`C2: ${error} is not a successful empty preview`, () => {
    assert.deepEqual(gpxImportPreview(readOk(), {ok: false, error}, []), {ok: false, error});
  });
}

const noCounts = {
  read: 0, routePoints: 0, invalidPoints: 0, trackPoints: 0,
  refusedInside: 0, refusedNear: 0, refusedUnchecked: 0,
  duplicates: 0, invalid: 0, overCapacity: 0, save: 0,
};

test('C3: no points gives a complete zero-count preview', () => {
  assert.deepEqual(gpxImportPreview(readOk(), screenOk(), []), {ok: true, save: [], counts: noCounts});
});

test('C3: the reader and screen breakdown stays separate from the file-order save list', () => {
  // Counting XML refusals as read waypoints or planning from unscreened waypoints changes this result.
  const read = readGpxWaypoints(`
    <gpx xmlns="http://www.topografix.com/GPX/1/1" version="1.1">
      <wpt lat="6" lon="7"><name>Z</name><desc>first note</desc></wpt>
      <wpt lat="1" lon="7"/>
      <wpt lat="2" lon="7"/>
      <wpt lat="4" lon="7"><name>A</name></wpt>
      <wpt lat="3" lon="7"/>
      <wpt lat="5" lon="7"><name>M</name></wpt>
      <wpt lat="91" lon="7"/>
      <wpt lat="1" lon="181"/>
      <wpt lat="1" lon="7"><name><b>markup</b></name></wpt>
      <extensions><wpt lat="1" lon="7"/></extensions>
      <rte><rtept lat="0" lon="1"/><rtept lat="0" lon="2"/></rte>
      <trk><trkseg><trkpt lat="0" lon="1"/><trkpt lat="0" lon="2"/><trkpt lat="0" lon="3"/></trkseg></trk>
    </gpx>`);
  const screen = screenGpxCandidates(read.waypoints, {
    checkedAt: 0,
    verdict: ({latitude}) => ({inside: latitude === 1, screened: latitude <= 2, denied: latitude <= 3}),
    refused: verdict => verdict.denied,
  }, 0);
  assert.deepEqual(gpxImportPreview(read, screen, []), {
    ok: true,
    save: [
      {name: 'Z', lat: 6, lon: 7, note: 'first note'},
      {name: 'A', lat: 4, lon: 7, note: null},
      {name: 'M', lat: 5, lon: 7, note: null},
    ],
    counts: {read: 6, routePoints: 2, invalidPoints: 4, trackPoints: 3,
      refusedInside: 1, refusedNear: 1, refusedUnchecked: 1,
      duplicates: 0, invalid: 0, overCapacity: 0, save: 3},
  });
});

const waypoint = (name, lat) => Object.freeze({name, lat, lon: 7, note: null});
const candidates = Object.freeze([waypoint('Z', 6), waypoint('A', 4), waypoint('M', 5)]);
const stored = count => Object.freeze(Array.from({length: count}, (_, lon) => Object.freeze({lat: 0, lon})));

test('C3: refusal categories, duplicates and invalid candidates do not consume the last slot or mutate inputs', () => {
  const duplicate = waypoint('stored match', 0);
  const invalid = waypoint('invalid', 91);
  const clear = Object.freeze([duplicate, invalid, candidates[0], candidates[1]]);
  // Unequal refusal counts catch swapped buckets; leading rejections catch limiting before planning.
  const refused = Object.freeze([
    Object.freeze({waypoint: waypoint('near 1', 1), reason: 'near'}),
    Object.freeze({waypoint: waypoint('near 2', 2), reason: 'near'}),
    Object.freeze({waypoint: waypoint('unchecked', 3), reason: 'unchecked'}),
  ]);
  const read = Object.freeze({...readOk(Object.freeze([...clear, ...refused.map(row => row.waypoint)])), rejected: Object.freeze([])});
  const screen = Object.freeze({ok: true, clear, refused});
  assert.deepEqual(gpxImportPreview(read, screen, stored(99)), {
    ok: true, save: [candidates[0]],
    counts: {...noCounts, read: 7, refusedNear: 2, refusedUnchecked: 1, duplicates: 1, invalid: 1, overCapacity: 1, save: 1},
  });
});

for (const [existing, save, overCapacity] of [
  [97, candidates, 0],  // An exact fit must keep all three.
  [99, [candidates[0]], 2],  // One slot must take the first candidate, not the first by name.
  [100, [], 3],  // A full store must keep none.
  [101, [], 3],  // Negative room must not act as a slice index from the end.
]) {
  test(`C3: ${existing} existing spots with three eligible candidates`, () => {
    assert.deepEqual(gpxImportPreview(readOk(candidates), screenOk(candidates), stored(existing)), {
      ok: true, save, counts: {...noCounts, read: 3, overCapacity, save: save.length},
    });
  });
}
