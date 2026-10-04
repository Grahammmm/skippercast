// The Meta Graph API client for Instagram and the Facebook Page
// (docs/plans/text-advisor/09-social.md § Publishing, "Graph API client"; TA-S0).
//
//   graph(cfg, method, path, params)   one call: the versioned base, the token and
//                                      appsecret_proof on every call, a 20 s timeout,
//                                      a small retry with backoff on HTTP 5xx and on
//                                      Meta's rate-limit codes 4, 17, 32 and 613
//   ig* / fb* / pageInfo               the calls TA-S2 publishes with, each one request
//                                      shape (tests/test_advisor_meta.mjs pins them)
//
// Raw fetch, no SDK, like server/boat-lookup.ts. The token travels in the query
// (GET) or the form body (POST) and never in a log line: errors are logged with
// the HTTP status, Meta's `code`, `error_subcode` and `fbtrace_id`, the edge
// name and the attempt, nothing else (no URL, no body, no message text, which
// can echo parameters). `fetcher` and `sleep` are injected by the tests.
//
// Credentials come from Worker secrets (01 § secrets): META_APP_SECRET for the
// proof, META_PAGE_TOKEN (the Facebook-Login route: a Page token that does not
// expire and serves both the Page and the linked Instagram account),
// META_IG_USER_ID and META_PAGE_ID. META_IG_TOKEN (an Instagram-Login token) is
// declared in env.ts but unused on this route.
import {advisorLog} from '../log.ts';
import {hex} from '../ids.ts';
import type {Env} from '../../env.ts';

/** Graph API version (developers.facebook.com/docs/graph-api/changelog/versions, checked 2026-10-04: v26.0 released 2026-07-29). */
export const GRAPH_VERSION = 'v26.0';
export const GRAPH_BASE = `https://graph.facebook.com/${GRAPH_VERSION}`;
/** The resumable upload host the Page's Reels upload sends the video URL to (3-phase upload, phase 2). */
export const RUPLOAD_BASE = `https://rupload.facebook.com/video-upload/${GRAPH_VERSION}`;
export const TIMEOUT_MS = 20_000;
export const MAX_ATTEMPTS = 3;
export const BACKOFF_MS: readonly number[] = [2_000, 8_000];
/** 4 app rate limit, 17 user rate limit, 32 Page rate limit, 613 call-rate limit. */
export const RETRY_CODES: ReadonlySet<number> = new Set([4, 17, 32, 613]);

export type Fetcher = (url: string, init: RequestInit) => Promise<Response>;
export interface MetaConfig {
  token: string;               // a Page token (Facebook-Login route) or, in meta-token.mjs, the user token
  appSecret: string;           // META_APP_SECRET: the key of appsecret_proof
  fetcher?: Fetcher;
  sleep?: (ms: number) => Promise<void>;
  base?: string;               // tests only
  attempts?: number;           // at most this many tries (default MAX_ATTEMPTS; the health read uses 1)
}
export type Params = Record<string, string | number | boolean | null | undefined>;

/** A failed Graph call. Holds only what is safe to log: never the token, URL or message text. */
export class MetaError extends Error {
  readonly status: number; readonly code: number | null; readonly subcode: number | null; readonly fbtraceId: string | null; readonly edge: string;
  constructor(edge: string, status: number, code: number | null, subcode: number | null, fbtraceId: string | null) {
    super(`meta ${edge} failed: HTTP ${status}${code !== null ? ` code ${code}` : ''}${subcode !== null ? ` subcode ${subcode}` : ''}`);
    this.name = 'MetaError'; this.edge = edge; this.status = status; this.code = code; this.subcode = subcode; this.fbtraceId = fbtraceId;
  }
  /** Worth a retry: a server error or one of the rate-limit codes. */
  get retryable(): boolean { return this.status >= 500 || (this.code !== null && RETRY_CODES.has(this.code)); }
}

/** The Meta secrets this deploy has: {configured} only when the publishing ones are all set (09 § Setup step 4). */
export function metaConfigured(env: Pick<Env, 'META_APP_SECRET' | 'META_PAGE_TOKEN' | 'META_IG_USER_ID' | 'META_PAGE_ID'>): boolean {
  return Boolean(env.META_APP_SECRET && env.META_PAGE_TOKEN && env.META_IG_USER_ID && env.META_PAGE_ID);
}
/** The client config from Worker secrets, or null when publishing is not configured. */
export function metaConfig(env: Env, overrides: Partial<MetaConfig> = {}): MetaConfig | null {
  return metaConfigured(env) ? {token: env.META_PAGE_TOKEN!, appSecret: env.META_APP_SECRET!, ...overrides} : null;
}

