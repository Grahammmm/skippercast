// Land or water for ranked places (CI6-01B; method: docs/land-water-method.md). The
// platform build derives dist/regions/<id>/land-water.json from the region's published
// NOAA CUSP shoreline (src/skippercast/platform/land_water.py). It holds, for every
// zoom-12 tile NOAA served, a grid of cells that are clean water (`w`), clean land (`l`)
// or mixed (`m`). A clean cell lies wholly more than the edge distance from every
// published line, with no parity curve through it. A place in a mixed cell needs the
// lines file (land-water-lines.json), which loads only then. It classifies by the
// published lines (edge band) and the parity curves (even-odd).
//
// Three outcomes: water, land and unknown. Unknown carries a reason:
// - outside-bounds: outside the region, or no finite position;
// - unserved-tile: a tile NOAA did not serve;
// - edge: within the edge distance (25 m) of a published line or seam join;
// - unavailable: no product, an unavailable one, or one that fails its checks;
// - pending: the lines file is still loading.
// Ranking keeps water only (fail-closed) and counts the rest in its basis. This is a
// planning screen, not a navigation boundary. Erasable syntax only: Node tests import it.
import {signal} from '@preact/signals';

export type UnknownReason = 'outside-bounds' | 'unserved-tile' | 'edge' | 'unavailable' | 'pending';
export type Placement = {readonly state: 'water' | 'land'} | {readonly state: 'unknown'; readonly reason: UnknownReason};
export type Place = (p: {readonly latitude: number; readonly longitude: number}) => Placement;
interface Point {readonly latitude: number; readonly longitude: number}

const UNIT = 100000;
const unknown = (reason: UnknownReason): Placement => ({state: 'unknown', reason});
const UNAVAILABLE = unknown('unavailable');
/** Fail-closed: every place is unknown. */
export const NO_LAND_WATER: Place = () => UNAVAILABLE;

/** The checked index, decoded. */
export interface LandWaterModel {
  readonly region: string;
  readonly bounds: readonly [number, number, number, number];
  readonly edgeM: number; readonly zoom: number; readonly grid: number;
  readonly tiles: ReadonlyMap<string, string>;
  readonly source: string; readonly linesSha256: string;
}
/** The lines file, decoded: edge and parity segments as flat [x1, y1, x2, y2, ...] in 1e-5 degree units. */
export interface LandWaterLines {readonly edge: Float64Array; readonly parity: Float64Array}

const int = (n: unknown): n is number => Number.isInteger(n);
const record = (v: unknown): Record<string, unknown> | null => v && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : null;

/** One tile's run-length cells ("w564m12...") as GRID² characters, or null when malformed. */
export function decodeCells(runs: unknown, size: number): string | null {
  if (typeof runs !== 'string') return null;
  let out = '';
  for (const m of runs.matchAll(/([wlm])(\d+)|(.)/g)) {
    if (m[3] !== undefined) return null;
    out += m[1]!.repeat(Number(m[2]));
    if (out.length > size) return null;
  }
  return out.length === size ? out : null;
}

/** The index as a model, or null when it is not an available, well-formed product for `region`. */
export function landWaterModel(index: unknown, region: string): LandWaterModel | null {
  const d = record(index), c = record(d?.constants), from = record(d?.derived_from), lines = record(d?.lines), tiles = record(d?.tiles);
  if (!d || d.schema_version !== 1 || d.product !== 'land-water' || d.region_id !== region || d.status !== 'available' || !c || !tiles) return null;
  const b = d.bounds as unknown[];
  if (!Array.isArray(b) || b.length !== 4 || !b.every(int) || !((b[0] as number) < (b[2] as number) && (b[1] as number) < (b[3] as number))) return null;
  const {edge_m: edgeM, tile_zoom: zoom, grid, unit} = c;
  if (typeof edgeM !== 'number' || !(edgeM > 0) || !int(zoom) || !int(grid) || grid < 1 || unit !== UNIT) return null;
  if (typeof from?.sha256 !== 'string' || typeof lines?.sha256 !== 'string') return null;
  const decoded = new Map<string, string>();
  for (const [key, runs] of Object.entries(tiles)) {
    const cells = decodeCells(runs, grid * grid);
    if (!cells || !new RegExp(`^${zoom}/\\d+/\\d+$`).test(key)) return null;
    decoded.set(key, cells);
  }
  return {region, bounds: b as [number, number, number, number], edgeM, zoom, grid, tiles: decoded, source: from.sha256, linesSha256: lines.sha256};
}

