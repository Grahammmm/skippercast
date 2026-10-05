// Charter fleet AIS watch list job routes (docs/plans/charter-fleet/design.md § 11, § 12;
// CF-46): what the processor's matcher (src/skippercast/fleet/ais/match.py) reads and
// pushes each run. Behind fleetGate and requireFleetJob (server/routes/fleet.ts); this
// module holds the work.
//
//   GET /api/fleet/jobs/watch?region=<id>&cursor=<mmsi>&status=<candidate|watched|rejected>
//     The region's fleet_ais_watch rows by MMSI, PAGE a page; `next` is the cursor of
//     the following page, null after the last. The processor writes the watched MMSIs
//     to the listener's watch.json.
//   POST /api/fleet/jobs/watch {region, run_id, rows?, ops?}
//     rows (<= 500): fleet_ais_watch upserts keyed (region, mmsi). first_seen_at keeps
//       the earliest and last_seen_at the latest; updated_at moves only when a value
//       changes, so the same request twice changes nothing. A `watched` row needs a
//       vessel of this region and is refused when the MMSI is another vessel's
//       registry MMSI or the vessel holds a different one: AIS never overrides the
//       registry (fleet_vessels.mmsi). An `admin` row needs its vessel to hold that
//       MMSI with `mmsi` pinned (what a set-mmsi decision or an admin edit leaves);
//       only such a row changes a stored `rejected` one (an admin's reject-mmsi).
//     ops (<= 500): registry operations, limited to what matching may write:
//       fact.upsert with method `ais`, source `ais-static` and a field under `ais.`
//       (disagreeing statics; no resolver rule reads them and profiles never show
//       them), and review.open of kind `mmsi`. Validated and applied by
//       registry.ts exactly as POST /api/fleet/jobs/registry would.
//   200 {ok, rows, changed, ops?}; 400 {error} (or {error, errors} for ops) with nothing written.
import {body} from '../http.ts';
import {ClientError} from '../errors.ts';
import {applyRegistry, MAX_OPS, MAX_PARAMS, REGION, RUN_ID, validateRegistry} from './registry.ts';
import type {OpFailure, Validated} from './registry.ts';

export const MAX_WATCH_BYTES = 1024 * 1024;
export const MAX_ROWS = 500;
export const PAGE = 1000;
export const WATCH_STATUSES = ['candidate', 'watched', 'rejected'] as const;
export const MATCH_METHODS = ['fcc-uls', 'call-sign', 'ais-static-name', 'geofence-presence', 'admin'] as const;
const SOURCES = ['aisstream', 'marinecadastre', 'datalastic'] as const;
const MMSI = /^[1-9]\d{0,8}$/;
const HEX32 = /^[0-9a-f]{32}$/;
const ISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/;
const CALL = /^[A-Z0-9]{1,16}$/;
const COLUMNS = ['region', 'mmsi', 'vessel_id', 'match_method', 'confidence', 'status', 'ais_name', 'ais_call_sign', 'ais_class',
  'first_seen_at', 'last_seen_at', 'last_seen_source', 'positions_30d', 'updated_at'] as const;

/** Test seam: the clock for updated_at. */
export const watchDeps: {now: () => Date} = {now: () => new Date()};

type SqlValue = string | number | null;
type Row = Record<string, SqlValue>;
type Result = {status: number; body: Record<string, unknown>};
class Invalid extends Error {}

/** GET /api/fleet/jobs/watch. */
export async function watchList(db: D1Database, region: string | undefined, cursor: string | undefined, status: string | undefined): Promise<Result> {
  if (!region || !REGION.test(region)) return {status: 400, body: {error: 'invalid region'}};
  const after = cursor ?? '';
  if (after !== '' && !MMSI.test(after)) return {status: 400, body: {error: 'invalid cursor'}};
  if (status !== undefined && !(WATCH_STATUSES as readonly string[]).includes(status)) return {status: 400, body: {error: 'invalid status'}};
  const filter = status === undefined ? '' : ' AND status=?';
  const rows = (await db.prepare(`SELECT ${COLUMNS.filter(c => c !== 'region').join(',')} FROM fleet_ais_watch WHERE region=? AND mmsi>?${filter} ORDER BY mmsi LIMIT ?`)
    .bind(...[region, after, ...status === undefined ? [] : [status], PAGE + 1]).all<Row>()).results;
  const page = rows.slice(0, PAGE);
  return {status: 200, body: {region, rows: page, next: rows.length > PAGE ? page[page.length - 1]!.mmsi : null}};
}

const text = (v: unknown, max: number, re?: RegExp): boolean => typeof v === 'string' && v.length > 0 && v.length <= max && (!re || re.test(v));
const oneOf = (values: readonly string[], v: unknown): boolean => typeof v === 'string' && values.includes(v);
const iso = (v: unknown): boolean => typeof v === 'string' && ISO.test(v) && Number.isFinite(Date.parse(v));

