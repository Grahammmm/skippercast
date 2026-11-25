// C31: the walk planner, spec checks and arrival judge of the Central picker walkthrough (no browser, no network).
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import test from 'node:test';
import {CENTRAL_REGIONS, CONTOUR_PAIR, checkContourPair, checkSpec, expectedFor, judgeArrival, pickerReach, planWalk} from '../scripts/relief/central_picker_walkthrough.mjs';

const TERRAIN = new Set(['monterey-point-sur', 'santa-cruz-monterey-bay']);
const STYLE = 'c'.repeat(64);
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
/** The published pair of a region, shaped as the ft-v3 contour documents are (provenance names region, set, style, role). */
const publishedPair = (region, style = STYLE) => {
  const make = overview => Buffer.from(JSON.stringify({type: 'FeatureCollection', features: [{type: 'Feature'}, {type: 'Feature'}],
    provenance: {region_id: region, set: 'ft-v3', units: 'ft', contours: style, features: 2, ...(overview ? {overview: {max_zoom: 12}} : {})}}));
  return [{name: CONTOUR_PAIR[0], bytes: make(true)}, {name: CONTOUR_PAIR[1], bytes: make(false)}];
};
const pinsOf = files => ({overview: sha(files.find(f => f.name === CONTOUR_PAIR[0]).bytes), detail: sha(files.find(f => f.name === CONTOUR_PAIR[1]).bytes)});
const spec = CENTRAL_REGIONS.map((region, i) => ({region, release: `/x/${region}/release.json`, lat: 35 + i / 10, lon: -121 - i / 10,
  contours: TERRAIN.has(region) ? null : `/x/c20/${region}`, contourPins: TERRAIN.has(region) ? null : pinsOf(publishedPair(region))}));
const seenOk = (region, extra = {}) => ({urlRegion: region, shownRegion: region, contoursDrawn: 5, contourRows: 1,
  creditLines: ['surveyed unstated · NAVD88 · not for navigation'], contourFilesRequested: 1, contourFilesRequestedAnyRegion: 1, pageErrors: [], ...extra});
const seenTerrain = (region, extra = {}) => ({urlRegion: region, shownRegion: region, contoursDrawn: 0, contourRows: 0, creditLines: [],
  contourFilesRequested: 0, contourFilesRequestedAnyRegion: 0, pageErrors: [], ...extra});

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

test('expected availability is the canonical table: the spec cannot turn a terrain-only region into a contour one or back', () => {
  assert.equal(expectedFor(spec[0]).contours, 'contours');
  assert.equal(expectedFor(spec[3]).contours, 'terrain-only');
  // Believable bug: availability derived from the row's own contours value lets a bad spec flip a region.
  assert.equal(expectedFor({...spec[3], contours: '/x/c20/monterey-point-sur'}).contours, 'terrain-only');
  assert.equal(expectedFor({...spec[0], contours: null}).contours, 'contours');
  assert.throws(() => expectedFor({region: 'morro-bay'}), /not a Central region/);
});

test('a spec row must carry the canonical contours value: a directory for contour regions, null for terrain-only', () => {
  const flip = (region, contours) => spec.map(r => r.region === region ? {...r, contours} : r);
  assert.throws(() => checkSpec(flip('monterey-point-sur', '/x/c20/monterey-point-sur')), /terrain-only: spec contours must be null/);
  assert.throws(() => checkSpec(flip('santa-cruz-monterey-bay', undefined)), /terrain-only/);
  assert.throws(() => checkSpec(flip('big-sur-coast', null)), /publishes contours/);
  assert.throws(() => checkSpec(flip('big-sur-coast', undefined)), /publishes contours/);
  assert.throws(() => checkSpec(flip('big-sur-coast', '')), /publishes contours/);
  assert.equal(checkSpec(spec).length, 6);
});

