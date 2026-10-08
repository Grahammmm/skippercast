import test from 'node:test';
import assert from 'node:assert/strict';
globalThis.REGIONS = {};
globalThis.DEPLOYMENT = {allowed_origins:['https://skippercast.com']};
const {coastTarget, serveCoastData} = await import('../server/coast-data.ts');

const request = (path, init) => new Request('https://skippercast.com' + path, init);
const snapshot = {schemaVersion:1, countyId:'slo', generatedAt:'2026-10-06T12:00:00Z', observations:[]};
const response = (data = snapshot) => new Response(JSON.stringify(data), {headers:{'Content-Type':'application/json'}});

test('bridge reads only explicit public datasets on the fixed owned host', () => {
  for (const path of ['/api/coast/report', '/api/coast/ocean', '/api/coast/history?county=slo', '/api/coast/habitat/release', '/api/coast/habitat/tiles?region=morro-bay', '/coast-data/data/coast-wide/c--122880--155648-32.bin', '/coast-data/data/coast3d/chart-model.json', '/coast-data/data/skippercast-habitat.geojson']) {
    assert.equal(coastTarget(new URL(request(path).url)).url.origin, 'https://fish-report.g4651.workers.dev', path);
  }
  for (const path of ['/api/coast/report?county=monterey', '/api/coast/report?region=monterey-point-sur', '/api/coast/report?region=constructor', '/api/coast/report?region=morro-bay&region=monterey-point-sur', '/api/coast/trips', '/api/coast/admin', '/api/coast/habitat/tiles?region=constructor', '/coast-data/data/government-habitat/private.bin', '/coast-data/data/habitat-government/private.bin', '/coast-data/artifacts/private.json', '/coast-data/data/%67overnment-habitat/private.bin', '/coast-data/data/coast-wide/%2e%2e/private.json', '/coast-data/data/coast-wide/escape%252fprivate.bin', '/coast-data/data/coast-wide/a.bin?url=https://other.test/', '/coast-data/data/coast-wide/a.bin?release=bad']) assert.equal(coastTarget(new URL(request(path).url)), null, path);
});

test('public snapshot bytes and original clock remain unchanged; identity headers are discarded', async () => {
  let seen;
  const raw = JSON.stringify(snapshot);
  const r = await serveCoastData(request('/api/coast/report', {headers:{Cookie:'session=private', Authorization:'Bearer secret', Origin:'https://skippercast.com', 'X-User':'private'}}), async req => {seen=req; return response();});
  assert.equal(r.status, 200); assert.equal(await r.text(), raw);
  assert.deepEqual([...seen.headers], []);
  assert.equal(r.headers.get('Cache-Control'), 'no-store');
  assert.equal(seen.redirect, 'manual');
});

test('missing, wrong-county, malformed, HTML and oversized snapshots are withheld', async () => {
  const bad = [() => new Response('missing', {status:503}), () => response({...snapshot,countyId:'monterey'}),
    () => response({...snapshot,generatedAt:'not-a-clock'}), () => new Response('<html>wrong product</html>',{headers:{'Content-Type':'text/html'}}),
    () => new Response('broken',{headers:{'Content-Type':'application/json'}}),
    () => new Response('{}',{headers:{'Content-Length':String(17*1024*1024),'Content-Type':'application/json'}})];
  for (const make of bad) assert.equal((await serveCoastData(request('/api/coast/history'), async () => make())).status, 503);
});

