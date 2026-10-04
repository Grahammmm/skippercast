// Post insights (docs/plans/text-advisor/09-social.md § Insights, SP-10; TA-S7).
//
//   collectInsights    the `insights` slot, 03:00 Pacific: every posted (or partly
//                      posted) post of the last 30 days, its Instagram media insights
//                      and its Page post's reach, reactions, comments and shares
//   storyInsightsTick  every cron tick, at most hourly: Stories younger than 24 hours,
//                      since Meta keeps a Story's insights only while it is up
//
// One row per post, surface and local day in advisor_post_stats (an UPSERT, so a
// rerun the same day replaces the numbers): Meta's values are lifetime totals, so
// the latest row is the post's current count and the rows by day are its growth.
// Columns: views, reach, likes, comments (a Story's `replies`), saved, shares,
// follows, profile_visits; link_taps stays 0 (no media metric gives it). raw_json
// keeps every metric read (profile_activity and ig_reels_avg_watch_time have no
// column) and notes for the metrics Meta did not give.
//
// Tolerance: Meta refuses the whole request (code 100) when one metric does not
// apply to the media, so on code 100 each metric is asked alone and one that is
// still refused counts 0 with a note. Any other failure (the token, a deleted or
// expired media, rate limits after the client's retries) skips that surface of that
// post and writes nothing, so an earlier row is never overwritten with zeros.
// Logs carry Meta's codes only (the Graph client), never ids or tokens.
import {advisorLog} from '../log.ts';
import {localClock, DEFAULT_TZ} from '../cron.ts';
import {fbPostCounts, fbPostReach, igMediaInsights, metaConfig, MetaError} from './meta.ts';
import type {Fetcher, MetaConfig} from './meta.ts';
import type {Env} from '../../env.ts';

export const FEED_METRICS = ['views', 'reach', 'likes', 'comments', 'saved', 'shares', 'follows', 'profile_visits', 'profile_activity'] as const;
export const REELS_METRICS = [...FEED_METRICS, 'ig_reels_avg_watch_time'] as const;
export const STORY_METRICS = ['views', 'reach', 'replies', 'follows', 'profile_visits'] as const;
export const INSIGHTS_DAYS = 30;
export const STORY_LIFE_MS = 24 * 3600000;
export const STORY_TICK_MS = 3600000;
export const MAX_POSTS = 100;
export const LAST_RUN_KEY = 'advisor.insights.last_run';
export const STORY_TICK_KEY = 'advisor.insights.stories_at';
const UNSUPPORTED = 100;   // Meta: "(#100) ... metric ... not supported for this media"
const DAY = 86400000;

export type Platform = 'instagram' | 'facebook';
export const STAT_COLUMNS = ['views', 'reach', 'likes', 'comments', 'saved', 'shares', 'follows', 'profile_visits', 'link_taps'] as const;
export type StatColumn = typeof STAT_COLUMNS[number];
export interface Reading {columns: Record<StatColumn, number>; metrics: Record<string, number>; notes: string[]}
export interface InsightsDeps {fetcher?: Fetcher; sleep?: (ms: number) => Promise<void>}
export interface InsightsResult {posts: number; instagram: number; facebook: number; failed: number; skipped?: string}

interface PostRow {id: string; kind: string; ig_media_id: string | null; fb_post_id: string | null; posted_at: string}

/** The Instagram metrics for a post kind: a Story's, a Reel's (FEED plus the average watch time) or a feed post's. */
export const metricsFor = (kind: string): readonly string[] => kind === 'story' ? STORY_METRICS : kind === 'reel' ? REELS_METRICS : FEED_METRICS;

const zeroColumns = (): Record<StatColumn, number> => Object.fromEntries(STAT_COLUMNS.map(c => [c, 0])) as Record<StatColumn, number>;

/** One media's Instagram reading, metric by metric when Meta refuses the set; null when the media cannot be read now. */
export async function readInstagram(cfg: MetaConfig, mediaId: string, kind: string): Promise<Reading | null> {
  const metrics = metricsFor(kind), notes: string[] = [];
  let values: Record<string, number>;
  try {
    values = await igMediaInsights(cfg, mediaId, metrics);
  } catch (error) {
    if (!(error instanceof MetaError) || error.code !== UNSUPPORTED) return null;
    values = {};
    for (const metric of metrics) {
      try { Object.assign(values, await igMediaInsights(cfg, mediaId, [metric])); }
      catch (each) {
        if (!(each instanceof MetaError) || each.code !== UNSUPPORTED) return null;
        notes.push(`${metric}: unavailable`);
      }
    }
  }
  for (const metric of metrics) {
    if (values[metric] === undefined) { values[metric] = 0; if (!notes.some(n => n.startsWith(`${metric}:`))) notes.push(`${metric}: not returned`); }
  }
  const columns = zeroColumns();
  for (const c of ['views', 'reach', 'likes', 'comments', 'saved', 'shares', 'follows', 'profile_visits'] as const) columns[c] = values[c] ?? 0;
  if (kind === 'story') columns.comments = values.replies ?? 0;
  return {columns, metrics: values, notes};
}

