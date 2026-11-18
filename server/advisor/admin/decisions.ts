// Admin decisions on review items (docs/plans/text-advisor/08-website.md § Admin,
// 02 § advisor_reviews; TA-W2). One code path for both deciders: the admin
// queue (POST /api/admin/reviews/<id>, server/routes/admin.ts) and the text
// admin fallback ("ok <code>" / "no <code>", consumer.ts applyAdminReview).
//
// Atomically commit one decision and its D1 effects. A reply reserves its
// intent before sending; retries use the existing outbound idempotency keys.
// Closed decisions have one durable, redacted audit record. Console telemetry
// does not determine whether the decision took effect.
//
//   kind          approve                         edit                            reject
//   media         publish_state approved (a       credit set, approved (the       publish_state rejected,
//                 video only once stripped,       same video hold),
//                 media.ts videoHold),
//                 media job requested, pages      media job requested, pages      (pages version bumped if it
//                 version bumped; the post draft  version bumped; the post draft  was approved); its unposted
//                 (TA-S1: an angler's shared      likewise                        posts rejected (TA-S1)
//                 photo, a consented boat photo)
//   report        published (if pending)          applyEdit: edit row, version+1  status rejected
//                 (publishReport bumps the pages  (applyEdit bumps them for a     (a published one bumps them)
//                 version)                        published report)
//   skipper       new_skipper: verified + text    -                               new_skipper: rejected + text
//                 (setBoatVerification, also the Skippers view's verify and reject, TA-W3)
//                 (either bumps the pages version)
//   conversation  closed; with `reply`: sent as   -                               closed
//                 the team through the channel
//   rule          closed (TA-A4 edits the rule)   -                               closed
//   post          admin/posts.ts decidePost       caption, targets, collaborators, status rejected
//                 (TA-S1): approved, approved_by/ tags, scheduled_for checked,
//                 at, scheduled_for; held while   then approved
//                 a photo is held (has_person)
import {advisorSettings} from '../settings.ts';
import {t} from '../strings.ts';
import {resolveLinks} from '../links.ts';
import {sha256} from '../ids.ts';
import {advisorLog} from '../log.ts';
import {bumpPagesVersion, pagesVersionWrite, prepareReportDecision, cleanFields} from '../intake/reports.ts';
import {requestMediaJob, videoHold} from '../media.ts';
// TA-S1: social drafts and post decisions.
import {ensureMediaDraft} from '../social/drafts.ts';
import {preparePostDecision} from './posts.ts';
import {claimReply, commitReview, finishReviewWork, reviewWork} from './review-store.ts';
import type {Predicate} from './review-store.ts';
import type {Env} from '../../env.ts';
import type {AdvisorContactRow, ReportEditFields, ReviewKind} from '../types.ts';

export type Decision = 'approve' | 'edit' | 'reject';
export const DECISIONS: readonly Decision[] = ['approve', 'edit', 'reject'];
/** advisor_reviews.status for each decision. */
export const DECIDED: Readonly<Record<Decision, 'approved' | 'edited' | 'rejected'>> = {approve: 'approved', edit: 'edited', reject: 'rejected'};
export const NOTE_MAX = 280;
export const REPLY_MAX = 1000;
export const CREDIT_MAX = 80;
const REPORT_FIELDS = new Set(['report_date', 'trip_type', 'anglers', 'counts', 'notes']);

export interface ReviewRow {
  id: string; kind: ReviewKind; ref_id: string; reason: string; status: 'open' | 'approved' | 'edited' | 'rejected';
  note: string | null; opened_at: string; decided_at: string | null; decided_by: string | null;
}

/** Send `text` to `contact` through its own channel once per (inId, key); returns the texts sent (consumer.ts teamSender). */
export type TeamSend = (contact: AdvisorContactRow, inId: string, key: string, text: string, createdBy: string | null) => Promise<number>;

export interface DecisionInput {
  reviewId: string;
  decision: Decision;
  patch?: unknown;                     // edit: the kind's fields (report fields, media credit)
  note?: unknown;                      // the admin's note, at most 280 characters
  reply?: unknown;                     // conversation: "reply as team"
  by: string | null;                   // users.id of the admin; null for the text admin (its decider is a contact)
  kinds?: readonly ReviewKind[];       // the kinds this decider may touch (the text admin: skipper and media)
  inId: string; key: string;           // the outbound id base for texts this decision sends
}
export interface DecisionDeps {
  now: number;
  send: TeamSend;
  sendsEnabled?: boolean;              // false while ADVISOR_REPLIES_ENABLED is off: the decision applies, nothing is texted
  dispatch?: (env: Env, file: string) => Promise<number>;   // TA-M1: the media job dispatch (tests); default watchdog.ts dispatchWorkflow
  fetcher?: (url: string, init: RequestInit) => Promise<Response>;   // TA-S1: the Messages API for a draft's caption line (tests)
}
export type DecisionOutcome =
  | {status: 'applied'; review: ReviewRow; sends: number; held?: 'replies-off'}
  | {status: 'repeated'; review: ReviewRow}
  | {status: 'not-found'}
  | {status: 'invalid'; error: string}
  | {status: 'conflict'; error: string};

