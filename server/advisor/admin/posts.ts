// Social posts in the admin (docs/plans/text-advisor/08-website.md § Admin,
// Queue and Posts; 09 § Drafts; TA-S1): the read side (a post's card detail,
// the Posts view's list) and the `post` review decision that
// admin/decisions.ts runs for the queue and the Posts view alike.
//
//   approve   status draft -> approved, approved_by/at, optional scheduled_for;
//             its media queued -> approved (public, the media job asked for public.jpg)
//   edit      caption, targets, collaborators, user tags, scheduled_for checked, then approved
//   reject    status rejected
//
// Approval is refused (409) while a photo is held: a has_person (or nsfw) photo
// whose media review is not approved, a media review still open, a rejected
// photo, a boat that is not verified or whose photo consent is no longer
// active (05 § Verification and § Consent).
//
// TA-S2, publishing an approved post (social/publish.ts):
//   post now   approved -> scheduled_for cleared, published in the request (one status read for a
//              video; the cron's next tick continues one still processing)
//   schedule   approved -> scheduled_for set (or cleared: the next tick posts it)
//   retry      partial or failed -> publish again, only the surfaces without a stored id
// Post now and retry need ADVISOR_SOCIAL_ENABLED and the Meta secrets.
import {adminMediaUrl} from './queue.ts';
import {reviewId} from '../contacts.ts';
import {consentActive} from '../intake/skippers.ts';
import {bumpPagesVersion} from '../intake/reports.ts';
import {requestMediaJob} from '../media.ts';
import {advisorLog} from '../log.ts';
import {COLLABORATORS_MAX, HANDLE, POST_KINDS, POST_STATUSES, REVIEW_REASON, TARGETS_FOR, USER_TAGS_MAX, captionProblem, captionStats, cleanCaption} from '../social/drafts.ts';
import type {PostKind, Target, UserTag} from '../social/drafts.ts';
// TA-S2: publishing.
import {advisorSettings} from '../settings.ts';
import {metaConfigured} from '../social/meta.ts';
import {publish} from '../social/publish.ts';
import type {PublishDeps, PublishOutcome} from '../social/publish.ts';
import type {Env} from '../../env.ts';

export const POSTS_PAGE = 50;
export const SCHEDULE_MAX_DAYS = 60;

export interface PostRow {
  id: string; kind: PostKind; region: string; boat_id: string | null; media_json: string; caption: string; collaborators_json: string | null;
  user_tags_json: string | null; targets_json: string; status: string; scheduled_for: string | null; ig_container_id: string | null; ig_media_id: string | null;
  fb_post_id: string | null; fb_story_id: string | null; collab_status: string | null; error: string | null; created_by: string;
  approved_by: string | null; approved_at: string | null; posted_at: string | null; created_at: string; updated_at: string;
}

const parse = <T>(json: string | null, fallback: T): T => { try { const v = JSON.parse(json ?? 'null'); return v ?? fallback; } catch { return fallback; } };
export const mediaIdsOf = (post: Pick<PostRow, 'media_json'>): string[] => parse<unknown[]>(post.media_json, []).filter((m): m is string => typeof m === 'string' && /^[\w-]{1,64}$/.test(m)).slice(0, 10);

interface HoldMedia {id: string; kind: string; has_person: number | null; publish_state: string; credit: string | null; r2_key: string; open_review: number}
async function mediaOf(db: D1Database, ids: string[]): Promise<HoldMedia[]> {
  if (!ids.length) return [];
  const rows = (await db.prepare(`SELECT m.id,m.kind,m.has_person,m.publish_state,m.credit,m.r2_key,
      (SELECT COUNT(*) FROM advisor_reviews r WHERE r.kind='media' AND r.ref_id=m.id AND r.status='open') AS open_review
      FROM advisor_media m WHERE m.id IN (${ids.map(() => '?').join(',')})`).bind(...ids).all<HoldMedia>()).results;
  return ids.map(id => rows.find(r => r.id === id)).filter((r): r is HoldMedia => Boolean(r));
}