/** One Page post's reading: its unique reach (post_impressions_unique), reactions, comments and shares; parts Meta refuses count 0 with a note. */
export async function readFacebook(cfg: MetaConfig, postId: string): Promise<Reading | null> {
  const notes: string[] = [], metrics: Record<string, number> = {};
  let reached = false;
  try {
    const reach = await fbPostReach(cfg, postId);
    if (reach === null) notes.push('post_impressions_unique: not returned'); else metrics.post_impressions_unique = reach;
    reached = true;
  } catch (error) {
    if (!(error instanceof MetaError) || error.code !== UNSUPPORTED) return null;
    notes.push('post_impressions_unique: unavailable');
  }
  try {
    const counts = await fbPostCounts(cfg, postId);
    for (const [name, value] of Object.entries(counts)) { if (value === null) notes.push(`${name}: not returned`); else metrics[name] = value; }
  } catch (error) {
    // The post itself cannot be read (deleted, the token): nothing to write unless the reach came back.
    if (!reached) return null;
    notes.push(`counts: ${error instanceof MetaError && error.code === UNSUPPORTED ? 'unavailable' : 'failed'}`);
  }
  const columns = zeroColumns();
  columns.reach = metrics.post_impressions_unique ?? 0;
  columns.likes = metrics.reactions ?? 0;
  columns.comments = metrics.comments ?? 0;
  columns.shares = metrics.shares ?? 0;
  return {columns, metrics, notes};
}

/** UPSERT the reading for (post, platform, local day of `now`). */
export async function saveReading(db: D1Database, postId: string, platform: Platform, reading: Reading, now: number): Promise<void> {
  const day = localClock(now, DEFAULT_TZ).date, at = new Date(now).toISOString();
  const raw = JSON.stringify({metrics: reading.metrics, ...(reading.notes.length ? {notes: reading.notes} : {})});
  await db.prepare(`INSERT INTO advisor_post_stats(post_id,platform,day,${STAT_COLUMNS.join(',')},raw_json,fetched_at) VALUES(?,?,?,${STAT_COLUMNS.map(() => '?').join(',')},?,?)
    ON CONFLICT(post_id,platform,day) DO UPDATE SET ${STAT_COLUMNS.map(c => `${c}=excluded.${c}`).join(',')},raw_json=excluded.raw_json,fetched_at=excluded.fetched_at`)
    .bind(postId, platform, day, ...STAT_COLUMNS.map(c => Math.round(reading.columns[c])), raw, at).run();
}

const configFor = (env: Env, deps: InsightsDeps): MetaConfig | null => metaConfig(env, {...(deps.fetcher ? {fetcher: deps.fetcher} : {}), ...(deps.sleep ? {sleep: deps.sleep} : {})});

/** Read and store one post's surfaces. A Story is read on Instagram only, and only while it is up (24 hours). */
async function readPost(env: Env, cfg: MetaConfig, post: PostRow, now: number, out: InsightsResult): Promise<void> {
  const db = env.DB!;
  const storyGone = post.kind === 'story' && now - Date.parse(post.posted_at) >= STORY_LIFE_MS;
  if (post.ig_media_id && !storyGone) {
    const reading = await readInstagram(cfg, post.ig_media_id, post.kind).catch(() => null);
    if (reading) { await saveReading(db, post.id, 'instagram', reading, now); out.instagram++; } else out.failed++;
  }
  // A Page photo Story has no post insights to read; a Page post does.
  if (post.fb_post_id && post.kind !== 'story') {
    const reading = await readFacebook(cfg, post.fb_post_id).catch(() => null);
    if (reading) { await saveReading(db, post.id, 'facebook', reading, now); out.facebook++; } else out.failed++;
  }
}

