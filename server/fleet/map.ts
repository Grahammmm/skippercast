// Charter fleet map API (docs/plans/charter-fleet/design.md § 14, D11; CF-50).
// Admin only while the public layer is undecided: the routes are registered in
// adminRoutes (routes/admin.ts) behind requireUser and requireAdmin, and
// fleetGate (routes/fleet.ts) answers 404 unless both FLEET_ENABLED and
// FLEET_MAP_ENABLED are on. Read-only over the 0014 activity tables.
//
//   GET /api/fleet/map/filters?region=   the values the filter card offers, from the data (<= 500 vessels; truncated: true past that)
//   GET /api/fleet/map/events?...         fleet_events as Point features, newest first, <= 2,000 a page
//   GET /api/fleet/map/tracks?...         fleet_trips' segments as LineString features, <= 300 trips a page
//   GET /api/fleet/map/heat?...           fleet_aggregates cells as Polygon features, most dwell first, <= 5,000 a page
//
// Query (every layer): region (required), bbox=minLon,minLat,maxLon,maxLat,
// from, to (YYYY-MM-DD, inclusive, the trip's local departure date), vessel,
// port, class, trip_type, kind, season, season_part, source, limit, cursor.
// vessel, port, class, trip_type, kind and source take up to 10 comma-separated
// values. A filter that a layer cannot apply (aggregates hold no vessel, port,
// class, trip type or source) is listed in `meta.ignored`, never silently widened.
// season_part=all means every part. On events and tracks an omitted season_part
// is every part too; on heat it is the whole-season cells (season_part NULL),
// which the aggregator always writes beside the per-part cells (§ 5), so the
// default heat view never counts a dwell twice. A heat cell without dates is
// kept under a date filter, and the bound it escaped is listed in `meta.ignored`.
//
// Tracks page by trip: `limit` and `meta.trips` count trips, `meta.count` counts
// segment features. A bbox drops segments (and trips left with none) after the
// page is cut, so a page can hold fewer trips than `meta.trips` shows, or none,
// while `meta.next` is still set: clients page on `meta.next`, never on counts.
//
// Every feature carries `basis` (always "inferred-from-movement": segment kinds,
// events and aggregates all come from speed and track shape, never a confirmed
// stop or catch) and `rights`. Rows with rights "noaa-planning-only"
// (MarineCadastre, D9) are included and tagged `planning_only: true` so the
// client can exclude them; `meta.planning_only` counts them.
import type {Context} from 'hono';
import {json} from '../http.ts';
import {fleetSettings} from './settings.ts';
import type {AppEnv} from '../env.ts';

export const CAPS = {events: 2000, tracks: 300, heat: 5000} as const;
export const LAYERS = ['filters', 'events', 'tracks', 'heat'] as const;
export type Layer = typeof LAYERS[number];
export const KINDS = ['drift-anchor', 'troll'] as const;
export const SOURCES = ['aisstream', 'marinecadastre', 'datalastic'] as const;
export const BASIS = 'inferred-from-movement';
export const PLANNING_ONLY = 'noaa-planning-only';
const MAX_VALUES = 10;   // keeps every statement under D1's 100 bound parameters
const MAX_FILTER_VESSELS = 500;
const DEFAULT_CELL_M = 1000;

const REGION = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?$/;
const TOKEN = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/;
const DATE = /^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/;
const SEASON = /^\d{4}$/;
const CURSOR = /^[A-Za-z0-9_-]{1,400}$/;

export interface MapQuery {
  region: string;
  bbox: [number, number, number, number] | null;   // minLon, minLat, maxLon, maxLat
  from: string | null; to: string | null;
  vessel: string[]; port: string[]; class: string[]; trip_type: string[]; kind: string[]; source: string[];
  season: string | null; season_part: string | null;
  module: string;
  limit: number;
  cursor: string[] | null;
}

