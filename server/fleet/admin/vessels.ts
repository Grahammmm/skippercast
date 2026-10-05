// The fleet admin's vessel routes (docs/plans/charter-fleet/design.md § 12, § 13; CF-30).
// Mounted in routes/admin.ts behind requireUser and requireAdmin; the FLEET_ENABLED
// gate (routes/fleet.ts) runs first, so every path here 404s while the fleet is off.
//
//   GET  /api/admin/fleet/vessels       ?region= &port= &class= &status= &profile_status= &ais=watched|unwatched
//                                       &completeness_max=0..1 &cursor=   by name, 100 a page
//   GET  /api/admin/fleet/vessels/:id   the vessel with every private column, each column's value, pin and
//                                       winning fact, every fact (history included), aliases, offerings,
//                                       changes, AIS watch rows, recent trips, linked advisor boats, open reviews
//   POST /api/admin/fleet/vessels/:id   {fields?: {<column>: value|null}, unpin?: [<column>], removal_requested?: true}
//   POST /api/admin/fleet/vessels/:id/link-advisor   {boat_id, unlink?: true}
//
// An edit is an admin fact and a pin (design § 5, § 7): for each column it writes a
// fleet_vessel_facts row with source_id 'admin', source_url 'admin:<users.id>', method
// 'admin', confidence 1 and no run, supersedes the vessel's earlier admin facts for
// that field, sets the column, and adds the column to pinned_json (an object keyed by
// column: {by, at, fact_id}), so the job API never overwrites it (registry.ts). The
// job API refuses admin provenance, so this is the only writer of admin facts. Each
// edit moves the vessel's updated_at to the edit time. `unpin` releases a pin without
// changing the value; the next resolver run may then replace it. completeness is the
// resolver's to recompute. A null value clears the column and is recorded as an admin
// fact whose value is null (the admin's "no value").
import {canonicalJson, factId, valueKey} from '../ids.ts';
import type {JsonValue} from '../ids.ts';
import {checkVesselColumn} from '../registry.ts';
import type {AdminOutcome} from '../../advisor/admin/skippers.ts';
import {validId} from '../../advisor/admin/skippers.ts';

type SqlValue = string | number | null;
const HEX32 = /^[0-9a-f]{32}$/;
const REGION = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?$/;
const KEY = /^[a-z0-9][a-z0-9-]{0,63}$/;
export const VESSEL_PAGE = 100;
const DETAIL_LIMITS = {facts: 1000, changes: 100, trips: 20} as const;

/** Columns an admin may set. name needs name_norm in the same edit (the normalisation is the Python resolver's, design § 7). */
export const EDITABLE = ['name', 'name_norm', 'operator_id', 'port_id', 'landing_id', 'vessel_class', 'waters_json',
  'uscg_doc', 'state_reg', 'hull_id', 'call_sign', 'mmsi', 'year_built', 'passengers_max', 'bunks', 'length_ft', 'beam_ft', 'cruise_kn',
  'website', 'booking_url', 'booking_platform', 'phone_business', 'email_business', 'status', 'profile_status', 'map_display_consent'] as const;
export type EditableColumn = typeof EDITABLE[number];
const NOT_NULL = new Set<string>(['name', 'name_norm', 'status', 'profile_status', 'map_display_consent']);
const MAP_CONSENT = ['none', 'aggregate', 'named'];
/** The fact field (a profile path) for a column: *_json columns drop the suffix. */
export const factField = (col: string): string => col.endsWith('_json') ? col.slice(0, -5) : col;
const ADMIN_RIGHTS = 'facts-only';

export const adminSource = (by: string): string => `admin:${by}`;

