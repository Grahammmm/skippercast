// The fleet review queue for the admin (docs/plans/charter-fleet/design.md § 5, § 7,
// § 12, § 13; CF-30). Mounted in routes/admin.ts behind requireUser and requireAdmin;
// the FLEET_ENABLED gate (routes/fleet.ts) runs first.
//
//   GET  /api/admin/fleet/reviews       ?region= &status=open|decided|dismissed|all &kind= &cursor=   newest first, 50 a page
//   POST /api/admin/fleet/reviews/:id   {action, vessel_id?, mmsi?, vessel_class?, status?, note?}
//
// A decision closes an open review (status 'decided', or 'dismissed' for `dismiss`)
// and records decision_json, decided_by and decided_at; the job snapshot returns it,
// so the resolver assigns that candidate as decided and never re-asks (§ 7 step 2).
// decision_json is canonical JSON {action, vessel_id?, boat_id?, mmsi?, vessel_class?,
// status?, note?, fact_ids?}. Actions, and the kinds they decide:
//
//   same-vessel   merge, advisor-link   the candidate is vessel_id. For advisor-link the
//                                       review's subject_id is the advisor boat, and the
//                                       decision sets advisor_boats.fleet_vessel_id (D5).
//   new-vessel    merge                 the candidate is a vessel of its own
//   set-mmsi      mmsi                  admin fact + pin for mmsi on vessel_id
//   reject-mmsi   mmsi                  the proposed MMSI is not this vessel's (decision only)
//   set-class     class                 admin fact + pin for vessel_class
//   set-status    vanished, scope, change   admin fact + pin for status (mark vanished:
//                                       inactive; mark active: active; out of scope: excluded)
//   confirm       change, fact-conflict seen; nothing else changes (field fixes are vessel edits)
//   dismiss       every kind            status 'dismissed'
//
// vessel_id defaults to proposal_json.vessel_id, then (except advisor-link) the review's
// subject_id; mmsi to candidate_json.mmsi; vessel_class to proposal_json.vessel_class.
// The review update runs first in the batch, and every other write is conditioned on
// that decision being the stored one, so two admins deciding at once cannot both apply.
// Repeating the stored decision answers {review, repeated: true}; a different one on a
// closed review is a conflict.
import {canonicalJson} from '../ids.ts';
import type {JsonValue} from '../ids.ts';
import {FLEET_ENUMS} from '../registry.ts';
import type {AdminOutcome} from '../../advisor/admin/skippers.ts';
import {editStatements, linkStatements, vesselRow} from './vessels.ts';
import type {Guard} from './vessels.ts';

type SqlValue = string | number | null;
const HEX32 = /^[0-9a-f]{32}$/;
const REGION = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?$/;
const ISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/;
export const REVIEW_PAGE = 50;
export const FLEET_REVIEW_STATUSES = ['open', 'decided', 'dismissed'] as const;
export const FLEET_ACTIONS = ['same-vessel', 'new-vessel', 'set-mmsi', 'reject-mmsi', 'set-class', 'set-status', 'confirm', 'dismiss'] as const;
export type FleetAction = typeof FLEET_ACTIONS[number];
/** The actions each review kind accepts (dismiss: every kind). */
export const ACTIONS_BY_KIND: Record<string, readonly FleetAction[]> = {
  'merge': ['same-vessel', 'new-vessel', 'dismiss'],
  'advisor-link': ['same-vessel', 'dismiss'],
  'mmsi': ['set-mmsi', 'reject-mmsi', 'dismiss'],
  'class': ['set-class', 'dismiss'],
  'vanished': ['set-status', 'dismiss'],
  'scope': ['set-status', 'dismiss'],
  'change': ['confirm', 'set-status', 'dismiss'],
  'fact-conflict': ['confirm', 'dismiss'],
};
const MAX_NOTE = 2000;

interface ReviewRow {id: string; region: string; kind: string; subject_id: string | null; candidate_json: string | null; proposal_json: string | null;
  score: number | null; status: string; decision_json: string | null; decided_by: string | null; decided_at: string | null; opened_at: string; run_id: string | null}

const parse = (text: string | null): unknown => { if (text === null) return null; try { return JSON.parse(text); } catch { return null; } };
const view = <T extends ReviewRow>({candidate_json, proposal_json, decision_json, ...r}: T) =>
  ({...r, candidate: parse(candidate_json), proposal: parse(proposal_json), decision: parse(decision_json)});

