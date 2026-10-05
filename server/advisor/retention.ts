// The Text Advisor's weekly retention prune (docs/plans/text-advisor/02-data-model.md
// § Retention and deletion), the `retention` slot in cron.ts: Sunday 09:00 UTC.
//
//   message bodies       advisor_messages.body nulled 180 days after created_at; the row stays for counts
//   media originals      90 days after created_at, the R2 original and its derived files are deleted
//                        unless the media is referenced: a published report's media_id, a post in an
//                        approved, scheduled, publishing, posted or partial state (media_json), or the
//                        media itself approved or posted (what the public pages show). The row stays
//                        with r2_key '' and derived_error 'expired'; a duplicate's shared object is
//                        deleted only when no kept row still points at it. Its cached caption line goes too.
//   reviews              deleted 90 days after decided_at (open reviews are never deleted)
//   daily answers        deleted 30 days after generated_at
//   post stats           deleted when `day` is more than 2 years (730 days) old
//   web-only contacts    no phone and no Instagram id, last_seen_at more than 90 days ago: deleted
//                        through forgetContact (R2 first, then the one D1 batch)
//   job_state            the advisor's short-lived keys more than 30 days old (updated_at): flows,
//                        web phone link codes and share offers; graphic requests whose post is gone
//                        or rejected (with the graphic files under advisor/posts/<id>/); once-markers
//                        whose window has passed (the weekly no-consent line) or whose boat or
//                        contact no longer exists. A once-marker of a live boat or contact stays:
//                        it is what keeps that line said once.
//   exports              advisor/exports/* objects more than 7 days old (uploaded, else the key's date)
//
// The rules that delete R2 objects (media, web-only contacts, graphic requests,
// exports) run only while ADVISOR_MEDIA is bound. The slot also runs while
// TEXT_ADVISOR_ENABLED is off but the bucket is bound (ENABLE_ADVISOR; cron.ts),
// so the stated periods hold when the advisor is switched off.
//
// Every rule is bounded per run (RETENTION_LIMITS); what is left waits for the
// next week's run, and the result says which rules hit their bound. Every
// statement selects by age, so a rerun (a retried slot) changes nothing new.
// R2 goes before D1 for the same rows, so a failure leaves the rows to find
// again. The log line is counts only. A rule that throws is logged and the
// others still run; the job then throws, so the slot is released for the next
// tick and the cron's outcome is 'partial' (recordCron's advisor field).
import {advisorLog} from './log.ts';
import {forgetContact} from './contacts.ts';
import type {Env} from '../env.ts';

const DAY = 86400000;
export const RETENTION_DAYS = {bodies: 180, media: 90, reviews: 90, daily: 30, stats: 730, contacts: 90, jobState: 30, exports: 7} as const;
/** Rows (or objects) per rule per run. */
export const RETENTION_LIMITS = {bodies: 20000, media: 500, reviews: 5000, daily: 5000, stats: 5000, contacts: 100, jobState: 2000, exports: 2000} as const;
/** Rows per D1 statement. */
export const RETENTION_CHUNK = 500;
/** Post statuses whose media stay (02: an approved or posted post; scheduled, publishing and partial are on the way or half posted). */
export const KEEP_POST_STATUSES = ['approved', 'scheduled', 'publishing', 'posted', 'partial'] as const;
/** job_state prefixes the age rule clears (02 § Reusing job_state). */
export const AGED_KEY_PREFIXES = ['advisor.flow.', 'advisor.link.', 'advisor.share.'] as const;

export type RetentionRule = keyof typeof RETENTION_LIMITS;
export interface RetentionResult {
  bodies: number; media: number; mediaObjects: number; reviews: number; daily: number; stats: number;
  contacts: number; jobState: number; graphicObjects: number; exports: number;
  more: RetentionRule[];     // rules that hit their bound: more waits for the next run
  failed: RetentionRule[];   // rules that threw (logged by name only)
}
export interface RetentionDeps {limits?: Partial<Record<RetentionRule, number>>; chunk?: number}

const iso = (ms: number): string => new Date(ms).toISOString();
const ID = /^[\w-]{1,64}$/;
const MEDIA_KEY = /^advisor\/media\/[\w-]{1,64}\/[\w-]{1,64}\.[a-z0-9]{1,5}$/;
const EXPORT_DATE = /^advisor\/exports\/[\w-]{1,64}\/(\d{4}-\d{2}-\d{2})(?:-\d+)?\.json$/;
const marks = (n: number): string => Array(n).fill('?').join(',');
const keepPosts = KEEP_POST_STATUSES.map(s => `'${s}'`).join(',');

