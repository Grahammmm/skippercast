// dist/sw.js is a classic worker script. It is loaded here, unchanged, in a
// node:vm context with a fake `self`, Cache Storage and network, so the tests
// exercise the exact file browsers run.
import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import {saveCoastalSnapshot} from '../dist/coastal-offline-core.js';
import {tileKey, tileURL, ENC_WMS, basemapRangeKey} from '../dist/offline-core.js';

const SOURCE = readFileSync(new URL('../dist/sw.js', import.meta.url), 'utf8');
const ORIGIN = 'https://skippercast.test';

class FakeCache {
  constructor(storage) { this.entries = new Map(); this.storage = storage; }
  static url(key) { return new URL(typeof key === 'string' ? key : key.url, ORIGIN).href; }
  async match(key, {ignoreSearch = false} = {}) {
    const want = FakeCache.url(key), strip = u => u.split('?')[0];
    for (const [url, response] of this.entries) if (url === want || (ignoreSearch && strip(url) === strip(want))) return response.clone();
    return undefined;
  }
  async put(key, response) { this.entries.set(FakeCache.url(key), response.clone()); }
  async delete(key) { return this.entries.delete(FakeCache.url(key)); }
  async keys() { return [...this.entries.keys()].map(u => new Request(u)); }
  async addAll(requests) {
    const responses = [];
    for (const request of requests) {
      const response = await this.storage.fetch(request);
      if (!response.ok) throw new TypeError('addAll: bad response');
      responses.push([request, response]);
    }
    for (const [request, response] of responses) await this.put(request, response);
  }
}

class FakeStorage {
  constructor(fetchImpl) { this.map = new Map(); this.fetch = fetchImpl; }
  async open(name) { if (!this.map.has(name)) this.map.set(name, new FakeCache(this)); return this.map.get(name); }
  async keys() { return [...this.map.keys()]; }
  async has(name) { return this.map.has(name); }
  async delete(name) { return this.map.delete(name); }
}

// In a worker, relative URLs resolve against the worker's location.
class WorkerRequest extends Request {
  constructor(input, init) { super(typeof input === 'string' ? new URL(input, ORIGIN) : input, init); }
}

/** A fresh worker. `network(request)` answers fetches; throw to simulate offline. */
function loadWorker({network = () => { throw new TypeError('offline'); }, locks} = {}) {
  const listeners = {}, messages = [];
  const calls = [];
  const fetchImpl = async (input, init) => {
    const request = input instanceof Request ? input : new Request(new URL(input.url || input, ORIGIN), init);
    calls.push(request.url);
    return network(request);
  };
  const storage = new FakeStorage(fetchImpl);
  const client = {id: 'page-1', postMessage: m => messages.push(m)};
  const self = {
    location: new URL(ORIGIN + '/sw.js'), navigator:{locks},
    addEventListener: (type, fn) => { (listeners[type] ||= []).push(fn); },
    clients: {get: async id => (id === client.id ? client : undefined), claim: async () => {}, matchAll: async () => []},
    registration: {showNotification: async () => {}},
    skipWaiting: async () => {},
  };
  const context = vm.createContext({self, caches: storage, clients: self.clients, fetch: fetchImpl, console: {warn() {}, log() {}},
    URL, Request: WorkerRequest, Response, Headers, Map, Set, Promise, Date, Math, Number, String, JSON, Error, TypeError, Array, TextDecoder, Uint8Array, setTimeout, clearTimeout});
  vm.runInContext(SOURCE, context, {filename: 'sw.js'});
  return {context, listeners, storage, messages, calls, client};
}

/** Dispatch a fetch event; resolves to the response or rejects like respondWith would. */
async function dispatch(worker, request) {
  let responded = null;
  const waits = [];
  const event = {request, clientId: worker.client.id, respondWith: p => { responded = p; }, waitUntil: p => waits.push(p)};
  worker.listeners.fetch.forEach(fn => fn(event));
  if (!responded) return null;
  const response = await responded;
  await Promise.all(waits);
  return response;
}

// undici's Request refuses mode 'navigate', so a navigation is a plain request-like object.
const nav = path => ({url: ORIGIN + path, method: 'GET', mode: 'navigate', headers: new Headers()});
const get = url => new Request(new URL(url, ORIGIN));
const chartTile = (z, x, y, layers = '0,1,2,6') => {
  // The GetMap URL v1's 2D map library built for its WMS tile layer (version 1.3.0, 512 px tiles).
  const half = 20037508.342789244, span = 2 * half / 2 ** (z - 1);
  const bbox = [-half + x * span, half - (y + 1) * span, -half + (x + 1) * span, half - y * span].join(',');
  return `${ENC_WMS}?service=WMS&request=GetMap&layers=${layers}&styles=&format=image%2Fpng&transparent=false&version=1.3.0&width=512&height=512&crs=EPSG%3A3857&bbox=${bbox}`;
};

