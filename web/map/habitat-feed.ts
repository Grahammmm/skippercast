// The region's published ocean layers (#491, #482): `habitat-dynamics.json` from the conditions feed
// (src/skippercast/pipeline/habitat_dynamics.py) and the tiles it lists, read in the browser for a
// place that binds no local coast report: the surface-temperature analysis for Water temp and the
// WCOFS surface forecast for Currents. Temp contrast (CI6-03) reads the same analysis with its two
// gradient fields for every region, bound or not (`regionalContrast`).
//
// - Checks, as the retired v1 loader's (dist/habitat-data.js before FE-61): the manifest names its
//   own region; each tile path sits in that region's folder; each tile's bytes match the manifest's
//   length and SHA-256 and repeat its region, layer, fields, grid, bounds and frame times. One tile
//   that fails refuses the whole layer: nothing is drawn from part of a grid.
// - Gate input: the layer's own status (`ok` or `retained` loads its tiles) and its own
//   `max_age_hours`, and the source's `data_retrieved_at` as the retrieval. The layers' own gates
//   judge the rest as they do for a report or packet: web/map/sst.ts the analysis's age, the dock's
//   hour and the grid; web/map/currents.ts packages/coast `selectedCurrent` (frame, cycle and
//   retrieval ages) and the grid.
// - Samples: SST open-water cells with a temperature and a non-negative analysis error, in °F, as
//   the coast report's (src/skippercast/pipeline/coast_report.py `_temperature`); WCOFS wet cells
//   with both velocity components, as packages/coast `CurrentCell`s.
//
// Erasable syntax only: tests/test_habitat_feed.mjs imports it by type stripping.
import type {CurrentCell, CurrentField} from '../../packages/coast/src/ocean-types.ts';
import type {SSTPoint, SurfaceTemperature} from '../../packages/coast/src/spatial-types.ts';

export const SST_LAYER_ID = 'sst-analysis';
export const CHLOROPHYLL_LAYER_ID = 'chlorophyll-observation';
export const WCOFS_LAYER_ID = 'wcofs-surface-forecast';
const TIMEOUT_MS = 15_000;
const MAX_TILES = 64;
const MAX_TILE_BYTES = 5_000_000;
const TILE_PATH = /^habitat-tiles\/[a-z0-9-]+-[a-f0-9]{16}\.json$/;
const SHA256 = /^[a-f0-9]{64}$/;
const REGION_ID = /^[a-z0-9-]+$/;
const HOUR = 3_600_000;
const KNOTS_PER_MS = 1.94384449;

/** What the region's feed offers Water temp. */
export type RegionalSST =
  /** The region publishes no manifest, or no surface-temperature layer in it. */
  | {readonly state: 'none'}
  /** The manifest or one of its tiles could not be read or failed a check. */
  | {readonly state: 'error'; readonly network?: true}
  /** Listed but not loaded: the layer's status is not `ok`/`retained`, or it was already past its age limit. */
  | {readonly state: 'listed'; readonly product: string; readonly analysedAt: string | null; readonly maxAgeMs: number; readonly layerStatus: string}
  /** Every tile passed: the analysis, in the coast report's shape. */
  | {readonly state: 'ready'; readonly product: string; readonly maxAgeMs: number; readonly sst: SurfaceTemperature};

/** What the region's feed offers Currents: only the WCOFS forecast is published per region. */
export type RegionalCurrents =
  | {readonly state: 'none'}
  | {readonly state: 'error'; readonly network?: true}
  /** Listed but not loaded: its frame times, so the rail can name the last one. */
  | {readonly state: 'listed'; readonly validAt: readonly string[]; readonly layerStatus: string}
  /** Every tile passed: the forecast as the packet's `CurrentField`, for `selectedCurrent`. */
  | {readonly state: 'ready'; readonly field: CurrentField};

const numeric = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const object = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v);
const same = (a: unknown, b: unknown): boolean => JSON.stringify(a) === JSON.stringify(b);
const instant = (v: unknown): string | null => typeof v === 'string' && Number.isFinite(Date.parse(v)) ? v : null;
const box = (b: unknown): boolean => {
  if (!Array.isArray(b) || b.length !== 4 || !b.every(numeric)) return false;
  const [w, s, e, n] = b as [number, number, number, number];
  return w < e && s < n && w >= -180 && e <= 180 && s >= -90 && n <= 90;
};

