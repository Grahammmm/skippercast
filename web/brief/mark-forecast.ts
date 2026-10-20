// Forecast at a mark or trip waypoint (BP CI6-06): the mark card's wind, seas
// and surface current at the dock's hour, read from the regional forecast feed
// the brief and the Conditions view already load (/api/forecast, web/conditions.ts).
// The feed is the only source.
//
// - Step 0, gridded or point series: a region's forecast is gridded when its
//   forecast points form a lattice that packages/coast surfaceField accepts.
//   That is the Swell layer's own test (web/map/forecast-grid.ts parseForecast),
//   and today Morro Bay (3 × 3 at 0.25°) and Cambria (2 × 2) pass it. Every
//   other region has a few named points. For those the card says so, shows the
//   regional values at the point the brief uses (named), and stops there: no
//   value is presented as the mark's own.
// - Nearest cell: every model sample in the feed names the model cell it came
//   from (the sampler's dominant cell, docs/forecast-data.md), and every WCOFS
//   sample names its ocean cell. For a gridded region each model reads the
//   sample whose cell is nearest the mark, with ties going to the sample
//   requested nearer the mark. A cell more than 1.5 grid lengths from the mark
//   is not the mark's cell (the pipeline's WCOFS rule, intelligence.py
//   forecast_currents), so that row is a gap. The card names the model, its
//   grid spacing and the distance from the mark to the sampled cell.
// - Families: NOAA (GFS wind, GFS-Wave seas) and ECMWF (IFS wind, WAM seas),
//   v1's two families as the Conditions view names them, each read on its
//   own and never averaged. The surface current is NOAA WCOFS for both.
// - Hour and age: each model's listed hour passes the gridded forecast gate
//   (web/map/frames.ts forecastTime): a run at most 36 hours old, a feed
//   retrieved at most 6 hours ago, and a listed hour within 90 minutes of the
//   dock's hour. A model that fails the gate, a missing sample or a value that
//   fails v1's unit-checked reader (`sample`) leaves its row as a gap with the
//   reason. Nothing is filled.
//
// Erasable syntax only: tests/test_mark_forecast.mjs imports it by type stripping.
import {FAMILIES, MODEL_NAMES, type ConditionsForecast, type Family} from '../conditions.ts';
import {compass} from '../landing/readings.ts';
import {parseForecast, sample} from '../map/forecast-grid.ts';
import {forecastTime} from '../map/frames.ts';

const HOUR = 3_600_000;
const KM_PER_DEGREE = 111.2;
/** A cell farther than this many grid lengths from the mark is not the mark's cell. */
export const CELL_REACH = 1.5;

/** Each model's grid spacing as docs/forecast-data.md states it, and in km for the reach rule (latitude degrees). */
export const MODEL_GRIDS: Readonly<Record<string, {readonly spacing: string; readonly km: number}>> = {
  gfs_global: {spacing: 'about 13 km', km: 13},
  ncep_gfswave016: {spacing: '0.16°', km: 0.16 * KM_PER_DEGREE},
  ecmwf_ifs025: {spacing: '0.25°', km: 0.25 * KM_PER_DEGREE},
  ecmwf_wam: {spacing: '0.25°', km: 0.25 * KM_PER_DEGREE},
};
export const CURRENT_MODEL = 'NOAA WCOFS';

export interface LatLon {readonly lat: number; readonly lon: number}
/** One sample the feed offers: the forecast point it was requested at and the cell it came from. */
export interface Candidate {readonly index: number; readonly point: string; readonly requested: LatLon; readonly cell: LatLon}

/** Great-circle distance in km (the pipeline's haversine, R = 6371 km). */
export function distanceKm(a: LatLon, b: LatLon): number {
  const r = Math.PI / 180, dLat = (b.lat - a.lat) * r, dLon = (b.lon - a.lon) * r;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * r) * Math.cos(b.lat * r) * Math.sin(dLon / 2) ** 2;
  return 6371 * 2 * Math.asin(Math.sqrt(Math.min(1, h)));
}

/**
 * The candidate whose cell is nearest `mark`, within `reachKm`; ties (several points sampled from one cell)
 * go to the one requested nearer the mark, then to feed order. Null when no cell is within reach.
 */
export function nearestCell<C extends Candidate>(candidates: readonly C[], mark: LatLon, reachKm: number): (C & {readonly km: number}) | null {
  let best: (C & {km: number; requestedKm: number}) | null = null;
  for (const c of candidates) {
    const km = distanceKm(mark, c.cell), requestedKm = distanceKm(mark, c.requested);
    if (km > reachKm) continue;
    if (!best || km < best.km - 1e-9 || (Math.abs(km - best.km) <= 1e-9 && requestedKm < best.requestedKm - 1e-9)) best = {...c, km, requestedKm};
  }
  if (!best) return null;
  const {requestedKm: _, ...chosen} = best;
  return chosen as C & {km: number};
}

