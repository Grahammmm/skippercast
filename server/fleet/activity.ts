// Charter fleet AIS job routes (docs/plans/charter-fleet/design.md § 11, § 12, § 18): what
// the processor (src/skippercast/fleet/ais/process.py, fleet-ais.yml) pushes and what the
// hosted health check (fleet-health.yml) reads. Behind fleetGate and requireFleetJob
// (server/routes/fleet.ts); this module holds the work. Bodies <= 1 MB; statements bind
// at most 100 parameters and each request's statements run in one D1 batch.
//
//   POST /api/fleet/jobs/activity  {region, source?, replace?, trips?, segments?, events?, aggregates?, processed?}
//     replace: [{mmsi, from, to}] (<= 50). For each window, deletes this region's and
//       source's trips of that MMSI departing in [from, to) with their segments and
//       events, then inserts `trips`, `segments` and `events`, so the same request twice
//       leaves the same rows and nothing outside the windows is touched. Every trip must
//       fall in a window of its MMSI and carry the request's source; segments and events
//       must belong to the request's trips; ids must be the derived ones (design § 5);
//       trip vessels must be this region's. Labels (fleet_segment_labels) are never touched.
//     aggregates: {season, cells, delete?, prune?}: upserts cells (by id), deletes the
//       listed cell ids of that season, and with `prune` (a computed_at) deletes the
//       season's cells computed at any other time (a full rebuild).
//     processed: {run_id, counts}: job_state fleet.ais.<region>.processed = {at, run_id, counts}.
//   POST /api/fleet/jobs/heartbeat {region, heartbeat, hours, messages_24h}
//     heartbeat (the listener's heartbeat.json, selected fields, or null): job_state
//     fleet.ais.<region>.heartbeat = {...heartbeat, received_at, messages_24h}. hours
//     (<= 72): fleet_ais_hours rows keyed (region, hour), hour an ISO UTC hour start
//     ('2026-10-05T09:00:00.000Z'). Writes an Analytics Engine `fleet_ais` point.
//   GET /api/fleet/jobs/health?region=<id>
//     Staleness booleans and ages only: {region, checked_at, stale_after_s, stale,
//     checks: {heartbeat, last_message, processed: {age_s, stale}}}. A check is stale
//     when its time is unknown or more than STALE_HOURS (3) old.
import {body} from '../http.ts';
import {ClientError} from '../errors.ts';
import {recordFleetAis} from '../analytics.ts';
import {sha256} from '../advisor/ids.ts';
import type {Env} from '../env.ts';
import {FLEET_ENUMS, MAX_PARAMS, REGION, RUN_ID} from './registry.ts';

export const MAX_ACTIVITY_BYTES = 1024 * 1024;
export const LIMITS = {windows: 50, trips: 200, segments: 4000, events: 2000, cells: 1000, hours: 72} as const;
export const STALE_HOURS = 3;
export const BASIS = 'inferred-from-movement';
export const heartbeatKey = (region: string): string => `fleet.ais.${region}.heartbeat`;
export const processedKey = (region: string): string => `fleet.ais.${region}.processed`;

/** Test seam: the clock for received_at, processed.at and health ages. */
export const activityDeps: {now: () => Date} = {now: () => new Date()};

type SqlValue = string | number | null;
type Row = Record<string, SqlValue>;
type Result = {status: number; body: Record<string, unknown>};
class Invalid extends Error {}

const ENUMS: Record<string, readonly string[]> = {
  source: ['aisstream', 'marinecadastre', 'datalastic'], rights: FLEET_ENUMS.rights, status: ['open', 'closed', 'truncated'],
  segment: ['in-port', 'transit', 'fishing-drift', 'fishing-troll', 'gap'], event: ['drift-anchor', 'troll'],
  basis: [BASIS], vesselClass: FLEET_ENUMS.vesselClass, tripType: FLEET_ENUMS.tripType,
};
const PATTERNS: Record<string, RegExp> = {
  id: /^[0-9a-f]{32}$/, iso: /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/, hour: /^\d{4}-\d{2}-\d{2}T\d{2}:00:00\.000Z$/,
  time: /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$/, day: /^\d{4}-\d{2}-\d{2}$/, season: /^\d{4}$/,
  mmsi: /^[1-9]\d{0,8}$/, token: /^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$/,
};
const TIMES = new Set(['iso', 'hour', 'time']);

