// "Save for offline": stores the current region's data, rules, forecast and
// NOAA chart tiles in Cache Storage (sc-pack-<region>-<time>), where dist/sw.js
// answers from them when the network is unavailable. Nothing goes to
// localStorage. Every stored response carries its saved-at time, and the
// service worker marks anything it answers from here as offline data.
import {getRegion, getRegionDirectory, localContext} from './region.js';
import {chartLayers} from './chart-map.js';
import {track} from '../web/telemetry.ts';
import {PACK_PREFIX, PACK_META, SHARED_FILES, planTiles, tileURL, tileKey, packRequests, stampedHeaders, formatBytes, relativeTime} from './offline-core.js';

const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const CONCURRENCY = 4;

/** Saved packs, newest first: [{cache, meta}]. */
export async function listPacks() {
  if (!('caches' in self)) return [];
  const out = [];
  for (const name of (await caches.keys()).filter(n => n.startsWith(PACK_PREFIX))) {
    const hit = await (await caches.open(name)).match(PACK_META);
    const meta = hit ? await hit.json().catch(() => null) : null;
    if (meta?.schema_version === 1) out.push({cache: name, meta});
  }
  return out.sort((a, b) => b.meta.saved_at.localeCompare(a.meta.saved_at));
}

async function regionConfig(id) {
  let directory = getRegionDirectory();
  if (!directory?.length) directory = (await (await fetch('regions/index.json')).json()).regions;
  return directory.find(r => r.id === id)?.config || null;
}

/** The Conditions view's own requests: forecast models, tides, alerts. */
async function conditionsRequests(region) {
  try {
    const {MODELS, modelURL, tideURL} = await import('./marine-data.js');
    const contexts = region.contexts ? Object.values(region.contexts) : [localContext()];
    const now = Date.now(), urls = [];
    for (const m of MODELS) urls.push(modelURL(m), m.meta);
    for (const ctx of contexts) {
      urls.push(tideURL(now, '6', ctx.stations.tide), tideURL(now, 'hilo', ctx.stations.tide));
      urls.push(`https://api.weather.gov/alerts/active?zone=${ctx.marine_zones.coastal}`, `https://api.weather.gov/alerts/active?zone=${ctx.marine_zones.offshore}`);
    }
    return urls;
  } catch { return []; }
}

async function pool(items, worker, signal) {
  let next = 0;
  await Promise.all(Array.from({length: Math.min(CONCURRENCY, items.length)}, async () => {
    while (next < items.length) { if (signal.aborted) return; await worker(items[next++]); }
  }));
}

/**
 * Save the current region. `progress({phase, done, total, bytes})` reports as
 * it goes; `signal` cancels (the partial pack is deleted). Resolves to meta.
 */
export async function savePack({signal, progress = () => {}, sessionStart = 0} = {}) {
  const region = getRegion(), origin = location.origin;
  const name = `${PACK_PREFIX}${region.id}-${Date.now()}`, cache = await caches.open(name);
  const started = new Date();
  let bytes = 0;
  const missing = [];
  async function store(url, key = url, init = {}, misses = missing) {
    try {
      const response = await fetch(url, {cache: 'no-cache', credentials: 'omit', signal, ...init});
      // An answer the service worker served from an older save is not new data:
      // storing it would give old data a new saved time.
      if (!response.ok || response.headers.has('X-SC-Offline')) { misses.push(url); return false; }
      const body = await response.blob();
      bytes += body.size;
      await cache.put(key, new Response(body, {status: 200, headers: stampedHeaders(response.headers)}));
      return true;
    } catch (error) {
      if (signal.aborted) throw error;
      misses.push(url); return false;
    }
  }
  try {
    try { await navigator.storage?.persist?.(); } catch {}
    const config = await regionConfig(region.id).catch(() => null) || `regions/${region.id}/region.json`;
    const configURL = new URL(config, origin + '/').href;
    const urls = packRequests({origin, region, config, shared: SHARED_FILES, extra: await conditionsRequests(region)});
    let done = 0;
    progress({phase: 'files', done, total: urls.length, bytes});
    await pool(urls, async url => { await store(url); progress({phase: 'files', done: ++done, total: urls.length, bytes}); }, signal);
    // Without the region's own config the pack cannot open offline: keep the older pack instead.
    if (missing.includes(configURL)) throw new Error('the region could not be downloaded. Check your connection; saved regions are unchanged.');
    // Also keep what this page has already loaded since it opened (exact forecast,
    // tide and layer requests), copied from the service worker's recent-data cache.
    let copied = 0;
    if (await caches.has('sc-data')) {
      const recent = await caches.open('sc-data');
      for (const request of await recent.keys()) {
        if (signal.aborted) break;
        if (await cache.match(request)) continue;
        const hit = await recent.match(request);
        const at = Date.parse(hit?.headers.get('X-SC-Saved-At') || '');
        if (!hit || !(at >= sessionStart)) continue;
        const body = await hit.blob();
        bytes += body.size; copied++;
        await cache.put(request, new Response(body, {status: hit.status, headers: hit.headers}));
      }
    }
    const layers = chartLayers(document.getElementById('base-map')?.value === 'nautical' ? 'nautical' : 'fishing');
    const plan = planTiles(region.bounds);
    let tilesSaved = 0, tilesDone = 0;
    const tileMisses = [];
    progress({phase: 'tiles', done: 0, total: plan.tiles.length, bytes});
    await pool(plan.tiles, async t => {
      if (await store(tileURL(t, layers), tileKey(layers, t.z, t.x, t.y), {cache: 'default', mode: 'cors'}, tileMisses)) tilesSaved++;
      progress({phase: 'tiles', done: ++tilesDone, total: plan.tiles.length, bytes});
    }, signal);
    if (signal.aborted) throw new DOMException('Cancelled', 'AbortError');
    const meta = {
      schema_version: 1, region_id: region.id, region_name: region.name, saved_at: started.toISOString(), bytes,
      files: {saved: urls.length - missing.length, requested: urls.length, from_session: copied},
      missing: missing.slice(0, 50),
      tiles: {saved: tilesSaved, planned: plan.tiles.length, min_zoom: plan.minZoom, max_zoom: plan.maxZoom, requested_max_zoom: plan.requestedMaxZoom, layers},
    };
    await cache.put(PACK_META, new Response(JSON.stringify(meta), {headers: {'Content-Type': 'application/json'}}));
    // The new pack is complete: older packs of the same region go.
    for (const old of (await caches.keys()).filter(n => n !== name && n.startsWith(`${PACK_PREFIX}${region.id}-`))) await caches.delete(old);
    track('offline_saved', {region: region.id});
    return meta;
  } catch (error) {
    await caches.delete(name);
    throw error;
  }
}