/** Why the post cannot be approved yet, or null (the hold reasons in the header). */
export async function approvalHold(db: D1Database, post: Pick<PostRow, 'boat_id' | 'media_json'>): Promise<string | null> {
  const ids = mediaIdsOf(post), media = await mediaOf(db, ids);
  if (!ids.length || media.length < ids.length) return 'a photo of this post no longer exists';
  for (const m of media) {
    if (m.publish_state === 'rejected') return 'a photo of this post was rejected';
    if (m.open_review) return 'a photo of this post is waiting for its photo review';
    if (m.has_person === 1 && m.publish_state !== 'approved') return 'a photo with a person in it needs its photo review approved first';
  }
  if (post.boat_id) {
    const boat = await db.prepare('SELECT status,consent_photos_at,consent_revoked_at FROM advisor_boats WHERE id=?').bind(post.boat_id)
      .first<{status: string; consent_photos_at: string | null; consent_revoked_at: string | null}>();
    if (!boat) return 'the boat no longer exists';
    if (!consentActive(boat)) return 'the boat has not given (or has revoked) photo consent';
    if (boat.status !== 'verified') return 'verify the boat first (Skippers view)';
  }
  return null;
}

/** A post as the admin sees it: fields parsed, the boat, each photo (admin thumbnail, hold state), the caption counts and the hold. */
export async function postView(db: D1Database, post: PostRow): Promise<Record<string, unknown>> {
  const ids = mediaIdsOf(post), media = await mediaOf(db, ids);
  const boat = post.boat_id ? await db.prepare('SELECT id,name,slug,status,instagram FROM advisor_boats WHERE id=?').bind(post.boat_id).first<Record<string, unknown>>() : null;
  const review = await reviewId('post', post.id, REVIEW_REASON);
  const open = await db.prepare("SELECT 1 AS x FROM advisor_reviews WHERE id=? AND status='open'").bind(review).first();
  return {
    id: post.id, kind: post.kind, region: post.region, status: post.status, caption: post.caption, caption_stats: captionStats(post.caption),
    targets: parse<string[]>(post.targets_json, []), allowed_targets: TARGETS_FOR[post.kind] ?? [], collaborators: parse<string[]>(post.collaborators_json, []),
    user_tags: parse<UserTag[]>(post.user_tags_json, []), scheduled_for: post.scheduled_for, error: post.error, created_by: post.created_by,
    ig_media_id: post.ig_media_id, fb_post_id: post.fb_post_id, fb_story_id: post.fb_story_id, collab_status: post.collab_status,   // TA-S2
    approved_by: post.approved_by, approved_at: post.approved_at, posted_at: post.posted_at, created_at: post.created_at, updated_at: post.updated_at,
    boat: boat ?? null,
    media: media.map(m => ({id: m.id, kind: m.kind, has_person: m.has_person === null ? null : m.has_person === 1, publish_state: m.publish_state, credit: m.credit,
      review_open: m.open_review > 0, thumb: m.r2_key ? adminMediaUrl(m.id) : null, original: m.r2_key ? adminMediaUrl(m.id, 'original') : null})),
    review_id: open ? review : null,
    hold: post.status === 'draft' ? await approvalHold(db, post) : null,
  };
}

/** The queue card's detail for a `post` review: {post}, or null when the post is gone. */
export async function postDetail(db: D1Database, id: string): Promise<Record<string, unknown> | null> {
  const post = await db.prepare('SELECT * FROM advisor_posts WHERE id=?').bind(id).first<PostRow>();
  return post ? {post: await postView(db, post)} : null;
}

export interface PostsQuery {status?: string | null; kind?: string | null; cursor?: string | null}
const encode = (row: {updated_at: string; id: string}): string => btoa(`${row.updated_at}|${row.id}`).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '');
function decode(cursor: string | null | undefined): {updated_at: string; id: string} | null {
  if (!cursor || !/^[\w-]{1,200}$/.test(cursor)) return null;
  try {
    const [updated_at, id] = atob(cursor.replaceAll('-', '+').replaceAll('_', '/')).split('|');
    return updated_at && id && /^\d{4}-\d{2}-\d{2}T[\d:.]+Z$/.test(updated_at) && /^[\w-]{1,64}$/.test(id) ? {updated_at, id} : null;
  } catch { return null; }
}

