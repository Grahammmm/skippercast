// Publishing approved posts to Instagram and the Facebook Page
// (docs/plans/text-advisor/09-social.md § Publishing, SO-4, SP-3, SP-4, SP-5; TA-S2).
//
//   publishDue(env, now, deps)        the cron's every-tick run: `publishing` posts first (a video
//                                     still processing), then `approved` posts whose scheduled_for
//                                     is past or null, at most PUBLISH_PER_TICK, only while
//                                     ADVISOR_SOCIAL_ENABLED is on and Meta is configured
//   publish(env, postId, deps, opts)  one post, idempotent on its status and stored ids
//
// One run of publish:
//   1. A lease (job_state advisor.publish.lock.<id>) so the cron and "post now" never run one post twice.
//   2. Media: every image must be derived (public.jpg, story.jpg; derived_at set) and every video
//      stripped of its container metadata (video.mp4, 00 principle 7): if not, the media job is
//      dispatched and the post waits (still `approved`). A photo or video given up by the job fails
//      the post. An `approved` post is re-checked against admin/posts.ts approvalHold.
//   3. status -> publishing.
//   4. Instagram (when targeted and ig_media_id is not stored): quota first
//      (content_publishing_limit; used up -> scheduled_for = max(scheduled_for, now) + 1 h, status
//      back to `approved`); one container per kind (image, REELS, STORIES, CAROUSEL with
//      is_carousel_item children), stored in ig_container_id the moment it exists so a rerun never
//      makes a second; its status_code polled every 10 s, at most `pollTries` times in this run
//      (IN_PROGRESS -> the post stays `publishing` and the next tick polls again, until
//      VIDEO_DEADLINE_MS); FINISHED -> media_publish, ig_media_id stored, the permalink read and
//      the skipper texted once ("Posted: <permalink>").
//   5. Facebook (when targeted and its id is not stored): a photo (/photos with the caption), a
//      multi-photo post (unpublished /photos then /feed attached_media), a Reel (/video_reels 3-phase
//      upload) or a photo Story (/photo_stories); fb_post_id or fb_story_id stored.
//   6. Every surface done -> `posted`, posted_at, its media `posted`; a surface failed and another
//      done -> `partial` with the error; none done -> `failed`. A failed surface is not tried again
//      until the admin retries (opts.retry), and a retry runs only the surfaces without an id.
//
// TA-S3 (SP-7, SO-5): the post's collaborators (at most 3 usernames; feed images, carousels and
// Reels, never Stories) and user tags (`{username, x, y}`; images only: a photo's container, or a
// carousel's first image item) go on the containers from collaborators_json and user_tags_json.
// A post published with collaborators gets collab_status 'invited'; collabTick (the cron, at most
// hourly) then reads GET /<ig_media_id>/collaborators for invite_status: any still pending (or not
// listed) -> invited, else any declined -> declined, else accepted, for 14 days after posting.
//
// TA-S4 (09 § Daily post and roundup): a daily post, a roundup or a Story card is published from its
// generated graphic (social/graphics.ts): the post waits while the job renders it, and its images
// (the card; the roundup's cover and slides as a carousel) are fetched at /media/post/<id>/<name>.
// An approved post without a time whose kind and region have calendar slots (calendar.json) waits
// for social/calendar.ts to give it one; any other unscheduled approved post is due at once.
//
// Per-post progress that has no column (carousel children, the Page's unpublished photo ids, a
// surface's error while the other is still pending) lives in job_state advisor.publish.<id>.
// Errors kept on the post are MetaError messages (edge, HTTP status, Meta's code and subcode):
// never a token, URL or Meta's message text.
import {advisorSettings} from '../settings.ts';
import {advisorLog} from '../log.ts';
import {t} from '../strings.ts';
import {recordPublish} from '../analytics.ts';
import {requestMediaJob, videoHold, graphicState} from '../media.ts';
import {graphicKeys, graphicName, graphicUrl, usesGraphic} from './graphics.ts';
import {calendarPairs} from './calendar.ts';
import {teamSender} from '../consumer.ts';
import {channelFor} from '../channels/index.ts';
import {approvalHold, mediaIdsOf} from '../admin/posts.ts';
import type {PostRow} from '../admin/posts.ts';
import {COLLABORATORS_MAX, HANDLE, TARGETS_FOR, USER_TAGS_MAX, captionStats} from './drafts.ts';
import type {Target} from './drafts.ts';
import {MetaError, fbFeed, fbPhoto, fbPhotoStory, fbVideoReel, igCollaborators, igContainer, igContainerStatus, igPermalink, igPublish, igPublishingLimit, metaConfig, metaConfigured} from './meta.ts';
import type {Fetcher, IgContainerInput, MetaConfig, UserTag} from './meta.ts';
import type {ConsumerDeps, AdvisorContactRow} from '../types.ts';
import type {Env} from '../../env.ts';

