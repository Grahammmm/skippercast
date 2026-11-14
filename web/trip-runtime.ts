// SC1407-10: the trip planner and offline-pack implementation behind web/trip.ts, loaded by its one dynamic
// import on first actual use (opening the planner, a pack or coastal call, a ranked set), so the first screen
// never loads it. It holds no shared state of its own: web/trip.ts owns the signals, the protected-area screen
// and the hash, and hands them in through `createTripRuntime`. Erasable syntax only (Node tests import this).
import type {Source} from 'pmtiles';
import {loadManifest} from '../dist/seafloor-data.js';
import {BASEMAP_MANIFEST, basemapArchive} from './map/chart.ts';
import {shorelineOverviewURL, shorelineURL} from './map/coastline.ts';
import {chartFileListed} from './chart-files.ts';
import {landWaterLinesURL, landWaterURL} from './land-water.ts';
import {depthContoursOverviewURL, depthContoursURL} from './map/depth-contours.ts';
import {atlasMarksURL, planIndexURL} from './startup-forms.ts';
import {MARKS_SOURCE} from './map/layers.ts';
import {markSources} from './map/marks.ts';
import {NO_PLAN, fitCamera, rankedSpots, recheckPlan, screenRanked, type RankedPlan, type RankedScreen} from './map/ranked.ts';
import {camera, cameraParam, choosePresentation, type Camera} from './map/stage.ts';
import {beginWaypointPlacement} from './waypoint-placement.ts';
import {appView, day, region, type UrlKey} from './state.ts';
import {reachFor} from './reach.ts';
import {tideSelection} from './tide-selection.ts';
import {saveTidePack} from './tide-stations.ts';
import type {PackMeta, Progress, ProtectedScreen} from './trip.ts';

/** The facade's own state and helpers this implementation uses (web/trip.ts builds one, once). */
export interface TripContext {
  /** When the facade module was evaluated: the pack copies responses browsed since then. */
  sessionStart: number;
  /** The facade's one shared protected-area screen loader (the brief's screen). */
  loadProtectedScreen(id: string): Promise<ProtectedScreen>;
  /** The screen was found bound to another region, so a planner start reloads the page. */
  screenElsewhere(): boolean;
  v1Region(id: string): Promise<typeof import('../dist/region.js')>;
  json(path: string): Promise<unknown>;
  openTrip(): void;
  closeTrip(): void;
  go(patch: Partial<Record<UrlKey, string | null>>): void;
  registerOffline(): void;
}
type PlannerModel = import('./planner.ts').Planner;
type PlannerView = typeof import('./app/Planner.tsx').Planner;

/** The 2D-map calls the planner makes (`getSize`, `getBounds`), answered from the shared camera and the map's size. */
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

/** "Show ranked spots on map" moves the Chart to the ranked set's extent (web/map/ranked.ts draws their pins). */
export {fitCamera};

/** v1's pack's option bag, which its JavaScript types too narrowly to pass a callback with arguments. */
type Loose<T> = (options: Record<string, unknown>) => T;

// The offline pack.
interface Extras {
  store(url: string, key?: string, init?: RequestInit, misses?: string[]): Promise<boolean>;
  put(key: string, body: ArrayBuffer, headers: Headers): Promise<void>;
  signal: AbortSignal;
  progress(phase: string, done: number, total: number): void;
}

/**
 * The interval a 206 answer really covers, or null when it is not the requested slice: one `bytes START-END/TOTAL` (TOTAL decimal or `*`)
 * starting at the requested offset and ending at the requested end. A shorter END is a genuine range only at the archive's known EOF
 * (a known TOTAL, END = TOTAL - 1, the request reaching TOTAL or beyond); the length is never inferred from Content-Length.
 */
function answeredRange(header: string | null, offset: number, end: number): {start: number; end: number} | null {
  const m = /^\s*bytes (\d+)-(\d+)\/(\d+|\*)\s*$/.exec(header ?? '');
  if (!m) return null;
  const start = Number(m[1]), last = Number(m[2]), total = m[3] === '*' ? null : Number(m[3]);
  if (![start, last].every(Number.isSafeInteger) || (total !== null && !Number.isSafeInteger(total)) || start !== offset || last < start || last > end) return null;
  if (total !== null && total <= last) return null;
  return last === end || (total !== null && last === total - 1 && end >= total) ? {start, end: last} : null;
}