/** GET /api/admin/posts: newest change first, 50 a page; status (any of POST_STATUSES, or 'all') and kind filters. Unknown values are refused. */
export async function listPosts(db: D1Database, query: PostsQuery = {}): Promise<{posts: Record<string, unknown>[]; next: string | null} | {error: string}> {
  const status = query.status || 'all', kind = query.kind || '';
  if (status !== 'all' && !(POST_STATUSES as readonly string[]).includes(status)) return {error: 'unknown status'};
  if (kind && !(POST_KINDS as readonly string[]).includes(kind)) return {error: 'unknown kind'};
  const where: string[] = [], args: unknown[] = [];
  if (status !== 'all') { where.push('status=?'); args.push(status); }
  if (kind) { where.push('kind=?'); args.push(kind); }
  const after = decode(query.cursor);
  if (after) { where.push('(updated_at<? OR (updated_at=? AND id<?))'); args.push(after.updated_at, after.updated_at, after.id); }
  const rows = (await db.prepare(`SELECT * FROM advisor_posts${where.length ? ` WHERE ${where.join(' AND ')}` : ''} ORDER BY updated_at DESC, id DESC LIMIT ?`)
    .bind(...args, POSTS_PAGE + 1).all<PostRow>()).results;
  const page = rows.slice(0, POSTS_PAGE);
  return {posts: await Promise.all(page.map(p => postView(db, p))), next: rows.length > POSTS_PAGE ? encode(page.at(-1)!) : null};
}

// ---- the decision ------------------------------------------------------------------------------

export interface PostPatch {caption?: string; targets?: Target[]; collaborators?: string[]; user_tags?: UserTag[]; scheduled_for?: string | null}
const EDIT_FIELDS = new Set(['caption', 'targets', 'collaborators', 'user_tags', 'scheduled_for']);

/** The checked patch for `kind`, or an error. `approve` takes only scheduled_for. */
export function postPatch(kind: PostKind, patch: unknown, decision: 'approve' | 'edit', now: number): {patch: PostPatch} | {error: string} {
  if (patch === undefined || patch === null) return decision === 'edit' ? {error: 'an edit needs post fields'} : {patch: {}};
  if (typeof patch !== 'object' || Array.isArray(patch)) return {error: 'patch must be an object'};
  const input = patch as Record<string, unknown>, out: PostPatch = {};
  for (const key of Object.keys(input)) {
    if (!EDIT_FIELDS.has(key)) return {error: `unknown field ${key.slice(0, 30)}`};
    if (decision === 'approve' && key !== 'scheduled_for') return {error: 'approve takes only scheduled_for; send the other fields as an edit'};
  }
  if ('caption' in input) {
    if (typeof input.caption !== 'string') return {error: 'caption must be text'};
    const caption = cleanCaption(input.caption);
    if (!caption && kind !== 'story') return {error: 'the caption is empty'};
    const problem = captionProblem(caption);
    if (problem) return {error: problem};
    out.caption = caption;
  }
  if ('targets' in input) {
    const allowed = TARGETS_FOR[kind] ?? [];
    if (!Array.isArray(input.targets) || !input.targets.length || input.targets.some(t => !allowed.includes(t as Target))) return {error: `targets must be some of ${allowed.join(', ')}`};
    out.targets = allowed.filter(t => (input.targets as unknown[]).includes(t));
  }
  if ('collaborators' in input) {
    const list = input.collaborators;
    if (!Array.isArray(list) || list.length > COLLABORATORS_MAX) return {error: `collaborators: at most ${COLLABORATORS_MAX} Instagram usernames`};
    const handles = list.map(h => typeof h === 'string' ? h.trim().replace(/^@/, '').toLowerCase() : '');
    if (handles.some(h => !HANDLE.test(h))) return {error: 'collaborators must be Instagram usernames'};
    if (kind === 'story' && handles.length) return {error: 'a story takes no collaborators'};
    out.collaborators = [...new Set(handles)];
  }
  if ('user_tags' in input) {
    const list = input.user_tags;
    if (!Array.isArray(list) || list.length > USER_TAGS_MAX) return {error: `user_tags: at most ${USER_TAGS_MAX}`};
    const tags: UserTag[] = [];
    for (const tag of list) {
      const t = tag as {username?: unknown; x?: unknown; y?: unknown} | null;
      const username = typeof t?.username === 'string' ? t.username.trim().replace(/^@/, '').toLowerCase() : '';
      const x = Number(t?.x), y = Number(t?.y);
      if (!HANDLE.test(username) || !(x >= 0 && x <= 1) || !(y >= 0 && y <= 1)) return {error: 'each user tag is {username, x, y} with x and y from 0 to 1'};
      tags.push({username, x, y});
    }
    if (tags.length && kind !== 'photo' && kind !== 'carousel') return {error: 'only a photo takes user tags'};
    out.user_tags = tags;
  }
  if ('scheduled_for' in input) {
    if (input.scheduled_for === null || input.scheduled_for === '') out.scheduled_for = null;
    else {
      const ms = typeof input.scheduled_for === 'string' ? Date.parse(input.scheduled_for) : NaN;
      if (!Number.isFinite(ms)) return {error: 'scheduled_for must be a date and time'};
      if (ms <= now) return {error: 'scheduled_for must be in the future'};
      if (ms > now + SCHEDULE_MAX_DAYS * 86400000) return {error: `scheduled_for must be within ${SCHEDULE_MAX_DAYS} days`};
      out.scheduled_for = new Date(ms).toISOString();
    }
  }
  if (decision === 'edit' && !Object.keys(out).length) return {error: 'an edit needs post fields'};
  return {patch: out};
}