export const PUBLISH_PER_TICK = 5;
export const POLL_EVERY_MS = 10_000;               // 09: status_code once per 10 s
export const POLL_TRIES = 30;                      // 09: up to 5 min (30 x 10 s) when nothing bounds the run
export const CRON_POLL_TRIES = 6;                  // a cron run polls a minute per post; the next tick continues
export const VIDEO_DEADLINE_MS = 30 * 60_000;      // a container still IN_PROGRESS this long after creation fails the surface
export const QUOTA_DEFER_MS = 3600_000;            // 09: quota used up -> scheduled_for += 1 h
export const DEFAULT_QUOTA = 50;                   // 09: 50 API posts per 24 h when Meta's config omits quota_total
export const LEASE_MS = 10 * 60_000;
export const STATE_PREFIX = 'advisor.publish.';
export const COLLAB_KEY = 'advisor.collab.checked_at';  // TA-S3: the collab read's hourly throttle
export const COLLAB_EVERY_MS = 3600_000 - 60_000;       // hourly (a little under, so a tick is never skipped)
export const COLLAB_WINDOW_MS = 14 * 86400_000;         // invites are read for 14 days after posting
export const COLLAB_PER_RUN = 20;
export const LOCK_PREFIX = 'advisor.publish.lock.';

export type PublishOutcome = 'posted' | 'partial' | 'failed' | 'pending' | 'deferred' | 'quota' | 'held' | 'busy' | 'skipped' | 'error';
export interface PublishResult {outcome: PublishOutcome; error?: string}

export interface PublishDeps {
  now?: () => number;                              // the clock (polling reads it again)
  fetcher?: Fetcher;                               // the Graph API (tests: recorded responses)
  sleep?: (ms: number) => Promise<void>;           // between status polls and Meta's retries
  pollTries?: number;                              // status_code reads in this run (default POLL_TRIES)
  consumer?: ConsumerDeps;                         // the skipper's text (default channels/index.ts channelFor)
  dispatch?: (env: Env, file: string) => Promise<number>;   // the media job dispatch (tests)
}

interface PublishState {ig_children?: string[]; ig_started_at?: string; ig_error?: string; fb_photos?: string[]; fb_error?: string}
interface MediaRow {id: string; kind: string; mime: string; r2_key: string; derived_at: string | null; derived_error: string | null; publish_state: string}

const IG_TARGETS: readonly Target[] = ['instagram', 'instagram_story'];
const FB_TARGETS: readonly Target[] = ['facebook', 'facebook_story'];
const parse = <T>(json: string | null, fallback: T): T => { try { return (JSON.parse(json ?? 'null') as T) ?? fallback; } catch { return fallback; } };
const short = (error: unknown): string => error instanceof MetaError || error instanceof TypeError ? error.message.slice(0, 200) : 'unexpected error';
const defaultSleep = (ms: number): Promise<void> => new Promise(resolve => setTimeout(resolve, ms));

/** The public URLs Meta fetches (09 § Media that Meta fetches; routes/advisor.ts /media). */
export const mediaUrls = (base: string, id: string): {feed: string; story: string; video: string} =>
  ({feed: `${base}/media/${id}.jpg`, story: `${base}/media/${id}.story.jpg`, video: `${base}/media/${id}.mp4`});

async function readState(db: D1Database, id: string): Promise<PublishState> {
  const row = await db.prepare('SELECT value FROM job_state WHERE key=?').bind(STATE_PREFIX + id).first<{value: string}>();
  return parse<PublishState>(row?.value ?? null, {});
}
async function writeState(db: D1Database, id: string, state: PublishState, at: string): Promise<void> {
  await db.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at')
    .bind(STATE_PREFIX + id, JSON.stringify(state), at).run();
}

