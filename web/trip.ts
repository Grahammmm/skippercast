// Trip planner, GPX export and the offline pack in the v2 app (FE-51, design
// § 6 and § 9). The day planner is v2's (web/planner.ts, rendered by
// web/app/Planner.tsx, #602) over the shared export contract (trip-export.js
// and gpx.js), with v1's draft (one per region in this browser), protected-area
// screen and GPX bytes; v1's pack (dist/offline-pack.js over offline-core.js)
// saves the region and this app's shell and basemap tiles join it; the coastal
// snapshots are dist/coastal-offline-core.js unchanged. Each loads on first use.
//
// SC1407-10: this module is what the first screen imports (the signals, the #export dialog, the draft's ids and
// the one protected-area screen). The planner, the pack, the basemap ranges and the coastal snapshots are
// web/trip-runtime.ts, loaded by this module's one dynamic import on first actual use; a call made before it
// arrives waits for it. The exports keep their names and signatures, so no importer changes.
//
// The protected-area screen and the pack read v1's region store once, so the
// planner stays bound to the region it opened for; opening it after a region
// change reloads the page, as v1 does. Erasable syntax only (Node tests import this).
import {signal} from '@preact/signals';
import {browserStorage} from '../dist/browser-storage.js';
import {formatBytes} from '../dist/offline-core.js';
import type {RankedPlan, RankedScreen} from './map/ranked.ts';
import {sharedFetch} from './shared-fetch.ts';
import {cancelWaypointPlacement} from './waypoint-placement.ts';
import {navigate, region, withParams, type UrlKey} from './state.ts';
import type {TripRuntime} from './trip-runtime.ts';

/** The v2 app's page key in a pack (dist/sw.js `V2_SHELL`). */
export const V2_SHELL = '/map';
export const TRIP_HASH = '#export';
// When this module first ran, as before the split: a pack copies the responses browsed since then.
const sessionStart = Date.now();

/** The planner's actions the app calls (web/planner.ts `createPlanner`). */
export interface Planner {open(): void; add(id: string): void; review(id: string): void; addPlace(p: {id: string; name: string; latitude: number; longitude: number; shore?: boolean}): string | null}
type PlannerModel = import('./planner.ts').Planner;
type PlannerView = typeof import('./app/Planner.tsx').Planner;
/** The started planner and its view, which the trip dialog renders; null until first use. */
export const plannerView = signal<{model: PlannerModel; View: PlannerView} | null>(null);
export const tripOpen = signal(false);
export const offlineOpen = signal(false);
/** The planner has drawn into the dialog; why it could not start, if it failed. */
export const tripReady = signal(false);
export const tripError = signal('');
/** The ids in this region's saved draft, for the account menu and the mark card. */
export const tripIds = signal<readonly string[]>([]);

/** trip-export.js `draftKey`, restated so the app's first paint loads no planner code (tests/test_trip.mjs pins it). */
export const draftKey = (id: string): string => `skippercast.export.v1.${id}`;
/** The draft's ids for `id` as the planner saved them (web/planner.ts `persist`); the planner screens them again. */
export function savedIds(id: string | null, storage: Pick<Storage, 'getItem'> | null | undefined = browserStorage()): string[] {
  try {
    const ids = id ? (JSON.parse(storage?.getItem(draftKey(id)) ?? 'null') as {ids?: unknown} | null)?.ids : null;
    return Array.isArray(ids) ? [...new Set(ids.filter((v): v is string => typeof v === 'string'))] : [];
  } catch { return []; }
}
const refreshIds = (): void => { tripIds.value = savedIds(region.peek()); };

const plain = (): string => location.href.split('#')[0]!;
const go = (patch: Partial<Record<UrlKey, string | null>>): void => { navigate(withParams(plain(), patch)); };
export const openTrip = (): void => { cancelWaypointPlacement(); if (location.hash !== TRIP_HASH) navigate(plain() + TRIP_HASH); else tripOpen.value = true; };
export const closeTrip = (): void => { if (location.hash === TRIP_HASH) navigate(plain(), {replace: true}); tripOpen.value = false; refreshIds(); };