test('routing: shell, fingerprinted assets, public data and tiles; private and OSM requests are left alone', () => {
  const {context} = loadWorker();
  const route = (request) => context.routeFor(request, ORIGIN);
  assert.equal(route(nav('/')), 'shell');
  assert.equal(route(get('/app.0123456789.js')), 'immutable');
  assert.equal(route(get('/vendor/simplewebauthn-browser-14.0.0/index.umd.min.js')), 'static');
  for (const path of ['/api/forecast?region=morro-bay', '/api/intelligence?region=x', '/api/daily?region=morro-bay&part=regulations', '/api/om/v1/marine?a=1', '/feeds/conditions/x.json', '/regions/index.json', '/data/regulations.json'])
    assert.equal(route(get(path)), 'data', path);
  for (const path of ['/api/session', '/api/trips', '/api/subscription', '/api/boat/lookup', '/sw.js', '/precache.json',
    '/feeds/tiles/seafloor/manifest-morro-bay.json', '/feeds/tiles/seafloor/seafloor-morro-bay.pmtiles'])
    assert.equal(route(get(path)), null, path);
  assert.equal(route(new Request(ORIGIN + '/api/forecast', {method: 'POST', body: '{}'})), null);
  assert.equal(route(get('https://tile.openstreetmap.org/10/100/200.png')), null, 'OSM tiles are never cached');
  assert.equal(route(get('https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?product=predictions')), 'data');
  assert.equal(route(get(chartTile(11, 330, 800))), 'tile');
  assert.equal(route(get('https://example.com/x.json')), null);
});

test('a chart tile and the trip pack\'s own tile URL share one cache key', () => {
  const {context} = loadWorker();
  for (const [z, x, y] of [[8, 20, 50], [12, 330, 800]]) {
    const key = tileKey('0,1,2,6', z, x, y);
    assert.equal(context.encTileKey(chartTile(z, x, y)), key);
    assert.equal(context.encTileKey(tileURL({z, x, y}, '0,1,2,6')), key);
  }
  assert.equal(context.encTileKey(ENC_WMS + '?request=GetCapabilities'), null);
  assert.equal(context.encTileKey(chartTile(10, 1, 1).replace('EPSG%3A3857', 'EPSG%3A4326')), null);
});

test('data is network-first: stored with its saved time online, served marked offline when the network fails', async () => {
  let online = true;
  const worker = loadWorker({network: request => {
    if (!online) throw new TypeError('Failed to fetch');
    return Response.json({region_id: 'morro-bay', url: request.url});
  }});
  const live = await dispatch(worker, get('/api/forecast?region=morro-bay'));
  assert.equal(live.headers.get('X-SC-Offline'), null, 'a live answer is not marked');
  const stored = await (await worker.storage.open('sc-data')).match(ORIGIN + '/api/forecast?region=morro-bay');
  const savedAt = stored.headers.get('X-SC-Saved-At');
  assert.ok(Date.parse(savedAt) > 0);
  online = false;
  const saved = await dispatch(worker, get('/api/forecast?region=morro-bay'));
  assert.equal(saved.headers.get('X-SC-Offline'), savedAt);
  assert.equal((await saved.json()).region_id, 'morro-bay');
  assert.deepEqual(JSON.parse(JSON.stringify(worker.messages.at(-1))), {type: 'skippercast-offline', savedAt, url: ORIGIN + '/api/forecast?region=morro-bay'});
  await assert.rejects(dispatch(worker, get('/api/forecast?region=other')), /Failed to fetch/, 'nothing saved: the failure is not hidden');
});

test('a daily-feed part is saved online and answers offline, so the rules badge keeps its last check', async () => {
  let online = true;
  const path = '/api/daily?region=morro-bay&part=regulations';
  const worker = loadWorker({network: () => { if (!online) throw new TypeError('Failed to fetch'); return Response.json({part: 'regulations', region_id: 'morro-bay'}); }});
  await dispatch(worker, get(path));
  online = false;
  const saved = await dispatch(worker, get(path));
  assert.ok(saved.headers.get('X-SC-Offline'));
  assert.equal((await saved.json()).part, 'regulations');
});

test('private and error responses are never stored', async () => {
  const worker = loadWorker({network: request => new URL(request.url).pathname === '/api/intelligence' ? new Response('x', {status: 503}) : Response.json({ok: 1})});
  assert.equal(await dispatch(worker, get('/api/trips')), null);
  await dispatch(worker, get('/api/intelligence?region=x'));
  const stored = await worker.storage.has('sc-data') ? (await (await worker.storage.open('sc-data')).keys()).length : 0;
  assert.equal(stored, 0);
});

test('the newest copy across the recent-data cache and trip packs wins', async () => {
  const worker = loadWorker();
  const put = async (name, url, at, body) => (await worker.storage.open(name)).put(url, new Response(body, {headers: {'X-SC-Saved-At': at}}));
  await put('sc-data', ORIGIN + '/data/regulations.json', '2026-09-01T00:00:00.000Z', 'old');
  await put('sc-pack-morro-bay-1', ORIGIN + '/data/regulations.json', '2026-09-20T00:00:00.000Z', 'new');
  const response = await dispatch(worker, get('/data/regulations.json?v=3'));
  assert.equal(await response.text(), 'new');
  assert.equal(response.headers.get('X-SC-Offline'), '2026-09-20T00:00:00.000Z');
});

test('a saved tide prediction answers the next day\'s dated request for the same station', async () => {
  const worker = loadWorker();
  const tides = (begin, end) => `https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?product=predictions&application=SkipperCast&station=9412110&begin_date=${begin}&end_date=${end}&datum=MLLW&time_zone=gmt&interval=hilo&units=english&format=json`;
  await (await worker.storage.open('sc-pack-morro-bay-1')).put(tides('20260928', '20261007'), new Response('{"predictions":[]}', {headers: {'X-SC-Saved-At': '2026-09-29T00:00:00.000Z'}}));
  const response = await dispatch(worker, get(tides('20260929', '20261008')));
  assert.equal(response.headers.get('X-SC-Offline'), '2026-09-29T00:00:00.000Z');
  await assert.rejects(dispatch(worker, get(tides('20260929', '20261008').replace('9412110', '9410000'))));
  await assert.rejects(dispatch(worker, get(tides('20260929', '20261008').replace('interval=hilo', 'interval=6'))));
});