test('a contour directory must be the region\'s published pair: exact names, pinned bytes, own provenance', () => {
  const region = 'big-sur-coast', good = publishedPair(region), ok = {pins: pinsOf(good), style: STYLE};
  assert.deepEqual([...checkContourPair(region, good, ok).keys()].sort(), [...CONTOUR_PAIR]);
  const [overview, detail] = good;
  // Names: a missing or extra file is refused (the route must never serve anything but the pair).
  assert.throws(() => checkContourPair(region, [overview], ok), /exactly/);
  assert.throws(() => checkContourPair(region, [...good, {name: 'secrets.json', bytes: Buffer.from('{}')}], ok), /exactly/);
  assert.throws(() => checkContourPair(region, [overview, {name: 'other.geojson', bytes: detail.bytes}], ok), /exactly/);
  // Believable bug: only names and "is a FeatureCollection" were checked, so identical fabricated bytes passed for every region.
  const fabricated = Buffer.from(JSON.stringify({type: 'FeatureCollection', features: [{type: 'Feature'}]}));
  assert.throws(() => checkContourPair(region, good.map(f => ({...f, bytes: fabricated})), ok), /differs from its published pin/);
  // Another region's real pair (a stale or mis-pointed directory) does not match this region's pins ...
  assert.throws(() => checkContourPair(region, publishedPair('cambria-san-simeon'), ok), /differs from its published pin/);
  // ... and, even if someone pinned those bytes, its own provenance names the wrong region.
  const other = publishedPair('cambria-san-simeon');
  assert.throws(() => checkContourPair(region, other, {pins: pinsOf(other), style: STYLE}), /not the published ft-v3 overview contours for this region/);
  // Swapped overview/detail bytes under the right names fail both the pins and (with swapped pins) the role.
  const swapped = [{name: CONTOUR_PAIR[0], bytes: detail.bytes}, {name: CONTOUR_PAIR[1], bytes: overview.bytes}];
  assert.throws(() => checkContourPair(region, swapped, ok), /differs from its published pin/);
  assert.throws(() => checkContourPair(region, swapped, {pins: pinsOf(swapped), style: STYLE}), /overview contours for this region/);
  // Stale: bytes pinned but built under another contour style than this release's.
  const stale = publishedPair(region, 'd'.repeat(64));
  assert.throws(() => checkContourPair(region, stale, {pins: pinsOf(stale), style: STYLE}), /this region and release/);
  // Held, empty or count-mismatched documents are not the published pair even when pinned.
  const variant = patch => good.map(f => { const d = JSON.parse(f.bytes); patch(d); return {name: f.name, bytes: Buffer.from(JSON.stringify(d))}; });
  for (const patch of [d => { d.provenance.publication_held = true; }, d => { d.features = []; d.provenance.features = 0; }, d => { d.provenance.features = 9; }]) {
    const bad = variant(patch);
    assert.throws(() => checkContourPair(region, bad, {pins: pinsOf(bad), style: STYLE}), /this region and release/);
  }
  assert.throws(() => checkContourPair(region, [overview, {name: CONTOUR_PAIR[1], bytes: Buffer.from('nope')}], {pins: pinsOf([overview, {bytes: Buffer.from('nope')}].map((f, i) => ({...f, name: CONTOUR_PAIR[i]}))), style: STYLE}), /not JSON/);
  // No pins, malformed pins or no release style: refused rather than trusted.
  assert.throws(() => checkContourPair(region, good, {style: STYLE}), /contourPins/);
  assert.throws(() => checkContourPair(region, good, {pins: ok.pins}), /contour style/);
});

test('a spec row must carry independent contour pins: two distinct SHA-256 for a contour region, none for terrain-only', () => {
  const edit = (region, change) => spec.map(r => r.region === region ? {...r, ...change} : r);
  for (const bad of [undefined, null, {}, {overview: 'x'.repeat(64), detail: 'y'.repeat(64)}, {overview: 'a'.repeat(64)},
    {overview: 'a'.repeat(64), detail: 'a'.repeat(64)}, {...spec[0].contourPins, extra: 'b'.repeat(64)}]) {
    assert.throws(() => checkSpec(edit('big-sur-coast', {contourPins: bad})), /contourPins/);
  }
  assert.throws(() => checkSpec(edit('monterey-point-sur', {contourPins: spec[0].contourPins})), /terrain-only: spec contourPins must be null/);
  assert.equal(checkSpec(spec).length, 6);
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

test('request invariants hold whatever is drawn: terrain-only never requests a contour file, a contour region always does', () => {
  // Believable bug: the request check ran only when zero features were drawn, so these two passed.
  const asked = judgeArrival(expectedFor(spec[3]), seenTerrain(spec[3].region, {contourFilesRequested: 1, contourFilesRequestedAnyRegion: 1}));
  assert.equal(asked.ok, false);
  assert.match(asked.problems.join(), /terrain-only region arrival requested 1 contour files/);
  assert.equal(judgeArrival(expectedFor(spec[3]), seenTerrain(spec[3].region, {contourFilesRequested: undefined, contourFilesRequestedAnyRegion: undefined})).ok, false);
  const stale = judgeArrival(expectedFor(spec[1]), seenOk(spec[1].region, {contourFilesRequested: 0}));
  assert.equal(stale.ok, false);
  assert.match(stale.problems.join(), /published contours not requested/);
});

test('a terrain-only arrival is judged against contour requests for ANY region, with a no-request control', () => {
  // Believable bug: requests were filtered to the arrival region before judging, so a stale request for the neighbor's
  // published file during a terrain-only arrival was dropped and the arrival reported zero.
  const other = judgeArrival(expectedFor(spec[3]), seenTerrain(spec[3].region,
    {contourFilesRequested: 0, contourFilesRequestedAnyRegion: 1, contourFilesSeen: ['big-sur-coast/depth-contours.geojson']}));
  assert.equal(other.ok, false);
  assert.match(other.problems.join(), /requested 1 contour files \(big-sur-coast\/depth-contours\.geojson\)/);
  assert.equal(judgeArrival(expectedFor(spec[5]), seenTerrain(spec[5].region, {contourFilesRequestedAnyRegion: 2})).ok, false);
  // Control: no contour request of any region in the interval passes; a contour arrival still needs only its OWN file.
  assert.equal(judgeArrival(expectedFor(spec[3]), seenTerrain(spec[3].region)).ok, true);
  assert.equal(judgeArrival(expectedFor(spec[1]), seenOk(spec[1].region, {contourFilesRequestedAnyRegion: 2})).ok, true);
  assert.match(judgeArrival(expectedFor(spec[1]), seenOk(spec[1].region, {contourFilesRequested: 0, contourFilesRequestedAnyRegion: 1})).problems.join(), /published contours not requested/);
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