/** The lease: an UPSERT that only takes an expired (or missing) lock. Returns the value to release with, or null. */
async function claim(db: D1Database, id: string, now: number): Promise<string | null> {
  const until = new Date(now + LEASE_MS).toISOString(), at = new Date(now).toISOString();
  const r = await db.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at WHERE job_state.value<?')
    .bind(LOCK_PREFIX + id, until, at, at).run();
  return r.meta.changes ? until : null;
}
const release = (db: D1Database, id: string, until: string): Promise<unknown> =>
  db.prepare('DELETE FROM job_state WHERE key=? AND value=?').bind(LOCK_PREFIX + id, until).run().catch(() => null);

/** The post's surfaces: its targets, limited to what its kind allows. */
export function surfacesOf(post: Pick<PostRow, 'kind' | 'targets_json'>): {ig: boolean; fb: boolean} {
  const allowed = TARGETS_FOR[post.kind] ?? [];
  const targets = parse<unknown[]>(post.targets_json, []).filter((x): x is Target => allowed.includes(x as Target));
  return {ig: targets.some(x => IG_TARGETS.includes(x)), fb: targets.some(x => FB_TARGETS.includes(x))};
}

/** The skipper's "Posted:" text: the boat owner, active, once per post (a deterministic outbound id). */
async function notifySkipper(env: Env, post: PostRow, permalink: string, deps: PublishDeps): Promise<number> {
  if (!post.boat_id || !advisorSettings(env).repliesEnabled) return 0;
  const db = env.DB!;
  const boat = await db.prepare('SELECT owner_contact_id,instagram FROM advisor_boats WHERE id=?').bind(post.boat_id).first<{owner_contact_id: string | null; instagram: string | null}>();
  if (!boat?.owner_contact_id) return 0;
  const contact = await db.prepare("SELECT * FROM advisor_contacts WHERE id=? AND status='active'").bind(boat.owner_contact_id).first<AdvisorContactRow>();
  if (!contact) return 0;
  const handle = boat.instagram?.toLowerCase() ?? null;
  const tagged = Boolean(handle) && (
    parse<string[]>(post.collaborators_json, []).includes(handle!)
    || parse<{username?: string}[]>(post.user_tags_json, []).some(x => x?.username === handle)
    || (captionStats(post.caption).mentions > 0 && post.caption.toLowerCase().includes(`@${handle}`)));
  const text = tagged ? t(contact.language, 'social_posted_tagged', {link: permalink, handle: handle!}) : t(contact.language, 'social_posted', {link: permalink});
  return teamSender(env, deps.consumer ?? {channelFor})(contact, post.id, 'posted', text, null);
}

type Step = {status: 'done'} | {status: 'pending'} | {status: 'quota'} | {status: 'error'; error: string};

/** Poll a container's status_code: FINISHED -> done; IN_PROGRESS past the run's tries -> pending (or an error past the deadline). */
async function pollContainer(cfg: MetaConfig, id: string, startedAt: string | undefined, tries: number, clock: () => number, sleep: (ms: number) => Promise<void>): Promise<Step> {
  for (let n = 0; n < tries; n++) {
    const {status_code} = await igContainerStatus(cfg, id);
    if (status_code === 'FINISHED') return {status: 'done'};
    if (status_code === 'PUBLISHED') return {status: 'error', error: 'the container was already published; check Instagram before retrying'};
    if (status_code === 'ERROR' || status_code === 'EXPIRED') return {status: 'error', error: `the Instagram container ${status_code === 'ERROR' ? 'failed to process' : 'expired'}`};
    if (n < tries - 1) await sleep(POLL_EVERY_MS);
  }
  const started = startedAt ? Date.parse(startedAt) : NaN;
  if (Number.isFinite(started) && clock() - started > VIDEO_DEADLINE_MS) return {status: 'error', error: 'the Instagram video was still processing after 30 minutes'};
  return {status: 'pending'};
}

/** One picture of a post as Meta fetches it: a photo or video's /media URLs, or a generated graphic's. */
interface Item {kind: 'image' | 'video'; feed: string; story: string; video: string}
const mediaItem = (base: string, m: MediaRow): Item => ({kind: m.kind === 'video' ? 'video' : 'image', ...mediaUrls(base, m.id)});
const graphicItem = (base: string, postId: string, key: string): Item => {
  const url = graphicUrl(base, postId, graphicName(key));
  return {kind: 'image', feed: url, story: url, video: ''};
};