/** Validate one admin edit: the stored column values (as bound) and the fact values. */
export function validateEdit(fields: unknown): {cols: Record<string, SqlValue>; values: Record<string, JsonValue>} | {error: string} {
  if (!fields || typeof fields !== 'object' || Array.isArray(fields)) return {error: 'fields must be an object'};
  const cols: Record<string, SqlValue> = {}, values: Record<string, JsonValue> = {};
  for (const [col, value] of Object.entries(fields as Record<string, unknown>)) {
    if (!(EDITABLE as readonly string[]).includes(col)) return {error: `${col}: not an editable column`};
    if (value === undefined) continue;
    if (value === null && NOT_NULL.has(col)) return {error: `${col}: cannot be cleared`};
    if (col === 'map_display_consent') {
      if (typeof value !== 'string' || !MAP_CONSENT.includes(value)) return {error: `${col}: not one of ${MAP_CONSENT.join(', ')}`};
      cols[col] = value;
    } else {
      const checked = checkVesselColumn(col, value);
      if ('error' in checked) return {error: checked.error};
      cols[col] = checked.value;
    }
    values[col] = value as JsonValue;
  }
  if (('name' in cols) !== ('name_norm' in cols)) return {error: 'name and name_norm are set together'};
  if (!Object.keys(cols).length) return {error: 'no fields to set'};
  return {cols, values};
}

/** A guard appended to each write so it runs only if `sql` (an EXISTS condition) holds, e.g. the review this decision closed. */
export interface Guard {sql: string; args: SqlValue[]}

/**
 * The statements for an admin edit of a vessel: one admin fact per column (superseding
 * the vessel's earlier admin facts for that field), the column values, the pins and
 * updated_at. Returns the fact ids by column. `guard` makes every statement conditional.
 */
export async function editStatements(db: D1Database, vessel: string, cols: Record<string, SqlValue>, values: Record<string, JsonValue>,
  by: string, now: string, guard?: Guard): Promise<{statements: D1PreparedStatement[]; facts: Record<string, string>}> {
  const statements: D1PreparedStatement[] = [], facts: Record<string, string> = {}, source = adminSource(by);
  const cond = guard ? ` AND ${guard.sql}` : '', gargs = guard?.args ?? [];
  for (const col of Object.keys(cols)) {
    const field = factField(col), value = values[col]!, key = await valueKey(value);
    const id = await factId(vessel, field, 'admin', source, key);
    facts[col] = id;
    statements.push(db.prepare(`INSERT INTO fleet_vessel_facts(id,vessel_id,field,value_json,value_key,source_id,source_url,method,confidence,rights,
        retrieved_at,first_seen_at,last_seen_at,superseded_at,superseded_by,run_id)
      SELECT ?,?,?,?,?,'admin',?,'admin',1,?,?,?,?,NULL,NULL,NULL WHERE 1${cond}
      ON CONFLICT(id) DO UPDATE SET retrieved_at=excluded.retrieved_at,last_seen_at=excluded.last_seen_at,superseded_at=NULL,superseded_by=NULL,
        method='admin',confidence=1,rights=excluded.rights`)
      .bind(id, vessel, field, canonicalJson(value), key, source, ADMIN_RIGHTS, now, now, now, ...gargs));
    statements.push(db.prepare(`UPDATE fleet_vessel_facts SET superseded_at=?,superseded_by=? WHERE vessel_id=? AND field=? AND source_id='admin'
      AND superseded_at IS NULL AND id<>?${cond}`).bind(now, id, vessel, field, id, ...gargs));
  }
  // The columns, then the pins: json_set merges into the stored object in the same statement, so a concurrent edit's pins survive.
  const names = Object.keys(cols);
  let pins = 'pinned_json';
  const pinArgs: SqlValue[] = [];
  for (const col of names) { pins = `json_set(${pins},'$."${col}"',json(?))`; pinArgs.push(JSON.stringify({by, at: now, fact_id: facts[col]})); }
  const sets = names.map(c => `${c}=?`).join(',');
  statements.push(db.prepare(`UPDATE fleet_vessels SET ${sets},pinned_json=${pins},updated_at=? WHERE id=?${cond}`)
    .bind(...names.map(c => cols[c]!), ...pinArgs, now, vessel, ...gargs));
  return {statements, facts};
}

/** True when a stored pinned_json is an object (the only shape an admin edit may merge into). */
const readablePins = (text: string): boolean => { try { const v = JSON.parse(text); return !!v && typeof v === 'object' && !Array.isArray(v); } catch { return false; } };
const parse = (text: string | null): unknown => { if (text === null) return null; try { return JSON.parse(text); } catch { return null; } };