/** Delta-encoded lines ([x0, y0, dx1, dy1, ...]) as flat segments; null when any is malformed. */
function segments(lines: unknown): Float64Array | null {
  if (!Array.isArray(lines)) return null;
  const out: number[] = [];
  for (const line of lines) {
    if (!Array.isArray(line) || line.length < 4 || line.length % 2 || !line.every(int)) return null;
    let x = line[0] as number, y = line[1] as number;
    for (let i = 2; i < line.length; i += 2) {
      const nx = x + (line[i] as number), ny = y + (line[i + 1] as number);
      out.push(x, y, nx, ny);
      x = nx; y = ny;
    }
  }
  return Float64Array.from(out);
}

/** The lines file for `model`, or null unless it is the one the index names (same region and shoreline). */
export function landWaterLines(data: unknown, model: LandWaterModel): LandWaterLines | null {
  const d = record(data), from = record(d?.derived_from);
  if (!d || d.schema_version !== 1 || d.product !== 'land-water-lines' || d.region_id !== model.region || from?.sha256 !== model.source || d.unit !== UNIT) return null;
  const edge = segments(d.edge), parity = segments(d.parity);
  return edge && parity && edge.length && parity.length ? {edge, parity} : null;
}

/** The tile key and the cell character for a position, or null outside the served tiles. */
function cellAt(model: LandWaterModel, p: Point): {cell: string} | null {
  const n = 2 ** model.zoom, fx = (p.longitude + 180) / 360 * n;
  const fy = (1 - Math.asinh(Math.tan(p.latitude * Math.PI / 180)) / Math.PI) / 2 * n;
  const tx = Math.floor(fx), ty = Math.floor(fy), cells = model.tiles.get(`${model.zoom}/${tx}/${ty}`);
  if (!cells) return null;
  const g = model.grid, col = Math.min(g - 1, Math.floor((fx - tx) * g)), row = Math.min(g - 1, Math.floor((fy - ty) * g));
  return {cell: cells[row * g + col]!};
}

/** Metres from (x, y) to the nearest edge segment, scaled at the point's latitude (stops early inside `limit`). */
function edgeMetres(lines: LandWaterLines, x: number, y: number, latitude: number, limit: number): number {
  const kx = 111320 * Math.cos(latitude * Math.PI / 180) / UNIT, ky = 110540 / UNIT, s = lines.edge;
  const rx = limit / kx, ry = limit / ky;
  let best = Infinity;
  for (let i = 0; i < s.length; i += 4) {
    const x1 = s[i]!, y1 = s[i + 1]!, x2 = s[i + 2]!, y2 = s[i + 3]!;
    if (Math.min(x1, x2) - rx > x || Math.max(x1, x2) + rx < x || Math.min(y1, y2) - ry > y || Math.max(y1, y2) + ry < y) continue;
    const ax = (x1 - x) * kx, ay = (y1 - y) * ky, dx = (x2 - x1) * kx, dy = (y2 - y1) * ky, len = dx * dx + dy * dy;
    const t = len === 0 ? 0 : Math.max(0, Math.min(1, -(ax * dx + ay * dy) / len));
    best = Math.min(best, Math.hypot(ax + t * dx, ay + t * dy));
    if (best <= limit) return best;
  }
  return best;
}

/** Even-odd parity of (x, y) under the parity segments, by a ray east, half-open in y (land when true). */
function parity(lines: LandWaterLines, x: number, y: number): boolean {
  const s = lines.parity;
  let hit = false;
  for (let i = 0; i < s.length; i += 4) {
    const x1 = s[i]!, y1 = s[i + 1]!, x2 = s[i + 2]!, y2 = s[i + 3]!;
    if ((y1 > y) !== (y2 > y) && x < x1 + (y - y1) * (x2 - x1) / (y2 - y1)) hit = !hit;
  }
  return hit;
}

/**
 * Where a position falls (docs/land-water-method.md steps 7-10). Without a model every place is unknown; in a mixed
 * cell it is pending until `lines` loads, and unknown if the lines failed (`lines === false`).
 */
