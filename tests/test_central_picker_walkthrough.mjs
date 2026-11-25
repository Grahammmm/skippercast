// C31: the walk planner, spec checks and arrival judge of the Central picker walkthrough (no browser, no network).
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import test from 'node:test';
import {existsSync, readFileSync} from 'node:fs';
import {join} from 'node:path';
import {CENTRAL_REGIONS, CONTOUR_PAIR, PIN_TABLE_PATH, REHEARSAL_PINS, checkContourPair, checkPinTable, checkSpec, expectedFor, judgeArrival, loadPinTable, pickerReach, planWalk} from '../scripts/relief/central_picker_walkthrough.mjs';

const TERRAIN = new Set(['monterey-point-sur', 'santa-cruz-monterey-bay']);
const STYLE = 'c'.repeat(64);
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
/** A synthetic pair of a region, shaped as the ft-v3 contour documents are (provenance names region, set, style, role). */
const publishedPair = (region, style = STYLE) => {
  const make = overview => Buffer.from(JSON.stringify({type: 'FeatureCollection', features: [{type: 'Feature'}, {type: 'Feature'}],
    provenance: {region_id: region, set: 'ft-v3', units: 'ft', contours: style, features: 2, ...(overview ? {overview: {max_zoom: 12}} : {})}}));
  return [{name: CONTOUR_PAIR[0], bytes: make(true)}, {name: CONTOUR_PAIR[1], bytes: make(false)}];
};
/** A pin table (as the committed one is shaped) built for the given synthetic pairs: the trust root a test chooses, never the caller's. */
const tableFor = pairs => {
  const regions = {};
  for (const region of CENTRAL_REGIONS) {
    const files = pairs[region] ?? (TERRAIN.has(region) ? null : publishedPair(region));
    regions[region] = files ? {overview: sha(files.find(f => f.name === CONTOUR_PAIR[0]).bytes), detail: sha(files.find(f => f.name === CONTOUR_PAIR[1]).bytes)} : {terrain_only: true};
  }
  return loadPinTable(JSON.stringify({schema: 'central-rehearsal-pins/1', regions}));
};
const spec = CENTRAL_REGIONS.map((region, i) => ({region, release: `/x/${region}/release.json`, lat: 35 + i / 10, lon: -121 - i / 10,
  contours: TERRAIN.has(region) ? null : `/x/c20/${region}`}));
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

test('a contour directory must be the region\'s pinned pair: exact names, table-pinned bytes, own provenance', () => {
  const region = 'big-sur-coast', good = publishedPair(region), ok = {table: tableFor({[region]: good}), style: STYLE};
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
  assert.throws(() => checkContourPair(region, other, {table: tableFor({[region]: other}), style: STYLE}), /not the published ft-v3 overview contours for this region/);
  // Swapped overview/detail bytes under the right names fail the pins and (with swapped pins) the role.
  const swapped = [{name: CONTOUR_PAIR[0], bytes: detail.bytes}, {name: CONTOUR_PAIR[1], bytes: overview.bytes}];
  assert.throws(() => checkContourPair(region, swapped, ok), /differs from its published pin/);
  assert.throws(() => checkContourPair(region, swapped, {table: tableFor({[region]: swapped}), style: STYLE}), /overview contours for this region/);
  // Stale: bytes pinned but built under another contour style than this release's.
  const stale = publishedPair(region, 'd'.repeat(64));
  assert.throws(() => checkContourPair(region, stale, {table: tableFor({[region]: stale}), style: STYLE}), /this region and release/);
  // Held, empty or count-mismatched documents are not the published pair even when pinned.
  const variant = patch => good.map(f => { const d = JSON.parse(f.bytes); patch(d); return {name: f.name, bytes: Buffer.from(JSON.stringify(d))}; });
  for (const patch of [d => { d.provenance.publication_held = true; }, d => { d.features = []; d.provenance.features = 0; }, d => { d.provenance.features = 9; }]) {
    const bad = variant(patch);
    assert.throws(() => checkContourPair(region, bad, {table: tableFor({[region]: bad}), style: STYLE}), /this region and release/);
  }
  const notJson = [overview, {name: CONTOUR_PAIR[1], bytes: Buffer.from('nope')}];
  assert.throws(() => checkContourPair(region, notJson, {table: tableFor({[region]: notJson}), style: STYLE}), /not JSON/);
  // No release style: refused rather than trusted. A terrain-only region has no pair to bind at all.
  assert.throws(() => checkContourPair(region, good, {table: ok.table}), /contour style/);
  assert.throws(() => checkContourPair('monterey-point-sur', good, ok), /no contour pair/);
  assert.throws(() => checkContourPair('morro-bay', good, ok), /no contour pair/);
});