/** The region's manifest on the site's conditions feed. */
export function habitatManifestURL(regionId: string, page: string): string {
  if (!REGION_ID.test(regionId)) throw new Error('Invalid region id');
  return new URL(`/feeds/conditions/regions/${regionId}/habitat-dynamics.json`, page).href;
}

/** A tile reference's URL, only inside the manifest's own region folder. */
export function habitatTileURL(manifestURL: string, record: unknown, regionId: string): string {
  if (!object(record) || typeof record.path !== 'string' || !TILE_PATH.test(record.path) || typeof record.sha256 !== 'string' || !SHA256.test(record.sha256)
    || !numeric(record.bytes) || record.bytes < 1 || record.bytes > MAX_TILE_BYTES || !box(record.bounds)) throw new Error('Invalid ocean tile reference');
  const url = new URL(record.path, manifestURL), root = new URL('.', manifestURL);
  if (url.origin !== root.origin || !url.pathname.startsWith(root.pathname) || !root.pathname.endsWith(`/regions/${regionId}/`)) throw new Error('Ocean tile outside region');
  return url.href;
}

/** The product's name: the source's name before any comma ("NOAA Geo-Polar Blended night SST, 5 km" gives "NOAA Geo-Polar Blended night SST"). */
const productName = (name: string): string => name.split(',')[0]!.trim();

interface Layer {
  readonly id: string;
  readonly raw: Record<string, unknown>;
  readonly fields: readonly string[];
  readonly resolution: readonly [number, number];
  readonly stride: number;
  /** Every frame the layer lists, populated or not; tiles may repeat only these times. */
  readonly frames: readonly {time: number; valid_cells?: unknown}[];
  readonly sourceId: string;
  readonly tiles: readonly Record<string, unknown>[];
  readonly status: string;
  readonly maxAgeMs: number;
  readonly product: string;
  readonly fetchedAt: string | null;
  /** The source's own credit line (`rights.attribution`), or ''. */
  readonly credit: string;
  readonly url: string;
}

/** A manifest layer, or null when the manifest has none; throws when the manifest is not the region's or the layer is malformed. */
function layerOf(data: unknown, regionId: string, id: string, kind: string, needs: readonly string[]): Layer | null {
  if (!object(data) || data.schema_version !== 1 || data.region_id !== regionId || !object(data.layers)) throw new Error('Not this region\'s ocean manifest');
  const l = data.layers[id];
  if (l === undefined) return null;
  const source = object(data.sources) ? data.sources[id] : undefined;
  if (!object(l) || l.id !== id || l.kind !== kind || !Array.isArray(l.fields) || l.fields[0] !== 'latitude' || l.fields[1] !== 'longitude'
    || !needs.every(f => (l.fields as unknown[]).includes(f)) || !Array.isArray(l.resolution_degrees) || l.resolution_degrees.length !== 2
    || !l.resolution_degrees.every(n => numeric(n) && n > 0 && n <= 0.25) || !Array.isArray(l.frames) || l.frames.length > 169
    || !l.frames.every(f => object(f) && numeric(f.time)) || !Array.isArray(l.tiles) || l.tiles.length > MAX_TILES || !numeric(l.max_age_hours) || l.max_age_hours <= 0
    || typeof l.status !== 'string' || !object(source) || typeof source.name !== 'string' || !source.name.trim()) throw new Error(`Malformed ${id} layer`);
  const stride = l.native_stride === undefined ? 1 : l.native_stride;
  if (!numeric(stride) || stride < 1) throw new Error(`Malformed ${id} layer`);
  return {id, raw: l, fields: l.fields as string[], resolution: l.resolution_degrees as [number, number], stride, status: l.status, maxAgeMs: l.max_age_hours * HOUR,
    frames: l.frames as {time: number}[], tiles: l.tiles as Record<string, unknown>[], sourceId: typeof l.source_id === 'string' && l.source_id ? l.source_id : id,
    product: productName(source.name), fetchedAt: instant(source.data_retrieved_at),
    credit: object(source.rights) && typeof source.rights.attribution === 'string' ? source.rights.attribution.trim() : '',
    url: typeof source.url === 'string' && /^https:\/\//.test(source.url) ? source.url : typeof l.source_url === 'string' ? l.source_url : ''};
}

/** The layer's populated frame times (epoch seconds), ascending. */
const populated = (layer: Layer): number[] => layer.frames.filter(f => !numeric(f.valid_cells) || f.valid_cells > 0).map(f => f.time).sort((a, b) => a - b);

async function sha256(bytes: ArrayBuffer): Promise<string> {
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), n => n.toString(16).padStart(2, '0')).join('');
}

