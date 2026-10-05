// Charter fleet registry operations (docs/plans/charter-fleet/design.md § 5, § 9):
// what POST /api/fleet/jobs/registry accepts and how it lands in the fleet_* tables.
//
// The Python pipeline resolves; the Worker validates and stores. Rules:
//   - Every operation is validated before anything is written: unknown keys,
//     enums, formats, https provenance, confidence 0-1, and references (a fact's
//     vessel must exist in the request's region or be upserted in the same
//     request). One bad operation rejects the whole request, listed by index.
//   - Upserts are keyed on deterministic ids (ids.ts), and an update runs only
//     when a stored value would change, so posting the same batch twice changes
//     no row the second time. Timestamps come from the operations, never the
//     Worker clock, except created_at (and a vessel's updated_at, which moves
//     only with a change). An older replay never overwrites a newer value: each
//     row is guarded by its recency column (vessels and aliases last_seen_at,
//     facts and departures retrieved_at, operators and offerings the op's
//     seen_at, stored as updated_at).
//   - Fields omitted from an upsert keep their stored value (an insert takes the
//     column default); a field present with null clears it.
//   - Pinned vessel fields are never overwritten: fleet_vessels.pinned_json is an
//     object keyed by column name (written by the admin API, CF-30); a pinned
//     column keeps its value, and an unreadable pinned_json pins every column.
//     A vessel whose operator asked for removal (removal_requested_at) is never
//     re-listed by a job. Jobs never write pinned_json, map_display_consent,
//     removal_requested_at, or an operator's consent, outreach or user_id.
//   - review.open never reopens or edits a decided or dismissed review, nor one
//     of another region.
//   - Facts must carry an https source_url. `admin:<users.id>` provenance is
//     written only by the admin API, so a job token cannot forge an admin fact.
//   - fact.purge deletes a retention-limited source's facts last seen before a time,
//     except the fields it keeps (Google Places: everything but place_id, CF-16);
//     only sources in PURGEABLE_SOURCES can be purged, and only in the request's region.
//   - Statements are multi-row and chunked so none binds more than D1's 100
//     parameters; the request's statements run in one D1 batch (one transaction).
import {canonicalJson, changeId, departureId, factId, reviewId, valueKey, vesselId} from './ids.ts';
import type {JsonValue} from './ids.ts';

export const MAX_OPS = 500;
export const MAX_PARAMS = 100;             // D1: bound parameters per statement
export const MAX_ERRORS = 50;              // validation errors listed in one response
export const MAX_SUPERSEDES = 20;
const MAX_JSON = 16000;                    // canonical characters per *_json value

export const OP_KINDS = ['operator.upsert', 'vessel.upsert', 'fact.upsert', 'alias.upsert', 'offering.upsert',
  'departure.upsert', 'review.open', 'change.record', 'run.record', 'fact.purge'] as const;
export type OpKind = typeof OP_KINDS[number];
type UpsertKind = Exclude<OpKind, 'fact.purge'>;
/** Sources whose facts expire under their terms (design § 5 Retention): the only ones fact.purge may delete. */
export const PURGEABLE_SOURCES = ['google-places'] as const;
const MAX_KEEP_FIELDS = 20;

export const FLEET_ENUMS = {
  vesselClass: ['six-pack', 'inspected-party', 'long-range'],
  waters: ['ocean', 'bay', 'delta', 'inland'],
  vesselStatus: ['active', 'inactive', 'sold', 'excluded'],
  profileStatus: ['listed', 'hidden'],
  method: ['page', 'api', 'search', 'inference', 'registry', 'ais', 'operator', 'admin'],
  rights: ['public-domain', 'facts-only', 'api-terms', 'public-record', 'noaa-planning-only', 'internal-only'],
  aliasKind: ['former-name', 'spelling', 'ais-name', 'report-name'],
  tripType: ['half-day', 'three-quarter-day', 'full-day', 'overnight', 'multi-day', 'private-charter', 'other'],
  priceBasis: ['per-person', 'private'],
  offeringStatus: ['active', 'retired'],
  days: ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'],
  reviewKind: ['merge', 'mmsi', 'class', 'fact-conflict', 'change', 'vanished', 'advisor-link', 'scope'],
  changeKind: ['new', 'renamed', 'sold', 'moved', 'vanished', 'returned', 'price', 'schedule', 'mmsi', 'class'],
  runStatus: ['running', 'ok', 'failed', 'partial'],
  sink: ['worker', 'staging'],
} as const;

