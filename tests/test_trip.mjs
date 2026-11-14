// FE-51: the v2 trip planner and offline pack (web/trip.ts). The planner's
// own state is tests/test_planner.mjs; these tests pin what trip.ts adds: the shared
// draft, the map adapter, the headless protected-area screen (the same GPX
// bytes as v1's map screen), the basemap plan's budget and the range recorder.
// tests/test_trip_export.mjs and the e2e ranked export cover the planner.
import assert from 'node:assert/strict';
import test, {mock} from 'node:test';
import {readFileSync} from 'node:fs';

const read = path => readFileSync(new URL(`../dist/${path}`, import.meta.url), 'utf8');
const REGION = JSON.parse(read('regions/morro-bay/region.json'));
const {TILE_CAP, basemapRangeKey, planBasemap, planTiles} = await import('../dist/offline-core.js');
const {draftKey} = await import('../dist/trip-export.js');
const trip = await import('../web/trip.ts');
// SC1407-10: the pure helpers live in the lazily loaded implementation; savePack still runs through the facade.
const runtime = await import('../web/trip-runtime.ts');

test('the account menu and mark card read the region\'s v1 draft, whatever it holds', () => {
  for (const id of ['morro-bay', 'cambria-san-simeon']) assert.equal(trip.draftKey(id), draftKey(id), 'the restated key is v1\'s');
  const store = new Map([[draftKey('morro-bay'), JSON.stringify({ids: ['SC26-001', 'SC26-001', 7, 'reef-2'], name: 'Day'})], [draftKey('bad'), '{']]);
  const storage = {getItem: k => store.get(k) ?? null};
  assert.deepEqual(trip.savedIds('morro-bay', storage), ['SC26-001', 'reef-2']);
  assert.deepEqual(trip.savedIds('bad', storage), []);
  assert.deepEqual(trip.savedIds(null, storage), []);
  assert.deepEqual(trip.savedIds('morro-bay', {getItem() { throw new Error('blocked'); }}), []);
});

test('the planner\'s map calls come from the shared camera and the chart\'s size', () => {
  // ?view= zoom 10 (256 px convention): 262,144 px around the world, so 512 px span 0.703° of longitude.
  const view = runtime.mapView({latitude: 35.37, longitude: -120.86, zoom: 10}, {width: 512, height: 512});
  assert.deepEqual(view.getSize(), {x: 512, y: 512});
  const b = view.getBounds();
  assert.ok(Math.abs(b.getEast() - b.getWest() - 0.703125) < 1e-9);
  assert.ok(Math.abs((b.getWest() + b.getEast()) / 2 + 120.86) < 1e-9);
  assert.ok(b.getNorth() > 35.37 && b.getSouth() < 35.37 && b.getNorth() - 35.37 < 35.37 - b.getSouth(), 'Mercator: a pixel spans less latitude to the north');
  assert.equal(b.contains([35.37, -120.86]), true);
  assert.equal(b.contains([35.37, -120.4]), false);
  const none = runtime.mapView(null, {width: 512, height: 512});
  assert.deepEqual(none.getSize(), {x: 0, y: 0}, 'no camera: v1 asks for the map first');
  assert.equal(none.getBounds().contains([35.37, -120.86]), false);
});