test('the trust root is the committed pin table: a fabricated pair with self-computed digests is refused, the table is validated', () => {
  const region = 'big-sur-coast', fake = publishedPair(region);
  // Believable bug (the previous design): pins came from the same caller-supplied spec, so a fabricated same-region,
  // same-style pair with provenance that looks right and digests computed from its own bytes passed.
  assert.throws(() => checkContourPair(region, fake, {style: STYLE}), /differs from its published pin/);
  assert.throws(() => checkContourPair(region, fake, {style: STYLE, table: REHEARSAL_PINS}), /differs from its published pin/);
  // Control: the same bytes ARE accepted when a table that names them is the reviewed trust root, so the refusal above is the table's.
  assert.equal(checkContourPair(region, fake, {style: STYLE, table: tableFor({[region]: fake})}).size, 2);
  // The committed table is the six Central regions, canonical availability, no contour entry for the terrain-only two.
  assert.equal(checkPinTable(JSON.parse(readFileSync(PIN_TABLE_PATH, 'utf8'))).schema, 'central-rehearsal-pins/1');
  assert.equal(REHEARSAL_PINS.schema, 'central-rehearsal-pins/1');
  assert.match(REHEARSAL_PINS.status, /REHEARSAL.*NOT a publication record/);
  for (const r of CENTRAL_REGIONS) assert.equal(TERRAIN.has(r), REHEARSAL_PINS.regions[r].terrain_only === true, r);
  // A bad table is refused: a terrain-only region with a contour entry (in either direction), shared or malformed digests, missing or extra regions.
  const edit = change => { const t = structuredClone(REHEARSAL_PINS); change(t.regions); return t; };
  const digest = 'e'.repeat(64);
  assert.throws(() => checkPinTable(edit(r => { r['monterey-point-sur'].detail = digest; })), /terrain-only/);
  assert.throws(() => checkPinTable(edit(r => { r['santa-cruz-monterey-bay'].overview = digest; })), /terrain-only/);
  assert.throws(() => checkPinTable(edit(r => { r['santa-cruz-monterey-bay'] = {overview: digest, detail: 'f'.repeat(64)}; })), /terrain-only/);
  assert.throws(() => checkPinTable(edit(r => { r['big-sur-coast'] = {terrain_only: true}; })), /publishes contours/);
  assert.throws(() => checkPinTable(edit(r => { r['big-sur-coast'].detail = r['big-sur-coast'].overview; })), /distinct/);
  assert.throws(() => checkPinTable(edit(r => { r['big-sur-coast'].detail = 'xyz'; })), /distinct/);
  assert.throws(() => checkPinTable(edit(r => { delete r['cambria-san-simeon']; })), /exactly the six/);
  assert.throws(() => checkPinTable(edit(r => { r['morro-bay'] = {overview: digest, detail: 'f'.repeat(64)}; })), /exactly the six/);
  assert.throws(() => checkPinTable({...REHEARSAL_PINS, schema: 'other'}), /not a central-rehearsal-pins/);
  // A table with a terrain-only entry cannot be used to bind a pair for that region, whatever the spec says.
  assert.throws(() => checkContourPair('monterey-point-sur', fake, {style: STYLE}), /no contour pair/);
});

test('a spec must not carry its own pins, on any row, whatever their value', () => {
  const add = (region, change) => spec.map(r => r.region === region ? {...r, ...change} : r);
  const own = {overview: 'a'.repeat(64), detail: 'b'.repeat(64)};
  assert.throws(() => checkSpec(add('big-sur-coast', {contourPins: own})), /must not carry pins/);
  assert.throws(() => checkSpec(add('big-sur-coast', {pins: own})), /must not carry pins/);
  assert.throws(() => checkSpec(add('big-sur-coast', {contourPins: null})), /must not carry pins/);
  assert.throws(() => checkSpec(add('big-sur-coast', {contourPins: undefined})), /must not carry pins/);
  assert.throws(() => checkSpec(add('monterey-point-sur', {contourPins: own})), /must not carry pins/);
  assert.throws(() => checkSpec(add('santa-cruz-monterey-bay', {contourPins: null})), /must not carry pins/);
  assert.equal(checkSpec(spec).length, 6);
});

// The real rehearsal pairs (C20/C21, synthetic approvals) live outside the repository: this check runs where they are
// present (CENTRAL_REHEARSAL_PAIRS=<dir holding one directory per contour region>) and skips otherwise.
const REAL = process.env.CENTRAL_REHEARSAL_PAIRS || '';
test('the real rehearsal pair of each contour region is accepted by the committed table, and a swap between regions is not', { skip: (!REAL || !existsSync(REAL)) && 'real rehearsal pairs not present (set CENTRAL_REHEARSAL_PAIRS)' }, () => {
  const read = region => CONTOUR_PAIR.map(name => ({name, bytes: readFileSync(join(REAL, region, name))}));
  const contourRegions = CENTRAL_REGIONS.filter(r => !TERRAIN.has(r));
  for (const region of contourRegions) {
    const files = read(region), style = JSON.parse(files[0].bytes).provenance.contours;
    assert.equal(checkContourPair(region, files, {style}).size, 2, region);
    const other = contourRegions.find(r => r !== region);
    assert.throws(() => checkContourPair(other, files, {style}), /differs from its published pin/, `${region} bytes under ${other}`);
  }
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