interface Run {
  env: Env; db: D1Database; cfg: MetaConfig; post: PostRow; media: MediaRow[]; items: Item[]; state: PublishState; base: string;
  clock: () => number; at: () => string; tries: number; sleep: (ms: number) => Promise<void>; deps: PublishDeps;
}

/** TA-S3: the post's collaborators (valid usernames, at most 3) and user tags (valid, x and y 0-1, at most 20), never on a story. */
export function tagsOf(post: Pick<PostRow, 'kind' | 'collaborators_json' | 'user_tags_json'>): {collaborators: string[]; user_tags: UserTag[]} {
  if (post.kind === 'story') return {collaborators: [], user_tags: []};
  const collaborators = [...new Set(parse<unknown[]>(post.collaborators_json, []).filter((h): h is string => typeof h === 'string' && HANDLE.test(h)))].slice(0, COLLABORATORS_MAX);
  const user_tags = parse<unknown[]>(post.user_tags_json, []).flatMap(raw => {
    const tag = raw as {username?: unknown; x?: unknown; y?: unknown} | null;
    const x = Number(tag?.x), y = Number(tag?.y);
    return typeof tag?.username === 'string' && HANDLE.test(tag.username) && x >= 0 && x <= 1 && y >= 0 && y <= 1 ? [{username: tag.username, x, y}] : [];
  }).slice(0, USER_TAGS_MAX);
  return {collaborators, user_tags};
}

/** The Instagram container input of one item of a carousel; the user tags go on the first image item. */
const itemInput = (item: Item, tags: UserTag[]): IgContainerInput =>
  item.kind === 'video' ? {kind: 'carousel_item', video_url: item.video} : {kind: 'carousel_item', image_url: item.feed, ...(tags.length ? {user_tags: tags} : {})};

/** The containers for this post (children first for a carousel); the parent's id. Stores every id the moment Meta returns it. */
async function createContainer(run: Run): Promise<Step | {status: 'created'; id: string}> {
  const {post, items, cfg, db, state} = run, ig = run.env.META_IG_USER_ID!;
  const caption = post.caption || undefined, first = items[0]!, video = first.kind === 'video';
  const {collaborators, user_tags} = tagsOf(post), collab = collaborators.length ? {collaborators} : {};
  let input: IgContainerInput;
  if (post.kind === 'story') input = video ? {kind: 'story', video_url: first.video} : {kind: 'story', image_url: first.story};
  else if (post.kind === 'reel') input = {kind: 'reel', video_url: first.video, ...(caption ? {caption} : {}), share_to_feed: true, ...collab};
  else if (items.length === 1) {
    if (video) return {status: 'error', error: 'a single video goes out as a reel'};
    input = {kind: 'image', image_url: first.feed, ...(caption ? {caption} : {}), ...collab, ...(user_tags.length ? {user_tags} : {})};
  } else {
    const children = (state.ig_children ?? []).slice(0, items.length);
    const tagged = items.findIndex(m => m.kind === 'image');
    for (let i = children.length; i < items.length; i++) {
      children.push(await igContainer(cfg, ig, itemInput(items[i]!, i === tagged ? user_tags : [])));
      state.ig_children = [...children];
      state.ig_started_at ??= run.at();
      await writeState(db, post.id, state, run.at());
    }
    // A video item must finish processing before the carousel container can name it.
    for (const [i, m] of items.entries()) {
      if (m.kind !== 'video') continue;
      const step = await pollContainer(cfg, children[i]!, state.ig_started_at, run.tries, run.clock, run.sleep);
      if (step.status !== 'done') {
        if (step.status === 'error') { delete state.ig_children; delete state.ig_started_at; }
        return step;
      }
    }
    input = {kind: 'carousel', children, ...(caption ? {caption} : {}), ...collab};
  }
  const id = await igContainer(cfg, ig, input);
  await db.prepare('UPDATE advisor_posts SET ig_container_id=?,updated_at=? WHERE id=?').bind(id, run.at(), post.id).run();
  post.ig_container_id = id;
  state.ig_started_at = run.at();
  await writeState(db, post.id, state, run.at());
  return {status: 'created', id};
}