function valid(kind: string, v: unknown): boolean {
  if (kind.startsWith('enum:')) return ENUMS[kind.slice(5)]!.includes(v as string);
  if (kind in PATTERNS) return typeof v === 'string' && PATTERNS[kind]!.test(v) && (!TIMES.has(kind) || Number.isFinite(Date.parse(v)));
  if (kind === 'text') return typeof v === 'string' && v.length <= 200_000;
  if (kind === 'bool') return typeof v === 'boolean';
  if (typeof v !== 'number' || !Number.isFinite(v)) return false;
  if (kind === 'int') return Number.isInteger(v) && v >= 0 && v < 1e12;
  if (kind === 'lat') return Math.abs(v) <= 90;
  if (kind === 'lon') return Math.abs(v) <= 180;
  return kind === 'num' && Math.abs(v) < 1e9;
}

/** The row with exactly `spec`'s columns; a kind ending '?' may be null or absent. */
function check(spec: Record<string, string>, raw: unknown, where: string): Row {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Invalid(`${where}: not an object`);
  const value = raw as Record<string, unknown>, row: Row = {};
  const extra = Object.keys(value).find(k => !(k in spec));
  if (extra) throw new Invalid(`${where}: unknown field ${extra}`);
  for (const [key, kind] of Object.entries(spec)) {
    const v = value[key], optional = kind.endsWith('?');
    if (v === undefined || v === null) {
      if (!optional) throw new Invalid(`${where}.${key}: required`);
      row[key] = null;
    } else if (!valid(optional ? kind.slice(0, -1) : kind, v)) throw new Invalid(`${where}.${key}: invalid`);
    else row[key] = typeof v === 'boolean' ? Number(v) : v as SqlValue;
  }
  return row;
}

const TRIP = {id: 'id', region: 'token', vessel_id: 'id', mmsi: 'mmsi', depart_port_id: 'token?', return_port_id: 'token?',
  departed_at: 'iso', returned_at: 'iso?', local_date: 'day', season: 'season', season_part: 'token?', status: 'enum:status',
  trip_type_inferred: 'enum:tripType?', distance_nm: 'num?', max_offshore_nm: 'num?', fishing_min: 'int?', positions_n: 'int?',
  gap_min: 'int?', source: 'enum:source', rights: 'enum:rights', classifier_version: 'token', computed_at: 'iso'};
const SEGMENT = {id: 'id', trip_id: 'id', seq: 'int', kind: 'enum:segment', started_at: 'iso', ended_at: 'iso', geometry: 'text?',
  points_n: 'int?', mean_sog: 'num?', straightness: 'num?', heading_var: 'num?'};
const EVENT = {id: 'id', trip_id: 'id', segment_id: 'id', vessel_id: 'id', region: 'token', kind: 'enum:event', lat: 'lat', lon: 'lon',
  radius_m: 'num?', started_at: 'iso', ended_at: 'iso', dwell_min: 'int', port_id: 'token?', vessel_class: 'enum:vesselClass?',
  trip_type: 'enum:tripType?', season: 'season', season_part: 'token?', basis: 'enum:basis', source: 'enum:source',
  rights: 'enum:rights', classifier_version: 'token', species_json: 'text?'};
const CELL = {id: 'id', region: 'token', module: 'token', params_json: 'text', cell_id: 'token', lat: 'lat', lon: 'lon',
  season: 'season', season_part: 'token?', kind: 'enum:event', vessels_n: 'int', events_n: 'int', dwell_min: 'int',
  first_date: 'day?', last_date: 'day?', rights: 'enum:rights', computed_at: 'iso'};
const HOUR = {hour: 'hour', messages: 'int', watched_messages: 'int', vessels: 'int', reconnects: 'int', max_gap_s: 'int', dropped: 'int'};
const BEAT = {source: 'token?', written_at: 'time', started_at: 'time?', last_message_at: 'time?', connected: 'bool?',
  messages_per_min: 'num?', watched_messages_per_min: 'num?', vessels: 'int?', reconnects: 'int?', dropped: 'int?',
  queue_depth: 'int?', watch_size: 'int?', git_sha: 'token?'};
const WINDOW = {mmsi: 'mmsi', from: 'iso', to: 'iso'};

const marks = (n: number): string => Array(n).fill('?').join(',');
function list(value: unknown, name: string, max: number): unknown[] {
  if (value === undefined) return [];
  if (!Array.isArray(value)) throw new Invalid(`${name} must be an array`);
  if (value.length > max) throw new Invalid(`at most ${max} ${name} per request`);
  return value;
}