const encoder = new TextEncoder();
/** appsecret_proof: lowercase hex HMAC-SHA256 of the access token, keyed with the app secret. */
export async function appsecretProof(token: string, appSecret: string): Promise<string> {
  const key = await crypto.subtle.importKey('raw', encoder.encode(appSecret), {name: 'HMAC', hash: 'SHA-256'}, false, ['sign']);
  return hex(await crypto.subtle.sign('HMAC', key, encoder.encode(token)));
}

/** The edge named in a log line: the path's last segment when it is a word ("media_publish"), else "node" (an id). */
export const edgeOf = (path: string): string => {
  const last = path.split('?')[0]!.split('/').filter(Boolean).at(-1) ?? '';
  return /^[a-z_]{1,40}$/.test(last) ? last : 'node';
};

const ID = /^[\w.-]{1,64}$/;
function requireId(value: string, what: string): string {
  if (typeof value !== 'string' || !ID.test(value)) throw new TypeError(`${what} must be an id`);
  return value;
}
const defaultSleep = (ms: number): Promise<void> => new Promise(resolve => setTimeout(resolve, ms));
const num = (v: unknown): number | null => typeof v === 'number' && Number.isFinite(v) ? v : typeof v === 'string' && /^\d{1,9}$/.test(v) ? Number(v) : null;

function form(params: Params): URLSearchParams {
  const out = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null) out.set(k, String(v));
  return out;
}

/** The error a failed response describes; the body's message is read for nothing but its codes. */
async function failure(edge: string, response: Response): Promise<MetaError> {
  let error: {code?: unknown; error_subcode?: unknown; fbtrace_id?: unknown} = {};
  try { error = ((await response.json()) as {error?: typeof error})?.error ?? {}; } catch { /* not JSON */ }
  const trace = typeof error.fbtrace_id === 'string' && /^[\w-]{1,64}$/.test(error.fbtrace_id) ? error.fbtrace_id : null;
  return new MetaError(edge, response.status, num(error.code), num(error.error_subcode), trace);
}

function logFailure(error: MetaError, attempt: number, retrying: boolean): void {
  advisorLog(retrying ? 'warn' : 'error', 'advisor_meta_error', {edge: error.edge, status: error.status, code: error.code, subcode: error.subcode,
    fbtrace_id: error.fbtraceId, attempt, retrying});
}

/**
 * One Graph API call. `path` is relative to the versioned base ("/<id>/media").
 * The token and appsecret_proof are added to the query (GET) or the form body
 * (POST). Retries a 5xx or a rate-limit code at most MAX_ATTEMPTS times in all,
 * waiting BACKOFF_MS between; a network failure is retried only for a GET (a
 * POST that timed out may have been applied). Throws MetaError.
 */
export async function graph<T = Record<string, unknown>>(cfg: MetaConfig, method: 'GET' | 'POST', path: string, params: Params = {}): Promise<T> {
  if (!path.startsWith('/') || path.includes('?') || path.includes('#') || path.includes('..')) throw new TypeError('graph path must be an absolute path without a query');
  const edge = edgeOf(path), fetcher = cfg.fetcher ?? ((url: string, init: RequestInit) => fetch(url, init)), sleep = cfg.sleep ?? defaultSleep;
  const all = form({...params, access_token: cfg.token, appsecret_proof: await appsecretProof(cfg.token, cfg.appSecret)});
  const url = `${cfg.base ?? GRAPH_BASE}${path}`, attempts = Math.max(1, Math.min(cfg.attempts ?? MAX_ATTEMPTS, MAX_ATTEMPTS));
  for (let attempt = 1; ; attempt++) {
    let response: Response;
    try {
      response = method === 'GET'
        ? await fetcher(`${url}?${all}`, {method, signal: AbortSignal.timeout(TIMEOUT_MS)})
        : await fetcher(url, {method, signal: AbortSignal.timeout(TIMEOUT_MS), headers: {'content-type': 'application/x-www-form-urlencoded'}, body: all.toString()});
    } catch (cause) {
      const retrying = method === 'GET' && attempt < attempts;
      advisorLog(retrying ? 'warn' : 'error', 'advisor_meta_error', {edge, status: 0, code: null, subcode: null, fbtrace_id: null, attempt, retrying,
        reason: (cause as Error)?.name === 'TimeoutError' ? 'timeout' : 'network'});
      if (!retrying) throw new MetaError(edge, 0, null, null, null);
      await sleep(BACKOFF_MS[attempt - 1] ?? BACKOFF_MS.at(-1)!);
      continue;
    }
    if (response.ok) {
      try { return await response.json() as T; } catch { throw new MetaError(edge, response.status, null, null, null); }
    }
    const error = await failure(edge, response);
    const retrying = error.retryable && attempt < attempts;
    logFailure(error, attempt, retrying);
    if (!retrying) throw error;
    await sleep(BACKOFF_MS[attempt - 1] ?? BACKOFF_MS.at(-1)!);
  }
}

