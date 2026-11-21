// Wire checks and display eligibility only; drawing is handled separately.
const HOUR_MS = 3_600_000;

type Withheld = 'too-little-clear-water' | 'no-usable-frame' | null;
type Point = [number, number];
interface ChlEdge {
  id: string;
  observedAt: string;
  cells: number;
  strength: number;
  bandHalfWidthKm: number;
  line: Point[];
}

export interface ChlEdgesDoc {
  product: string;
  credit: string;
  maxAgeMs: number;
  observedAt: string | null;
  observedFraction: number | null;
  withheld: Withheld;
  edges: ChlEdge[];
}

export type ChlEdgesFeed = {state: 'none'} | {state: 'error'} | {state: 'ready'; doc: ChlEdgesDoc};

const record = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v);
const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const text = (v: unknown): v is string => typeof v === 'string' && v.trim() !== '';

function zonedIso(v: unknown): v is string {
  if (typeof v !== 'string') return false;
  const parts = /^(\d{4})-(\d{2})-(\d{2})T(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d(?:\.\d+)?)?(?:Z|[+-](?:[01]\d|2[0-3]):?[0-5]\d)$/.exec(v);
  if (!parts) return false;
  // Date.parse can normalize impossible dates (e.g. February 30) instead of refusing them.
  const year = Number(parts[1]), month = Number(parts[2]), day = Number(parts[3]);
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = month === 2 ? (leap ? 29 : 28) : [4, 6, 9, 11].includes(month) ? 30 : 31;
  return month >= 1 && month <= 12 && day >= 1 && day <= days && Number.isFinite(Date.parse(v));
}

function readEdge(v: unknown): ChlEdge | null {
  if (!record(v)) return null;
  const {id, observed_at, cells, strength_log10_per_cell: strength, band_half_width_km: bandHalfWidthKm, geometry} = v;
  if (!text(id) || typeof observed_at !== 'string' || typeof cells !== 'number' || !Number.isInteger(cells) || cells < 5
    || !finite(strength) || strength <= 0 || !finite(bandHalfWidthKm) || bandHalfWidthKm < 0 || !record(geometry)) return null;
  const {type, coordinates} = geometry;
  if (type !== 'LineString' || !Array.isArray(coordinates) || coordinates.length < 2) return null;
  const line: Point[] = [];
  for (const point of coordinates) {
    if (!Array.isArray(point) || point.length !== 2) return null;
    const [lon, lat] = point;
    if (!finite(lon) || Math.abs(lon) > 180 || !finite(lat) || Math.abs(lat) > 90) return null;
    line.push([lon, lat]);
  }
  return {id, observedAt: observed_at, cells, strength, bandHalfWidthKm, line};
}

/** Project the wire document only after every edge has passed its checks. */
export function readChlEdges(data: unknown, regionId: string): ChlEdgesDoc | null {
  try {
    if (!record(data) || data.schema_version !== 1 || data.region_id !== regionId || data.layer_id !== 'chl-edges') return null;
    const {product, credit, max_age_hours, observed_at: observedAt, observed_fraction: observedFraction, withheld, edges: raw} = data;
    if (!text(product) || !finite(max_age_hours) || max_age_hours <= 0 || !(observedAt === null || zonedIso(observedAt))
      || !(observedFraction === null || (finite(observedFraction) && observedFraction >= 0 && observedFraction <= 1))
      || !(withheld === null || withheld === 'too-little-clear-water' || withheld === 'no-usable-frame')
      || !Array.isArray(raw) || (withheld !== null && raw.length !== 0)) return null;
    const edges: ChlEdge[] = [];
    for (const entry of raw) {
      const edge = readEdge(entry);
      if (!edge) return null;
      edges.push(edge);
    }
    return {product, credit: typeof credit === 'string' ? credit : '', maxAgeMs: max_age_hours * HOUR_MS, observedAt, observedFraction, withheld, edges};
  } catch {
    // The boundary also accepts unknown callers, not just values decoded from JSON.
    return null;
  }
}

export async function regionalChlEdges(regionId: string, o: {fetchFn: typeof fetch; page: string; signal?: AbortSignal}): Promise<ChlEdgesFeed> {
  try {
    if (!/^[a-z0-9-]+$/.test(regionId)) return {state: 'error'};
    const url = new URL(`/feeds/conditions/regions/${regionId}/chl-edges.json`, o.page).href;
    const response = await o.fetchFn(url, o.signal ? {signal: o.signal} : {});
    if (response.status === 404) return {state: 'none'};
    const doc = response.ok ? readChlEdges(await response.json(), regionId) : null;
    return doc ? {state: 'ready', doc} : {state: 'error'};
  } catch (error) {
    if (o.signal?.aborted) throw error;
    return {state: 'error'};
  }
}

export function chlEdgesShown(doc: ChlEdgesDoc, now: Date):
  {show: true} | {show: false; reason: 'withheld-clear-water' | 'no-usable-frame' | 'no-observation' | 'stale' | 'future'} {
  if (doc.withheld === 'too-little-clear-water') return {show: false, reason: 'withheld-clear-water'};
  if (doc.withheld === 'no-usable-frame') return {show: false, reason: 'no-usable-frame'};
  if (doc.observedAt === null) return {show: false, reason: 'no-observation'};
  const age = now.getTime() - Date.parse(doc.observedAt);
  if (age < -HOUR_MS) return {show: false, reason: 'future'};
  if (age > doc.maxAgeMs) return {show: false, reason: 'stale'};
  return {show: true};
}
