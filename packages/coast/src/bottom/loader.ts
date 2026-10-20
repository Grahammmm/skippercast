// Measured seabed survey windows: decode, probe, section and integrity-checked loading.
// Ported from the v1 trial loader dist/bottom-view.js (browser-trial-readiness, 2026-10-11),
// which FE-61 removed with the v1 shell. Pure module: no DOM, no Three, no region globals;
// callers inject fetch, the page origin and the current region so tests stay offline.
// Blank survey cells stay null. Schema 2 keeps authoritative positive-down depths separate
// from display elevations and is a held private diagnostic, never a publishable product.

// Survey JSON is validated field by field below before any value is trusted.
export type BottomWindowData = Record<string, any>;

export interface BottomGrid {
  elevations: (number | null)[];
  depths: (number | null)[];
  uncertainty: (number | null)[] | null;
  mask: number[];
  width: number;
  height: number;
}

export interface BottomProbe {
  valid: boolean;
  depth_m: number | null;
  uncertainty_m: number | null;
  uncertainty_kind: string | null;
}

export interface BottomSample {
  x: number;
  y: number;
  distance_ft: number;
  depth_ft: number | null;
}

export interface BottomIndexRecord {
  status: string;
  path: string;
  sha256: string;
}

export interface BottomIndex {
  region_id: string;
  views: Record<string, BottomIndexRecord | undefined>;
}

export interface BottomView {
  data: BottomWindowData;
  grid: BottomGrid;
  record: BottomIndexRecord;
  /** True for a schema 2 private diagnostic window (publication held). */
  diagnostic: boolean;
}

const FEET_PER_M = 3.28084;

/** Schema 1 (int16 decimetre elevations, 129×129) or schema 2 display elevations, positive up. */
export function decodeBottom(data: BottomWindowData): (number | null)[] {
  if (data.schema_version === 2) return decodeBottomWindow(data).elevations;
  if (data.schema_version !== 1 || data.encoding !== 'base64-int16-le' || data.width !== 129 || data.height !== 129 ||
    data.elevation_unit_m !== 0.1 || data.nodata !== -32768 || !(data.cell_m > 0)) throw new Error('Unsupported survey window');
  const bytes = Uint8Array.from(atob(data.elevations), (c) => c.charCodeAt(0));
  if (bytes.length !== data.width * data.height * 2) throw new Error('Incomplete survey window');
  const view = new DataView(bytes.buffer);
  return Array.from({length: data.width * data.height}, (_, i) => {
    const n = view.getInt16(i * 2, true);
    return n === data.nodata ? null : n / 10;
  });
}

function invalidV2(): never {
  throw new Error('Invalid private float32 window');
}

function checkV2Contract(data: BottomWindowData): void {
  const v = data.vertical, src = v?.lineage?.source_vertical, crs = data.crs;
  if (data.schema_version !== 2 || !Number.isInteger(data.width) || !Number.isInteger(data.height) ||
    data.width < 1 || data.width > 128 || data.height < 1 || data.height > 128 ||
    data.encoding !== 'base64-float32-le' || data.byte_order !== 'little' || data.dtype !== 'float32' ||
    data.mask_encoding !== 'base64-uint8' || data.cell_m !== 2 || data.depth_sign !== 'positive_down' ||
    data.depth_units !== 'm' || data.uncertainty_kind !== 'producer_uncertainty_m' ||
    data.vertical_datum !== 'MLLW' || data.datum_realization !== 'unknown' ||
    data.internal_diagnostic !== true || data.publication_prohibited !== true || data.website !== 'held' ||
    data.habitat !== 'unassessed' || data.support_kind !== 'native_grid_node_footprints' || data.native_cell_m !== 2 ||
    data.coordinate_transform_applied !== false || data.resampled !== false) invalidV2();
  if (crs?.authority !== 'EPSG:26910' || typeof crs?.wkt !== 'string' ||
    (!crs.wkt.includes('PROJCS') && !crs.wkt.includes('PROJCRS')) ||
    typeof crs?.original_wkt !== 'string' || !crs.original_wkt.includes('BOUNDCRS') ||
    !/^[a-f0-9]{64}$/.test(crs?.lineage_sha256 || '')) invalidV2();
  const a = data.affine;
  if (!Array.isArray(a) || a.length !== 6 || !a.every(Number.isFinite) ||
    a[0] !== 2 || a[1] !== 0 || a[3] !== 0 || a[4] !== -2) invalidV2();
  const node = data.node_span_m, foot = data.footprint_span_m;
  if (!Array.isArray(node) || node.length !== 2 || !Array.isArray(foot) || foot.length !== 2 ||
    node[0] !== 2 * (data.width - 1) || node[1] !== 2 * (data.height - 1) ||
    foot[0] !== 2 * data.width || foot[1] !== 2 * data.height) invalidV2();
  if (data.precision !== 'unchanged_float32_bits' || data.nodata !== 'validity_mask') invalidV2();
  if (v?.sign !== 'positive_down' || v?.units !== 'm' || v?.datum !== 'MLLW' || v?.datum_realization !== 'unknown' ||
    v?.scale !== 1 || v?.offset !== 0 || v?.scale_offset_applied !== true || v?.storage !== 'normalized_depth' ||
    !Array.isArray(v?.conflicts) || v.conflicts.length !== 0 || v?.lineage?.datum_transform !== false) invalidV2();
  if (src?.sign !== 'positive_up' || src?.units !== 'm' || src?.datum !== 'MLLW' || src?.datum_realization !== 'unknown' ||
    src?.scale !== 1 || src?.offset !== 0 || src?.scale_offset_applied !== false ||
    !Array.isArray(src?.conflicts) || src.conflicts.length !== 0) invalidV2();
  if (JSON.stringify(v.evidence) !== JSON.stringify(src.evidence) || !Array.isArray(src.evidence) || !src.evidence.length) invalidV2();
  if (!src.evidence.some((e: BottomWindowData) => e.kind === 'raster_header')) invalidV2();
  for (const e of src.evidence) if (e.kind === 'raster_header') {
    for (const k of ['sign', 'units', 'datum', 'datum_realization', 'scale', 'offset', 'scale_offset_applied'])
      if (e.facts?.[k] !== src[k]) invalidV2();
  }
}