/** One tile's rows by frame time (epoch seconds), after its length, hash and identity checks. */
export async function tileRows(bytes: ArrayBuffer, record: Record<string, unknown>, regionId: string, layer: Pick<Layer, 'id' | 'fields' | 'resolution' | 'frames'>): Promise<Map<number, unknown[][]>> {
  if (bytes.byteLength !== record.bytes) throw new Error('Ocean tile length mismatch');
  if (await sha256(bytes) !== record.sha256) throw new Error('Ocean tile integrity check failed');
  const tile: unknown = JSON.parse(new TextDecoder().decode(bytes));
  if (!object(tile) || tile.schema_version !== 1 || tile.region_id !== regionId || tile.layer_id !== layer.id || !same(tile.fields, layer.fields)
    || !same(tile.resolution_degrees, layer.resolution) || !same(tile.bounds, record.bounds) || !Array.isArray(tile.frames)) throw new Error('Ocean tile identity or grid mismatch');
  const width = layer.fields.length, out = new Map<number, unknown[][]>();
  for (const f of tile.frames) {
    if (!object(f) || !numeric(f.time) || !Array.isArray(f.cells) || !layer.frames.some(p => p.time === f.time) || out.has(f.time)) throw new Error('Ocean tile frames differ from the layer');
    for (const r of f.cells)
      if (!Array.isArray(r) || r.length !== width || !numeric(r[0]) || !numeric(r[1]) || r.some(v => v !== null && typeof v !== 'boolean' && !numeric(v))) throw new Error('Invalid ocean tile samples');
    out.set(f.time, f.cells as unknown[][]);
  }
  return out;
}

type Get = (url: string) => Promise<Response>;
interface ReadOptions {fetchFn: typeof fetch; page: string; now: Date; signal?: AbortSignal}
class NetworkReadError extends Error {}
const getter = (o: ReadOptions): Get => async url => {
  try {
    return await o.fetchFn(url, {signal: o.signal ? AbortSignal.any([o.signal, AbortSignal.timeout(TIMEOUT_MS)]) : AbortSignal.timeout(TIMEOUT_MS)});
  } catch (error) {
    if (error instanceof TypeError) throw new NetworkReadError('Ocean data could not be fetched');
    throw error;
  }
};

/** Every tile's rows, merged by frame time; one failed tile throws. */
async function allRows(get: Get, manifestURL: string, regionId: string, layer: Layer): Promise<Map<number, unknown[][]>> {
  const records = layer.tiles.map(record => ({record, url: habitatTileURL(manifestURL, record, regionId)}));
  const parts = await Promise.all(records.map(async ({record, url}) => {
    const r = await get(url);
    if (!r.ok) throw new Error('Ocean tile unavailable');
    return tileRows(await r.arrayBuffer(), record, regionId, layer);
  }));
  const out = new Map<number, unknown[][]>();
  for (const part of parts) for (const [time, rows] of part) out.set(time, [...(out.get(time) ?? []), ...rows]);
  return out;
}

/** The manifest, or a terminal state: 'none' for no manifest or no such layer, 'error' for a failed read. */
async function manifestLayer(regionId: string, o: ReadOptions, read: (data: unknown) => Layer | null): Promise<{layer: Layer; manifestURL: string; get: Get} | 'none' | 'error'> {
  const get = getter(o), manifestURL = habitatManifestURL(regionId, o.page), response = await get(manifestURL);
  if (response.status === 404) return 'none';
  if (!response.ok) return 'error';
  const layer = read(await response.json());
  return layer ? {layer, manifestURL, get} : 'none';
}