export type PostDecisionOutcome = {status: 'ok'} | {status: 'invalid'; error: string} | {status: 'conflict'; error: string};

/**
 * The `post` review's effect (decideReview runs it before closing the review).
 * Idempotent: a post no longer in draft answers conflict, so a repeat of an
 * applied decision is caught by decideReview's closed review first.
 */
export async function decidePost(env: Env, postId: string, decision: 'approve' | 'edit' | 'reject', patch: unknown, by: string | null, now: number,
  deps: {dispatch?: (env: Env, file: string) => Promise<number>} = {}): Promise<PostDecisionOutcome> {
  const db = env.DB!, at = new Date(now).toISOString();
  const post = await db.prepare('SELECT * FROM advisor_posts WHERE id=?').bind(postId).first<PostRow>();
  if (!post) return {status: 'conflict', error: 'the post no longer exists'};
  if (post.status !== 'draft') return {status: 'conflict', error: `the post is ${post.status}`};
  if (decision === 'reject') {
    await db.prepare("UPDATE advisor_posts SET status='rejected',updated_at=? WHERE id=? AND status='draft'").bind(at, post.id).run();
    return {status: 'ok'};
  }
  const checked = postPatch(post.kind, patch, decision, now);
  if ('error' in checked) return {status: 'invalid', error: checked.error};
  const hold = await approvalHold(db, post);
  if (hold) return {status: 'conflict', error: hold};
  const p = checked.patch, sets: string[] = [], args: unknown[] = [];
  if (p.caption !== undefined) { sets.push('caption=?'); args.push(p.caption); }
  if (p.targets !== undefined) { sets.push('targets_json=?'); args.push(JSON.stringify(p.targets)); }
  if (p.collaborators !== undefined) { sets.push('collaborators_json=?'); args.push(p.collaborators.length ? JSON.stringify(p.collaborators) : null); }
  if (p.user_tags !== undefined) { sets.push('user_tags_json=?'); args.push(p.user_tags.length ? JSON.stringify(p.user_tags) : null); }
  if (p.scheduled_for !== undefined) { sets.push('scheduled_for=?'); args.push(p.scheduled_for); }
  const ids = mediaIdsOf(post);
  const [approved] = await db.batch([
    db.prepare(`UPDATE advisor_posts SET ${[...sets, "status='approved'", 'approved_by=?', 'approved_at=?', 'updated_at=?'].join(',')} WHERE id=? AND status='draft'`)
      .bind(...args, by, at, at, post.id),
    // The photos become public with the post (09 § Media that Meta fetches serves approved and posted media).
    db.prepare(`UPDATE advisor_media SET publish_state='approved' WHERE publish_state='queued' AND id IN (${ids.map(() => '?').join(',')})`).bind(...ids),
  ]);
  if (approved?.meta.changes) {
    await bumpPagesVersion(db, now);
    await requestMediaJob(env, now, deps.dispatch ? {dispatch: deps.dispatch} : {});
    advisorLog('info', 'advisor_post_approved', {kind: post.kind, edited: Object.keys(p).filter(k => k !== 'scheduled_for').length > 0, scheduled: Boolean(p.scheduled_for ?? post.scheduled_for)});
  }
  return {status: 'ok'};
}