// ---- list -------------------------------------------------------------------------
const CURSOR = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z)\|([0-9a-f]{32})$/;

/** GET /api/admin/fleet/reviews: newest first, with the subject vessel's name and slug where the subject is a vessel. */
export async function listFleetReviews(db: D1Database, q: {region?: string; status?: string; kind?: string; cursor?: string}):
  Promise<{reviews: unknown[]; next: string | null} | {error: string}> {
  const where: string[] = [], args: SqlValue[] = [], status = q.status || 'open';
  if (status !== 'all') {
    if (!(FLEET_REVIEW_STATUSES as readonly string[]).includes(status)) return {error: 'unknown status'};
    where.push('r.status=?'); args.push(status);
  }
  if (q.kind) { if (!(FLEET_ENUMS.reviewKind as readonly string[]).includes(q.kind)) return {error: 'unknown kind'}; where.push('r.kind=?'); args.push(q.kind); }
  if (q.region) { if (!REGION.test(q.region)) return {error: 'invalid region'}; where.push('r.region=?'); args.push(q.region); }
  if (q.cursor) {
    const m = CURSOR.exec(q.cursor);
    if (!m) return {error: 'invalid cursor'};
    where.push('(r.opened_at<? OR (r.opened_at=? AND r.id>?))'); args.push(m[1]!, m[1]!, m[2]!);
  }
  const rows = (await db.prepare(`SELECT r.*, v.name AS subject_name, v.slug AS subject_slug FROM fleet_reviews r
    LEFT JOIN fleet_vessels v ON v.id=r.subject_id ${where.length ? 'WHERE ' + where.join(' AND ') : ''}
    ORDER BY r.opened_at DESC, r.id LIMIT ?`).bind(...args, REVIEW_PAGE + 1).all<ReviewRow & {subject_name: string | null; subject_slug: string | null}>()).results;
  const page = rows.slice(0, REVIEW_PAGE), last = page[page.length - 1];
  return {
    reviews: page.map(r => ({...view(r), actions: r.status === 'open' ? ACTIONS_BY_KIND[r.kind] ?? ['dismiss'] : []})),
    next: rows.length > REVIEW_PAGE && last ? `${last.opened_at}|${last.id}` : null,
  };
}

// ---- decide -----------------------------------------------------------------------
export interface DecisionInput {action?: unknown; vessel_id?: unknown; mmsi?: unknown; vessel_class?: unknown; status?: unknown; note?: unknown}
const INPUT_KEYS = ['action', 'vessel_id', 'mmsi', 'vessel_class', 'status', 'note'];
const field = (json: unknown, key: string): unknown => json && typeof json === 'object' && !Array.isArray(json) ? (json as Record<string, unknown>)[key] : undefined;