/** A PMTiles source that keeps each byte range it reads under offline-core.js `basemapRangeKey`. */
export function rangeRecorder(url: string, put: Extras['put'], signal: AbortSignal, key: (url: string, range: string) => string | null): Source {
  return {
    getKey: () => url,
    async getBytes(offset, length, s, etag) {
      if (![offset, length].every(Number.isSafeInteger) || offset < 0 || length < 1 || length - 1 > Number.MAX_SAFE_INTEGER - offset) throw new Error(`Basemap range bytes=${offset}+${length}: not a valid range`);
      const end = offset + length - 1;
      const range = `bytes=${offset}-${end}`, at = key(url, range);
      const response = await fetch(url, {headers: {range}, credentials: 'omit', signal: s ?? signal});
      // Only the exact range, live: a whole archive or a saved answer is never stored.
      if (!at || response.status !== 206 || response.headers.has('X-SC-Offline')) { void response.body?.cancel(); throw new Error(`Basemap range ${range}: HTTP ${response.status}`); }
      // And only the slice that was asked for: the answer's own interval and byte count must match before anything is written.
      const got = answeredRange(response.headers.get('Content-Range'), offset, end);
      if (!got) { void response.body?.cancel(); throw new Error(`Basemap range ${range}: the answer is not that range`); }
      const data = await response.arrayBuffer(), tag = response.headers.get('ETag');
      if (etag && tag && tag !== etag) throw new Error('The basemap archive changed while saving.');
      if (data.byteLength !== got.end - got.start + 1) throw new Error(`Basemap range ${range}: the answer is the wrong length`);
      await put(at, data, response.headers);
      return {data, etag: tag && !tag.startsWith('W/') ? tag : undefined};
    },
  };
}

/**
 * The pack's stored files in order: the shell, the basemap manifest, the shoreline forms, then the land-water index and lines and the full and
 * overview depth contours the region publishes, then the startup copies (#617) and `hashed`. A fixed allowlist, each gated on its own name in the
 * region's published `chart_files` (an unknown list fails open, as chartFileListed decides); poster.svg and any other name are never saved.
 */
export function packFiles(id: string, page: string, hashed: readonly string[]): [string, string, RequestInit][] {
  const origin = new URL(page).origin, listed = (name: string, url: string): string[] => chartFileListed(id, name) ? [url] : [];
  return [[origin + V2_SHELL, origin + V2_SHELL, {}],
    ...[BASEMAP_MANIFEST, ...listed('shoreline.geojson', shorelineURL(id)), ...listed('shoreline-overview.geojson', shorelineOverviewURL(id)),
      ...listed('land-water.json', landWaterURL(id)), ...listed('land-water-lines.json', landWaterLinesURL(id)),
      ...listed('depth-contours.geojson', depthContoursURL(id)), ...listed('depth-contours-overview.geojson', depthContoursOverviewURL(id)),
      atlasMarksURL(id), planIndexURL(id)]
      .map((p): [string, string, RequestInit] => [new URL(p, page).href, new URL(p, page).href, {}]),
    ...hashed.map((p): [string, string, RequestInit] => [origin + p, origin + p, {cache: 'default'}])];
}
/** The v2 app's page key in a pack (dist/sw.js `V2_SHELL`; web/trip.ts exports the same). */
const V2_SHELL = '/map';

/**
 * The pack's ocean phase (docs/plans/offline-ocean-coverage.md D3, D6, D9), run only inside the explicit Save action. A place with a
 * coast report (resolveReportBinding, as the layers decide it) reads its Coastal readings pointer and fetches nothing; any other
 * place saves its water-temperature and current layers whole or not at all (web/map/ocean-pack.ts). Fatal storage errors propagate.
 */
