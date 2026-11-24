import test from 'node:test';
import assert from 'node:assert/strict';
import {MAX_EDDIES, MAX_OUTLINE_POINTS, parseEddiesTile} from '../web/map/eddies-feed.ts';

// In-memory fixtures exercise the decoded tile boundary, not the habitat loader's byte checks.
const frameTime = '2026-01-02T03:04:05Z';
const first = () => ({outline: [[-180, -90], [-179, -90], [-179, -89], [-180, -90]], sense: 'cw', diameter_km: 34, ow_min: -0.025});
const second = () => ({outline: [[180, 90], [179, 89], [179, 90], [180, 90]], sense: 'ccw', diameter_km: 12, ow_min: -0.005});
const tile = (features = [first(), second()]) => ({frame_time: frameTime, features});
const expectedFirst = () => ({outline: [[-180, -90], [-179, -90], [-179, -89], [-180, -90]], sense: 'cw', diameterKm: 34, owMin: -0.025});
const expected = () => ({ok: true, frameTime, eddies: [expectedFirst(), {
  outline: [[180, 90], [179, 89], [179, 90], [180, 90]], sense: 'ccw', diameterKm: 12, owMin: -0.005,
}]});

// Catch a cap or inequality drifting away from the wire contract in either direction.
test('C1: exports the exact caps and accepts both inclusive upper bounds', () => {
  assert.deepEqual({MAX_EDDIES, MAX_OUTLINE_POINTS}, {MAX_EDDIES: 200, MAX_OUTLINE_POINTS: 2000});
  const outline = Array.from({length: 2000}, (_, i) => [i % 7, i % 11]);
  outline[1999] = [0, 0];
  const features = Array.from({length: 200}, (_, i) => i === 0 ? {...first(), outline} : first());
  const eddies = Array.from({length: 200}, (_, i) => i === 0 ? {...expectedFirst(), outline} : expectedFirst());
  assert.deepEqual(parseEddiesTile(tile(features)), {ok: true, frameTime, eddies});
});

// A decoder must not return partial success or leak a thrown value instead of naming the path.
test('C2: one bad feature rejects the whole two-eddy tile', () => {
  assert.deepEqual(parseEddiesTile(tile([first(), {...second(), sense: 'counterclockwise'}])),
    {ok: false, error: 'features[1].sense'});
});

test('C2: a throwing property is reported at its field path', () => {
  const unreadable = {...second(), get ow_min() { throw new Error('unreadable'); }};
  assert.deepEqual(parseEddiesTile(tile([first(), unreadable])), {ok: false, error: 'features[1].ow_min'});
});

test('C2: a revoked root proxy returns a tile error without throwing', () => {
  const {proxy, revoke} = Proxy.revocable(tile(), {});
  revoke();
  assert.deepEqual(parseEddiesTile(proxy), {ok: false, error: 'tile'});
});

test('C3: accepts a valid two-eddy tile and projects the exact fields', () => {
  assert.deepEqual(parseEddiesTile(tile()), expected());
});

test('C3: an empty tile is valid and preserves minute precision', () => {
  const minute = '2026-01-02T03:04Z';
  const raw = Object.assign(Object.create(null), {frame_time: minute, features: []});
  assert.deepEqual(parseEddiesTile(raw), {ok: true, frameTime: minute, eddies: []});
});

test('C3: accepts real February dates without changing timestamp precision or geometry', () => {
  for (const frameTime of ['2028-02-29T03:00Z', '2026-02-28T23:59:59Z']) {
    assert.deepEqual(parseEddiesTile({...tile(), frame_time: frameTime}), {...expected(), frameTime});
  }
});