interface VesselRow {id: string; region: string; pinned_json: string; profile_status: string; removal_requested_at: string | null; [k: string]: unknown}

/** A vessel row by id, or null. */
export async function vesselRow(db: D1Database, id: string): Promise<VesselRow | null> {
  if (!HEX32.test(id)) return null;
  return db.prepare('SELECT * FROM fleet_vessels WHERE id=?').bind(id).first<VesselRow>();
}

/** Reference checks an edit needs against D1: the operator must be in the vessel's region. */
async function checkReferences(db: D1Database, vessel: VesselRow, cols: Record<string, SqlValue>): Promise<string | null> {
  const operator = cols.operator_id;
  if (typeof operator === 'string') {
    const row = await db.prepare('SELECT region FROM fleet_operators WHERE id=?').bind(operator).first<{region: string}>();
    if (row?.region !== vessel.region) return 'operator_id: unknown operator in this region';
  }
  return null;
}

// ---- list -------------------------------------------------------------------------
export interface VesselQuery {region?: string; port?: string; class?: string; status?: string; profile_status?: string; ais?: string; completeness_max?: string; cursor?: string}
const CURSOR = /^([A-Z0-9]{1,120}):([0-9a-f]{32})$/;

/** GET /api/admin/fleet/vessels: filtered, by name_norm then id, 100 a page. */
export async function listVessels(db: D1Database, q: VesselQuery): Promise<{vessels: unknown[]; next: string | null} | {error: string}> {
  const where: string[] = [], args: SqlValue[] = [];
  if (q.region) { if (!REGION.test(q.region)) return {error: 'invalid region'}; where.push('v.region=?'); args.push(q.region); }
  if (q.port) { if (!KEY.test(q.port)) return {error: 'invalid port'}; where.push('v.port_id=?'); args.push(q.port); }
  if (q.class) {
    if (q.class === 'none') where.push('v.vessel_class IS NULL');
    else { const c = checkVesselColumn('vessel_class', q.class); if ('error' in c) return {error: 'invalid class'}; where.push('v.vessel_class=?'); args.push(q.class); }
  }
  if (q.status) { const c = checkVesselColumn('status', q.status); if ('error' in c) return {error: 'invalid status'}; where.push('v.status=?'); args.push(q.status); }
  if (q.profile_status) { const c = checkVesselColumn('profile_status', q.profile_status); if ('error' in c) return {error: 'invalid profile_status'}; where.push('v.profile_status=?'); args.push(q.profile_status); }
  const watched = "EXISTS (SELECT 1 FROM fleet_ais_watch w WHERE w.vessel_id=v.id AND w.status='watched')";
  if (q.ais === 'watched') where.push(watched);
  else if (q.ais === 'unwatched') where.push(`NOT ${watched}`);
  else if (q.ais) return {error: 'ais must be watched or unwatched'};
  if (q.completeness_max) {
    const n = Number(q.completeness_max);
    if (!Number.isFinite(n) || n < 0 || n > 1) return {error: 'completeness_max must be 0-1'};
    where.push('v.completeness<=?'); args.push(n);
  }
  if (q.cursor) {
    const m = CURSOR.exec(q.cursor);
    if (!m) return {error: 'invalid cursor'};
    where.push('(v.name_norm>? OR (v.name_norm=? AND v.id>?))'); args.push(m[1]!, m[1]!, m[2]!);
  }
  const rows = (await db.prepare(`SELECT v.id,v.region,v.slug,v.name,v.name_norm,v.operator_id,v.port_id,v.landing_id,v.vessel_class,v.mmsi,v.uscg_doc,
      v.status,v.profile_status,v.completeness,v.pinned_json,v.last_seen_at,v.updated_at,
      ${watched} AS ais_watched,
      (SELECT COUNT(*) FROM fleet_reviews r WHERE r.subject_id=v.id AND r.status='open') AS open_reviews
    FROM fleet_vessels v ${where.length ? 'WHERE ' + where.join(' AND ') : ''} ORDER BY v.name_norm,v.id LIMIT ?`)
    .bind(...args, VESSEL_PAGE + 1).all<{id: string; name_norm: string; pinned_json: string; ais_watched: number}>()).results;
  const page = rows.slice(0, VESSEL_PAGE);
  const last = page[page.length - 1];
  return {
    vessels: page.map(({pinned_json, ais_watched, ...v}) => ({...v, ais_watched: !!ais_watched, pinned: pinnedNames(pinned_json)})),
    next: rows.length > VESSEL_PAGE && last ? `${last.name_norm}:${last.id}` : null,
  };
}