export async function oceanPhase({put, signal, progress}: Pick<Extras, 'put' | 'signal' | 'progress'>, region: {id: string; center: readonly [number, number]; localAreas?: readonly {id: string; bounds: readonly number[]}[]},
  deps: {now?: () => Date; origin?: string; fetchFn?: typeof fetch; readCoastal?: () => Promise<{saved_at?: string} | null>} = {}) {
  const [{regionPlace}, {resolveReportBinding}, ocean] = await Promise.all([import('./map/currents.ts'), import('../packages/coast/src/state/report-binding.ts'), import('./map/ocean-pack.ts')]);
  const place = regionPlace(region, 'boat', '');
  if (place && resolveReportBinding(place)) {
    const saved = await (deps.readCoastal ?? readCoastal)().catch(() => null);
    return {schema_version: 1, path: 'coastal-report', manifest: null, layers: {}, bytes: 0, coastal: saved?.saved_at ? {saved_at: saved.saved_at} : null};
  }
  const fetchFn = deps.fetchFn ?? fetch, now = deps.now ?? (() => new Date());
  let manifestStatus: number | null = null;   // saveOcean asks for the manifest first
  const saved = await ocean.saveOcean({regionId: region.id, origin: deps.origin ?? location.origin, put, signal, progress: (_layer, done, total) => progress('ocean', done, total),
    fetchFn: async (...a) => { const r = await fetchFn(...a); manifestStatus ??= r.status; return r; },
    eligible: (id, manifest) => ocean.eligibility(id, manifest, now())});
  return manifestStatus === 404 && !saved.manifest.stored ? {schema_version: 1, path: 'none', manifest: saved.manifest, layers: {}, bytes: 0, cap_bytes: saved.cap_bytes} : {schema_version: 1, path: 'regional', ...saved};
}

/** savePack's `more`: this app's page and files (precache.json `v2`), the basemap manifest, the published shoreline, land-water and depth-contour files, the startup copies (#617), tiles and, last, the ocean phase. */
async function v2Pack({store, put, signal, progress}: Extras, id: string, bounds: number[], place: Parameters<typeof oceanPhase>[1]) {
  const page = location.href, misses: string[] = [];
  const tideURLs = await tideSelection.packURLs(id);
  await saveTidePack(tideURLs, put, signal);
  const list = await fetch('/precache.json', {cache: 'no-cache', signal}).then(r => r.ok ? r.json() : null, () => null) as {build?: string; v2?: {assets?: unknown[]; static?: unknown[]}} | null;
  const hashed = [...list?.v2?.assets ?? [], ...list?.v2?.static ?? []].filter((p): p is string => typeof p === 'string' && /^\/(?!\/)/.test(p));
  const files = packFiles(id, page, hashed);
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
  const ocean = await oceanPhase({put, signal, progress}, place);
  return {build: list?.build ?? null, shell: {saved: files.length - misses.filter(m => !m.startsWith('basemap')).length, requested: files.length},
    basemap: {archive: archive ? new URL(archive).pathname : null, saved, planned: plan.tiles.length, min_zoom: plan.minZoom, max_zoom: plan.maxZoom}, missing: misses.slice(0, 50), ocean};
}

/** The saved packs, each with its cache-only legal inventory (web/trip.ts answers [] itself where there is no Cache Storage). */
async function listPacks(): Promise<{cache: string; meta: PackMeta}[]> {
  const packs = await (await import('../dist/offline-pack.js')).listPacks() as {cache: string; meta: PackMeta}[];
  const {inspectLegalPack} = await import('../dist/legal-pack.js');
  for (const pack of packs) pack.meta.legal = await inspectLegalPack(await caches.open(pack.cache), pack.meta.region_id, location.origin);
  return packs;
}

const coastal = () => import('../dist/coastal-offline-core.js');
const coastalOptions = (signal?: AbortSignal) => ({origin: location.origin, caches: globalThis.caches, signal});
const readCoastal = async () => (await coastal()).readCoastalSnapshot(coastalOptions());