// Each fixture isolates a rule: coercion, missing bounds, sparse-array skipping,
// or dropping the closure/sign check would turn that refusal into success.
const tileCases = [
  ['null tile', null, 'tile'],
  ['primitive tile', 42, 'tile'],
  ['array masquerading as a tile', Object.assign([], tile()), 'tile'],
  ['non-plain object with valid tile fields', Object.assign(new Date(0), tile()), 'tile'],
  ['missing frame_time', {features: []}, 'frame_time'],
  ['frame_time not a string', {...tile(), frame_time: 0}, 'frame_time'],
  ['parseable but noncanonical frame_time', {...tile(), frame_time: '2026-01-02T03:04:05+00:00'}, 'frame_time'],
  ['canonical-looking but unparseable frame_time', {...tile(), frame_time: '2026-13-02T03:04:05Z'}, 'frame_time'],
  // Date.parse can silently roll nonexistent days and 24:00 into another day.
  ['February 30 frame_time', {...tile(), frame_time: '2026-02-30T03:00Z'}, 'frame_time'],
  ['nonleap February 29 frame_time', {...tile(), frame_time: '2026-02-29T03:00Z'}, 'frame_time'],
  ['hour 24 frame_time', {...tile(), frame_time: '2026-02-28T24:00:00Z'}, 'frame_time'],
  ['minute 60 frame_time', {...tile(), frame_time: '2026-02-28T23:60Z'}, 'frame_time'],
  ['second 60 frame_time', {...tile(), frame_time: '2026-02-28T23:59:60Z'}, 'frame_time'],
  ['missing features', {frame_time: frameTime}, 'features'],
  ['non-array features', tile({0: first(), length: 1}), 'features'],
  ['too many features', tile(Array.from({length: 201}, first)), 'features'],
  ['non-object feature', tile([first(), null]), 'features[1]'],
  ['sparse features', tile([first(), , second()]), 'features[1]'],
];
for (const [name, raw, error] of tileCases) {
  test(`C3: rejects ${name}`, () => assert.deepEqual(parseEddiesTile(raw), {ok: false, error}));
}

const featureCases = [
  ['non-array outline', {outline: {}}, 'outline'],
  ['three-point closed outline', {outline: [[0, 0], [1, 0], [0, 0]]}, 'outline'],
  ['too many outline points', {outline: Array.from({length: 2001}, () => [0, 0])}, 'outline'],
  ['outline open in longitude', {outline: [[0, 0], [1, 0], [1, 1], [1, 0]]}, 'outline'],
  ['outline open in latitude', {outline: [[0, 0], [1, 0], [1, 1], [0, 1]]}, 'outline'],
  ['non-array coordinate pair', {outline: [[0, 0], {0: 1, 1: 1, length: 2}, [1, 0], [0, 0]]}, 'outline[1]'],
  ['three-element coordinate pair', {outline: [[0, 0], [1, 1, 0], [1, 0], [0, 0]]}, 'outline[1]'],
  ['sparse outline', {outline: [[0, 0], , [1, 0], [0, 0]]}, 'outline[1]'],
  ...[
    ['out-of-range positive longitude', [181, 0]],
    ['out-of-range negative longitude', [-181, 0]],
    ['out-of-range positive latitude', [0, 91]],
    ['out-of-range negative latitude', [0, -91]],
    ['NaN longitude', [NaN, 0]],
    ['NaN latitude', [0, NaN]],
    ['infinite longitude', [Infinity, 0]],
    ['numeric string latitude', [0, '1']],
  ].map(([name, point]) => [name, {outline: [[0, 0], point, [1, 0], [0, 0]]}, 'outline[1]']),
  ['zero diameter', {diameter_km: 0}, 'diameter_km'],
  ['negative diameter', {diameter_km: -1}, 'diameter_km'],
  ['infinite diameter', {diameter_km: Infinity}, 'diameter_km'],
  ['numeric string diameter', {diameter_km: '12'}, 'diameter_km'],
  ['zero OW minimum', {ow_min: 0}, 'ow_min'],
  ['positive OW minimum', {ow_min: 1}, 'ow_min'],
  ['infinite OW minimum', {ow_min: -Infinity}, 'ow_min'],
  ['numeric string OW minimum', {ow_min: '-1'}, 'ow_min'],
];
for (const [name, change, field] of featureCases) {
  test(`C3: rejects ${name}`, () => {
    assert.deepEqual(parseEddiesTile(tile([first(), {...second(), ...change}])),
      {ok: false, error: `features[1].${field}`});
  });
}

// A shallow copy (or sorting by diameter) would corrupt this result.
test('C4: preserves feature and point order in arrays detached from the input', () => {
  const raw = tile();
  const parsed = parseEddiesTile(raw);
  raw.frame_time = 'invalid';
  raw.features[0].outline[0][0] = 0;
  raw.features[0].outline.reverse();
  raw.features[0].diameter_km = 1;
  raw.features.reverse();
  raw.features.length = 0;
  assert.deepEqual(parsed, expected());
});