function packRow({cache, meta}, now) {
  const when = relativeTime(meta.saved_at, now) || '';
  const tiles = meta.tiles.saved ? `${meta.tiles.saved}${meta.tiles.saved < meta.tiles.planned ? ` of ${meta.tiles.planned}` : ''} chart tiles (zoom ${meta.tiles.min_zoom}–${meta.tiles.max_zoom})` : 'no chart tiles';
  const gaps = meta.missing?.length ? ` · ${meta.missing.length} items could not be saved` : '';
  return `<li><div><strong>${esc(meta.region_name)}</strong><span class="small">Saved ${esc(when)} · <time datetime="${esc(meta.saved_at)}">${esc(new Date(meta.saved_at).toLocaleString())}</time> · ${esc(formatBytes(meta.bytes))} · ${esc(tiles)}${esc(gaps)}</span></div><button type="button" data-delete-pack="${esc(cache)}">Delete</button></li>`;
}

/** Render the "Offline trip pack" card into `host`. */
export function initOfflinePack(host, {sessionStart = 0} = {}) {
  if (!host) return;
  if (!('caches' in self) || !('serviceWorker' in navigator)) {
    host.innerHTML = '<p>This browser cannot save SkipperCast for offline use.</p>';
    return;
  }
  host.innerHTML = `<p>Save this region before you lose signal: the map layers, fishing rules, protected areas, the latest forecast and NOAA chart tiles (zoom 8–12). Saved data shows its saved time when you are offline.</p>
    <div class="offline-pack-actions"><button type="button" class="primary" id="offline-pack-save">Save this region for offline</button><button type="button" id="offline-pack-cancel" hidden>Cancel</button></div>
    <div id="offline-pack-progress" hidden><progress max="1" value="0"></progress><p class="small" role="status" aria-live="polite"></p></div>
    <h3 class="offline-pack-heading">Saved regions</h3><ul id="offline-pack-list" class="offline-pack-list"></ul>
    <p class="small">Street map tiles are not saved; OpenStreetMap does not allow bulk downloads. Planning aid · not a navigation chart.</p>`;
  const save = host.querySelector('#offline-pack-save'), cancel = host.querySelector('#offline-pack-cancel');
  const box = host.querySelector('#offline-pack-progress'), bar = box.querySelector('progress'), status = box.querySelector('p');
  const list = host.querySelector('#offline-pack-list');
  let controller = null;
  async function refresh() {
    save.textContent = `Save ${getRegion().name} for offline`;
    const packs = await listPacks().catch(() => []);
    const now = Date.now();
    list.innerHTML = packs.length ? packs.map(p => packRow(p, now)).join('') : '<li class="small">Nothing saved on this device yet.</li>';
  }
  list.addEventListener('click', async event => {
    const name = event.target.closest('[data-delete-pack]')?.dataset.deletePack;
    if (!name) return;
    await caches.delete(name);
    status.textContent = 'Saved region deleted.'; box.hidden = false; bar.hidden = true;
    refresh();
  });
  cancel.addEventListener('click', () => controller?.abort());
  save.addEventListener('click', async () => {
    if (controller) return;
    if (!navigator.onLine) { box.hidden = false; bar.hidden = true; status.textContent = 'You are offline. Connect to save this region; saved regions are unchanged.'; return; }
    controller = new AbortController();
    save.disabled = true; cancel.hidden = false; box.hidden = false; bar.hidden = false; bar.value = 0;
    const label = {files: 'Saving data and rules', tiles: 'Saving chart tiles'};
    try {
      const meta = await savePack({signal: controller.signal, sessionStart, progress: ({phase, done, total, bytes}) => {
        bar.max = Math.max(1, total); bar.value = done;
        status.textContent = `${label[phase]} · ${done} of ${total} · ${formatBytes(bytes)}`;
      }});
      const gaps = meta.missing.length ? ` ${meta.missing.length} items could not be saved; they will be missing offline.` : '';
      const capped = meta.tiles.max_zoom !== meta.tiles.requested_max_zoom ? ` Chart tiles stop at zoom ${meta.tiles.max_zoom} to stay under ${meta.tiles.planned} tiles.` : '';
      status.textContent = `Saved ${meta.region_name} · ${formatBytes(meta.bytes)}.${gaps}${capped}`;
    } catch (error) {
      status.textContent = error?.name === 'AbortError' ? 'Cancelled. Nothing new was saved.' : `Could not save: ${error?.message || error}`;
    } finally {
      controller = null; save.disabled = false; cancel.hidden = true; bar.hidden = true;
      refresh();
    }
  });
  host.closest('details')?.addEventListener('toggle', refresh);
  refresh();
}