function unpackBase64(encoded: unknown, size: number): Uint8Array {
  if (typeof encoded !== 'string' || encoded.length !== 4 * Math.ceil(size / 3) ||
    !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(encoded)) invalidV2();
  const bytes = Uint8Array.from(atob(encoded), (c) => c.charCodeAt(0));
  if (bytes.length !== size) invalidV2();
  return bytes;
}

/** Decode either schema into depths (positive down), elevations, validity mask and uncertainty. */
export function decodeBottomWindow(data: BottomWindowData): BottomGrid {
  if (data.schema_version === 1) {
    const elevations = decodeBottom(data);
    return {elevations, depths: elevations.map((v) => v === null ? null : -v), uncertainty: null,
      mask: elevations.map((v) => v === null ? 0 : 1), width: data.width, height: data.height};
  }
  checkV2Contract(data);
  const n = data.width * data.height;
  const db = unpackBase64(data.depth_m, n * 4), ub = unpackBase64(data.uncertainty_m, n * 4), mask = unpackBase64(data.validity, n);
  const dv = new DataView(db.buffer), uv = new DataView(ub.buffer), depths: (number | null)[] = [], uncertainty: (number | null)[] = [];
  for (let i = 0; i < n; i++) {
    const d = dv.getFloat32(i * 4, true), u = uv.getFloat32(i * 4, true);
    if (mask[i] !== 0 && mask[i] !== 1) invalidV2();
    if (mask[i] === 1 && (!Number.isFinite(d) || d < 0 || d > 91.44 || !Number.isFinite(u) || u <= 0 || u > 1)) invalidV2();
    depths.push(mask[i] === 1 ? d : null); uncertainty.push(mask[i] === 1 ? u : null);
  }
  const valid = depths.filter((v): v is number => v !== null);
  if (!valid.length) invalidV2();
  const lo = Math.min(...valid), hi = Math.max(...valid);
  for (const [range, mult] of [[data.depth_range_ft, FEET_PER_M], [data.display_depth_range_m, 1]] as const) {
    if (!Array.isArray(range) || range.length !== 2 || !range.every(Number.isFinite) || range[0] > lo * mult || range[1] < hi * mult) invalidV2();
  }
  if (data.span_m !== Math.max(...data.footprint_span_m)) invalidV2();
  return {depths, uncertainty, mask: Array.from(mask), elevations: depths.map((v) => v === null ? null : -v),
    width: data.width, height: data.height};
}

/** Read one grid node. Throws outside the window; a blank node reports valid=false. */
export function bottomProbe(data: BottomWindowData, x: number, y: number): BottomProbe {
  const grid = decodeBottomWindow(data);
  if (!Number.isInteger(x) || !Number.isInteger(y) || x < 0 || y < 0 || x >= grid.width || y >= grid.height) throw new Error('Probe outside window');
  const i = y * grid.width + x;
  return {valid: grid.mask[i] === 1, depth_m: grid.depths[i], uncertainty_m: grid.uncertainty?.[i] ?? null,
    uncertainty_kind: data.uncertainty_kind ?? null};
}