test('chart tiles come from a trip pack offline, marked with their saved time', async () => {
  const worker = loadWorker();
  await (await worker.storage.open('sc-pack-morro-bay-1')).put(tileKey('0,1,2,6', 11, 330, 800), new Response('png', {headers: {'X-SC-Saved-At': '2026-09-29T01:00:00.000Z'}}));
  const response = await dispatch(worker, new Request(chartTile(11, 330, 800), {mode: 'no-cors'}));
  assert.equal(await response.text(), 'png');
  assert.equal(response.headers.get('X-SC-Offline'), '2026-09-29T01:00:00.000Z');
  await assert.rejects(dispatch(worker, get(chartTile(11, 331, 800))));
});

test('install precaches the build manifest; navigation falls back to the cached shell offline', async () => {
  let online = true;
  const manifest = {schema_version: 1, build: 'dev', shells: ['/'], assets: ['/app.0123456789.js'], static: ['/manifest.webmanifest']};
  const worker = loadWorker({network: request => {
    if (!online) throw new TypeError('offline');
    const url = new URL(request.url);
    if (url.pathname === '/precache.json') return Response.json(manifest);
    return new Response(`body of ${url.pathname}${url.search}`);
  }});
  const waits = [];
  worker.listeners.install.forEach(fn => fn({waitUntil: p => waits.push(p)}));
  await Promise.all(waits);
  const shell = await worker.storage.open('sc-shell-dev');
  assert.deepEqual((await shell.keys()).map(r => { const u = new URL(r.url); return u.pathname + u.search; }).sort(), ['/', '/app.0123456789.js', '/manifest.webmanifest']);
  online = false;
  assert.equal(await (await dispatch(worker, nav('/?region=morro-bay'))).text(), 'body of /');
  assert.equal(await (await dispatch(worker, get('/app.0123456789.js'))).text(), 'body of /app.0123456789.js');
  await assert.rejects(dispatch(worker, nav('/sources.html')), 'only the app shell has an offline fallback');
});

// #497: '/' stores the landing. FE-61 removed the v1 shell: ?ui=v1 and /index.html open the landing too.
test('offline / opens the landing and its first paint, and so do ?ui=v1 and /index.html', async () => {
  let online = true;
  const manifest = {schema_version: 1, build: 'dev', shells: ['/'], assets: ['/assets/landing.1111111111.js'], static: []};
  const worker = loadWorker({network: request => {
    if (!online) throw new TypeError('offline');
    const url = new URL(request.url);
    if (url.pathname === '/precache.json') return Response.json(manifest);
    if (url.pathname === '/') return new Response('landing');
    return new Response(`body of ${url.pathname}`);
  }});
  const waits = [];
  worker.listeners.install.forEach(fn => fn({waitUntil: p => waits.push(p)}));
  await Promise.all(waits);
  online = false;
  assert.equal(await (await dispatch(worker, nav('/'))).text(), 'landing');
  assert.equal(await (await dispatch(worker, nav('/?ui=v2'))).text(), 'landing');
  assert.equal(await (await dispatch(worker, get('/assets/landing.1111111111.js'))).text(), 'body of /assets/landing.1111111111.js', 'the landing paints offline');
  assert.equal(await (await dispatch(worker, nav('/?ui=v1&region=morro-bay'))).text(), 'landing');
  assert.equal(await (await dispatch(worker, nav('/index.html'))).text(), 'landing');
  await assert.rejects(dispatch(worker, nav('/map?region=morro-bay')), /offline/, 'the app opens offline only from a pack');
  await assert.rejects(dispatch(worker, get('/assets/maplibre.2222222222.js')), /offline/, 'MapLibre is never installed');
});

test('a failed precache does not fail the install (push must still work)', async () => {
  const worker = loadWorker({network: () => new Response('no', {status: 500})});
  const waits = [];
  worker.listeners.install.forEach(fn => fn({waitUntil: p => waits.push(p)}));
  await assert.doesNotReject(Promise.all(waits));
  assert.equal((await (await worker.storage.open('sc-shell-dev')).keys()).length, 0);
});

test('activate removes older shells and keeps saved data and trip packs', async () => {
  const worker = loadWorker();
  for (const name of ['sc-shell-old1234567', 'sc-shell-dev', 'sc-data', 'sc-pack-morro-bay-1']) await worker.storage.open(name);
  const waits = [];
  worker.listeners.activate.forEach(fn => fn({waitUntil: p => waits.push(p)}));
  await Promise.all(waits);
  assert.deepEqual((await worker.storage.keys()).sort(), ['sc-data', 'sc-pack-morro-bay-1', 'sc-shell-dev']);
});

test('precacheList accepts only same-origin paths from a valid manifest', () => {
  const {context} = loadWorker();
  assert.deepEqual([...context.precacheList({shells: ['/'], assets: ['/a.0123456789.js', '//evil.test/x.js', 'https://evil.test/y.js'], static: ['/icon.png']})],
    ['/', '/a.0123456789.js', '/icon.png']);
  assert.throws(() => context.precacheList({assets: []}), /invalid precache manifest/);
});

test('push delivery and notification clicks are still handled', async () => {
  const worker = loadWorker();
  assert.equal(worker.listeners.push?.length, 1);
  assert.equal(worker.listeners.notificationclick?.length, 1);
  const shown = [];
  worker.context.self.registration.showNotification = async (title, options) => shown.push([title, options.tag]);
  const waits = [];
  worker.listeners.push[0]({data: {json: () => ({eventId: 'e1', body: 'Wind rising', title: 'Trip'})}, waitUntil: p => waits.push(p)});
  await Promise.all(waits);
  assert.deepEqual(shown, [['Trip', 'e1']]);
});