async function deletePrefix(bucket: R2Bucket, prefix: string): Promise<number> {
  let deleted = 0, cursor: string | undefined;
  do {
    const page = await bucket.list({prefix, cursor, limit: 1000});
    const keys = page.objects.map(o => o.key);
    if (keys.length) { await bucket.delete(keys); deleted += keys.length; }
    cursor = page.truncated ? page.cursor : undefined;
  } while (cursor);
  return deleted;
}

/**
 * Run `statement(limit)` (a bounded UPDATE or DELETE) in chunks until it
 * changes fewer rows than asked, or `max` rows changed. {changed, more}.
 */
async function chunked(max: number, chunk: number, statement: (limit: number) => D1PreparedStatement): Promise<{changed: number; more: boolean}> {
  let changed = 0;
  while (changed < max) {
    const limit = Math.min(chunk, max - changed);
    const n = (await statement(limit).run()).meta.changes ?? 0;
    changed += n;
    if (n < limit) return {changed, more: false};
  }
  return {changed, more: true};
}

/** Message bodies older than 180 days: nulled. */
async function pruneBodies(db: D1Database, now: number, max: number, chunk: number) {
  const cutoff = iso(now - RETENTION_DAYS.bodies * DAY);
  return chunked(max, chunk, limit => db.prepare('UPDATE advisor_messages SET body=NULL WHERE id IN (SELECT id FROM advisor_messages WHERE body IS NOT NULL AND created_at<? LIMIT ?)').bind(cutoff, limit));
}

/** Media older than 90 days that nothing published or approved references: the R2 original and derived files, then the row's key. */
async function pruneMedia(db: D1Database, bucket: R2Bucket, now: number, max: number, chunk: number): Promise<{changed: number; objects: number; more: boolean}> {
  const cutoff = iso(now - RETENTION_DAYS.media * DAY);
  // An unreadable media_json references nothing (json_each would fail the whole statement).
  const unreferenced = `m.r2_key<>'' AND m.created_at<? AND m.publish_state NOT IN ('approved','posted')
    AND NOT EXISTS (SELECT 1 FROM advisor_reports r WHERE r.media_id=m.id AND r.status='published')
    AND NOT EXISTS (SELECT 1 FROM advisor_posts p, json_each(CASE WHEN json_valid(p.media_json) THEN p.media_json ELSE '[]' END) j
      WHERE p.status IN (${keepPosts}) AND j.value=m.id)`;
  let changed = 0, objects = 0;
  while (changed < max) {
    const limit = Math.min(chunk, max - changed);
    const rows = (await db.prepare(`SELECT m.id,m.r2_key FROM advisor_media m WHERE ${unreferenced} ORDER BY m.created_at,m.id LIMIT ?`).bind(cutoff, limit)
      .all<{id: string; r2_key: string}>()).results.filter(r => ID.test(r.id));
    if (!rows.length) return {changed, objects, more: false};
    const ids = rows.map(r => r.id);
    // A duplicate's row points at the first row's object: delete it only when no row outside this set still uses it.
    const keys = [...new Set(rows.map(r => r.r2_key).filter(k => MEDIA_KEY.test(k)))];
    const shared = keys.length ? new Set((await db.prepare(`SELECT DISTINCT r2_key FROM advisor_media WHERE r2_key IN (${marks(keys.length)}) AND id NOT IN (${marks(ids.length)})`)
      .bind(...keys, ...ids).all<{r2_key: string}>()).results.map(r => r.r2_key)) : new Set<string>();
    const gone = keys.filter(k => !shared.has(k));
    if (gone.length) { await bucket.delete(gone); objects += gone.length; }
    for (const id of ids) objects += await deletePrefix(bucket, `advisor/derived/${id}/`);
    const results = await db.batch([
      db.prepare(`UPDATE advisor_media SET r2_key='',derived_at=NULL,derived_error='expired' WHERE id IN (${marks(ids.length)})`).bind(...ids),
      db.prepare(`DELETE FROM job_state WHERE key IN (${marks(ids.length)})`).bind(...ids.map(id => `advisor.caption.${id}`)),
    ]);
    changed += results[0]?.meta.changes ?? 0;
    if (rows.length < limit) return {changed, objects, more: false};
  }
  return {changed, objects, more: true};
}

