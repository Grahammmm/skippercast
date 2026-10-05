// Charter fleet job API (docs/plans/charter-fleet/design.md § 9, § 12): the
// registry snapshot the Python resolver reads, and the registry operations its
// ingest step posts. The routes (server/routes/fleet.ts) sit behind fleetGate and
// requireFleetJob; this module holds the work.
//
//   GET  /api/fleet/jobs/snapshot?region=<id>&cursor=<c>
//        One page from one section, in order: operators, vessels (each with its
//        aliases and offerings), decided reviews. `next` is the cursor of the
//        following page, null after the last. Vessels carry their stable keys and
//        `pinned` (the pinned column names); reviews are the decided and dismissed
//        ones, so a re-run never re-asks. Private columns (consent, outreach,
//        removal requests, map consent, facts) are not in the snapshot.
//   POST /api/fleet/jobs/registry   {region, run_id, batch?, ops: [...]}
//        Body <= 1 MB, <= 500 operations (registry.ts). 200 {ok, run_id, batch,
//        ops, changed, counts}; 400 {error, errors: [{index, op, error}]} with
//        nothing written. Each call records a fleet_runs row
//        '<run_id>:registry.<batch>' (step 'registry', sink 'worker'); the first
//        'ok' for that id is kept.
import {body} from '../http.ts';
import {ClientError} from '../errors.ts';
import {applyRegistry, MAX_OPS, REGION, RUN_ID, validateRegistry} from './registry.ts';
import type {ApplyResult, OpFailure} from './registry.ts';

export const MAX_REGISTRY_BYTES = 1024 * 1024;
export const PAGE = {operators: 500, vessels: 100, reviews: 500} as const;
const SECTIONS = ['o', 'v', 'r'] as const;
const CURSOR = /^([ovr]):([A-Za-z0-9_-]{0,64})$/;

/** Test seam: the clock for created_at/updated_at and fleet_runs times. */
export const jobsDeps: {now: () => Date} = {now: () => new Date()};

type Result = {status: number; body: Record<string, unknown>};
const parse = (text: string | null): unknown => { if (text === null) return null; try { return JSON.parse(text); } catch { return null; } };

/** The names of the pinned columns in a stored pinned_json (all of them unreadable: '*'). */
function pinnedNames(text: string): string[] {
  const value = parse(text);
  return value && typeof value === 'object' && !Array.isArray(value) ? Object.keys(value).sort() : ['*'];
}

interface VesselRow { id: string; pinned_json: string; waters_json: string | null; [k: string]: unknown }
interface OfferingRow { vessel_id: string; days_json: string | null; target_species_json: string | null; source_fact_ids_json: string | null; [k: string]: unknown }

const VESSEL_COLUMNS = 'id,slug,name,name_norm,operator_id,port_id,landing_id,vessel_class,waters_json,uscg_doc,state_reg,hull_id,call_sign,mmsi,' +
  'year_built,passengers_max,bunks,length_ft,beam_ft,cruise_kn,website,booking_url,booking_platform,phone_business,email_business,' +
  'status,profile_status,pinned_json,completeness,first_seen_at,last_seen_at,last_profiled_at';
const OFFERING_COLUMNS = 'id,vessel_id,name,trip_type,duration_h,price_cents,price_basis,capacity,currency,departs_local,days_json,season_from,season_to,' +
  'target_species_json,booking_url,status,source_fact_ids_json,valid_from,valid_to,updated_at';