test('range responses retain exact bytes, ETag and original habitat release receipt', async () => {
  const r = await serveCoastData(request('/api/coast/habitat/tiles?region=morro-bay', {headers:{Range:'bytes=2-4'}}), async req => {
    assert.equal(req.headers.get('Range'), 'bytes=2-4');
    return new Response(new Uint8Array([3,4,5]), {status:206,headers:{'Content-Range':'bytes 2-4/10',ETag:'"original"','X-Fish-Habitat-Release':'a'.repeat(64), 'Set-Cookie':'private=1'}});
  });
  assert.equal(r.status,206); assert.deepEqual([...new Uint8Array(await r.arrayBuffer())],[3,4,5]);
  assert.equal(r.headers.get('ETag'),'"original"'); assert.equal(r.headers.get('X-Fish-Habitat-Release'),'a'.repeat(64));
  assert.equal(r.headers.get('Set-Cookie'),null);
  for (const range of ['bytes=0-', 'bytes=-8', 'bytes=4-2', 'bytes=0-99999999999999999999', 'bytes=0-2097152']) {
    assert.equal((await serveCoastData(request('/api/coast/habitat/tiles?region=morro-bay',{headers:{Range:range}}), async()=>{throw Error('Must not fetch');})).status,416);
  }
});

test('range downgrade, changed offsets and wrong lengths are refused', async () => {
  for (const [status, range, bytes] of [[200,'bytes 2-4/10',[3,4,5]],[206,'bytes 1-3/10',[3,4,5]],[206,'bytes 2-4/10',[3,4]]]) {
    const r = await serveCoastData(request('/api/coast/habitat/tiles?region=morro-bay',{headers:{Range:'bytes=2-4'}}), async()=>new Response(new Uint8Array(bytes),{status,headers:{'Content-Range':range}}));
    assert.equal(r.status,503);
  }
});

test('HEAD preserves archive identity without a body; writes and private paths never fetch', async () => {
  const r=await serveCoastData(request('/api/coast/habitat/tiles?region=morro-bay',{method:'HEAD'}),async req=>{
    assert.equal(req.method,'HEAD'); return new Response(null,{headers:{'Content-Length':'12000000',ETag:'"archive"'}});
  });
  assert.equal(r.status,200); assert.equal(r.headers.get('Content-Length'),'12000000'); assert.equal(await r.text(),'');
  assert.equal((await serveCoastData(request('/api/coast/report',{method:'POST'}),async()=>{throw Error('Must not fetch');})).status,405);
  assert.equal((await serveCoastData(request('/api/coast/trips'),async()=>{throw Error('Must not fetch');})).status,404);
});

test('HEAD rejects inexact ranges and unsafe totals; unsolicited partial responses are unavailable', async () => {
  for (const [range,size] of [['bytes 99-101/200','3'],['bytes 2-4/10','500'],['bytes 2-4/99999999999999999999','3']]) {
    const r = await serveCoastData(request('/api/coast/habitat/tiles?region=morro-bay',{method:'HEAD',headers:{Range:'bytes=2-4'}}),async()=>new Response(null,{status:206,headers:{'Content-Range':range,'Content-Length':size}}));
    assert.equal(r.status,503);
  }
  const r = await serveCoastData(request('/coast-data/data/coast-wide/a.bin'),async()=>new Response(new Uint8Array([1]),{status:206,headers:{'Content-Range':'bytes 0-0/10'}}));
  assert.equal(r.status,503);
});

test('declared oversize, malformed lengths and streaming overflow cancel the upstream body', async () => {
  for (const length of ['99999999', 'malformed', null]) {
    let cancelled=false;
    const stream=new ReadableStream({start(controller){if(length===null)controller.enqueue(new Uint8Array(8*1024*1024+1));},cancel(){cancelled=true;}});
    const headers={}; if(length!==null)headers['Content-Length']=length;
    const r=await serveCoastData(request('/coast-data/data/coast-wide/a.bin'),async()=>new Response(stream,{headers}));
    assert.equal(r.status,503); assert.equal(cancelled,true,String(length));
  }
});
test('upstream redirects are rejected without following a foreign destination',async()=>{
 let calls=0;
 const response=await serveCoastData(new Request('https://skippercast.com/api/coast/report'),async request=>{calls++;assert.equal(request.redirect,'manual');return new Response(null,{status:302,headers:{Location:'https://foreign.example/private'}});});
 assert.equal(response.status,503);assert.equal(calls,1);
});