/** Decided reviews 90 days after the decision. */
async function pruneReviews(db: D1Database, now: number, max: number, chunk: number) {
  const cutoff = iso(now - RETENTION_DAYS.reviews * DAY);
  return chunked(max, chunk, limit => db.prepare("DELETE FROM advisor_reviews WHERE id IN (SELECT id FROM advisor_reviews WHERE status<>'open' AND decided_at IS NOT NULL AND decided_at<? LIMIT ?)").bind(cutoff, limit));
}

/** Daily answers 30 days after they were generated. */
async function pruneDaily(db: D1Database, now: number, max: number, chunk: number) {
  const cutoff = iso(now - RETENTION_DAYS.daily * DAY);
  return chunked(max, chunk, limit => db.prepare('DELETE FROM advisor_daily_answers WHERE key IN (SELECT key FROM advisor_daily_answers WHERE generated_at<? LIMIT ?)').bind(cutoff, limit));
}

/** Post stats older than two years (by their day). */
async function pruneStats(db: D1Database, now: number, max: number, chunk: number) {
  const cutoff = iso(now - RETENTION_DAYS.stats * DAY).slice(0, 10);
  return chunked(max, chunk, limit => db.prepare('DELETE FROM advisor_post_stats WHERE rowid IN (SELECT rowid FROM advisor_post_stats WHERE day<? LIMIT ?)').bind(cutoff, limit));
}

/** Web-only contacts inactive for 90 days, each through forgetContact. */
async function pruneContacts(db: D1Database, bucket: R2Bucket, now: number, max: number): Promise<{changed: number; more: boolean}> {
  const cutoff = iso(now - RETENTION_DAYS.contacts * DAY);
  const ids = (await db.prepare(`SELECT id FROM advisor_contacts WHERE phone_hash IS NULL AND ig_sid IS NULL AND web_session IS NOT NULL AND last_seen_at<?
      ORDER BY last_seen_at,id LIMIT ?`).bind(cutoff, max + 1).all<{id: string}>()).results.map(r => r.id).filter(id => ID.test(id));
  let changed = 0;
  for (const id of ids.slice(0, max)) changed += (await forgetContact(db, bucket, id, new Date(now))).contact;
  return {changed, more: ids.length > max};
}

/** The advisor's expired job_state keys (see the header), and the graphic files of graphic requests that go. */
async function pruneJobState(db: D1Database, bucket: R2Bucket | undefined, now: number, max: number, chunk: number): Promise<{changed: number; objects: number; more: boolean}> {
  const cutoff = iso(now - RETENTION_DAYS.jobState * DAY);
  let changed = 0, objects = 0, more = false;
  const run = async (statement: (limit: number) => D1PreparedStatement) => {
    if (changed >= max) { more = true; return; }
    const r = await chunked(max - changed, chunk, statement);
    changed += r.changed; more ||= r.more;
  };
  const aged = AGED_KEY_PREFIXES.map(() => 'key LIKE ?').join(' OR ');
  await run(limit => db.prepare(`DELETE FROM job_state WHERE key IN (SELECT key FROM job_state WHERE (${aged}) AND updated_at<? LIMIT ?)`)
    .bind(...AGED_KEY_PREFIXES.map(p => `${p}%`), cutoff, limit));
  // Once-markers: advisor.once.<what>.<boat id> (autopub, noconsent, instagram) and advisor.once.homeport.<contact id>.
  await run(limit => db.prepare(`DELETE FROM job_state WHERE key IN (SELECT key FROM job_state WHERE key LIKE 'advisor.once.%' AND updated_at<? AND (
      key LIKE 'advisor.once.noconsent.%'
      OR (key LIKE 'advisor.once.homeport.%' AND NOT EXISTS (SELECT 1 FROM advisor_contacts c WHERE c.id=substr(job_state.key, length('advisor.once.homeport.')+1)))
      OR ((key LIKE 'advisor.once.autopub.%' OR key LIKE 'advisor.once.instagram.%')
        AND NOT EXISTS (SELECT 1 FROM advisor_boats b WHERE b.id=substr(job_state.key, instr(substr(job_state.key, length('advisor.once.')+1), '.')+length('advisor.once.')+1)))
    ) LIMIT ?)`).bind(cutoff, limit));
  // Graphic requests whose post is gone or rejected: the files under advisor/posts/<id>/ first, then the key
  // (only with the bucket bound, like the media rule).
  while (bucket && changed < max) {
    const limit = Math.min(chunk, max - changed);
    const keys = (await db.prepare(`SELECT key FROM job_state WHERE key LIKE 'advisor.graphic.%' AND updated_at<?
        AND NOT EXISTS (SELECT 1 FROM advisor_posts p WHERE p.id=substr(job_state.key, length('advisor.graphic.')+1) AND p.status<>'rejected') ORDER BY key LIMIT ?`)
      .bind(cutoff, limit).all<{key: string}>()).results.map(r => r.key);
    if (!keys.length) break;
    for (const key of keys) { const id = key.slice('advisor.graphic.'.length); if (ID.test(id)) objects += await deletePrefix(bucket, `advisor/posts/${id}/`); }
    changed += (await db.prepare(`DELETE FROM job_state WHERE key IN (${marks(keys.length)})`).bind(...keys).run()).meta.changes ?? 0;
    if (keys.length < limit) break;
    if (changed >= max) more = true;
  }
  return {changed, objects, more};
}