type Params = Record<string, string | undefined>;
type Feature = {type: 'Feature'; id: string; geometry: Record<string, unknown>; properties: Record<string, unknown>};
export interface MapPage {
  type: 'FeatureCollection';
  features: Feature[];
  meta: {layer: Layer; region: string; count: number; cap: number; next: string | null; planning_only: number; ignored: string[]; trips?: number};
}

const LIST_FILTERS = ['vessel', 'port', 'class', 'trip_type', 'kind', 'source'] as const;
const IGNORED_BY_HEAT = ['vessel', 'port', 'class', 'trip_type', 'source'] as const;

function list(name: string, raw: string | undefined, allowed?: readonly string[]): string[] | string {
  if (raw === undefined || raw === '') return [];
  const values = [...new Set(raw.split(',').map(v => v.trim()).filter(Boolean))];
  if (values.length > MAX_VALUES) return `${name}: at most ${MAX_VALUES} values`;
  for (const v of values) if (!TOKEN.test(v) || (allowed && !allowed.includes(v))) return `invalid ${name}`;
  return values;
}

const encodeCursor = (parts: (string | number)[]): string => btoa(JSON.stringify(parts)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
function decodeCursor(raw: string, shape: ('s' | 'n')[]): string[] | null {
  if (!CURSOR.test(raw)) return null;
  try {
    const parts: unknown = JSON.parse(atob(raw.replace(/-/g, '+').replace(/_/g, '/')));
    if (!Array.isArray(parts) || parts.length !== shape.length) return null;
    return parts.every((p, i) => shape[i] === 'n' ? Number.isFinite(p) : typeof p === 'string' && p.length <= 160) ? parts.map(String) : null;
  } catch { return null; }
}
const CURSOR_SHAPE: Record<Exclude<Layer, 'filters'>, ('s' | 'n')[]> = {events: ['s', 's'], tracks: ['s', 's'], heat: ['n', 's']};

/** Parse and validate a map query; an error string for anything malformed. */
export function mapQuery(layer: Exclude<Layer, 'filters'>, params: Params): MapQuery | {error: string} {
  const region = params.region ?? '';
  if (!REGION.test(region)) return {error: 'region is required'};
  let bbox: MapQuery['bbox'] = null;
  if (params.bbox) {
    const n = params.bbox.split(',').map(Number);
    if (n.length !== 4 || !n.every(Number.isFinite)) return {error: 'bbox must be minLon,minLat,maxLon,maxLat'};
    const [w, s, e, north] = n as [number, number, number, number];
    if (w < -180 || e > 180 || s < -90 || north > 90 || w >= e || s >= north) return {error: 'bbox out of range'};
    bbox = [w, s, e, north];
  }
  const from = params.from || null, to = params.to || null;
  if ((from && !DATE.test(from)) || (to && !DATE.test(to))) return {error: 'from and to must be YYYY-MM-DD'};
  if (from && to && from > to) return {error: 'from is after to'};
  const season = params.season || null, season_part = params.season_part || null;
  if (season && !SEASON.test(season)) return {error: 'season must be a year'};
  if (season_part && !TOKEN.test(season_part)) return {error: 'invalid season_part'};
  const module = params.module || 'grid';
  if (!TOKEN.test(module)) return {error: 'invalid module'};
  const lists: Record<string, string[]> = {};
  for (const name of LIST_FILTERS) {
    const value = list(name, params[name], name === 'kind' ? KINDS : name === 'source' ? SOURCES : undefined);
    if (typeof value === 'string') return {error: value};
    lists[name] = value;
  }
  const cap = CAPS[layer];
  const limit = params.limit === undefined || params.limit === '' ? cap : Number(params.limit);
  if (!Number.isInteger(limit) || limit < 1 || limit > cap) return {error: `limit must be 1-${cap}`};
  const cursor = params.cursor ? decodeCursor(params.cursor, CURSOR_SHAPE[layer]) : null;
  if (params.cursor && !cursor) return {error: 'invalid cursor'};
  return {region, bbox, from, to, season, season_part, module, limit, cursor,
    vessel: lists.vessel!, port: lists.port!, class: lists.class!, trip_type: lists.trip_type!, kind: lists.kind!, source: lists.source!};
}

class Where {
  parts: string[] = []; args: (string | number)[] = [];
  add(sql: string, ...args: (string | number)[]): void { this.parts.push(sql); this.args.push(...args); }
  in(column: string, values: string[]): void { if (values.length) this.add(`${column} IN (${values.map(() => '?').join(',')})`, ...values); }
  get sql(): string { return this.parts.length ? this.parts.join(' AND ') : '1'; }
}

const planning = (rights: string): boolean => rights === PLANNING_ONLY;
const page = (layer: Layer, q: MapQuery, features: Feature[], next: string | null, ignored: string[] = []): MapPage =>
  ({type: 'FeatureCollection', features, meta: {layer, region: q.region, count: features.length, cap: q.limit, next,
    planning_only: features.filter(f => f.properties.planning_only).length, ignored}});

// The trip's local departure date is the date-range key on every per-trip layer
// (the catch-log join key, § 5); an event without its trip row falls back to its UTC day.
const EVENT_DATE = 'COALESCE(t.local_date, substr(e.started_at,1,10))';

type EventRow = {id: string; trip_id: string; vessel_id: string; kind: string; lat: number; lon: number; radius_m: number | null; started_at: string; ended_at: string;
  dwell_min: number; port_id: string | null; vessel_class: string | null; trip_type: string | null; season: string; season_part: string | null; basis: string;
  source: string; rights: string; classifier_version: string; species_json: string | null; local_date: string; name: string | null; slug: string | null};

/** Activity events as Point features, newest first. */
export async function mapEvents(db: D1Database, q: MapQuery): Promise<MapPage> {
  const w = new Where();
  w.add('e.region=?', q.region);
  if (q.bbox) w.add('e.lon>=? AND e.lat>=? AND e.lon<=? AND e.lat<=?', ...q.bbox);
  if (q.from) w.add(`${EVENT_DATE}>=?`, q.from);
  if (q.to) w.add(`${EVENT_DATE}<=?`, q.to);
  w.in('e.vessel_id', q.vessel);
  w.in('e.port_id', q.port);
  w.in('COALESCE(e.vessel_class, v.vessel_class)', q.class);
  w.in('COALESCE(e.trip_type, t.trip_type_inferred)', q.trip_type);
  w.in('e.kind', q.kind);
  w.in('e.source', q.source);
  if (q.season) w.add('e.season=?', q.season);
  if (q.season_part && q.season_part !== 'all') w.add('e.season_part=?', q.season_part);
  if (q.cursor) w.add('(e.started_at<? OR (e.started_at=? AND e.id<?))', q.cursor[0]!, q.cursor[0]!, q.cursor[1]!);
  const rows = (await db.prepare(`SELECT e.id, e.trip_id, e.vessel_id, e.kind, e.lat, e.lon, e.radius_m, e.started_at, e.ended_at, e.dwell_min,
      e.port_id, COALESCE(e.vessel_class, v.vessel_class) AS vessel_class, COALESCE(e.trip_type, t.trip_type_inferred) AS trip_type, e.season, e.season_part,
      e.basis, e.source, e.rights, e.classifier_version, e.species_json, ${EVENT_DATE} AS local_date, v.name, v.slug
    FROM fleet_events e LEFT JOIN fleet_trips t ON t.id=e.trip_id LEFT JOIN fleet_vessels v ON v.id=e.vessel_id
    WHERE ${w.sql} ORDER BY e.started_at DESC, e.id DESC LIMIT ?`).bind(...w.args, q.limit + 1).all<EventRow>()).results;
  const more = rows.length > q.limit, shown = rows.slice(0, q.limit);
  const features: Feature[] = shown.map(r => ({type: 'Feature', id: r.id, geometry: {type: 'Point', coordinates: [r.lon, r.lat]}, properties: {
    layer: 'event', id: r.id, trip_id: r.trip_id, vessel_id: r.vessel_id, vessel_name: r.name, vessel_slug: r.slug, port_id: r.port_id,
    vessel_class: r.vessel_class, trip_type: r.trip_type, kind: r.kind, local_date: r.local_date, started_at: r.started_at, ended_at: r.ended_at,
    dwell_min: r.dwell_min, radius_m: r.radius_m, season: r.season, season_part: r.season_part, species: parseJson(r.species_json),
    source: r.source, classifier_version: r.classifier_version,
    basis: r.basis || BASIS, rights: r.rights, planning_only: planning(r.rights)}}));
  const last = shown.at(-1);
  return page('events', q, features, more && last ? encodeCursor([last.started_at, last.id]) : null);
}

type TripRow = {id: string; vessel_id: string; mmsi: string; depart_port_id: string | null; return_port_id: string | null; departed_at: string; returned_at: string | null;
  local_date: string; season: string; season_part: string | null; status: string; trip_type_inferred: string | null; distance_nm: number | null;
  max_offshore_nm: number | null; fishing_min: number | null; source: string; rights: string; classifier_version: string; name: string | null; slug: string | null;
  vessel_class: string | null};
type SegmentRow = {id: string; trip_id: string; seq: number; kind: string; started_at: string; ended_at: string; geometry: string | null; points_n: number | null; mean_sog: number | null};

/** Trip tracks: one LineString feature per segment, trips newest first; `limit` counts trips. */
export async function mapTracks(db: D1Database, q: MapQuery): Promise<MapPage> {
  const w = new Where();
  w.add('t.region=?', q.region);
  if (q.from) w.add('t.local_date>=?', q.from);
  if (q.to) w.add('t.local_date<=?', q.to);
  w.in('t.vessel_id', q.vessel);
  if (q.port.length) {
    const marks = q.port.map(() => '?').join(',');
    w.add(`(t.depart_port_id IN (${marks}) OR t.return_port_id IN (${marks}))`, ...q.port, ...q.port);
  }
  w.in('v.vessel_class', q.class);
  w.in('t.trip_type_inferred', q.trip_type);
  w.in('t.source', q.source);
  if (q.kind.length) w.add(`EXISTS (SELECT 1 FROM fleet_events k WHERE k.trip_id=t.id AND k.kind IN (${q.kind.map(() => '?').join(',')}))`, ...q.kind);
  if (q.season) w.add('t.season=?', q.season);
  if (q.season_part && q.season_part !== 'all') w.add('t.season_part=?', q.season_part);
  if (q.cursor) w.add('(t.departed_at<? OR (t.departed_at=? AND t.id<?))', q.cursor[0]!, q.cursor[0]!, q.cursor[1]!);
  const trips = (await db.prepare(`SELECT t.id, t.vessel_id, t.mmsi, t.depart_port_id, t.return_port_id, t.departed_at, t.returned_at, t.local_date, t.season,
      t.season_part, t.status, t.trip_type_inferred, t.distance_nm, t.max_offshore_nm, t.fishing_min, t.source, t.rights, t.classifier_version,
      v.name, v.slug, v.vessel_class
    FROM fleet_trips t LEFT JOIN fleet_vessels v ON v.id=t.vessel_id
    WHERE ${w.sql} ORDER BY t.departed_at DESC, t.id DESC LIMIT ?`).bind(...w.args, q.limit + 1).all<TripRow>()).results;
  const more = trips.length > q.limit, shown = trips.slice(0, q.limit);
  const segments = new Map<string, SegmentRow[]>();
  // D1 binds at most 100 parameters a statement: fetch segments in chunks of trips.
  for (let i = 0; i < shown.length; i += 90) {
    const ids = shown.slice(i, i + 90).map(t => t.id);
    const rows = (await db.prepare(`SELECT id, trip_id, seq, kind, started_at, ended_at, geometry, points_n, mean_sog FROM fleet_segments
      WHERE trip_id IN (${ids.map(() => '?').join(',')}) ORDER BY trip_id, seq`).bind(...ids).all<SegmentRow>()).results;
    for (const row of rows) { const list = segments.get(row.trip_id) ?? []; list.push(row); segments.set(row.trip_id, list); }
  }
  const features: Feature[] = [];
  for (const t of shown) {
    const tripFeatures: Feature[] = [];
    for (const s of segments.get(t.id) ?? []) {
      const coordinates = s.geometry ? decodePolyline(s.geometry) : [];
      if (coordinates.length < 2) continue;
      if (q.bbox && !intersects(coordinates, q.bbox)) continue;
      tripFeatures.push({type: 'Feature', id: s.id, geometry: {type: 'LineString', coordinates}, properties: {
        layer: 'track', id: s.id, trip_id: t.id, seq: s.seq, segment_kind: s.kind, started_at: s.started_at, ended_at: s.ended_at, points_n: s.points_n, mean_sog: s.mean_sog,
        vessel_id: t.vessel_id, vessel_name: t.name, vessel_slug: t.slug, vessel_class: t.vessel_class, depart_port_id: t.depart_port_id, return_port_id: t.return_port_id,
        trip_type: t.trip_type_inferred, trip_status: t.status, local_date: t.local_date, departed_at: t.departed_at, returned_at: t.returned_at,
        season: t.season, season_part: t.season_part, distance_nm: t.distance_nm, max_offshore_nm: t.max_offshore_nm, fishing_min: t.fishing_min,
        source: t.source, classifier_version: t.classifier_version,
        basis: BASIS, rights: t.rights, planning_only: planning(t.rights)}});
    }
    features.push(...tripFeatures);
  }
  const last = shown.at(-1);
  const result = page('tracks', q, features, more && last ? encodeCursor([last.departed_at, last.id]) : null);
  return {...result, meta: {...result.meta, trips: shown.length}};
}

type CellRow = {id: string; module: string; params_json: string; cell_id: string; lat: number; lon: number; season: string; season_part: string | null; kind: string;
  vessels_n: number; events_n: number; dwell_min: number; first_date: string | null; last_date: string | null; rights: string; computed_at: string};

/** Aggregate cells as Polygon (rectangle) features, most dwell first. */
export async function mapHeat(db: D1Database, q: MapQuery): Promise<MapPage> {
  const w = new Where();
  w.add('a.region=?', q.region);
  w.add('a.module=?', q.module);
  if (q.bbox) w.add('a.lon>=? AND a.lat>=? AND a.lon<=? AND a.lat<=?', ...q.bbox);
  // A cell overlaps the range when its dates do; a cell without dates is kept.
  if (q.from) w.add('(a.last_date IS NULL OR a.last_date>=?)', q.from);
  if (q.to) w.add('(a.first_date IS NULL OR a.first_date<=?)', q.to);
  w.in('a.kind', q.kind);
  if (q.season) w.add('a.season=?', q.season);
  if (!q.season_part) w.add('a.season_part IS NULL');
  else if (q.season_part !== 'all') w.add('a.season_part=?', q.season_part);
  if (q.cursor) w.add('(a.dwell_min<? OR (a.dwell_min=? AND a.id>?))', Number(q.cursor[0]), Number(q.cursor[0]), q.cursor[1]!);
  const rows = (await db.prepare(`SELECT a.id, a.module, a.params_json, a.cell_id, a.lat, a.lon, a.season, a.season_part, a.kind, a.vessels_n, a.events_n,
      a.dwell_min, a.first_date, a.last_date, a.rights, a.computed_at
    FROM fleet_aggregates a WHERE ${w.sql} ORDER BY a.dwell_min DESC, a.id ASC LIMIT ?`).bind(...w.args, q.limit + 1).all<CellRow>()).results;
  const more = rows.length > q.limit, shown = rows.slice(0, q.limit);
  const features: Feature[] = shown.map(r => ({type: 'Feature', id: r.id, geometry: {type: 'Polygon', coordinates: [cellRing(r.lat, r.lon, cellSize(r.params_json))]}, properties: {
    layer: 'heat', id: r.id, cell_id: r.cell_id, module: r.module, kind: r.kind, season: r.season, season_part: r.season_part,
    vessels_n: r.vessels_n, events_n: r.events_n, dwell_min: r.dwell_min, first_date: r.first_date, last_date: r.last_date, computed_at: r.computed_at,
    basis: BASIS, rights: r.rights, planning_only: planning(r.rights)}}));
  const ignored: string[] = IGNORED_BY_HEAT.filter(name => q[name].length > 0);
  if (q.from && shown.some(r => r.last_date === null)) ignored.push('from');
  if (q.to && shown.some(r => r.first_date === null)) ignored.push('to');
  const last = shown.at(-1);
  return page('heat', q, features, more && last ? encodeCursor([last.dwell_min, last.id]) : null, ignored);
}

/** The values the filter card offers for a region, read from the activity tables. */
export async function mapFilters(db: D1Database, region: string): Promise<Record<string, unknown>> {
  const values = async (sql: string, ...args: string[]): Promise<string[]> =>
    (await db.prepare(sql).bind(...args).all<{v: string | null}>()).results.map(r => r.v).filter((v): v is string => typeof v === 'string' && v !== '');
  const vessels = (await db.prepare(`SELECT v.id, v.name, v.slug, v.vessel_class, v.port_id FROM fleet_vessels v
      WHERE v.id IN (SELECT vessel_id FROM fleet_trips WHERE region=? UNION SELECT vessel_id FROM fleet_events WHERE region=?)
      ORDER BY v.name_norm, v.id LIMIT ?`).bind(region, region, MAX_FILTER_VESSELS + 1)
    .all<{id: string; name: string; slug: string; vessel_class: string | null; port_id: string | null}>()).results;
  const range = await db.prepare('SELECT MIN(local_date) AS min, MAX(local_date) AS max FROM fleet_trips WHERE region=?').bind(region).first<{min: string | null; max: string | null}>();
  const rights = await values(`SELECT rights AS v FROM fleet_events WHERE region=? UNION SELECT rights FROM fleet_trips WHERE region=?
    UNION SELECT rights FROM fleet_aggregates WHERE region=? ORDER BY 1`, region, region, region);
  return {
    region,
    vessels: vessels.slice(0, MAX_FILTER_VESSELS).map(v => ({id: v.id, name: v.name, slug: v.slug, vessel_class: v.vessel_class, port_id: v.port_id})),
    truncated: vessels.length > MAX_FILTER_VESSELS,   // the vessel list stopped at the cap
    ports: await values(`SELECT port_id AS v FROM fleet_events WHERE region=? UNION SELECT depart_port_id FROM fleet_trips WHERE region=?
      UNION SELECT return_port_id FROM fleet_trips WHERE region=? ORDER BY 1`, region, region, region),
    classes: await values(`SELECT vessel_class AS v FROM fleet_events WHERE region=? UNION SELECT v.vessel_class FROM fleet_trips t
      JOIN fleet_vessels v ON v.id=t.vessel_id WHERE t.region=? ORDER BY 1`, region, region),
    trip_types: await values(`SELECT trip_type AS v FROM fleet_events WHERE region=? UNION SELECT trip_type_inferred FROM fleet_trips WHERE region=? ORDER BY 1`, region, region),
    kinds: await values('SELECT DISTINCT kind AS v FROM fleet_events WHERE region=? ORDER BY 1', region),
    seasons: await values('SELECT season AS v FROM fleet_events WHERE region=? UNION SELECT season FROM fleet_trips WHERE region=? ORDER BY 1 DESC', region, region),
    season_parts: await values('SELECT season_part AS v FROM fleet_events WHERE region=? UNION SELECT season_part FROM fleet_trips WHERE region=? ORDER BY 1', region, region),
    sources: await values('SELECT source AS v FROM fleet_events WHERE region=? UNION SELECT source FROM fleet_trips WHERE region=? ORDER BY 1', region, region),
    modules: await values('SELECT DISTINCT module AS v FROM fleet_aggregates WHERE region=? ORDER BY 1', region),
    dates: {min: range?.min ?? null, max: range?.max ?? null},
    rights, planning_only_rights: PLANNING_ONLY, basis: BASIS, caps: CAPS,
  };
}

/** GET /api/fleet/map/:layer, registered in adminRoutes after requireAdmin. */
export async function fleetMap(c: Context<AppEnv>): Promise<Response> {
  const settings = fleetSettings(c.env), layer = c.req.param('layer') as Layer;
  // fleetGate already answered 404 for these; checked again so the handler never depends on mount order.
  if (!settings.enabled || !settings.mapEnabled || !(LAYERS as readonly string[]).includes(layer)) return json({error: 'Not found'}, 404);
  if (!c.env.DB) return json({error: 'This service is temporarily unavailable.'}, 503);
  const params = c.req.query();
  if (layer === 'filters') {
    if (!REGION.test(params.region ?? '')) return json({error: 'region is required'}, 400);
    return json(await mapFilters(c.env.DB, params.region!));
  }
  const q = mapQuery(layer, params);
  if ('error' in q) return json({error: q.error}, 400);
  return json(await (layer === 'events' ? mapEvents : layer === 'tracks' ? mapTracks : mapHeat)(c.env.DB, q));
}

function parseJson(text: string | null): unknown {
  if (text === null) return null;
  try { return JSON.parse(text); } catch { return null; }
}

/** Google encoded polyline (precision 5) to GeoJSON [lon, lat] pairs; [] if malformed. */
export function decodePolyline(encoded: string, precision = 5): [number, number][] {
  const factor = 10 ** precision, out: [number, number][] = [];
  let index = 0, lat = 0, lon = 0;
  const next = (): number | null => {
    let result = 0, shift = 0, byte: number;
    do {
      if (index >= encoded.length) return null;
      byte = encoded.charCodeAt(index++) - 63;
      if (byte < 0 || byte > 63 || shift > 30) return null;
      result |= (byte & 0x1f) << shift;
      shift += 5;
    } while (byte >= 0x20);
    return result & 1 ? ~(result >> 1) : result >> 1;
  };
  while (index < encoded.length) {
    const dLat = next(), dLon = next();
    if (dLat === null || dLon === null) return [];
    lat += dLat; lon += dLon;
    out.push([Number((lon / factor).toFixed(precision)), Number((lat / factor).toFixed(precision))]);
  }
  return out;
}

/** True when the line's bounding box overlaps bbox. */
function intersects(coordinates: [number, number][], [w, s, e, n]: [number, number, number, number]): boolean {
  let minLon = Infinity, minLat = Infinity, maxLon = -Infinity, maxLat = -Infinity;
  for (const [lon, lat] of coordinates) { minLon = Math.min(minLon, lon); maxLon = Math.max(maxLon, lon); minLat = Math.min(minLat, lat); maxLat = Math.max(maxLat, lat); }
  return minLon <= e && maxLon >= w && minLat <= n && maxLat >= s;
}

/** A cell's edge in metres from its params_json (resolution_m), else the 1 km default (§ 3 thresholds.aggregate). */
function cellSize(paramsJson: string): number {
  const params = parseJson(paramsJson) as {resolution_m?: unknown} | null;
  const size = params && typeof params === 'object' ? Number(params.resolution_m) : NaN;
  return Number.isFinite(size) && size > 0 && size <= 100_000 ? size : DEFAULT_CELL_M;
}

/** A closed rectangle ring of `size` metres centred on (lat, lon), equirectangular. */
function cellRing(lat: number, lon: number, size: number): [number, number][] {
  const dLat = size / 2 / 111_320, dLon = size / 2 / (111_320 * Math.max(Math.cos(lat * Math.PI / 180), 0.01));
  const r = (v: number): number => Number(v.toFixed(6));
  return [[r(lon - dLon), r(lat - dLat)], [r(lon + dLon), r(lat - dLat)], [r(lon + dLon), r(lat + dLat)], [r(lon - dLon), r(lat + dLat)], [r(lon - dLon), r(lat - dLat)]];
}
