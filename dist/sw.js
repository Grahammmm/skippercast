// SkipperCast service worker: trip-alert notifications and the offline trip pack.
//
// A classic script, not a module: trip-alerts.js and offline.js register the
// same stable '/sw.js' without {type:'module'} (the type is part of a
// registration, and classic workers run on every browser that has web push).
// The logic is plain top-level functions so tests/test_sw.mjs loads this exact
// file in node:vm with a fake `self`, rather than testing an exported copy.
//
// Caches (Cache Storage; nothing here uses localStorage):
//   sc-shell-<build>  the app shell '/' and this build's fingerprinted assets,
//                     listed by the build in /precache.json. Older builds are
//                     deleted on activate.
//   sc-data           the latest public data responses seen online (bounded).
//   sc-pack-<region>  an explicit "Save for offline" trip pack (offline-pack.js).
// Data is network-first. A response answered from a cache always carries
// X-SC-Offline: <saved-at ISO> and the page is told, so saved data is never
// shown as if it were live.

// Replaced with the build id by scripts/precache.mjs, so every deploy changes
// these bytes and the browser installs the new worker and its precache.
const BUILD = 'dev';
const SHELL_PREFIX = 'sc-shell-';
const SHELL_CACHE = SHELL_PREFIX + BUILD;
const DATA_CACHE = 'sc-data';
const PACK_PREFIX = 'sc-pack-';
const DATA_LIMIT = 150;
const COASTAL_PREFIX='sc-coastal-snapshot-',COASTAL_INDEX='sc-coastal-index',COASTAL_META='/__skippercast-coastal.json';
const COASTAL_LIMITS={'/api/coast/report':8*1024*1024,'/api/coast/ocean':8*1024*1024,'/api/coast/history':16*1024*1024};
const SAVED_HEADER = 'X-SC-Saved-At';
const OFFLINE_HEADER = 'X-SC-Offline';
// NOAA ENC chart display (chart-map.js). OSM street tiles are never stored:
// the OSM tile policy forbids bulk download and prefetching for offline use.
const ENC_ORIGIN = 'https://gis.charttools.noaa.gov';
const ENC_PATH = '/arcgis/rest/services/MCS/NOAAChartDisplay/MapServer/exts/MaritimeChartService/WMSServer';
const MERCATOR_HALF = 20037508.342789244;
// Public data, identical for everyone. Private routes (session, trips,
// subscriptions, boat lookup) are never cached.
const PUBLIC_API = /^\/api\/(?:forecast|intelligence|habitat|daily|om\/)/;
const DATA_PATH = /^\/(?:feeds|regions|data)\//;
// Public government data the page fetches directly (tides, NWS alerts).
const DATA_HOSTS = new Set(['api.tidesandcurrents.noaa.gov', 'api.weather.gov']);
const FINGERPRINTED = /\.[0-9a-f]{10}\.(?:js|css)$/;

/** Which strategy answers this request, or null to leave it to the network. */
function routeFor(request, origin) {
  if (request.method !== 'GET' || request.headers.has('range')) return null;
  const url = new URL(request.url);
  if (url.origin !== origin) {
    if (url.origin === ENC_ORIGIN && url.pathname === ENC_PATH) return encTileKey(url) ? 'tile' : null;
    return url.protocol === 'https:' && DATA_HOSTS.has(url.hostname) ? 'data' : null;
  }
  if (request.mode === 'navigate') return 'shell';
  if (url.pathname === '/sw.js' || url.pathname === '/precache.json') return null;
  if(Object.hasOwn(COASTAL_LIMITS,url.pathname)){return !request.headers.has('X-SC-Offline-Save')&&!url.search&&!url.hash&&!request.headers.has('authorization')&&!request.headers.has('cookie')?'coastal':null;}
  if (url.pathname.startsWith('/api/')) return PUBLIC_API.test(url.pathname) ? 'data' : null;
  // Seafloor habitat is shown only while its screening manifest is current; a
  // saved copy would outlive the Worker's expiry gate, so it is never cached.
  if (url.pathname.startsWith('/feeds/tiles/seafloor/')) return null;
  if (DATA_PATH.test(url.pathname)) return 'data';
  if (FINGERPRINTED.test(url.pathname)) return 'immutable';
  return 'static';
}

/**
 * Stable cache key for a WMS tile of the ENC chart: layer set, tile size and
 * Web Mercator tile index. Leaflet and offline-pack.js write the GetMap query
 * differently (parameter order, float digits), so neither URL is the key.
 * Null for anything that is not a square EPSG:3857 tile on the tile grid.
 */