/** One watch row with exactly its columns, or throws Invalid. */
function checkRow(raw: unknown, i: number, region: string): Row {
  const where = `rows[${i}]`;
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Invalid(`${where}: not an object`);
  const v = raw as Record<string, unknown>;
  const extra = Object.keys(v).find(k => !(COLUMNS as readonly string[]).includes(k) || k === 'region' || k === 'updated_at');
  if (extra) throw new Invalid(`${where}: unknown field ${extra}`);
  const nullable = (key: string, ok: (x: unknown) => boolean) => { if (v[key] !== null && v[key] !== undefined && !ok(v[key])) throw new Invalid(`${where}.${key}: invalid`); };
  const required = (key: string, ok: (x: unknown) => boolean) => { if (!ok(v[key])) throw new Invalid(`${where}.${key}: invalid`); };
  required('mmsi', x => text(x, 9, MMSI));
  nullable('vessel_id', x => text(x, 32, HEX32));
  required('match_method', x => oneOf(MATCH_METHODS, x));
  required('confidence', x => typeof x === 'number' && Number.isFinite(x) && x >= 0 && x <= 1);
  required('status', x => oneOf(WATCH_STATUSES, x));
  nullable('ais_name', x => text(x, 64) && (x as string).trim() === x);
  nullable('ais_call_sign', x => text(x, 16, CALL));
  nullable('ais_class', x => oneOf(['A', 'B'], x));
  required('first_seen_at', iso);
  required('last_seen_at', iso);
  nullable('last_seen_source', x => oneOf(SOURCES, x));
  nullable('positions_30d', x => Number.isInteger(x) && (x as number) >= 0 && (x as number) < 1e9);
  if ((v.first_seen_at as string) > (v.last_seen_at as string)) throw new Invalid(`${where}: first_seen_at after last_seen_at`);
  if (v.status === 'watched' && (v.vessel_id === null || v.vessel_id === undefined)) throw new Invalid(`${where}: a watched row needs a vessel_id`);
  const row: Row = {region};
  for (const key of COLUMNS) if (key !== 'region' && key !== 'updated_at') row[key] = (v[key] ?? null) as SqlValue;
  row.positions_30d ??= 0;
  return row;
}

/** Only the operations matching may write (header). */
function checkOps(ops: unknown[]): OpFailure[] {
  const errors: OpFailure[] = [];
  ops.forEach((raw, index) => {
    const op = raw && typeof raw === 'object' && !Array.isArray(raw) ? raw as Record<string, unknown> : {};
    if (op.op === 'fact.upsert') {
      if (op.method !== 'ais' || op.source_id !== 'ais-static' || typeof op.field !== 'string' || !op.field.startsWith('ais.') || 'supersedes' in op)
        errors.push({index, op: 'fact.upsert', error: 'matching writes only method ais facts from ais-static under ais.*'});
    } else if (op.op === 'review.open') {
      if (op.kind !== 'mmsi') errors.push({index, op: 'review.open', error: 'matching opens only mmsi reviews'});
    } else errors.push({index, op: typeof op.op === 'string' ? op.op : null, error: 'only fact.upsert and review.open'});
  });
  return errors;
}

const marks = (n: number): string => Array(n).fill('?').join(',');
/** True when a stored pinned_json is an object pinning `mmsi` (an unreadable one pins nothing here). */
function pinsMmsi(text: string): boolean {
  try { const v = JSON.parse(text) as unknown; return !!v && typeof v === 'object' && !Array.isArray(v) && Object.hasOwn(v, 'mmsi'); }
  catch { return false; }
}

