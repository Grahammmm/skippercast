// Trip planner, GPX export and the offline pack in the v2 app (FE-51, design
// § 6 and § 9). A wrapper, not a rewrite: v1's day planner (dist/export-ui.js
// over trip-export.js and gpx.js) renders into the app's trip dialog with the
// same draft (one per region in this browser), protected-area screen and GPX,
// so a plan exports the same bytes from either shell; v1's pack
// (dist/offline-pack.js over offline-core.js) saves the region and this app's
// shell and basemap tiles join it; the coastal snapshots are
// dist/coastal-offline-core.js unchanged. Every v1 module loads on first use.
//
// export-ui.js and the screen read v1's region store once, so the planner
// stays bound to the region it opened for; opening it after a region change
// reloads the page, as v1 does. Erasable syntax only (Node tests import this).
import {signal} from '@preact/signals';
import type {Source} from 'pmtiles';
import {loadManifest} from '../dist/seafloor-data.js';
import {BASEMAP_MANIFEST, basemapArchive} from './map/chart.ts';
import {shorelineURL} from './map/coastline.ts';
import {MARKS_SOURCE} from './map/layers.ts';
import {markSources} from './map/marks.ts';
import {NO_PLAN, fitCamera, rankedSpots, recheckPlan, screenRanked, type RankedPlan, type RankedScreen} from './map/ranked.ts';
import {camera, cameraParam, type Camera} from './map/stage.ts';
import {appView, navigate, region, withParams, type UrlKey} from './state.ts';

/** The v2 app's page key in a pack (dist/sw.js `V2_SHELL`). */
export const V2_SHELL = '/map';
export const TRIP_HASH = '#export';
const sessionStart = Date.now();

/** dist/export-ui.js `initExport`'s answer. */
export interface Planner {open(): void; add(id: string): void; review(id: string): void}
export const tripOpen = signal(false);
export const offlineOpen = signal(false);
/** The planner has drawn into the dialog; why it could not start, if it failed. */
export const tripReady = signal(false);
export const tripError = signal('');
/** The ids in this region's saved draft, for the account menu and the mark card. */
export const tripIds = signal<readonly string[]>([]);

/** trip-export.js `draftKey`, restated so the app's first paint loads no planner code (tests/test_trip.mjs pins it). */
export const draftKey = (id: string): string => `skippercast.export.v1.${id}`;
/** The draft's ids for `id` as v1 saved them (export-ui.js `persist`); the planner screens them again. */
export function savedIds(id: string | null, storage: Pick<Storage, 'getItem'> | undefined = globalThis.localStorage): string[] {
  try {
    const ids = id ? (JSON.parse(storage?.getItem(draftKey(id)) ?? 'null') as {ids?: unknown} | null)?.ids : null;
    return Array.isArray(ids) ? [...new Set(ids.filter((v): v is string => typeof v === 'string'))] : [];
  } catch { return []; }
}
const refreshIds = (): void => { tripIds.value = savedIds(region.peek()); };

/** The Leaflet calls the planner makes (`getSize`, `getBounds`), answered from the shared camera and the map's size. */
export function mapView(c: Camera | null, size: {width: number; height: number}) {
  const world = c ? 256 * 2 ** c.zoom : Infinity, mercator = (lat: number) => (1 - Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360)) / Math.PI) / 2;
  const latitude = (y: number) => 360 / Math.PI * Math.atan(Math.exp(Math.PI * (1 - 2 * y))) - 90;
  const lon = c?.longitude ?? NaN, y = c ? mercator(c.latitude) : NaN, w = size.width / world * 360, h = size.height / world;
  const b = {getWest: () => lon - w / 2, getEast: () => lon + w / 2, getNorth: () => latitude(y - h / 2), getSouth: () => latitude(y + h / 2)};
  return {
    getSize: () => ({x: c ? size.width : 0, y: c ? size.height : 0}),
    getBounds: () => ({...b, contains: ([la, lo]: [number, number]) => lo >= b.getWest() && lo <= b.getEast() && la >= b.getSouth() && la <= b.getNorth()}),
  };
}
const chartSize = () => { const r = document.querySelector('.app-chart')?.getBoundingClientRect(); return {width: r?.width ?? 0, height: r?.height ?? 0}; };