// Committed files are read through web/shared-fetch.ts, so a file the startup already read (the
// region, the protected-area snapshot) is not requested twice.
const json = async (path: string): Promise<unknown> => {
  const response = await sharedFetch(path, {signal: AbortSignal.timeout(20000)});
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return response.json();
};
/** dist/forecast.js `fetchJSON`'s contract (a body's `error` is a failure) over the shared read. */
const screenJSON = async (path: string): Promise<unknown> => {
  const body = await json(path) as {error?: unknown; reason?: unknown} | null;
  if (body?.error) throw new Error(String(body.reason || 'Provider error'));
  return body;
};
/** v1's region store set to `id` (the planner, the screen and the pack read it). */
async function v1Region(id: string) {
  const regions = await import('../dist/region.js');
  regions.setRegion(await json(`regions/${encodeURIComponent(id)}/region.json`));
  return regions;
}

/** SCJ-2b: the one protected-area screen the planner and the brief share, for one region, loaded on first use: dist/protected-areas.js `initProtectedAreas`, web/map/ranked.ts `RankedScreen` plus `refresh`. */
export type PlannerScreen = RankedScreen & {refresh(): Promise<unknown>};
export type ProtectedScreen = {state: 'idle' | 'loading'} | {state: 'failed'} | {state: 'loaded'; region: string; screen: PlannerScreen};
export const protectedScreen = signal<ProtectedScreen>({state: 'idle'});
let screenInits: Promise<unknown> = Promise.resolve(), screenElsewhere = false, screenLoad: {region: string; done: Promise<ProtectedScreen>} | null = null;
/** Today's screen for `id`, one region-store change at a time. protected-areas.js builds its live ds582 query from the region it first loads for, so another region's (other bounds) fails closed. */
function defaultInit(id: string): Promise<PlannerScreen> {
  const next = screenInits.then(async () => {
    const regions = await v1Region(id), {initProtectedAreas, MPA_QUERY} = await import('../dist/protected-areas.js'), r = regions.getRegion() as {id?: string; mpa?: {bounds?: number[]}};
    if (r.id !== id || new URL(MPA_QUERY).searchParams.get('geometry') !== r.mpa?.bounds?.join(',')) { screenElsewhere = true; throw new Error('protected-area check bound to another region'); }
    return await initProtectedAreas(null, () => {}, screenJSON) as PlannerScreen;
  });
  screenInits = next.catch(() => {}); return next;
}
/** The region's screen, loaded once (a different region starts again at `loading`); a failure is `failed`, never a throw, and a later call tries again. */
export function loadProtectedScreen(id: string | null = region.peek(), init: (id: string) => Promise<PlannerScreen> = defaultInit): Promise<ProtectedScreen> {
  if (!id) return Promise.resolve({state: 'idle'});
  if (screenLoad?.region === id) return screenLoad.done;
  protectedScreen.value = {state: 'loading'};
  const mine: {region: string; done: Promise<ProtectedScreen>} = {region: id, done: Promise.resolve(id).then(init).then(screen => { void screen.refresh(); return {state: 'loaded', region: id, screen} as const; }, () => ({state: 'failed'} as const))
    .then((next: ProtectedScreen) => { if (screenLoad === mine) { protectedScreen.value = next; if (next.state === 'failed') screenLoad = null; } return next; })};
  screenLoad = mine;
  return mine.done;
}

/** v2 registers v1's /sw.js only once something is saved, so a visitor who saves nothing never stores its precache. */
export function registerOffline(): void {
  if (!('serviceWorker' in navigator) || !isSecureContext) return;
  navigator.serviceWorker.register('/sw.js').catch((error: Error) => console.warn('SkipperCast service worker not registered:', error.message));
}

// The implementation, one instance per page over this module's state; a failed import or start leaves the slot
// empty so the dialog's Retry imports again. `runtimeSource.load` is the only import of it (tests delay or fail it).
type RuntimeModule = typeof import('./trip-runtime.ts');
export const runtimeSource = {load: (): Promise<RuntimeModule> => import('./trip-runtime.ts')};
let runtimeLoad: Promise<TripRuntime> | null = null, runtimeNow: TripRuntime | null = null;
function runtime(): Promise<TripRuntime> {
  if (runtimeNow) return Promise.resolve(runtimeNow);
  runtimeLoad ??= Promise.resolve().then(() => runtimeSource.load()).then(m => runtimeNow ??= m.createTripRuntime({
    sessionStart, loadProtectedScreen: id => loadProtectedScreen(id), screenElsewhere: () => screenElsewhere, v1Region, json, openTrip, closeTrip, go, registerOffline,
  })).catch((error: unknown) => { runtimeLoad = null; throw error; });
  return runtimeLoad;
}