const coastalPaths=['/api/coast/report','/api/coast/ocean','/api/coast/history'];
async function seedCoastal(worker){
 const base={schemaVersion:1,countyId:'slo',generatedAt:'2026-01-01T00:00:00.000Z'};
 return saveCoastalSnapshot({origin:ORIGIN,caches:worker.storage,fetcher:async url=>{const path=new URL(url).pathname;return Response.json({...base,...(path.endsWith('/report')?{forecasts:[],observations:[],tides:[],tideEvents:[],alerts:[],sources:[],catches:[],visibility:{}}:path.endsWith('/ocean')?{currents:[],sources:[]}:{stations:[],recentWindowDays:7})});}});
}
test('coastal snapshots serve exact original complete products only after network failure',async()=>{
 const acquired=[];const worker=loadWorker({locks:{request:async(name,options,read)=>{acquired.push([name,options.mode]);return read();}}});
 const meta=await seedCoastal(worker);
 for(const path of coastalPaths){const response=await dispatch(worker,get(path));const original=await (await worker.storage.open(meta.cache)).match(path);assert.equal(await response.text(),await original.text());assert.equal(response.headers.get('X-SC-Offline'),meta.saved_at);}
 assert.equal(acquired.length,3);assert.ok(acquired.every(([name,mode])=>name==='skippercast-coastal-snapshot:'+ORIGIN&&mode==='shared'));
 assert.equal(worker.messages.length,3);
});
test('coastal online reads never save automatically or hide HTTP errors',async()=>{
 let status=200;const worker=loadWorker({network:()=>new Response('live',{status})});
 await dispatch(worker,get(coastalPaths[0]));assert.deepEqual(await worker.storage.keys(),[]);
 await seedCoastal(worker);
 for(status of [403,404,503]){const response=await dispatch(worker,get(coastalPaths[0]));assert.equal(response.status,status);assert.equal(response.headers.get('X-SC-Offline'),null);}
});
test('coastal fallback excludes save requests, private variants, HEAD and Range',()=>{
 const {context}=loadWorker();const route=request=>context.routeFor(request,ORIGIN);
 for(const path of coastalPaths){assert.equal(route(get(path)),'coastal');assert.equal(route(get(path+'?x=1')),null);assert.equal(route(get('https://other.test'+path)),null);
 for(const headers of [{Authorization:'Bearer x'},{Cookie:'x=y'},{Range:'bytes=0-1'},{'X-SC-Offline-Save':'1'}])assert.equal(route(new Request(ORIGIN+path,{headers})),null);
 assert.equal(route(new Request(ORIGIN+path,{method:'HEAD'})),null);}
});
test('coastal fallback rejects missing or damaged members before serving any product',async()=>{
 for(const corruption of ['missing','shape','length','clock','metadata']){
 const worker=loadWorker(),meta=await seedCoastal(worker),cache=await worker.storage.open(meta.cache);
 if(corruption==='missing')await cache.delete(coastalPaths[2]);
 else if(corruption==='metadata')await cache.put('/__skippercast-coastal.json',new Response(JSON.stringify(meta),{status:201,headers:{'X-SC-Saved-At':meta.saved_at}}));
 else {const original=await cache.match(coastalPaths[2]),body=await original.json();if(corruption==='shape')delete body.stations;if(corruption==='length')body.extra='corrupt';if(corruption==='clock')body.generatedAt='2025-01-01T00:00:00.000Z';await cache.put(coastalPaths[2],Response.json(body,{headers:{'X-SC-Saved-At':meta.saved_at}}));}
 await assert.rejects(dispatch(worker,get(coastalPaths[0])),/offline/,corruption);
 }
});

// FE-51: a pack saved from the v2 app also holds the app's page, its hashed files and the basemap byte ranges.
const ARCHIVE = ORIGIN + '/feeds/tiles/basemap/ca-coast-20261008.pmtiles';
const ranged = (url, range) => new Request(url, {headers: {Range: range}});
async function v2Pack(worker) {
  const pack = await worker.storage.open('sc-pack-morro-bay-2'), at = {'X-SC-Saved-At': '2026-10-09T01:00:00.000Z'};
  await pack.put(ORIGIN + '/map', new Response('v2 page', {headers: {...at, 'Content-Type': 'text/html'}}));
  await pack.put(ORIGIN + '/assets/app.0123456789.js', new Response('v2 code', {headers: at}));
  await pack.put(ORIGIN + '/basemap/glyphs/dm-sans-medium/0-255.pbf', new Response('glyphs', {headers: at}));
  await pack.put(basemapRangeKey(ARCHIVE, 'bytes=0-16383'), new Response('header', {headers: {...at, 'Content-Range': 'bytes 0-16383/189085436', ETag: '"e"'}}));
}

test('basemap byte ranges route by archive and Range header only; the page and the worker derive one key', () => {
  const {context} = loadWorker();
  const route = request => context.routeFor(request, ORIGIN);
  assert.equal(route(ranged(ARCHIVE, 'bytes=0-16383')), 'basemap');
  assert.equal(context.basemapKey(ranged(ARCHIVE, 'bytes=16384-20000')), basemapRangeKey(ARCHIVE, 'bytes=16384-20000'));
  for (const request of [ranged(ARCHIVE + '?v=1', 'bytes=0-1'), ranged(ARCHIVE, 'bytes=0-'), ranged(ORIGIN + '/feeds/tiles/seafloor/seafloor-morro-bay.pmtiles', 'bytes=0-1'),
    ranged('https://other.test/feeds/tiles/basemap/ca-coast-20261008.pmtiles', 'bytes=0-1'), new Request(ARCHIVE, {method: 'HEAD', headers: {Range: 'bytes=0-1'}})])
    assert.equal(route(request), null, request.url);
});

