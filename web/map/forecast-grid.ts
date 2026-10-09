// The regional forecast grid (FE-17, docs/plans/front-end/design.md § 9): the
// shared forecast feed that v1's hourly matrix reads (dist/forecast-matrix.js
// through dist/marine-data.js loadMarine and readConditions), for the Chart's
// Swell field.
//
// - Feed: /api/forecast?region=<id>, the regional pipeline's Open-Meteo-style
//   answer for the region's forecast points (`requested_points`), each model
//   with its run metadata and the feed's retrieval time. Swell reads NOAA
//   GFS-Wave 0.16° (`ncep_gfswave016`, v1's default NOAA family) and its
//   primary swell partition; no other model stands in.
// - Samples: `sample` is v1's marine-data.js reader restated (that module loads
//   v1's region store): unit-checked, the exact UTC hour, never past the run's
//   published end, never negative, directions within 360°.
//   tests/test_swell_layer.mjs pins it to v1's function. Nothing is filled.
// - Grid: the points that share their latitude with another point and their
//   longitude with another (Morro Bay's 3 × 3 offshore points 0.25° apart,
//   Cambria's 2 × 2); packages/coast surfaceField must accept them as one
//   lattice, else the region has no grid (#501). Inshore points off that
//   lattice are left out, so the field never reaches toward them.
//
// Erasable syntax only: tests/test_swell_layer.mjs imports it by type stripping.
import {surfaceField, type FieldPoint} from './surface-field.js';

export const WAVE_MODEL = {id: 'ncep_gfswave016', name: 'NOAA GFS-Wave', resolution: '0.16°'} as const;
/** The primary swell partition's hourly variables and units (v1's readConditions `swell`). */
export const SWELL_VARS = {height: ['swell_wave_height', 'ft'], period: ['swell_wave_period', 's'], from: ['swell_wave_direction', '°']} as const;

type Series = {hourly?: Record<string, unknown>; hourly_units?: Record<string, unknown>; utc_offset_seconds?: unknown};
export interface GridPoint {readonly id: string; readonly lat: number; readonly lon: number; /** The point's series in the model's `data`. */ readonly index: number}
export interface WaveForecast {
  readonly region: string;
  /** The feed's retrieval, epoch ms. */
  readonly retrieved: number;
  /** The grid's points, or empty when the region's points form none. */
  readonly lattice: readonly GridPoint[];
  readonly step: readonly [number, number] | null;
  /** The model's run (initialisation) and published end, epoch seconds, its series per point and its listed hours; null when the feed lacks it. */
  readonly model: {readonly issued: number; readonly end: number; readonly data: readonly unknown[]; readonly times: readonly number[]} | null;
}

/** v1's `sample` (dist/marine-data.js): one unit-checked value at exactly `epoch` (seconds), or null. */
export function sample(data: unknown, variable: string, epoch: number, unit: string, meta?: {data_end_time?: number} | null): number | null {
  const d = data as Series | null | undefined, times = d?.hourly?.time, values = d?.hourly?.[variable];
  if (d?.hourly_units?.time !== 'unixtime' || d?.utc_offset_seconds !== 0 || d?.hourly_units?.[variable] !== unit
    || !Array.isArray(times) || !Array.isArray(values) || values.length !== times.length) return null;
  if (meta?.data_end_time && epoch > meta.data_end_time) return null;
  const i = times.indexOf(epoch);
  if (i < 0 || times.indexOf(epoch, i + 1) !== -1) return null;
  const n = values[i];
  if (typeof n !== 'number' || !Number.isFinite(n)) return null;
  if (!['temperature_2m', 'sea_surface_temperature'].includes(variable) && n < 0) return null;
  if (variable.endsWith('direction') && n > 360) return null;
  return n;
}

/** The points sharing their latitude and their longitude with others: the region's grid, before surfaceField judges it. */
export function latticePoints(points: readonly Omit<GridPoint, 'index'>[]): GridPoint[] {
  const count = (key: 'lat' | 'lon', v: number): number => points.filter(p => Math.abs(p[key] - v) < 1e-6).length;
  return points.map((p, index) => ({...p, index})).filter(p => count('lat', p.lat) > 1 && count('lon', p.lon) > 1);
}

const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);

/** The feed for `region` as Swell reads it, or null when it is not that region's feed. */
export function parseForecast(json: unknown, region: string): WaveForecast | null {
  const f = json as {region_id?: unknown; retrieved?: unknown; requested_points?: unknown; models?: Record<string, {data?: unknown; meta?: {last_run_initialisation_time?: unknown; data_end_time?: unknown}}>} | null;
  if (!f || f.region_id !== region || !finite(f.retrieved) || !Array.isArray(f.requested_points)) return null;
  const points = f.requested_points.map(p => Array.isArray(p) && typeof p[0] === 'string' && finite(p[1]) && finite(p[2]) ? {id: p[0], lat: p[1], lon: p[2]} : null);
  if (points.some(p => p === null)) return null;
  const lattice = latticePoints(points as Omit<GridPoint, 'index'>[]);
  const step = surfaceField(lattice.map(p => ({lon: p.lon, lat: p.lat, values: [0]})))?.step ?? null;
  const m = f.models?.[WAVE_MODEL.id], issued = m?.meta?.last_run_initialisation_time, end = m?.meta?.data_end_time;
  const data = Array.isArray(m?.data) && m.data.length === points.length ? m.data as unknown[] : null;
  const times = (data?.[lattice[0]?.index ?? -1] as Series | undefined)?.hourly?.time;
  const model = data && finite(issued) && finite(end) && Array.isArray(times) && times.every(finite)
    ? {issued, end, data, times: (times as number[]).filter(t => t <= end)} : null;
  return {region, retrieved: f.retrieved, lattice: step ? lattice : [], step: step ? [step[0], step[1]] : null, model};
}

/** The grid's primary swell at `epoch` (seconds): [height ft, period s, sin and cos of the from-direction] where all three answer. */
export function swellPoints(f: WaveForecast, epoch: number): FieldPoint[] {
  if (!f.model) return [];
  const meta = {data_end_time: f.model.end}, out: FieldPoint[] = [];
  for (const p of f.lattice) {
    const at = (v: readonly [string, string]): number | null => sample(f.model!.data[p.index], v[0], epoch, v[1], meta);
    const height = at(SWELL_VARS.height), period = at(SWELL_VARS.period), from = at(SWELL_VARS.from);
    if (height === null || period === null || from === null) continue;
    const r = from * Math.PI / 180;
    out.push({lon: p.lon, lat: p.lat, values: [height, period, Math.sin(r), Math.cos(r)]});
  }
  return out;
}

/** The feed for `region`, or null when it fails to load or is not that region's. */
export async function loadForecast(region: string, fetchFn: typeof fetch, page: string): Promise<WaveForecast | null> {
  try {
    const response = await fetchFn(new URL(`/api/forecast?region=${encodeURIComponent(region)}`, page).href, {signal: AbortSignal.timeout(15000)});
    return response.ok ? parseForecast(await response.json(), region) : null;
  } catch { return null; }
}