const loads = (layer: Layer): boolean => layer.status === 'ok' || layer.status === 'retained';

export interface ChlorophyllObservation {
  readonly product: string;
  readonly sampleAt: string;
  readonly maxAgeMs: number;
  readonly resolution: readonly [number, number];
  readonly cells: readonly {lat: number; lon: number; value: number}[];
}
export type RegionalChlorophyll =
  | {readonly state: 'none' | 'error' | 'listed'}
  | {readonly state: 'ready'; readonly observation: ChlorophyllObservation};

/** Strict display boundary, independent of acquisition/reuse/retrieval time. */
export function chlorophyllFresh(o: ChlorophyllObservation, now: Date): boolean {
  const age = now.getTime() - Date.parse(o.sampleAt);
  return Number.isFinite(age) && age >= -HOUR && Number.isFinite(o.maxAgeMs) && o.maxAgeMs > 0 && age < o.maxAgeMs;
}

/** Native observed cells only: no interpolation and no fallback to an older populated scene. */
export async function regionalChlorophyll(regionId: string, o: ReadOptions): Promise<RegionalChlorophyll> {
  try {
    const found = await manifestLayer(regionId, o, data => layerOf(data, regionId, CHLOROPHYLL_LAYER_ID, 'observation', ['chlorophyll_mg_m3']));
    if (typeof found === 'string') return {state: found};
    const {layer, manifestURL, get} = found;
    const latest = layer.frames.filter(f => numeric(f.valid_cells) && f.valid_cells > 0).map(f => f.time).sort((a, b) => a - b).at(-1);
    const sample = instant(layer.raw.sample_at);
    if (!loads(layer) || latest === undefined || !sample || Date.parse(sample) !== latest * 1000 || layer.stride !== 1)
      return {state: 'listed'};
    const observation: ChlorophyllObservation = {product: layer.product, sampleAt: new Date(latest * 1000).toISOString(),
      maxAgeMs: layer.maxAgeMs, resolution: layer.resolution, cells: []};
    if (!chlorophyllFresh(observation, o.now)) return {state: 'listed'};
    const rows = await allRows(get, manifestURL, regionId, layer), index = layer.fields.indexOf('chlorophyll_mg_m3');
    const cells = (rows.get(latest) ?? []).flatMap(r => {
      const value = r[index], lat = r[0] as number, lon = r[1] as number;
      return numeric(value) && value >= 0.001 && value <= 100 && lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180
        ? [{lat, lon, value}] : [];
    });
    return cells.length ? {state: 'ready', observation: {...observation, cells}} : {state: 'listed'};
  } catch (error) {
    if (o.signal?.aborted) throw error;
    return {state: 'error'};
  }
}

/**
 * The region's surface-temperature analysis from its feed. Tiles are read only for a layer whose own status is
 * `ok` or `retained` and whose latest frame is within its own age limit at `now`.
 */
export async function regionalSST(regionId: string, o: ReadOptions): Promise<RegionalSST> {
  try {
    const found = await manifestLayer(regionId, o, data => layerOf(data, regionId, SST_LAYER_ID, 'analysis', ['temperature_c', 'analysis_error_c']));
    if (typeof found === 'string') return {state: found};
    const {layer, manifestURL, get} = found, latest = populated(layer).at(-1) ?? null;
    const analysedAt = latest === null ? instant(layer.raw.sample_at) : new Date(latest * 1000).toISOString();
    const age = analysedAt === null ? NaN : o.now.getTime() - Date.parse(analysedAt);
    if (!loads(layer) || latest === null || !(age < layer.maxAgeMs) || !layer.fetchedAt)
      return {state: 'listed', product: layer.product, analysedAt, maxAgeMs: layer.maxAgeMs, layerStatus: layer.status};
    const rows = await allRows(get, manifestURL, regionId, layer);
    const [lat, lon] = layer.resolution;
    if (lat !== lon) return {state: 'error'};   // packages/coast surfaceField takes one spacing
    const t = layer.fields.indexOf('temperature_c'), e = layer.fields.indexOf('analysis_error_c'), points: SSTPoint[] = [];
    for (const r of rows.get(latest) ?? []) {
      const temp = r[t], error = r[e];
      if (numeric(temp) && numeric(error) && error >= 0) points.push({lon: r[1] as number, lat: r[0] as number, tempF: temp * 1.8 + 32, errorF: error * 1.8});
    }
    return {state: 'ready', product: layer.product, maxAgeMs: layer.maxAgeMs, sst: {sourceId: layer.sourceId, analysedAt: analysedAt!, fetchedAt: layer.fetchedAt,
      nativeResolutionDeg: lat, sampleSpacingDeg: lat * layer.stride, points, url: layer.url, kind: 'analysis'}};
  } catch (error) {
    if (o.signal?.aborted) throw error;
    return error instanceof NetworkReadError ? {state: 'error', network: true} : {state: 'error'};
  }
}