test('offline, a v2 pack opens the app: its page at /map, hashed files, glyphs and basemap ranges, marked with the saved time', async () => {
  let online = true;
  const worker = loadWorker({network: request => { if (!online) throw new TypeError('offline'); return new Response('live', {status: request.headers.has('range') ? 206 : 200}); }});
  await v2Pack(worker);
  assert.equal(await (await dispatch(worker, ranged(ARCHIVE, 'bytes=0-16383'))).text(), 'live', 'network first');
  online = false;
  const page = await dispatch(worker, nav('/map?ui=v2&region=morro-bay#export'));
  assert.equal(await page.text(), 'v2 page');
  assert.equal(page.headers.get('X-SC-Offline'), '2026-10-09T01:00:00.000Z');
  assert.equal(await (await dispatch(worker, get('/assets/app.0123456789.js'))).text(), 'v2 code');
  assert.equal(await (await dispatch(worker, get('/basemap/glyphs/dm-sans-medium/0-255.pbf'))).text(), 'glyphs');
  const range = await dispatch(worker, ranged(ARCHIVE, 'bytes=0-16383'));
  assert.equal(range.status, 206);
  assert.equal(range.headers.get('Content-Range'), 'bytes 0-16383/189085436');
  assert.equal(range.headers.get('ETag'), '"e"');
  assert.equal(await range.text(), 'header');
  await assert.rejects(dispatch(worker, ranged(ARCHIVE, 'bytes=16384-20000')), /offline/, 'an unsaved range still fails');
  await assert.rejects(dispatch(worker, get('/assets/other.0123456789.js')), /offline/);
});

test('without a v2 pack the v1 offline answers are unchanged: /map and unsaved files fail, / opens the v1 shell', async () => {
  const worker = loadWorker();
  await (await worker.storage.open('sc-shell-dev')).put(ORIGIN + '/', new Response('v1 shell'));
  await assert.rejects(dispatch(worker, nav('/map?ui=v2')), /offline/);
  await assert.rejects(dispatch(worker, get('/basemap/glyphs/dm-sans-medium/0-255.pbf')), /offline/);
  assert.equal(await (await dispatch(worker, nav('/?region=morro-bay'))).text(), 'v1 shell');
  await v2Pack(worker);
  assert.equal(await (await dispatch(worker, nav('/?region=morro-bay'))).text(), 'v1 shell', 'a v2 pack never answers for the v1 shell');
});

// SC1938-01 (plan docs/plans/offline-ocean-coverage.md D8; tests 11, 13, 20): offline, a region's habitat manifest comes from
// its committed pack unless a newer sc-data copy is complete for every layer the pack saved. Manifests and caches are synthetic.
const REGION = 'test-coast', FEED = '/feeds/conditions/regions/', MANIFEST = `${FEED}${REGION}/habitat-dynamics.json`;
const SST = 'sst-analysis', WCOFS = 'wcofs-surface-forecast';
const T0 = '2026-10-19T10:00:00.000Z', T1 = '2026-10-20T10:00:00.000Z', T2 = '2026-10-21T10:00:00.000Z';
const tileName = (layer, tag, k) => `habitat-tiles/${layer}-${tag}-${k}.json`;
/** A manifest in the pipeline's shape (only what the worker reads): `layers` maps a layer id to its tile count. */
const manifestBody = (tag, layers, {status = 'ok', pad = 0} = {}) => ({schema_version: 1, region_id: REGION, tag, pad: 'x'.repeat(pad),
  layers: Object.fromEntries(Object.entries(layers).map(([id, n]) => [id, {id, status, tiles: Array.from({length: n}, (_, k) => ({path: tileName(id, tag, k)}))}]))});
const keep = (worker, cache, path, at, body) => worker.storage.open(cache).then(c => c.put(ORIGIN + path, new Response(typeof body === 'string' ? body : JSON.stringify(body), {headers: {'X-SC-Saved-At': at}})));
const commit = (worker, cache, region = REGION) => keep(worker, cache, '/__skippercast-pack.json', T1, {schema_version: 1, region_id: region});
async function keepTiles(worker, cache, tag, layers, at, region = REGION) {
  for (const [id, n] of Object.entries(layers)) for (let k = 0; k < n; k++) await keep(worker, cache, `${FEED}${region}/${tileName(id, tag, k)}`, at, `tile ${id} ${k}`);
}
/**
 * Offline manifest request with a committed pack (manifest `pack`, its tiles `packTiles`) and sc-data (manifest `data`, its tiles
 * `dataTiles`), each saved at the given time. Resolves to the tag of the manifest the worker answered with, or null for a failure.
 */
async function answer({pack, data, packTiles = pack, dataTiles = {}, packAt = T1, dataAt = T2, packBody = null, dataBody = null, packOptions, dataOptions, setup} = {}) {
  const worker = loadWorker();
  if (pack || packBody) { await commit(worker, 'sc-pack-test-coast-1'); await keep(worker, 'sc-pack-test-coast-1', MANIFEST, packAt, packBody ?? manifestBody('pack', pack, packOptions)); await keepTiles(worker, 'sc-pack-test-coast-1', 'pack', packTiles || {}, packAt); }
  if (data || dataBody) { await keep(worker, 'sc-data', MANIFEST, dataAt, dataBody ?? manifestBody('data', data, dataOptions)); await keepTiles(worker, 'sc-data', 'data', dataTiles, dataAt); }
  await setup?.(worker);
  const response = await dispatch(worker, get(MANIFEST)).catch(() => null);
  if (!response) return null;
  const saved = await response.text(), tag = saved.startsWith('{') ? JSON.parse(saved).tag : saved;
  assert.equal(response.headers.get('X-SC-Offline'), tag === 'pack' ? packAt : dataAt, 'marked with the saved time of the copy it answers with');
  return tag;
}
const BOTH = {[SST]: 2, [WCOFS]: 2};