let planner: {region: string; ready: Promise<Planner | null>} | null = null;
/** The planner for the current region, started on first use; null without a region, after a failure, or while a region change reloads. */
export async function loadPlanner(): Promise<Planner | null> {
  const id = region.peek();
  if (!id) return null;
  if (planner && planner.region !== id) { location.reload(); return null; }
  tripError.value = '';
  if (planner) return planner.ready;
  // Started for `id` only: a region changed while the implementation arrives or the planner starts publishes nothing.
  const mine: {region: string; ready: Promise<Planner | null>} = {region: id, ready: runtime().then(async rt => {
    if (region.peek() !== id) return null;
    const started = await rt.startPlanner(id);
    if (region.peek() !== id) { started.model.dispose(); return null; }
    plannerView.value = started;
    tripReady.value = true;
    return started.model;
  }).then(api => { if (!api && planner === mine) planner = null; return api; }, (error: Error) => {
    if (planner === mine) planner = null;
    if (region.peek() === id) tripError.value = `The trip planner could not load (${error.message}). Try again when you are online.`;
    return null;
  })};
  planner = mine;
  return mine.ready;
}

/** Run `act` once on the planner for the region current at the call; a region changed meanwhile adds nothing. */
async function withPlanner(act: (m: Planner) => void): Promise<void> {
  const id = region.peek(), m = await loadPlanner();
  if (m && region.peek() === id) act(m);
  refreshIds();
}
export async function addToTrip(id: string): Promise<void> { await withPlanner(m => m.add(id)); }
export async function reviewTrip(id: string): Promise<void> { await withPlanner(m => m.review(id)); }
/** SCJ-1: a recommended habitat place joins the trip, or opens it for export, as a user waypoint whose id is planner.ts `addPlace`'s (`habitat:reef:r1` → `user:habitat-reef-r1`). */
export const placeTripId = (id: string): string => `user:habitat-${id.replace(/^habitat:/, '').replace(/[^a-zA-Z0-9-]/g, '-').slice(0, 72)}`;
export async function addPlaceToTrip(p: Parameters<Planner['addPlace']>[0]): Promise<void> { const place = {...p}; await withPlanner(m => { m.addPlace(place); }); }
export async function reviewPlace(p: Parameters<Planner['addPlace']>[0]): Promise<void> { const place = {...p}; await withPlanner(m => { const id = m.addPlace(place); if (id) m.review(id); }); }

// The offline pack, implemented in web/trip-runtime.ts; each call waits for it.
export interface PackMeta {
  region_id: string; region_name: string; saved_at: string; bytes: number; missing: string[];
  tiles: {saved: number; planned: number; min_zoom: number; max_zoom: number | null};
  v2?: {basemap: {saved: number; planned: number}; shell: {saved: number; requested: number}; /** URLs (and basemap tiles) the v2 phase could not save. */ missing?: string[]};
  /** Cache-only inventory, recomputed whenever the offline dialog opens. */
  legal?: Awaited<ReturnType<typeof import('../dist/legal-pack.js').inspectLegalPack>>;
  /** The ocean phase's record (D9), additive: absent from packs saved before it. */
  ocean?: Awaited<ReturnType<RuntimeModule['oceanPhase']>>;
  /** ISO time of the last hour both the saved wind and wave models cover; additive, absent from older packs or when a model was not saved. */
  forecast_end?: string;
}
export type Progress = {phase: string; done: number; total: number; bytes: number};
export async function listPacks(): Promise<{cache: string; meta: PackMeta}[]> {
  if (!('caches' in globalThis)) return [];
  return (await runtime()).listPacks();
}
/** Save `id` for offline: v1's pack with this app added; then the worker is registered so the pack answers offline. A save cancelled before the implementation arrives writes nothing. */
export async function savePack(id: string, signal: AbortSignal, progress: (p: Progress) => void): Promise<PackMeta> {
  signal.throwIfAborted();
  const rt = await runtime();
  signal.throwIfAborted();
  return rt.savePack(id, signal, progress);
}
export const readCoastal = async () => (await runtime()).readCoastal();
export const canSaveCoastal = async () => (await runtime()).canSaveCoastal();
export async function saveCoastal(signal: AbortSignal) { signal.throwIfAborted(); const rt = await runtime(); signal.throwIfAborted(); return rt.saveCoastal(signal); }
export const deleteCoastal = async () => (await runtime()).deleteCoastal();