/** One row of the card: a value, or a gap with its reason. */
export interface MarkReading {
  readonly label: 'Wind' | 'Seas' | 'Current';
  readonly model: string;
  readonly grid: string;
  /** "12 kt from NW 315° · gusts 16 kt"; null is a gap. */
  readonly value: string | null;
  /** Why the row is a gap; '' when it has a value. */
  readonly gap: string;
  /** The forecast point whose sample was read. */
  readonly point: string | null;
  /** The sampled cell and its distance from the mark (gridded regions only). */
  readonly cell: (LatLon & {readonly km: number}) | null;
  /** The listed hour read, epoch ms; null for a gap. */
  readonly validAt: number | null;
  /** The run's initialisation, epoch ms, where the feed gives it. */
  readonly issuedAt: number | null;
}
export interface MarkForecast {
  /** Step 0: whether the region's forecast is a grid or a few named points. */
  readonly kind: 'grid' | 'points';
  /** The dock's hour, epoch ms. */
  readonly at: number;
  /** For point series: the regional point the values are read at. */
  readonly point: string | null;
  readonly families: readonly {readonly family: Family; readonly label: string; readonly rows: readonly MarkReading[]}[];
  readonly current: MarkReading;
}

type Series = {latitude?: unknown; longitude?: unknown; hourly?: {time?: unknown}};
type FeedModel = {data?: unknown; meta?: {last_run_initialisation_time?: unknown; data_end_time?: unknown}};
type FeedCurrents = {status?: unknown; issued_at?: unknown; resolution_km?: unknown; points?: unknown};
type Feed = {region_id?: unknown; retrieved?: unknown; requested_points?: unknown; models?: Record<string, FeedModel>; currents?: FeedCurrents};

const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const km1 = (km: number): string => String(Math.round(km * 10) / 10);