// ---- TA-S2: post now, schedule, retry ------------------------------------------------------------

export type PostActionOutcome = {status: 'ok'; post: Record<string, unknown>; outcome?: PublishOutcome; error?: string}
  | {status: 'not-found'} | {status: 'invalid'; error: string} | {status: 'conflict'; error: string};

const loadPost = (db: D1Database, id: string): Promise<PostRow | null> =>
  /^[\w-]{1,64}$/.test(id) ? db.prepare('SELECT * FROM advisor_posts WHERE id=?').bind(id).first<PostRow>() : Promise.resolve(null);

/** Why this deploy cannot publish now, or null. */
function cannotPublish(env: Env): string | null {
  if (!advisorSettings(env).socialEnabled) return 'social publishing is switched off (ADVISOR_SOCIAL_ENABLED)';
  if (!metaConfigured(env)) return 'the Meta secrets are not set';
  return null;
}

async function afterPublish(env: Env, id: string, result: {outcome: PublishOutcome; error?: string}): Promise<PostActionOutcome> {
  if (result.outcome === 'busy') return {status: 'conflict', error: 'the post is being published right now'};
  const post = await loadPost(env.DB!, id);
  if (!post) return {status: 'not-found'};
  return {status: 'ok', post: await postView(env.DB!, post), outcome: result.outcome, ...(result.error ? {error: result.error} : {})};
}

/** POST /api/admin/posts/:id/publish: an approved post now (its schedule cleared). */
export async function postNow(env: Env, id: string, now: number, deps: PublishDeps = {}): Promise<PostActionOutcome> {
  const db = env.DB!, post = await loadPost(db, id);
  if (!post) return {status: 'not-found'};
  if (post.status !== 'approved') return {status: 'conflict', error: `the post is ${post.status}`};
  const blocked = cannotPublish(env);
  if (blocked) return {status: 'conflict', error: blocked};
  await db.prepare("UPDATE advisor_posts SET scheduled_for=NULL,updated_at=? WHERE id=? AND status='approved'").bind(new Date(now).toISOString(), id).run();
  return afterPublish(env, id, await publish(env, id, {pollTries: 1, ...deps}));
}

/** POST /api/admin/posts/:id/schedule {scheduled_for}: an approved post's time (within 60 days; null clears it, so the next tick posts it). */
export async function schedulePost(env: Env, id: string, input: unknown, now: number): Promise<PostActionOutcome> {
  const db = env.DB!, post = await loadPost(db, id);
  if (!post) return {status: 'not-found'};
  if (post.status !== 'approved') return {status: 'conflict', error: `the post is ${post.status}`};
  const body = input && typeof input === 'object' && !Array.isArray(input) ? input as Record<string, unknown> : {};
  if (!('scheduled_for' in body)) return {status: 'invalid', error: 'scheduled_for is required (null clears it)'};
  const checked = postPatch(post.kind, {scheduled_for: body.scheduled_for}, 'approve', now);
  if ('error' in checked) return {status: 'invalid', error: checked.error};
  await db.prepare("UPDATE advisor_posts SET scheduled_for=?,updated_at=? WHERE id=? AND status='approved'").bind(checked.patch.scheduled_for ?? null, new Date(now).toISOString(), id).run();
  return {status: 'ok', post: await postView(db, (await loadPost(db, id))!)};
}

/** POST /api/admin/posts/:id/retry: a partial or failed post again; only its surfaces without an id are tried. */
export async function retryPost(env: Env, id: string, deps: PublishDeps = {}): Promise<PostActionOutcome> {
  const post = await loadPost(env.DB!, id);
  if (!post) return {status: 'not-found'};
  if (post.status !== 'partial' && post.status !== 'failed') return {status: 'conflict', error: `the post is ${post.status}`};
  const blocked = cannotPublish(env);
  if (blocked) return {status: 'conflict', error: blocked};
  return afterPublish(env, id, await publish(env, id, {pollTries: 1, ...deps}, {retry: true}));
}
