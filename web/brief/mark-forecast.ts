// Forecast at a mark or trip waypoint (BP CI6-06): the mark card's wind, seas
// and surface current at the dock's hour, read from the regional forecast feed
// the brief and the Conditions view already load (/api/forecast, web/conditions.ts).
// The feed is the only source.
//
// - Step 0, gridded or point series: the feed's model wind and seas (GFS,
//   GFS-Wave, IFS, WAM) are point series in every region. The sampler
//   (server/model-api.js, docs/forecast-data.md) interpolates each model
//   bilinearly between the four cells around each named forecast point; the
//   latitude and longitude it reports are only the dominant cell's, and the
//   value is not that cell's. Points that happen to form a lattice (Morro Bay,
//   Cambria) are still interpolated points, not model cells. So the card says
//   so, shows those rows at the regional point the brief reads, named, and
//   stops there: no model value is placed at the mark or at a cell.
// - Surface current: the feed's NOAA WCOFS samples are native ocean cells,
//   each with its own position (the pipeline keeps the nearest ocean cell's
//   own value, intelligence.py forecast_currents). The current row reads the
//   sampled cell nearest the mark when one lies within 1.5 grid lengths of it
//   (the pipeline's WCOFS reach) and names that cell's distance from the
//   mark. Otherwise it reads the regional point's sample, named, as the model
//   rows do.
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
import {sample} from '../map/forecast-grid.ts';
import {forecastTime} from '../map/frames.ts';
import {localeOf, t, type Language} from '../i18n.ts';
import {fixed} from '../view-copy.ts';

const HOUR = 3_600_000;
/** A WCOFS cell farther than this many grid lengths from the mark is not the mark's cell. */
export const CELL_REACH = 1.5;

/** Each model's grid spacing as docs/forecast-data.md states it. */
export const MODEL_GRIDS: Readonly<Record<string, string>> = {
  gfs_global: 'about 13 km',
  ncep_gfswave016: '0.16°',
  ecmwf_ifs025: '0.25°',
  ecmwf_wam: '0.25°',
};
export const CURRENT_MODEL = 'NOAA WCOFS';

export interface LatLon {readonly lat: number; readonly lon: number}
/** One native-cell sample the feed offers: the forecast point it was published for and the cell it is. */
export interface Candidate {readonly index: number; readonly point: string; readonly requested: LatLon; readonly cell: LatLon}

/** Great-circle distance in km (the pipeline's haversine, R = 6371 km). */
export function distanceKm(a: LatLon, b: LatLon): number {
  const r = Math.PI / 180, dLat = (b.lat - a.lat) * r, dLon = (b.lon - a.lon) * r;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * r) * Math.cos(b.lat * r) * Math.sin(dLon / 2) ** 2;
  return 6371 * 2 * Math.asin(Math.sqrt(Math.min(1, h)));
}