/** What the browser said about keeping saved packs: agreed or refused our request, already keeps them, or has no storage API. */
export type Keep = 'agreed' | 'refused' | 'already' | 'unavailable';
type StorageNav = {storage?: {persist?: () => Promise<boolean>; persisted?: () => Promise<boolean>; estimate?: () => Promise<{usage?: number; quota?: number}>}};
/** Ask the browser to keep saved packs, after a save only: no request when it already does or has no way to say. */
export async function keepSaved(nav: StorageNav = globalThis.navigator as StorageNav): Promise<Keep> {
  try {
    const storage = nav?.storage;
    if (typeof storage?.persist !== 'function' || typeof storage.persisted !== 'function') return 'unavailable';
    if (await storage.persisted()) return 'already';
    return (await storage.persist()) ? 'agreed' : 'refused';
  } catch { return 'unavailable'; }
}
/** The browser's estimate of the space used and available, or null when it gives none. */
export async function storageLine(nav: StorageNav = globalThis.navigator as StorageNav): Promise<{used: number; quota: number} | null> {
  try {
    const e = typeof nav?.storage?.estimate === 'function' ? await nav.storage.estimate() : null;
    return e && Number.isFinite(e.usage) && Number.isFinite(e.quota) ? {used: e.usage as number, quota: e.quota as number} : null;
  } catch { return null; }
}
/** The list's one line from the browser's estimate. */
export const estimateWords = (r: {used: number; quota: number}): string => `Browser's estimate: ${formatBytes(r.used)} used of ${formatBytes(r.quota)} available`;
/** Run a save; only once it has resolved, ask the browser to keep it. A save that throws or is cancelled makes no request. */
export async function savePackKept(save: () => Promise<PackMeta>, nav?: StorageNav): Promise<{meta: PackMeta; keep: Keep}> {
  const meta = await save();
  return {meta, keep: await keepSaved(nav)};
}
/** The dialog's words for the browser's answer; nothing when it has none. */
export const KEEP_WORDS: Readonly<Record<Keep, string>> = {
  agreed: 'This browser agreed to keep saved packs.',
  already: 'This browser already keeps saved packs.',
  refused: 'This browser may clear saved packs when space is low.',
  unavailable: '',
};

/**
 * From main.tsx: the dialog follows `#export`, the ranked set draws on and moves the Chart, and a saved pack keeps the worker current.
 * The dialog opens only with a region (SC2252-15): a regionless /map#export (the app shortcut) stays closed while main.tsx's home
 * resolution replaces the address, and opens when a region arrives. Returns a function that undoes the start (tests).
 * SC1407-10: only an open dialog and the planner's own ranked event load the implementation; the boundary, region and
 * timer redraws run once it is there (before it, there is no ranked set to draw).
 */
export function startTrip(): () => void {
  const sync = () => { tripOpen.value = location.hash === TRIP_HASH && !!region.peek(); if (tripOpen.peek()) void loadPlanner(); };
  const onRanked = (event: Event) => {
    const detail = (event as CustomEvent<RankedPlan | null>).detail, at = region.peek();
    if (runtimeNow) runtimeNow.ranked(detail);
    else void runtime().then(rt => { if (region.peek() === at) rt.ranked(detail); }, () => {});
  };
  const drawRanked = () => { runtimeNow?.drawRanked(); };
  addEventListener('hashchange', sync);
  addEventListener('storage', refreshIds);
  const stops = [region.subscribe(sync), region.subscribe(refreshIds)];
  document.addEventListener('skippercast:trip-ranked', onRanked);
  document.addEventListener('skippercast:boundaries', drawRanked);
  stops.push(region.subscribe(drawRanked));
  const timer = setInterval(() => { void runtimeNow?.recheckRanked(); }, 60000);
  void globalThis.caches?.keys().then(names => { if (names.some(n => n.startsWith('sc-pack-') || n.startsWith('sc-coastal-'))) registerOffline(); }, () => {});
  return () => {
    removeEventListener('hashchange', sync); removeEventListener('storage', refreshIds);
    document.removeEventListener('skippercast:trip-ranked', onRanked); document.removeEventListener('skippercast:boundaries', drawRanked);
    for (const stop of stops) stop();
    clearInterval(timer);
  };
}
