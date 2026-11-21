import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {signal} from '@preact/signals';
import {createCharterGrounds, groundsAvailability} from '../web/map/charter-grounds.ts';
import {aisAvailability, aisOn, createCommercialAis} from '../web/map/commercial-ais.ts';
import {MARKS_SOURCE, SELECTION_SOURCE, terrainLayers} from '../web/map/layers.ts';
import {createMarks, marksAvailability, markScreen, markSources, spotCard} from '../web/map/marks.ts';
import {markFeatures} from '../web/map/habitat.ts';
import {configureStore, syncFromURL} from '../web/state.ts';

const PAGE = 'https://s.test/map';
const MORRO = 'morro-bay', CAMBRIA = 'cambria-san-simeon', SOUTH = 'southern-california';
const NOW = Date.parse('2026-10-09T18:00:00Z');
const bytes = path => readFileSync(new URL(`../dist/${path}`, import.meta.url));
const read = path => JSON.parse(bytes(path));
const snapshot = read('data/protected-areas.geojson');
const metaPath = id => `regions/${id}/region.json`;
const fullAtlas = id => `regions/${id}/atlas.json`;
const startup = id => `regions/${id}/atlas-marks.json`;
const meta = (id, assets) => ({...read(metaPath(id)), mpa: {bounds: [-121, 32, -117, 36], minimum_features: 1}, assets});
const json = d => Response.json(d);
const flush = () => new Promise(resolve => setImmediate(resolve));
const marksCount = () => markSources[MARKS_SOURCE].value.features.length;
const verdicts = () => [marksAvailability.value, groundsAvailability.value, aisAvailability.value];

function setup(t, id, overrides = {}, {spot, start = true} = {}) {
  const go = (region, selection) => {
    globalThis.location = {href: `${PAGE}?region=${region}&profile=boat&target=reef&layers=fleet${selection ? `&spot=${selection}` : ''}`};
    syncFromURL(location.href);
  };
  configureStore({v2: true, storage: null});
  go(id, spot);
  const requests = [], overlays = new Map();
  const fetchFn = async url => {
    const path = new URL(url).pathname.slice(1);
    requests.push(path);
    if (Object.hasOwn(overrides, path)) return overrides[path]();
    try { return new Response(bytes(path)); }
    catch { return new Response(null, {status: 404}); }
  };
  const engine = signal({setOverlay(key, data) { if (data) overlays.set(key, data); else overlays.delete(key); }, setData() {}});
  const opts = {engine, fetchFn, page: () => PAGE, palette: () => ({amber: 'amber', bg: 'black'})};
  const marks = createMarks({...opts, now: () => NOW, liveMpaRead: async () => ({data: snapshot, checkedAt: new Date(NOW).toISOString()})});
  aisOn.value = start;
  const grounds = createCharterGrounds(opts), ais = createCommercialAis(opts);
  t.after(() => { ais.destroy(); grounds.destroy(); marks.destroy(); aisOn.value = false; delete globalThis.location; });
  return {go, requests, overlays};
}

// Test the real loader and source together: collapsing bound failures into a zero count would mislead the next legend.
for (const [label, status, binding, atlas] of [
  ['zero targets', 'empty', fullAtlas(CAMBRIA), () => json({region_id: CAMBRIA, targets: []})],
  ['no binding', 'no-product', null, () => { throw new Error('unbound atlas requested'); }],
  ['malformed atlas', 'failed', fullAtlas(CAMBRIA), () => new Response('{')],
  ['malformed entry', 'failed', fullAtlas(CAMBRIA), () => json({region_id: CAMBRIA, targets: [null]})],
  ['missing bound bytes', 'failed', fullAtlas(CAMBRIA), () => new Response(null, {status: 404})],
]) {
  test(`marks-availability: ${label}`, async t => {
    const {requests} = setup(t, CAMBRIA, {
      [metaPath(CAMBRIA)]: () => json(meta(CAMBRIA, {atlas: binding})),
      [startup(CAMBRIA)]: atlas,
      [fullAtlas(CAMBRIA)]: atlas,
    });
    await flush();
    assert.deepEqual(verdicts(), [status, 'no-product', 'no-product']);
    assert.equal(marksCount(), 0);
    if (!binding) assert.ok(!requests.includes(startup(CAMBRIA)) && !requests.includes(fullAtlas(CAMBRIA)));
  });
}

// Nonempty atlas counts and per-target depth qualification must not publish unranked Southern reference coordinates.
test('marks-availability: Southern atlas is held even with a current boundary check', async t => {
  const atlas = read(startup(SOUTH));
  assert.equal(atlas.targets.length, 11);
  setup(t, SOUTH, {[metaPath(SOUTH)]: () => json(meta(SOUTH, {atlas: fullAtlas(SOUTH)}))}, {spot: atlas.targets[0].id});
  await flush();
  assert.equal(markScreen.value.status, 'ready');
  assert.ok(markFeatures(atlas, 'reef', 'boat', markScreen.value).features.length > 0, 'the screen alone would admit these candidates');
  assert.deepEqual(verdicts(), ['held', 'no-product', 'no-product']);
  assert.equal(marksCount(), 0);
  assert.equal(markSources[SELECTION_SOURCE].value.features.length, 0, 'a direct link cannot restore a held mark');
  assert.equal(spotCard.value, null);
});

