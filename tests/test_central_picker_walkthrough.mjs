// C31: the walk planner, spec checks and arrival judge of the Central picker walkthrough (no browser, no network).
import assert from 'node:assert/strict';
import test from 'node:test';
import {CENTRAL_REGIONS, checkSpec, expectedFor, judgeArrival, pickerReach, planWalk} from '../scripts/relief/central_picker_walkthrough.mjs';

const TERRAIN = new Set(['monterey-point-sur', 'santa-cruz-monterey-bay']);
const spec = CENTRAL_REGIONS.map((region, i) => ({region, release: `/x/${region}/release.json`, lat: 35 + i / 10, lon: -121 - i / 10,
  contours: TERRAIN.has(region) ? null : `/x/c20/${region}`}));
const seenOk = (region, extra = {}) => ({urlRegion: region, shownRegion: region, contoursDrawn: 5, contourRows: 1,
  creditLines: ['surveyed unstated · NAVD88 · not for navigation'], contourFilesRequested: 1, pageErrors: [], ...extra});
const seenTerrain = (region, extra = {}) => ({urlRegion: region, shownRegion: region, contoursDrawn: 0, contourRows: 0, creditLines: [],
  contourFilesRequested: 0, pageErrors: [], ...extra});

test('the walk opens the first region, picks the other five, then goes Back five times', () => {
  const steps = planWalk(spec);
  assert.deepEqual(steps.map(s => s.kind), ['open', 'pick', 'pick', 'pick', 'pick', 'pick', 'back', 'back', 'back', 'back', 'back']);
  assert.deepEqual(steps.slice(0, 6).map(s => s.region), CENTRAL_REGIONS);
  assert.deepEqual(steps.slice(6).map(s => s.region), [...CENTRAL_REGIONS].slice(0, 5).reverse());
});

test('a spec must be exactly the six Central regions, once each, with a release and a centre', () => {
  assert.throws(() => checkSpec(spec.slice(1)), /exactly the six/);
  assert.throws(() => checkSpec([...spec.slice(1), {...spec[1]}]), /once/);
  assert.throws(() => checkSpec([...spec.slice(1), {...spec[0], region: 'morro-bay'}]), /once/);
  assert.throws(() => checkSpec(spec.map((r, i) => i ? r : {...r, release: undefined})), /incomplete/);
  assert.throws(() => checkSpec(spec.map((r, i) => i ? r : {...r, lat: NaN})), /incomplete/);
  assert.equal(checkSpec(spec).length, 6);
});

test('expected availability follows the published pair: contours, or terrain-only when there is none', () => {
  assert.equal(expectedFor(spec[0]).contours, 'contours');
  assert.equal(expectedFor(spec[3]).contours, 'terrain-only');
});

test('a correct contour arrival and a correct terrain-only arrival pass', () => {
  assert.deepEqual(judgeArrival(expectedFor(spec[0]), seenOk(spec[0].region)), {ok: true, problems: [], notes: []});
  assert.equal(judgeArrival(expectedFor(spec[3]), seenTerrain(spec[3].region)).ok, true);
});

test('arriving on the wrong region, by address or by what the Chart shows, is broken', () => {
  const v = judgeArrival(expectedFor(spec[1]), seenOk(spec[1].region, {shownRegion: spec[0].region}));
  assert.equal(v.ok, false);
  assert.match(v.problems.join(), /Chart shows cambria-san-simeon/);
  assert.match(judgeArrival(expectedFor(spec[1]), seenOk(spec[1].region, {urlRegion: null})).problems.join(), /address names null/);
});

test('a terrain-only region must not inherit the neighbor\'s lines, legend row or credit', () => {
  const stale = judgeArrival(expectedFor(spec[3]), seenTerrain(spec[3].region, {contoursDrawn: 5, contourRows: 1, creditLines: ['surveyed unstated']}));
  assert.equal(stale.ok, false);
  assert.equal(stale.problems.length, 3);
});

test('credited, loaded contours outside the arrival camera are a note about the view, not a failure', () => {
  const v = judgeArrival(expectedFor(spec[1]), seenOk(spec[1].region, {contoursDrawn: 0, camera: null}));
  assert.equal(v.ok, true);
  assert.match(v.notes.join(), /none in view at the arrival camera/);
});

test('contours never requested or never credited are broken, and page errors fail the arrival', () => {
  assert.match(judgeArrival(expectedFor(spec[1]), seenOk(spec[1].region, {contoursDrawn: 0, contourFilesRequested: 0})).problems.join(), /not requested/);
  assert.match(judgeArrival(expectedFor(spec[1]), seenOk(spec[1].region, {creditLines: []})).problems.join(), /no contour credit/);
  assert.match(judgeArrival(expectedFor(spec[0]), seenOk(spec[0].region, {pageErrors: ['boom']})).problems.join(), /page errors/);
});

test('the picker can open a region only when the coverage snapshot lists it as active or preview', () => {
  const rows = [['cambria-san-simeon', 'Cambria', 'preview'], ['big-sur-coast', 'Big Sur', 'draft'], ['monterey-point-sur', 'Monterey', 'active']];
  const reach = Object.fromEntries(pickerReach(rows, spec).map(r => [r.region, r]));
  assert.equal(reach['cambria-san-simeon'].openable, true);
  assert.equal(reach['big-sur-coast'].openable, false);
  assert.equal(reach['monterey-point-sur'].openable, true);
  assert.deepEqual([reach['point-arguello-conception'].listed, reach['point-arguello-conception'].openable], [false, false]);
});
