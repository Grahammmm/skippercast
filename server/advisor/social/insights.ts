// Post insights (docs/plans/text-advisor/09-social.md § Insights, SP-10; TA-S7).
//
//   collectInsights    the `insights` slot, 03:00 Pacific: every posted (or partly
//                      posted) post of the last 30 days, its Instagram media insights
//                      and its Page post's reach, reactions, comments and shares
//   storyInsightsTick  every cron tick, at most hourly: Stories younger than 24 hours,
//                      since Meta keeps a Story's insights only while it is up
//
// One row per post, surface and local day in advisor_post_stats (an UPSERT, so a
// rerun the same day replaces the numbers it measured). Meta's values are lifetime
// totals. Facebook engagement keeps the last measured counts and their individual
// timestamps in the latest row when a new reading is incomplete.
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

interface PostRow {id: string; kind: string; ig_media_id: string | null; fb_post_id: string | null; posted_at: string; ig_posted_at: string | null}

/** H8 #13: when the Instagram Story went up: Instagram's own success time, else (legacy rows) the first surface's. */
const STORY_START = 'COALESCE(ig_posted_at, posted_at)';
const storyStart = (post: Pick<PostRow, 'posted_at' | 'ig_posted_at'>): string => post.ig_posted_at ?? post.posted_at;

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

const FACEBOOK_ENGAGEMENT = {likes: 'reactions', comments: 'comments', shares: 'shares'} as const;
type EngagementColumn = keyof typeof FACEBOOK_ENGAGEMENT;
const engagementColumns = Object.keys(FACEBOOK_ENGAGEMENT) as EngagementColumn[];

/** One Page post's reading. The metrics map contains only measurements Meta actually returned. */
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

interface StatsRaw {
  metrics?: Record<string, number>;
  notes?: string[];
  engagement_measured_at?: Record<EngagementColumn, string | null>;
}

function statsRaw(row: Record<string, unknown>): StatsRaw {
  try { return JSON.parse(String(row.raw_json)) ?? {}; } catch { return {}; }
}

function measuredAt(row: Record<string, unknown>, raw: StatsRaw, column: EngagementColumn): string | null {
  // Legacy rows have no per-metric timestamps. Only a provider value present in
  // raw_json is evidence of measurement; the integer column may be a placeholder.
  if (raw.engagement_measured_at) return raw.engagement_measured_at[column] ?? null;
  return typeof raw.metrics?.[FACEBOOK_ENGAGEMENT[column]] === 'number' ? String(row.fetched_at) : null;
}

/** How often the Facebook compare-and-set write re-reads after another writer changed the day's row. */
const SAVE_ATTEMPTS = 5;