export function placeOf(model: LandWaterModel | null, lines: LandWaterLines | null | false, p: Point): Placement {
  if (!model) return UNAVAILABLE;
  if (typeof p?.longitude !== 'number' || typeof p?.latitude !== 'number') return unknown('outside-bounds');
  const x = p.longitude * UNIT, y = p.latitude * UNIT, [w, s, e, n] = model.bounds;
  if (!Number.isFinite(x) || !Number.isFinite(y) || !(x > w && x < e && y > s && y < n)) return unknown('outside-bounds');
  const at = cellAt(model, p);
  if (!at) return unknown('unserved-tile');
  if (at.cell === 'w') return {state: 'water'};
  if (at.cell === 'l') return {state: 'land'};
  if (lines === false) return UNAVAILABLE;
  if (!lines) return unknown('pending');
  return linesPlace(model, lines, p);
}

/** The lines-file classification alone (steps 7-8), for a position already inside a served tile; tests compare it with the grid. */
export function linesPlace(model: LandWaterModel, lines: LandWaterLines, p: Point): Placement {
  const x = p.longitude * UNIT, y = p.latitude * UNIT;
  if (edgeMetres(lines, x, y, p.latitude, model.edgeM) <= model.edgeM) return unknown('edge');
  return {state: parity(lines, x, y) ? 'land' : 'water'};
}

/** The basis sentence for places a ranked list withheld ("N spots withheld: land/water not confirmed."). */
export function withheldNote(n: number): string {
  return n > 0 ? `${n} spot${n === 1 ? '' : 's'} withheld: land/water not confirmed.` : '';
}
/** What every ranked list says about the check. */
export const LAND_WATER_BASIS = 'Places on land, within 25 m of the NOAA shoreline, or outside its served tiles are withheld; the shoreline is not a navigation boundary.';

/** Keep the water places, in order; count the others and note whether any waits on the lines file. */
export function keepWater<T extends Point>(items: readonly T[], place: Place): {kept: T[]; withheld: number; pending: boolean} {
  const kept: T[] = [];
  let withheld = 0, pending = false;
  for (const t of items) {
    const at = place(t);
    if (at.state === 'water') kept.push(t);
    else { withheld++; pending ||= at.state === 'unknown' && at.reason === 'pending'; }
  }
  return {kept, withheld, pending};
}

// ---- loading (one region at a time) ----

export type LandWaterState = {
  readonly region: string | null;
  readonly state: 'idle' | 'loading' | 'ready' | 'unavailable';
  readonly model: LandWaterModel | null;
  /** The lines file: not asked for (null), loading, loaded, or failed (false). */
  readonly lines: LandWaterLines | null | false;
  readonly linesLoading: boolean;
};
const IDLE: LandWaterState = {region: null, state: 'idle', model: null, lines: null, linesLoading: false};
export const landWater = signal<LandWaterState>(IDLE);

/** The classifier for `region` from the loaded state: pending while its index loads, fail-closed when it has none. */
export function placeFor(state: LandWaterState, region: string | null): Place {
  if (!region) return NO_LAND_WATER;
  if (state.region !== region || state.state === 'idle' || state.state === 'loading') return PENDING;
  if (state.state !== 'ready') return NO_LAND_WATER;
  return p => placeOf(state.model, state.lines, p);
}
const PENDING: Place = () => unknown('pending');

export const landWaterURL = (region: string): string => `regions/${encodeURIComponent(region)}/land-water.json`;
export const landWaterLinesURL = (region: string): string => `regions/${encodeURIComponent(region)}/land-water-lines.json`;

type Fetch = (input: string, init?: RequestInit) => Promise<Response>;
const page = (): string => globalThis.location?.href ?? 'http://localhost/';

// The request in flight for each file. A second caller for the same region (and, for the lines,
// the same index) awaits that request instead of starting one or reading its loading snapshot,
// so whoever awaits a loader gets the region's settled state: ready or unavailable, lines loaded
// or failed. A region switch or reset replaces the job; the replaced request then writes nothing
// and its callers get the newer state, which a classifier for the old region reads as pending.
// A job's work starts on the next microtask, after it is recorded, so even a fetch that throws
// at once settles through the job.
interface Job {readonly region: string; readonly model: LandWaterModel | null; readonly promise: Promise<LandWaterState>}
let indexJob: Job | null = null;
let linesJob: Job | null = null;
// Only the selected region's settled transport/429/5xx failure is retryable.
let indexTransientFailure = false;