/** Multi-row INSERTs of `rows` (all with `columns`), chunked under MAX_PARAMS; `tail` e.g. an upsert clause. */
function inserts(db: D1Database, table: string, columns: string[], rows: Row[], tail = ''): D1PreparedStatement[] {
  const size = Math.floor(MAX_PARAMS / columns.length), out: D1PreparedStatement[] = [];
  for (let i = 0; i < rows.length; i += size) {
    const part = rows.slice(i, i + size);
    out.push(db.prepare(`INSERT INTO ${table}(${columns.join(',')}) VALUES ${part.map(() => `(${marks(columns.length)})`).join(',')}${tail}`)
      .bind(...part.flatMap(r => columns.map(c => r[c] ?? null))));
  }
  return out;
}
const upsert = (key: string, columns: string[]): string => ` ON CONFLICT(${key}) DO UPDATE SET ${columns.filter(c => !key.split(',').includes(c)).map(c => `${c}=excluded.${c}`).join(',')}`;
const id32 = async (...parts: (string | number)[]): Promise<string> => (await sha256(parts.join('|'))).slice(0, 32);

/** [the parsed JSON object, null] or [null, the 400/413 answer]. */
async function readBody(request: Request): Promise<[Record<string, unknown>, null] | [null, Result]> {
  try { return [await body(request, MAX_ACTIVITY_BYTES), null]; }
  catch (error) {
    if (error instanceof ClientError) return [null, {status: error.message === 'body too large' ? 413 : 400, body: {error: error.message}}];
    throw error;
  }
}

/** POST /api/fleet/jobs/activity. */
export async function activity(db: D1Database, request: Request): Promise<Result> {
  const [raw, refused] = await readBody(request);
  if (!raw) return refused!;
  try { return await applyActivity(db, raw); }
  catch (error) { if (error instanceof Invalid) return {status: 400, body: {error: error.message}}; throw error; }
}