/** Grid-bearing cross-section through the window centre, nearest-node sampled; gaps stay null. */
export function bottomSection(data: BottomWindowData, bearing = 90): BottomSample[] {
  if (!Number.isFinite(bearing)) throw new Error('Invalid section bearing');
  const grid = decodeBottomWindow(data), a = bearing * Math.PI / 180, dx = Math.sin(a), dy = -Math.cos(a);
  const cx = (grid.width - 1) / 2, cy = (grid.height - 1) / 2;
  const radius = Math.min(Math.abs(dx) < 1e-12 ? Infinity : cx / Math.abs(dx), Math.abs(dy) < 1e-12 ? Infinity : cy / Math.abs(dy));
  const count = Math.max(grid.width, grid.height);
  return Array.from({length: count}, (_, i) => {
    const step = count === 1 ? 0 : (i / (count - 1) * 2 - 1) * radius, x = cx + step * dx, y = cy + step * dy;
    const row = Math.max(0, Math.min(grid.height - 1, Math.round(y))), col = Math.max(0, Math.min(grid.width - 1, Math.round(x)));
    const v = grid.depths[row * grid.width + col];
    return {x, y, distance_ft: (step + radius) * data.cell_m * FEET_PER_M, depth_ft: v === null ? null : v * FEET_PER_M};
  });
}

export interface BottomLoaderDeps {
  fetch: typeof fetch;
  /** Page origin; survey assets must be same-origin. */
  origin: string;
  /** Region selected right now; re-read after every await to drop stale loads. */
  currentRegionId: () => string;
  /** The region's bottom_index asset URL (absolute or origin-relative), or null when it has none. */
  indexURL: (regionId: string) => string | null;
}

const UNAVAILABLE = 'No measured seabed image is available for this area.';

async function sha256Hex(bytes: ArrayBuffer): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(digest), (n) => n.toString(16).padStart(2, '0')).join('');
}

/** A loader with its own per-region index cache. Failed index reads are not cached. */
export function createBottomLoader(deps: BottomLoaderDeps) {
  const indexes = new Map<string, Promise<BottomIndex>>();
  async function load(targetId: string): Promise<BottomView> {
    const regionId = deps.currentRegionId(), indexPath = deps.indexURL(regionId);
    if (!indexPath) throw new Error(UNAVAILABLE);
    const indexURL = new URL(indexPath, deps.origin).href, key = regionId + '|' + indexURL;
    if (!indexes.has(key)) indexes.set(key, deps.fetch(indexURL)
      .then((r) => { if (!r.ok) throw new Error('Survey index unavailable'); return r.json() as Promise<BottomIndex>; })
      .catch((e) => { indexes.delete(key); throw e; }));
    const index = await indexes.get(key)!;
    if (deps.currentRegionId() !== regionId) throw new Error('Region changed during survey load');
    if (index.region_id !== regionId) throw new Error('Survey belongs to another region');
    const record = index.views?.[targetId];
    if (record?.status !== 'surveyed' && record?.status !== 'private_diagnostic')
      throw new Error(UNAVAILABLE + ' Regional geology cannot resolve individual rocks.');
    if (typeof record.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(record.sha256)) throw new Error('Survey integrity check failed');
    // Index paths are site-root relative (regions/<id>/bottom/...), as the v1 shell resolved them from /.
    const url = new URL(record.path, deps.origin);
    if (url.origin !== new URL(deps.origin).origin || !url.pathname.includes(`/regions/${regionId}/bottom/`)) throw new Error('Invalid survey asset path');
    url.searchParams.set('v', record.sha256.slice(0, 12));
    const response = await deps.fetch(url.href);
    if (!response.ok) throw new Error('Survey window unavailable');
    const bytes = await response.arrayBuffer();
    if (await sha256Hex(bytes) !== record.sha256) throw new Error('Survey integrity check failed');
    const data = JSON.parse(new TextDecoder().decode(bytes)) as BottomWindowData;
    if (deps.currentRegionId() !== regionId || data.region_id !== regionId || data.target_id !== targetId) throw new Error('Survey identity mismatch');
    const grid = decodeBottomWindow(data);
    if (record.status === 'private_diagnostic' && data.schema_version !== 2) throw new Error('Private diagnostic index requires schema 2');
    if (data.schema_version === 2 && record.status !== 'private_diagnostic') throw new Error('Private window requires diagnostic index');
    return {data, grid, record, diagnostic: data.schema_version === 2};
  }
  return {load};
}