function encTileKey(input) {
  const url = new URL(input);
  const p = new Map([...url.searchParams].map(([k, v]) => [k.toLowerCase(), v]));
  if (String(p.get('request')).toLowerCase() !== 'getmap') return null;
  const crs = p.get('crs') || p.get('srs');
  const size = Number(p.get('width')), layers = p.get('layers');
  const box = String(p.get('bbox') || '').split(',').map(Number);
  if (crs !== 'EPSG:3857' || !layers || !/^[0-9,]+$/.test(layers) || !(size >= 256) || Number(p.get('height')) !== size) return null;
  if (box.length !== 4 || box.some(v => !Number.isFinite(v))) return null;
  const span = box[2] - box[0];
  if (!(span > 0) || Math.abs((box[3] - box[1]) - span) > span * 1e-6) return null;
  const perAxis = Math.round((2 * MERCATOR_HALF) / span);
  const zoom = Math.log2(perAxis) + Math.log2(size / 256);
  if (!Number.isInteger(zoom) || Math.abs(perAxis * span - 2 * MERCATOR_HALF) > span * 1e-6) return null;
  const x = Math.round((box[0] + MERCATOR_HALF) / span), y = Math.round((MERCATOR_HALF - box[3]) / span);
  return `${ENC_ORIGIN}/__skippercast-tile/${layers}/${size}/${zoom}/${x}/${y}`;
}

/** A copy of a stored response that says, in a header, when it was saved. */
function offlineResponse(cached) {
  const headers = new Headers(cached.headers);
  const savedAt = headers.get(SAVED_HEADER) || new Date(0).toISOString();
  headers.set(OFFLINE_HEADER, savedAt);
  return new Response(cached.body, {status: cached.status, statusText: cached.statusText, headers});
}

/** A copy of a network response stamped with the time it was stored. */
function stamped(response, now = new Date()) {
  const headers = new Headers(response.headers);
  headers.set(SAVED_HEADER, now.toISOString());
  return new Response(response.body, {status: response.status, statusText: response.statusText, headers});
}

/** Only complete, readable answers are kept (no opaque, partial or error responses). */
function storable(response) {
  return !!response && response.status === 200 && ['basic', 'cors', 'default'].includes(response.type);
}

/**
 * A dated request whose saved answer still serves a later day: NOAA tide
 * predictions are requested for "yesterday to +8 days", so the URL changes
 * daily while a saved range still covers the trip. Null for anything else.
 */
function datasetKey(input) {
  const url = new URL(input);
  if (url.hostname !== 'api.tidesandcurrents.noaa.gov' || url.searchParams.get('product') !== 'predictions') return null;
  const p = url.searchParams;
  return ['tides', p.get('station'), p.get('interval'), p.get('datum'), p.get('units'), p.get('time_zone')].join('|');
}

/** The newest saved copy of a request across the data cache and every trip pack. */
async function newestSaved(request, key = request) {
  const names = (await caches.keys()).filter(n => n === DATA_CACHE || n.startsWith(PACK_PREFIX));
  const url = new URL(typeof key === 'string' ? key : key.url);
  // Static region files are sometimes requested with a ?v= tag; APIs and feeds are matched exactly.
  const loose = url.origin === self.location.origin && /^\/(?:regions|data)\//.test(url.pathname);
  const dataset = datasetKey(url);
  let best = null, bestAt = '';
  for (const name of names) {
    const cache = await caches.open(name);
    let hit = await cache.match(key, {ignoreVary: true}) || (loose ? await cache.match(key, {ignoreVary: true, ignoreSearch: true}) : undefined);
    if (!hit && dataset) {
      for (const saved of await cache.keys()) {
        if (datasetKey(saved.url) !== dataset) continue;
        const candidate = await cache.match(saved, {ignoreVary: true});
        if (candidate && (!hit || (candidate.headers.get(SAVED_HEADER) || '') > (hit.headers.get(SAVED_HEADER) || ''))) hit = candidate;
      }
    }
    const at = hit?.headers.get(SAVED_HEADER) || '';
    if (hit && (!best || at > bestAt)) { best = hit; bestAt = at; }
  }
  return best;
}

async function trimCache(name, limit) {
  const cache = await caches.open(name), keys = await cache.keys();
  for (const key of keys.slice(0, Math.max(0, keys.length - limit))) await cache.delete(key);
}

// Per page (client id): the oldest saved-at it has been shown. offline.js asks
// for it once it loads, because messages sent before it listens are lost.
const servedFromCache = new Map();
async function tellClient(clientId, savedAt, url) {
  if (!clientId) return;
  const prior = servedFromCache.get(clientId);
  if (!prior || savedAt < prior) servedFromCache.set(clientId, savedAt);
  const client = await self.clients.get(clientId);
  client?.postMessage({type: 'skippercast-offline', savedAt: servedFromCache.get(clientId), url});
}