// ---- Instagram (two-step publishing: a container, then media_publish) ----------------------

export type IgContainerKind = 'image' | 'reel' | 'story' | 'carousel_item' | 'carousel';
export interface UserTag {username: string; x: number; y: number}
export interface IgContainerInput {
  kind: IgContainerKind;
  image_url?: string; video_url?: string;      // a public https URL Meta fetches (09 § Media that Meta fetches)
  caption?: string;                            // not on stories or carousel items
  collaborators?: string[];                    // up to 3 usernames; feed images, carousels and Reels only (SP-7)
  user_tags?: UserTag[];                       // images and carousel items
  children?: string[];                         // carousel: the item container ids, 2-10
  share_to_feed?: boolean;                     // reels
}

/** The form fields of POST /<ig-user-id>/media for one container (tests pin each kind's shape). */
export function igContainerParams(input: IgContainerInput): Params {
  const video = Boolean(input.video_url);
  const https = (u: string | undefined): string | undefined => {
    if (u === undefined) return undefined;
    if (!/^https:\/\/[^\s]+$/.test(u)) throw new TypeError('media URLs must be https');
    return u;
  };
  const p: Params = {};
  switch (input.kind) {
    case 'image':
      p.image_url = https(input.image_url); break;
    case 'reel':
      p.media_type = 'REELS'; p.video_url = https(input.video_url);
      if (input.share_to_feed !== undefined) p.share_to_feed = input.share_to_feed;
      break;
    case 'story':
      p.media_type = 'STORIES'; if (video) p.video_url = https(input.video_url); else p.image_url = https(input.image_url);
      break;
    case 'carousel_item':
      p.is_carousel_item = true; if (video) { p.media_type = 'VIDEO'; p.video_url = https(input.video_url); } else p.image_url = https(input.image_url);
      break;
    case 'carousel':
      if (!input.children || input.children.length < 2 || input.children.length > 10) throw new TypeError('a carousel takes 2 to 10 items');
      p.media_type = 'CAROUSEL'; p.children = input.children.map(c => requireId(c, 'child')).join(',');
      break;
  }
  if (input.kind !== 'carousel' && !p.image_url && !p.video_url) throw new TypeError('a container needs image_url or video_url');
  if (input.caption !== undefined && input.kind !== 'story' && input.kind !== 'carousel_item') p.caption = input.caption;
  if (input.collaborators?.length && (input.kind === 'image' || input.kind === 'reel' || input.kind === 'carousel')) p.collaborators = JSON.stringify(input.collaborators.slice(0, 3));
  if (input.user_tags?.length && (input.kind === 'image' || input.kind === 'carousel_item')) p.user_tags = JSON.stringify(input.user_tags);
  return p;
}

/** POST /<ig-user-id>/media: a container; its id. */
export async function igContainer(cfg: MetaConfig, igUserId: string, input: IgContainerInput): Promise<string> {
  const r = await graph<{id?: string}>(cfg, 'POST', `/${requireId(igUserId, 'ig user')}/media`, igContainerParams(input));
  return requireId(String(r.id ?? ''), 'container');
}