const formats = new Map<string, Intl.DateTimeFormat>();
function parts(ms: number, tz: string): Record<string, string> {
  let f = formats.get(tz);
  if (!f) formats.set(tz, f = new Intl.DateTimeFormat('en-US', {timeZone: tz, weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', hour12: true}));
  return Object.fromEntries(f.formatToParts(new Date(ms)).map(p => [p.type, p.value]));
}
/** "Oct 8, 5 pm" in the region's zone. */
export const runText = (ms: number, tz: string): string => { const p = parts(ms, tz); return `${p.month} ${p.day}, ${p.hour} ${(p.dayPeriod ?? '').toLowerCase()}`; };
/** "Thu 3 pm". */
export const hourText = (ms: number, tz: string): string => { const p = parts(ms, tz); return `${p.weekday} ${p.hour} ${(p.dayPeriod ?? '').toLowerCase()}`; };

/**
 * Why the gate refused a listed hour, in its own order (as the Swell layer words it): a run ahead of the
 * clock, the run's 36-hour limit, the feed's retrieval, the run's span, then no listed hour near.
 */
export function gateGap(name: string, times: readonly number[], issued: number | null, retrieved: number, at: number, now: number, tz: string): string {
  if (issued === null) return `the ${name} run carries no issue time, so its age cannot be checked`;
  const ahead = now + 5 * 60_000, run = runText(issued, tz);
  if (issued > ahead) return `the ${name} run of ${run} is dated ahead of this device's clock`;
  if (now - issued > 36 * HOUR) return `the ${name} run of ${run} is past its 36-hour age limit`;
  if (!Number.isFinite(retrieved)) return 'the regional forecast carries no retrieval time, so its age cannot be checked';
  if (retrieved > ahead) return 'the regional forecast is dated ahead of this device\'s clock';
  if (now - retrieved > 6 * HOUR) return 'the regional forecast was last retrieved more than 6 hours ago';
  const first = times.length ? Math.min(...times) : null, last = times.length ? Math.max(...times) : null;
  if (first === null || last === null || at < first || at > last) return `the selected hour is outside the ${name} run of ${run}`;
  return `the ${name} run of ${run} lists no hour within 90 minutes of the selected hour`;
}

/** The feed's requested points, in feed order; null when malformed. */
function feedPoints(f: Feed): {id: string; lat: number; lon: number}[] | null {
  if (!Array.isArray(f.requested_points)) return null;
  const points = f.requested_points.map(p => Array.isArray(p) && typeof p[0] === 'string' && finite(p[1]) && finite(p[2]) ? {id: p[0], lat: p[1], lon: p[2]} : null);
  return points.every(p => p !== null) ? points as {id: string; lat: number; lon: number}[] : null;
}

const gapRow = (label: MarkReading['label'], model: string, grid: string, gap: string, extra: Partial<MarkReading> = {}): MarkReading =>
  ({label, model, grid, value: null, gap, point: null, cell: null, validAt: null, issuedAt: null, ...extra});

/** What a model's sample reads at epoch seconds `t`: the row's value, or null when a needed value is missing. */
function modelValue(label: 'Wind' | 'Seas', series: unknown, t: number, end: number | null): string | null {
  const meta = end === null ? null : {data_end_time: end}, at = (v: string, unit: string) => sample(series, v, t, unit, meta);
  if (label === 'Wind') {
    const speed = at('wind_speed_10m', 'kn'), from = at('wind_direction_10m', '°'), gust = at('wind_gusts_10m', 'kn');
    if (speed === null) return null;
    // v1's rule: a gust below the sustained wind is left out.
    return `${Math.round(speed)} kt${from === null ? '' : ` from ${compass(from)} ${Math.round(from)}°`}${gust !== null && gust >= speed ? ` · gusts ${Math.round(gust)} kt` : ''}`;
  }
  // v1's rule: seas without a positive period are left out.
  const period = at('wave_period', 's'), height = period !== null && period > 0 ? at('wave_height', 'ft') : null, from = at('wave_direction', '°');
  if (height === null || period === null) return null;
  return `${height.toFixed(1)} ft · ${Math.round(period)} s${from === null ? '' : ` from ${compass(from)} ${Math.round(from)}°`}`;
}

/** One model's row: at the sampled cell nearest the mark (grid), or at the regional point (points). */
function modelRow(label: 'Wind' | 'Seas', id: string, f: Feed, points: readonly {id: string; lat: number; lon: number}[], where: {mark: LatLon} | {point: number},
  at: number, now: number, tz: string): MarkReading {
  const name = MODEL_NAMES[id] ?? id, grid = MODEL_GRIDS[id]?.spacing ?? 'unstated';
  const m = f.models?.[id], data = Array.isArray(m?.data) && m.data.length === points.length ? m.data as unknown[] : null;
  if (!data) return gapRow(label, name, grid, `the regional forecast carries no ${name} samples`);
  const issued = finite(m?.meta?.last_run_initialisation_time) ? m.meta.last_run_initialisation_time * 1000 : null;
  const end = finite(m?.meta?.data_end_time) ? m.meta.data_end_time : null;
  let index: number, cell: MarkReading['cell'] = null;
  if ('mark' in where) {
    const candidates: Candidate[] = points.flatMap((p, i) => {
      const s = data[i] as Series | null;
      return s && finite(s.latitude) && finite(s.longitude) ? [{index: i, point: p.id, requested: {lat: p.lat, lon: p.lon}, cell: {lat: s.latitude, lon: s.longitude}}] : [];
    });
    const reach = CELL_REACH * (MODEL_GRIDS[id]?.km ?? 0), chosen = nearestCell(candidates, where.mark, reach);
    if (!chosen) return gapRow(label, name, grid, `no ${name} cell lies within ${km1(reach)} km (1.5 grid lengths) of this mark`);
    index = chosen.index; cell = {...chosen.cell, km: chosen.km};
  } else index = where.point;
  const point = points[index]!.id, times = (data[index] as Series | null)?.hourly?.time;
  const listed = Array.isArray(times) ? times.filter(finite).map(s => s * 1000) : [];
  const t = issued === null ? null : forecastTime(listed, issued, finite(f.retrieved) ? f.retrieved : NaN, new Date(at), new Date(now));
  if (t === null) return gapRow(label, name, grid, gateGap(name, listed, issued, finite(f.retrieved) ? f.retrieved : NaN, at, now, tz), {point, cell, issuedAt: issued});
  const value = modelValue(label, data[index], t / 1000, end);
  if (value === null) return gapRow(label, name, grid, `the ${name} sample has no ${label === 'Wind' ? 'wind' : 'seas'} value for ${hourText(t, tz)}`, {point, cell, issuedAt: issued});
  return {label, model: name, grid, value, gap: '', point, cell, validAt: t, issuedAt: issued};
}

/** The surface current row from the feed's WCOFS samples: nearest cell to the mark (grid), or the regional point's sample (points). */
function currentRow(f: Feed, points: readonly {id: string; lat: number; lon: number}[], where: {mark: LatLon} | {point: number}, at: number, now: number, tz: string): MarkReading {
  const c = f.currents, name = CURRENT_MODEL, resolution = finite(c?.resolution_km) ? c.resolution_km : null;
  const grid = resolution === null ? 'unstated' : `about ${km1(resolution)} km`;
  if (!c || c.status !== 'ok') return gapRow('Current', name, grid, `the regional forecast carries no ${name} surface-current forecast${typeof c?.status === 'string' && c.status !== 'missing' ? ` (${c.status})` : ''}`);
  const issued = typeof c.issued_at === 'string' && Number.isFinite(Date.parse(c.issued_at)) ? Date.parse(c.issued_at) : null;
  // Each sample: [valid time s, cell lat, cell lon, speed kn, toward °, km from its point].
  const samples = (Array.isArray(c.points) ? c.points : []).map(p => {
    const id = (p as {point_id?: unknown})?.point_id, list = (p as {samples?: unknown})?.samples;
    const index = points.findIndex(q => q.id === id);
    return {index, samples: index < 0 || !Array.isArray(list) ? [] : list.filter((s): s is number[] => Array.isArray(s) && s.length >= 5 && s.slice(0, 5).every(finite))};
  }).filter(p => p.index >= 0);
  const pool = 'mark' in where ? samples : samples.filter(p => p.index === where.point);
  const listed = [...new Set(pool.flatMap(p => p.samples.map(s => s[0]! * 1000)))].sort((a, b) => a - b);
  const retrieved = finite(f.retrieved) ? f.retrieved : NaN;
  const t = issued === null ? null : forecastTime(listed, issued, retrieved, new Date(at), new Date(now));
  const pointId = 'point' in where ? points[where.point]?.id ?? null : null;
  if (t === null) return gapRow('Current', name, grid, gateGap(name, listed, issued, retrieved, at, now, tz), {point: pointId, issuedAt: issued});
  const at_t = pool.flatMap(p => p.samples.filter(s => s[0]! * 1000 === t).map(s => ({index: p.index, point: points[p.index]!.id, s})));
  let pick: {point: string; s: number[]; km?: number} | null;
  if ('mark' in where) {
    const reach = CELL_REACH * (resolution ?? 0);
    const chosen = nearestCell(at_t.map(x => ({...x, requested: {lat: points[x.index]!.lat, lon: points[x.index]!.lon}, cell: {lat: x.s[1]!, lon: x.s[2]!}})), where.mark, reach);
    if (!chosen) return gapRow('Current', name, grid, `no ${name} cell sampled for ${hourText(t, tz)} lies within ${km1(reach)} km (1.5 grid lengths) of this mark`, {issuedAt: issued});
    pick = chosen;
  } else pick = at_t[0] ?? null;
  if (!pick) return gapRow('Current', name, grid, `the ${name} forecast has no sample at forecast point ${pointId} for ${hourText(t, tz)}`, {point: pointId, issuedAt: issued});
  const [, lat, lon, speed, toward] = pick.s as [number, number, number, number, number];
  return {label: 'Current', model: name, grid, value: `${speed.toFixed(2)} kt toward ${Math.round(toward)}° true`, gap: '', point: pick.point,
    cell: pick.km === undefined ? null : {lat, lon, km: pick.km}, validAt: t, issuedAt: issued};
}

/** Step 0 for the loaded feed: 'grid' when its points form a lattice the Swell layer accepts, else 'points'; null without a feed. */
export function forecastKind(feed: unknown, region: string): 'grid' | 'points' | null {
  const f = parseForecast(feed, region);
  return f ? (f.step ? 'grid' : 'points') : null;
}

/**
 * The forecast for a mark at `mark` and the dock's hour `at` (epoch ms), from the regional forecast `f` as the
 * brief loaded it; null without that region's feed.
 */
export function markForecast(f: ConditionsForecast | null, region: string, mark: LatLon, at: number, now: number, tz: string): MarkForecast | null {
  const feed = f?.region === region ? f.feed as Feed | undefined : undefined;
  const kind = feed ? forecastKind(feed, region) : null, points = feed ? feedPoints(feed) : null;
  if (!f || !feed || !kind || !points) return null;
  const regional = points.findIndex(p => p.id === f.point.id);
  const where = kind === 'grid' ? {mark} : {point: regional};
  if (kind === 'points' && regional < 0) return null;
  const families = (Object.keys(FAMILIES) as Family[]).map(family => ({
    family, label: FAMILIES[family].label,
    rows: [modelRow('Wind', FAMILIES[family].wind, feed, points, where, at, now, tz), modelRow('Seas', FAMILIES[family].wave, feed, points, where, at, now, tz)],
  }));
  return {kind, at, point: kind === 'points' ? f.point.id : null, families, current: currentRow(feed, points, where, at, now, tz)};
}

/** A row's source line: model, grid, where it was sampled, and its hour when that differs from the dock's. */
export function readingSource(r: MarkReading, at: number, tz: string): string {
  return [
    `${r.model} · ${r.grid} grid`,
    r.cell ? `cell ${km1(r.cell.km)} km from this mark` : r.point ? `point ${r.point}` : '',
    r.validAt !== null && r.validAt !== at ? `valid ${hourText(r.validAt, tz)}` : '',
    r.issuedAt !== null && r.value !== null ? `run ${runText(r.issuedAt, tz)}` : '',
  ].filter(Boolean).join(' · ');
}