test('isOceanKey: the worker\'s copy and the module\'s agree on every URL', async () => {
  const {isOceanKey} = await import('../dist/offline-core.js');
  const {context} = loadWorker(), region = `${ORIGIN}${FEED}a`;
  const table = [[`${region}/habitat-dynamics.json`, true], [`${region}/habitat-dynamics.json?v=3`, true], [`${region}/habitat-tiles/sst-analysis-0-0-0123456789abcdef.json`, true],
    [`${region}/habitat-tiles/x`, true], [`${region}/habitat-tiles/`, false], [`${region}/habitat-tiles`, false], [`${region}/habitat-tiles/a/b.json`, false],
    [`${region}/habitat-tiles/../habitat-dynamics.json`, true], [`${region}/habitat-tiles/../../b/habitat-tiles/x`, true], [`${region}/../../../x.json`, false],
    [`${ORIGIN}${FEED}A/habitat-dynamics.json`, false], [`${ORIGIN}${FEED}${'a'.repeat(65)}/habitat-dynamics.json`, false], [`${region}/habitat-dynamics.json.bak`, false],
    [`${ORIGIN}/regions/x/habitat-dynamics.json`, false], [`https://other.test${FEED}a/habitat-dynamics.json`, false], [`${ORIGIN}/feeds/tiles/seafloor/x.pmtiles`, false],
    [`${ORIGIN}/api/habitat?region=a`, false], ['not a url', false], ['', false]];
  for (const [url, want] of table) {
    assert.equal(isOceanKey(url, ORIGIN), want, `module: ${url}`);
    assert.equal(context.isOceanKey(url, ORIGIN), want, `worker: ${url}`);
  }
  assert.equal(context.isOceanKey(`${region}/habitat-dynamics.json`, 'https://other.test'), false, 'the origin must match the one given');
  assert.equal(isOceanKey(`${region}/habitat-dynamics.json`, undefined), false);
  assert.equal(context.isOceanKey(`${region}/habitat-dynamics.json`, undefined), false);
});

test('D8 (a): a pack that saved both layers beats a newer sc-data manifest whose tiles were never cached', async () => {
  assert.equal(await answer({pack: BOTH, data: BOTH}), 'pack');
  assert.equal(await answer({pack: BOTH, data: BOTH, dataTiles: {[SST]: 2}}), 'pack', 'a layer with only some tiles cached is not complete');
});

test('D8 (b): a newer sc-data copy complete for every layer the pack saved replaces it', async () => {
  assert.equal(await answer({pack: {[SST]: 2}, data: BOTH, dataTiles: BOTH}), 'data');
  assert.equal(await answer({pack: BOTH, data: BOTH, packTiles: {[SST]: 2}, dataTiles: BOTH}), 'data', 'a layer the pack failed to save does not hold it back');
  assert.equal(await answer({pack: BOTH, data: BOTH, dataTiles: BOTH}), 'data', 'equal coverage, newer copy');
  assert.equal(await answer({pack: BOTH, data: {[SST]: 2, [WCOFS]: 2}, dataTiles: BOTH, dataOptions: {status: 'retained'}}), 'data', 'retained counts as ok');
});

test('D8 (c): when the sets do not contain each other the pack wins', async () => {
  assert.equal(await answer({pack: {[SST]: 2, [WCOFS]: 2}, packTiles: {[SST]: 2}, data: BOTH, dataTiles: {[WCOFS]: 2}}), 'pack');
});

test('D8 (d): a pack that saved no layer gives way to any newer sc-data copy (today\'s newest-wins)', async () => {
  assert.equal(await answer({pack: BOTH, packTiles: {}, data: BOTH}), 'data');
  assert.equal(await answer({pack: BOTH, packTiles: {}, data: {}}), 'data');
  assert.equal(await answer({pack: {[SST]: 0}, data: BOTH}), 'data', 'a layer that lists no tile is not saved');
});

test('D8 (e): an older or equally old sc-data copy never replaces the pack', async () => {
  assert.equal(await answer({pack: BOTH, data: BOTH, dataTiles: BOTH, dataAt: T0}), 'pack');
  assert.equal(await answer({pack: BOTH, data: BOTH, dataTiles: BOTH, dataAt: T1}), 'pack');
  assert.equal(await answer({pack: BOTH, packTiles: {}, data: BOTH, dataAt: T0}), 'pack', 'even when the pack saved no layer');
});

