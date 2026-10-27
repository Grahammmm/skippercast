import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, readdirSync, statSync} from 'node:fs';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import catalog from '../catalog/sources.json' with {type: 'json'};
globalThis.REGIONS = {};
globalThis.DEPLOYMENT = {allowed_origins:['https://skippercast.com']};
const {coastTarget, coastFeeds, serveCoastData} = await import('../server/coast-data.ts');

const request = (path, init) => new Request('https://skippercast.com' + path, init);
// FE-62: the bridge is retired. Any request to another origin fails the test that made it.
let outbound = 0;
globalThis.fetch = async () => { outbound++; throw Error('Must not fetch another origin'); };

// FE-62 acceptance 3: no Fish Worker origin anywhere in the Worker's source.
test('server/ names no Fish Worker origin and coast-data.ts makes no outbound request', () => {
  const root = fileURLToPath(new URL('../server/', import.meta.url));
  const files = [];
  const walk = dir => { for (const name of readdirSync(dir)) { const path = join(dir, name); statSync(path).isDirectory() ? walk(path) : files.push(path); } };
  walk(root);
  assert.ok(files.some(f => f.endsWith('coast-data.ts')));
  for (const file of files) assert.doesNotMatch(readFileSync(file, 'utf8'), /fish-report\.|slofishreport/i, file);
  assert.doesNotMatch(readFileSync(join(root, 'coast-data.ts'), 'utf8'), /\bfetch\s*\(|\bORIGIN\b|https?:\/\//, 'coast-data.ts reads only R2');
});

test('only explicit public datasets are admitted; private, encoded and foreign paths never are', () => {
  for (const [path, snapshot, asset] of [['/api/coast/report', 'report', null], ['/api/coast/ocean', 'ocean', null], ['/api/coast/history?county=slo', 'history', null],
    ['/api/coast/habitat/release', null, '/api/habitat/release'], ['/api/coast/habitat/tiles?region=morro-bay', null, '/api/habitat/tiles?region=morro-bay'],
    ['/coast-data/data/coast-wide/c--122880--155648-32.bin', null, '/data/coast-wide/c--122880--155648-32.bin'],
    ['/coast-data/data/coast3d/chart-model.json', null, '/data/coast3d/chart-model.json'], ['/coast-data/data/skippercast-habitat.geojson', null, '/data/skippercast-habitat.geojson']]) {
    const target = coastTarget(new URL(request(path).url));
    assert.deepEqual([target.snapshot, target.asset, target.release], [snapshot, asset, null], path);
  }
  assert.equal(coastTarget(new URL(request(`/api/coast/habitat/tiles?region=morro-bay&release=${'a'.repeat(64)}`).url)).release, 'a'.repeat(64));
  for (const path of ['/api/coast/report?county=monterey', '/api/coast/report?region=monterey-point-sur', '/api/coast/report?region=constructor', '/api/coast/report?region=morro-bay&region=monterey-point-sur', '/api/coast/trips', '/api/coast/admin', '/api/coast/habitat/tiles?region=constructor', '/coast-data/data/government-habitat/private.bin', '/coast-data/data/habitat-government/private.bin', '/coast-data/artifacts/private.json', '/coast-data/data/%67overnment-habitat/private.bin', '/coast-data/data/coast-wide/%2e%2e/private.json', '/coast-data/data/coast-wide/escape%252fprivate.bin', '/coast-data/data/coast-wide/a.bin?url=https://other.test/', '/coast-data/data/coast-wide/a.bin?release=bad',
    // The Fish shore files belonged to no R2 group and left with the bridge.
    '/coast-data/data/slo-shoreline.geojson', '/coast-data/data/slo-shore-habitat.geojson']) assert.equal(coastTarget(new URL(request(path).url)), null, path);
});

for (const [label, store] of [['no R2', null], ['empty R2', fakeStore({})]]) {
  test(`${label}: nothing published is unavailable, never fetched from another origin`, async () => {
    const before = outbound;
    for (const name of ['report', 'ocean', 'history']) {
      const r = await serveCoastData(request('/api/coast/' + name, {headers: {Cookie: 'session=private', Authorization: 'Bearer secret'}}), store);
      assert.equal(r.status, 503, name); assert.equal(r.headers.get('Cache-Control'), 'no-store');
      assert.match(r.headers.get('X-Coast-Upstream'), new RegExp(`^${name}=unavailable \\((?:unbound|missing)\\)`), name);
    }
    for (const path of ['/api/coast/habitat/release', '/api/coast/habitat/tiles?region=morro-bay', '/coast-data/data/coast-wide/a.bin', '/coast-data/data/coast3d/chart-model.json'])
      for (const method of ['GET', 'HEAD']) assert.equal((await serveCoastData(request(path, {method}), store)).status, 503, `${method} ${path}`);
    assert.equal((await serveCoastData(request('/api/coast/report', {method: 'POST'}), store)).status, 405);
    assert.equal((await serveCoastData(request('/api/coast/trips'), store)).status, 404);
    for (const range of ['bytes=0-', 'bytes=-8', 'bytes=4-2', 'bytes=0-99999999999999999999', 'bytes=0-2097152'])
      assert.equal((await serveCoastData(request('/api/coast/habitat/tiles?region=morro-bay', {headers: {Range: range}}), store)).status, 416, range);
    assert.equal((await serveCoastData(request('/api/coast/report', {headers: {Range: 'bytes=0-3'}}), store)).status, 416, 'snapshots take no range');
    assert.equal(outbound, before);
  });
}

// FE-85: assets copied to R2 by scripts/coast/publish_assets.py (synthetic fixture bytes).
const sha = async bytes => Buffer.from(await crypto.subtle.digest('SHA-256', bytes)).toString('hex');
const tile = new Uint8Array(64).map((_, i) => i), habitatRelease = 'b'.repeat(64);
function fakeStore(objects) {
  const reads = [];
  const meta = async key => ({size: objects[key].byteLength, etag: (await sha(objects[key])).slice(0, 32)});
  return {reads, objects,
    async head(key) { reads.push(key); return key in objects ? meta(key) : null; },
    async get(key, options = {}) {
      reads.push(key); if (!(key in objects)) return null;
      const m = await meta(key);
      if (options.onlyIf?.etagMatches && options.onlyIf.etagMatches !== m.etag) return m;
      const r = options.range, bytes = r ? objects[key].slice(r.offset, r.offset + r.length) : objects[key].slice();
      return {...m, body: new Response(bytes).body, arrayBuffer: async () => bytes.buffer};
    }};
}
async function published(files, {groups = ['terrain', 'habitat'], pointer} = {}) {
  const objects = {}, entries = {};
  for (const [path, {bytes, ...extra}] of Object.entries(files)) {
    const digest = await sha(bytes); objects['coast/objects/' + digest] = bytes;
    entries[path] = {sha256: digest, bytes: bytes.byteLength, contentType: 'application/octet-stream', ...extra};
  }
  const manifest = new TextEncoder().encode(JSON.stringify({schemaVersion: 1, kind: 'skippercast-coast-assets', groups, objects: entries}));
  const id = await sha(manifest); objects[`coast/releases/${id}.json`] = manifest;
  objects['coast/current.json'] = new TextEncoder().encode(JSON.stringify(pointer ?? {schemaVersion: 1, status: 'ready', releaseId: id}));
  return {store: fakeStore(objects), entries};
}
const fixture = () => published({'/data/coast-wide/a.bin': {bytes: tile},
  '/api/habitat/tiles?region=morro-bay': {bytes: tile.map(v => 255 - v), habitatRelease, expiresAt: '2099-01-01T00:00:00Z'}});

test('R2 assets are served only after their manifest SHA-256 matches, with exact ranges and receipts', async () => {
  const {store, entries} = await fixture();
  const whole = await serveCoastData(request('/coast-data/data/coast-wide/a.bin'), store);
  assert.equal(whole.status, 200); assert.deepEqual(new Uint8Array(await whole.arrayBuffer()), tile);
  assert.equal(whole.headers.get('ETag'), `"sha256-${entries['/data/coast-wide/a.bin'].sha256}"`);
  for (let i = 0; i < 2; i++) {  // the second read uses the verified version's etag
    const part = await serveCoastData(request(`/api/coast/habitat/tiles?region=morro-bay&release=${habitatRelease}`, {headers: {Range: 'bytes=2-4'}}), store);
    assert.equal(part.status, 206); assert.deepEqual([...new Uint8Array(await part.arrayBuffer())], [253, 252, 251]);
    assert.equal(part.headers.get('Content-Range'), 'bytes 2-4/64'); assert.equal(part.headers.get('X-Fish-Habitat-Release'), habitatRelease);
  }
  const head = await serveCoastData(request('/api/coast/habitat/tiles?region=morro-bay', {method: 'HEAD'}), store);
  assert.equal(head.status, 200); assert.equal(head.headers.get('Content-Length'), '64'); assert.equal(await head.text(), '');
});

test('an altered byte or an object missing from the manifest is refused before any byte is served', async () => {
  const {store, entries} = await fixture();
  const key = 'coast/objects/' + entries['/data/coast-wide/a.bin'].sha256;
  assert.equal((await serveCoastData(request('/coast-data/data/coast-wide/a.bin'), store)).status, 200);
  store.objects[key] = tile.slice(); store.objects[key][10] ^= 1;  // tampered after an earlier verified read
  for (const init of [undefined, {headers: {Range: 'bytes=0-3'}}, {method: 'HEAD'}]) {
    const r = await serveCoastData(request('/coast-data/data/coast-wide/a.bin', init), store);
    assert.equal(r.status, 503); assert.equal(r.headers.get('ETag'), null);
  }
  const fresh = await published({'/data/coast-wide/a.bin': {bytes: tile.map(v => v ^ 3)}});
  const altered = 'coast/objects/' + Object.values(fresh.entries)[0].sha256;
  fresh.store.objects[altered] = fresh.store.objects[altered].slice(); fresh.store.objects[altered][0] ^= 1;  // altered before any read
  assert.equal((await serveCoastData(request('/coast-data/data/coast-wide/a.bin'), fresh.store)).status, 503);
  assert.equal((await serveCoastData(request('/coast-data/data/coast-wide/b.bin'), store)).status, 404);
  assert.equal((await serveCoastData(request('/coast-data/data/coast3d/chart-model.json'), store)).status, 404);
});

test('wrong ranges, unknown releases and expired entries are refused; encoded private paths never read R2', async () => {
  const {store} = await fixture();
  assert.equal((await serveCoastData(request('/coast-data/data/coast-wide/a.bin', {headers: {Range: 'bytes=60-70'}}), store)).status, 416);
  assert.equal((await serveCoastData(request('/coast-data/data/coast-wide/a.bin', {headers: {Range: 'bytes=4-'}}), store)).status, 416);
  for (const path of [`/api/coast/habitat/tiles?region=morro-bay&release=${'c'.repeat(64)}`, `/coast-data/data/coast-wide/a.bin?release=${habitatRelease}`])
    assert.equal((await serveCoastData(request(path), store)).status, 404, path);
  store.reads.length = 0;
  for (const path of ['/coast-data/data/%67overnment-habitat/private.bin', '/coast-data/data/coast-wide/%2e%2e/private.json', '/coast-data/data/coast-wide/escape%252fprivate.bin', '/coast-data/data/habitat-government/current.json', '/coast-data/coast/current.json'])
    assert.equal((await serveCoastData(request(path), store)).status, 404, path);
  assert.deepEqual(store.reads, []);
  const expired = await published({'/api/habitat/tiles?region=morro-bay': {bytes: tile, habitatRelease, expiresAt: '2020-01-01T00:00:00Z'}});
  assert.equal((await serveCoastData(request('/api/coast/habitat/tiles?region=morro-bay', {method: 'HEAD'}), expired.store)).status, 503);
});

test('unpublished groups are unavailable; held or mismatched releases fail closed', async () => {
  assert.equal((await serveCoastData(request('/coast-data/data/coast-wide/a.bin'), fakeStore({}))).status, 503, 'no pointer: nothing published');
  const {store} = await published({'/data/coast-wide/a.bin': {bytes: tile}}, {groups: ['terrain']});
  assert.equal((await serveCoastData(request('/coast-data/data/coast-wide/a.bin'), store)).status, 200);
  assert.equal((await serveCoastData(request('/api/coast/habitat/tiles?region=morro-bay'), store)).status, 503, 'habitat is not in this release');
  for (const pointer of [{schemaVersion: 1, status: 'held', releaseId: 'd'.repeat(64)}, {schemaVersion: 1, status: 'ready', releaseId: 'd'.repeat(64)}]) {
    const held = await published({'/data/coast-wide/a.bin': {bytes: tile}}, {pointer});
    assert.equal((await serveCoastData(request('/coast-data/data/coast-wide/a.bin'), held.store)).status, 503);
  }
});

test('the reef context travels with habitat, not terrain', async () => {
  const reef = new Uint8Array([7, 8]);
  const terrain = await published({'/data/coast-wide/a.bin': {bytes: tile}, '/data/coast-wide/reef-context.json': {bytes: reef}}, {groups: ['terrain']});
  assert.equal((await serveCoastData(request('/coast-data/data/coast-wide/reef-context.json'), terrain.store)).status, 503);
  const habitat = await published({'/data/coast-wide/reef-context.json': {bytes: reef}}, {groups: ['habitat']});
  const r = await serveCoastData(request('/coast-data/data/coast-wide/reef-context.json'), habitat.store);
  assert.equal(r.status, 200); assert.deepEqual([...new Uint8Array(await r.arrayBuffer())], [7, 8]);
});

test('concurrent first reads of one object hash it once', async () => {
  const cold = tile.map(v => v * 3);  // bytes no earlier test verified
  const {store, entries} = await published({'/api/habitat/tiles?region=morro-bay': {bytes: cold, habitatRelease, expiresAt: '2099-01-01T00:00:00Z'}});
  const key = 'coast/objects/' + entries['/api/habitat/tiles?region=morro-bay'].sha256;
  // Only an unpinned whole read hashes; a request that arrives after the hash has finished reads its pinned etag instead.
  const get = store.get.bind(store), whole = [];
  store.get = (k, options = {}) => { if (k === key && !options.onlyIf && !options.range) whole.push(k); return get(k, options); };
  const parts = await Promise.all([0, 8, 16, 24].map(start => serveCoastData(request('/api/coast/habitat/tiles?region=morro-bay',
    {headers: {Range: `bytes=${start}-${start + 7}`}}), store)));
  assert.deepEqual(parts.map(r => r.status), [206, 206, 206, 206]);
  assert.deepEqual(new Uint8Array(await parts[1].arrayBuffer()), cold.slice(8, 16));
  assert.equal(whole.length, 1, 'one unpinned whole-object read hashes it');
});

// Hold cold object bodies independently; pointer reads stay promise-only so one
// event-loop checkpoint can drain same-key joiners after the manifest is warm.
async function gatedAssets(t, files) {
  const {store, entries} = await published(files);
  const get = store.get.bind(store), pointer = await get('coast/current.json');
  const pointerBytes = await pointer.arrayBuffer();
  const gates = new Map(), jobs = [], counts = new Map();
  let closed = false, active = 0, peak = 0;
  const before = outbound;
  const send = (path, init) => {
    const job = serveCoastData(request(path, init), store);
    jobs.push(job); return job;
  };
  // Cache only the release, not an asset's verified etag.
  assert.equal((await send('/coast-data/data/coast-wide/gate-absent.bin')).status, 404);
  store.get = async (key, options) => {
    if (key === 'coast/current.json') return {...pointer,
      body: new Response(pointerBytes).body, arrayBuffer: async () => pointerBytes};
    const gate = gates.get(key);
    if (!gate) return get(key, options);
    counts.set(key, (counts.get(key) ?? 0) + 1);
    const object = await get(key, options);
    return {...object, arrayBuffer: async () => {
      active++; peak = Math.max(peak, active); gate.entered.resolve();
      try { await gate.body.promise; return await object.arrayBuffer(); }
      finally { active--; }
    }};
  };
  t.after(async () => {
    closed = true;
    for (const gate of gates.values()) gate.body.resolve();
    for (const result of await Promise.allSettled(jobs)) {
      if (result.status === 'fulfilled' && !result.value.bodyUsed) await result.value.body?.cancel();
    }
    store.get = get;
  });
  const arm = path => {
    const key = 'coast/objects/' + entries[path].sha256;
    const gate = {key, entered: Promise.withResolvers(), body: Promise.withResolvers()};
    if (closed) gate.body.resolve();
    gates.set(key, gate); return gate;
  };
  return {send, arm, counts, entries, stats: () => ({active, peak, bridgeCalls: outbound - before})};
}

test('distinct cold R2 keys overlap while same-key ranges share a read', {timeout: 5000}, async t => {
  // Two is a control population, not an accepted global concurrency limit.
  const a = '/data/coast-wide/gate-overlap-a.bin', b = '/data/coast-wide/gate-overlap-b.bin';
  const bytesA = new TextEncoder().encode('synthetic overlap asset A'), bytesB = new TextEncoder().encode('synthetic overlap asset B');
  const f = await gatedAssets(t, {[a]: {bytes: bytesA}, [b]: {bytes: bytesB}});
  const ga = f.arm(a), gb = f.arm(b);
  const first = f.send('/coast-data' + a, {headers: {Range: 'bytes=0-7'}});
  const shared = f.send('/coast-data' + a, {headers: {Range: 'bytes=8-15'}});
  const other = f.send('/coast-data' + b);
  await Promise.all([ga.entered.promise, gb.entered.promise]);
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(f.stats(), {active: 2, peak: 2, bridgeCalls: 0});
  assert.equal(f.counts.get(ga.key), 1); assert.equal(f.counts.get(gb.key), 1);
  // B finishes while A is still held: distinct keys have independent progress.
  gb.body.resolve();
  const otherResponse = await other;
  assert.equal(otherResponse.status, 200);
  assert.equal(otherResponse.headers.get('ETag'), `"sha256-${f.entries[b].sha256}"`);
  assert.deepEqual(new Uint8Array(await otherResponse.arrayBuffer()), bytesB);
  assert.equal(f.stats().active, 1);
  ga.body.resolve();
  const parts = await Promise.all([first, shared]);
  for (const [i, part] of parts.entries()) {
    assert.equal(part.status, 206);
    assert.equal(part.headers.get('Content-Range'), `bytes ${i * 8}-${i * 8 + 7}/${bytesA.length}`);
    assert.deepEqual(new Uint8Array(await part.arrayBuffer()), bytesA.slice(i * 8, i * 8 + 8));
  }
  assert.equal(f.counts.get(ga.key), 1);
  assert.deepEqual(f.stats(), {active: 0, peak: 2, bridgeCalls: 0});
});

test('a shared R2 read rejection fails closed, leaves another key running and permits retry', {timeout: 5000}, async t => {
  const a = '/data/coast-wide/gate-retry-a.bin', b = '/data/coast-wide/gate-retry-b.bin';
  const bytesA = new TextEncoder().encode('synthetic retry asset A'), bytesB = new TextEncoder().encode('synthetic retry asset B');
  const f = await gatedAssets(t, {[a]: {bytes: bytesA}, [b]: {bytes: bytesB}});
  const ga = f.arm(a), gb = f.arm(b);
  const first = f.send('/coast-data' + a), shared = f.send('/coast-data' + a, {method: 'HEAD'});
  const other = f.send('/coast-data' + b);
  await Promise.all([ga.entered.promise, gb.entered.promise]);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.counts.get(ga.key), 1);
  assert.deepEqual(f.stats(), {active: 2, peak: 2, bridgeCalls: 0});
  ga.body.reject(Error('synthetic R2 body failure'));
  for (const failed of await Promise.all([first, shared])) {
    assert.equal(failed.status, 503);
    assert.equal(failed.headers.get('ETag'), null);
    assert.deepEqual(await failed.json(), {error: 'Coast source unavailable'});
  }
  assert.equal(f.counts.get(ga.key), 1, 'both failed callers shared the rejected read');
  assert.deepEqual(f.stats(), {active: 1, peak: 2, bridgeCalls: 0});
  const retryGate = f.arm(a), retry = f.send('/coast-data' + a);
  await retryGate.entered.promise;
  assert.equal(f.counts.get(ga.key), 2, 'rejection removed the pending entry');
  retryGate.body.resolve();
  const recovered = await retry;
  assert.equal(recovered.status, 200);
  assert.equal(recovered.headers.get('ETag'), `"sha256-${f.entries[a].sha256}"`);
  assert.deepEqual(new Uint8Array(await recovered.arrayBuffer()), bytesA);
  assert.equal(f.stats().active, 1, 'retry did not wait for or cancel the other key');
  gb.body.resolve();
  const unaffected = await other;
  assert.equal(unaffected.status, 200);
  assert.deepEqual(new Uint8Array(await unaffected.arrayBuffer()), bytesB);
  assert.equal(f.counts.get(gb.key), 1);
  assert.deepEqual(f.stats(), {active: 0, peak: 2, bridgeCalls: 0});
});

test("the renderer's verified-asset and habitat HEAD checks pass against R2 and fail on tampering", async () => {
  const {verifiedAsset} = await import('../packages/coast/src/coast3d/regional.ts');
  const {validateHabitatHeads} = await import('../packages/coast/src/map/habitat-lifecycle.ts');
  const {coastPath} = await import('../packages/coast/src/transport.ts');
  const {store, entries} = await fixture();
  const serve = (path, init) => serveCoastData(request(coastPath(path), init), store);
  const original = globalThis.fetch; globalThis.fetch = (path, init) => serveCoastData(request(path, init), store);
  try {
    const asset = {url: '/data/coast-wide/a.bin', ...entries['/data/coast-wide/a.bin']};
    assert.deepEqual(new Uint8Array(await verifiedAsset(asset)), tile);
    const archive = entries['/api/habitat/tiles?region=morro-bay'];
    const region = {regionId: 'morro-bay', ready: true, commercialArchivePermitted: true, license: 'public-domain-us-gov', expiresAt: '2099-01-01T00:00:00Z',
      archiveSha256: archive.sha256, archiveETag: `"sha256-${archive.sha256}"`, archiveBytes: archive.bytes};
    const manifest = {ready: true, expiresAt: '2099-01-01T00:00:00Z', releaseId: habitatRelease, consumerContract: 'fish-habitat-v1', regions: [region]};
    await validateHabitatHeads(manifest, serve);
    store.objects['coast/objects/' + asset.sha256] = tile.map(v => v ^ 1);
    await assert.rejects(verifiedAsset(asset), /Asset unavailable/);
    await assert.rejects(validateHabitatHeads({...manifest, regions: [{...region, regionId: 'cambria-san-simeon'}]}, serve), /publication changed/);
  } finally { globalThis.fetch = original; }
});

// FE-84: snapshot sources from SkipperCast's own feeds (synthetic packets in the FE-40, FE-41, FE-42 and coast_snapshots.py shapes).
const ago = hours => new Date(Date.now() - hours * 3_600_000).toISOString();
const site = (id, areaId, extra = {}) => ({id, name: `Site ${id}`, areaId, lat: 35.37, lon: -120.88, sourceId: `cdip-${id}`, issuedAt: ago(5), fetchedAt: ago(0.5),
  hours: [{at: ago(-1), waveFt: 4.2, periodS: 13, directionDeg: 290, qualityFlag: 1, secondaryFlag: 0}], url: `https://cdip.ucsd.edu/mops/?mop=${id}`, kind: 'forecast',
  availability: 'available', freshness: 'current', temporalResolutionMinutes: 180, waterDepthM: 10, depthDatum: 'NAVD88', directionConvention: 'from degrees true',
  modelInputCycleAt: null, validThrough: ago(-60), ...extra});
const nearshoreFeed = (generated = ago(0.5), sites = [site('SL345', 'central')]) => ({schema_version: 1, region_id: 'morro-bay', generated_at: generated,
  nearshore: sites, sources: sites.map(s => ({id: s.sourceId, label: `CDIP nearshore · ${s.name}`, url: s.url, kind: 'forecast', outcome: 'ok', fetchedAt: s.fetchedAt, issuedAt: s.issuedAt}))});
const beachFeed = (generated = ago(0.2), outcome = 'ok') => ({schemaVersion: 1, countyId: 'slo', regionId: 'morro-bay', generatedAt: generated,
  waterQuality: outcome === 'ok' ? [{id: 'b1', name: 'Synthetic Beach', lat: 35.37, lon: -120.86, status: 'Beach Open', advisory: null, sampledAt: null, fetchedAt: generated,
    sourceId: 'slo-beach-water-quality', url: 'https://www.slocounty.ca.gov/', areaId: 'central', stationCode: 'SB1', sampleDateAvailable: false}] : [],
  sources: [{id: 'slo-beach-water-quality', label: 'SLO County beach water-contact status', url: 'https://services6.arcgis.com/', kind: 'observation', outcome, fetchedAt: generated}]});
const oceanFeed = (generated = ago(0.3)) => ({schemaVersion: 1, countyId: 'slo', generatedAt: generated, currents: [], cloud: null,
  sources: [{id: 'skippercast-noaa-ocean', url: 'https://raw.githubusercontent.com/', fetchedAt: ago(0.4), status: 'error', error: 'No fresh reviewed current fields'}]});
const historyFeed = (generated = ago(30)) => ({schemaVersion: 1, countyId: 'slo', generatedAt: generated, recentWindowDays: 45, stations: [
  {stationId: '46215', recent: {lastObservedAt: ago(30.5), stale: false}, baseline: {months: []}, sources: []},
  {stationId: '46028', recent: {lastObservedAt: ago(1), stale: false}, baseline: {months: []}, sources: []}]});
const feedStore = files => fakeStore(Object.fromEntries(Object.entries(files).map(([key, value]) => [key, new TextEncoder().encode(JSON.stringify(value))])));
const NEARSHORE = 'conditions/regions/morro-bay/nearshore.json', BEACH = 'conditions/regions/morro-bay/beach-health.json';
const OCEAN = 'conditions/regions/morro-bay/coast-ocean.json', HISTORY = 'data/regions/morro-bay/history.json';
const REPORT = 'conditions/regions/morro-bay/coast-report.json';
// FE-87: coast_report.py's assembled fixture (tests/unit/test_coast_report.py), re-dated only for the Worker's age check.
const skippercastReport = JSON.parse(readFileSync(new URL('./fixtures/coast/skippercast-report.json', import.meta.url), 'utf8'));
const reportFeed = (generated = ago(0.4)) => ({...skippercastReport, generatedAt: generated});
const report = async (files, feeds) => serveCoastData(request('/api/coast/report'), feedStore(files), feeds);

test('every feed is used unless the rights register refuses a catalog row behind it', async () => {
  assert.deepEqual([...coastFeeds()], ['nearshore', 'water-quality', 'ocean', 'history', 'report'], 'no committed catalog row refuses a feed today');
  const held = (id, change) => catalog.sources.map(s => s.id === id ? {...s, ...change} : s);
  assert.ok(!coastFeeds(held('landing-reports', {rights: {commercial_use: 'prohibited'}})).has('report'));
  assert.ok(!coastFeeds(held('slo-beach-water-quality', {rights: {commercial_use: 'permission-required'}})).has('water-quality'));
  assert.ok(!coastFeeds(held('cdip-mop', {review_status: 'restricted'})).has('nearshore'));
  assert.ok(!coastFeeds(catalog.sources.filter(s => s.id !== 'ndbc-history')).has('history'), 'a source with no catalog row');
  assert.ok(coastFeeds(held('slo-beach-water-quality', {review_status: 'candidate'})).has('water-quality'), 'pending is not refused');
  const store = feedStore({[OCEAN]: oceanFeed()});
  const r = await serveCoastData(request('/api/coast/ocean'), store, coastFeeds(held('noaa-goes-nowcoast', {review_status: 'restricted'})));
  assert.equal(r.status, 503); assert.equal(r.headers.get('X-Coast-Upstream'), 'ocean=unavailable (refused)');
  assert.deepEqual(store.reads, [], 'a refused feed is never read');
  const beach = await (await report({[REPORT]: reportFeed(), [BEACH]: beachFeed()}, coastFeeds(held('slo-beach-water-quality', {review_status: 'unavailable'})))).json();
  assert.equal(beach.waterQuality, undefined, 'refused beach rows are left out of the report');
});

test('the report takes nearshore and beach rows from their own feeds with their own clocks', async () => {
  const own = reportFeed(), near = nearshoreFeed(), beach = beachFeed();
  const r = await serveCoastData(request('/api/coast/report?region=morro-bay'), feedStore({[REPORT]: own, [NEARSHORE]: near, [BEACH]: beach}));
  assert.equal(r.status, 200); assert.equal(r.headers.get('X-Coast-Upstream'), 'report=skippercast, nearshore=skippercast, water-quality=skippercast');
  const data = await r.json();
  assert.deepEqual(data.nearshore, near.nearshore); assert.deepEqual(data.waterQuality, beach.waterQuality);
  assert.deepEqual(data.sources, [...own.sources, ...near.sources, ...beach.sources]);
  const {freshNearshore} = await import('../packages/coast/src/presentation.ts');
  assert.deepEqual(freshNearshore(data, 'central', new Date()).map(s => s.fetchedAt), [near.nearshore[0].fetchedAt]);
  // A beach feed that failed keeps its error outcome and no rows: never read as open beaches.
  const failed = await (await report({[REPORT]: own, [BEACH]: beachFeed(ago(0.2), 'error')})).json();
  assert.deepEqual(failed.waterQuality, []); assert.equal(failed.sources.at(-1).outcome, 'error');
});

test('FE-62: a report whose nearshore or beach feed is not current is served without those rows, never from Fish', async () => {
  const own = reportFeed(), beach = beachFeed();
  const r = await report({[REPORT]: own, [BEACH]: beach});
  assert.equal(r.status, 200); assert.equal(r.headers.get('X-Coast-Upstream'), 'report=skippercast, nearshore=unavailable (missing), water-quality=skippercast');
  const data = await r.json();
  assert.deepEqual([data.nearshore, data.waterQuality, data.forecasts], [undefined, beach.waterQuality, own.forecasts]);
  assert.deepEqual(data.sources, [...own.sources, ...beach.sources]);
  const alone = await report({[REPORT]: own});
  assert.equal(alone.headers.get('X-Coast-Upstream'), 'report=skippercast, nearshore=unavailable (missing), water-quality=unavailable (missing)');
  const bare = await alone.json();
  assert.deepEqual([bare.nearshore, bare.waterQuality, bare.sources], [undefined, undefined, own.sources]);
  // A region-wide CDIP failure re-publishes the last nearshore.json, whose sites still say "current": the server checks generated_at itself.
  for (const [feed, reason] of [[nearshoreFeed(ago(3.1)), 'stale'], [nearshoreFeed(ago(-0.5)), 'stale'], [{...nearshoreFeed(), region_id: 'monterey-point-sur'}, 'invalid'],
    [{...nearshoreFeed(), generated_at: 'yesterday'}, 'invalid'], [nearshoreFeed(ago(0.5), [{...site('SL345', 'central'), availability: 'ok'}]), 'invalid']]) {
    const s = await report({[REPORT]: own, [NEARSHORE]: feed, [BEACH]: beach});
    assert.equal(s.headers.get('X-Coast-Upstream'), `report=skippercast, nearshore=unavailable (${reason}), water-quality=skippercast`);
    assert.equal((await s.json()).nearshore, undefined, reason);
  }
  const stale = await report({[REPORT]: own, [NEARSHORE]: nearshoreFeed(), [BEACH]: beachFeed(ago(3.5))});
  assert.equal(stale.headers.get('X-Coast-Upstream'), 'report=skippercast, nearshore=skippercast, water-quality=unavailable (stale)');
  const broken = fakeStore({[REPORT]: new TextEncoder().encode(JSON.stringify(own)), [NEARSHORE]: new TextEncoder().encode('{')});
  assert.equal((await serveCoastData(request('/api/coast/report'), broken)).headers.get('X-Coast-Upstream'), 'report=skippercast, nearshore=unavailable (unreadable), water-quality=unavailable (missing)');
});

test('FE-62 review: nearshore and beach rows already in the report base are dropped unless their own feed is used', async () => {
  const clean = reportFeed();
  const embedded = {...clean, nearshore: [site('EMBED', 'central')], waterQuality: [{id: 'embedded-beach', status: 'Beach Open', fetchedAt: ago(0.1)}],
    sources: [...clean.sources, {id: 'cdip-EMBED', outcome: 'ok', fetchedAt: ago(0.1)}, {id: 'slo-beach-water-quality', outcome: 'ok', fetchedAt: ago(0.1)}]};
  const everyFeed = coastFeeds(), refusedEnrichment = new Set([...everyFeed].filter(name => !['nearshore', 'water-quality'].includes(name)));
  for (const [files, feeds, reason] of [[{}, everyFeed, 'missing'], [{[NEARSHORE]: nearshoreFeed(ago(3.1)), [BEACH]: beachFeed(ago(3.5))}, everyFeed, 'stale'],
    [{[NEARSHORE]: nearshoreFeed(), [BEACH]: beachFeed()}, refusedEnrichment, 'refused']]) {
    const r = await report({[REPORT]: embedded, ...files}, feeds);
    assert.equal(r.status, 200, reason);
    assert.equal(r.headers.get('X-Coast-Upstream'), `report=skippercast, nearshore=unavailable (${reason}), water-quality=unavailable (${reason})`);
    const data = await r.json();
    assert.deepEqual([data.nearshore, data.waterQuality, data.sources], [undefined, undefined, clean.sources], reason);
  }
  // With both feeds used, their rows and statuses replace the embedded ones.
  const near = nearshoreFeed(), beach = beachFeed();
  const used = await (await report({[REPORT]: embedded, [NEARSHORE]: near, [BEACH]: beach})).json();
  assert.deepEqual([used.nearshore.map(s => s.id), used.waterQuality, used.sources], [['SL345'], beach.waterQuality, [...clean.sources, ...near.sources, ...beach.sources]]);
});

test('a site whose model issue reached 48 h is served stale, never current, with its clocks unchanged', async () => {
  const old = site('SL552', 'north', {issuedAt: ago(48.2)}), feed = nearshoreFeed(ago(0.5), [site('SL345', 'central'), old]);
  const data = await (await report({[REPORT]: reportFeed(), [NEARSHORE]: feed})).json();
  assert.deepEqual(data.nearshore.map(s => s.freshness), ['current', 'stale']);
  assert.equal(data.nearshore[1].issuedAt, old.issuedAt); assert.equal(data.nearshore[1].fetchedAt, old.fetchedAt);
});

test('ocean and history packets are served from R2; stale ones are unavailable', async () => {
  const ocean = oceanFeed(), history = historyFeed(), store = feedStore({[OCEAN]: ocean, [HISTORY]: history});
  const o = await serveCoastData(request('/api/coast/ocean'), store);
  assert.equal(o.status, 200); assert.deepEqual(await o.json(), ocean); assert.equal(o.headers.get('X-Coast-Upstream'), 'ocean=skippercast');
  assert.equal(o.headers.get('Cache-Control'), 'no-store');
  const h = await (await serveCoastData(request('/api/coast/history?county=slo'), store)).json();
  // Published weekly: a series last observed over 3 h ago is stale now, whatever it was at publication.
  assert.deepEqual(h.stations.map(s => s.recent.stale), [true, false]);
  assert.deepEqual(h.stations.map(s => s.recent.lastObservedAt), history.stations.map(s => s.recent.lastObservedAt));
  assert.equal(h.generatedAt, history.generatedAt);
  const head = await serveCoastData(request('/api/coast/ocean', {method: 'HEAD'}), store);
  assert.equal(head.status, 200); assert.equal(await head.text(), '');
  const stale = feedStore({[OCEAN]: oceanFeed(ago(3.2)), [HISTORY]: historyFeed(ago(8 * 24 + 1))});
  for (const name of ['ocean', 'history']) {
    const r = await serveCoastData(request('/api/coast/' + name), stale);
    assert.equal(r.status, 503); assert.equal(r.headers.get('X-Coast-Upstream'), `${name}=unavailable (stale)`);
  }
});

test('without a current report base the report is unavailable, even with fresh nearshore and beach rows', async () => {
  const r = await report({[NEARSHORE]: nearshoreFeed(), [BEACH]: beachFeed()});
  assert.equal(r.status, 503); assert.equal(r.headers.get('X-Coast-Upstream'), 'report=unavailable (missing), nearshore=skippercast, water-quality=skippercast');
  for (const [feed, reason] of [[reportFeed(ago(2.1)), 'stale'], [reportFeed(ago(-0.5)), 'stale'], [{...reportFeed(), countyId: 'monterey'}, 'invalid'],
    [{...reportFeed(), sources: [{id: 'nws-alerts', outcome: 'partial', fetchedAt: ago(0)}]}, 'invalid'], [{...reportFeed(), tides: null}, 'invalid']]) {
    const s = await report({[REPORT]: feed});
    assert.equal(s.status, 503); assert.match(s.headers.get('X-Coast-Upstream'), new RegExp(`^report=unavailable \\(${reason}\\)`));
  }
  const head = await serveCoastData(request('/api/coast/report', {method: 'HEAD'}), feedStore({}));
  assert.equal(head.status, 503);
});

// FE-87: the report's base from coast_report.py, with the FE-84 overlays on SkipperCast's own report.
test('the fixture report passes packages/coast readiness in every county area', async () => {
  const {slo} = await import('../packages/coast/src/counties.ts');
  const {freshForecast, freshObservation, assess} = await import('../packages/coast/src/assessment.ts');
  const {availableDays, buildDaily} = await import('../packages/coast/src/daily.ts');
  const {createState} = await import('../packages/coast/src/state/experience.ts');
  const {recentCatchTrips} = await import('../packages/coast/src/ui/catches.ts');
  const report = skippercastReport, now = new Date(Date.parse(report.generatedAt) + 10 * 60_000);
  for (const area of slo.areas) {
    assert.equal(freshForecast(report, area, now)?.sourceId, `nws-${area.id}`, area.id);
    const days = availableDays(report, slo, area, now);
    assert.equal(days.length, 3, area.id);
    for (const mode of ['boat', 'shore']) {
      const brief = buildDaily(report, slo, area, mode, days[0].date, now);
      // Shore also lists its offshore surf estimate (the fixture carries no nearshore model) and, for Avila and Pismo, the
      // missing shoreline bearing (#542).
      const shore = ['Breaking surf, beach access and water quality need a local check', 'Surf is an offshore estimate where no fresh nearshore model covers the hour',
        ...(area.id === 'south' ? ['Wind side unknown for this stretch of coast; wind judged on speed only'] : [])];
      // Boat at Morro Bay (central) also lists the bar check's offshore swell estimate (#542).
      const boat = ['Harbor entrance and full return route need a separate check',
        ...(area.id === 'central' ? ['Bar swell is an offshore estimate where no fresh nearshore model covers the hour'] : [])];
      assert.deepEqual(brief.missing, mode === 'boat' ? boat : shore, area.id);
      assert.ok(brief.hours.length && brief.tides.length && brief.tideEvents.length && brief.tempObservation, area.id);
    }
    assert.equal(assess(report, area, 'boat', now, slo.timezone).status, 'Caution', 'the active advisory, not missing data');
  }
  assert.ok(report.observations.some(o => o.stationId === slo.temperatureStationId && freshObservation(o.observedAt, now)));
  assert.deepEqual(recentCatchTrips(createState(report, slo, 'boat', 'central', undefined, undefined, now)).map(t => t.boat), ['Fixture Vessel']);
});

test('with every source published, the snapshots keep each source\'s clocks and make no outbound request', async () => {
  const before = outbound;
  const own = reportFeed(), near = nearshoreFeed(), beach = beachFeed();
  const store = feedStore({[REPORT]: own, [NEARSHORE]: near, [BEACH]: beach, [OCEAN]: oceanFeed(), [HISTORY]: historyFeed()});
  for (const name of ['report', 'ocean', 'history']) for (const method of ['GET', 'HEAD'])
    assert.equal((await serveCoastData(request('/api/coast/' + name, {method}), store)).status, 200, `${method} ${name}`);
  const r = await serveCoastData(request('/api/coast/report?region=morro-bay'), store);
  const data = await r.json();
  for (const key of ['generatedAt', 'forecasts', 'observations', 'tides', 'tideEvents', 'alerts', 'catches', 'catchContext', 'catchStatus', 'spatial', 'visibility'])
    assert.deepEqual(data[key], own[key], key);
  assert.equal(outbound, before);
});

test('#422: history needs a positive recentWindowDays; a merged report over 8 MB is refused, not truncated', async () => {
  for (const days of [undefined, 0, '45']) {
    const r = await serveCoastData(request('/api/coast/history'), feedStore({[HISTORY]: {...historyFeed(), recentWindowDays: days}}));
    assert.equal(r.status, 503); assert.equal(r.headers.get('X-Coast-Upstream'), 'history=unavailable (invalid)', String(days));
  }
  const pad = (data, size) => ({...data, padding: 'x'.repeat(size - new TextEncoder().encode(JSON.stringify(data)).byteLength - 20)});
  const many = nearshoreFeed(ago(0.5), Array.from({length: 150}, (_, i) => site(`SL${i}`, 'central')));
  const big = pad(reportFeed(), 8 * 1024 * 1024);
  assert.equal((await report({[REPORT]: big, [NEARSHORE]: many, [BEACH]: beachFeed()})).status, 503);
  assert.equal((await report({[REPORT]: big, [BEACH]: beachFeed()})).status, 503, 'merged with the beach rows alone');
  assert.equal((await report({[REPORT]: big})).status, 200, 'the unmerged packet fits');
});