// FE-85: assets copied to R2 by scripts/coast/publish_assets.py (synthetic fixture bytes).
const sha = async bytes => Buffer.from(await crypto.subtle.digest('SHA-256', bytes)).toString('hex');
const noBridge = async () => { throw Error('Must not reach the bridge'); };
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
  const whole = await serveCoastData(request('/coast-data/data/coast-wide/a.bin'), noBridge, store);
  assert.equal(whole.status, 200); assert.deepEqual(new Uint8Array(await whole.arrayBuffer()), tile);
  assert.equal(whole.headers.get('ETag'), `"sha256-${entries['/data/coast-wide/a.bin'].sha256}"`);
  for (let i = 0; i < 2; i++) {  // the second read uses the verified version's etag
    const part = await serveCoastData(request(`/api/coast/habitat/tiles?region=morro-bay&release=${habitatRelease}`, {headers: {Range: 'bytes=2-4'}}), noBridge, store);
    assert.equal(part.status, 206); assert.deepEqual([...new Uint8Array(await part.arrayBuffer())], [253, 252, 251]);
    assert.equal(part.headers.get('Content-Range'), 'bytes 2-4/64'); assert.equal(part.headers.get('X-Fish-Habitat-Release'), habitatRelease);
  }
  const head = await serveCoastData(request('/api/coast/habitat/tiles?region=morro-bay', {method: 'HEAD'}), noBridge, store);
  assert.equal(head.status, 200); assert.equal(head.headers.get('Content-Length'), '64'); assert.equal(await head.text(), '');
});

test('an altered byte or an object missing from the manifest is refused before any byte is served', async () => {
  const {store, entries} = await fixture();
  const key = 'coast/objects/' + entries['/data/coast-wide/a.bin'].sha256;
  assert.equal((await serveCoastData(request('/coast-data/data/coast-wide/a.bin'), noBridge, store)).status, 200);
  store.objects[key] = tile.slice(); store.objects[key][10] ^= 1;  // tampered after an earlier verified read
  for (const init of [undefined, {headers: {Range: 'bytes=0-3'}}, {method: 'HEAD'}]) {
    const r = await serveCoastData(request('/coast-data/data/coast-wide/a.bin', init), noBridge, store);
    assert.equal(r.status, 503); assert.equal(r.headers.get('ETag'), null);
  }
  const fresh = await published({'/data/coast-wide/a.bin': {bytes: tile.map(v => v ^ 3)}});
  const altered = 'coast/objects/' + Object.values(fresh.entries)[0].sha256;
  fresh.store.objects[altered] = fresh.store.objects[altered].slice(); fresh.store.objects[altered][0] ^= 1;  // altered before any read
  assert.equal((await serveCoastData(request('/coast-data/data/coast-wide/a.bin'), noBridge, fresh.store)).status, 503);
  assert.equal((await serveCoastData(request('/coast-data/data/coast-wide/b.bin'), noBridge, store)).status, 404);
  assert.equal((await serveCoastData(request('/coast-data/data/coast3d/chart-model.json'), noBridge, store)).status, 404);
});

test('wrong ranges, unknown releases and expired entries are refused; encoded private paths never read R2', async () => {
  const {store} = await fixture();
  assert.equal((await serveCoastData(request('/coast-data/data/coast-wide/a.bin', {headers: {Range: 'bytes=60-70'}}), noBridge, store)).status, 416);
  assert.equal((await serveCoastData(request('/coast-data/data/coast-wide/a.bin', {headers: {Range: 'bytes=4-'}}), noBridge, store)).status, 416);
  for (const path of [`/api/coast/habitat/tiles?region=morro-bay&release=${'c'.repeat(64)}`, `/coast-data/data/coast-wide/a.bin?release=${habitatRelease}`])
    assert.equal((await serveCoastData(request(path), noBridge, store)).status, 404, path);
  store.reads.length = 0;
  for (const path of ['/coast-data/data/%67overnment-habitat/private.bin', '/coast-data/data/coast-wide/%2e%2e/private.json', '/coast-data/data/coast-wide/escape%252fprivate.bin', '/coast-data/data/habitat-government/current.json', '/coast-data/coast/current.json'])
    assert.equal((await serveCoastData(request(path), noBridge, store)).status, 404, path);
  assert.deepEqual(store.reads, []);
  const expired = await published({'/api/habitat/tiles?region=morro-bay': {bytes: tile, habitatRelease, expiresAt: '2020-01-01T00:00:00Z'}});
  assert.equal((await serveCoastData(request('/api/coast/habitat/tiles?region=morro-bay', {method: 'HEAD'}), noBridge, expired.store)).status, 503);
});