// A region lookup failure is unknown coverage, not evidence that no product was bound.
test('marks-availability: metadata failure applies to all three checks', async t => {
  setup(t, CAMBRIA, {[metaPath(CAMBRIA)]: () => new Response(null, {status: 500})});
  await flush();
  assert.deepEqual(verdicts(), ['failed', 'failed', 'failed']);
});

// A slow second region must not keep Morro features on either renderer or leave Morro's checks active.
test('marks-availability: Morro clears before Cambria metadata resolves', async t => {
  let resolveCambria;
  const pending = new Promise(resolve => { resolveCambria = resolve; });
  const {go, overlays} = setup(t, MORRO, {[metaPath(CAMBRIA)]: () => pending});
  // Morro's startup asset is hash-verified by Web Crypto, which need not complete in one tick.
  for (let i = 0; i < 200 && verdicts().some(s => s !== 'ready'); i++) await new Promise(resolve => setTimeout(resolve, 5));
  assert.deepEqual(verdicts(), ['ready', 'ready', 'ready']);
  assert.ok(marksCount() > 0);
  assert.ok(terrainLayers.value.marks.features.length > 0);
  assert.equal(overlays.size, 2);
  go(CAMBRIA);
  assert.deepEqual(verdicts(), [null, null, null]);
  assert.equal(marksCount(), 0);
  assert.equal(terrainLayers.value.marks.features.length, 0);
  assert.equal(terrainLayers.value['charter-grounds'], undefined);
  assert.equal(overlays.size, 0);
  resolveCambria(json(meta(CAMBRIA, {atlas: fullAtlas(CAMBRIA)})));
  await flush();
  assert.deepEqual(verdicts(), ['empty', 'no-product', 'no-product']);
});

// Contract: a charter file whose outline is a shell (a Polygon with no coordinates) is failed, not drawn.
// Bug caught: validating only `!!geometry` accepted it and the ready boundary screen threw in hatchLines.
for (const [label, geometry] of [['no coordinates', {type: 'Polygon'}], ['empty rings', {type: 'Polygon', coordinates: []}], ['non-numeric point', {type: 'Polygon', coordinates: [[[0, 0], [1, 'x'], [1, 1], [0, 0]]]}], ['not a polygon', {type: 'Point', coordinates: [0, 0]}]]) {
  test(`marks-availability: charter ground with ${label} outline is failed`, async t => {
    const grounds = 'test/ground.json';
    const ground = {id: 'G', latitude: 35.5, longitude: -121.9, depth_ft: [10, 60], map_species: ['lingcod'], reports: [{species: ['lingcod']}], geometry};
    const {overlays} = setup(t, CAMBRIA, {
      [metaPath(CAMBRIA)]: () => json(meta(CAMBRIA, {charters: grounds})),
      [grounds]: () => json({grounds: [ground]}),
    });
    await flush();
    assert.equal(groundsAvailability.value, 'failed');
    assert.equal(overlays.size, 0);
  });
}

// Each public fleet loader distinguishes an inspected empty file from an unusable one; the AIS option stays lazy.
test('marks-availability: fleet empty vs invalid, without fetching an off option', async t => {
  const grounds = 'test/ground.json', ais = 'test/cells.json';
  const {requests, overlays} = setup(t, CAMBRIA, {
    [metaPath(CAMBRIA)]: () => json(meta(CAMBRIA, {charters: grounds, commercial_ais: ais})),
    [grounds]: () => json({grounds: []}),
    [ais]: () => json({type: 'FeatureCollection', features: [null]}),
  }, {start: false});
  await flush();
  assert.deepEqual(verdicts(), ['no-product', 'empty', null]);
  assert.ok(!requests.includes(ais));
  aisOn.value = true;
  await flush();
  assert.deepEqual(verdicts(), ['no-product', 'empty', 'failed']);
  assert.equal(overlays.size, 0);
});

// Contract: an AIS cell missing a field the picker card reads is a failed asset, not a ready one.
// Bug caught: validating only id, coordinates and geometry reported `ready`, then selecting a cell without
// `apparent_fishing_hours` threw in aisMark (`hours(undefined)`).
const AIS_CELL = read('data/commercial-ais-effort.geojson').features[0];
for (const field of ['apparent_fishing_hours', 'days_with_apparent_fishing', 'active_dates_utc', 'label', 'gear_label', 'resolution_note', 'fishing_location_confidence', 'vessel_count_note']) {
  test(`marks-availability: AIS cell without ${field} is failed`, async t => {
    const ais = 'test/cells.json', {[field]: _dropped, ...properties} = AIS_CELL.properties;
    const {overlays} = setup(t, CAMBRIA, {
      [metaPath(CAMBRIA)]: () => json(meta(CAMBRIA, {commercial_ais: ais})),
      [ais]: () => json({type: 'FeatureCollection', features: [{...AIS_CELL, properties}]}),
    });
    await flush();
    assert.equal(aisAvailability.value, 'failed');
    assert.equal(overlays.size, 0);
  });
}
