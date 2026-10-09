// FE-51: the v2 trip planner and offline pack (web/trip.ts). The planner is
// v1's (dist/export-ui.js); these tests pin what the wrapper adds: the shared
// draft, the map adapter, the headless protected-area screen (the same GPX
// bytes as v1's map screen), the basemap plan's budget and the range recorder.
// tests/test_trip_export.mjs and the e2e ranked export cover the planner.
import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';

const read = path => readFileSync(new URL(`../dist/${path}`, import.meta.url), 'utf8');
const REGION = JSON.parse(read('regions/morro-bay/region.json'));
const {TILE_CAP, basemapRangeKey, planBasemap, planTiles} = await import('../dist/offline-core.js');
const {draftKey} = await import('../dist/trip-export.js');
const trip = await import('../web/trip.ts');

test('the account menu and mark card read the region\'s v1 draft, whatever it holds', () => {
  for (const id of ['morro-bay', 'cambria-san-simeon']) assert.equal(trip.draftKey(id), draftKey(id), 'the restated key is v1\'s');
  const store = new Map([[draftKey('morro-bay'), JSON.stringify({ids: ['SC26-001', 'SC26-001', 7, 'reef-2'], name: 'Day'})], [draftKey('bad'), '{']]);
  const storage = {getItem: k => store.get(k) ?? null};
  assert.deepEqual(trip.savedIds('morro-bay', storage), ['SC26-001', 'reef-2']);
  assert.deepEqual(trip.savedIds('bad', storage), []);
  assert.deepEqual(trip.savedIds(null, storage), []);
  assert.deepEqual(trip.savedIds('morro-bay', {getItem() { throw new Error('blocked'); }}), []);
});

test('the planner\'s Leaflet calls come from the shared camera and the chart\'s size', () => {
  // ?view= zoom 10 (256 px convention): 262,144 px around the world, so 512 px span 0.703° of longitude.
  const view = trip.mapView({latitude: 35.37, longitude: -120.86, zoom: 10}, {width: 512, height: 512});
  assert.deepEqual(view.getSize(), {x: 512, y: 512});
  const b = view.getBounds();
  assert.ok(Math.abs(b.getEast() - b.getWest() - 0.703125) < 1e-9);
  assert.ok(Math.abs((b.getWest() + b.getEast()) / 2 + 120.86) < 1e-9);
  assert.ok(b.getNorth() > 35.37 && b.getSouth() < 35.37 && b.getNorth() - 35.37 < 35.37 - b.getSouth(), 'Mercator: a pixel spans less latitude to the north');
  assert.equal(b.contains([35.37, -120.86]), true);
  assert.equal(b.contains([35.37, -120.4]), false);
  const none = trip.mapView(null, {width: 512, height: 512});
  assert.deepEqual(none.getSize(), {x: 0, y: 0}, 'no camera: v1 asks for the map first');
  assert.equal(none.getBounds().contains([35.37, -120.86]), false);
});

test('the ranked set moves the Chart to its extent', () => {
  assert.equal(trip.fitCamera([]), null);
  const c = trip.fitCamera([{latitude: 35.43, longitude: -121.17}, {latitude: 35.432, longitude: -121.002}]);
  assert.ok(Math.abs(c.latitude - 35.431) < 1e-9 && Math.abs(c.longitude + 121.086) < 1e-9);
  assert.ok(c.zoom > 10 && c.zoom < 12);
});

test('a Morro Bay pack stays inside the documented budget: chart and base map tiles at zoom 8–12, each under the cap', () => {
  const chart = planTiles(REGION.bounds), base = planBasemap(REGION.bounds);
  assert.equal(chart.maxZoom, 12, 'every zoom level fits');
  assert.equal(base.tiles.length, chart.tiles.length);
  assert.ok(base.tiles.length <= TILE_CAP, `${base.tiles.length} base map tiles`);
  assert.equal(base.tiles.length, 95, 'docs/web-app.md states this count');
  // A 512 px vector tile at archive zoom z draws map zoom z + 1: the same cells, one zoom lower.
  assert.deepEqual(base.tiles.map(t => [t.z + 1, t.x, t.y]), chart.tiles.map(t => [t.z, t.x, t.y]));
  assert.deepEqual([...new Set(base.tiles.map(t => t.z))], [7, 8, 9, 10, 11]);
});