/** POST /api/fleet/jobs/watch. */
export async function watchUpdate(db: D1Database, request: Request): Promise<Result> {
  let raw: Record<string, unknown>;
  try { raw = await body(request, MAX_WATCH_BYTES); }
  catch (error) {
    if (error instanceof ClientError) return {status: error.message === 'body too large' ? 413 : 400, body: {error: error.message}};
    throw error;
  }
  const {region, run_id: runId, rows: r, ops: o, ...extra} = raw;
  try {
    if (Object.keys(extra).length) throw new Invalid(`unknown field: ${Object.keys(extra)[0]}`);
    if (typeof region !== 'string' || !REGION.test(region)) throw new Invalid('invalid region');
    if (typeof runId !== 'string' || !RUN_ID.test(runId)) throw new Invalid('invalid run_id');
    if (r !== undefined && !Array.isArray(r)) throw new Invalid('rows must be an array');
    if (o !== undefined && !Array.isArray(o)) throw new Invalid('ops must be an array');
    const given = (r ?? []) as unknown[], ops = (o ?? []) as unknown[];
    if (given.length > MAX_ROWS) return {status: 413, body: {error: `at most ${MAX_ROWS} rows per request`}};
    if (ops.length > MAX_OPS) return {status: 413, body: {error: `at most ${MAX_OPS} operations per request`}};
    if (!given.length && !ops.length) throw new Invalid('nothing to do');
    const rows = given.map((x, i) => checkRow(x, i, region));
    if (new Set(rows.map(x => x.mmsi)).size !== rows.length) throw new Invalid('rows: an MMSI appears twice');

    // References: every vessel in this region; a watched row never contradicts the registry's MMSIs.
    const vesselIds = [...new Set(rows.map(x => x.vessel_id).filter((x): x is string => typeof x === 'string'))];
    const vessels = new Map<string, string | null>(), adminMmsi = new Map<string, string>();
    for (let i = 0; i < vesselIds.length; i += MAX_PARAMS - 1) {
      const part = vesselIds.slice(i, i + MAX_PARAMS - 1);
      for (const v of (await db.prepare(`SELECT id,mmsi,pinned_json FROM fleet_vessels WHERE region=? AND id IN (${marks(part.length)})`).bind(region, ...part)
        .all<{id: string; mmsi: string | null; pinned_json: string}>()).results) {
        vessels.set(v.id, v.mmsi);
        if (v.mmsi && pinsMmsi(v.pinned_json)) adminMmsi.set(v.id, v.mmsi);
      }
    }
    const watched = rows.filter(x => x.status === 'watched'), holders = new Map<string, string[]>();
    const mmsis = [...new Set(watched.map(x => x.mmsi as string))];
    for (let i = 0; i < mmsis.length; i += MAX_PARAMS - 1) {
      const part = mmsis.slice(i, i + MAX_PARAMS - 1);
      for (const v of (await db.prepare(`SELECT id,mmsi FROM fleet_vessels WHERE region=? AND status<>'excluded' AND mmsi IN (${marks(part.length)})`).bind(region, ...part)
        .all<{id: string; mmsi: string}>()).results) holders.set(v.mmsi, [...holders.get(v.mmsi) ?? [], v.id]);
    }
    rows.forEach((x, i) => {
      if (x.vessel_id !== null && !vessels.has(x.vessel_id as string)) throw new Invalid(`rows[${i}].vessel_id: unknown vessel in region ${region}`);
      if (x.match_method === 'admin' && adminMmsi.get(x.vessel_id as string) !== x.mmsi) throw new Invalid(`rows[${i}]: an admin match needs the vessel's pinned registry MMSI`);
      if (x.status !== 'watched') return;
      if ((holders.get(x.mmsi as string) ?? []).some(id => id !== x.vessel_id)) throw new Invalid(`rows[${i}]: ${x.mmsi} is another vessel's registry MMSI`);
      const own = vessels.get(x.vessel_id as string);
      if (own && own !== x.mmsi) throw new Invalid(`rows[${i}]: the vessel's registry MMSI is ${own}`);
    });

    // Operations are validated before anything is written, then applied after the rows.
    let validated: Validated | null = null;
    if (ops.length) {
      const refused = checkOps(ops);
      if (refused.length) return {status: 400, body: {error: 'invalid operations', errors: refused.slice(0, 50)}};
      validated = await validateRegistry(db, {region, runId, ops});
      if (!validated.ok) return {status: 400, body: {error: 'invalid operations', errors: validated.errors}};
    }

    const now = watchDeps.now().toISOString(), cols = [...COLUMNS], t = 'fleet_ais_watch';
    const updatable = cols.filter(c => !['region', 'mmsi', 'updated_at'].includes(c));
    const expr = (c: string) => c === 'first_seen_at' ? `MIN(${t}.${c},excluded.${c})` : c === 'last_seen_at' ? `MAX(${t}.${c},excluded.${c})` : `excluded.${c}`;
    const changed = updatable.map(c => `(${expr(c)}) IS NOT ${t}.${c}`).join(' OR ');
    const adminHolds = `EXISTS (SELECT 1 FROM fleet_vessels v WHERE v.id=excluded.vessel_id AND v.mmsi=excluded.mmsi AND json_valid(v.pinned_json)
      AND json_type(v.pinned_json)='object' AND json_type(v.pinned_json,'$.mmsi') IS NOT NULL)`;
    const keep = `NOT (${t}.status='rejected' AND excluded.status<>'rejected' AND NOT (excluded.match_method='admin' AND ${adminHolds}))`;
    const tail = ` ON CONFLICT(region,mmsi) DO UPDATE SET ${updatable.map(c => `${c}=${expr(c)}`).join(',')},updated_at=excluded.updated_at WHERE ${keep} AND (${changed})`;
    const size = Math.floor(MAX_PARAMS / cols.length), statements: D1PreparedStatement[] = [];
    for (let i = 0; i < rows.length; i += size) {
      const part = rows.slice(i, i + size);
      statements.push(db.prepare(`INSERT INTO ${t}(${cols.join(',')}) VALUES ${part.map(() => `(${marks(cols.length)})`).join(',')}${tail}`)
        .bind(...part.flatMap(x => cols.map(c => c === 'updated_at' ? now : x[c] ?? null))));
    }
    const results = statements.length ? await db.batch(statements) : [];
    const out: Record<string, unknown> = {ok: true, rows: rows.length, changed: results.reduce((n, x) => n + Number(x.meta?.changes ?? 0), 0)};
    if (validated?.ok) {
      const applied = await applyRegistry(db, {region, runId, ops}, validated.rows, now);
      out.ops = {count: ops.length, changed: applied.changed, counts: applied.counts};
    }
    return {status: 200, body: out};
  } catch (error) {
    if (error instanceof Invalid) return {status: 400, body: {error: error.message}};
    throw error;
  }
}