/** The 03:00 slot: every post published in the last 30 days (newest first, at most 100). */
export async function collectInsights(env: Env, now: number, deps: InsightsDeps = {}): Promise<InsightsResult> {
  const out: InsightsResult = {posts: 0, instagram: 0, facebook: 0, failed: 0};
  const cfg = configFor(env, deps);
  if (!env.DB || !cfg) { out.skipped = 'not-configured'; return out; }
  const posts = (await env.DB.prepare(`SELECT id,kind,ig_media_id,fb_post_id,posted_at FROM advisor_posts WHERE status IN ('posted','partial') AND posted_at IS NOT NULL AND posted_at>=?
    ORDER BY posted_at DESC LIMIT ?`).bind(new Date(now - INSIGHTS_DAYS * DAY).toISOString(), MAX_POSTS).all<PostRow>()).results;
  for (const post of posts) { out.posts++; await readPost(env, cfg, post, now, out); }
  const at = new Date(now).toISOString();
  await env.DB.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at')
    .bind(LAST_RUN_KEY, JSON.stringify({at, ...out}), at).run();
  advisorLog(out.failed ? 'warn' : 'info', 'advisor_insights', {...out});
  return out;
}

/**
 * Every cron tick, at most hourly (job_state advisor.insights.stories_at, claimed
 * with an UPSERT-with-WHERE so two ticks never both run): Stories posted less than
 * 24 hours ago, so their numbers are kept before Meta drops them. 'idle' when
 * nothing ran.
 */
export async function storyInsightsTick(env: Env, now: number, deps: InsightsDeps = {}): Promise<InsightsResult | 'idle'> {
  const cfg = configFor(env, deps);
  if (!env.DB || !cfg) return 'idle';
  const db = env.DB, since = new Date(now - STORY_LIFE_MS).toISOString();
  const posts = (await db.prepare(`SELECT id,kind,ig_media_id,fb_post_id,posted_at FROM advisor_posts WHERE kind='story' AND status IN ('posted','partial')
    AND ig_media_id IS NOT NULL AND posted_at>? ORDER BY posted_at LIMIT ?`).bind(since, MAX_POSTS).all<PostRow>()).results;
  if (!posts.length) return 'idle';
  const at = new Date(now).toISOString();
  const claim = await db.prepare(`INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at
    WHERE job_state.value<=?`).bind(STORY_TICK_KEY, at, at, new Date(now - STORY_TICK_MS + 60000).toISOString()).run();
  if (!claim.meta.changes) return 'idle';
  const out: InsightsResult = {posts: 0, instagram: 0, facebook: 0, failed: 0};
  for (const post of posts) { out.posts++; await readPost(env, cfg, {...post, fb_post_id: null}, now, out); }
  advisorLog(out.failed ? 'warn' : 'info', 'advisor_story_insights', {...out});
  return out;
}

export interface PostStats {
  instagram: (Record<StatColumn, number> & {day: string; fetched_at: string; notes: string[]}) | null;
  facebook: (Record<StatColumn, number> & {day: string; fetched_at: string; notes: string[]}) | null;
  chats: number;
}

/**
 * A posted post's latest numbers per surface, and "chats started": contacts whose
 * first message came from the post's own link (`[via ig:<post id>]`, or the
 * Instagram media id in its place), advisor_contacts.source_post_id.
 */
export async function postStats(db: D1Database, post: {id: string; ig_media_id: string | null}): Promise<PostStats> {
  const rows = (await db.prepare(`SELECT * FROM advisor_post_stats WHERE post_id=? ORDER BY day DESC`).bind(post.id).all<Record<string, unknown>>()).results;
  const latest = (platform: Platform): PostStats['instagram'] => {
    const row = rows.find(r => r.platform === platform);
    if (!row) return null;
    let notes: string[] = [];
    try { const raw = JSON.parse(String(row.raw_json)); if (Array.isArray(raw?.notes)) notes = raw.notes.filter((n: unknown): n is string => typeof n === 'string').slice(0, 20); } catch { notes = []; }
    return {...Object.fromEntries(STAT_COLUMNS.map(c => [c, Number(row[c]) || 0])) as Record<StatColumn, number>, day: String(row.day), fetched_at: String(row.fetched_at), notes};
  };
  const ids = [post.id, ...(post.ig_media_id ? [post.ig_media_id] : [])];
  const chats = (await db.prepare(`SELECT COUNT(*) AS n FROM advisor_contacts WHERE source_post_id IN (${ids.map(() => '?').join(',')})`).bind(...ids).first<{n: number}>())?.n ?? 0;
  return {instagram: latest('instagram'), facebook: latest('facebook'), chats};
}