export type IgStatusCode = 'EXPIRED' | 'ERROR' | 'FINISHED' | 'IN_PROGRESS' | 'PUBLISHED';
/** GET /<container-id>?fields=status_code,status: where a (video) container is. */
export async function igContainerStatus(cfg: MetaConfig, containerId: string): Promise<{status_code: IgStatusCode | null; status: string | null}> {
  const r = await graph<{status_code?: string; status?: string}>(cfg, 'GET', `/${requireId(containerId, 'container')}`, {fields: 'status_code,status'});
  const code = ['EXPIRED', 'ERROR', 'FINISHED', 'IN_PROGRESS', 'PUBLISHED'].includes(String(r.status_code)) ? r.status_code as IgStatusCode : null;
  return {status_code: code, status: typeof r.status === 'string' ? r.status.slice(0, 200) : null};
}

/** POST /<ig-user-id>/media_publish creation_id=<container>: the published media id. */
export async function igPublish(cfg: MetaConfig, igUserId: string, containerId: string): Promise<string> {
  const r = await graph<{id?: string}>(cfg, 'POST', `/${requireId(igUserId, 'ig user')}/media_publish`, {creation_id: requireId(containerId, 'container')});
  return requireId(String(r.id ?? ''), 'media');
}

export interface PublishingLimit {quota_usage: number; quota_total: number | null; quota_duration: number | null}
/** The content_publishing_limit response's numbers ({data: [{quota_usage, config: {quota_total, quota_duration}}]}); null when absent. */
export function parsePublishingLimit(body: unknown): PublishingLimit | null {
  const row = (body as {data?: unknown[]} | null)?.data?.[0] as {quota_usage?: unknown; config?: {quota_total?: unknown; quota_duration?: unknown}} | undefined;
  const usage = num(row?.quota_usage);
  if (usage === null) return null;
  return {quota_usage: usage, quota_total: num(row?.config?.quota_total), quota_duration: num(row?.config?.quota_duration)};
}
/** GET /<ig-user-id>/content_publishing_limit?fields=quota_usage,config (09: 50 API posts per 24 h). */
export async function igPublishingLimit(cfg: MetaConfig, igUserId: string): Promise<PublishingLimit> {
  const parsed = parsePublishingLimit(await graph(cfg, 'GET', `/${requireId(igUserId, 'ig user')}/content_publishing_limit`, {fields: 'quota_usage,config'}));
  if (!parsed) throw new MetaError('content_publishing_limit', 200, null, null, null);
  return parsed;
}

/** GET /<ig-media-id>?fields=permalink: the post's public link (the skipper's "Posted:" text, 09 step 6). */
export async function igPermalink(cfg: MetaConfig, mediaId: string): Promise<string | null> {
  const r = await graph<{permalink?: string}>(cfg, 'GET', `/${requireId(mediaId, 'media')}`, {fields: 'permalink'});
  return typeof r.permalink === 'string' && /^https:\/\/(?:www\.)?instagram\.com\//.test(r.permalink) ? r.permalink : null;
}

// ---- Facebook Page ------------------------------------------------------------------------------

/**
 * POST /<page-id>/photos: a photo post with its message, published now or
 * scheduled by Meta (`scheduled_publish_time`, epoch seconds, 10 min to 30 days
 * ahead, with published=false). Returns the photo id and the feed post id.
 */
export async function fbPhoto(cfg: MetaConfig, pageId: string, input: {url: string; message?: string; scheduled_publish_time?: number; published?: boolean}): Promise<{id: string; post_id: string | null}> {
  if (!/^https:\/\/\S+$/.test(input.url)) throw new TypeError('the photo URL must be https');
  const scheduled = input.scheduled_publish_time !== undefined;
  const r = await graph<{id?: string; post_id?: string}>(cfg, 'POST', `/${requireId(pageId, 'page')}/photos`, {url: input.url, message: input.message,
    published: scheduled ? false : (input.published ?? true), scheduled_publish_time: input.scheduled_publish_time});
  return {id: requireId(String(r.id ?? ''), 'photo'), post_id: typeof r.post_id === 'string' && ID.test(r.post_id) ? r.post_id : null};
}

/**
 * A Page Reel, the 3-phase upload: (1) POST /<page-id>/video_reels
 * upload_phase=start -> video_id; (2) POST rupload.facebook.com/video-upload/<v>/<video_id>
 * with the header `file_url` (Meta fetches the video; that host takes the token
 * as `Authorization: OAuth`, not the Graph query, so this one call carries no
 * appsecret_proof); (3) POST /<page-id>/video_reels upload_phase=finish,
 * video_state=PUBLISHED, description. Returns the video id (and post id when Meta gives one).
 */
