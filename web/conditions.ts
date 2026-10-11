// Conditions rows (FE-32, docs/plans/front-end/design.md § 10 Conditions).
//
// The stacked chart is packages/coast `chart()` mounted by CoastMarkup; this
// module only builds its rows, as v1's coast-conditions.js composition does
// since #393:
// - Forecast rows (Wind, Gusts, Offshore, Air, Cloud) come from SkipperCast's
//   seven-day dual-model forecast, /api/forecast?region=<id>, for every region:
//   the NOAA family (GFS wind, GFS-Wave seas) or the ECMWF family (IFS wind,
//   WAM seas), v1's two families, sampled with v1's unit-checked reader
//   (`sample`, web/map/forecast-grid.ts) at the forecast point nearest the
//   region centre. Nothing is filled: a missing hour stays a gap.
// - Local rows (Nearshore, Tide) come from the coast report only where
//   web/coast-data.ts admits one (Morro Bay and Cambria today), each with its
//   own clock. They never fill or shorten the forecast's horizon.
// - The horizon is the time dock's (web/hour.ts): 169 whole hours from the
//   current one, set by the clock alone.
//
// Erasable syntax only: tests/test_conditions_rows.mjs imports it by type stripping.
import type {Point, Series} from '../packages/coast/src/charts/series.ts';
import type {Report} from '../packages/coast/src/types.ts';
import {sample} from './map/forecast-grid.ts';
import {freshNearshore} from './map/nearshore-model.js';

const HOUR_MS = 3_600_000;
/** The time dock's horizon: 168 hours after the current whole hour. */
export const SPAN_HOURS = 168;

export type Family = 'gfs' | 'ecmwf';
/** v1's two model families (dist/marine-data.js readConditions). */
export const FAMILIES: Readonly<Record<Family, {readonly label: string; readonly wind: string; readonly wave: string}>> = {
  gfs: {label: 'NOAA', wind: 'gfs_global', wave: 'ncep_gfswave016'},
  ecmwf: {label: 'ECMWF', wind: 'ecmwf_ifs025', wave: 'ecmwf_wam'},
};
export const MODEL_NAMES: Readonly<Record<string, string>> = {
  gfs_global: 'NOAA GFS', ncep_gfswave016: 'NOAA GFS-Wave', ecmwf_ifs025: 'ECMWF IFS', ecmwf_wam: 'ECMWF WAM',
};

/** One model's series at the chosen point, with its run clock (epoch seconds). */
export interface ModelRun {readonly id: string; readonly issued: number | null; readonly end: number | null; readonly data: unknown}
export interface ConditionsForecast {
  readonly region: string;
  /** The feed's retrieval, epoch ms. */
  readonly retrieved: number;
  readonly point: {readonly id: string; readonly lat: number; readonly lon: number};
  readonly models: Readonly<Record<string, ModelRun>>;
}

const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);

/** The feed for `region` at the inshore point nearest `near` (offshore lattice points only when no other answers); null when it is not that region's feed. */
export function parseConditionsForecast(json: unknown, region: string, near: readonly [number, number] | null): ConditionsForecast | null {
  const f = json as {region_id?: unknown; retrieved?: unknown; requested_points?: unknown; models?: Record<string, {data?: unknown; meta?: {last_run_initialisation_time?: unknown; data_end_time?: unknown}}>} | null;
  if (!f || f.region_id !== region || !finite(f.retrieved) || !Array.isArray(f.requested_points)) return null;
  const points = f.requested_points.flatMap((p, index) => Array.isArray(p) && typeof p[0] === 'string' && finite(p[1]) && finite(p[2]) ? [{id: p[0], lat: p[1], lon: p[2], index}] : []);
  if (points.length !== f.requested_points.length || !points.length) return null;
  const inshore = points.filter(p => !p.id.startsWith('offshore')), pool = inshore.length ? inshore : points;
  const gap = (p: {lat: number; lon: number}) => near ? (p.lat - near[0]) ** 2 + ((p.lon - near[1]) * Math.cos(near[0] * Math.PI / 180)) ** 2 : 0;
  const point = pool.reduce((a, b) => gap(b) < gap(a) ? b : a);
  const models: Record<string, ModelRun> = {};
  for (const [id, m] of Object.entries(f.models ?? {})) {
    if (!Array.isArray(m?.data) || m.data.length !== points.length) continue;
    const issued = m.meta?.last_run_initialisation_time, end = m.meta?.data_end_time;
    models[id] = {id, issued: finite(issued) ? issued : null, end: finite(end) ? end : null, data: m.data[point.index]};
  }
  return {region, retrieved: f.retrieved, point: {id: point.id, lat: point.lat, lon: point.lon}, models};
}

/** The feed for `region`, or null when it fails to load or is not that region's. */
export async function loadConditionsForecast(region: string, near: readonly [number, number] | null, fetchFn: typeof fetch, page: string): Promise<ConditionsForecast | null> {
  try {
    const response = await fetchFn(new URL(`/api/forecast?region=${encodeURIComponent(region)}`, page).href, {signal: AbortSignal.timeout(15000)});
    return response.ok ? parseConditionsForecast(await response.json(), region, near) : null;
  } catch { return null; }
}

/** The chart's span: the current whole hour to 168 hours later (ISO), whatever the sources cover. */
export function conditionsSpan(now: Date): {start: string; end: string} {
  const start = Math.floor(now.getTime() / HOUR_MS) * HOUR_MS;
  return {start: new Date(start).toISOString(), end: new Date(start + SPAN_HOURS * HOUR_MS).toISOString()};
}