/** "Send me my data" exports in R2 older than 7 days. */
async function pruneExports(bucket: R2Bucket, now: number, max: number): Promise<{changed: number; more: boolean}> {
  const cutoff = now - RETENTION_DAYS.exports * DAY;
  let changed = 0, cursor: string | undefined;
  do {
    const page = await bucket.list({prefix: 'advisor/exports/', cursor, limit: 1000});
    const expired = page.objects.filter(o => {
      const uploaded = o.uploaded ? new Date(o.uploaded).getTime() : NaN;
      if (Number.isFinite(uploaded)) return uploaded < cutoff;
      const date = EXPORT_DATE.exec(o.key)?.[1];
      return date ? Date.parse(`${date}T23:59:59Z`) < cutoff : false;
    }).map(o => o.key);
    const old = expired.slice(0, max - changed);
    if (old.length) { await bucket.delete(old); changed += old.length; }
    if (changed >= max) return {changed, more: Boolean(page.truncated) || expired.length > old.length};
    cursor = page.truncated ? page.cursor : undefined;
  } while (cursor);
  return {changed, more: false};
}

/**
 * The weekly prune: every rule in 02's retention table, bounded per run.
 * Returns counts only; throws after logging when a rule failed.
 */
export async function runRetention(env: Env, now: number = Date.now(), deps: RetentionDeps = {}): Promise<RetentionResult> {
  if (!env.DB) throw Error('storage unavailable');
  const db = env.DB, bucket = env.ADVISOR_MEDIA, chunk = Math.max(1, deps.chunk ?? RETENTION_CHUNK);
  const limit = (rule: RetentionRule): number => Math.max(0, deps.limits?.[rule] ?? RETENTION_LIMITS[rule]);
  const result: RetentionResult = {bodies: 0, media: 0, mediaObjects: 0, reviews: 0, daily: 0, stats: 0, contacts: 0, jobState: 0, graphicObjects: 0, exports: 0, more: [], failed: []};
  const step = async (rule: RetentionRule, fn: () => Promise<{changed: number; more: boolean; objects?: number}>, objects?: 'mediaObjects' | 'graphicObjects') => {
    try {
      const r = await fn();
      result[rule] = r.changed;
      if (objects) result[objects] = r.objects ?? 0;
      if (r.more) result.more.push(rule);
    } catch (error) {
      result.failed.push(rule);
      advisorLog('error', 'advisor_retention_rule_failed', {rule, reason: String((error as Error)?.message).slice(0, 200)});
    }
  };
  // The rules that delete R2 objects run only with the bucket bound: without it they would drop the
  // rows that find the objects and leave the objects behind. Contacts first: forgetContact removes
  // their messages and media outright, so the later rules skip them.
  if (bucket) await step('contacts', () => pruneContacts(db, bucket, now, limit('contacts')));
  await step('bodies', () => pruneBodies(db, now, limit('bodies'), chunk));
  if (bucket) await step('media', () => pruneMedia(db, bucket, now, limit('media'), chunk), 'mediaObjects');
  await step('reviews', () => pruneReviews(db, now, limit('reviews'), chunk));
  await step('daily', () => pruneDaily(db, now, limit('daily'), chunk));
  await step('stats', () => pruneStats(db, now, limit('stats'), chunk));
  await step('jobState', () => pruneJobState(db, bucket, now, limit('jobState'), chunk), 'graphicObjects');
  if (bucket) await step('exports', () => pruneExports(bucket, now, limit('exports')));
  const {more, failed, ...counts} = result;
  advisorLog(failed.length ? 'warn' : 'info', 'advisor_retention', {...counts, more: more.join(',') || 'none', failed: failed.length});
  if (failed.length) throw Error(`retention failed: ${failed.join(',')}`);
  return result;
}
