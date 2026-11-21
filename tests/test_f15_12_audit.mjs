// SCA-458 / F15-12 (MB contours): z18 magnifies z17;
// it must not add native detail or silently erase the survey gap.
// Default CI: real projection over synthetic controls. Diagnostic replay:
//   node tests/test_f15_12_audit.mjs --baseline
// The replay reports the gap without making it an expected production result.
import assert from 'node:assert/strict';
import test from 'node:test';
import {isDeepStrictEqual} from 'node:util';
import {signal} from '@preact/signals';
import {createDepthContours, DEPTH_HIT, DEPTH_UNRESOLVED_FILL, depthContoursURL} from '../web/map/depth-contours.ts';
import {mapOptions, ZOOM_OFFSET} from '../web/map/engine.ts';
import {DEPTH_CONTOURS_SOURCE} from '../web/map/layers.ts';
import {camera} from '../web/map/stage.ts';
import {region} from '../web/state.ts';

const START = 17, REQUEST = 18, REGION = 'fixture-region';
// Invented patch around the origin: a contour on the surveyed side, the
// boundary at x=0, and an unresolved polygon immediately across the boundary.
const source = {source_id: 'fixture', name: 'Fixture survey', survey_date: '2025', vertical_datum: 'fixture datum', native_cell_m: 2};
const feature = (id, type, coordinates, properties) => ({type: 'Feature', id, geometry: {type, coordinates}, properties: {
  source_id: source.source_id, survey_date: source.survey_date, vertical_datum: source.vertical_datum,
  minzoom: 8, index: false, ...properties,
}});
const features = [
  feature('depth', 'LineString', [[-0.001, -0.001], [-0.001, 0.001]], {kind: 'contour', depth_ft: 15, minzoom: 15, estimated: true}),
  feature('edge', 'LineString', [[0, -0.001], [0, 0.001]], {kind: 'survey-edge'}),
  feature('gap', 'Polygon', [[[0, -0.001], [0.001, -0.001], [0.001, 0.001], [0, 0.001], [0, -0.001]]], {kind: 'unresolved-area', reason: 'hole'}),
];
const file = {type: 'FeatureCollection', features, provenance: {
  region_id: REGION, units: 'ft', set: 'ft-v2', shelf_limit_ft: 300, index_depths_ft: [60, 150, 300],
  intervals: [
    {minzoom: 8, depths_ft: [60, 120, 180, 240, 300]},
    {minzoom: 11, depths_ft: [30, 90, 150, 210, 270]},
    {minzoom: 13, depths_ft: [10, 20, 40, 50, 70, 80, 100]},
    {minzoom: 15, depths_ft: [5, 15, 25], native_max_cell_m: 2},
  ],
  review_expires: '2027-01-01', sources: [source], sources_omitted: [],
}};
const warnings = [['edge', DEPTH_HIT, /missing data, not flat water/],
  ['gap', DEPTH_UNRESOLVED_FILL, /no usable measurement/]];
const byId = (items, id) => items.find(f => f.id === id);

function endpointGaps(before, after) {
  const issues = [];
  if (![START, REQUEST].includes(after.zoom)) issues.push(`unexpected endpoint z${after.zoom}`);
  for (const [id] of warnings) {
    const f = byId(after.features, id);
    if (!f || !after.warnings.includes(id)) issues.push(`lost ${id} warning`);
    else if (!isDeepStrictEqual(f.geometry, byId(before.features, id).geometry)) issues.push(`changed ${id} geometry`);
  }
  const detail = ({geometry, properties: {contour_label, ...properties}}) => ({geometry, properties});
  for (const f of after.features.filter(f => f.properties.kind === 'contour')) {
    // Compare the whole line, including depth, geometry and provenance. A
    // finer line at the old depth is still new detail, even with the same ID.
    const prior = byId(before.features, f.id);
    if (!prior || !isDeepStrictEqual(detail(f), detail(prior))) issues.push(`new contour detail: ${f.id}`);
  }
  return issues;
}

async function replay(t, cap) {
  const centre = {longitude: 0, latitude: 0, zoom: START};
  const page = () => 'https://fixture.invalid/map';
  const requested = [], url = new URL(depthContoursURL(REGION), page()).href;
  let data;
  region.value = REGION;
  camera.value = centre;
  const engine = signal({
    setOverlay() {},
    setData(id, collection) { if (id === DEPTH_CONTOURS_SOURCE) data = collection.features; },
  });
  const layer = createDepthContours({engine, page, palette: () => ({mapContourWidth: '1'}),
    now: () => Date.parse('2026-11-19T00:00:00Z'),
    fetchFn: async href => { requested.push(href); return href === url ? Response.json(file) : new Response(null, {status: 404}); },
  });
  t.after(() => { layer.destroy(); camera.value = null; region.value = null; });
  await new Promise(resolve => setImmediate(resolve));
  function observe() {
    assert.ok(data, 'the checked ft-v2 file reached the overlay source');
    return {zoom: camera.value.zoom, features: structuredClone(data), warnings: warnings.flatMap(([id, hitLayer, text]) => {
      const f = byId(data, id);
      return f && text.test(layer.pick.mark(hitLayer, f.properties)?.reading ?? '') ? [id] : [];
    })};
  }
  const before = observe();
  assert.deepEqual(before.features.map(f => f.id).sort(), ['depth', 'edge', 'gap'], 'z17 has a contour, edge and gap');
  assert.deepEqual(before.warnings, ['edge', 'gap'], 'z17 distinguishes missing measurements from flat water');
  // Model the renderer's maxZoom clamp at the engine boundary, in app units.
  const max = cap ?? (mapOptions({}, {version: 8, sources: {}, layers: []}, centre).maxZoom + ZOOM_OFFSET);
  camera.value = {...centre, zoom: Math.min(REQUEST, max)};
  const after = observe();
  assert.deepEqual(requested, [url], 'one synthetic file; no new detail fetch on zoom');
  return {before, after};
}

if (process.argv.includes('--baseline')) {
  test('F15-12: camera and contour projection, read-only receipt', async t => {
    const {before, after} = await replay(t);
    t.diagnostic(`app zoom ${before.zoom} -> ${after.zoom} (requested ${REQUEST}); z17 source IDs: ${before.features.map(f => f.id).join(', ')}; endpoint source IDs: ${after.features.map(f => f.id).join(', ') || 'none'}`);
    const issues = endpointGaps(before, after);
    t.diagnostic(issues.length ? `GAP: ${issues.join('; ')}` : 'NO GAP');
  });
} else {
  test('F15-12: zooming to z18 retains the z17 coverage and detail', async t => {
    const {before, after} = await replay(t);
    assert.equal(after.zoom, REQUEST);
    assert.deepEqual(endpointGaps(before, after), []);
    assert.deepEqual(after.features, before.features, 'z18 magnifies the same overlay');
  });

  test('F15-12: an empty projection or invented detail at z18 fails the endpoint contract', async t => {
    const {before} = await replay(t, START);
    assert.deepEqual(endpointGaps(before, {zoom: REQUEST, features: [], warnings: []}), ['lost edge warning', 'lost gap warning']);
    const changed = {...before, zoom: REQUEST, features: structuredClone(before.features)};
    byId(changed.features, 'depth').geometry.coordinates[0][0] *= 2;
    assert.deepEqual(endpointGaps(before, changed), ['new contour detail: depth']);
  });
}