test('the ranked set moves the Chart to its extent', () => {
  assert.equal(runtime.fitCamera([]), null);
  const c = runtime.fitCamera([{latitude: 35.43, longitude: -121.17}, {latitude: 35.432, longitude: -121.002}]);
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
    const source = runtime.rangeRecorder(archive, put, new AbortController().signal, basemapRangeKey);
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

// RF1036-8: a 206 is stored under the requested range key only when it really is that slice.
async function recordRange(offset, length, answer, etag) {
  const archive = 'https://s.test/feeds/tiles/basemap/ca-coast-20261008.pmtiles', realFetch = globalThis.fetch;
  const puts = [], fetches = [], reads = {n: 0};
  const put = async (key, body, headers) => { puts.push([key, new Uint8Array(body), headers.get('Content-Range')]); };
  globalThis.fetch = async (url, init) => {
    fetches.push(init.headers.range);
    const {range, bytes, status = 206, headers = {}} = answer(init);
    const response = new Response(bytes, {status, headers: range ? {'Content-Range': range, ...headers} : headers});
    const read = response.arrayBuffer.bind(response);
    response.arrayBuffer = () => { reads.n++; return read(); };
    return response;
  };
  try {
    const source = runtime.rangeRecorder(archive, put, new AbortController().signal, basemapRangeKey);
    const out = await source.getBytes(offset, length, undefined, etag).then(value => ({value}), error => ({error}));
    return {...out, puts, fetches, reads: reads.n, archive};
  } finally { globalThis.fetch = realFetch; }
}
const distinct = n => Uint8Array.from({length: n}, (_, i) => i + 1);

test('range_header_identity_before_write: only the requested slice is saved, and a wrong answer is refused before it is read', async () => {
  const ok = await recordRange(16, 4, () => ({range: 'bytes 16-19/99', bytes: distinct(4)}));
  assert.equal(ok.error, undefined);
  assert.equal(ok.puts.length, 1);
  assert.equal(ok.puts[0][0], `${ok.archive}?sc-range=16-19`);
  assert.ok(Buffer.from(ok.puts[0][1]).equals(Buffer.from(distinct(4))) && Buffer.from(ok.value.data).equals(Buffer.from(distinct(4))), 'the bytes are kept unchanged');
  assert.equal((await recordRange(16, 4, () => ({range: '  bytes 16-19/*  ', bytes: distinct(4)}))).puts.length, 1, 'an unknown total with the full slice is fine');
  for (const [name, range] of [['wrong start', 'bytes 20-23/99'], ['wrong end', 'bytes 16-18/*'], ['past the request', 'bytes 16-20/99'], ['missing', undefined], ['bad unit', 'items 16-19/99'],
    ['reversed', 'bytes 19-16/99'], ['impossible total', 'bytes 16-19/19'], ['trailing junk', 'bytes 16-19/99 x'], ['multipart', 'bytes 16-17/99, 18-19/99'], ['unsatisfied', 'bytes */99'],
    ['unsafe field', 'bytes 16-19/99999999999999999999']]) {
    const r = await recordRange(16, 4, () => ({range, bytes: distinct(4)}));
    assert.match(String(r.error?.message), /Basemap range bytes=16-19/, name);
    assert.equal(r.puts.length, 0, `${name}: nothing written`);
    assert.equal(r.reads, 0, `${name}: the body is never read`);
  }
});

test('range_body_cardinality_before_write: the body must be exactly as long as the answered interval', async () => {
  for (const n of [0, 3, 5]) {
    const r = await recordRange(16, 4, () => ({range: 'bytes 16-19/99', bytes: distinct(n)}));
    assert.match(String(r.error?.message), /wrong length/, `${n} bytes`);
    assert.equal(r.puts.length, 0, `${n} bytes: nothing written`);
  }
  const ok = await recordRange(16, 4, () => ({range: 'bytes 16-19/99', bytes: distinct(4)}));
  assert.equal(ok.puts.length, 1);
});

test('small_archive_eof_is_not_truncation: a range clipped at the known end is kept, a premature or unproven short one is not', async () => {
  const eof = await recordRange(0, 16384, () => ({range: 'bytes 0-99/100', bytes: distinct(100)}));
  assert.equal(eof.error, undefined);
  assert.equal(eof.puts.length, 1);
  assert.equal(eof.puts[0][0], `${eof.archive}?sc-range=0-16383`, 'kept under the key of the request');
  assert.equal(eof.puts[0][2], 'bytes 0-99/100', 'with its truthful Content-Range');
  assert.equal(eof.value.data.byteLength, 100);
  for (const [name, range, n] of [['premature end', 'bytes 0-98/100', 99], ['unknown total', 'bytes 0-99/*', 100], ['one byte missing', 'bytes 0-99/100', 99],
    ['request ends inside the archive', 'bytes 0-99/20000', 100]]) {
    const r = await recordRange(0, 16384, () => ({range, bytes: distinct(n)}));
    assert.ok(r.error, name);
    assert.equal(r.puts.length, 0, `${name}: nothing written`);
  }
});

test('range_request_integer_bounds: an impossible request is refused before any fetch', async () => {
  for (const [offset, length] of [[-1, 4], [1.5, 4], [NaN, 4], [Infinity, 4], [2 ** 53, 4], [0, 0], [0, -3], [0, 2.5], [0, 2 ** 53], [Number.MAX_SAFE_INTEGER, 2]]) {
    const r = await recordRange(offset, length, () => ({range: 'bytes 0-0/1', bytes: distinct(1)}));
    assert.match(String(r.error?.message), /not a valid range/, `${offset},${length}`);
    assert.equal(r.fetches.length + r.puts.length, 0, `${offset},${length}: no request, no write`);
  }
  const zero = await recordRange(0, 1, () => ({range: 'bytes 0-0/1', bytes: distinct(1)}));
  assert.equal(zero.puts.length, 1);
});

test('existing_safety_and_failure_controls: a saved or whole answer, a changed archive and a failing network or store still refuse', async () => {
  const good = {range: 'bytes 16-19/99', bytes: distinct(4), headers: {ETag: '"a"'}};
  const changed = await recordRange(16, 4, () => good, '"b"');
  assert.match(String(changed.error?.message), /changed while saving/);
  assert.equal(changed.puts.length, 0);
  const weak = await recordRange(16, 4, () => ({...good, headers: {ETag: 'W/"a"'}}));
  assert.equal(weak.value.etag, undefined, 'a weak ETag is not handed back');
  assert.equal((await recordRange(16, 4, () => good, '"a"')).value.etag, '"a"');
  for (const answer of [{...good, status: 200}, {...good, headers: {'X-SC-Offline': '2026-10-01T00:00:00Z'}}]) {
    const r = await recordRange(16, 4, () => answer);
    assert.match(String(r.error?.message), /Basemap range bytes=16-19: HTTP/);
    assert.equal(r.puts.length, 0);
  }
  const realFetch = globalThis.fetch, mine = new AbortController(), seen = [];
  try {
    globalThis.fetch = async (_u, init) => { seen.push(init.signal); throw new TypeError('network down'); };
    const source = runtime.rangeRecorder('https://s.test/feeds/tiles/basemap/ca-coast-20261008.pmtiles', async () => {}, new AbortController().signal, basemapRangeKey);
    await assert.rejects(source.getBytes(16, 4, mine.signal), /network down/);
    assert.deepEqual(seen, [mine.signal]);
    globalThis.fetch = async () => new Response(distinct(4), {status: 206, headers: {'Content-Range': 'bytes 16-19/99'}});
    const failing = runtime.rangeRecorder('https://s.test/feeds/tiles/basemap/ca-coast-20261008.pmtiles', async () => { throw new Error('quota'); }, new AbortController().signal, basemapRangeKey);
    await assert.rejects(failing.getBytes(16, 4), /quota/);
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

// SC1938-04: the pack's ocean phase, through the real trip.savePack and dist/offline-pack.js, with a fake Cache Storage, a fake network
// and a mocked clock (nothing here reads the real time or the network). The SST layer is left out of these manifests; its clocks are
// tests/test_ocean_pack.mjs's.
const {isOceanKey, PACK_META} = await import('../dist/offline-core.js');
const {wcofsFeed} = await import('./helpers/wcofs-feed.mjs');
const SAVE_AT = Date.parse('2026-10-16T08:00:00Z'), FEEDS = 'https://s.test/feeds/conditions/regions/', PRIOR_KEY = 'https://s.test/prior.json';
const WCOFS = 'wcofs-surface-forecast', STORAGE_MESSAGE = 'storage on this device is full or unavailable. Saved regions are unchanged.';
class FakeCache {
  constructor(owner, name) { this.owner = owner; this.name = name; this.map = new Map(); }
  async put(k, r) {
    const key = String(k?.url ?? k), error = this.owner.fail?.(this.name, key);
    if (error) throw error;
    this.map.set(key, {bytes: Buffer.from(await r.arrayBuffer()), headers: [...r.headers]});
  }
  async match(k) { const e = this.map.get(String(k?.url ?? k)); return e && new Response(e.bytes, {headers: e.headers}); }
  async keys() { return [...this.map.keys()].map(url => ({url})); }
}
class FakeCaches {
  constructor() { this.map = new Map(); this.fail = null; }
  async open(name) { if (!this.map.has(name)) this.map.set(name, new FakeCache(this, name)); return this.map.get(name); }
  async keys() { return [...this.map.keys()]; }
  async has(name) { return this.map.has(name); }
  async delete(name) { return this.map.delete(name); }
  snapshot() { return JSON.stringify([...this.map].map(([n, c]) => [n, [...c.map].map(([k, v]) => [k, v.bytes.toString('base64')])])); }
  packs() { return [...this.map].filter(([n]) => n.startsWith('sc-pack-')); }
}
const configOf = id => id === 'test-coast' ? JSON.parse(read('regions/morro-bay/region.json').replaceAll('morro-bay', 'test-coast')) : JSON.parse(read(`regions/${id}/region.json`));
const oceanFeed = (id, opts = {}) => wcofsFeed({region: id, times: [SAVE_AT / 1000 - 3600, SAVE_AT / 1000], flow: () => [0.2, -0.1], issuedAt: '2026-10-16T03:00:00Z', retrievedAt: '2026-10-16T06:00:00Z',
  grids: [{bounds: [-121, 35, -120.85, 35.2], cells: [[35.05, -120.95], [35.1, -120.9]]}], ...opts});

/** One trip.savePack run. `fail(cacheName, key)` may reject a write; `abortOn(url)` aborts as that URL is asked; `prior` seeds an older pack and some unrelated data. */
async function packRun({id = 'test-coast', manifestStatus = 200, feedOpts, fail, abortOn, prior = true, seed} = {}) {
  const saved = {caches: globalThis.caches, location: globalThis.location, document: globalThis.document, fetch: globalThis.fetch};
  const had = Object.fromEntries(Object.keys(saved).map(k => [k, k in globalThis])), caches = new FakeCaches(), controller = new AbortController(), asked = [], phases = [];
  const feed = oceanFeed(id, feedOpts), base = `${FEEDS}${id}/`, config = configOf(id);
  if (prior) {
    const old = await caches.open(`sc-pack-${id}-1`);
    await old.put(PACK_META, Response.json({schema_version: 1, region_id: id, region_name: 'Old', saved_at: '2026-10-01T00:00:00.000Z', bytes: 3, missing: [], tiles: {saved: 0, planned: 0, min_zoom: 8, max_zoom: 12}}));
    await old.put(PRIOR_KEY, new Response('old'));
  }
  await seed?.(caches);
  const before = caches.snapshot();
  caches.fail = fail ? (name, key) => fail(name, key, controller) : null;
  Object.assign(globalThis, {caches, location: new URL('https://s.test/'), document: {getElementById: () => null}});
  globalThis.fetch = async (input, init) => {
    const url = String(input?.url ?? input), u = new URL(url, 'https://s.test/');
    asked.push(url);
    if (abortOn?.(url)) controller.abort();
    if (u.pathname === '/regions/index.json') return Response.json({default_region: id, regions: [{id, config: `regions/${id}/region.json`}]});
    if (u.pathname === `/regions/${id}/region.json`) return Response.json(config);
    if (url === `${base}habitat-dynamics.json`) return manifestStatus === 200 ? Response.json(feed.manifest) : new Response('no', {status: manifestStatus});
    const tile = feed.tiles.find(t => url === base + t.record.path);
    return tile ? new Response(tile.bytes) : new Response('Not found', {status: 404});
  };
  mock.timers.enable({apis: ['Date'], now: SAVE_AT});
  try {
    const meta = await trip.savePack(id, controller.signal, p => phases.push(p.phase)).then(m => ({meta: m}), error => ({error}));
    return {...meta, caches, before, asked, phases, feed, controller, bodies: name => [...caches.map.get(name).map].map(([k, v]) => [k, v.bytes])};
  } finally {
    mock.timers.reset();
    for (const k of Object.keys(saved)) if (had[k]) globalThis[k] = saved[k]; else Reflect.deleteProperty(globalThis, k);
  }
}
const oceanKeys = (caches, name) => [...caches.map.get(name).map.keys()].filter(k => isOceanKey(k, 'https://s.test'));

test('a regional pack saves the ocean phase last and records it at the meta top level, its bytes counted once', async () => {
  const run = await packRun(), {meta, caches} = run;
  assert.equal(run.error, undefined, String(run.error));
  assert.equal(meta.schema_version, 1);
  const [name, ...rest] = caches.packs().map(([n]) => n);
  assert.deepEqual([rest.length, name === 'sc-pack-test-coast-1'], [0, false], 'the older pack of the region goes after the commit');
  const ocean = meta.ocean, base = `${FEEDS}test-coast/`, tileKey = base + run.feed.tiles[0].record.path;
  assert.equal(ocean.schema_version, 1);
  assert.equal(ocean.path, 'regional');
  assert.deepEqual(Object.keys(meta.v2).sort(), ['basemap', 'build', 'missing', 'shell'], 'ocean is the meta\'s own field, not inside v2');
  assert.deepEqual(ocean.layers[WCOFS], {state: 'saved', tiles: {saved: 1, listed: 1}, bytes: run.feed.tiles[0].bytes.length, data_at: '2026-10-16T03:00:00.000Z',
    retrieved_at: '2026-10-16T06:00:00.000Z', max_age_hours: 36, drawable_until: '2026-10-16T12:00:00.000Z'});
  assert.equal(ocean.layers['sst-analysis'].state, 'absent');
  assert.deepEqual(oceanKeys(caches, name).sort(), [base + 'habitat-dynamics.json', tileKey].sort(), 'the pack holds the manifest and the saved tile, nothing else ocean');
  const stored = Object.fromEntries(run.bodies(name));
  assert.equal(ocean.manifest.bytes, stored[base + 'habitat-dynamics.json'].length);
  assert.equal(ocean.bytes, ocean.manifest.bytes + ocean.layers[WCOFS].bytes, 'meta.ocean.bytes: the manifest and the saved layers');
  assert.equal(ocean.bytes, oceanKeys(caches, name).reduce((a, k) => a + stored[k].length, 0), 'every ocean byte in the pack');
  assert.equal(meta.bytes, run.bodies(name).filter(([k]) => k !== PACK_META).reduce((a, [, b]) => a + b.length, 0), 'meta.bytes counts every stored byte, the ocean ones once');
  assert.equal(run.asked.filter(u => u === base + 'habitat-dynamics.json').length, 1, 'the files phase does not fetch the manifest; the ocean phase does, once');
  assert.ok(meta.missing.every(u => !isOceanKey(u, 'https://s.test')) && meta.v2.missing.every(u => !isOceanKey(u, 'https://s.test')), 'ocean misses are listed only under ocean');
  assert.equal(run.phases.at(-1), 'ocean', 'the ocean phase is the last progress');
  assert.ok(!caches.snapshot().includes('sc-coastal'), 'no coastal cache is created');
});

test('a layer retrieved too long before the save is recorded not-current with its deadline; nothing of it is written', async () => {
  const run = await packRun({feedOpts: {retrievedAt: '2026-10-16T00:00:00Z'}}), layer = run.meta.ocean.layers[WCOFS];
  assert.deepEqual([layer.state, layer.why, layer.bytes, layer.drawable_until], ['not-current', 'retrieval', 0, '2026-10-16T06:00:00.000Z']);
  assert.ok(!run.asked.some(u => u.includes('habitat-tiles')), 'no tile fetched');
  const [[name]] = run.caches.packs();
  assert.deepEqual(oceanKeys(run.caches, name), [`${FEEDS}test-coast/habitat-dynamics.json`], 'the manifest alone is stored');
  assert.equal(run.meta.ocean.bytes, run.meta.ocean.manifest.bytes);
});

test('Morro Bay and Cambria pack as coastal-report: no ocean fetch, no ocean key even when browsed, the Coastal readings caches untouched', async () => {
  for (const id of ['morro-bay', 'cambria-san-simeon']) {
    const base = `${FEEDS}${id}/`, browsed = async caches => {
      const recent = await caches.open('sc-data');
      for (const k of [`${base}habitat-dynamics.json`, `${base}habitat-tiles/wcofs-surface-forecast-0-0-0123456789abcdef.json`, 'https://s.test/api/other.json'])
        await recent.put(k, new Response('{"browsed":1}', {headers: {'X-SC-Saved-At': '2099-01-01T00:00:00Z'}}));
    };
    const run = await packRun({id, seed: browsed}), [[name]] = run.caches.packs();
    assert.equal(run.error, undefined, `${id}: ${run.error}`);
    assert.deepEqual(run.meta.ocean, {schema_version: 1, path: 'coastal-report', manifest: null, layers: {}, bytes: 0, coastal: null}, id);
    assert.deepEqual(oceanKeys(run.caches, name), [], `${id}: the pack holds no ocean key`);
    assert.ok(run.meta.files.from_session >= 1 && run.bodies(name).some(([k]) => k === 'https://s.test/api/other.json'), `${id}: unrelated browsed data is still copied`);
    assert.ok(!run.asked.some(u => isOceanKey(u, 'https://s.test')), `${id}: nothing ocean was requested`);
    assert.ok(![...run.caches.map.keys()].some(n => n.startsWith('sc-coastal')), `${id}: no coastal cache created`);
    assert.deepEqual(Object.keys(run.meta.v2).sort(), ['basemap', 'build', 'missing', 'shell']);
  }
});

test('oceanPhase for a report-bound place reads only the saved-snapshot pointer; a pointer that cannot be read is null; nothing is fetched or written', async () => {
  const morro = JSON.parse(read('regions/morro-bay/region.json')), place = {id: 'morro-bay', center: morro.map.center, localAreas: morro.map.local_areas};
  const never = () => { throw new Error('touched'); }, extras = {put: never, signal: new AbortController().signal, progress: never};
  const saved = {schema_version: 1, path: 'coastal-report', manifest: null, layers: {}, bytes: 0};
  assert.deepEqual(await runtime.oceanPhase(extras, place, {fetchFn: never, readCoastal: async () => ({saved_at: '2026-10-15T10:00:00.000Z'})}), {...saved, coastal: {saved_at: '2026-10-15T10:00:00.000Z'}});
  assert.deepEqual(await runtime.oceanPhase(extras, place, {fetchFn: never, readCoastal: async () => null}), {...saved, coastal: null});
  assert.deepEqual(await runtime.oceanPhase(extras, place, {fetchFn: never, readCoastal: async () => { throw new Error('locked'); }}), {...saved, coastal: null});
  // A centre outside every reviewed local area binds no report: the regional path (here, a manifest that is not there).
  const off = {...place, center: [36.5, -122.2]};
  const result = await runtime.oceanPhase({...extras, put: async () => {}, progress() {}}, off, {origin: 'https://s.test', fetchFn: async () => new Response('no', {status: 404}), readCoastal: never});
  assert.equal(result.path, 'none');
});

test('a manifest that is not there (404) is path none and the pack commits; another failed read is regional with both layers failed', async () => {
  const run = await packRun({manifestStatus: 404}), [[name]] = run.caches.packs();
  assert.equal(run.error, undefined, String(run.error));
  assert.deepEqual(run.meta.ocean, {schema_version: 1, path: 'none', manifest: {stored: false, reason: 'http'}, layers: {}, bytes: 0, cap_bytes: 12_000_000});
  assert.ok(run.caches.map.get(name).map.has(PACK_META), 'the pack is committed');
  assert.deepEqual(oceanKeys(run.caches, name), []);
  const broken = await packRun({manifestStatus: 500});
  assert.equal(broken.meta.ocean.path, 'regional');
  assert.deepEqual(broken.meta.ocean.manifest, {stored: false, reason: 'http'});
  assert.deepEqual(Object.values(broken.meta.ocean.layers).map(l => [l.state, l.reason]), [['failed', 'manifest'], ['failed', 'manifest']]);
});

test('cancelling during the ocean phase deletes the whole candidate and leaves the prior pack as it was', async () => {
  for (const [when, abortOn] of [['at the manifest', url => url.endsWith('habitat-dynamics.json')], ['at the first tile', url => url.includes('habitat-tiles/')]]) {
    const run = await packRun({abortOn});
    assert.equal(run.error?.name, 'AbortError', when);
    assert.equal(run.meta, undefined, when);
    assert.equal(run.caches.snapshot(), run.before, `${when}: nothing of the cancelled save remains; the prior pack and sc-data are byte for byte`);
    assert.deepEqual(run.caches.packs().map(([n]) => n), ['sc-pack-test-coast-1'], when);
  }
  // Cancelled before the ocean phase asked for anything: the same.
  const early = await packRun({abortOn: url => url.endsWith('/precache.json')});
  assert.equal(early.error?.name, 'AbortError');
  assert.equal(early.caches.snapshot(), early.before);
});

test('a rejected ocean write is fatal: the storage message, no meta, the prior pack byte for byte, no candidate', async () => {
  const quota = new DOMException('full', 'QuotaExceededError');
  for (const [what, hit] of [['a tile', key => key.includes('habitat-tiles/')], ['the manifest', key => key.endsWith('habitat-dynamics.json')]]) {
    const run = await packRun({fail: (name, key) => hit(key) ? quota : null});
    assert.equal(run.error?.message, STORAGE_MESSAGE, what);
    assert.equal(run.error.cause, quota, what);
    assert.equal(run.meta, undefined, what);
    assert.equal(run.caches.snapshot(), run.before, `${what}: nothing of the failed save remains; the prior pack, sc-data and the rest are byte for byte`);
    assert.deepEqual(run.caches.packs().map(([n]) => n), ['sc-pack-test-coast-1'], what);
    assert.ok(![...run.caches.map.values()].some(c => c.map.has(PACK_META) && c.name !== 'sc-pack-test-coast-1'), `${what}: no new meta anywhere`);
  }
  const first = await packRun({prior: false, fail: (name, key) => key.includes('habitat-tiles/') ? quota : null});
  assert.equal(first.error?.message, STORAGE_MESSAGE);
  assert.deepEqual(first.caches.packs(), [], 'a first save that fails leaves no pack cache at all');
  // A nonfatal ocean failure (a tile failing its hash) with every write succeeding commits: the two kinds are kept apart.
  const soft = await packRun({feedOpts: {record: r => ({...r, sha256: '0'.repeat(64)})}});
  assert.equal(soft.error, undefined);
  const layer = soft.meta.ocean.layers[WCOFS];
  assert.deepEqual([layer.state, layer.reason, layer.bytes], ['failed', 'integrity', 0]);
  assert.equal(soft.meta.ocean.bytes, soft.meta.ocean.manifest.bytes, 'the failed layer adds nothing');
  // A write that rejects after the signal aborted is the cancellation path, not the storage message.
  const late = await packRun({fail: (name, key, controller) => { if (key.includes('habitat-tiles/')) { controller.abort(); return quota; } return null; }});
  assert.equal(late.error?.name, 'AbortError');
  assert.equal(late.caches.snapshot(), late.before);
});

// SC1938-05: the Trip dialog's ocean coverage lines, from the pack's own ocean record, at an injected now (web/trip-ocean-lines.ts).
const {oceanLines} = await import('../web/trip-ocean-lines.ts');
const SST = 'sst-analysis', UNTIL = '2026-10-16T12:00:00.000Z', layerRec = (state, extra = {}) => ({state, tiles: {saved: 0, listed: 1}, bytes: 0, ...extra});
const regional = (sst, wcofs) => ({ocean: {schema_version: 1, path: 'regional', layers: {...sst ? {[SST]: sst} : {}, ...wcofs ? {[WCOFS]: wcofs} : {}}}});
const NOW = new Date('2026-10-16T11:00:00Z');

test('a saved layer says when it stops showing, in the region\'s zone, one hour before drawable_until', () => {
  const lines = oceanLines(regional(layerRec('saved', {drawable_until: UNTIL}), layerRec('saved', {drawable_until: UNTIL})), NOW, 'America/Los_Angeles');
  assert.equal(lines.water, 'saved · not shown after Fri 5 am · only for hours on or after the analysis');
  assert.equal(lines.currents, 'saved · not shown after Fri 5 am · only for forecast hours');
  assert.equal(oceanLines(regional(layerRec('saved', {drawable_until: UNTIL}), null), NOW, 'UTC').water.includes('Fri 12 pm'), true, 'the time follows the zone given');
});

test('a saved layer past its deadline says past its age limit and promises no time; the deadline instant itself is past', () => {
  const meta = regional(layerRec('saved', {drawable_until: UNTIL}), layerRec('saved', {drawable_until: UNTIL}));
  for (const now of [new Date(UNTIL), new Date('2026-10-17T00:00:00Z')]) assert.deepEqual(oceanLines(meta, now), {water: 'saved · past its age limit', currents: 'saved · past its age limit'});
  assert.equal(oceanLines(regional(layerRec('saved'), null), NOW).water, 'saved', 'a saved layer without a valid deadline claims nothing more');
  assert.equal(oceanLines(regional(layerRec('saved', {drawable_until: 'soon'}), null), NOW).water, 'saved');
});

test('each state and why of a layer has its own line', () => {
  const cases = [[layerRec('failed', {reason: 'integrity'}), 'not saved: failed check'], [layerRec('failed', {reason: 'manifest'}), 'not saved: failed check'],
    [layerRec('over-cap'), 'not saved: too large for this pack'], [layerRec('not-current', {why: 'retrieval'}), 'not saved: forecast too old to show offline'],
    [layerRec('not-current', {why: 'short-window'}), 'not saved: forecast too old to show offline'], [layerRec('not-current', {why: 'age'}), 'not saved: no current data at save time'],
    [layerRec('not-current', {why: 'status'}), 'not saved: no current data at save time'], [layerRec('not-current'), 'not saved: no current data at save time'],
    [layerRec('absent'), 'not saved: not published for this area'], [layerRec('cancelled'), 'not saved'], [layerRec('mystery'), 'not saved'], [null, 'not saved']];
  for (const [rec, line] of cases) {
    const lines = oceanLines(regional(rec, rec), NOW);
    assert.deepEqual([lines.water, lines.currents], [line, line], JSON.stringify(rec));
  }
  const mixed = oceanLines(regional(layerRec('saved', {drawable_until: UNTIL}), layerRec('over-cap')), NOW);
  assert.deepEqual([mixed.water.startsWith('saved · not shown after'), mixed.currents], [true, 'not saved: too large for this pack'], 'the two lines are independent');
});

test('a pack without an ocean record shows no lines; the older record shapes do not throw', () => {
  assert.equal(oceanLines({}, NOW), null);
  assert.equal(oceanLines({ocean: undefined}, NOW), null);
  assert.deepEqual(oceanLines({ocean: {path: 'regional', layers: {}}}, NOW), {water: 'not saved', currents: 'not saved'});
});

test('a coastal-report pack points at Coastal readings with or without a committed snapshot; a place with no feed says not published', () => {
  const saved = oceanLines({ocean: {schema_version: 1, path: 'coastal-report', layers: {}, coastal: {saved_at: '2026-10-15T17:30:00.000Z'}}}, NOW, 'America/Los_Angeles');
  assert.deepEqual(saved, {water: 'from Coastal readings (saved Thu 10 am)', currents: 'from Coastal readings (saved Thu 10 am)'});
  for (const coastal of [null, undefined, {}, {saved_at: 'x'}]) assert.deepEqual(oceanLines({ocean: {path: 'coastal-report', layers: {}, coastal}}, NOW), {water: 'from Coastal readings (not saved)', currents: 'from Coastal readings (not saved)'}, String(coastal));
  assert.deepEqual(oceanLines({ocean: {path: 'none', layers: {}}}, NOW), {water: 'not published for this area', currents: 'not published for this area'});
});

test('the lines are read from a real saved pack record: a current WCOFS layer is saved with its time, the absent SST layer is not', async () => {
  const run = await packRun({}), lines = oceanLines(run.meta, new Date(SAVE_AT));
  assert.equal(lines.currents, 'saved · not shown after Fri 5 am · only for forecast hours');
  assert.equal(lines.water, 'not saved: not published for this area');
  assert.equal(oceanLines(run.meta, new Date(UNTIL)).currents, 'saved · past its age limit');
});