async function networkFirstData(event) {
  const {request} = event;
  try {
    const response = await fetch(request);
    if (storable(response)) {
      const copy = stamped(response.clone());
      event.waitUntil(caches.open(DATA_CACHE).then(c => c.put(request, copy)).then(() => trimCache(DATA_CACHE, DATA_LIMIT)).catch(() => {}));
    }
    return response;
  } catch (error) {
    const saved = await newestSaved(request);
    if (!saved) throw error;
    const response = offlineResponse(saved);
    event.waitUntil(tellClient(event.clientId, response.headers.get(OFFLINE_HEADER), request.url));
    return response;
  }
}

/** Explicit, completed public snapshot only. Ordinary browsing never saves it. */
async function coastalSnapshot(request){
 const manager=self.navigator?.locks??globalThis.navigator?.locks;const read=()=>readCoastalSnapshot(request);return manager?.request?manager.request('skippercast-coastal-snapshot:'+self.location.origin,{mode:'shared'},read):read();
}
function coastalProduct(path,body){
 const object=value=>value!==null&&typeof value==='object'&&!Array.isArray(value);
 if(!object(body)||body.schemaVersion!==1||body.countyId!=='slo'||typeof body.generatedAt!=='string'||!Number.isFinite(Date.parse(body.generatedAt))||Date.parse(body.generatedAt)>Date.now())return false;
 if(path==='/api/coast/report')return ['forecasts','observations','tides','tideEvents','alerts','sources','catches'].every(name=>Array.isArray(body[name]))&&object(body.visibility);
 if(path==='/api/coast/ocean')return Array.isArray(body.currents)&&Array.isArray(body.sources);
 return path==='/api/coast/history'&&Array.isArray(body.stations)&&Number.isFinite(body.recentWindowDays)&&body.recentWindowDays>0;
}
async function coastalBytes(response,limit){
 const reader=response.body.getReader(),parts=[];let size=0,timedOut=false;const timer=setTimeout(()=>{timedOut=true;void reader.cancel().catch(()=>{});},20000);
 try{while(true){const {done,value}=await reader.read();if(timedOut)throw Error('Snapshot read timeout');if(done)break;size+=value.byteLength;if(size>limit)throw Error('Snapshot byte limit');parts.push(value);}const bytes=new Uint8Array(size);let at=0;for(const part of parts){bytes.set(part,at);at+=part.byteLength;}return bytes;}catch(error){void reader.cancel().catch(()=>{});throw error;}finally{clearTimeout(timer);reader.releaseLock();}
}
async function readCoastalSnapshot(request){
 try{
  if(!await caches.has(COASTAL_INDEX))return null;const index=await caches.open(COASTAL_INDEX),pointer=await index.match(COASTAL_META);if(!pointer||pointer.status!==200)return null;
  const meta=await pointer.json();if(pointer.headers.get(SAVED_HEADER)!==meta?.saved_at)return null;if(meta?.schema_version!==1||typeof meta.cache!=='string'||!meta.cache.startsWith(COASTAL_PREFIX)||meta.cache.length>160||!/^[a-z0-9-]+$/.test(meta.cache)||!Number.isFinite(Date.parse(meta.saved_at))||Date.parse(meta.saved_at)>Date.now()||!Array.isArray(meta.products)||meta.products.length!==3)return null;
  const paths=new Set();let bytes=0;for(const product of meta.products){if(!product||!Object.hasOwn(COASTAL_LIMITS,product.path)||paths.has(product.path)||!Number.isFinite(Date.parse(product.generated_at))||Date.parse(product.generated_at)>Date.now()||!Number.isInteger(product.bytes)||product.bytes<1||product.bytes>COASTAL_LIMITS[product.path])return null;paths.add(product.path);bytes+=product.bytes;}if(bytes!==meta.bytes||bytes>32*1024*1024)return null;
  if(!await caches.has(meta.cache))return null;const cache=await caches.open(meta.cache),record=await cache.match(COASTAL_META);if(!record||record.status!==200||record.headers.get(SAVED_HEADER)!==meta.saved_at)return null;const complete=await record.json();if(JSON.stringify(complete)!==JSON.stringify(meta))return null;
  for(const product of meta.products){
   const stored=await cache.match(product.path);if(!stored||!storable(stored)||stored.headers.get(SAVED_HEADER)!==meta.saved_at||stored.headers.has(OFFLINE_HEADER)||!/^application\/json(?:\s*;|$)/i.test(stored.headers.get('content-type')||''))return null;
   const raw=await coastalBytes(stored,COASTAL_LIMITS[product.path]);if(raw.byteLength!==product.bytes)return null;const body=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(raw));if(!coastalProduct(product.path,body)||body.generatedAt!==product.generated_at)return null;
  }
  return await cache.match(request);
 }catch{return null;}
}
async function networkFirstCoastal(event){
 try{return await fetch(event.request);}catch(error){
  const saved=await coastalSnapshot(event.request);if(!saved)throw error;const response=offlineResponse(saved);
  event.waitUntil(tellClient(event.clientId,response.headers.get(OFFLINE_HEADER),event.request.url));return response;
 }
}