test('unpublished groups keep the bridge; held or mismatched releases fail closed', async () => {
  const bridged = async () => new Response(new Uint8Array([7]), {status: 200});
  const empty = fakeStore({});
  assert.deepEqual([...new Uint8Array(await (await serveCoastData(request('/coast-data/data/coast-wide/a.bin'), bridged, empty)).arrayBuffer())], [7]);
  const {store} = await published({'/data/coast-wide/a.bin': {bytes: tile}}, {groups: ['terrain']});
  assert.equal((await serveCoastData(request('/coast-data/data/slo-shoreline.geojson'), bridged, store)).status, 200);
  assert.equal((await serveCoastData(request('/api/coast/report'), async () => response(), store)).status, 200);
  for (const pointer of [{schemaVersion: 1, status: 'held', releaseId: 'd'.repeat(64)}, {schemaVersion: 1, status: 'ready', releaseId: 'd'.repeat(64)}]) {
    const held = await published({'/data/coast-wide/a.bin': {bytes: tile}}, {pointer});
    assert.equal((await serveCoastData(request('/coast-data/data/coast-wide/a.bin'), noBridge, held.store)).status, 503);
  }
});

test('held releases affect only published groups; the reef context travels with habitat', async () => {
  const bridged = async () => new Response(new Uint8Array([7]), {status: 200});
  const held = await published({'/data/coast-wide/a.bin': {bytes: tile}}, {pointer: {schemaVersion: 1, status: 'held', releaseId: 'd'.repeat(64)}});
  assert.equal((await serveCoastData(request('/coast-data/data/slo-shoreline.geojson'), bridged, held.store)).status, 200);
  const {store} = await published({'/data/coast-wide/a.bin': {bytes: tile}}, {groups: ['terrain']});
  const reef = await serveCoastData(request('/coast-data/data/coast-wide/reef-context.json'), bridged, store);
  assert.deepEqual([...new Uint8Array(await reef.arrayBuffer())], [7]);
});

test('concurrent first reads of one object hash it once', async () => {
  const cold = tile.map(v => v * 3);  // bytes no earlier test verified
  const {store, entries} = await published({'/api/habitat/tiles?region=morro-bay': {bytes: cold, habitatRelease, expiresAt: '2099-01-01T00:00:00Z'}});
  const key = 'coast/objects/' + entries['/api/habitat/tiles?region=morro-bay'].sha256;
  const parts = await Promise.all([0, 8, 16, 24].map(start => serveCoastData(request('/api/coast/habitat/tiles?region=morro-bay',
    {headers: {Range: `bytes=${start}-${start + 7}`}}), noBridge, store)));
  assert.deepEqual(parts.map(r => r.status), [206, 206, 206, 206]);
  assert.deepEqual(new Uint8Array(await parts[1].arrayBuffer()), cold.slice(8, 16));
  assert.equal(store.reads.filter(k => k === key).length, 1);
});

test("the renderer's verified-asset and habitat HEAD checks pass against R2 and fail on tampering", async () => {
  const {verifiedAsset} = await import('../packages/coast/src/coast3d/regional.ts');
  const {validateHabitatHeads} = await import('../packages/coast/src/map/habitat-lifecycle.ts');
  const {coastPath} = await import('../packages/coast/src/transport.ts');
  const {store, entries} = await fixture();
  const serve = (path, init) => serveCoastData(request(coastPath(path), init), noBridge, store);
  const original = globalThis.fetch; globalThis.fetch = (path, init) => serveCoastData(request(path, init), noBridge, store);
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