const iso = (ms: number): string => new Date(ms).toISOString();
const clean = (value: unknown, max: number): string | null => {
  if (typeof value !== 'string') return null;
  const v = value.replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, '').trim();
  return v ? Array.from(v).slice(0, max).join('') : null;
};

export async function reviewRow(db: D1Database, id: string): Promise<ReviewRow | null> {
  return /^[0-9a-f]{32}$/.test(id) ? db.prepare('SELECT * FROM advisor_reviews WHERE id=?').bind(id).first<ReviewRow>() : null;
}

/** The report fields an admin edit may set, validated (null when the patch has nothing usable). */
export function reportPatch(patch: unknown): ReportEditFields | null {
  if (!patch || typeof patch !== 'object' || Array.isArray(patch)) return null;
  const input = Object.fromEntries(Object.entries(patch).filter(([k]) => REPORT_FIELDS.has(k))) as ReportEditFields;
  const fields = cleanFields(input);
  return Object.keys(fields).length ? fields : null;
}

/** Apply one decision. Never throws for bad input: it answers 'invalid', 'conflict' or 'not-found'. */
export async function decideReview(env: Env, input: DecisionInput, deps: DecisionDeps): Promise<DecisionOutcome> {
  const db = env.DB;
  if (!db) return {status: 'not-found'};
  if (!DECISIONS.includes(input.decision)) return {status: 'invalid', error: 'decision must be approve, edit or reject'};
  const review = await reviewRow(db, input.reviewId);
  if (!review || (input.kinds && !input.kinds.includes(review.kind))) return {status: 'not-found'};
  const now = deps.now, at = iso(now), status = DECIDED[input.decision];
  const sendsEnabled = deps.sendsEnabled ?? true;
  const dispatch = deps.dispatch ? {dispatch: deps.dispatch} : {};
  const skipperIntent = () => sha256(JSON.stringify([input.by, input.inId, input.key]));
  const repeated = async (row: ReviewRow): Promise<DecisionOutcome> => {
    if (row.status === status) await resume(row);
    return {status: 'repeated', review: row};
  };
  async function resume(row: ReviewRow): Promise<number> {
    if (!row.decided_at) return 0;
    const work = await reviewWork(db!, row.id, row.decided_at);
    if (!work) return 0;
    let sends = 0;
    if (work.followup === 'skipper') {
      if (work.intent !== await skipperIntent() || !sendsEnabled) return 0;
      await notifyBoat(env, row.ref_id, row.status === 'approved', async (owner, body) => {
        sends += await deps.send(owner, input.inId, `${input.key}.skipper`, body, row.decided_by);
      }, true);
    } else {
      // The media rows already carry the work for the scheduled job. This is
      // the existing throttled nudge; retry at the committed decision's time.
      await requestMediaJob(env, Date.parse(row.decided_at), dispatch);
      if (work.followup === 'media') {
        const draft = await ensureMediaDraft(env, row.ref_id, {now: Date.parse(row.decided_at),
          ...(row.decided_by ? {createdBy: row.decided_by} : {}), ...(deps.fetcher ? {fetcher: deps.fetcher} : {})});
        if (draft.status === 'skipped') advisorLog('info', 'advisor_post_draft_skipped', {reason: draft.reason});
      }
    }
    await finishReviewWork(db!, work.id);
    return sends;
  }
  if (review.status !== 'open') return repeated(review);
  const note = input.note === undefined ? null : clean(input.note, NOTE_MAX);
  const reply = input.reply == null ? null : clean(input.reply, REPLY_MAX);
  if (input.reply != null && !reply) return {status: 'invalid', error: 'reply must be text'};
  if (reply && (review.kind !== 'conversation' || input.decision !== 'approve')) return {status: 'invalid', error: 'only a conversation can be answered'};
  const close: Parameters<typeof commitReview>[2] = {decision: status, at, by: input.by, note};
  let plan: NonNullable<Parameters<typeof commitReview>[3]> = {};
  let sends = 0, held: 'replies-off' | undefined;
  async function lost(): Promise<DecisionOutcome> {
    const after = await reviewRow(db!, input.reviewId);
    if (!after) return {status: 'not-found'};
    if (after.status !== 'open') return repeated(after);
    return {status: 'conflict', error: 'the review, its subject, or a pending decision changed; reload and retry the winning decision'};
  }

  switch (review.kind) {
    case 'media': {
      const prepared = await prepareMediaDecision(db, review.ref_id, input, now);
      if (prepared.status) return prepared;
      plan = prepared;
      if (input.decision !== 'reject') close.followup = 'media';
      break;
    }
    case 'report': {
      const fields = input.decision === 'edit' ? reportPatch(input.patch) : null;
      if (input.decision === 'edit' && !fields) return {status: 'invalid', error: 'an edit needs report fields'};
      const prepared = await prepareReportDecision(db, review.id, review.ref_id, input.decision, fields, now);
      if (prepared.error) return {status: 'conflict', error: prepared.error};
      plan = prepared;
      break;
    }
    case 'skipper': {
      if (input.decision === 'edit') return {status: 'invalid', error: 'boat fields are edited in the Skippers view'};
      if (review.reason !== 'new_skipper') break;
      const ok = input.decision === 'approve';
      plan.effects = won => [boatVerificationWrite(db, review.ref_id, ok, input.by, at, won), pagesVersionWrite(db, now, 'changes()=1')];
      if (sendsEnabled) {
        close.followup = 'skipper';
        close.intent = await skipperIntent();
      } else if (await boatOwner(db, review.ref_id)) held = 'replies-off';
      break;
    }
    case 'conversation': {
      if (input.decision === 'edit') return {status: 'invalid', error: 'a conversation is answered with a reply'};
      if (!reply) break;
      if (!sendsEnabled) return {status: 'conflict', error: 'replies are switched off (ADVISOR_REPLIES_ENABLED)'};
      const contact = await conversationContact(db, review.ref_id);
      if (!contact) return {status: 'conflict', error: 'the contact no longer exists'};
      if (contact.status !== 'active') return {status: 'conflict', error: `the contact is ${contact.status}`};
      // Bind the recipient and original request to the winner without storing
      // extra copies of reply text, note, or the recipient's address.
      const inId = contact.message_id ?? review.id;
      const digest = await sha256(JSON.stringify([contact.id, inId, input.by, note, reply]));
      const claim = await claimReply(db, review, digest, input.by, contact.id);
      if (!claim) return lost();
      const current = await conversationContact(db, review.ref_id);
      if (!current || current.id !== contact.id || current.status !== 'active') return {status: 'conflict', error: 'the contact changed or is not active'};
      // Keep the existing outbound key, including when an older Worker already
      // wrote the message before leaving this review open.
      sends = await deps.send(current, inId, `team.${(await sha256(reply)).slice(0, 16)}`, reply, input.by);
      plan.replyId = claim;
      break;
    }
    case 'post': {
      const prepared = await preparePostDecision(db, review.ref_id, input.decision, input.patch, input.by, now);
      if (prepared.status !== 'ok') {
        const after = await reviewRow(db, review.id);
        return after && after.status !== 'open' ? repeated(after) : prepared;
      }
      plan = prepared;
      if (input.decision !== 'reject') close.followup = 'post';
      break;
    }
    case 'rule':
      if (input.decision === 'edit') return {status: 'invalid', error: 'rules are edited in the Rules view'};
      break;
    default:
      return {status: 'invalid', error: 'unknown review kind'};
  }

  if (!await commitReview(db, review, close, plan)) return lost();
  const after: ReviewRow = {...review, status, decided_at: at, decided_by: input.by, note: note ?? review.note};
  sends += await resume(after);
  // The event is telemetry only. The transaction above is the audit record.
  advisorLog('info', 'advisor_review_decided', {kind: review.kind, decision: status, by: input.by ? 'admin' : 'text', sends});
  return {status: 'applied', review: after, sends, ...(held ? {held} : {})};
}