/** Instagram: quota, container (once), status, media_publish, permalink, the skipper's text. */
async function publishInstagram(run: Run): Promise<Step> {
  const {post, cfg, db, state} = run, ig = run.env.META_IG_USER_ID!;
  try {
    const limit = await igPublishingLimit(cfg, ig);
    if (limit.quota_usage >= (limit.quota_total ?? DEFAULT_QUOTA)) return {status: 'quota'};
    let container = post.ig_container_id;
    if (!container) {
      const made = await createContainer(run);
      if (made.status !== 'created') return made;
      container = made.id;
    }
    const step = await pollContainer(cfg, container, state.ig_started_at, run.tries, run.clock, run.sleep);
    if (step.status === 'pending') return step;
    if (step.status === 'error') {
      // A failed or expired container is dropped so a retry makes a new one; a published one is kept.
      if (!/already published/.test(step.error)) {
        await db.prepare('UPDATE advisor_posts SET ig_container_id=NULL,updated_at=? WHERE id=? AND ig_container_id=?').bind(run.at(), post.id, container).run();
        post.ig_container_id = null; delete state.ig_children; delete state.ig_started_at;
      }
      return step;
    }
    const mediaId = await igPublish(cfg, ig, container);
    // TA-S3: collaborators were invited with the container; the cron reads their answers.
    const invited = post.kind !== 'story' && tagsOf(post).collaborators.length > 0;
    await db.prepare('UPDATE advisor_posts SET ig_media_id=?,collab_status=?,updated_at=? WHERE id=?').bind(mediaId, invited ? 'invited' : null, run.at(), post.id).run();
    post.ig_media_id = mediaId; post.collab_status = invited ? 'invited' : null;
    advisorLog('info', 'advisor_post_published', {surface: 'instagram', kind: post.kind});
    const permalink = await igPermalink(cfg, mediaId).catch(() => null);
    if (permalink) await notifySkipper(run.env, post, permalink, run.deps).catch(error => advisorLog('warn', 'advisor_post_notify_failed', {reason: short(error)}));
    return {status: 'done'};
  } catch (error) {
    // Nothing stored yet: a retry starts the containers again (unfinished children expire on their own).
    if (!post.ig_container_id) { delete state.ig_children; delete state.ig_started_at; }
    return {status: 'error', error: short(error)};
  }
}

/** Facebook Page: one photo, a multi-photo post, a Reel or a photo Story. */
async function publishFacebook(run: Run): Promise<Step> {
  const {post, items, cfg, db, state} = run, page = run.env.META_PAGE_ID!;
  const message = post.caption || undefined, first = items[0]!;
  try {
    if (post.kind === 'story') {
      if (first.kind === 'video') return {status: 'error', error: 'a video Story to the Page is not supported yet'};
      const story = await fbPhotoStory(cfg, page, {url: first.story});
      await db.prepare('UPDATE advisor_posts SET fb_story_id=?,updated_at=? WHERE id=?').bind(story.post_id, run.at(), post.id).run();
      post.fb_story_id = story.post_id;
    } else {
      let id: string;
      if (post.kind === 'reel') {
        const reel = await fbVideoReel(cfg, page, {video_url: first.video, ...(message ? {description: message} : {})});
        id = reel.post_id ?? reel.video_id;
      } else if (items.length === 1) {
        const photo = await fbPhoto(cfg, page, {url: first.feed, ...(message ? {message} : {})});
        id = photo.post_id ?? photo.id;
      } else {
        if (items.some(m => m.kind === 'video')) return {status: 'error', error: 'a multi-photo Page post takes photos only'};
        const photos = (state.fb_photos ?? []).slice(0, items.length);
        for (let i = photos.length; i < items.length; i++) {
          photos.push((await fbPhoto(cfg, page, {url: items[i]!.feed, published: false})).id);
          state.fb_photos = [...photos];
          await writeState(db, post.id, state, run.at());
        }
        id = await fbFeed(cfg, page, {...(message ? {message} : {}), photo_ids: photos});
      }
      await db.prepare('UPDATE advisor_posts SET fb_post_id=?,updated_at=? WHERE id=?').bind(id, run.at(), post.id).run();
      post.fb_post_id = id;
    }
    advisorLog('info', 'advisor_post_published', {surface: 'facebook', kind: post.kind});
    return {status: 'done'};
  } catch (error) {
    return {status: 'error', error: short(error)};
  }
}

async function fail(db: D1Database, id: string, error: string, at: string, from: readonly string[]): Promise<void> {
  await db.prepare(`UPDATE advisor_posts SET status='failed',error=?,updated_at=? WHERE id=? AND status IN (${from.map(() => '?').join(',')})`).bind(error.slice(0, 500), at, id, ...from).run();
}