/** The v1 modules' option bags, which their JavaScript types too narrowly to pass a callback with arguments. */
type Loose<T> = (options: Record<string, unknown>) => T;
const plain = (): string => location.href.split('#')[0]!;
const go = (patch: Partial<Record<UrlKey, string | null>>): void => { navigate(withParams(plain(), patch)); };
export const openTrip = (): void => { if (location.hash !== TRIP_HASH) navigate(plain() + TRIP_HASH); else tripOpen.value = true; };
export const closeTrip = (): void => { if (location.hash === TRIP_HASH) navigate(plain(), {replace: true}); tripOpen.value = false; refreshIds(); };

const json = async (path: string): Promise<unknown> => {
  const response = await fetch(path, {signal: AbortSignal.timeout(20000)});
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return response.json();
};
/** v1's region store set to `id` (the planner, the screen and the pack read it). */
async function v1Region(id: string) {
  const regions = await import('../dist/region.js');
  regions.setRegion(await json(`regions/${encodeURIComponent(id)}/region.json`));
  return regions;
}

let planner: {region: string; ready: Promise<Planner | null>} | null = null;
/** The planner for the current region, started on first use; null without a region, after a failure, or while a region change reloads. */
export async function loadPlanner(): Promise<Planner | null> {
  const id = region.peek();
  if (!id) return null;
  if (planner && planner.region !== id) { location.reload(); return null; }
  tripError.value = '';
  planner ??= {region: id, ready: startPlanner(id).then(api => { tripReady.value = true; return api; }, (error: Error) => {
    tripError.value = `The trip planner could not load (${error.message}). Try again when you are online.`;
    planner = null;
    return null;
  })};
  return planner.ready;
}

async function startPlanner(id: string): Promise<Planner> {
  const regions = await v1Region(id);
  // protected-areas.js builds its live query from the region store when it loads, so it loads after setRegion.
  const [{initProtectedAreas}, v1] = await Promise.all([import('../dist/protected-areas.js'), import('../dist/export-ui.js')]);
  const initExport = v1.initExport as unknown as Loose<Planner>;
  const path = regions.assetURL('atlas');
  const atlas = (path ? await json(path) : {targets: [], areas: [], drifts: []}) as {targets: {id: string}[]};
  const screen = await initProtectedAreas(null, () => {});
  // The ranked pins are screened by the planner's own screen, as v1's are (#495).
  rankedScreen = screen as RankedScreen;
  drawRanked();
  const api = initExport({atlas, screen, map: {getSize: () => mapView(camera.peek(), chartSize()).getSize(), getBounds: () => mapView(camera.peek(), chartSize()).getBounds()},
    getVisible: () => { const ids = new Set((markSources[MARKS_SOURCE]?.value.features ?? []).map(f => f.properties.id)); return atlas.targets.filter(t => ids.has(t.id)); },
    navigation: {showView(name: string) {
      if (name === 'export') { openTrip(); return; }
      closeTrip();
      if (name === 'forecast') go({view: 'conditions'}); else if (appView.peek() !== 'coast') go({view: null});
    }},
    onConditions: ({date}: {date: string}) => { closeTrip(); go({view: 'conditions', day: date}); }});
  void screen.refresh();
  return api;
}

export async function addToTrip(id: string): Promise<void> { (await loadPlanner())?.add(id); refreshIds(); }
export async function reviewTrip(id: string): Promise<void> { (await loadPlanner())?.review(id); refreshIds(); }

/** "Show ranked spots on map" moves the Chart to the ranked set's extent (web/map/ranked.ts draws their pins). */
export {fitCamera};

