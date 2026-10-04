// Admin decisions on review items (docs/plans/text-advisor/08-website.md § Admin,
// 02 § advisor_reviews; TA-W2). One code path for both deciders: the admin
// queue (POST /api/admin/reviews/<id>, server/routes/admin.ts) and the text
// admin fallback ("ok <code>" / "no <code>", consumer.ts applyAdminReview).
//
//   open review -> the kind's effect (idempotent on its own) -> the kind's text
//   (deterministic outbound id, so a repeat never texts twice) -> the review
//   closed with a conditional UPDATE ... WHERE status='open'.
//
// The review is closed last, so a decision interrupted half-way is finished by
// a repeat of the same request; a repeat after it closed changes nothing and
// answers 'repeated'.
//
//   kind          approve                         edit                            reject
//   media         publish_state approved,         credit set, approved,           publish_state rejected
//                 media job requested             media job requested
//   report        published (if pending)          applyEdit: edit row, version+1  status rejected
//   skipper       new_skipper: verified + text    -                               new_skipper: rejected + text
//   conversation  closed; with `reply`: sent as   -                               closed
//                 the team through the channel
//   rule          closed (TA-A4 edits the rule)   -                               closed
//   post          TA-S1                           TA-S1                           TA-S1
import {advisorSettings} from '../settings.ts';
import {t} from '../strings.ts';
import {resolveLinks} from '../links.ts';
import {sha256} from '../ids.ts';
import {advisorLog} from '../log.ts';
import {publishReport, applyEdit, bumpPagesVersion, invalidateDailyAnswer, cleanFields} from '../intake/reports.ts';
import {requestMediaJob} from '../media.ts';
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
  if (review.status !== 'open') return {status: 'repeated', review};
  const at = iso(deps.now), settings = advisorSettings(env);
  const sendsEnabled = deps.sendsEnabled ?? true;
  const note = input.note === undefined ? null : clean(input.note, NOTE_MAX);
  const reply = input.reply === undefined || input.reply === null ? null : clean(input.reply, REPLY_MAX);
  if (input.reply != null && !reply) return {status: 'invalid', error: 'reply must be text'};
  if (reply && (review.kind !== 'conversation' || input.decision !== 'approve')) return {status: 'invalid', error: 'only a conversation can be answered'};
  let sends = 0, held: 'replies-off' | undefined;
  const text = async (contact: AdvisorContactRow, inId: string, key: string, body: string): Promise<void> => {
    if (!sendsEnabled) { held = 'replies-off'; return; }
    sends += await deps.send(contact, inId, key, body, input.by);
  };

  switch (review.kind) {
    case 'media': {
      if (input.decision === 'edit') {
        const credit = clean((input.patch as {credit?: unknown} | undefined)?.credit, CREDIT_MAX);
        if (!credit) return {status: 'invalid', error: 'an edit sets the credit'};
        await db.prepare('UPDATE advisor_media SET credit=? WHERE id=?').bind(credit, review.ref_id).run();
      }
      const ok = input.decision !== 'reject';
      await db.prepare(`UPDATE advisor_media SET publish_state=? WHERE id=? AND publish_state IN (${ok ? "'private','queued'" : "'private','queued','approved'"})`)
        .bind(ok ? 'approved' : 'rejected', review.ref_id).run();
      // TA-M1: an approved photo needs its public.jpg (upright, 07 § orientation) for the pages and Meta.
      if (ok) await requestMediaJob(env, deps.now, deps.dispatch ? {dispatch: deps.dispatch} : {});
      break;
    }
    case 'report': {
      const row = await db.prepare('SELECT id,port,status FROM advisor_reports WHERE id=?').bind(review.ref_id).first<{id: string; port: string; status: string}>();
      if (!row) return {status: 'conflict', error: 'the report no longer exists'};
      if (input.decision === 'approve') {
        await publishReport(db, {id: ''}, row.id, deps.now, {auto: true, team: true});
      } else if (input.decision === 'edit') {
        const fields = reportPatch(input.patch);
        if (!fields) return {status: 'invalid', error: 'an edit needs report fields'};
        const key = `admin:${(await sha256(JSON.stringify(fields))).slice(0, 16)}`;
        const result = await applyEdit(db, {id: ''}, review.id, key, row.id, fields, {team: true}, deps.now);
        if (result === 'refused') return {status: 'conflict', error: 'the boat already has a report for that date'};
      } else {
        const r = await db.prepare("UPDATE advisor_reports SET status='rejected',updated_at=? WHERE id=? AND status IN ('draft','pending_confirm','published')").bind(at, row.id).run();
        if (r.meta.changes && row.status === 'published') { await bumpPagesVersion(db, deps.now); await invalidateDailyAnswer(db, row.port, deps.now); }
      }
      break;
    }
    case 'skipper': {
      if (input.decision === 'edit') return {status: 'invalid', error: 'boat fields are edited in the Skippers view'};
      if (review.reason !== 'new_skipper') break;   // owner_forgotten and the like: the review only records that someone looked
      const ok = input.decision === 'approve';
      const r = ok
        ? await db.prepare("UPDATE advisor_boats SET status='verified',verified_at=?,verified_by=?,updated_at=? WHERE id=? AND status<>'verified'").bind(at, input.by, at, review.ref_id).run()
        : await db.prepare("UPDATE advisor_boats SET status='rejected',updated_at=? WHERE id=? AND status<>'rejected'").bind(at, review.ref_id).run();
      if (r.meta.changes) await bumpPagesVersion(db, deps.now);   // 05: verification re-renders the boat page
      // 05 § Verification: the skipper hears the decision, through their own channel.
      const boat = await db.prepare('SELECT name,slug,owner_contact_id FROM advisor_boats WHERE id=?').bind(review.ref_id).first<{name: string; slug: string; owner_contact_id: string | null}>();
      const owner = boat?.owner_contact_id ? await db.prepare("SELECT * FROM advisor_contacts WHERE id=? AND status='active'").bind(boat.owner_contact_id).first<AdvisorContactRow>() : null;
      if (boat && owner) await text(owner, input.inId, `${input.key}.skipper`, resolveLinks(t(owner.language, ok ? 'boat_verified' : 'boat_rejected', {name: boat.name, slug: boat.slug}), settings.publicBase).text);
      break;
    }
    case 'conversation': {
      if (input.decision === 'edit') return {status: 'invalid', error: 'a conversation is answered with a reply'};
      if (!reply) break;
      if (!sendsEnabled) return {status: 'conflict', error: 'replies are switched off (ADVISOR_REPLIES_ENABLED)'};
      const contact = await conversationContact(db, review.ref_id);
      if (!contact) return {status: 'conflict', error: 'the contact no longer exists'};
      if (contact.status !== 'active') return {status: 'conflict', error: `the contact is ${contact.status}`};
      // in_reply_to is the flagged inbound message when the review points at one.
      const inId = contact.message_id ?? review.id;
      await text(contact, inId, `team.${(await sha256(reply)).slice(0, 16)}`, reply);
      break;
    }
    case 'post':
      return {status: 'invalid', error: 'social drafts are decided in the Posts view (TA-S1)'};
    case 'rule':
      if (input.decision === 'edit') return {status: 'invalid', error: 'rules are edited in the Rules view'};
      break;
    default:
      return {status: 'invalid', error: 'unknown review kind'};
  }

  const status = DECIDED[input.decision];
  const closed = await db.prepare("UPDATE advisor_reviews SET status=?,decided_at=?,decided_by=?,note=COALESCE(?,note) WHERE id=? AND status='open'")
    .bind(status, at, input.by, note, review.id).run();
  const after = (await reviewRow(db, review.id))!;
  if (!closed.meta.changes) return {status: 'repeated', review: after};
  advisorLog('info', 'advisor_review_decided', {kind: review.kind, decision: status, by: input.by ? 'admin' : 'text', sends});
  return {status: 'applied', review: after, sends, ...(held ? {held} : {})};
}

/** The contact behind a conversation review: ref_id is the flagged inbound message (04), or a contact id. */
export async function conversationContact(db: D1Database, refId: string): Promise<(AdvisorContactRow & {message_id: string | null}) | null> {
  const viaMessage = await db.prepare('SELECT c.*,m.id AS message_id FROM advisor_messages m JOIN advisor_contacts c ON c.id=m.contact_id WHERE m.id=?').bind(refId)
    .first<AdvisorContactRow & {message_id: string}>();
  if (viaMessage) return viaMessage;
  const contact = await db.prepare('SELECT * FROM advisor_contacts WHERE id=?').bind(refId).first<AdvisorContactRow>();
  return contact ? {...contact, message_id: null} : null;
}