async function prepareMediaDecision(db: D1Database, id: string, input: DecisionInput, now: number) {
  const row = await db.prepare('SELECT kind,derived_at,derived_error,publish_state FROM advisor_media WHERE id=?').bind(id)
    .first<{kind: string; derived_at: string | null; derived_error: string | null; publish_state: string}>();
  const ok = input.decision !== 'reject', at = iso(now);
  const hold = row && ok ? videoHold(row) : null;
  if (hold) return {status: 'conflict' as const, error: hold};
  const credit = input.decision === 'edit' ? clean((input.patch as {credit?: unknown} | undefined)?.credit, CREDIT_MAX) : null;
  if (input.decision === 'edit' && !credit) return {status: 'invalid' as const, error: 'an edit sets the credit'};
  const check = row ? {sql: 'EXISTS (SELECT 1 FROM advisor_media WHERE id=? AND kind=? AND derived_at IS ? AND derived_error IS ? AND publish_state=?)',
    args: [id, row.kind, row.derived_at, row.derived_error, row.publish_state]}
    : {sql: 'NOT EXISTS (SELECT 1 FROM advisor_media WHERE id=?)', args: [id]};
  const effects = (won: Predicate) => {
    const eligible = ok ? ['private', 'queued'] : ['private', 'queued', 'approved'];
    const change = row && eligible.includes(row.publish_state);
    const writes: D1PreparedStatement[] = [];
    if (row && (credit || change)) writes.push(db.prepare(`UPDATE advisor_media SET credit=COALESCE(?,credit),publish_state=? WHERE id=? AND (${won.sql})`)
      .bind(credit, change ? (ok ? 'approved' : 'rejected') : row.publish_state, id, ...won.args));
    if (credit || (change && (ok || row?.publish_state === 'approved'))) writes.push(pagesVersionWrite(db, now, won.sql, won.args));
    if (!ok) {
      // Close the affected reviews against the same set of draft/approved posts
      // before updating the statuses of those posts, all inside the batch.
      const hasPhoto = "p.status IN ('draft','approved') AND EXISTS (SELECT 1 FROM json_each(p.media_json) WHERE value=?)";
      writes.push(db.prepare(`UPDATE advisor_reviews SET status='rejected',decided_at=?,note=COALESCE(note,'photo rejected')
        WHERE kind='post' AND status='open' AND ref_id IN (SELECT p.id FROM advisor_posts p WHERE ${hasPhoto}) AND (${won.sql})`).bind(at, id, ...won.args),
      db.prepare(`UPDATE advisor_posts AS p SET status='rejected',error='media_rejected',updated_at=?
        WHERE ${hasPhoto} AND (${won.sql})`).bind(at, id, ...won.args));
    }
    return writes;
  };
  return {check, effects};
}

