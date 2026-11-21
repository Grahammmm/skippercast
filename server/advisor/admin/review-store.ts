import type {ReviewKind} from '../types.ts';

export interface ReviewKey {id: string; kind: ReviewKind; ref_id: string; opened_at: string}
export interface Predicate {sql: string; args: unknown[]}
export const always: Predicate = {sql: '1', args: []};
interface Close {
  decision: 'approved' | 'edited' | 'rejected'; at: string; by: string | null; note: string | null;
  followup?: 'post' | 'media' | 'skipper'; intent?: string;
}
const sameReview = (review: ReviewKey): Predicate => ({sql: "id=? AND kind=? AND ref_id=? AND opened_at=? AND status='open'", args: [review.id, review.kind, review.ref_id, review.opened_at]});
const pending = 'FROM advisor_review_events WHERE review_id=? AND decided_at IS NULL';

/** A winning reply is immutable once it can start the existing outbound path.
 * Store only a request fingerprint, not another copy of the private reply. */
export async function claimReply(db: D1Database, review: ReviewKey, intent: string, by: string | null, contactId: string): Promise<string | null> {
  const row = sameReview(review);
  const id = crypto.randomUUID();
  await db.prepare(`INSERT INTO advisor_review_events(id,review_id,kind,decision,actor,intent)
    SELECT ?,id,kind,'approved',?,? FROM advisor_reviews WHERE ${row.sql} AND NOT EXISTS (SELECT 1 ${pending})
      AND EXISTS (SELECT 1 FROM advisor_contacts WHERE id=? AND status='active')`)
    .bind(id, by ? 'admin' : 'text', intent, ...row.args, review.id, contactId).run();
  const won = await db.prepare(`SELECT id,intent ${pending}`).bind(review.id).first<{id: string; intent: string}>();
  return won?.intent === intent ? won.id : null;
}

/** Commit the decision and its D1 effects in one batch. Every effect depends
 * on this batch's marker, not on a stale read or the outcome of another batch.
 * A reply already owns the marker; finalize it only if this review still matches. */
export async function commitReview(db: D1Database, review: ReviewKey, close: Close, opts: {
  check?: Predicate; effects?: (won: Predicate) => D1PreparedStatement[]; replyId?: string;
} = {}): Promise<boolean> {
  const id = opts.replyId ?? crypto.randomUUID(), row = sameReview(review), check = opts.check ?? always;
  const marker = opts.replyId
    ? db.prepare(`UPDATE advisor_review_events SET decided_at=?,intent=NULL
        WHERE id=? AND decided_at IS NULL AND EXISTS (SELECT 1 FROM advisor_reviews WHERE ${row.sql})`)
      .bind(close.at, id, ...row.args)
    : db.prepare(`INSERT INTO advisor_review_events(id,review_id,kind,decision,actor,decided_at,followup,intent)
        SELECT ?,id,kind,?,?,?,?,? FROM advisor_reviews WHERE ${row.sql} AND (${check.sql}) AND NOT EXISTS (SELECT 1 ${pending})`)
      .bind(id, close.decision, close.by ? 'admin' : 'text', close.at, close.followup ?? null, close.intent ?? null, ...row.args, ...check.args, review.id);
  const won = {sql: 'EXISTS (SELECT 1 FROM advisor_review_events WHERE id=?)', args: [id]};
  const [result] = await db.batch([
    marker,
    db.prepare(`UPDATE advisor_reviews SET status=?,decided_at=?,decided_by=?,note=COALESCE(?,note)
      WHERE ${row.sql} AND changes()=1`).bind(close.decision, close.at, close.by, close.note, ...row.args),
    db.prepare('UPDATE advisor_review_events SET followup=NULL,intent=NULL WHERE review_id=? AND id<>? AND followup IS NOT NULL AND changes()=1').bind(review.id, id),
    ...(opts.effects?.(won) ?? []),
  ]);
  return Boolean(result?.meta.changes);
}

export interface ReviewWork {id: string; followup: NonNullable<Close['followup']>; intent: string | null}
export function reviewWork(db: D1Database, reviewId: string, at: string): Promise<ReviewWork | null> {
  return db.prepare('SELECT id,followup,intent FROM advisor_review_events WHERE review_id=? AND decided_at=? AND followup IS NOT NULL')
    .bind(reviewId, at).first<ReviewWork>();
}

export async function finishReviewWork(db: D1Database, id: string): Promise<void> {
  await db.prepare('UPDATE advisor_review_events SET followup=NULL,intent=NULL WHERE id=?').bind(id).run();
}