/** One analysis cell for Temp contrast, in the tile's own units (°C, °C per km); null where the tile has none. */
export interface ContrastSample {
  readonly lat: number;
  readonly lon: number;
  readonly tempC: number | null;
  readonly errorC: number | null;
  /** The pipeline's centred native-grid gradient (habitat_dynamics.py `gradients`). */
  readonly gradientCPerKm: number | null;
  /** 1 where the change across a pair of neighbours exceeds their summed analysis error, 0 where it does not, null where it cannot be judged. */
  readonly supported: 0 | 1 | null;
}

/** What the region's feed offers Temp contrast: the same layer as Water temp, with its two gradient fields. */
export type RegionalContrast =
  | {readonly state: 'none'}
  | {readonly state: 'error'}
  /** Listed but not loaded, as for Water temp, or the layer carries no gradient fields (`gradients: false`). */
  | {readonly state: 'listed'; readonly product: string; readonly analysedAt: string | null; readonly maxAgeMs: number; readonly layerStatus: string; readonly gradients: boolean}
  /** Every tile passed: the latest frame's cells, open water only. */
  | {readonly state: 'ready'; readonly product: string; readonly sourceId: string; readonly analysedAt: string; readonly fetchedAt: string; readonly maxAgeMs: number;
    /** Native spacing (latitude, longitude) times the layer's stride, degrees: the neighbour spacing and the drawn cell's size. */
    readonly spacingDeg: readonly [number, number]; readonly nativeResolutionDeg: number; readonly url: string; readonly credit: string; readonly samples: readonly ContrastSample[]};

const GRADIENT_FIELDS = ['temperature_gradient_c_per_km', 'thermal_contrast_supported'] as const;

/**
 * The region's surface-temperature analysis with its gradient fields, for Temp contrast. The same checks and gate
 * as `regionalSST`: tiles are read only for a layer whose own status is `ok` or `retained`, whose latest frame is
 * within its own age limit at `now`, and that names its retrieval. A layer without the two gradient fields is listed,
 * never drawn.
 */