test('D8 (f): a pack cache without PACK_META (a save in progress) is not a candidate, and its tiles count for nothing', async () => {
  const unfinished = async worker => { await keep(worker, 'sc-pack-test-coast-2', MANIFEST, '2026-10-22T10:00:00.000Z', manifestBody('half', BOTH)); await keepTiles(worker, 'sc-pack-test-coast-2', 'half', BOTH, T2); };
  assert.equal(await answer({pack: BOTH, setup: unfinished}), 'pack', 'the committed pack answers, not the newer unfinished one');
  assert.equal(await answer({data: BOTH, setup: unfinished}), 'data', 'only sc-data is a candidate');
  assert.equal(await answer({setup: unfinished}), null, 'nothing else is saved: the failure is not hidden');
  const tilesOnlyThere = async worker => { await keepTiles(worker, 'sc-pack-test-coast-2', 'data', BOTH, T2); };
  assert.equal(await answer({pack: BOTH, data: BOTH, setup: tilesOnlyThere}), 'pack', 'sc-data tiles held only by an unfinished pack are missing');
  const committed = async worker => { await commit(worker, 'sc-pack-test-coast-2'); await keepTiles(worker, 'sc-pack-test-coast-2', 'data', BOTH, T2); };
  assert.equal(await answer({pack: BOTH, data: BOTH, setup: committed}), 'data', 'the same tiles in a committed pack do count');
  const garbage = async worker => { await keep(worker, 'sc-pack-test-coast-2', '/__skippercast-pack.json', T1, 'not json'); await keep(worker, 'sc-pack-test-coast-2', MANIFEST, T2, manifestBody('junk', BOTH)); };
  assert.equal(await answer({pack: BOTH, setup: garbage}), 'pack', 'a meta that does not parse commits nothing');
});

test('D8 (g): an unparsable, over-1-MiB or wrongly shaped candidate counts as no layers', async () => {
  const pad = 1024 * 1024;
  assert.equal(await answer({pack: {[SST]: 2}, data: BOTH, dataTiles: BOTH, dataBody: 'not json'}), 'pack', 'unparsable sc-data copy');
  assert.equal(await answer({pack: {[SST]: 2}, data: BOTH, dataTiles: BOTH, dataBody: '{"layers":null}'}), 'pack', 'no layers object');
  assert.equal(await answer({pack: {[SST]: 2}, data: BOTH, dataTiles: BOTH, dataOptions: {pad}}), 'pack', 'over 1 MiB');
  assert.equal(await answer({pack: BOTH, data: BOTH, dataTiles: BOTH, packOptions: {pad}}), 'data', 'an over-1-MiB pack copy saved nothing');
  assert.equal(await answer({packBody: 'not json', data: BOTH, dataTiles: BOTH}), 'data', 'an unparsable pack copy saved nothing');
  assert.equal(await answer({pack: BOTH, data: BOTH, dataTiles: BOTH, dataOptions: {status: 'stale'}}), 'pack', 'a layer that is not ok or retained is not complete');
  const under = await answer({pack: {[SST]: 2}, data: BOTH, dataTiles: BOTH, dataOptions: {pad: pad - 1000}});
  assert.equal(under, 'data', 'a manifest under the limit is read');
});

test('D8: a manifest tile path that leaves the region folder counts as missing, never present', async () => {
  const escape = path => async worker => {
    const copy = manifestBody('data', {[SST]: 1});
    copy.layers[SST].tiles = [{path}];
    await keep(worker, 'sc-data', MANIFEST, T2, copy);
    let target = null;
    try { target = new URL(path, ORIGIN + MANIFEST); } catch {}
    // Whatever the path points at is stored, in sc-data and the pack, so only the folder rule can refuse it.
    if (target && target.pathname !== MANIFEST) for (const cache of ['sc-data', 'sc-pack-test-coast-1']) await (await worker.storage.open(cache)).put(target.href, new Response('present', {headers: {'X-SC-Saved-At': T2}}));
  };
  for (const path of ['../other/habitat-tiles/x.json', 'habitat-tiles/../../other/habitat-tiles/x.json', '/feeds/conditions/regions/other/habitat-tiles/x.json', 'https://evil.test/feeds/conditions/regions/test-coast/habitat-tiles/x.json',
    'habitat-tiles/x.json?v=2', '../test-coast/habitat-dynamics.json', 'habitat-tiles/sub/x.json', 'habitat-tiles/', 'http://[bad', ''])
    assert.equal(await answer({pack: {[SST]: 2}, setup: escape(path)}), 'pack', path);
  const sound = async worker => { const copy = manifestBody('data', {[SST]: 1}); await keep(worker, 'sc-data', MANIFEST, T2, copy); await keepTiles(worker, 'sc-data', 'data', {[SST]: 1}, T2); };
  assert.equal(await answer({pack: {[SST]: 2}, setup: sound}), 'data', 'the same shape with a path inside the folder is complete');
  const missingPath = async worker => { const copy = manifestBody('data', {[SST]: 1}); copy.layers[SST].tiles = [{}, null, 7]; await keep(worker, 'sc-data', MANIFEST, T2, copy); };
  assert.equal(await answer({pack: {[SST]: 2}, setup: missingPath}), 'pack', 'tile records without a path');
});

test('D8: only the requested region\'s committed pack is a candidate', async () => {
  const worker = loadWorker();
  await commit(worker, 'sc-pack-test-coast-1');
  await keep(worker, 'sc-pack-test-coast-1', MANIFEST, T0, manifestBody('mine', BOTH));
  await commit(worker, 'sc-pack-test-coast-extra-1', 'test-coast-extra');
  await keep(worker, 'sc-pack-test-coast-extra-1', MANIFEST, T1, manifestBody('other', BOTH));
  const response = await dispatch(worker, get(MANIFEST));
  assert.equal((await response.json()).tag, 'mine', 'a newer copy in another region\'s pack is ignored, though its cache name starts with this region\'s');
  assert.equal(response.headers.get('X-SC-Offline'), T0);
  const other = loadWorker();
  await commit(other, 'sc-pack-test-coast-extra-1', 'test-coast-extra');
  await keep(other, 'sc-pack-test-coast-extra-1', MANIFEST, T1, manifestBody('other', BOTH));
  await assert.rejects(dispatch(other, get(MANIFEST)), /offline/, 'another region\'s pack alone answers nothing');
  await keep(other, 'sc-data', MANIFEST, T0, manifestBody('data', BOTH));
  assert.equal((await (await dispatch(other, get(MANIFEST))).json()).tag, 'data', 'an older sc-data copy is still the only candidate');
});