/** The pinned column names ('*' when pinned_json is unreadable: every column is pinned). */
export function pinnedNames(text: string): string[] {
  const value = parse(text);
  return value && typeof value === 'object' && !Array.isArray(value) ? Object.keys(value).sort() : ['*'];
}

// ---- detail -----------------------------------------------------------------------
interface FactRow {id: string; field: string; value_json: string; source_id: string; source_url: string; method: string; confidence: number;
  rights: string; retrieved_at: string; first_seen_at: string; last_seen_at: string; superseded_at: string | null; superseded_by: string | null; run_id: string | null}

const VALUE_COLUMNS = EDITABLE.filter(c => c !== 'map_display_consent');

/** GET /api/admin/fleet/vessels/:id. */
export async function vesselDetail(db: D1Database, id: string): Promise<Record<string, unknown> | null> {
  const row = await vesselRow(db, id);
  if (!row) return null;
  const [facts, aliases, offerings, changes, watch, trips, boats, reviews, operator] = await Promise.all([
    db.prepare(`SELECT id,field,value_json,source_id,source_url,method,confidence,rights,retrieved_at,first_seen_at,last_seen_at,superseded_at,superseded_by,run_id
      FROM fleet_vessel_facts WHERE vessel_id=? ORDER BY field,superseded_at IS NOT NULL,retrieved_at DESC,id LIMIT ?`).bind(id, DETAIL_LIMITS.facts).all<FactRow>(),
    db.prepare('SELECT alias,alias_norm,kind,source_url,first_seen_at,last_seen_at FROM fleet_aliases WHERE vessel_id=? ORDER BY alias_norm').bind(id).all(),
    db.prepare('SELECT * FROM fleet_offerings WHERE vessel_id=? ORDER BY status,name').bind(id).all<Record<string, unknown>>(),
    db.prepare('SELECT id,kind,before_json,after_json,detected_at,run_id,review_id FROM fleet_changes WHERE vessel_id=? ORDER BY detected_at DESC,id LIMIT ?').bind(id, DETAIL_LIMITS.changes)
      .all<{before_json: string | null; after_json: string | null}>(),
    db.prepare('SELECT region,mmsi,match_method,confidence,status,ais_name,ais_call_sign,ais_class,first_seen_at,last_seen_at,positions_30d,updated_at FROM fleet_ais_watch WHERE vessel_id=? ORDER BY mmsi').bind(id).all(),
    db.prepare(`SELECT id,mmsi,depart_port_id,return_port_id,departed_at,returned_at,local_date,status,trip_type_inferred,distance_nm,fishing_min,source,rights
      FROM fleet_trips WHERE vessel_id=? ORDER BY departed_at DESC LIMIT ?`).bind(id, DETAIL_LIMITS.trips).all(),
    db.prepare('SELECT id,slug,name,port,status FROM advisor_boats WHERE fleet_vessel_id=? ORDER BY slug').bind(id).all(),
    db.prepare("SELECT id,kind,score,opened_at FROM fleet_reviews WHERE subject_id=? AND status='open' ORDER BY opened_at DESC,id").bind(id).all(),
    row.operator_id ? db.prepare('SELECT id,slug,name,consent_status,outreach_status FROM fleet_operators WHERE id=?').bind(row.operator_id).first() : Promise.resolve(null),
  ]);
  const pins = parse(row.pinned_json), pinAll = !pins || typeof pins !== 'object' || Array.isArray(pins);
  const pinOf = (col: string): unknown => pinAll ? true : (pins as Record<string, unknown>)[col] ?? null;
  // Each column's winning fact as the Worker can see it: a current fact whose value equals the column's,
  // an admin fact first, then the highest confidence, then the latest. The Python resolver chose the value.
  const current = facts.results.filter(f => f.superseded_at === null);
  const fields: Record<string, unknown> = {};
  for (const col of [...VALUE_COLUMNS, 'map_display_consent']) {
    const stored = row[col] as SqlValue, value = col.endsWith('_json') ? parse(stored as string | null) : stored;
    const text = value === null ? 'null' : canonicalJson(value as JsonValue), field = factField(col);
    const winner = current.filter(f => f.field === field && f.value_json === text)
      .sort((a, b) => Number(b.method === 'admin') - Number(a.method === 'admin') || b.confidence - a.confidence || b.retrieved_at.localeCompare(a.retrieved_at))[0];
    fields[col] = {value, pinned: pinOf(col), fact_id: winner?.id ?? null};
  }
  const {pinned_json, waters_json, ...vessel} = row;
  return {
    vessel: {...vessel, waters: parse(waters_json as string | null), pinned: pinnedNames(pinned_json)},
    fields,
    facts: facts.results.map(({value_json, ...f}) => ({...f, value: parse(value_json)})),
    aliases: aliases.results,
    offerings: offerings.results.map(({days_json, target_species_json, source_fact_ids_json, ...o}) =>
      ({...o, days: parse(days_json as string | null), target_species: parse(target_species_json as string | null), source_fact_ids: parse(source_fact_ids_json as string | null)})),
    changes: changes.results.map(({before_json, after_json, ...c}) => ({...c, before: parse(before_json), after: parse(after_json)})),
    watch: watch.results, trips: trips.results, advisor_boats: boats.results, open_reviews: reviews.results, operator,
  };
}

