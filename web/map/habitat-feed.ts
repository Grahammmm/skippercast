// The region's published ocean layers (#491): `habitat-dynamics.json` from the conditions feed
// (src/skippercast/pipeline/habitat_dynamics.py) and the tiles it lists, read in the browser for a
// place that binds no local coast report. Only its surface-temperature analysis is read here.
//
// - Checks, as the retired v1 loader's (dist/habitat-data.js before FE-61): the manifest names its
//   own region; each tile path sits in that region's folder; each tile's bytes match the manifest's
//   length and SHA-256 and repeat its region, layer, fields, grid, bounds and frame times. One tile
//   that fails refuses the whole analysis: nothing is drawn from part of a grid.
// - Gate input: the layer's own status (`ok` or `retained` loads its tiles), its own `max_age_hours`,
//   its latest populated frame as the analysis time, and the source's `data_retrieved_at` as the
//   retrieval. web/map/sst.ts judges age, the dock's hour and the grid as it does for a report.
// - Samples: open-water cells with a temperature and a non-negative analysis error, in °F, as the
//   coast report's (src/skippercast/pipeline/coast_report.py `_temperature`).
//
// Erasable syntax only: tests/test_habitat_feed.mjs imports it by type stripping.
import type {SSTPoint, SurfaceTemperature} from '../../packages/coast/src/spatial-types.ts';

export const SST_LAYER_ID = 'sst-analysis';
const TIMEOUT_MS = 15_000;
const MAX_TILES = 64;
const MAX_TILE_BYTES = 5_000_000;
const TILE_PATH = /^habitat-tiles\/[a-z0-9-]+-[a-f0-9]{16}\.json$/;
const SHA256 = /^[a-f0-9]{64}$/;
const REGION_ID = /^[a-z0-9-]+$/;

/** What the region's feed offers Water temp. */
export type RegionalSST =
  /** The region publishes no manifest, or no surface-temperature layer in it. */
  | {readonly state: 'none'}
  /** The manifest or one of its tiles could not be read or failed a check. */
  | {readonly state: 'error'}
  /** Listed but not loaded: the layer's status is not `ok`/`retained`, or it was already past its age limit. */
  | {readonly state: 'listed'; readonly product: string; readonly analysedAt: string | null; readonly maxAgeMs: number; readonly layerStatus: string}
  /** Every tile passed: the analysis, in the coast report's shape. */
  | {readonly state: 'ready'; readonly product: string; readonly maxAgeMs: number; readonly sst: SurfaceTemperature};

const numeric = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const object = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v);
const same = (a: unknown, b: unknown): boolean => JSON.stringify(a) === JSON.stringify(b);
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
  readonly fields: readonly string[];
  readonly resolution: readonly [number, number];
  readonly stride: number;
  /** Every frame the layer lists, populated or not; tiles may repeat only these times. */
  readonly frames: readonly {time: number; valid_cells?: unknown}[];
  readonly sourceId: string;
  readonly tiles: readonly Record<string, unknown>[];
  readonly status: string;
  readonly sampleAt: string | null;
  readonly maxAgeMs: number;
}

/** The manifest's surface-temperature layer, or null when it has none; throws when the manifest is not the region's or the layer is malformed. */
export function sstLayer(data: unknown, regionId: string): {layer: Layer; product: string; fetchedAt: string | null; url: string} | null {
  if (!object(data) || data.schema_version !== 1 || data.region_id !== regionId || !object(data.layers)) throw new Error('Not this region\'s ocean manifest');
  const l = data.layers[SST_LAYER_ID];
  if (l === undefined) return null;
  const source = object(data.sources) ? data.sources[SST_LAYER_ID] : undefined;
  if (!object(l) || l.id !== SST_LAYER_ID || l.kind !== 'analysis' || !Array.isArray(l.fields) || l.fields[0] !== 'latitude' || l.fields[1] !== 'longitude'
    || !l.fields.includes('temperature_c') || !l.fields.includes('analysis_error_c') || !Array.isArray(l.resolution_degrees) || l.resolution_degrees.length !== 2
    || !l.resolution_degrees.every(n => numeric(n) && n > 0 && n <= 0.25) || !Array.isArray(l.frames) || l.frames.length > 169
    || !l.frames.every(f => object(f) && numeric(f.time)) || !Array.isArray(l.tiles) || l.tiles.length > MAX_TILES || !numeric(l.max_age_hours) || l.max_age_hours <= 0
    || typeof l.status !== 'string' || !object(source) || typeof source.name !== 'string' || !source.name.trim()) throw new Error('Malformed surface-temperature layer');
  const stride = l.native_stride === undefined ? 1 : l.native_stride;
  if (!numeric(stride) || stride < 1) throw new Error('Malformed surface-temperature layer');
  const sampleAt = typeof l.sample_at === 'string' && Number.isFinite(Date.parse(l.sample_at)) ? l.sample_at : null;
  const fetchedAt = typeof source.data_retrieved_at === 'string' && Number.isFinite(Date.parse(source.data_retrieved_at)) ? source.data_retrieved_at : null;
  const url = typeof source.url === 'string' && /^https:\/\//.test(source.url) ? source.url : typeof l.source_url === 'string' ? l.source_url : '';
  return {
    layer: {fields: l.fields as string[], resolution: l.resolution_degrees as [number, number], stride, status: l.status, sampleAt, maxAgeMs: l.max_age_hours * 3_600_000,
      frames: l.frames as {time: number}[], tiles: l.tiles as Record<string, unknown>[], sourceId: typeof l.source_id === 'string' && l.source_id ? l.source_id : SST_LAYER_ID},
    product: productName(source.name), fetchedAt, url,
  };
}