/**
 * Publish one post (the header's steps). `opts.retry` lets a `partial` or
 * `failed` post run again: only its surfaces without a stored id are tried.
 * Never throws for Meta failures; they end in the post's status and error.
 */
export async function publish(env: Env, postId: string, deps: PublishDeps = {}, opts: {retry?: boolean} = {}): Promise<PublishResult> {
  const db = env.DB, clock = deps.now ?? Date.now;
  if (!db) return {outcome: 'skipped', error: 'no database'};
  const cfg = metaConfig(env, {...(deps.fetcher ? {fetcher: deps.fetcher} : {}), ...(deps.sleep ? {sleep: deps.sleep} : {})});
  if (!cfg) return {outcome: 'skipped', error: 'Meta is not configured'};
  const startedMs = clock(), at = (): string => new Date(clock()).toISOString();
  const lease = await claim(db, postId, startedMs);
  if (!lease) return {outcome: 'busy'};
  let outcome: PublishOutcome = 'skipped', error: string | undefined;
  let kind = 'other';
  try {
    const post = await db.prepare('SELECT * FROM advisor_posts WHERE id=?').bind(postId).first<PostRow>();
    const startable = ['approved', 'publishing', ...(opts.retry ? ['partial', 'failed'] : [])];
    if (!post || !startable.includes(post.status)) return {outcome: 'skipped', error: post ? `the post is ${post.status}` : 'the post no longer exists'};
    kind = post.kind;
    const ids = mediaIdsOf(post);
    const rows = ids.length ? (await db.prepare(`SELECT id,kind,mime,r2_key,derived_at,derived_error,publish_state FROM advisor_media WHERE id IN (${ids.map(() => '?').join(',')})`)
      .bind(...ids).all<MediaRow>()).results : [];
    const media = ids.map(id => rows.find(r => r.id === id)).filter((m): m is MediaRow => Boolean(m));
    const graphic = usesGraphic(post), rendered = graphic ? await graphicState(db, post.id) : null;
    if (post.status !== 'publishing') {
      // Consent, the boat's verification and the photos' reviews are checked again before anything goes out.
      const hold = await approvalHold(db, post, {videoPendingOk: true, graphicPendingOk: true});
      if (hold) { await fail(db, post.id, hold, at(), [post.status]); outcome = 'held'; error = hold; return {outcome, error}; }
    }
    if ((!graphic && !media.length) || media.length < ids.length) { error = 'a photo of this post no longer exists'; await fail(db, post.id, error, at(), startable); outcome = 'failed'; return {outcome, error}; }
    if (rendered?.status === 'pending') {
      // TA-S4: the daily card, the roundup slides or the Story card are still being rendered by the media job.
      await requestMediaJob(env, clock(), deps.dispatch ? {dispatch: deps.dispatch} : {});
      outcome = 'deferred';
      return {outcome};
    }
    const base = advisorSettings(env).publicBase;
    const items = graphic ? graphicKeys(rendered).map(k => graphicItem(base, post.id, k)) : media.map(m => mediaItem(base, m));
    if (!items.length) { error = 'the graphic of this post could not be made'; await fail(db, post.id, error, at(), startable); outcome = 'failed'; return {outcome, error}; }
    const broken = media.find(m => !m.r2_key || m.derived_error || (m.kind !== 'image' && m.kind !== 'video'));
    if (broken) {
      error = (broken.r2_key && videoHold(broken)) || 'a photo of this post could not be prepared for posting';
      await fail(db, post.id, error, at(), startable); outcome = 'failed'; return {outcome, error};
    }
    if (media.some(m => !m.derived_at)) {
      // public.jpg and story.jpg, and a video's stripped copy (no location metadata), come from the media job
      // (09 § Derived images): ask for them and wait.
      await requestMediaJob(env, clock(), deps.dispatch ? {dispatch: deps.dispatch} : {});
      outcome = 'deferred';
      return {outcome};
    }
    const {ig, fb} = surfacesOf(post);
    if (!ig && !fb) { error = 'the post has no surface to go to'; await fail(db, post.id, error, at(), startable); outcome = 'failed'; return {outcome, error}; }
    const state = await readState(db, post.id);
    if (opts.retry) { delete state.ig_error; delete state.fb_error; }
    const claimed = await db.prepare(`UPDATE advisor_posts SET status='publishing',error=NULL,updated_at=? WHERE id=? AND status=?`).bind(at(), post.id, post.status).run();
    if (!claimed.meta.changes) return {outcome: 'skipped', error: 'the post changed'};
    const run: Run = {env, db, cfg, post, media, items, state, base, clock, at, tries: Math.max(1, deps.pollTries ?? POLL_TRIES),
      sleep: deps.sleep ?? defaultSleep, deps};

    let igPending = false;
    if (ig && !post.ig_media_id && !state.ig_error) {
      const step = await publishInstagram(run);
      if (step.status === 'quota') {
        const base = Math.max(post.scheduled_for ? Date.parse(post.scheduled_for) || 0 : 0, clock());
        await db.prepare("UPDATE advisor_posts SET status='approved',scheduled_for=?,updated_at=? WHERE id=? AND status='publishing'")
          .bind(new Date(base + QUOTA_DEFER_MS).toISOString(), at(), post.id).run();
        await writeState(db, post.id, state, at());
        advisorLog('warn', 'advisor_publish_quota', {kind: post.kind});
        outcome = 'quota';
        return {outcome};
      }
      if (step.status === 'pending') igPending = true;
      if (step.status === 'error') state.ig_error = step.error;
    }
    if (fb && !(post.kind === 'story' ? post.fb_story_id : post.fb_post_id) && !state.fb_error) {
      const step = await publishFacebook(run);
      if (step.status === 'error') state.fb_error = step.error;
    }
    if (igPending) { await writeState(db, post.id, state, at()); outcome = 'pending'; return {outcome}; }

    const igDone = !ig || Boolean(post.ig_media_id), fbDone = !fb || Boolean(post.kind === 'story' ? post.fb_story_id : post.fb_post_id);
    const errors = [state.ig_error && !igDone ? `instagram: ${state.ig_error}` : null, state.fb_error && !fbDone ? `facebook: ${state.fb_error}` : null].filter(Boolean).join('; ');
    if (igDone && fbDone) {
      await db.batch([
        db.prepare("UPDATE advisor_posts SET status='posted',posted_at=?,error=NULL,updated_at=? WHERE id=? AND status='publishing'").bind(at(), at(), post.id),
        ...(ids.length ? [db.prepare(`UPDATE advisor_media SET publish_state='posted' WHERE publish_state='approved' AND id IN (${ids.map(() => '?').join(',')})`).bind(...ids)] : []),
        db.prepare('DELETE FROM job_state WHERE key=?').bind(STATE_PREFIX + post.id),
      ]);
      outcome = 'posted';
    } else {
      const anyDone = (ig && Boolean(post.ig_media_id)) || (fb && Boolean(post.kind === 'story' ? post.fb_story_id : post.fb_post_id));
      outcome = anyDone ? 'partial' : 'failed';
      error = errors || 'publishing failed';
      await db.prepare("UPDATE advisor_posts SET status=?,error=?,updated_at=? WHERE id=? AND status='publishing'").bind(outcome, error.slice(0, 500), at(), post.id).run();
      await writeState(db, post.id, state, at());
      advisorLog('warn', 'advisor_publish_failed', {kind: post.kind, outcome});
    }
    return {outcome, ...(error ? {error} : {})};
  } catch (thrown) {
    // A D1 failure mid-run: the post stays where it was (a `publishing` post is picked up again next tick).
    advisorLog('error', 'advisor_publish_error', {reason: short(thrown)});
    outcome = 'error';
    return {outcome, error: 'publishing stopped on an internal error; it is tried again on the next run'};
  } finally {
    await release(db, postId, lease);
    if (outcome !== 'skipped') recordPublish(env, {kind, outcome, ms: clock() - startedMs});
  }
}