// ---- edit -------------------------------------------------------------------------
export interface EditInput {fields?: unknown; unpin?: unknown; removal_requested?: unknown}

/** POST /api/admin/fleet/vessels/:id. */
export async function editVessel(db: D1Database, id: string, input: EditInput, by: string, now: string): Promise<AdminOutcome<Record<string, unknown>>> {
  const vessel = await vesselRow(db, id);
  if (!vessel) return {status: 'not-found'};
  for (const key of Object.keys(input)) if (!['fields', 'unpin', 'removal_requested'].includes(key)) return {status: 'invalid', error: `unknown field: ${key}`};
  let edit: {cols: Record<string, SqlValue>; values: Record<string, JsonValue>} = {cols: {}, values: {}};
  if (input.fields !== undefined) {
    const checked = validateEdit(input.fields);
    if ('error' in checked) return {status: 'invalid', error: checked.error};
    edit = checked;
  }
  const unpin = input.unpin ?? [];
  if (!Array.isArray(unpin) || unpin.length > EDITABLE.length || !unpin.every(c => typeof c === 'string' && (EDITABLE as readonly string[]).includes(c)))
    return {status: 'invalid', error: 'unpin must be a list of editable columns'};
  if (unpin.some(c => c in edit.cols)) return {status: 'invalid', error: 'a column cannot be set and unpinned in one edit'};
  if (input.removal_requested !== undefined && input.removal_requested !== true) return {status: 'invalid', error: 'removal_requested must be true'};
  // An operator's removal request hides the boat (US-C3); its date is kept if the boat is later unhidden.
  const removal = input.removal_requested === true;
  if (removal && (edit.cols.profile_status ?? vessel.profile_status) !== 'hidden') return {status: 'invalid', error: 'removal_requested needs profile_status hidden'};
  if (!Object.keys(edit.cols).length && !unpin.length && !removal) return {status: 'invalid', error: 'nothing to change'};
  if (!readablePins(vessel.pinned_json)) return {status: 'conflict', error: 'pinned_json is unreadable; repair it before editing'};
  const problem = await checkReferences(db, vessel, edit.cols);
  if (problem) return {status: 'invalid', error: problem};

  const statements: D1PreparedStatement[] = [];
  if (Object.keys(edit.cols).length) statements.push(...(await editStatements(db, id, edit.cols, edit.values, by, now)).statements);
  if (unpin.length) {
    const paths = (unpin as string[]).map(c => `'$."${c}"'`).join(',');
    statements.push(db.prepare(`UPDATE fleet_vessels SET pinned_json=json_remove(pinned_json,${paths}),updated_at=? WHERE id=?`).bind(now, id));
  }
  if (removal) statements.push(db.prepare('UPDATE fleet_vessels SET removal_requested_at=COALESCE(removal_requested_at,?),updated_at=? WHERE id=?').bind(now, now, id));
  await db.batch(statements);
  return {status: 'ok', value: (await vesselDetail(db, id))!};
}

