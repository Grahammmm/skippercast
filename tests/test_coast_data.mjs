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