/** One snapshot page for a region. */
export async function snapshot(db: D1Database, region: string | undefined, cursor: string | undefined): Promise<Result> {
  if (!region || !REGION.test(region)) return {status: 400, body: {error: 'invalid region'}};
  const match = CURSOR.exec(cursor ?? 'o:');
  if (!match) return {status: 400, body: {error: 'invalid cursor'}};
  const section = match[1] as typeof SECTIONS[number], after = match[2]!;
  const out: Record<string, unknown> = {region, cursor: `${section}:${after}`, operators: [], vessels: [], reviews: []};
  let rows: {id: string}[];
  if (section === 'o') {
    rows = (await db.prepare(`SELECT id,slug,name,website,phone_business,email_business,booking_platform FROM fleet_operators
      WHERE region=? AND id>? ORDER BY id LIMIT ?`).bind(region, after, PAGE.operators + 1).all<{id: string}>()).results;
    out.operators = rows.slice(0, PAGE.operators);
  } else if (section === 'v') {
    const vessels = (await db.prepare(`SELECT ${VESSEL_COLUMNS} FROM fleet_vessels WHERE region=? AND id>? ORDER BY id LIMIT ?`)
      .bind(region, after, PAGE.vessels + 1).all<VesselRow>()).results;
    rows = vessels;
    const page = vessels.slice(0, PAGE.vessels);
    // Children of exactly this page's vessels, selected by the same range (no IN list to bind).
    const range = 'vessel_id IN (SELECT id FROM fleet_vessels WHERE region=? AND id>? ORDER BY id LIMIT ?)';
    const aliases = (await db.prepare(`SELECT vessel_id,alias,alias_norm,kind,source_url,first_seen_at,last_seen_at FROM fleet_aliases WHERE ${range} ORDER BY vessel_id,alias_norm`)
      .bind(region, after, PAGE.vessels).all<{vessel_id: string}>()).results;
    const offerings = (await db.prepare(`SELECT ${OFFERING_COLUMNS} FROM fleet_offerings WHERE ${range} ORDER BY vessel_id,id`)
      .bind(region, after, PAGE.vessels).all<OfferingRow>()).results;
    const group = <T extends {vessel_id: string}>(list: T[]) => { const m = new Map<string, Omit<T, 'vessel_id'>[]>(); for (const {vessel_id, ...rest} of list) m.set(vessel_id, [...m.get(vessel_id) ?? [], rest]); return m; };
    const aliasesOf = group(aliases), offeringsOf = group(offerings.map(({days_json, target_species_json, source_fact_ids_json, ...o}) =>
      ({...o, days: parse(days_json), target_species: parse(target_species_json), source_fact_ids: parse(source_fact_ids_json)})));
    out.vessels = page.map(({pinned_json, waters_json, ...v}) => ({...v, waters: parse(waters_json), pinned: pinnedNames(pinned_json),
      aliases: aliasesOf.get(v.id) ?? [], offerings: offeringsOf.get(v.id) ?? []}));
  } else {
    const reviews = (await db.prepare(`SELECT id,kind,subject_id,candidate_json,proposal_json,score,status,decision_json,decided_at,opened_at
      FROM fleet_reviews WHERE region=? AND status<>'open' AND id>? ORDER BY id LIMIT ?`).bind(region, after, PAGE.reviews + 1)
      .all<{id: string; candidate_json: string | null; proposal_json: string | null; decision_json: string | null}>()).results;
    rows = reviews;
    out.reviews = reviews.slice(0, PAGE.reviews).map(({candidate_json, proposal_json, decision_json, ...r}) =>
      ({...r, candidate: parse(candidate_json), proposal: parse(proposal_json), decision: parse(decision_json)}));
  }
  const size = section === 'o' ? PAGE.operators : section === 'v' ? PAGE.vessels : PAGE.reviews;
  const nextSection = SECTIONS[SECTIONS.indexOf(section) + 1];
  out.next = rows.length > size ? `${section}:${rows[size - 1]!.id}` : nextSection ? `${nextSection}:` : null;
  return {status: 200, body: out};
}

/** Record this call in fleet_runs. The first `ok` for a call id stays: a replay or a later failure never overwrites it. */
async function recordCall(db: D1Database, id: string, region: string, startedAt: string, status: 'ok' | 'failed', counts: unknown, error: string | null): Promise<void> {
  await db.prepare(`INSERT INTO fleet_runs(id,region,step,sink,started_at,finished_at,status,counts_json,error) VALUES(?,?,'registry','worker',?,?,?,?,?)
    ON CONFLICT(id) DO UPDATE SET region=excluded.region,started_at=excluded.started_at,finished_at=excluded.finished_at,status=excluded.status,counts_json=excluded.counts_json,error=excluded.error
    WHERE fleet_runs.status<>'ok'`)
    .bind(id, region, startedAt, jobsDeps.now().toISOString(), status, counts === null ? null : JSON.stringify(counts), error).run();
}

/** POST /api/fleet/jobs/registry. */
export async function registry(db: D1Database, request: Request): Promise<Result> {
  const startedAt = jobsDeps.now().toISOString();
  let raw: Record<string, unknown>;
  try { raw = await body(request, MAX_REGISTRY_BYTES); }
  catch (error) {
    if (error instanceof ClientError && error.message === 'body too large') return {status: 413, body: {error: 'body too large'}};
    throw error;
  }
  const {region, run_id: runId, batch = 0, ops, ...extra} = raw;
  if (Object.keys(extra).length) return {status: 400, body: {error: `unknown field: ${Object.keys(extra)[0]}`}};
  if (typeof region !== 'string' || !REGION.test(region)) return {status: 400, body: {error: 'invalid region'}};
  if (typeof runId !== 'string' || !RUN_ID.test(runId)) return {status: 400, body: {error: 'invalid run_id'}};
  if (!Number.isInteger(batch) || (batch as number) < 0 || (batch as number) > 99999) return {status: 400, body: {error: 'invalid batch'}};
  if (!Array.isArray(ops)) return {status: 400, body: {error: 'ops must be an array'}};
  if (ops.length > MAX_OPS) return {status: 413, body: {error: `at most ${MAX_OPS} operations per request`}};
  const callId = `${runId}:registry.${batch}`, envelope = {region, runId, ops};

  const validated = await validateRegistry(db, envelope);
  if (!validated.ok) {
    const errors: OpFailure[] = validated.errors;
    await recordCall(db, callId, region, startedAt, 'failed', {ops: ops.length, rejected: errors.length}, `invalid operations: first at index ${errors[0]!.index}`);
    return {status: 400, body: {error: 'invalid operations', errors}};
  }
  let result: ApplyResult;
  try { result = await applyRegistry(db, envelope, validated.rows, startedAt); }
  catch (error) {
    await recordCall(db, callId, region, startedAt, 'failed', {ops: ops.length}, 'write failed').catch(() => {});
    throw error;
  }
  await recordCall(db, callId, region, startedAt, 'ok', {ops: ops.length, changed: result.changed, kinds: result.counts}, null);
  return {status: 200, body: {ok: true, run_id: runId, batch, ops: ops.length, changed: result.changed, counts: result.counts}};
}