/** The implementation over the facade's context: one per page, made by web/trip.ts on first use. Making it fetches and starts nothing. */
export function createTripRuntime(ctx: TripContext) {
  // The ranked plan the Chart draws (#495): the planner's latest event, screened as v1's
  // dist/trip-ranking-layer.js screens it; a publication found changed is held until verified again.
  let ranked: RankedPlan = NO_PLAN, rankedScreen: RankedScreen | null = null;
  const rejected = new Map<string, number>();
  const drawRanked = (): void => { rankedSpots.value = screenRanked(ranked, rankedScreen, rejected, region.peek()); };

  /** The planner for `id` and its view; the facade publishes them only if `id` is still the region. */
  async function startPlanner(id: string): Promise<{model: PlannerModel; View: PlannerView}> {
    // SCJ-2b: the brief's screen (one live ds582 query, one freshness clock), started here if the brief has not.
    const loaded = await ctx.loadProtectedScreen(id);
    if (loaded.state !== 'loaded') { if (ctx.screenElsewhere()) location.reload(); throw new Error('protected-area check unavailable'); }
    const screen = loaded.screen, regions = await ctx.v1Region(id);
    const [{createPlanner}, {Planner: View}] = await Promise.all([import('./planner.ts'), import('./app/Planner.tsx')]);
    const path = regions.assetURL('atlas');
    const atlas = (path ? await ctx.json(path) : {targets: [], areas: [], drifts: []}) as import('./planner.ts').Atlas;
    // The ranked pins are screened by the planner's own screen, as v1's are (#495).
    rankedScreen = screen as RankedScreen;
    drawRanked();
    const model = createPlanner({atlas, screen, region: regions.getRegion() as import('./planner.ts').PlannerDeps['region'],
      map: {getSize: () => mapView(camera.peek(), chartSize()).getSize(), getBounds: () => mapView(camera.peek(), chartSize()).getBounds()},
      // Read when the planner starts for the region; a range changed later applies to the next region's planner, and the planner measures from its chosen port.
      reachNm: reachFor('boat'), viewDay: () => day.peek(),
      getVisible: () => { const ids = new Set((markSources[MARKS_SOURCE]?.value.features ?? []).map(f => f.properties.id)); return atlas.targets.filter(t => ids.has(t.id)); },
      nav: {
        open: ctx.openTrip,
        showMap() { ctx.closeTrip(); if (appView.peek() !== 'coast') ctx.go({view: null}); },
        // SC1407-15: the route preview's points, kept in frame (a detour included), as Show ranked spots on map does.
        fit(points) { const at = fitCamera(points); if (at) ctx.go({view: cameraParam(at)}); },
        conditions(date: string) { ctx.closeTrip(); ctx.go({view: 'conditions', day: date}); },
        chooseWaypoint(pick) {
          ctx.closeTrip();
          if (appView.peek() !== 'coast') ctx.go({view: null});
          choosePresentation('chart');
          beginWaypointPlacement(id, pick);
        },
      }});
    return {model, View};
  }

  return {
    startPlanner,
    drawRanked,
    /** The planner's `skippercast:trip-ranked` detail: draw it and, when asked, move the Chart to it. */
    ranked(detail: RankedPlan | null): void {
      ranked = detail?.targets ? detail : NO_PLAN;
      drawRanked();
      const at = detail?.fit ? fitCamera(ranked.targets) : null;
      if (at) ctx.go({view: cameraParam(at)});
    },
    /** Each minute, as v1 does: the screen's age and the publication's expiry again, and the manifest still the plan's. */
    async recheckRanked(): Promise<void> {
      drawRanked();
      const current = ranked, hash = current.publication?.export_sha256;
      if (!current.targets.length || !hash) return;
      const gate = await loadManifest(current.publication?.region);
      if (ranked !== current) return;
      const next = recheckPlan(current, gate, rejected, Date.now());
      if (next !== current) { ranked = next; drawRanked(); }
    },
    listPacks,
    /** Save `id` for offline: v1's pack with this app added; then the worker is registered so the pack answers offline. */
    async savePack(id: string, signal: AbortSignal, progress: (p: Progress) => void): Promise<PackMeta> {
      const regions = await ctx.v1Region(id), save = (await import('../dist/offline-pack.js')).savePack as unknown as Loose<Promise<PackMeta>>;
      const region = regions.getRegion() as {id: string; bounds: number[]; map?: {center?: [number, number]; local_areas?: {id: string; bounds: number[]}[]}};
      const place = {id, center: region.map?.center ?? [NaN, NaN] as [number, number], localAreas: region.map?.local_areas ?? []};
      const meta = await save({signal, progress, sessionStart: ctx.sessionStart, more: (extras: Extras) => v2Pack(extras, id, region.bounds, place)});
      ctx.registerOffline();
      return meta;
    },
    readCoastal,
    canSaveCoastal: async () => (await coastal()).canMutateCoastalSnapshot({caches: globalThis.caches}),
    async saveCoastal(signal: AbortSignal) { const meta = await (await coastal()).saveCoastalSnapshot(coastalOptions(signal)); ctx.registerOffline(); return meta; },
    deleteCoastal: async () => (await coastal()).deleteCoastalSnapshot(coastalOptions()),
  };
}
export type TripRuntime = ReturnType<typeof createTripRuntime>;