function startJob(region: string, model: LandWaterModel | null, work: (current: () => boolean) => Promise<LandWaterState>, slot: 'index' | 'lines'): Job {
  let job: Job | null = null;
  const current = (): boolean => (slot === 'index' ? indexJob : linesJob) === job;
  job = {region, model, promise: Promise.resolve().then(() => work(current))};
  if (slot === 'index') indexJob = job; else linesJob = job;
  return job;
}

/**
 * Load `region`'s index once and resolve with its settled state; a missing or failed one leaves the region
 * unavailable (every place unknown). Only an explicit `retryTransient: true` retries a settled transport,
 * HTTP 429 or HTTP 5xx failure. Ready, invalid and permanently unavailable products remain memoized.
 * There are no automatic retries. Concurrent callers, including explicit retries, share one request.
 */
export function loadLandWater(region: string, fetchFn: Fetch = (...a) => fetch(...a), options: {readonly retryTransient?: boolean} = {}): Promise<LandWaterState> {
  const now = landWater.peek();
  if (now.region === region && (now.state === 'ready' || (now.state === 'unavailable' && !(options.retryTransient === true && indexTransientFailure)))) return Promise.resolve(now);
  if (indexJob?.region === region) return indexJob.promise;
  linesJob = null;
  indexTransientFailure = false;
  landWater.value = {...IDLE, region, state: 'loading'};
  return startJob(region, null, async current => {
    let model: LandWaterModel | null = null;
    let transient = false;
    try {
      const r = await fetchFn(new URL(landWaterURL(region), page()).href);
      if (r.ok) {
        // Invalid JSON/schema is a product failure, not a transport retry grant.
        try { model = landWaterModel(await r.json(), region); } catch { model = null; }
      } else transient = r.status === 429 || (r.status >= 500 && r.status <= 599);
    } catch { transient = true; }
    if (!current()) return landWater.peek();
    indexJob = null;
    indexTransientFailure = transient;
    return landWater.value = {...IDLE, region, state: model ? 'ready' : 'unavailable', model};
  }, 'index').promise;
}

async function sha256(text: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, '0')).join('');
}

/**
 * Load the lines file for the ready region once and resolve with the state once it has loaded or failed; one whose
 * bytes or source differ from the index's counts as failed. Concurrent callers share one request.
 */
export function loadLandWaterLines(region: string, fetchFn: Fetch = (...a) => fetch(...a)): Promise<LandWaterState> {
  const now = landWater.peek(), model = now.model;
  if (now.region !== region || now.state !== 'ready' || !model || now.lines !== null) return Promise.resolve(now);
  if (linesJob?.region === region && linesJob.model === model) return linesJob.promise;
  landWater.value = {...now, linesLoading: true};
  return startJob(region, model, async current => {
    let lines: LandWaterLines | false = false;
    try {
      const r = await fetchFn(new URL(landWaterLinesURL(region), page()).href);
      const text = r.ok ? await r.text() : '';
      lines = text && await sha256(text) === model.linesSha256 ? landWaterLines(JSON.parse(text), model) ?? false : false;
    } catch { lines = false; }
    const later = landWater.peek();
    if (!current() || later.region !== region || later.model !== model) return later;
    linesJob = null;
    return landWater.value = {...later, lines, linesLoading: false};
  }, 'lines').promise;
}

/** Whether any of `points` waits on the lines file under `model` (falls in a mixed cell). */
export function needsLines(model: LandWaterModel | null, points: readonly Point[]): boolean {
  return !!model && points.some(p => { const at = placeOf(model, null, p); return at.state === 'unknown' && at.reason === 'pending'; });
}

/**
 * Load what classifying `points` in `region` needs (the planner awaits this before it ranks) and return the classifier,
 * bound to the settled state: never to a loading snapshot, whoever started the requests.
 */
export async function ensureLandWater(region: string, points: readonly Point[], fetchFn?: Fetch): Promise<Place> {
  let state = await loadLandWater(region, fetchFn);
  if (state.region === region && state.state === 'ready' && state.lines === null && needsLines(state.model, points))
    state = await loadLandWaterLines(region, fetchFn);
  return placeFor(state, region);
}

/** Tests: forget the loaded region and any request in flight. */
export function resetLandWater(): void { indexJob = null; linesJob = null; indexTransientFailure = false; landWater.value = IDLE; }