async function applyActivity(db: D1Database, raw: Record<string, unknown>): Promise<Result> {
  const {region, source, replace, trips: t, segments: s, events: e, aggregates, processed, ...extra} = raw;
  if (Object.keys(extra).length) throw new Invalid(`unknown field: ${Object.keys(extra)[0]}`);
  if (typeof region !== 'string' || !REGION.test(region)) throw new Invalid('invalid region');
  const windows = list(replace, 'windows', LIMITS.windows).map((w, i) => check(WINDOW, w, `replace[${i}]`));
  const trips = list(t, 'trips', LIMITS.trips).map((r, i) => check(TRIP, r, `trips[${i}]`));
  const segments = list(s, 'segments', LIMITS.segments).map((r, i) => check(SEGMENT, r, `segments[${i}]`));
  const events = list(e, 'events', LIMITS.events).map((r, i) => check(EVENT, r, `events[${i}]`));
  if (!windows.length && (trips.length || segments.length || events.length)) throw new Invalid('trips, segments and events need replace windows');
  if (windows.length && !ENUMS.source!.includes(source as string)) throw new Invalid('invalid source');
  if (!windows.length && aggregates === undefined && processed === undefined) throw new Invalid('nothing to do');

  // Each trip inside a window of its MMSI; children inside the request; ids as derived (design § 5).
  const tripsById = new Map<string, Row>(), segmentIds = new Set<string>();
  for (const [i, w] of windows.entries()) if (!(w.from! < w.to!)) throw new Invalid(`replace[${i}]: from must be before to`);
  for (const [i, trip] of trips.entries()) {
    if (trip.region !== region || trip.source !== source) throw new Invalid(`trips[${i}]: region or source differs from the request`);
    if (!windows.some(w => w.mmsi === trip.mmsi && w.from! <= trip.departed_at! && trip.departed_at! < w.to!)) throw new Invalid(`trips[${i}]: outside every replace window of its MMSI`);
    if (trip.id !== await id32(trip.mmsi!, trip.departed_at!, trip.source!)) throw new Invalid(`trips[${i}]: id is not sha256(mmsi|departed_at|source)`);
    if (tripsById.has(trip.id as string)) throw new Invalid(`trips[${i}]: duplicate id`);
    tripsById.set(trip.id as string, trip);
  }
  for (const [i, seg] of segments.entries()) {
    if (!tripsById.has(seg.trip_id as string)) throw new Invalid(`segments[${i}]: trip not in this request`);
    if (seg.id !== await id32(seg.trip_id!, seg.seq!) || segmentIds.has(seg.id as string)) throw new Invalid(`segments[${i}]: id is not sha256(trip_id|seq) or repeats`);
    segmentIds.add(seg.id as string);
  }
  const eventIds = new Set<string>();
  for (const [i, ev] of events.entries()) {
    const trip = tripsById.get(ev.trip_id as string);
    if (!trip || !segmentIds.has(ev.segment_id as string)) throw new Invalid(`events[${i}]: trip or segment not in this request`);
    if (ev.region !== region || ev.source !== source || ev.vessel_id !== trip.vessel_id) throw new Invalid(`events[${i}]: region, source or vessel differs from its trip`);
    if (ev.id !== await id32(ev.trip_id!, ev.started_at!, ev.kind!) || eventIds.has(ev.id as string)) throw new Invalid(`events[${i}]: id is not sha256(trip_id|started_at|kind) or repeats`);
    eventIds.add(ev.id as string);
  }
  const vessels = [...new Set(trips.map(r => r.vessel_id as string))], known = new Set<string>();
  for (let i = 0; i < vessels.length; i += MAX_PARAMS - 1) {
    const part = vessels.slice(i, i + MAX_PARAMS - 1);
    for (const row of (await db.prepare(`SELECT id FROM fleet_vessels WHERE region=? AND id IN (${marks(part.length)})`).bind(region, ...part).all<{id: string}>()).results) known.add(row.id);
  }
  const unknown = vessels.find(v => !known.has(v));
  if (unknown) throw new Invalid(`unknown vessel ${unknown} in region ${region}`);

  const statements: D1PreparedStatement[] = [], kinds: string[] = [];
  const add = (kind: string, items: D1PreparedStatement[]) => { statements.push(...items); kinds.push(...items.map(() => kind)); };
  const inWindow = 'SELECT id FROM fleet_trips WHERE region=? AND source=? AND mmsi=? AND departed_at>=? AND departed_at<?';
  for (const w of windows) {
    const args = [region, source as string, w.mmsi, w.from, w.to];
    add('deleted_events', [db.prepare(`DELETE FROM fleet_events WHERE trip_id IN (${inWindow})`).bind(...args)]);
    add('deleted_segments', [db.prepare(`DELETE FROM fleet_segments WHERE trip_id IN (${inWindow})`).bind(...args)]);
    add('deleted_trips', [db.prepare('DELETE FROM fleet_trips WHERE region=? AND source=? AND mmsi=? AND departed_at>=? AND departed_at<?').bind(...args)]);
  }
  add('trips', inserts(db, 'fleet_trips', Object.keys(TRIP), trips));
  add('segments', inserts(db, 'fleet_segments', Object.keys(SEGMENT), segments));
  add('events', inserts(db, 'fleet_events', Object.keys(EVENT), events));

  if (aggregates !== undefined) {
    if (!aggregates || typeof aggregates !== 'object' || Array.isArray(aggregates)) throw new Invalid('aggregates must be an object');
    const {season, cells: c, delete: d, prune, ...more} = aggregates as Record<string, unknown>;
    if (Object.keys(more).length) throw new Invalid(`aggregates: unknown field ${Object.keys(more)[0]}`);
    if (!valid('season', season)) throw new Invalid('aggregates.season: invalid');
    const cells = list(c, 'cells', LIMITS.cells).map((r, i) => check(CELL, r, `aggregates.cells[${i}]`));
    if (cells.some(cell => cell.region !== region || cell.season !== season)) throw new Invalid('aggregates.cells: region or season differs from the request');
    const gone = list(d, 'cells', LIMITS.cells).map(id => { if (!valid('id', id)) throw new Invalid('aggregates.delete: invalid id'); return id as string; });
    if (prune !== undefined && !valid('iso', prune)) throw new Invalid('aggregates.prune: invalid');
    add('cells', inserts(db, 'fleet_aggregates', Object.keys(CELL), cells, upsert('id', Object.keys(CELL))));
    for (let i = 0; i < gone.length; i += MAX_PARAMS - 2) {
      const part = gone.slice(i, i + MAX_PARAMS - 2);
      add('deleted_cells', [db.prepare(`DELETE FROM fleet_aggregates WHERE region=? AND season=? AND id IN (${marks(part.length)})`).bind(region, season as string, ...part)]);
    }
    if (prune !== undefined) add('deleted_cells', [db.prepare('DELETE FROM fleet_aggregates WHERE region=? AND season=? AND computed_at<>?').bind(region, season as string, prune as string)]);
  }
  if (processed !== undefined) {
    const {run_id: runId, counts, ...more} = (processed && typeof processed === 'object' && !Array.isArray(processed) ? processed : {bad: 1}) as Record<string, unknown>;
    const text = JSON.stringify(counts ?? null);
    if (Object.keys(more).length || typeof runId !== 'string' || !RUN_ID.test(runId) || text.length > 4000) throw new Invalid('invalid processed');
    const at = activityDeps.now().toISOString();
    add('processed', [db.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at')
      .bind(processedKey(region), JSON.stringify({at, run_id: runId, counts: counts ?? null}), at)]);
  }
  const results = statements.length ? await db.batch(statements) : [];
  const changes: Record<string, number> = {};
  results.forEach((r, i) => { changes[kinds[i]!] = (changes[kinds[i]!] ?? 0) + Number(r.meta?.changes ?? 0); });
  return {status: 200, body: {ok: true, windows: windows.length, changes}};
}