// The ranked plan the Chart draws (#495): the planner's latest event, screened as v1's
// dist/trip-ranking-layer.js screens it; a publication found changed is held until verified again.
let ranked: RankedPlan = NO_PLAN, rankedScreen: RankedScreen | null = null;
const rejected = new Map<string, number>();
const drawRanked = (): void => { rankedSpots.value = screenRanked(ranked, rankedScreen, rejected, region.peek()); };
/** Each minute, as v1 does: the screen's age and the publication's expiry again, and the manifest still the plan's. */
async function recheckRanked(): Promise<void> {
  drawRanked();
  const current = ranked, hash = current.publication?.export_sha256;
  if (!current.targets.length || !hash) return;
  const gate = await loadManifest(current.publication?.region);
  if (ranked !== current) return;
  const next = recheckPlan(current, gate, rejected, Date.now());
  if (next !== current) { ranked = next; drawRanked(); }
}

// The offline pack.
interface Extras {
  store(url: string, key?: string, init?: RequestInit, misses?: string[]): Promise<boolean>;
  put(key: string, body: ArrayBuffer, headers: Headers): Promise<void>;
  signal: AbortSignal;
  progress(phase: string, done: number, total: number): void;
}

/** A PMTiles source that keeps each byte range it reads under offline-core.js `basemapRangeKey`. */
export function rangeRecorder(url: string, put: Extras['put'], signal: AbortSignal, key: (url: string, range: string) => string | null): Source {
  return {
    getKey: () => url,
    async getBytes(offset, length, s, etag) {
      const range = `bytes=${offset}-${offset + length - 1}`, at = key(url, range);
      const response = await fetch(url, {headers: {range}, credentials: 'omit', signal: s ?? signal});
      // Only the exact range, live: a whole archive or a saved answer is never stored.
      if (!at || response.status !== 206 || response.headers.has('X-SC-Offline')) { void response.body?.cancel(); throw new Error(`Basemap range ${range}: HTTP ${response.status}`); }
      const data = await response.arrayBuffer(), tag = response.headers.get('ETag');
      if (data.byteLength > length || (etag && tag && tag !== etag)) throw new Error('The basemap archive changed while saving.');
      await put(at, data, response.headers);
      return {data, etag: tag && !tag.startsWith('W/') ? tag : undefined};
    },
  };
}

/** savePack's `more`: this app's page and files (precache.json `v2`), the basemap manifest, shoreline and tiles. */
async function v2Pack({store, put, signal, progress}: Extras, id: string, bounds: number[]) {
  const page = location.href, origin = location.origin, misses: string[] = [];
  const list = await fetch('/precache.json', {cache: 'no-cache', signal}).then(r => r.ok ? r.json() : null, () => null) as {build?: string; v2?: {assets?: unknown[]; static?: unknown[]}} | null;
  const hashed = [...list?.v2?.assets ?? [], ...list?.v2?.static ?? []].filter((p): p is string => typeof p === 'string' && /^\/(?!\/)/.test(p));
  const files: [string, string, RequestInit][] = [[`${origin}${V2_SHELL}?ui=v2`, origin + V2_SHELL, {}],
    ...[BASEMAP_MANIFEST, shorelineURL(id)].map((p): [string, string, RequestInit] => [new URL(p, page).href, new URL(p, page).href, {}]),
    ...hashed.map((p): [string, string, RequestInit] => [origin + p, origin + p, {cache: 'default'}])];
  let done = 0;
  for (const [url, key, init] of files) { await store(url, key, init, misses); progress('shell', ++done, files.length); }
  const [archive, {basemapRangeKey, planBasemap}] = await Promise.all([basemapArchive((...a) => fetch(...a), page), import('../dist/offline-core.js')]);
  const plan = planBasemap(bounds) as {tiles: {z: number; x: number; y: number}[]; minZoom: number; maxZoom: number | null};
  let saved = 0, tile = 0;
  if (archive) {
    const {PMTiles} = await import('./map/maplibre.js');
    const reader = new PMTiles(rangeRecorder(archive, put, signal, basemapRangeKey));
    for (const t of plan.tiles) {
      if (signal.aborted) break;
      try { if (await reader.getZxy(t.z, t.x, t.y, signal)) saved++; } catch (error) { if (signal.aborted) throw error; misses.push(`basemap ${t.z}/${t.x}/${t.y}`); }
      progress('basemap', ++tile, plan.tiles.length);
    }
  }
  return {build: list?.build ?? null, shell: {saved: files.length - misses.filter(m => !m.startsWith('basemap')).length, requested: files.length},
    basemap: {archive: archive ? new URL(archive).pathname : null, saved, planned: plan.tiles.length, min_zoom: plan.minZoom, max_zoom: plan.maxZoom}, missing: misses.slice(0, 50)};
}