export async function fbVideoReel(cfg: MetaConfig, pageId: string, input: {video_url: string; description?: string}): Promise<{video_id: string; post_id: string | null}> {
  if (!/^https:\/\/\S+$/.test(input.video_url)) throw new TypeError('the video URL must be https');
  const page = requireId(pageId, 'page');
  const start = await graph<{video_id?: string}>(cfg, 'POST', `/${page}/video_reels`, {upload_phase: 'start'});
  const videoId = requireId(String(start.video_id ?? ''), 'video');
  const fetcher = cfg.fetcher ?? ((url: string, init: RequestInit) => fetch(url, init));
  let uploaded: Response;
  try {
    uploaded = await fetcher(`${RUPLOAD_BASE}/${videoId}`, {method: 'POST', signal: AbortSignal.timeout(TIMEOUT_MS),
      headers: {Authorization: `OAuth ${cfg.token}`, file_url: input.video_url}});
  } catch {
    advisorLog('error', 'advisor_meta_error', {edge: 'video_upload', status: 0, code: null, subcode: null, fbtrace_id: null, attempt: 1, retrying: false, reason: 'network'});
    throw new MetaError('video_upload', 0, null, null, null);
  }
  if (!uploaded.ok) { const error = await failure('video_upload', uploaded); logFailure(error, 1, false); throw error; }
  const done = await graph<{success?: boolean; post_id?: string}>(cfg, 'POST', `/${page}/video_reels`, {upload_phase: 'finish', video_id: videoId, video_state: 'PUBLISHED', description: input.description});
  if (done.success === false) throw new MetaError('video_reels', 200, null, null, null);
  return {video_id: videoId, post_id: typeof done.post_id === 'string' && ID.test(done.post_id) ? done.post_id : null};
}

/**
 * A multi-photo Page post (TA-S2): POST /<page-id>/feed with `message` and
 * `attached_media[i]={"media_fbid":"<photo id>"}` for photos already uploaded
 * unpublished (fbPhoto published=false). Returns the feed post id.
 */
export async function fbFeed(cfg: MetaConfig, pageId: string, input: {message?: string; photo_ids: string[]}): Promise<string> {
  if (!input.photo_ids.length || input.photo_ids.length > 10) throw new TypeError('a multi-photo post takes 1 to 10 photos');
  const params: Params = {message: input.message};
  input.photo_ids.forEach((id, i) => { params[`attached_media[${i}]`] = JSON.stringify({media_fbid: requireId(id, 'photo')}); });
  const r = await graph<{id?: string}>(cfg, 'POST', `/${requireId(pageId, 'page')}/feed`, params);
  return requireId(String(r.id ?? ''), 'post');
}

/** A Page photo Story: an unpublished photo (POST /<page-id>/photos published=false), then POST /<page-id>/photo_stories photo_id. Returns the story's post id. */
export async function fbPhotoStory(cfg: MetaConfig, pageId: string, input: {url: string}): Promise<{photo_id: string; post_id: string}> {
  const photo = await fbPhoto(cfg, pageId, {url: input.url, published: false});
  const r = await graph<{post_id?: string; success?: boolean}>(cfg, 'POST', `/${requireId(pageId, 'page')}/photo_stories`, {photo_id: photo.id});
  return {photo_id: photo.id, post_id: requireId(String(r.post_id ?? ''), 'story')};
}

export interface PageInfo {id: string; name: string | null; instagram: {id: string; username: string | null} | null}
/** GET /<page-id>?fields=id,name,instagram_business_account{id,username}: the Page and its linked Instagram account. */
export async function pageInfo(cfg: MetaConfig, pageId: string): Promise<PageInfo> {
  const r = await graph<{id?: string; name?: string; instagram_business_account?: {id?: string; username?: string}}>(cfg, 'GET', `/${requireId(pageId, 'page')}`,
    {fields: 'id,name,instagram_business_account{id,username}'});
  const ig = r.instagram_business_account;
  return {id: requireId(String(r.id ?? ''), 'page'), name: typeof r.name === 'string' ? r.name : null,
    instagram: ig?.id && ID.test(ig.id) ? {id: ig.id, username: typeof ig.username === 'string' ? ig.username : null} : null};
}