/** POST /api/admin/fleet/reviews/:id. */
export async function decideFleetReview(db: D1Database, id: string, input: DecisionInput, by: string, now: string):
  Promise<AdminOutcome<{review: unknown; repeated?: true}>> {
  if (!HEX32.test(id)) return {status: 'not-found'};
  const review = await db.prepare('SELECT * FROM fleet_reviews WHERE id=?').bind(id).first<ReviewRow>();
  if (!review) return {status: 'not-found'};
  for (const key of Object.keys(input)) if (!INPUT_KEYS.includes(key)) return {status: 'invalid', error: `unknown field: ${key}`};
  const action = input.action as FleetAction;
  if (!(FLEET_ACTIONS as readonly unknown[]).includes(action)) return {status: 'invalid', error: `action must be one of ${FLEET_ACTIONS.join(', ')}`};
  if (!(ACTIONS_BY_KIND[review.kind] ?? ['dismiss']).includes(action)) return {status: 'invalid', error: `${action} does not decide a ${review.kind} review`};
  if (input.note !== undefined && (typeof input.note !== 'string' || input.note.length > MAX_NOTE)) return {status: 'invalid', error: 'note: at most 2000 characters'};
  if (!ISO.test(now)) throw Error('now must be Date#toISOString');

  const candidate = parse(review.candidate_json), proposal = parse(review.proposal_json);
  const decision: Record<string, JsonValue> = {action};
  const needsVessel = ['same-vessel', 'set-mmsi', 'set-class', 'set-status'].includes(action) || (action === 'reject-mmsi' && review.subject_id !== null);
  let vesselId: string | null = null;
  if (needsVessel) {
    const given = input.vessel_id ?? field(proposal, 'vessel_id') ?? (review.kind !== 'advisor-link' ? review.subject_id : undefined);
    if (typeof given !== 'string' || !HEX32.test(given)) return {status: 'invalid', error: 'vessel_id: missing or invalid'};
    const vessel = await vesselRow(db, given);
    if (!vessel || vessel.region !== review.region) return {status: 'invalid', error: 'vessel_id: unknown vessel in this region'};
    vesselId = given; decision.vessel_id = given;
  } else if (input.vessel_id !== undefined) return {status: 'invalid', error: `vessel_id: not used by ${action}`};

  const cols: Record<string, SqlValue> = {};
  if (action === 'set-mmsi' || action === 'reject-mmsi') {
    const mmsi = input.mmsi ?? field(candidate, 'mmsi');
    if (typeof mmsi !== 'string' || !/^\d{9}$/.test(mmsi)) return {status: 'invalid', error: 'mmsi: missing or not 9 digits'};
    decision.mmsi = mmsi;
    if (action === 'set-mmsi') cols.mmsi = mmsi;
  } else if (input.mmsi !== undefined) return {status: 'invalid', error: `mmsi: not used by ${action}`};
  if (action === 'set-class') {
    const cls = input.vessel_class ?? field(proposal, 'vessel_class');
    if (typeof cls !== 'string' || !(FLEET_ENUMS.vesselClass as readonly string[]).includes(cls)) return {status: 'invalid', error: `vessel_class: not one of ${FLEET_ENUMS.vesselClass.join(', ')}`};
    decision.vessel_class = cls; cols.vessel_class = cls;
  } else if (input.vessel_class !== undefined) return {status: 'invalid', error: `vessel_class: not used by ${action}`};
  if (action === 'set-status') {
    if (typeof input.status !== 'string' || !(FLEET_ENUMS.vesselStatus as readonly string[]).includes(input.status)) return {status: 'invalid', error: `status: not one of ${FLEET_ENUMS.vesselStatus.join(', ')}`};
    decision.status = input.status; cols.status = input.status;
  } else if (input.status !== undefined) return {status: 'invalid', error: `status: not used by ${action}`};
  let boatId: string | null = null;
  if (review.kind === 'advisor-link' && action === 'same-vessel') { boatId = review.subject_id; decision.boat_id = boatId; }
  if (input.note) decision.note = input.note as string;

  // A closed review: the same decision again is a repeat, anything else a conflict.
  const essence = (d: unknown) => { const {note: _n, fact_ids: _f, ...rest} = (d ?? {}) as Record<string, JsonValue>; return canonicalJson(rest); };
  if (review.status !== 'open') {
    if (essence(parse(review.decision_json)) === essence(decision)) return {status: 'ok', value: {review: view(review), repeated: true}};
    return {status: 'conflict', error: `review already ${review.status}`};
  }

  // Every write after the review update runs only if this decision is the stored one.
  const guard: Guard = {sql: 'EXISTS (SELECT 1 FROM fleet_reviews WHERE id=? AND decided_by=? AND decided_at=?)', args: [id, by, now]};
  const writes: D1PreparedStatement[] = [];
  if (Object.keys(cols).length) {
    const edit = await editStatements(db, vesselId!, cols, cols as Record<string, JsonValue>, by, now, guard);
    writes.push(...edit.statements);
    decision.fact_ids = Object.values(edit.facts);
  }
  if (boatId !== null) {
    const link = await linkStatements(db, vesselId!, boatId, false, now, guard);
    if ('status' in link) return link.status === 'not-found' ? {status: 'not-found'} : {status: link.status, error: link.error};
    writes.push(...link.statements);
  }
  const status = action === 'dismiss' ? 'dismissed' : 'decided';
  const results = await db.batch([
    db.prepare(`UPDATE fleet_reviews SET status=?,decision_json=?,decided_by=?,decided_at=? WHERE id=? AND status='open'`)
      .bind(status, canonicalJson(decision), by, now, id),
    ...writes,
  ]);
  if (!(results[0]?.meta.changes)) {
    const stored = await db.prepare('SELECT * FROM fleet_reviews WHERE id=?').bind(id).first<ReviewRow>();
    if (stored && essence(parse(stored.decision_json)) === essence(decision)) return {status: 'ok', value: {review: view(stored), repeated: true}};
    return {status: 'conflict', error: `review already ${stored?.status ?? 'closed'}`};
  }
  const stored = await db.prepare('SELECT * FROM fleet_reviews WHERE id=?').bind(id).first<ReviewRow>();
  return {status: 'ok', value: {review: view(stored!)}};
}
