import assert from 'node:assert/strict';
import {test} from 'node:test';
import {HOLD, OK, REGIONS, classify, visibleAt, visibleLinesInView, visibleOthersInView} from '../scripts/relief/central_arrival_audit.mjs';
import {PROFILE, TERRAIN_ONLY} from '../scripts/relief/central_preview_cameras.mjs';

const cambria = 'cambria-san-simeon', monterey = 'monterey-point-sur', bigSur = 'big-sur-coast';
const detail = region => `/regions/${region}/depth-contours.geojson`;
const pointerRead = region => ({path: `/catalog/relief/${region}.json`, status: 200, sha256: 'p'});
const contourRegion = (over = {}) => ({region: cambria, terrainOnly: false, listed: ['depth-contours.geojson'],
  reads: [pointerRead(cambria), {path: detail(cambria), status: 200, sha256: 'a'}], expected: {[detail(cambria)]: 'a'},
  accepted: true, reason: null, drawn: 3, inView: 4, othersInView: 0, ...over});
const line = (coords, props = {}) => ({type: 'Feature', properties: {kind: 'contour', depth_ft: 60, ...props},
  geometry: {type: 'LineString', coordinates: coords}});

test('the audit covers exactly the six Central regions, two of them terrain-only', () => {
  assert.equal(REGIONS.length, 6);
  assert.equal(new Set(REGIONS).size, 6);
  assert.deepEqual(REGIONS.filter(r => TERRAIN_ONLY.includes(r)).sort(), [...TERRAIN_ONLY].sort());
  assert.deepEqual(REGIONS.filter(r => !TERRAIN_ONLY.includes(r)).sort(), Object.keys(PROFILE).sort());
  assert.equal(OK.filter(c => HOLD.includes(c)).length, 0);
});

// C35's defect: chart_files omitted the pair, so the Chart never asked for it; that must not pass as "nothing in view".
test('a contour region whose pair was never read is a HOLD, listed or not', () => {
  const missing = classify(contourRegion({listed: [], reads: [pointerRead(cambria)], accepted: false, drawn: undefined, inView: null}));
  assert.deepEqual(missing, {result: 'never-requested', ok: false, problems: ['contour pair missing from region chart_files']});
  const unread = classify(contourRegion({reads: [pointerRead(cambria), {path: detail(cambria), status: 404, sha256: null}], drawn: 0, inView: null}));
  assert.equal(unread.result, 'never-requested');
  assert.deepEqual(unread.problems, ['contour pair listed but never read']);
});

test('an accepted pair is rendered when drawn with a contour line in view, out-of-view only with none', () => {
  assert.deepEqual(classify(contourRegion()), {result: 'rendered', ok: true, problems: []});
  assert.deepEqual(classify(contourRegion({drawn: 0, inView: 0})), {result: 'out-of-view', ok: true, problems: []});
  const zero = classify(contourRegion({drawn: 0, inView: 2}));
  assert.equal(zero.result, 'unexplained-zero');
  assert.equal(zero.ok, false);
  const silent = classify(contourRegion({drawn: undefined}));
  assert.equal(silent.result, 'unexplained-zero');
  assert.deepEqual(silent.problems, ['contour diagnostic never reported a draw count']);
  const phantom = classify(contourRegion({drawn: 2, inView: 0, othersInView: 0}));
  assert.equal(phantom.result, 'unexplained-draw');
  assert.equal(phantom.ok, false);
});

// Review t_c8028b34 item 1: the Chart's hit count includes survey edges and unresolved outlines.
test('hits from survey edges or unresolved outlines never pass as rendered contours', () => {
  const edgeOnly = classify(contourRegion({drawn: 2, inView: 0, othersInView: 1}));
  assert.deepEqual(edgeOnly, {result: 'out-of-view', ok: true, problems: []});
  const both = classify(contourRegion({drawn: 5, inView: 3, othersInView: 1}));
  assert.equal(both.result, 'unattributed-draw');
  assert.equal(both.ok, false);
  assert.match(both.problems[0], /cannot prove a contour line/);
});