export interface PublishDueResult {status: 'off' | 'ran'; outcomes: PublishOutcome[]}

/**
 * The cron's run (every 15-minute tick, not a daily slot): nothing unless
 * ADVISOR_SOCIAL_ENABLED is on and the Meta secrets are set; then `publishing`
 * posts (a video still processing) and due `approved` posts, oldest due first,
 * at most PUBLISH_PER_TICK, one after the other. Due: scheduled_for past, or
 * no scheduled_for and no calendar slot for the post's kind and region (TA-S4:
 * those wait for social/calendar.ts to give them a slot's time).
 */
export async function publishDue(env: Env, now: number = Date.now(), deps: PublishDeps = {}): Promise<PublishDueResult> {
  if (!env.DB || !advisorSettings(env).socialEnabled || !metaConfigured(env)) return {status: 'off', outcomes: []};
  const pairs = calendarPairs();
  const unslotted = pairs.length ? ` AND (kind || '|' || region) NOT IN (${pairs.map(() => '?').join(',')})` : '';
  const due = (await env.DB.prepare(`SELECT id FROM advisor_posts WHERE status='publishing'
    OR (status='approved' AND (scheduled_for<=? OR (scheduled_for IS NULL${unslotted})))
    ORDER BY CASE status WHEN 'publishing' THEN 0 ELSE 1 END, COALESCE(scheduled_for, approved_at, updated_at), id LIMIT ?`)
    .bind(new Date(now).toISOString(), ...pairs, PUBLISH_PER_TICK).all<{id: string}>()).results;
  const outcomes: PublishOutcome[] = [];
  for (const {id} of due) outcomes.push((await publish(env, id, {pollTries: CRON_POLL_TRIES, ...deps})).outcome);
  return {status: 'ran', outcomes};
}