export interface PackMeta {
  region_id: string; region_name: string; saved_at: string; bytes: number; missing: string[];
  tiles: {saved: number; planned: number; min_zoom: number; max_zoom: number | null};
  v2?: {basemap: {saved: number; planned: number}; shell: {saved: number; requested: number}};
}
export type Progress = {phase: string; done: number; total: number; bytes: number};
export async function listPacks(): Promise<{cache: string; meta: PackMeta}[]> {
  if (!('caches' in globalThis)) return [];
  return (await import('../dist/offline-pack.js')).listPacks() as Promise<{cache: string; meta: PackMeta}[]>;
}
/** Save `id` for offline: v1's pack with this app added; then the worker is registered so the pack answers offline. */
export async function savePack(id: string, signal: AbortSignal, progress: (p: Progress) => void): Promise<PackMeta> {
  const regions = await v1Region(id), save = (await import('../dist/offline-pack.js')).savePack as unknown as Loose<Promise<PackMeta>>;
  const meta = await save({signal, progress, sessionStart, more: (extras: Extras) => v2Pack(extras, id, regions.getRegion().bounds)});
  registerOffline();
  return meta;
}

const coastal = () => import('../dist/coastal-offline-core.js');
const coastalOptions = (signal?: AbortSignal) => ({origin: location.origin, caches: globalThis.caches, signal});
export const readCoastal = async () => (await coastal()).readCoastalSnapshot(coastalOptions());
export const canSaveCoastal = async () => (await coastal()).canMutateCoastalSnapshot({caches: globalThis.caches});
export async function saveCoastal(signal: AbortSignal) { const meta = await (await coastal()).saveCoastalSnapshot(coastalOptions(signal)); registerOffline(); return meta; }
export const deleteCoastal = async () => (await coastal()).deleteCoastalSnapshot(coastalOptions());

/** v2 registers v1's /sw.js only once something is saved, so a visitor who saves nothing never stores its precache. */
export function registerOffline(): void {
  if (!('serviceWorker' in navigator) || !isSecureContext) return;
  navigator.serviceWorker.register('/sw.js').catch((error: Error) => console.warn('SkipperCast service worker not registered:', error.message));
}

/** From main.tsx: the dialog follows `#export`, the ranked set draws on and moves the Chart, and a saved pack keeps the worker current. */
export function startTrip(): void {
  const sync = () => { tripOpen.value = location.hash === TRIP_HASH; if (tripOpen.peek()) void loadPlanner(); };
  addEventListener('hashchange', sync);
  addEventListener('storage', refreshIds);
  sync();
  region.subscribe(refreshIds);
  document.addEventListener('skippercast:trip-ranked', event => {
    const detail = (event as CustomEvent<RankedPlan | null>).detail;
    ranked = detail?.targets ? detail : NO_PLAN;
    drawRanked();
    const at = detail?.fit ? fitCamera(ranked.targets) : null;
    if (at) go({view: cameraParam(at)});
  });
  document.addEventListener('skippercast:boundaries', drawRanked);
  region.subscribe(drawRanked);
  setInterval(() => { void recheckRanked(); }, 60000);
  void globalThis.caches?.keys().then(names => { if (names.some(n => n.startsWith('sc-pack-') || n.startsWith('sc-coastal-'))) registerOffline(); }, () => {});
}
