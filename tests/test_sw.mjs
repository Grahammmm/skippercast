// dist/sw.js is a classic worker script. It is loaded here, unchanged, in a
// node:vm context with a fake `self`, Cache Storage and network, so the tests
// exercise the exact file browsers run.
import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import {tileKey, tileURL, ENC_WMS} from '../dist/offline-core.js';

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
function loadWorker({network = () => { throw new TypeError('offline'); }} = {}) {
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
    location: new URL(ORIGIN + '/sw.js'),
    addEventListener: (type, fn) => { (listeners[type] ||= []).push(fn); },
    clients: {get: async id => (id === client.id ? client : undefined), claim: async () => {}, matchAll: async () => []},
    registration: {showNotification: async () => {}},
    skipWaiting: async () => {},
  };
  const context = vm.createContext({self, caches: storage, clients: self.clients, fetch: fetchImpl, console: {warn() {}, log() {}},
    URL, Request: WorkerRequest, Response, Headers, Map, Set, Promise, Date, Math, Number, String, JSON, Error, TypeError, Array});
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
const leafletTile = (z, x, y, layers = '0,1,2,6') => {
  // The GetMap URL Leaflet 1.9 builds for L.tileLayer.wms(..., {version:'1.3.0', tileSize:512}).
  const half = 20037508.342789244, span = 2 * half / 2 ** (z - 1);
  const bbox = [-half + x * span, half - (y + 1) * span, -half + (x + 1) * span, half - y * span].join(',');
  return `${ENC_WMS}?service=WMS&request=GetMap&layers=${layers}&styles=&format=image%2Fpng&transparent=false&version=1.3.0&width=512&height=512&crs=EPSG%3A3857&bbox=${bbox}`;
};

test('routing: shell, fingerprinted assets, public data and tiles; private and OSM requests are left alone', () => {
  const {context} = loadWorker();
  const route = (request) => context.routeFor(request, ORIGIN);
  assert.equal(route(nav('/')), 'shell');
  assert.equal(route(get('/app.0123456789.js')), 'immutable');
  assert.equal(route(get('/vendor/leaflet.js')), 'static');
  for (const path of ['/api/forecast?region=morro-bay', '/api/intelligence?region=x', '/api/om/v1/marine?a=1', '/feeds/conditions/x.json', '/regions/index.json', '/data/regulations.json'])
    assert.equal(route(get(path)), 'data', path);
  for (const path of ['/api/session', '/api/trips', '/api/subscription', '/api/boat/lookup', '/sw.js', '/precache.json'])
    assert.equal(route(get(path)), null, path);
  assert.equal(route(new Request(ORIGIN + '/api/forecast', {method: 'POST', body: '{}'})), null);
  assert.equal(route(get('https://tile.openstreetmap.org/10/100/200.png')), null, 'OSM tiles are never cached');
  assert.equal(route(get('https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?product=predictions')), 'data');
  assert.equal(route(get(leafletTile(11, 330, 800))), 'tile');
  assert.equal(route(get('https://example.com/x.json')), null);
});

test('a Leaflet chart tile and the trip pack\'s own tile URL share one cache key', () => {
  const {context} = loadWorker();
  for (const [z, x, y] of [[8, 20, 50], [12, 330, 800]]) {
    const key = tileKey('0,1,2,6', z, x, y);
    assert.equal(context.encTileKey(leafletTile(z, x, y)), key);
    assert.equal(context.encTileKey(tileURL({z, x, y}, '0,1,2,6')), key);
  }
  assert.equal(context.encTileKey(ENC_WMS + '?request=GetCapabilities'), null);
  assert.equal(context.encTileKey(leafletTile(10, 1, 1).replace('EPSG%3A3857', 'EPSG%3A4326')), null);
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
  const response = await dispatch(worker, new Request(leafletTile(11, 330, 800), {mode: 'no-cors'}));
  assert.equal(await response.text(), 'png');
  assert.equal(response.headers.get('X-SC-Offline'), '2026-09-29T01:00:00.000Z');
  await assert.rejects(dispatch(worker, get(leafletTile(11, 331, 800))));
});

test('install precaches the build manifest; navigation falls back to the cached shell offline', async () => {
  let online = true;
  const manifest = {schema_version: 1, build: 'dev', shells: ['/'], assets: ['/app.0123456789.js'], static: ['/vendor/leaflet.js']};
  const worker = loadWorker({network: request => {
    if (!online) throw new TypeError('offline');
    const path = new URL(request.url).pathname;
    if (path === '/precache.json') return Response.json(manifest);
    return new Response(`body of ${path}`);
  }});
  const waits = [];
  worker.listeners.install.forEach(fn => fn({waitUntil: p => waits.push(p)}));
  await Promise.all(waits);
  const shell = await worker.storage.open('sc-shell-dev');
  assert.deepEqual((await shell.keys()).map(r => new URL(r.url).pathname).sort(), ['/', '/app.0123456789.js', '/vendor/leaflet.js']);
  online = false;
  assert.equal(await (await dispatch(worker, nav('/?region=morro-bay'))).text(), 'body of /');
  assert.equal(await (await dispatch(worker, get('/app.0123456789.js'))).text(), 'body of /app.0123456789.js');
  await assert.rejects(dispatch(worker, nav('/sources.html')), 'only the app shell has an offline fallback');
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