// ---- TA-S3: collaborator invites ---------------------------------------------------------------------

export type CollabStatus = 'invited' | 'accepted' | 'declined';
/** The post's collab_status from Meta's list: any of ours pending or not listed -> invited; else any declined -> declined; else accepted. */
export function collabStatusOf(invited: readonly string[], listed: readonly {username: string; invite_status: string | null}[]): CollabStatus {
  const status = invited.map(name => listed.find(c => c.username === name.toLowerCase())?.invite_status ?? 'pending');
  if (status.some(s => s !== 'accepted' && s !== 'declined')) return 'invited';
  return status.includes('declined') ? 'declined' : 'accepted';
}

export interface CollabTickResult {status: 'off' | 'throttled' | 'ran'; read: number; changed: number}

/**
 * The cron's collab read (TA-S3), at most once an hour (job_state
 * advisor.collab.checked_at): posted or partial posts with an Instagram media
 * id, collab_status 'invited' and posted in the last 14 days, oldest first, at
 * most COLLAB_PER_RUN, each one GET /<ig_media_id>/collaborators. A read that
 * fails leaves the post as it was; a changed status is written.
 */
export async function collabTick(env: Env, now: number = Date.now(), deps: Pick<PublishDeps, 'fetcher' | 'sleep'> = {}): Promise<CollabTickResult> {
  const db = env.DB;
  if (!db || !advisorSettings(env).socialEnabled || !metaConfigured(env)) return {status: 'off', read: 0, changed: 0};
  const at = new Date(now).toISOString(), cutoff = new Date(now - COLLAB_EVERY_MS).toISOString();
  const claimed = await db.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at WHERE job_state.value<=?')
    .bind(COLLAB_KEY, at, at, cutoff).run();
  if (!claimed.meta.changes) return {status: 'throttled', read: 0, changed: 0};
  const cfg = metaConfig(env, {...(deps.fetcher ? {fetcher: deps.fetcher} : {}), ...(deps.sleep ? {sleep: deps.sleep} : {}), attempts: 1})!;
  const posts = (await db.prepare(`SELECT id,kind,collaborators_json,user_tags_json,ig_media_id FROM advisor_posts WHERE collab_status='invited' AND ig_media_id IS NOT NULL
    AND status IN ('posted','partial') AND posted_at>=? ORDER BY posted_at, id LIMIT ?`).bind(new Date(now - COLLAB_WINDOW_MS).toISOString(), COLLAB_PER_RUN)
    .all<Pick<PostRow, 'id' | 'kind' | 'collaborators_json' | 'user_tags_json' | 'ig_media_id'>>()).results;
  let read = 0, changed = 0;
  for (const post of posts) {
    const invited = tagsOf(post).collaborators;
    if (!invited.length) continue;
    try {
      const listed = await igCollaborators(cfg, post.ig_media_id!);
      read++;
      const next = collabStatusOf(invited, listed);
      if (next !== 'invited') {
        const r = await db.prepare("UPDATE advisor_posts SET collab_status=?,updated_at=? WHERE id=? AND collab_status='invited'").bind(next, at, post.id).run();
        changed += r.meta.changes ? 1 : 0;
      }
    } catch (error) {
      advisorLog('warn', 'advisor_collab_read_failed', {reason: short(error)});
    }
  }
  if (changed) advisorLog('info', 'advisor_collab_updated', {count: changed});
  return {status: 'ran', read, changed};
}