// ---- advisor link -------------------------------------------------------------------
/**
 * Link (or unlink) an advisor boat to a registry vessel: advisor_boats.fleet_vessel_id
 * (D5). One boat per vessel and one vessel per boat; linking to another vessel or a
 * vessel another boat holds is a conflict (unlink first).
 */
export async function linkStatements(db: D1Database, vesselId: string, boatId: unknown, unlink: boolean, now: string, guard?: Guard):
  Promise<{statements: D1PreparedStatement[]} | {status: 'invalid' | 'conflict'; error: string} | {status: 'not-found'}> {
  if (typeof boatId !== 'string' || !validId(boatId)) return {status: 'invalid', error: 'boat_id: invalid'};
  const boat = await db.prepare('SELECT id,fleet_vessel_id FROM advisor_boats WHERE id=?').bind(boatId).first<{id: string; fleet_vessel_id: string | null}>();
  if (!boat) return {status: 'invalid', error: 'boat_id: unknown advisor boat'};
  const cond = guard ? ` AND ${guard.sql}` : '', gargs = guard?.args ?? [];
  if (unlink) {
    if (boat.fleet_vessel_id !== vesselId) return {status: 'conflict', error: 'the boat is not linked to this vessel'};
    return {statements: [db.prepare(`UPDATE advisor_boats SET fleet_vessel_id=NULL,updated_at=? WHERE id=? AND fleet_vessel_id=?${cond}`).bind(now, boatId, vesselId, ...gargs)]};
  }
  if (boat.fleet_vessel_id && boat.fleet_vessel_id !== vesselId) return {status: 'conflict', error: 'the boat is linked to another vessel'};
  const other = await db.prepare('SELECT id FROM advisor_boats WHERE fleet_vessel_id=? AND id<>?').bind(vesselId, boatId).first<{id: string}>();
  if (other) return {status: 'conflict', error: 'another advisor boat is linked to this vessel'};
  return {statements: [db.prepare(`UPDATE advisor_boats SET fleet_vessel_id=?,updated_at=? WHERE id=? AND (fleet_vessel_id IS NULL OR fleet_vessel_id<>?)${cond}`)
    .bind(vesselId, now, boatId, vesselId, ...gargs)]};
}

/** POST /api/admin/fleet/vessels/:id/link-advisor {boat_id, unlink?: true}. */
export async function linkAdvisor(db: D1Database, id: string, input: Record<string, unknown>, now: string): Promise<AdminOutcome<Record<string, unknown>>> {
  if (!await vesselRow(db, id)) return {status: 'not-found'};
  for (const key of Object.keys(input)) if (!['boat_id', 'unlink'].includes(key)) return {status: 'invalid', error: `unknown field: ${key}`};
  if (input.unlink !== undefined && input.unlink !== true) return {status: 'invalid', error: 'unlink must be true'};
  const out = await linkStatements(db, id, input.boat_id, input.unlink === true, now);
  if ('status' in out) return out;
  await db.batch(out.statements);
  const boats = (await db.prepare('SELECT id,slug,name,port,status FROM advisor_boats WHERE fleet_vessel_id=? ORDER BY slug').bind(id).all()).results;
  return {status: 'ok', value: {vessel_id: id, advisor_boats: boats}};
}