function boatVerificationWrite(db: D1Database, boatId: string, ok: boolean, by: string | null, at: string, when: Predicate): D1PreparedStatement {
  return ok
    ? db.prepare(`UPDATE advisor_boats SET status='verified',verified_at=?,verified_by=?,updated_at=? WHERE id=? AND status<>'verified' AND (${when.sql})`).bind(at, by, at, boatId, ...when.args)
    : db.prepare(`UPDATE advisor_boats SET status='rejected',updated_at=? WHERE id=? AND status<>'rejected' AND (${when.sql})`).bind(at, boatId, ...when.args);
}

async function boatOwner(db: D1Database, boatId: string, status?: string) {
  return db.prepare(`SELECT c.*,b.name AS boat_name,b.slug AS boat_slug FROM advisor_boats b JOIN advisor_contacts c ON c.id=b.owner_contact_id
    WHERE b.id=? AND c.status='active' AND (? IS NULL OR b.status=?)`).bind(boatId, status ?? null, status ?? null)
    .first<AdvisorContactRow & {boat_name: string; boat_slug: string}>();
}
async function notifyBoat(env: Env, boatId: string, ok: boolean, text: (owner: AdvisorContactRow, body: string) => Promise<void>, checkStatus = false): Promise<void> {
  const owner = await boatOwner(env.DB!, boatId, checkStatus ? (ok ? 'verified' : 'rejected') : undefined);
  if (owner) await text(owner, resolveLinks(t(owner.language, ok ? 'boat_verified' : 'boat_rejected', {name: owner.boat_name, slug: owner.boat_slug}), advisorSettings(env).publicBase).text);
}

/**
 * Verify or reject a boat (05 § Verification), shared by the skipper review and
 * the Skippers view (TA-W3, admin/skippers.ts): the status (verified_at and
 * verified_by on a verify), the pages version when it changed (05: the page
 * re-renders), and the owner's text through `text` while the owner is active.
 * True when the status changed.
 */
export async function setBoatVerification(env: Env, args: {boatId: string; ok: boolean; by: string | null; now: number;
  text: (owner: AdvisorContactRow, body: string) => Promise<void>}): Promise<boolean> {
  const db = env.DB!;
  const r = await boatVerificationWrite(db, args.boatId, args.ok, args.by, iso(args.now), {sql: '1', args: []}).run();
  if (r.meta.changes) await bumpPagesVersion(db, args.now);
  await notifyBoat(env, args.boatId, args.ok, args.text);
  return Boolean(r.meta.changes);
}

/** The contact behind a conversation review: ref_id is the flagged inbound message (04), or a contact id. */
export async function conversationContact(db: D1Database, refId: string): Promise<(AdvisorContactRow & {message_id: string | null}) | null> {
  const viaMessage = await db.prepare('SELECT c.*,m.id AS message_id FROM advisor_messages m JOIN advisor_contacts c ON c.id=m.contact_id WHERE m.id=?').bind(refId)
    .first<AdvisorContactRow & {message_id: string}>();
  if (viaMessage) return viaMessage;
  const contact = await db.prepare('SELECT * FROM advisor_contacts WHERE id=?').bind(refId).first<AdvisorContactRow>();
  return contact ? {...contact, message_id: null} : null;
}