export async function regionalContrast(regionId: string, o: ReadOptions): Promise<RegionalContrast> {
  try {
    const found = await manifestLayer(regionId, o, data => layerOf(data, regionId, SST_LAYER_ID, 'analysis', ['temperature_c', 'analysis_error_c']));
    if (typeof found === 'string') return {state: found};
    const {layer, manifestURL, get} = found, latest = populated(layer).at(-1) ?? null;
    const analysedAt = latest === null ? instant(layer.raw.sample_at) : new Date(latest * 1000).toISOString();
    const age = analysedAt === null ? NaN : o.now.getTime() - Date.parse(analysedAt);
    const gradients = GRADIENT_FIELDS.every(f => layer.fields.includes(f));
    if (!gradients || !loads(layer) || latest === null || !(age < layer.maxAgeMs) || !layer.fetchedAt)
      return {state: 'listed', product: layer.product, analysedAt, maxAgeMs: layer.maxAgeMs, layerStatus: layer.status, gradients};
    const rows = await allRows(get, manifestURL, regionId, layer);
    const [t, e, g, s] = ['temperature_c', 'analysis_error_c', ...GRADIENT_FIELDS].map(f => layer.fields.indexOf(f)) as [number, number, number, number];
    const value = (v: unknown): number | null => numeric(v) ? v : null;
    const samples = (rows.get(latest) ?? []).map((r): ContrastSample => {
      const error = value(r[e]), flag = r[s];
      return {lat: r[0] as number, lon: r[1] as number, tempC: value(r[t]), errorC: error !== null && error >= 0 ? error : null, gradientCPerKm: value(r[g]),
        supported: flag === 1 || flag === true ? 1 : flag === 0 || flag === false ? 0 : null};
    });
    const [lat, lon] = layer.resolution;
    return {state: 'ready', product: layer.product, sourceId: layer.sourceId, analysedAt: analysedAt!, fetchedAt: layer.fetchedAt, maxAgeMs: layer.maxAgeMs,
      spacingDeg: [lat * layer.stride, lon * layer.stride], nativeResolutionDeg: lat, url: layer.url, credit: layer.credit, samples};
  } catch (error) {
    if (o.signal?.aborted) throw error;
    return {state: 'error'};
  }
}

/** The packet's WCOFS text (src/skippercast/pipeline/coast_snapshots.py FORECAST_TEXT), which the layer's own limitations replace. */
const WCOFS_LABEL = 'NOAA WCOFS surface-current forecast', WCOFS_ATTRIBUTION = 'NOAA National Ocean Service · WCOFS';

/**
 * The region's WCOFS surface forecast from its feed, as the packet's `CurrentField`. Tiles are read only for a layer
 * whose own status is `ok` or `retained`, issued within its own age limit at `now`, with a retrieval time.
 */
export async function regionalCurrents(regionId: string, o: ReadOptions): Promise<RegionalCurrents> {
  try {
    const found = await manifestLayer(regionId, o, data => layerOf(data, regionId, WCOFS_LAYER_ID, 'forecast', ['u_mps', 'v_mps']));
    if (typeof found === 'string') return {state: found};
    const {layer, manifestURL, get} = found, times = populated(layer), issuedAt = instant(layer.raw.issued_at);
    const validAt = times.map(t => new Date(t * 1000).toISOString());
    if (!loads(layer) || !times.length || !issuedAt || !(o.now.getTime() - Date.parse(issuedAt) < layer.maxAgeMs) || !layer.fetchedAt || layer.raw.surface_only !== true)
      return {state: 'listed', validAt, layerStatus: layer.status};
    const rows = await allRows(get, manifestURL, regionId, layer);
    const u = layer.fields.indexOf('u_mps'), v = layer.fields.indexOf('v_mps');
    const frames = times.map(time => ({validAt: new Date(time * 1000).toISOString(), cells: (rows.get(time) ?? []).flatMap((r): CurrentCell[] => {
      const east = r[u], north = r[v];
      if (!numeric(east) || !numeric(north)) return [];
      return [{lat: r[0] as number, lon: r[1] as number, uMs: east, vMs: north, speedKnots: Math.hypot(east, north) * KNOTS_PER_MS,
        towardDeg: (Math.atan2(east, north) * 180 / Math.PI + 360) % 360}];
    })}));
    return {state: 'ready', field: {id: 'wcofs', kind: 'forecast', label: WCOFS_LABEL, url: layer.url, fetchedAt: layer.fetchedAt, issuedAt, sampleAt: null,
      // The packet's nominal 4 km (coast_snapshots.py DEFINITIONS), the model's own "approximately 4 km".
      nativeResolutionKm: 4, sampleStride: layer.stride, horizontalDatum: typeof layer.raw.horizontal_datum === 'string' ? layer.raw.horizontal_datum : 'NAD83',
      surfaceOnly: true, frames, attribution: WCOFS_ATTRIBUTION, license: 'public-domain-us-gov',
      limitations: typeof layer.raw.limitations === 'string' ? layer.raw.limitations : ''}};
  } catch (error) {
    if (o.signal?.aborted) throw error;
    return error instanceof NetworkReadError ? {state: 'error', network: true} : {state: 'error'};
  }
}