async function sha256(bytes: ArrayBuffer): Promise<string> {
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), n => n.toString(16).padStart(2, '0')).join('');
}

/** One tile's open-water samples at `time` (epoch seconds), after its length, hash and identity checks. */
export async function tileSamples(bytes: ArrayBuffer, record: Record<string, unknown>, regionId: string, layer: Layer, time: number): Promise<SSTPoint[]> {
  if (bytes.byteLength !== record.bytes) throw new Error('Ocean tile length mismatch');
  if (await sha256(bytes) !== record.sha256) throw new Error('Ocean tile integrity check failed');
  const tile: unknown = JSON.parse(new TextDecoder().decode(bytes));
  if (!object(tile) || tile.schema_version !== 1 || tile.region_id !== regionId || tile.layer_id !== SST_LAYER_ID || !same(tile.fields, layer.fields)
    || !same(tile.resolution_degrees, layer.resolution) || !same(tile.bounds, record.bounds) || !Array.isArray(tile.frames)) throw new Error('Ocean tile identity or grid mismatch');
  const width = layer.fields.length, t = layer.fields.indexOf('temperature_c'), e = layer.fields.indexOf('analysis_error_c');
  const points: SSTPoint[] = [];
  for (const f of tile.frames) {
    if (!object(f) || !numeric(f.time) || !Array.isArray(f.cells) || !layer.frames.some(p => p.time === f.time)) throw new Error('Ocean tile frames differ from the layer');
    for (const r of f.cells) {
      if (!Array.isArray(r) || r.length !== width || !numeric(r[0]) || !numeric(r[1]) || r.some(v => v !== null && typeof v !== 'boolean' && !numeric(v))) throw new Error('Invalid ocean tile samples');
      const temp = r[t], error = r[e];
      if (f.time === time && numeric(temp) && numeric(error) && error >= 0) points.push({lon: r[1], lat: r[0], tempF: temp * 1.8 + 32, errorF: error * 1.8});
    }
  }
  return points;
}

/**
 * The region's surface-temperature analysis from its feed. Tiles are read only for a layer whose own status is
 * `ok` or `retained` and whose latest frame is within its own age limit at `now`.
 */
export async function regionalSST(regionId: string, o: {fetchFn: typeof fetch; page: string; now: Date; signal?: AbortSignal}): Promise<RegionalSST> {
  const get = (url: string) => o.fetchFn(url, {signal: o.signal ? AbortSignal.any([o.signal, AbortSignal.timeout(TIMEOUT_MS)]) : AbortSignal.timeout(TIMEOUT_MS)});
  try {
    const manifestURL = habitatManifestURL(regionId, o.page), response = await get(manifestURL);
    if (response.status === 404) return {state: 'none'};
    if (!response.ok) return {state: 'error'};
    const found = sstLayer(await response.json(), regionId);
    if (!found) return {state: 'none'};
    const {layer, product, fetchedAt, url} = found;
    const latest = layer.frames.filter(f => !numeric(f.valid_cells) || f.valid_cells > 0)
      .reduce<number | null>((best, f) => best === null || f.time > best ? f.time : best, null);
    const analysedAt = latest === null ? layer.sampleAt : new Date(latest * 1000).toISOString();
    const age = analysedAt === null ? NaN : o.now.getTime() - Date.parse(analysedAt);
    const listed: RegionalSST = {state: 'listed', product, analysedAt, maxAgeMs: layer.maxAgeMs, layerStatus: layer.status};
    if ((layer.status !== 'ok' && layer.status !== 'retained') || latest === null || !(age < layer.maxAgeMs) || !fetchedAt) return listed;
    const records = layer.tiles.map(record => ({record, url: habitatTileURL(manifestURL, record, regionId)}));
    const parts = await Promise.all(records.map(async ({record, url: tileURL}) => {
      const r = await get(tileURL);
      if (!r.ok) throw new Error('Ocean tile unavailable');
      return tileSamples(await r.arrayBuffer(), record, regionId, layer, latest);
    }));
    const [lat, lon] = layer.resolution;
    if (lat !== lon) return {state: 'error'};   // packages/coast surfaceField takes one spacing
    return {state: 'ready', product, maxAgeMs: layer.maxAgeMs, sst: {sourceId: layer.sourceId, analysedAt: analysedAt!, fetchedAt, nativeResolutionDeg: lat,
      sampleSpacingDeg: lat * layer.stride, points: parts.flat(), url, kind: 'analysis'}};
  } catch (error) {
    if (o.signal?.aborted) throw error;
    return {state: 'error'};
  }
}