test('the range recorder keeps each exact live range under the service worker\'s key, never a whole or saved answer', async () => {
  const archive = 'https://s.test/feeds/tiles/basemap/ca-coast-20261008.pmtiles';
  assert.equal(basemapRangeKey(archive, 'bytes=0-16383'), `${archive}?sc-range=0-16383`);
  for (const [url, range] of [[archive, 'bytes=0-'], [archive + '?v=1', 'bytes=0-1'], ['https://s.test/feeds/tiles/seafloor/x.pmtiles', 'bytes=0-1']])
    assert.equal(basemapRangeKey(url, range), null);
  const kept = [], realFetch = globalThis.fetch;
  const put = async (key, body, headers) => { kept.push([key, body.byteLength, headers.get('ETag')]); };
  try {
    globalThis.fetch = async (_url, init) => new Response(new Uint8Array(4), {status: 206, headers: {'Content-Range': `${init.headers.range.replace('=', ' ')}/99`, ETag: '"a"'}});
    const source = trip.rangeRecorder(archive, put, new AbortController().signal, basemapRangeKey);
    assert.equal(source.getKey(), archive);
    assert.deepEqual(await source.getBytes(16, 4), {data: new Uint8Array(4).buffer, etag: '"a"'});
    assert.deepEqual(kept, [[`${archive}?sc-range=16-19`, 4, '"a"']]);
    await assert.rejects(source.getBytes(16, 4, undefined, '"b"'), /changed while saving/);
    for (const response of [new Response('whole', {status: 200}), new Response('x', {status: 206, headers: {'X-SC-Offline': '2026-10-01T00:00:00Z'}})]) {
      globalThis.fetch = async () => response;
      await assert.rejects(source.getBytes(0, 1), /Basemap range/);
    }
    assert.equal(kept.length, 1);
  } finally { globalThis.fetch = realFetch; }
});

test('the headless protected-area screen is v1\'s: the same checks, and the same GPX bytes for the same selection', async () => {
  const restore = {document: globalThis.document, L: globalThis.L, fetch: globalThis.fetch};
  const stamp = new Date(Date.now() - 60000).toISOString();
  globalThis.document = {getElementById: () => null, createElement: () => ({textContent: '', classList: {toggle() {}}}), dispatchEvent: () => true};
  const drawn = [];
  const layer = {addTo() { return this; }, clearLayers() {}};
  globalThis.L = {layerGroup: () => layer, geoJSON: f => { drawn.push(f); return {bindTooltip() { return this; }, bindPopup() { return this; }, addTo() { return this; }}; }};
  // The committed snapshot, then the daily feed's fresh copy (the live service is unreachable here, as when it fails).
  globalThis.fetch = async url => {
    const u = new URL(url, 'https://s.test/');
    if (u.hostname !== 's.test') throw new TypeError('offline');
    if (u.pathname === '/api/daily') return Response.json({schema_version: 1, region_id: 'morro-bay', part: u.searchParams.get('part'), generated_at: stamp,
      catch_probability: null, bite_score: null, sources: {'mpa-boundaries': {status: 'ok', data_retrieved_at: stamp, data: {geojson: JSON.parse(read(REGION.assets.protected_areas))}}}});
    return new Response(read(u.pathname.slice(1)), {headers: {'Content-Type': 'application/json'}});
  };
  try {
    (await import('../dist/region.js')).setRegion(REGION);
    const {initProtectedAreas} = await import('../dist/protected-areas.js');
    const v1 = await initProtectedAreas({createPane: () => ({style: {}}), getZoom: () => 10}, () => {});
    const shown = drawn.length;
    const v2 = await initProtectedAreas(null, () => {});
    assert.ok(shown > 0 && drawn.length === shown, 'the headless screen draws nothing');
    await Promise.all([v1.refresh(), v2.refresh()]);
    assert.equal(v1.ready(), true);
    assert.equal(v2.ready(), true);
    const atlas = JSON.parse(read(REGION.assets.atlas));
    for (const t of atlas.targets) assert.equal(v2.pointAllowed(t), v1.pointAllowed(t), t.id);
    const ids = atlas.targets.filter(t => v1.pointAllowed(t)).slice(0, 6).map(t => t.id);
    assert.equal(ids.length, 6);
    const {buildExport} = await import('../dist/trip-export.js');
    const layers = {waypoints: true, outlines: true, alignments: true, exclusions: true};
    const gpx = screen => buildExport({atlas, screen, ids, layers, region: REGION, title: 'My fishing day · 2026-10-10', bounds: REGION.mpa.bounds,
      now: new Date('2026-10-09T12:00:00Z'), allowResearch: true}).gpx;
    assert.equal(gpx(v2), gpx(v1));
    assert.match(gpx(v2), /<wpt /);
  } finally { Object.assign(globalThis, restore); }
});