/** UPSERT the reading for (post, platform, local day of `now`). */
export async function saveReading(db: D1Database, postId: string, platform: Platform, reading: Reading, now: number): Promise<void> {
  const day = localClock(now, DEFAULT_TZ).date, at = new Date(now).toISOString();
  const raw: StatsRaw = {metrics: reading.metrics, ...(reading.notes.length ? {notes: reading.notes} : {})};
  const columns = {...reading.columns};
  if (platform !== 'facebook') {
    await db.prepare(`INSERT INTO advisor_post_stats(post_id,platform,day,${STAT_COLUMNS.join(',')},raw_json,fetched_at) VALUES(?,?,?,${STAT_COLUMNS.map(() => '?').join(',')},?,?)
      ON CONFLICT(post_id,platform,day) DO UPDATE SET ${STAT_COLUMNS.map(c => `${c}=excluded.${c}`).join(',')},raw_json=excluded.raw_json,fetched_at=excluded.fetched_at`)
      .bind(postId, platform, day, ...STAT_COLUMNS.map(c => Math.round(columns[c])), JSON.stringify(raw), at).run();
    return;
  }
  const timestamps: Record<EngagementColumn, string | null> = {likes: null, comments: null, shares: null};
  for (const c of engagementColumns) if (reading.metrics[FACEBOOK_ENGAGEMENT[c]] !== undefined) timestamps[c] = at;
  const missing = engagementColumns.filter(c => timestamps[c] === null);
  if (missing.length) {
    // Carry each unmeasured metric from the latest earlier day that measured it
    // (including pre-upgrade rows); the same day's row is merged below.
    const previous = (await db.prepare(`SELECT * FROM advisor_post_stats WHERE post_id=? AND platform='facebook' AND day<? AND fetched_at<=? ORDER BY day DESC`)
      .bind(postId, day, at).all<Record<string, unknown>>()).results;
    for (const row of previous) {
      const prior = statsRaw(row);
      for (const c of missing) {
        if (timestamps[c] !== null) continue;
        const measured = measuredAt(row, prior, c);
        if (measured !== null) { timestamps[c] = measured; columns[c] = Number(row[c]); }
      }
      if (missing.every(c => timestamps[c] !== null)) break;
    }
  }
  raw.engagement_measured_at = timestamps;
  // H8 #7: overlapping runs may write the same day's row between our read and our
  // write. Merge per metric against the row as it is now and write it only if it is
  // still that row (compare-and-set on fetched_at and raw_json), re-reading on a lost
  // race: the newer reading keeps the row's reach and notes, and each engagement
  // metric keeps its newest measurement whichever order the writes land in. A
  // reading older than everything stored changes nothing.
  for (let attempt = 0; attempt < SAVE_ATTEMPTS; attempt++) {
    const current = await db.prepare(`SELECT * FROM advisor_post_stats WHERE post_id=? AND platform='facebook' AND day=?`).bind(postId, day).first<Record<string, unknown>>();
    if (!current) {
      const inserted = await db.prepare(`INSERT INTO advisor_post_stats(post_id,platform,day,${STAT_COLUMNS.join(',')},raw_json,fetched_at) VALUES(?,'facebook',?,${STAT_COLUMNS.map(() => '?').join(',')},?,?)
        ON CONFLICT(post_id,platform,day) DO NOTHING`).bind(postId, day, ...STAT_COLUMNS.map(c => Math.round(columns[c])), JSON.stringify(raw), at).run();
      if (inserted.meta.changes) return;
      continue;
    }
    const merged = mergeFacebook(current, {columns, raw, fetched_at: at});
    if (!merged) return;
    const updated = await db.prepare(`UPDATE advisor_post_stats SET ${STAT_COLUMNS.map(c => `${c}=?`).join(',')},raw_json=?,fetched_at=?
      WHERE post_id=? AND platform='facebook' AND day=? AND fetched_at=? AND raw_json=?`)
      .bind(...STAT_COLUMNS.map(c => Math.round(merged.columns[c])), JSON.stringify(merged.raw), merged.fetched_at, postId, day, current.fetched_at, current.raw_json).run();
    if (updated.meta.changes) return;
  }
  throw Error('insights: the Facebook stats row kept changing; not written');
}

interface FacebookRow {columns: Record<StatColumn, number>; raw: StatsRaw; fetched_at: string}

/** The day's Facebook row merged with a reading, or null when the reading adds nothing newer. */
function mergeFacebook(current: Record<string, unknown>, incoming: FacebookRow): FacebookRow | null {
  const currentRaw = statsRaw(current), currentAt = String(current.fetched_at);
  const stored: FacebookRow = {columns: Object.fromEntries(STAT_COLUMNS.map(c => [c, Number(current[c]) || 0])) as Record<StatColumn, number>, raw: currentRaw, fetched_at: currentAt};
  const incomingBase = incoming.fetched_at >= currentAt, base = incomingBase ? incoming : stored;
  const columns = {...base.columns}, timestamps = {} as Record<EngagementColumn, string | null>;
  let changed = incomingBase;
  for (const c of engagementColumns) {
    const mine = incoming.raw.engagement_measured_at?.[c] ?? null, theirs = measuredAt(current, currentRaw, c);
    const take = mine !== null && (theirs === null || mine > theirs || (mine === theirs && incomingBase));
    timestamps[c] = take ? mine : theirs;
    columns[c] = take ? incoming.columns[c] : stored.columns[c];
    if (take && !incomingBase) changed = true;
  }
  return changed ? {columns, raw: {...base.raw, engagement_measured_at: timestamps}, fetched_at: base.fetched_at} : null;
}

const configFor = (env: Env, deps: InsightsDeps): MetaConfig | null => metaConfig(env, {...(deps.fetcher ? {fetcher: deps.fetcher} : {}), ...(deps.sleep ? {sleep: deps.sleep} : {})});