test('D8: of two committed packs of one region, the newer copy is the pack candidate', async () => {
  const worker = loadWorker();
  for (const [name, tag, at] of [['sc-pack-test-coast-1', 'old', T0], ['sc-pack-test-coast-2', 'new', T1]]) { await commit(worker, name); await keep(worker, name, MANIFEST, at, manifestBody(tag, BOTH)); }
  assert.equal((await (await dispatch(worker, get(MANIFEST))).json()).tag, 'new');
});

test('plan test 13: with no pack, offline manifests, tiles and failures are as before', async () => {
  let online = true;
  const worker = loadWorker({network: request => { if (!online) throw new TypeError('Failed to fetch'); return new URL(request.url).pathname.endsWith('.json') && request.url.includes('habitat-dynamics') ? Response.json(manifestBody('live', BOTH)) : new Response('tile'); }});
  assert.equal((await (await dispatch(worker, get(MANIFEST))).json()).tag, 'live');
  assert.equal(await (await dispatch(worker, get(`${FEED}${REGION}/${tileName(SST, 'live', 0)}`))).text(), 'tile');
  online = false;
  const manifest = await dispatch(worker, get(MANIFEST));
  assert.equal((await manifest.json()).tag, 'live', 'sc-data alone answers, with no tiles required');
  assert.ok(manifest.headers.get('X-SC-Offline'));
  assert.equal(await (await dispatch(worker, get(`${FEED}${REGION}/${tileName(SST, 'live', 0)}`))).text(), 'tile');
  await assert.rejects(dispatch(worker, get(`${FEED}other/habitat-dynamics.json`)), /Failed to fetch/, 'nothing saved: the failure is not hidden');
  await assert.rejects(dispatch(worker, get(`${FEED}${REGION}/${tileName(SST, 'live', 9)}`)), /Failed to fetch/);
  assert.deepEqual(JSON.parse(JSON.stringify(worker.messages.at(-1))).type, 'skippercast-offline');
});

test('ocean tiles and every other route keep plain newest-wins, pack or not', async () => {
  const worker = loadWorker(), tile = `${FEED}${REGION}/${tileName(SST, 'x', 0)}`;
  await commit(worker, 'sc-pack-test-coast-1');
  await keep(worker, 'sc-pack-test-coast-1', tile, T1, 'pack tile');
  await keep(worker, 'sc-data', tile, T2, 'data tile');
  assert.equal(await (await dispatch(worker, get(tile))).text(), 'data tile');
  await keep(worker, 'sc-pack-test-coast-1', '/data/regulations.json', T2, 'pack rules');
  await keep(worker, 'sc-data', '/data/regulations.json', T1, 'data rules');
  assert.equal(await (await dispatch(worker, get('/data/regulations.json'))).text(), 'pack rules');
  await keep(worker, 'sc-pack-test-coast-1', '/api/habitat?region=test-coast', T1, 'pack api');
  await keep(worker, 'sc-data', '/api/habitat?region=test-coast', T2, 'data api');
  assert.equal(await (await dispatch(worker, get('/api/habitat?region=test-coast'))).text(), 'data api', 'the Worker\'s JSON copy is not an ocean key');
});

test('plan test 20: the coastal route ignores pack contents, and a manifest read never opens coastal caches', async () => {
  const worker = loadWorker();
  await commit(worker, 'sc-pack-test-coast-1');
  for (const path of coastalPaths) await keep(worker, 'sc-pack-test-coast-1', path, T2, JSON.stringify({generatedAt: '2026-01-01T00:00:00.000Z'}));
  for (const path of coastalPaths) await assert.rejects(dispatch(worker, get(path)), /offline/, 'a pack copy never answers the coastal route');
  const before = JSON.stringify((await worker.storage.keys()).sort());
  const meta = await seedCoastal(worker);
  const coastalBefore = await Promise.all([meta.cache, 'sc-coastal-index'].map(async n => JSON.stringify((await (await worker.storage.open(n)).keys()).map(r => r.url))));
  await keep(worker, 'sc-pack-test-coast-1', MANIFEST, T1, manifestBody('pack', BOTH));
  await keepTiles(worker, 'sc-pack-test-coast-1', 'pack', BOTH, T1);
  await keep(worker, 'sc-data', MANIFEST, T2, manifestBody('data', BOTH));
  const opened = [], open = worker.storage.open.bind(worker.storage);
  worker.storage.open = async name => { opened.push(name); return open(name); };
  assert.equal((await (await dispatch(worker, get(MANIFEST))).json()).tag, 'pack');
  assert.deepEqual([...new Set(opened)].sort(), ['sc-data', 'sc-pack-test-coast-1'], 'only the data cache and committed packs are opened');
  assert.ok(opened.every(n => !n.startsWith('sc-coastal-')));
  const coastalAfter = await Promise.all([meta.cache, 'sc-coastal-index'].map(async n => JSON.stringify((await (await worker.storage.open(n)).keys()).map(r => r.url))));
  assert.deepEqual(coastalAfter, coastalBefore, 'the coastal caches are untouched');
  assert.ok(JSON.parse(before).includes('sc-pack-test-coast-1'));
  for (const path of coastalPaths) assert.equal((await dispatch(worker, get(path))).headers.get('X-SC-Offline'), meta.saved_at, 'the coastal snapshot still answers from its own caches');
});