/** POST /api/fleet/jobs/heartbeat. */
export async function heartbeat(db: D1Database, request: Request, env?: Pick<Env, 'ANALYTICS'>): Promise<Result> {
  const [raw, refused] = await readBody(request);
  if (!raw) return refused!;
  const {region, heartbeat: beat, hours: h, messages_24h: messages, ...extra} = raw;
  try {
    if (Object.keys(extra).length) throw new Invalid(`unknown field: ${Object.keys(extra)[0]}`);
    if (typeof region !== 'string' || !REGION.test(region)) throw new Invalid('invalid region');
    if (messages !== undefined && !valid('int', messages)) throw new Invalid('invalid messages_24h');
    const row = beat === null || beat === undefined ? null : check(BEAT, beat, 'heartbeat');
    const hours = list(h, 'hours', LIMITS.hours).map((r, i) => ({region, ...check(HOUR, r, `hours[${i}]`)}));
    const now = activityDeps.now(), statements = inserts(db, 'fleet_ais_hours', ['region', ...Object.keys(HOUR)], hours, upsert('region,hour', ['region', ...Object.keys(HOUR)]));
    if (row) {
      const value = {...beat as Record<string, unknown>, received_at: now.toISOString(), messages_24h: messages ?? null};
      statements.push(db.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at')
        .bind(heartbeatKey(region), JSON.stringify(value), now.toISOString()));
    }
    if (statements.length) await db.batch(statements);
    const age = (iso: SqlValue | undefined) => typeof iso === 'string' ? Math.max(0, Math.round((now.getTime() - Date.parse(iso)) / 1000)) : -1;
    recordFleetAis(env, region, {heartbeatAgeS: age(row?.written_at), lastMessageAgeS: age(row?.last_message_at), messages24h: typeof messages === 'number' ? messages : -1});
    return {status: 200, body: {ok: true, hours: hours.length, heartbeat: row !== null}};
  } catch (error) {
    if (error instanceof Invalid) return {status: 400, body: {error: error.message}};
    throw error;
  }
}

/** GET /api/fleet/jobs/health: staleness booleans and ages, nothing else. */
export async function health(db: D1Database, region: string | undefined): Promise<Result> {
  if (!region || !REGION.test(region)) return {status: 400, body: {error: 'invalid region'}};
  const rows = (await db.prepare('SELECT key,value FROM job_state WHERE key IN (?,?)').bind(heartbeatKey(region), processedKey(region))
    .all<{key: string; value: string}>()).results;
  const read = (key: string): Record<string, unknown> => { try { return JSON.parse(rows.find(r => r.key === key)?.value ?? '{}') ?? {}; } catch { return {}; } };
  const beat = read(heartbeatKey(region)), done = read(processedKey(region)), now = activityDeps.now(), limit = STALE_HOURS * 3600;
  const check = (at: unknown) => {
    const time = typeof at === 'string' ? Date.parse(at) : NaN;
    const ageS = Number.isFinite(time) ? Math.max(0, Math.floor((now.getTime() - time) / 1000)) : null;
    return {age_s: ageS, stale: ageS === null || ageS > limit};
  };
  const checks = {heartbeat: check(beat.written_at), last_message: check(beat.last_message_at), processed: check(done.at)};
  return {status: 200, body: {region, checked_at: now.toISOString(), stale_after_s: limit, stale: Object.values(checks).some(c => c.stale), checks}};
}