/** Read and store one post's surfaces. A Story is read on Instagram only, and only while it is up (24 hours). */
async function readPost(env: Env, cfg: MetaConfig, post: PostRow, now: number, out: InsightsResult): Promise<void> {
  const db = env.DB!;
  const storyGone = post.kind === 'story' && now - Date.parse(storyStart(post)) >= STORY_LIFE_MS;
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
  const posts = (await env.DB.prepare(`SELECT id,kind,ig_media_id,fb_post_id,posted_at,ig_posted_at FROM advisor_posts WHERE status IN ('posted','partial') AND posted_at IS NOT NULL AND posted_at>=?
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
  const posts = (await db.prepare(`SELECT id,kind,ig_media_id,fb_post_id,posted_at,ig_posted_at FROM advisor_posts WHERE kind='story' AND status IN ('posted','partial')
    AND ig_media_id IS NOT NULL AND ${STORY_START}>? ORDER BY ${STORY_START} LIMIT ?`).bind(since, MAX_POSTS).all<PostRow>()).results;
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

type SurfaceStats = Record<StatColumn, number> & {day: string; fetched_at: string; notes: string[]};
type FacebookStats = Omit<SurfaceStats, EngagementColumn> & Record<EngagementColumn, number | null> & {
  engagement: Record<EngagementColumn, {measuredAt: string | null; stale: boolean}>;
};
export interface PostStats {
  instagram: SurfaceStats | null;
  facebook: FacebookStats | null;
  chats: number;
}

/**
 * A posted post's latest numbers per surface, and "chats started": contacts whose
 * first message came from the post's own link (`[via ig:<post id>]`, or the
 * Instagram media id in its place), advisor_contacts.source_post_id.
 */
export async function postStats(db: D1Database, post: {id: string; ig_media_id: string | null}): Promise<PostStats> {
  const rows = (await db.prepare(`SELECT * FROM advisor_post_stats WHERE post_id=? ORDER BY day DESC`).bind(post.id).all<Record<string, unknown>>()).results;
  const surface = (row: Record<string, unknown>, raw: StatsRaw): SurfaceStats => {
    const notes = Array.isArray(raw.notes) ? raw.notes.filter(n => typeof n === 'string').slice(0, 20) : [];
    return {...Object.fromEntries(STAT_COLUMNS.map(c => [c, Number(row[c]) || 0])) as Record<StatColumn, number>, day: String(row.day), fetched_at: String(row.fetched_at), notes};
  };
  const ig = rows.find(r => r.platform === 'instagram');
  const fbRows = rows.filter(r => r.platform === 'facebook'), fb = fbRows[0];
  let facebook: FacebookStats | null = null;
  if (fb) {
    const raw = statsRaw(fb);
    const latest = surface(fb, raw);
    const engagement = {} as FacebookStats['engagement'];
    const values = {} as Record<EngagementColumn, number | null>;
    for (const c of engagementColumns) {
      let at = measuredAt(fb, raw, c), value: number | null = at === null ? null : latest[c];
      let stale = at !== null && raw.metrics?.[FACEBOOK_ENGAGEMENT[c]] === undefined;
      if (at === null) {
        // H8 #6: a latest row with no measurement of this metric (e.g. a legacy row
        // whose count was not returned) shows the latest earlier measured value, a
        // measured zero included, with its measurement time; never a placeholder 0.
        for (const row of fbRows.slice(1)) {
          const earlier = measuredAt(row, statsRaw(row), c);
          if (earlier !== null) { at = earlier; value = Number(row[c]) || 0; stale = true; break; }
        }
      }
      engagement[c] = {measuredAt: at, stale};
      values[c] = value;
      // The admin table already displays notes beside the numbers.
      if (at === null) latest.notes.push(`${c}: unavailable`);
      else if (stale) latest.notes.push(`${c}: stale (last measured ${at})`);
    }
    facebook = {...latest, ...values, engagement};
  }
  const ids = [post.id, ...(post.ig_media_id ? [post.ig_media_id] : [])];
  const chats = (await db.prepare(`SELECT COUNT(*) AS n FROM advisor_contacts WHERE source_post_id IN (${ids.map(() => '?').join(',')})`).bind(...ids).first<{n: number}>())?.n ?? 0;
  return {instagram: ig ? surface(ig, statsRaw(ig)) : null, facebook, chats};
}