async function shell(event) {
  try {
    return await fetch(event.request);
  } catch (error) {
    const path = new URL(event.request.url).pathname;
    if (!/^\/(?:index\.html)?$/.test(path)) throw error;
    const saved = await (await caches.open(SHELL_CACHE)).match('/', {ignoreSearch: true});
    if (!saved) throw error;
    return saved;
  }
}

async function cacheFirst(request) {
  const cache = await caches.open(SHELL_CACHE);
  const hit = await cache.match(request, {ignoreSearch: true});
  if (hit) return hit;
  const response = await fetch(request);
  // A fingerprinted name never changes content, so it can join this build's cache.
  if (storable(response) && FINGERPRINTED.test(new URL(request.url).pathname)) cache.put(request, response.clone()).catch(() => {});
  return response;
}

async function tile(event) {
  try {
    return await fetch(event.request);
  } catch (error) {
    const saved = await newestSaved(event.request, encTileKey(event.request.url));
    if (!saved) throw error;
    return offlineResponse(saved);
  }
}

async function precached(request) {
  const hit = await (await caches.open(SHELL_CACHE)).match(request, {ignoreSearch: true});
  return hit || fetch(request);
}

function handleFetch(event, origin = self.location.origin) {
  const route = routeFor(event.request, origin);
  if (!route) return null;
  event.respondWith(route === 'coastal' ? networkFirstCoastal(event) : route === 'data' ? networkFirstData(event)
    : route === 'shell' ? shell(event)
    : route === 'tile' ? tile(event)
    : route === 'immutable' ? cacheFirst(event.request)
    : precached(event.request));
  return route;
}

/** The same-origin URLs to precache for a build, from its /precache.json. */
function precacheList(manifest) {
  if (!manifest || !Array.isArray(manifest.assets) || !Array.isArray(manifest.shells)) throw new Error('invalid precache manifest');
  return [...new Set([...manifest.shells, ...manifest.assets, ...(manifest.static || [])])]
    .filter(u => typeof u === 'string' && u.startsWith('/') && !u.startsWith('//'));
}

async function precacheShell() {
  const response = await fetch('/precache.json', {cache: 'no-cache'});
  if (!response.ok) throw new Error('precache manifest unavailable');
  const urls = precacheList(await response.json());
  // All or nothing (addAll): a partial shell would open offline and then fail.
  await (await caches.open(SHELL_CACHE)).addAll(urls.map(u => new Request(u, {cache: 'reload'})));
}

/** True when this build's shell is stored (addAll writes all of it or none). */
async function shellReady() {
  return !!(await (await caches.open(SHELL_CACHE)).match('/'));
}

async function install() {
  // Push must keep working even if the precache cannot be fetched right now, so a
  // failed precache does not fail the install; offline.js asks again on the next load.
  try { await precacheShell(); } catch (error) { console.warn('SkipperCast offline shell not stored:', error?.message || error); }
}

async function activate() {
  for (const name of await caches.keys()) if (name.startsWith(SHELL_PREFIX) && name !== SHELL_CACHE) await caches.delete(name);
  await self.clients.claim();
}

self.addEventListener('install', event => { event.waitUntil(install().then(() => self.skipWaiting())); });
self.addEventListener('activate', event => { event.waitUntil(activate()); });
self.addEventListener('fetch', event => { handleFetch(event); });
self.addEventListener('message', event => {
  const type = event.data?.type;
  if (type === 'skippercast-offline-status' && event.source) {
    event.source.postMessage({type: 'skippercast-offline', savedAt: servedFromCache.get(event.source.id) || null});
    event.waitUntil(shellReady().then(ready => ready || precacheShell().then(shellReady)).catch(() => false)
      .then(ready => event.source.postMessage({type: 'skippercast-shell', ready, build: BUILD})));
  }
});

// Notification delivery for trip alerts.
self.addEventListener('push',event=>{
  let data;try{data=event.data?.json();}catch{return;}
  if(!data?.eventId||!data.body)return;
  event.waitUntil(self.registration.showNotification(data.title||'SkipperCast',{body:data.body,tag:data.eventId,renotify:false,data:{url:'/#forecast'},icon:'/app-icon.svg'}));
});
self.addEventListener('notificationclick',event=>{
  event.notification.close();event.waitUntil((async()=>{const windows=await clients.matchAll({type:'window',includeUncontrolled:true});const target=windows.find(w=>new URL(w.url).origin===self.location.origin);if(target){await target.navigate('/#forecast');return target.focus();}return clients.openWindow('/#forecast');})());
});