/** Each whole hour of the span, epoch seconds. */
const spanHours = (start: string): number[] => Array.from({length: SPAN_HOURS + 1}, (_, i) => Date.parse(start) / 1000 + i * 3600);

/** One hourly row from `run`; `pick` turns the hour's samples into the value or null. */
function modelRow(label: string, unit: string, color: string, hours: readonly number[], run: ModelRun | undefined, pick: (at: (variable: string, unit: string) => number | null) => number | null, range: {min?: number; max?: number} = {}): Series {
  const meta = run?.end ? {data_end_time: run.end} : null;
  const points: Point[] = hours.map(epoch => ({at: new Date(epoch * 1000).toISOString(), value: run ? pick((v, u) => sample(run.data, v, epoch, u, meta)) : null}));
  return {label, unit, color, points, ...range};
}

/** Wind, Gusts, Offshore, Air and Cloud for `family` (v1's rules: gusts below the sustained wind and seas with no positive period are left out). */
export function forecastRows(f: ConditionsForecast | null, family: Family, start: string): Series[] {
  const hours = spanHours(start), wind = f?.models[FAMILIES[family].wind], wave = f?.models[FAMILIES[family].wave];
  return [
    modelRow('Wind', 'kt', 'var(--coast-mint)', hours, wind, at => at('wind_speed_10m', 'kn')),
    modelRow('Gusts', 'kt', 'var(--coast-amber)', hours, wind, at => { const g = at('wind_gusts_10m', 'kn'), w = at('wind_speed_10m', 'kn'); return g !== null && w !== null && g >= w ? g : null; }),
    modelRow('Offshore seas', 'ft', 'var(--coast-blue)', hours, wave, at => { const p = at('wave_period', 's'); return p !== null && p > 0 ? at('wave_height', 'ft') : null; }),
    modelRow('Air', '°F', 'var(--coast-coral)', hours, wind, at => at('temperature_2m', '°F'), {min: 30}),
    modelRow('Cloud', '%', 'var(--coast-muted)', hours, wind, at => at('cloud_cover', '%'), {min: 0, max: 100}),
  ];
}

/** The local rows where a coast report binds: the freshest nearshore model site for the area, and the tide curve. */
export function coastRows(report: Report, areaId: string, now: Date): {rows: Series[]; site: {name: string; fetchedAt: string} | null} {
  const site = freshNearshore(report, areaId, now).sort((a, b) => Date.parse(b.fetchedAt) - Date.parse(a.fetchedAt))[0];
  const rows: Series[] = [];
  if (site) rows.push({label: 'Nearshore', unit: 'ft', color: 'var(--coast-blue)', points: site.hours.map(h => ({at: h.at, value: h.waveFt})), gapMs: Math.max(90, (site.temporalResolutionMinutes ?? 60) * 1.5) * 60000});
  if (report.tides.length) rows.push({label: 'Tide', unit: 'ft', color: 'var(--coast-mint)', points: report.tides.map(t => ({at: t.at, value: t.heightFt}))});
  return {rows, site: site ? {name: site.name, fetchedAt: site.fetchedAt} : null};
}

/** The design's row order: Wind, Gusts, Offshore, Nearshore, Tide, Air, Cloud. */
export function conditionsRows(forecast: readonly Series[], local: readonly Series[]): Series[] {
  const [wind, gust, offshore, air, cloud] = forecast;
  return [wind, gust, offshore, ...local, air, cloud].filter((row): row is Series => !!row);
}

/** Each row's value at the whole hour `at` (ISO), null where the row has none. */
export function readingsAt(rows: readonly Series[], at: string): {label: string; unit: string; value: number | null}[] {
  const t = Date.parse(at);
  return rows.map(row => {
    const point = row.points.find(p => Date.parse(p.at) === t) ?? row.points.find(p => Math.abs(Date.parse(p.at) - t) < 30 * 60000 && finite(p.value));
    return {label: row.label, unit: row.unit, value: finite(point?.value) ? point.value : null};
  });
}

/** One source's clock line: the model run, or the local reading's fetch. */
export interface SourceClock {readonly label: string; readonly kind: 'run' | 'fetched' | 'retrieved'; readonly at: string | null}

/** The clocks the chart's rows carry, each its own: model runs, the feed's retrieval, the nearshore fetch, the tide predictions' fetch. */
export function sourceClocks(f: ConditionsForecast | null, family: Family, report: Report | null, site: {name: string; fetchedAt: string} | null): SourceClock[] {
  const iso = (s: number | null) => s === null ? null : new Date(s * 1000).toISOString();
  const out: SourceClock[] = [FAMILIES[family].wind, FAMILIES[family].wave].map(id => ({label: MODEL_NAMES[id] ?? id, kind: 'run', at: iso(f?.models[id]?.issued ?? null)}));
  out.push({label: 'Regional forecast feed', kind: 'retrieved', at: f ? new Date(f.retrieved).toISOString() : null});
  if (site) out.push({label: `Nearshore model · ${site.name}`, kind: 'fetched', at: site.fetchedAt});
  const tides = report?.tides.length ? report.sources.find(s => s.kind === 'prediction') : undefined;
  if (tides) out.push({label: tides.label, kind: 'fetched', at: tides.fetchedAt});
  return out;
}