// Review t_c8028b34 item 2: a read pair that the Chart withheld (expired review, failed validation) is not out-of-view.
test('a read but withheld or failed pair is a HOLD whatever its geometry', () => {
  for (const over of [{drawn: 0, inView: 0}, {drawn: 0, inView: 3}, {drawn: 3, inView: 4}]) {
    const got = classify(contourRegion({...over, accepted: false, reason: 'Withheld: the survey review has expired.'}));
    assert.equal(got.result, 'not-accepted');
    assert.equal(got.ok, false);
    assert.deepEqual(got.problems, ['the Chart read the pair but did not accept it: Withheld: the survey review has expired.']);
  }
});

test('terrain-only passes only with nothing listed, read, accepted or drawn', () => {
  const clean = {region: monterey, terrainOnly: true, listed: [], reads: [pointerRead(monterey)], expected: {}, accepted: false,
    drawn: 0, inView: null, othersInView: null};
  assert.deepEqual(classify(clean), {result: 'terrain-only', ok: true, problems: []});
  assert.equal(classify({...clean, drawn: 2}).result, 'terrain-leak');
  assert.equal(classify({...clean, accepted: true}).result, 'terrain-leak');
  assert.equal(classify({...clean, listed: ['depth-contours.geojson']}).result, 'terrain-leak');
  assert.equal(classify({...clean, reads: [...clean.reads, {path: detail(monterey), status: 404, sha256: null}]}).result, 'terrain-leak');
  // A neighbour's contour read is a problem even when the region itself looks clean.
  const foreign = classify({...clean, reads: [...clean.reads, {path: detail(cambria), status: 200, sha256: 'a'}]});
  assert.equal(foreign.result, 'terrain-only');
  assert.equal(foreign.ok, false);
  assert.deepEqual(foreign.problems, ['foreign region contour resource requested']);
});

test('drawn lines from bytes other than the build manifest never pass', () => {
  const swapped = classify(contourRegion({reads: [pointerRead(cambria), {path: detail(cambria), status: 200, sha256: 'b'}]}));
  assert.equal(swapped.result, 'rendered');
  assert.equal(swapped.ok, false);
  assert.match(swapped.problems[0], /differ from the build manifest/);
});

test('geometry uses the Chart zoom rule and the full phone viewport at the map zoom', () => {
  const [lat, lon] = PROFILE[bigSur].center, zoom = PROFILE[bigSur].zoom;
  // At view z10 (map z9, 728 px per degree) a 390 px wide phone spans ~0.54 deg of longitude: 0.15 deg east is inside it
  // (it would fall outside if the view zoom were used as the map zoom), 0.5 deg east is not.
  const near = line([[lon + 0.15, lat - 0.01], [lon + 0.15, lat + 0.01]]);
  const far = line([[lon + 0.5, lat - 0.01], [lon + 0.5, lat + 0.01]]);
  assert.equal(visibleLinesInView([{features: [near, far]}], [lat, lon], zoom), 1);
  // Tier bounds: minzoom inclusive, maxzoom exclusive (web/map/depth-contours.ts visibleAt).
  assert.equal(visibleAt({minzoom: 11, maxzoom: 13}, 11), true);
  assert.equal(visibleAt({minzoom: 11, maxzoom: 13}, 13), false);
  assert.equal(visibleAt({}, 3), true);
  const later = line(near.geometry.coordinates, {minzoom: 11});
  assert.equal(visibleLinesInView([{features: [later]}], [lat, lon], zoom), 0);
  // Survey edges and unresolved outlines are counted apart from contour lines; a polygon counts by its outline.
  const edge = {...near, properties: {kind: 'survey-edge'}};
  const ring = [[lon - 0.05, lat - 0.05], [lon + 0.05, lat - 0.05], [lon + 0.05, lat + 0.05], [lon - 0.05, lat - 0.05]];
  const area = {type: 'Feature', properties: {kind: 'unresolved-area'}, geometry: {type: 'Polygon', coordinates: [ring]}};
  assert.equal(visibleLinesInView([{features: [edge, area]}], [lat, lon], zoom), 0);
  assert.equal(visibleOthersInView([{features: [near, edge, area]}], [lat, lon], zoom), 2);
});