/**
 * The candidate whose cell is nearest `mark`, within `reachKm`; ties (one cell published for several points)
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
  /** The native cell read and its distance from the mark: WCOFS current only, when a sampled cell is within reach. */
  readonly cell: (LatLon & {readonly km: number}) | null;
  /** The listed hour read, epoch ms; null for a gap. */
  readonly validAt: number | null;
  /** The run's initialisation, epoch ms, where the feed gives it. */
  readonly issuedAt: number | null;
  /** SC2252-05: the unrounded numbers behind a model wind or seas row's text, from the same sample calls (the trip plan compares them to a person's own limits). Absent on gaps and the current row. */
  readonly sampled?: {readonly windKn: number | null; readonly gustKn: number | null; readonly seasFt: number | null; readonly periodS: number | null};
  /** SC2252-05: why a model row is a gap: the arrival hour is outside the run's listed hours, or no listed hour is near it, or anything else (no model, old run, missing field). */
  readonly gapKind?: 'outside-hours' | 'no-hour' | 'other';
}
export interface MarkForecast {
  /** Step 0 for model wind and seas: the feed carries point series (interpolated at named points), in every region. */
  readonly kind: 'points';
  /** The dock's hour, epoch ms. */
  readonly at: number;
  /** The regional point the model rows are read at: the point the brief reads. */
  readonly point: string;
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
/** Non-English clocks: the platform's own grammar for the language, cached by locale, zone and kind. */
const localFormats = new Map<string, Intl.DateTimeFormat>();
function localClock(ms: number, tz: string, lang: Language, kind: 'run' | 'hour'): string {
  const key = `${localeOf(lang)}|${tz}|${kind}`;
  let f = localFormats.get(key);
  if (!f) localFormats.set(key, f = new Intl.DateTimeFormat(localeOf(lang), kind === 'run' ? {timeZone: tz, month: 'short', day: 'numeric', hour: 'numeric'} : {timeZone: tz, weekday: 'short', hour: 'numeric'}));
  return f.format(new Date(ms));
}
/** "Oct 8, 5 pm" in the region's zone (`lang` other than English: the language's own short date and hour). */
export const runText = (ms: number, tz: string, lang: Language = 'en'): string => {
  if (lang !== 'en') return localClock(ms, tz, lang, 'run');
  const p = parts(ms, tz); return `${p.month} ${p.day}, ${p.hour} ${(p.dayPeriod ?? '').toLowerCase()}`;
};
/** "Thu 3 pm". */
export const hourText = (ms: number, tz: string, lang: Language = 'en'): string => {
  if (lang !== 'en') return localClock(ms, tz, lang, 'hour');
  const p = parts(ms, tz); return `${p.weekday} ${p.hour} ${(p.dayPeriod ?? '').toLowerCase()}`;
};

/** A grid spacing in `lang`: the built-in "about N km" and "unstated" are the only words; degree grids pass through. */
function gridText(grid: string, lang: Language): string {
  if (lang === 'en') return grid;
  if (grid === 'unstated') return t('markForecast.unstated', lang);
  const km = /^about (\d+(?:\.\d+)?) km$/.exec(grid);
  return km ? t('markForecast.gridAbout', lang, {km: km[1]!}) : grid;
}

/**
 * Why the gate refused a listed hour, in its own order (as the Swell layer words it): a run ahead of the
 * clock, the run's 36-hour limit, the feed's retrieval, the run's span, then no listed hour near.
 */
export function gateGap(name: string, times: readonly number[], issued: number | null, retrieved: number, at: number, now: number, tz: string, lang: Language = 'en'): string {
  return gateText(gateReason(times, issued, retrieved, at, now), name, issued, tz, lang);
}

type GateReason = 'noIssue' | 'futureRun' | 'oldRun' | 'noRetrieval' | 'futureRetrieval' | 'oldRetrieval' | 'outside' | 'noHour';
/** The gate's first refusal, in the order gateGap words them (SC2252-05: typed, so a caller never matches translated text). */
function gateReason(times: readonly number[], issued: number | null, retrieved: number, at: number, now: number): GateReason {
  if (issued === null) return 'noIssue';
  const ahead = now + 5 * 60_000;
  if (issued > ahead) return 'futureRun';
  if (now - issued > 36 * HOUR) return 'oldRun';
  if (!Number.isFinite(retrieved)) return 'noRetrieval';
  if (retrieved > ahead) return 'futureRetrieval';
  if (now - retrieved > 6 * HOUR) return 'oldRetrieval';
  const first = times.length ? Math.min(...times) : null, last = times.length ? Math.max(...times) : null;
  return first === null || last === null || at < first || at > last ? 'outside' : 'noHour';
}
function gateText(reason: GateReason, name: string, issued: number | null, tz: string, lang: Language): string {
  const run = issued === null ? '' : runText(issued, tz, lang);
  switch (reason) {
    case 'noIssue': return t('markForecast.gate.noIssue', lang, {model: name});
    case 'futureRun': return t('markForecast.gate.futureRun', lang, {model: name, run});
    case 'oldRun': return t('markForecast.gate.oldRun', lang, {model: name, run});
    case 'noRetrieval': return t('markForecast.gate.noRetrieval', lang);
    case 'futureRetrieval': return t('markForecast.gate.futureRetrieval', lang);
    case 'oldRetrieval': return t('markForecast.gate.oldRetrieval', lang);
    case 'outside': return t('markForecast.gate.outside', lang, {model: name, run});
    case 'noHour': return t('markForecast.gate.noHour', lang, {model: name, run});
  }
}

/** The feed's requested points, in feed order; null when malformed. */
function feedPoints(f: Feed): {id: string; lat: number; lon: number}[] | null {
  if (!Array.isArray(f.requested_points)) return null;
  const points = f.requested_points.map(p => Array.isArray(p) && typeof p[0] === 'string' && finite(p[1]) && finite(p[2]) ? {id: p[0], lat: p[1], lon: p[2]} : null);
  return points.every(p => p !== null) ? points as {id: string; lat: number; lon: number}[] : null;
}

const gapRow = (label: MarkReading['label'], model: string, grid: string, gap: string, extra: Partial<MarkReading> = {}): MarkReading =>
  ({label, model, grid, value: null, gap, point: null, cell: null, validAt: null, issuedAt: null, ...extra});

/** What a model's sample reads at epoch seconds `t`: the row's text and the numbers behind it, or null when a needed value is missing. */
function modelValue(label: 'Wind' | 'Seas', series: unknown, sec: number, end: number | null, lang: Language): {text: string; sampled: NonNullable<MarkReading['sampled']>} | null {
  const meta = end === null ? null : {data_end_time: end}, at = (v: string, unit: string) => sample(series, v, sec, unit, meta);
  if (label === 'Wind') {
    const speed = at('wind_speed_10m', 'kn'), from = at('wind_direction_10m', '°'), gust = at('wind_gusts_10m', 'kn');
    if (speed === null) return null;
    // v1's rule: a gust below the sustained wind is left out.
    const gusts = gust !== null && gust >= speed ? gust : null;
    return {text: `${Math.round(speed)} kt${from === null ? '' : t('markForecast.from', lang, {compass: compass(from), degrees: Math.round(from)})}${gusts !== null ? t('markForecast.gusts', lang, {gust: Math.round(gusts)}) : ''}`,
      sampled: {windKn: speed, gustKn: gusts, seasFt: null, periodS: null}};
  }
  // v1's rule: seas without a positive period are left out.
  const period = at('wave_period', 's'), height = period !== null && period > 0 ? at('wave_height', 'ft') : null, from = at('wave_direction', '°');
  if (height === null || period === null) return null;
  return {text: `${fixed(lang === 'en' ? height : Number(height.toFixed(1)), 1, lang)} ft · ${Math.round(period)} s${from === null ? '' : t('markForecast.from', lang, {compass: compass(from), degrees: Math.round(from)})}`,
    sampled: {windKn: null, gustKn: null, seasFt: height, periodS: period}};
}

/**
 * One model's row at the regional forecast point `index`: the sampler's interpolation there. The series' reported
 * latitude and longitude (the dominant cell) are never read: the value is the point's, not that cell's.
 */
function modelRow(label: 'Wind' | 'Seas', id: string, f: Feed, points: readonly {id: string; lat: number; lon: number}[], index: number,
  at: number, now: number, tz: string, lang: Language): MarkReading {
  const name = MODEL_NAMES[id] ?? id, grid = gridText(MODEL_GRIDS[id] ?? 'unstated', lang), point = points[index]!.id;
  const m = f.models?.[id], data = Array.isArray(m?.data) && m.data.length === points.length ? m.data as unknown[] : null;
  if (!data) return gapRow(label, name, grid, t('markForecast.gap.noModel', lang, {model: name}), {point, gapKind: 'other'});
  const issued = finite(m?.meta?.last_run_initialisation_time) ? m.meta.last_run_initialisation_time * 1000 : null;
  const end = finite(m?.meta?.data_end_time) ? m.meta.data_end_time : null;
  const times = (data[index] as Series | null)?.hourly?.time, retrieved = finite(f.retrieved) ? f.retrieved : NaN;
  const listed = Array.isArray(times) ? times.filter(finite).map(s => s * 1000) : [];
  const hr = issued === null ? null : forecastTime(listed, issued, retrieved, new Date(at), new Date(now));
  if (hr === null) {
    const reason = gateReason(listed, issued, retrieved, at, now);
    return gapRow(label, name, grid, gateText(reason, name, issued, tz, lang), {point, issuedAt: issued, gapKind: reason === 'outside' ? 'outside-hours' : reason === 'noHour' ? 'no-hour' : 'other'});
  }
  const value = modelValue(label, data[index], hr / 1000, end, lang);
  if (value === null) return gapRow(label, name, grid, t(label === 'Wind' ? 'markForecast.gap.noWind' : 'markForecast.gap.noSeas', lang, {model: name, hour: hourText(hr, tz, lang)}), {point, issuedAt: issued, gapKind: 'other'});
  return {label, model: name, grid, value: value.text, gap: '', point, cell: null, validAt: hr, issuedAt: issued, sampled: value.sampled};
}

/** A WCOFS sample that can be real: five finite numbers, a cell on the globe, a speed of zero or more, a bearing in 0-360. Rejected whole, never repaired. */
const possibleSample = (s: unknown): s is number[] =>
  Array.isArray(s) && s.length >= 5 && s.slice(0, 5).every(finite) && Math.abs(s[1]) <= 90 && Math.abs(s[2]) <= 180 && s[3] >= 0 && s[4] >= 0 && s[4] <= 360;

/**
 * The surface current row from the feed's WCOFS native-cell samples: the sampled cell nearest the mark within
 * 1.5 grid lengths, else the regional point's own sample (named, no distance).
 */
function currentRow(f: Feed, points: readonly {id: string; lat: number; lon: number}[], mark: LatLon, regional: number, at: number, now: number, tz: string, lang: Language): MarkReading {
  const c = f.currents, name = CURRENT_MODEL, resolution = finite(c?.resolution_km) ? c.resolution_km : null;
  const grid = gridText(resolution === null ? 'unstated' : `about ${km1(resolution)} km`, lang);
  if (!c || c.status !== 'ok') return gapRow('Current', name, grid, t('markForecast.gap.noCurrent', lang, {model: name, status: typeof c?.status === 'string' && c.status !== 'missing' ? ` (${c.status})` : ''}));
  const issued = typeof c.issued_at === 'string' && Number.isFinite(Date.parse(c.issued_at)) ? Date.parse(c.issued_at) : null;
  // Each sample: [valid time s, cell lat, cell lon, speed kn, toward °, km from its point].
  const samples = (Array.isArray(c.points) ? c.points : []).map(p => {
    const id = (p as {point_id?: unknown})?.point_id, list = (p as {samples?: unknown})?.samples;
    const index = points.findIndex(q => q.id === id);
    return {index, samples: index < 0 || !Array.isArray(list) ? [] : list.filter(possibleSample)};
  }).filter(p => p.index >= 0);
  const listed = [...new Set(samples.flatMap(p => p.samples.map(s => s[0]! * 1000)))].sort((a, b) => a - b);
  const retrieved = finite(f.retrieved) ? f.retrieved : NaN, pointId = points[regional]!.id;
  const hr = issued === null ? null : forecastTime(listed, issued, retrieved, new Date(at), new Date(now));
  if (hr === null) return gapRow('Current', name, grid, gateGap(name, listed, issued, retrieved, at, now, tz, lang), {point: pointId, issuedAt: issued});
  const at_t = samples.flatMap(p => p.samples.filter(s => s[0]! * 1000 === hr).map(s => ({index: p.index, point: points[p.index]!.id, s})));
  const reach = CELL_REACH * (resolution ?? 0);
  const near = nearestCell(at_t.map(x => ({...x, requested: {lat: points[x.index]!.lat, lon: points[x.index]!.lon}, cell: {lat: x.s[1]!, lon: x.s[2]!}})), mark, reach);
  const pick: {point: string; s: number[]; km?: number} | null = near ?? at_t.find(x => x.index === regional) ?? null;
  if (!pick) return gapRow('Current', name, grid, t('markForecast.gap.noCell', lang, {model: name, hour: hourText(hr, tz, lang), km: km1(reach), point: pointId}), {point: pointId, issuedAt: issued});
  const [, lat, lon, speed, toward] = pick.s as [number, number, number, number, number];
  return {label: 'Current', model: name, grid, value: t('markForecast.towardTrue', lang, {speed: fixed(lang === 'en' ? speed : Number(speed.toFixed(2)), 2, lang), degrees: Math.round(toward)}), gap: '', point: pick.point,
    cell: pick.km === undefined ? null : {lat, lon, km: pick.km}, validAt: hr, issuedAt: issued};
}

/**
 * The forecast for a mark at `mark` and the dock's hour `at` (epoch ms), from the regional forecast `f` as the
 * brief loaded it; null without that region's feed or its regional point.
 */
export function markForecast(f: ConditionsForecast | null, region: string, mark: LatLon, at: number, now: number, tz: string, lang: Language = 'en'): MarkForecast | null {
  const feed = f?.region === region ? f.feed as Feed | undefined : undefined;
  const points = feed && feed.region_id === region ? feedPoints(feed) : null;
  if (!f || !feed || !points) return null;
  const regional = points.findIndex(p => p.id === f.point.id);
  if (regional < 0) return null;
  const families = (Object.keys(FAMILIES) as Family[]).map(family => ({
    family, label: FAMILIES[family].label,
    rows: [modelRow('Wind', FAMILIES[family].wind, feed, points, regional, at, now, tz, lang), modelRow('Seas', FAMILIES[family].wave, feed, points, regional, at, now, tz, lang)],
  }));
  return {kind: 'points', at, point: f.point.id, families, current: currentRow(feed, points, mark, regional, at, now, tz, lang)};
}

/** A row's source line: model, grid, where it was read, and its hour when that differs from the dock's. */
export function readingSource(r: MarkReading, at: number, tz: string, lang: Language = 'en'): string {
  return [
    t('markForecast.src.model', lang, {model: r.model, grid: r.grid}),
    r.cell ? t('markForecast.src.cell', lang, {km: km1(r.cell.km)}) : r.point ? t('markForecast.src.point', lang, {point: r.point}) : '',
    r.validAt !== null && r.validAt !== at ? t('markForecast.valid', lang, {hour: hourText(r.validAt, tz, lang)}) : '',
    r.issuedAt !== null && r.value !== null ? t('markForecast.src.run', lang, {run: runText(r.issuedAt, tz, lang)}) : '',
  ].filter(Boolean).join(' · ');
}