export const REGION = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?$/;   // a regions/<id> directory name
export const RUN_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/;
const HEX32 = /^[0-9a-f]{32}$/;
const OPERATOR_ID = /^[A-Za-z0-9_-]{16,64}$/;
const SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const KEY = /^[a-z0-9][a-z0-9-]{0,63}$/;                       // port, landing, source, booking platform ids
const NORM = /^[A-Z0-9]{1,120}$/;                               // name_norm, alias_norm (design § 7)
const FIELD = /^[a-z][a-z0-9_]*(?:\[\])?(?:\.[a-z][a-z0-9_]*(?:\[\])?){0,5}$/;   // a profile path
const SPECIES = /^[a-z0-9][a-z0-9_-]{0,63}$/;
const ISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z$/;
const DATE = /^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])$/;
const HHMM = /^(?:[01]\d|2[0-3]):[0-5]\d$/;
const MMDD = /^(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])$/;
const E164 = /^\+[1-9]\d{6,14}$/;
const EMAIL = /^[^\s@<>()",;:]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$/;

type SqlValue = string | number | null;
class OpError extends Error {}
const fail = (message: string): never => { throw new OpError(message); };

// ---- field validators: each returns the stored value or throws OpError ----------
type Check = (v: unknown, name: string) => SqlValue;
const nullable = (check: Check): Check => (v, name) => v === null ? null : check(v, name);
const text = (max: number, re?: RegExp): Check => (v, name) =>
  typeof v === 'string' && v.length > 0 && v.length <= max && v.trim() === v && (!re || re.test(v)) ? v : fail(`${name}: invalid`);
const oneOf = (values: readonly string[]): Check => (v, name) => typeof v === 'string' && values.includes(v) ? v : fail(`${name}: not one of ${values.join(', ')}`);
const int = (min: number, max: number): Check => (v, name) => Number.isInteger(v) && (v as number) >= min && (v as number) <= max ? v as number : fail(`${name}: not an integer in ${min}-${max}`);
const real = (min: number, max: number): Check => (v, name) => typeof v === 'number' && Number.isFinite(v) && v >= min && v <= max ? v : fail(`${name}: not a number in ${min}-${max}`);
/** ISO-8601 UTC, stored as Date#toISOString so stored times compare as text. */
const iso: Check = (v, name) => {
  if (typeof v !== 'string' || !ISO.test(v)) return fail(`${name}: not an ISO-8601 UTC time`);
  const t = Date.parse(v); return Number.isFinite(t) ? new Date(t).toISOString() : fail(`${name}: not an ISO-8601 UTC time`);
};
const date: Check = (v, name) => typeof v === 'string' && DATE.test(v) && !Number.isNaN(Date.parse(v + 'T00:00:00Z')) ? v : fail(`${name}: not a YYYY-MM-DD date`);
export function httpsUrl(v: unknown): string | null {
  if (typeof v !== 'string' || v.length > 2048) return null;
  try { const u = new URL(v); return u.protocol === 'https:' && !u.username && !u.password && u.hostname.includes('.') ? v : null; } catch { return null; }
}
const https: Check = (v, name) => httpsUrl(v) ?? fail(`${name}: not an https URL`);
const json = (shape: (v: unknown, name: string) => void = () => {}): Check => (v, name) => {
  if (v === undefined) return fail(`${name}: missing`);
  shape(v, name);
  let text: string; try { text = canonicalJson(v as JsonValue); } catch { return fail(`${name}: not JSON`); }
  return text.length <= MAX_JSON ? text : fail(`${name}: too large`);
};
const listOf = (item: (v: unknown) => boolean, max: number, unique = true) => (v: unknown, name: string): void => {
  if (!Array.isArray(v) || v.length > max || !v.every(item) || (unique && new Set(v).size !== v.length)) fail(`${name}: invalid list`);
};
const object = (v: unknown, name: string): void => { if (!v || typeof v !== 'object' || Array.isArray(v)) fail(`${name}: not an object`); };
const container = (v: unknown, name: string): void => { if (!v || typeof v !== 'object') fail(`${name}: not an object or array`); };
const isString = (re: RegExp) => (v: unknown): boolean => typeof v === 'string' && re.test(v);
/** A fact's provenance: an https URL. `admin:` is the admin API's alone (CF-30). */
const provenance: Check = (v, name) => typeof v === 'string' && v.startsWith('admin:') ? fail(`${name}: admin provenance is written only by the admin API`) : https(v, name);

// ---- operation specs -----------------------------------------------------------
// fields: the keys an operation may carry and their checks; `required` keys must be
// present (null only where the check allows it). Keys not listed are rejected.
interface Spec { fields: Record<string, Check>; required: string[] }
const opt = (spec: Record<string, Check>) => spec;
const SPECS: Record<OpKind, Spec> = {
  'operator.upsert': {required: ['id', 'slug', 'name', 'seen_at'], fields: opt({
    id: text(64, OPERATOR_ID), seen_at: iso, slug: text(80, SLUG), name: text(120),
    website: nullable(https), phone_business: nullable(text(16, E164)), email_business: nullable(text(254, EMAIL)),
    booking_platform: nullable(text(64, KEY)), lead_score: nullable(real(0, 100)), lead_score_json: nullable(json(object)),
  })},
  'vessel.upsert': {required: ['id', 'slug', 'name', 'name_norm', 'first_seen_at', 'last_seen_at'], fields: opt({
    id: text(32, HEX32), creation_key: text(200, /^[a-z][a-z0-9-]*:\S+$/), slug: text(80, SLUG), name: text(120), name_norm: text(120, NORM),
    operator_id: nullable(text(64, OPERATOR_ID)), port_id: nullable(text(64, KEY)), landing_id: nullable(text(64, KEY)),
    vessel_class: nullable(oneOf(FLEET_ENUMS.vesselClass)), waters_json: nullable(json(listOf(v => (FLEET_ENUMS.waters as readonly unknown[]).includes(v), 4))),
    uscg_doc: nullable(text(20, /^[A-Z0-9-]+$/)), state_reg: nullable(text(20, /^[A-Z0-9-]+$/)), hull_id: nullable(text(20, /^[A-Z0-9-]+$/)),
    call_sign: nullable(text(10, /^[A-Z0-9]{3,10}$/)), mmsi: nullable(text(9, /^\d{9}$/)),
    year_built: nullable(int(1850, 2100)), passengers_max: nullable(int(0, 2000)), bunks: nullable(int(0, 500)),
    length_ft: nullable(real(1, 500)), beam_ft: nullable(real(1, 100)), cruise_kn: nullable(real(0, 60)),
    website: nullable(https), booking_url: nullable(https), booking_platform: nullable(text(64, KEY)),
    phone_business: nullable(text(16, E164)), email_business: nullable(text(254, EMAIL)),
    status: oneOf(FLEET_ENUMS.vesselStatus), profile_status: oneOf(FLEET_ENUMS.profileStatus), completeness: real(0, 1),
    first_seen_at: iso, last_seen_at: iso, last_profiled_at: nullable(iso),
  })},
  'fact.upsert': {required: ['vessel_id', 'field', 'value_json', 'source_id', 'source_url', 'method', 'confidence', 'rights', 'retrieved_at'], fields: opt({
    id: text(32, HEX32), vessel_id: text(32, HEX32), field: text(100, FIELD), value_json: json(v => { if (v === null) fail('value_json: null is not a value'); }),
    source_id: text(64, KEY), source_url: provenance, method: oneOf(FLEET_ENUMS.method.filter(m => m !== 'admin')),
    confidence: real(0, 1), rights: oneOf(FLEET_ENUMS.rights), retrieved_at: iso, first_seen_at: iso, last_seen_at: iso,
    supersedes: json(listOf(isString(HEX32), MAX_SUPERSEDES)),
  })},
  'alias.upsert': {required: ['vessel_id', 'alias', 'alias_norm', 'kind', 'source_url', 'first_seen_at', 'last_seen_at'], fields: opt({
    vessel_id: text(32, HEX32), alias: text(120), alias_norm: text(120, NORM), kind: oneOf(FLEET_ENUMS.aliasKind),
    source_url: https, first_seen_at: iso, last_seen_at: iso,
  })},
  'offering.upsert': {required: ['id', 'vessel_id', 'name', 'trip_type', 'seen_at'], fields: opt({
    id: text(32, HEX32), seen_at: iso, vessel_id: text(32, HEX32), name: text(120), trip_type: oneOf(FLEET_ENUMS.tripType),
    duration_h: nullable(real(0, 720)), price_cents: nullable(int(0, 10_000_000)), price_basis: nullable(oneOf(FLEET_ENUMS.priceBasis)),
    capacity: nullable(int(1, 2000)), currency: text(3, /^[A-Z]{3}$/), departs_local: nullable(text(5, HHMM)),
    days_json: nullable(json(listOf(v => (FLEET_ENUMS.days as readonly unknown[]).includes(v), 7))),
    season_from: nullable(text(5, MMDD)), season_to: nullable(text(5, MMDD)),
    target_species_json: nullable(json(listOf(isString(SPECIES), 50))), booking_url: nullable(https),
    status: oneOf(FLEET_ENUMS.offeringStatus), source_fact_ids_json: nullable(json(listOf(isString(HEX32), 100))),
    valid_from: nullable(date), valid_to: nullable(date),
  })},
  'departure.upsert': {required: ['offering_id', 'vessel_id', 'date', 'source_url', 'retrieved_at'], fields: opt({
    id: text(32, HEX32), offering_id: text(32, HEX32), vessel_id: text(32, HEX32), date,
    departs_local: nullable(text(5, HHMM)), price_cents: nullable(int(0, 10_000_000)), load_text: nullable(text(200)),
    source_url: https, retrieved_at: iso,
  })},
  'review.open': {required: ['kind', 'fingerprint', 'opened_at'], fields: opt({
    id: text(32, HEX32), kind: oneOf(FLEET_ENUMS.reviewKind), fingerprint: text(500), subject_id: nullable(text(64, /^[A-Za-z0-9_-]+$/)),
    candidate_json: nullable(json(container)), proposal_json: nullable(json(container)), score: nullable(real(0, 1)), opened_at: iso,
  })},
  'change.record': {required: ['vessel_id', 'kind', 'after_json', 'detected_at'], fields: opt({
    id: text(32, HEX32), vessel_id: text(32, HEX32), kind: oneOf(FLEET_ENUMS.changeKind),
    before_json: json(), after_json: json(), detected_at: iso, review_id: nullable(text(32, HEX32)),
  })},
  'run.record': {required: ['step', 'sink', 'started_at', 'status'], fields: opt({
    step: text(32, /^[a-z][a-z-]*$/), sink: oneOf(FLEET_ENUMS.sink), started_at: iso, finished_at: nullable(iso),
    status: oneOf(FLEET_ENUMS.runStatus), counts_json: nullable(json(object)), error: nullable(text(2000)),
  })},
  'fact.purge': {required: ['source_id', 'keep_fields', 'seen_before'], fields: opt({
    source_id: oneOf(PURGEABLE_SOURCES), keep_fields: json(listOf(isString(FIELD), MAX_KEEP_FIELDS)), seen_before: iso,
  })},
};

/** The vessel.upsert check for one column (the admin API's edits, CF-30): the stored value, or an error. */
export function checkVesselColumn(col: string, value: unknown): {value: SqlValue} | {error: string} {
  const check = Object.hasOwn(SPECS['vessel.upsert'].fields, col) ? SPECS['vessel.upsert'].fields[col]! : null;
  if (!check) return {error: `${col}: not a vessel column`};
  try { return {value: check(value, col)}; }
  catch (error) { if (error instanceof OpError) return {error: error.message}; throw error; }
}

/** A validated operation: its kind, its stored columns, and its index in the request. */
export interface Row { kind: OpKind; index: number; id: string; cols: Record<string, SqlValue>; supersedes?: string[] }
export interface OpFailure { index: number; op: string | null; error: string }
export interface RegistryRequest { region: string; runId: string; ops: unknown[] }
export type Validated = {ok: true; rows: Row[]} | {ok: false; errors: OpFailure[]};

/** Field-level validation of one operation (no database): the row, or throws OpError. */
async function validateOp(raw: unknown, index: number, region: string): Promise<Row> {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return fail('not an object');
  const {op, ...rest} = raw as Record<string, unknown>;
  if (typeof op !== 'string' || !(OP_KINDS as readonly string[]).includes(op)) return fail(`op: not one of ${OP_KINDS.join(', ')}`);
  const kind = op as OpKind, spec = SPECS[kind], cols: Record<string, SqlValue> = {};
  for (const key of Object.keys(rest)) if (!Object.hasOwn(spec.fields, key)) fail(`${key}: not a field of ${kind}`);
  for (const key of spec.required) if (rest[key] === undefined) fail(`${key}: missing`);
  for (const [key, value] of Object.entries(rest)) if (value !== undefined) cols[key] = spec.fields[key]!(value, key);
  const given = cols.id as string | undefined, s = (k: string) => cols[k] as string;
  const derived = async (id: string): Promise<string> => given !== undefined && given !== id ? fail(`id: does not match the derived id ${id}`) : id;
  let row: Row;
  switch (kind) {
    case 'vessel.upsert': {
      if (cols.creation_key !== undefined && await vesselId(region, s('creation_key')) !== given) fail('id: does not match sha256(region:creation_key)');
      delete cols.creation_key;
      row = {kind, index, id: s('id'), cols};
      break;
    }
    case 'fact.upsert': {
      const value = JSON.parse(s('value_json')) as JsonValue, key = await valueKey(value);
      cols.id = await derived(await factId(s('vessel_id'), s('field'), s('source_id'), s('source_url'), key));
      cols.value_key = key;
      cols.first_seen_at ??= cols.retrieved_at!; cols.last_seen_at ??= cols.retrieved_at!;
      if (s('first_seen_at') > s('last_seen_at')) fail('first_seen_at: after last_seen_at');
      const supersedes = cols.supersedes === undefined ? [] : JSON.parse(s('supersedes')) as string[];
      delete cols.supersedes;
      if (supersedes.includes(s('id'))) fail('supersedes: a fact cannot supersede itself');
      row = {kind, index, id: s('id'), cols, supersedes};
      break;
    }
    case 'alias.upsert':
      if (s('first_seen_at') > s('last_seen_at')) fail('first_seen_at: after last_seen_at');
      row = {kind, index, id: `${s('vessel_id')}|${s('alias_norm')}`, cols};
      break;
    case 'departure.upsert':
      cols.id = await derived(await departureId(s('offering_id'), s('date'), (cols.departs_local as string | null | undefined) ?? ''));
      row = {kind, index, id: s('id'), cols};
      break;
    case 'review.open':
      cols.id = await derived(await reviewId(s('kind'), s('fingerprint')));
      delete cols.fingerprint;
      row = {kind, index, id: s('id'), cols};
      break;
    case 'change.record':
      cols.id = await derived(await changeId(s('vessel_id'), s('kind'), s('after_json')));
      row = {kind, index, id: s('id'), cols};
      break;
    case 'run.record':
      row = {kind, index, id: s('step'), cols};
      break;
    case 'fact.purge':
      row = {kind, index, id: `${s('source_id')}|${s('seen_before')}|${s('keep_fields')}`, cols};
      break;
    case 'operator.upsert': case 'offering.upsert':
      cols.updated_at = cols.seen_at!; delete cols.seen_at;   // stored as updated_at, the row's recency guard
      row = {kind, index, id: s('id'), cols};
      break;
    default:
      row = {kind, index, id: s('id'), cols};
  }
  if (kind === 'vessel.upsert' && s('first_seen_at') > s('last_seen_at')) fail('first_seen_at: after last_seen_at');
  return row;
}

const marks = (n: number): string => Array(n).fill('?').join(',');
/** SELECT ... WHERE <column> IN (values), chunked under the parameter limit; `fixed` binds first. */
async function selectIn<T>(db: D1Database, sql: (marks: string) => string, values: string[], fixed: SqlValue[] = []): Promise<T[]> {
  const out: T[] = [], unique = [...new Set(values)], size = MAX_PARAMS - fixed.length;
  for (let i = 0; i < unique.length; i += size) {
    const part = unique.slice(i, i + size);
    out.push(...(await db.prepare(sql(marks(part.length))).bind(...fixed, ...part).all<T>()).results);
  }
  return out;
}

/**
 * Validate a registry request: every operation's fields, then its references
 * against D1 (vessels, operators and offerings in this region, slug uniqueness
 * across fleet and advisor boats). Duplicates of one row keep the last operation.
 */
export async function validateRegistry(db: D1Database, request: RegistryRequest): Promise<Validated> {
  const errors: OpFailure[] = [], rows: Row[] = [], {region} = request;
  const failed = (index: number, op: unknown, error: string) => {
    if (errors.length < MAX_ERRORS) errors.push({index, op: typeof op === 'string' ? op : null, error});
  };
  for (const [index, raw] of request.ops.entries()) {
    try { rows.push(await validateOp(raw, index, region)); }
    catch (error) {
      if (!(error instanceof OpError)) throw error;
      failed(index, (raw as {op?: unknown} | null)?.op, error.message);
    }
  }
  // Last operation per row wins (the earlier ones are dropped, not errors).
  const last = new Map<string, Row>();
  for (const row of rows) last.set(`${row.kind}\u0000${row.id}`, row);
  const kept = rows.filter(row => last.get(`${row.kind}\u0000${row.id}`) === row);
  const of = (kind: OpKind) => kept.filter(r => r.kind === kind);

  const vesselOps = of('vessel.upsert'), operatorOps = of('operator.upsert'), offeringOps = of('offering.upsert');
  const str = (r: Row, k: string) => r.cols[k] as string;
  const referenced = kept.filter(r => r.kind !== 'operator.upsert' && r.kind !== 'review.open' && r.kind !== 'run.record' && r.kind !== 'fact.purge')
    .map(r => r.kind === 'vessel.upsert' ? str(r, 'id') : str(r, 'vessel_id'));
  const vessels = new Map((await selectIn<{id: string; region: string; slug: string}>(db,
    m => `SELECT id,region,slug FROM fleet_vessels WHERE id IN (${m})`, referenced)).map(v => [v.id, v]));
  const batchVessels = new Set(vesselOps.map(r => r.id));
  const operatorIds = [...operatorOps.map(r => r.id), ...vesselOps.map(r => r.cols.operator_id).filter((v): v is string => typeof v === 'string')];
  const operators = new Map((await selectIn<{id: string; region: string}>(db, m => `SELECT id,region FROM fleet_operators WHERE id IN (${m})`, operatorIds)).map(o => [o.id, o]));
  const batchOperators = new Set(operatorOps.map(r => r.id));
  const offerings = new Map((await selectIn<{id: string; vessel_id: string}>(db, m => `SELECT id,vessel_id FROM fleet_offerings WHERE id IN (${m})`,
    [...of('departure.upsert').map(r => str(r, 'offering_id')), ...offeringOps.map(r => r.id)])).map(o => [o.id, o.vessel_id]));
  const batchOfferings = new Map(offeringOps.map(r => [r.id, str(r, 'vessel_id')]));

  // Slugs: unique across fleet vessels (other ids), advisor boats, and fleet operators (other ids).
  const vesselSlugs = vesselOps.map(r => str(r, 'slug')), operatorSlugs = operatorOps.map(r => str(r, 'slug'));
  const vesselSlugOwner = new Map((await selectIn<{id: string; slug: string}>(db, m => `SELECT id,slug FROM fleet_vessels WHERE slug IN (${m})`, vesselSlugs)).map(v => [v.slug, v.id]));
  const advisorSlugs = new Set((await selectIn<{slug: string}>(db, m => `SELECT slug FROM advisor_boats WHERE slug IN (${m})`, vesselSlugs)).map(b => b.slug));
  const operatorSlugOwner = new Map((await selectIn<{id: string; slug: string}>(db, m => `SELECT id,slug FROM fleet_operators WHERE slug IN (${m})`, operatorSlugs)).map(o => [o.slug, o.id]));

  const vesselKnown = (id: string) => batchVessels.has(id) || vessels.get(id)?.region === region;
  const claimed = new Map<string, string>();     // slug -> id within this request
  const ok: Row[] = [];
  for (const row of kept) {
    const err = (message: string) => failed(row.index, row.kind, message);
    const before = errors.length;
    switch (row.kind) {
      case 'operator.upsert': {
        const existing = operators.get(row.id), slug = str(row, 'slug'), owner = operatorSlugOwner.get(slug), mine = claimed.get('o:' + slug);
        if (existing && existing.region !== region) err('id: operator belongs to another region');
        if ((owner && owner !== row.id) || (mine && mine !== row.id)) err('slug: already taken');
        claimed.set('o:' + slug, row.id);
        break;
      }
      case 'vessel.upsert': {
        const existing = vessels.get(row.id), slug = str(row, 'slug'), owner = vesselSlugOwner.get(slug), mine = claimed.get('v:' + slug);
        if (existing && existing.region !== region) err('id: vessel belongs to another region');
        if ((owner && owner !== row.id) || (mine && mine !== row.id) || advisorSlugs.has(slug)) err('slug: already taken');
        claimed.set('v:' + slug, row.id);
        const operator = row.cols.operator_id;
        if (typeof operator === 'string' && !batchOperators.has(operator) && operators.get(operator)?.region !== region) err('operator_id: unknown operator in this region');
        break;
      }
      case 'departure.upsert': {
        if (!vesselKnown(str(row, 'vessel_id'))) err('vessel_id: unknown vessel in this region');
        const owner = batchOfferings.get(str(row, 'offering_id')) ?? offerings.get(str(row, 'offering_id'));
        if (owner === undefined) err('offering_id: unknown offering');
        else if (owner !== str(row, 'vessel_id')) err('offering_id: belongs to another vessel');
        break;
      }
      case 'offering.upsert': {
        if (!vesselKnown(str(row, 'vessel_id'))) err('vessel_id: unknown vessel in this region');
        const stored = offerings.get(row.id);
        if (stored !== undefined && stored !== str(row, 'vessel_id')) err('id: offering belongs to another vessel');
        break;
      }
      case 'fact.upsert': case 'alias.upsert': case 'change.record':
        if (!vesselKnown(str(row, 'vessel_id'))) err('vessel_id: unknown vessel in this region');
        break;
      default:
    }
    if (errors.length === before) ok.push(row);
  }
  if (errors.length) return {ok: false, errors: errors.sort((a, b) => a.index - b.index)};
  return {ok: true, rows: ok};
}

// ---- writes --------------------------------------------------------------------
interface Table {
  name: string;
  conflict: string;                                  // the ON CONFLICT target
  insertOnly: string[];                              // columns never changed by an update
  update?: (col: string) => string;                  // SET expression for a column (default excluded.col)
  where?: string;                                    // an extra condition for the update to run
  nothing?: boolean;                                 // ON CONFLICT DO NOTHING
  created?: boolean;                                 // created_at from the Worker clock, on insert only
  stamp?: 'clock' | 'seen';                          // updated_at: the Worker clock on a change, or the op's seen_at (moves forward only)
}

const newer = (t: string, at: string, col: string) => `CASE WHEN excluded.${at}>=${t}.${at} THEN excluded.${col} ELSE ${t}.${col} END`;
const latest = (t: string, col: string) => `MAX(${t}.${col},excluded.${col})`;
const earliest = (t: string, col: string) => `MIN(${t}.${col},excluded.${col})`;
/** True when the stored vessel's pinned_json pins `col`, or cannot be read (fail closed). */
const pinned = (col: string) => `(CASE WHEN NOT json_valid(fleet_vessels.pinned_json) THEN 1 WHEN json_type(fleet_vessels.pinned_json)<>'object' THEN 1 ` +
  `ELSE json_type(fleet_vessels.pinned_json,'$."${col}"') IS NOT NULL END)`;

const TABLES: Record<UpsertKind, Table> = {
  // Operators and offerings have no observation column of their own: the op's seen_at is stored as updated_at
  // and guards the row, so an older replay never overwrites a newer value.
  'operator.upsert': {name: 'fleet_operators', conflict: 'id', insertOnly: ['id', 'region'], created: true, stamp: 'seen', update: col =>
    col === 'updated_at' ? latest('fleet_operators', col) : newer('fleet_operators', 'updated_at', col)},
  'vessel.upsert': {name: 'fleet_vessels', conflict: 'id', insertOnly: ['id', 'region'], created: true, stamp: 'clock', update: col => {
    const t = 'fleet_vessels';
    if (col === 'first_seen_at') return earliest(t, col);
    if (col === 'last_seen_at') return latest(t, col);
    // A pinned column keeps its value; so does every column when the op was seen before the stored row (an older replay).
    const keep = `${pinned(col)} OR excluded.last_seen_at<${t}.last_seen_at`;
    if (col === 'profile_status') return `CASE WHEN ${keep} THEN ${t}.${col} WHEN ${t}.removal_requested_at IS NOT NULL AND excluded.${col}='listed' THEN ${t}.${col} ELSE excluded.${col} END`;
    return `CASE WHEN ${keep} THEN ${t}.${col} ELSE excluded.${col} END`;
  }},
  'fact.upsert': {name: 'fleet_vessel_facts', conflict: 'id', insertOnly: ['id', 'vessel_id', 'field', 'value_json', 'value_key', 'source_id', 'source_url'], update: col => {
    const t = 'fleet_vessel_facts';
    if (col === 'retrieved_at' || col === 'last_seen_at') return latest(t, col);
    if (col === 'first_seen_at') return earliest(t, col);
    if (col === 'superseded_at' || col === 'superseded_by')     // seen again after it was superseded: current again
      return `CASE WHEN ${t}.superseded_at IS NOT NULL AND excluded.retrieved_at>${t}.superseded_at THEN NULL ELSE ${t}.${col} END`;
    return newer(t, 'retrieved_at', col);                       // method, confidence, rights, run_id
  }},
  'alias.upsert': {name: 'fleet_aliases', conflict: 'vessel_id,alias_norm', insertOnly: ['vessel_id', 'alias_norm'], update: col => {
    const t = 'fleet_aliases';
    if (col === 'last_seen_at') return latest(t, col);
    if (col === 'first_seen_at') return earliest(t, col);
    return newer(t, 'last_seen_at', col);
  }},
  'offering.upsert': {name: 'fleet_offerings', conflict: 'id', insertOnly: ['id', 'vessel_id'], stamp: 'seen', update: col =>
    col === 'updated_at' ? latest('fleet_offerings', col) : newer('fleet_offerings', 'updated_at', col)},
  'departure.upsert': {name: 'fleet_departures', conflict: 'id', insertOnly: ['id', 'offering_id', 'vessel_id', 'date'], update: col =>
    col === 'retrieved_at' ? latest('fleet_departures', col) : newer('fleet_departures', 'retrieved_at', col)},
  'review.open': {name: 'fleet_reviews', conflict: 'id', insertOnly: ['id', 'region', 'kind', 'opened_at', 'run_id', 'status'], where: "fleet_reviews.status='open' AND fleet_reviews.region=excluded.region"},
  'change.record': {name: 'fleet_changes', conflict: 'id', insertOnly: [], nothing: true},
  'run.record': {name: 'fleet_runs', conflict: 'id', insertOnly: ['id', 'region'], update: col =>
    col === 'started_at' ? earliest('fleet_runs', col) : `excluded.${col}`},
};

/** The columns the Worker adds to each kind's rows: region, run_id, status, ids. */
function stored(row: Row, request: RegistryRequest): Record<string, SqlValue> {
  const cols = {...row.cols};
  switch (row.kind) {
    case 'operator.upsert': case 'vessel.upsert': cols.region = request.region; break;
    case 'fact.upsert': cols.run_id = request.runId;
      cols.superseded_at = null; cols.superseded_by = null; break;   // only for the update expression; an insert is current
    case 'review.open': cols.region = request.region; cols.run_id = request.runId; cols.status = 'open'; break;
    case 'change.record': cols.run_id = request.runId; break;
    case 'run.record': cols.id = `${request.runId}:${row.cols.step}`; cols.region = request.region; break;
    default:
  }
  return cols;
}

/** Multi-row upserts for one kind's rows with the same column set, chunked under MAX_PARAMS. */
function upserts(db: D1Database, kind: UpsertKind, rows: Record<string, SqlValue>[], now: string): D1PreparedStatement[] {
  const table = TABLES[kind], statements: D1PreparedStatement[] = [];
  const groups = new Map<string, Record<string, SqlValue>[]>();
  for (const cols of rows) {
    const full = {...cols, ...table.created ? {created_at: now} : {}, ...table.stamp === 'clock' ? {updated_at: now} : {}};
    const key = Object.keys(full).sort().join(',');
    groups.set(key, [...groups.get(key) ?? [], full]);
  }
  for (const [key, group] of groups) {
    const columns = key.split(','), perRow = columns.length, size = Math.max(1, Math.floor(MAX_PARAMS / perRow));
    if (perRow > MAX_PARAMS) throw Error(`${kind}: ${perRow} columns exceed the parameter limit`);
    const updatable = columns.filter(c => !table.insertOnly.includes(c) && c !== 'created_at' && !(c === 'updated_at' && table.stamp === 'clock'));
    const sets = updatable.map(c => [c, table.update ? table.update(c) : `excluded.${c}`] as const);
    const changed = sets.map(([c, expr]) => `(${expr}) IS NOT ${table.name}.${c}`);
    let tail: string;
    if (table.nothing || !sets.length) tail = ' ON CONFLICT DO NOTHING';
    else {
      const assignments = sets.map(([c, expr]) => `${c}=${expr}`);
      if (table.stamp === 'clock') assignments.push('updated_at=excluded.updated_at');
      const conditions = [table.where, `(${changed.join(' OR ')})`].filter(Boolean).join(' AND ');
      tail = ` ON CONFLICT(${table.conflict}) DO UPDATE SET ${assignments.join(',')} WHERE ${conditions}`;
    }
    for (let i = 0; i < group.length; i += size) {
      const part = group.slice(i, i + size);
      const sql = `INSERT INTO ${table.name}(${columns.join(',')}) VALUES ${part.map(() => `(${marks(perRow)})`).join(',')}${tail}`;
      statements.push(db.prepare(sql).bind(...part.flatMap(cols => columns.map(c => cols[c] ?? null))));
    }
  }
  return statements;
}

export interface ApplyResult { changed: number; counts: Partial<Record<OpKind, {ops: number; changed: number}>> }

/**
 * Write validated rows in one D1 batch. Returns the rows changed per kind (D1's
 * meta.changes: an upsert whose values all match the stored row changes nothing).
 */
export async function applyRegistry(db: D1Database, request: RegistryRequest, rows: Row[], now: string): Promise<ApplyResult> {
  const statements: D1PreparedStatement[] = [], owners: OpKind[] = [], counts: ApplyResult['counts'] = {};
  for (const kind of OP_KINDS) {
    const mine = rows.filter(r => r.kind === kind);
    if (!mine.length) continue;
    counts[kind] = {ops: mine.length, changed: 0};
    if (kind === 'fact.purge') {
      // Facts of this source, in this region, last seen before seen_before, except the kept fields.
      for (const r of mine) {
        statements.push(db.prepare(`DELETE FROM fleet_vessel_facts WHERE source_id=? AND last_seen_at<?
          AND NOT EXISTS (SELECT 1 FROM json_each(?) WHERE json_each.value=fleet_vessel_facts.field)
          AND vessel_id IN (SELECT id FROM fleet_vessels WHERE region=?)`).bind(r.cols.source_id!, r.cols.seen_before!, r.cols.keep_fields!, request.region));
        owners.push(kind);
      }
      continue;
    }
    for (const s of upserts(db, kind, mine.map(r => stored(r, request)), now)) { statements.push(s); owners.push(kind); }
    if (kind !== 'fact.upsert') continue;
    // A newer value from the same source supersedes the facts it names (same vessel and field, still
    // current, and not seen after this one), so an older replay never supersedes a newer fact.
    for (const r of mine) {
      if (!r.supersedes?.length) continue;
      statements.push(db.prepare(`UPDATE fleet_vessel_facts SET superseded_at=?,superseded_by=? WHERE vessel_id=? AND field=? AND superseded_at IS NULL
        AND retrieved_at<=? AND id IN (${marks(r.supersedes.length)})`).bind(r.cols.retrieved_at!, r.id, r.cols.vessel_id!, r.cols.field!, r.cols.retrieved_at!, ...r.supersedes));
      owners.push(kind);
    }
  }
  if (!statements.length) return {changed: 0, counts};
  const results = await db.batch(statements);
  let changed = 0;
  results.forEach((result, i) => { const n = result.meta.changes ?? 0; changed += n; counts[owners[i]!]!.changed += n; });
  return {changed, counts};
}
