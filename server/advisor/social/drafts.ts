// Social post drafts (docs/plans/text-advisor/09-social.md § Drafts, SO-1, SC-3,
// SO-5, SP-3, AC-1; TA-S1). A consented skipper photo or video, or an angler
// photo the team approved, becomes one advisor_posts row with status 'draft'
// and one `post` review (reason social_draft). Nothing is published here
// (TA-S2 publishes approved posts).
//
//   ensureMediaDraft(env, mediaId)   the checks (media queued or approved; a boat photo needs the
//                                    boat not rejected and photo consent active; an angler photo
//                                    needs the team's approval), then draftFromMedia
//   draftFromMedia(env, media, boat, report, language)
//                                    kind (photo, reel for a video, story for a count board),
//                                    caption, collaborators, the centre user tag, targets; the
//                                    row and its review, idempotent on the media id
//   revokeBoatPosts(db, boatId)      consent revoked: the boat's draft and approved posts rejected
//   rejectPostsForMedia(db, mediaId) a photo the team rejected takes its unposted posts with it
//
// The caption: one model line (prompts/caption.ts, forced tool, <= 120 tokens,
// cached by media id in job_state advisor.caption.<media id>, recorded as the
// `advisor:caption` LLM feature, under the global LLM cap) or a fixed line
// when the model is unavailable, then the credit ("Aboard {boat} (@handle) out
// of {port}." or "Photo: {credit}"), the same-day report's numbers, the call to
// action with the advisor's number, and the hashtags (catalog/advisor/hashtags.json,
// at most 12). Every caption is checked against Instagram's limits: 2,200
// characters, 30 hashtags, 20 mentions. A Story carries no caption (Meta's
// Stories take none), no collaborators and no tags.
import hashtagCatalog from '../../../catalog/advisor/hashtags.json' with {type: 'json'};
import {advisorSettings} from '../settings.ts';
import {advisorLog} from '../log.ts';
import {sha256} from '../ids.ts';
import {t} from '../strings.ts';
import {portName, portRegion} from '../links.ts';
import {stripMarkdown} from '../reply.ts';
import {regionConfig} from '../answers/regions.ts';
import {localDate, PACIFIC} from '../answers/time.ts';
import {reportSpeciesKey, speciesName} from '../vision/species.ts';
import {consentActive} from '../intake/skippers.ts';
import {countsOf} from '../intake/reports.ts';
import {reviewId} from '../contacts.ts';
import {CAPTION_LINE_MAX, CAPTION_MAX_TOKENS, CAPTION_TOOL, captionPrompt} from '../prompts/caption.ts';
import type {CaptionFacts} from '../prompts/caption.ts';
import {recordLlm} from '../../analytics.ts';
import type {LlmUsage} from '../../analytics.ts';
import type {Env} from '../../env.ts';
import type {Language} from '../types.ts';

// ---- limits and shapes ---------------------------------------------------------------------

export const CAPTION_MAX = 2200;             // Instagram's caption limit (02 § advisor_posts)
export const HASHTAGS_MAX = 30;
export const MENTIONS_MAX = 20;
export const COLLABORATORS_MAX = 3;          // SP-7
export const USER_TAGS_MAX = 20;
export const DRAFT_HASHTAGS_MAX: number = hashtagCatalog.max;   // 09: <= 12 in a draft
export const CAPTION_TIMEOUT_MS = 15_000;
export const CAPTION_KEY_PREFIX = 'advisor.caption.';
export const API = 'https://api.anthropic.com/v1/messages';
/** The feed's language: SkipperCast's accounts post in English (09); the language argument exists for a later Spanish account. */
export const FEED_LANGUAGE: Language = 'en';
export const FISH_ID_MIN = 0.6;              // 06's medium band: a species named in the caption only from here
export const REVIEW_REASON = 'social_draft';

export type PostKind = 'photo' | 'carousel' | 'reel' | 'story' | 'daily' | 'roundup';
export type PostStatus = 'draft' | 'approved' | 'scheduled' | 'publishing' | 'posted' | 'partial' | 'failed' | 'rejected';
export type Target = 'instagram' | 'facebook' | 'instagram_story' | 'facebook_story';
export const POST_KINDS: readonly PostKind[] = ['photo', 'carousel', 'reel', 'story', 'daily', 'roundup'];
export const POST_STATUSES: readonly PostStatus[] = ['draft', 'approved', 'scheduled', 'publishing', 'posted', 'partial', 'failed', 'rejected'];
/** The surfaces a kind may go to (09 § Drafts: feed kinds to IG + FB, stories to both Story surfaces). */
export const TARGETS_FOR: Readonly<Record<PostKind, readonly Target[]>> = {
  photo: ['instagram', 'facebook'], carousel: ['instagram', 'facebook'], reel: ['instagram', 'facebook'],
  daily: ['instagram', 'facebook'], roundup: ['instagram', 'facebook'], story: ['instagram_story', 'facebook_story'],
};
export const HANDLE = /^[a-z0-9._]{1,30}$/;

export interface UserTag {username: string; x: number; y: number}

/** The id of the one post a media item makes: sha256('post:media:' + id)[:32], so a retry or the backfill finds it. */
export const postIdForMedia = async (mediaId: string): Promise<string> => (await sha256(`post:media:${mediaId}`)).slice(0, 32);
export const captionKey = (mediaId: string): string => CAPTION_KEY_PREFIX + mediaId;

const HASHTAG = /(?:^|[^\p{L}\p{N}_&#])#[\p{L}\p{N}_]+/gu;
const MENTION = /(?:^|[^\p{L}\p{N}_.@])@[A-Za-z0-9._]{1,30}/gu;

/** Characters (code points), hashtags and @mentions of a caption, as Instagram counts them. */
export function captionStats(caption: string): {length: number; hashtags: number; mentions: number} {
  return {length: Array.from(caption).length, hashtags: [...caption.matchAll(HASHTAG)].length, mentions: [...caption.matchAll(MENTION)].length};
}
/** Why a caption cannot go to Instagram, or null when it can. */
export function captionProblem(caption: string): string | null {
  const s = captionStats(caption);
  if (s.length > CAPTION_MAX) return `the caption is ${s.length} characters (at most ${CAPTION_MAX})`;
  if (s.hashtags > HASHTAGS_MAX) return `the caption has ${s.hashtags} hashtags (at most ${HASHTAGS_MAX})`;
  if (s.mentions > MENTIONS_MAX) return `the caption has ${s.mentions} mentions (at most ${MENTIONS_MAX})`;
  return null;
}
/** Control characters out (newlines kept), trailing spaces trimmed per line. */
export const cleanCaption = (text: string): string => String(text ?? '').replace(/\r\n?/g, '\n').replace(/[\u0000-\u0009\u000b-\u001f\u007f]/g, '').replace(/[ \t]+$/gm, '').trim();

// ---- caption parts -------------------------------------------------------------------------

const REGION_TAGS = hashtagCatalog.regions as Record<string, string[]>;
const SPECIES_TAGS = hashtagCatalog.species as Record<string, string[]>;
/** The draft's hashtags (without #): brand, angler, region, then each species and its report parent; deduplicated, at most `max`. */
export function hashtagsFor(region: string | null, speciesKeys: readonly string[], options: {angler?: boolean; max?: number} = {}): string[] {
  const out: string[] = [];
  const add = (tags: readonly string[] | undefined): void => { for (const tag of tags ?? []) if (/^[a-z0-9_]{1,60}$/.test(tag) && !out.includes(tag)) out.push(tag); };
  add(hashtagCatalog.brand);
  if (options.angler) add(hashtagCatalog.angler);
  if (region) add(REGION_TAGS[region]);
  for (const key of speciesKeys) { add(SPECIES_TAGS[key]); add(SPECIES_TAGS[reportSpeciesKey(key)]); }
  return out.slice(0, Math.min(options.max ?? DRAFT_HASHTAGS_MAX, HASHTAGS_MAX));
}

/** An E.164 US number as (805) 555-0100, the way the media job's footer prints it; else the text page. */
export function displayNumber(e164: string | null): string {
  const m = e164 ? /^\+1(\d{3})(\d{3})(\d{4})$/.exec(e164) : null;
  return m ? `(${m[1]}) ${m[2]}-${m[3]}` : 'skippercast.com/text';
}

export interface ReportForCaption {anglers: number | null; counts_json: string}
/** "Trip total: 45 vermilion, 12 lings for 22 anglers." from a published same-day report's kept lines (at most 4), or null. */
export function reportLine(report: ReportForCaption | null, language: Language): string | null {
  if (!report) return null;
  const kept = countsOf(report.counts_json).filter(c => c.kept && !c.uncertain).slice(0, 4).map(c => `${c.kept} ${c.label}`);
  if (!kept.length) return null;
  const counts = kept.join(', ');
  return report.anglers ? t(language, 'caption_report', {counts, anglers: report.anglers}) : t(language, 'caption_report_no_anglers', {counts});
}

export interface MediaForDraft {
  id: string; contact_id: string; boat_id: string | null; kind: string; mime: string; classification_json: string | null;
  has_person: number | null; publish_state: string; credit: string | null; created_at: string;
}
export interface BoatForDraft {
  id: string; name: string; slug: string; port: string; region: string; instagram: string | null; status: string;
  consent_photos_at: string | null; consent_revoked_at: string | null;
}

/** 09 § Drafts: a video is a Reel, a count-board photo a Story, any other still a photo. */
export function postKindFor(media: Pick<MediaForDraft, 'kind' | 'classification_json'>): 'photo' | 'reel' | 'story' {
  if (media.kind === 'video') return 'reel';
  try { if (JSON.parse(media.classification_json ?? 'null')?.classify?.kind === 'count_board') return 'story'; } catch { /* a photo */ }
  return 'photo';
}

/** The species the photo shows: its fish ID's top candidate at >= 0.6 (06's medium band), catalog keys only. */
export function photoSpecies(media: Pick<MediaForDraft, 'classification_json'>): string[] {
  try {
    const top = JSON.parse(media.classification_json ?? 'null')?.fish_id?.candidates?.[0];
    return top && typeof top.species_key === 'string' && Number(top.confidence) >= FISH_ID_MIN && speciesName(top.species_key) ? [top.species_key] : [];
  } catch { return []; }
}

// ---- the model line ------------------------------------------------------------------------------

export interface DraftDeps {
  now?: number;
  fetcher?: (url: string, init: RequestInit) => Promise<Response>;   // the Messages API (tests: a fake)
  createdBy?: string;                                               // 'engine' (default) or the admin's users.id
  hint?: string | null;                                             // propose_post: the skipper's words about the photo
  language?: Language;
}

/** A model line that may go in a caption: one sentence, no tag, mention, link, emoji-only or number the facts lack. */
export function acceptableLine(text: unknown, facts: CaptionFacts): string | null {
  if (typeof text !== 'string') return null;
  const s = stripMarkdown(text).replace(/\s+/g, ' ').replace(/^["'“”]+|["'“”]+$/g, '').trim();
  if (!s || Array.from(s).length > CAPTION_LINE_MAX) return null;
  if (/[#@]|https?:|www\.|\.com\b|%|\bpercent|\bodds\b|\bchance|\bprobab|por ciento|probabilidad/i.test(s)) return null;
  const known = JSON.stringify(facts);
  if ((s.match(/\d+/g) ?? []).some(n => !known.includes(n))) return null;   // a number the facts do not have is invented
  return s;
}

const fallbackLine = (facts: CaptionFacts): string => facts.species[0] ? t(facts.language, 'caption_line_species', {species: facts.species[0]}) : t(facts.language, 'caption_line_generic');

/**
 * The caption's first line: cached for this media id and language, else one
 * forced-tool call (when ANTHROPIC_API_KEY is set and the global LLM cap
 * allows), else the fixed line. Only a model line is cached.
 */
export async function captionLine(env: Env, mediaId: string, facts: CaptionFacts, deps: DraftDeps = {}): Promise<{line: string; source: 'cache' | 'model' | 'fixed'}> {
  const db = env.DB!, now = deps.now ?? Date.now(), settings = advisorSettings(env);
  const cached = await db.prepare('SELECT value FROM job_state WHERE key=?').bind(captionKey(mediaId)).first<{value: string}>();
  try {
    const v = JSON.parse(cached?.value ?? 'null') as {line?: unknown; language?: unknown} | null;
    if (v && v.language === facts.language && typeof v.line === 'string' && acceptableLine(v.line, facts)) return {line: v.line, source: 'cache'};
  } catch { /* regenerate */ }
  if (!env.ANTHROPIC_API_KEY) return {line: fallbackLine(facts), source: 'fixed'};
  const day = Math.floor(now / 86400000);
  const used = await db.prepare('INSERT INTO request_limits(id,count,expires_at) VALUES(?,1,?) ON CONFLICT(id) DO UPDATE SET count=count+1 RETURNING count')
    .bind(`global:advisor-llm:${day}`, (day + 2) * 86400).first<{count: number}>();
  if ((used?.count ?? Infinity) > settings.globalDailyLlm) { advisorLog('warn', 'advisor_global_cap', {limit: settings.globalDailyLlm, feature: 'caption'}); return {line: fallbackLine(facts), source: 'fixed'}; }
  const fetcher = deps.fetcher ?? ((url: string, init: RequestInit) => fetch(url, init));
  const usage: LlmUsage = {model: settings.model, turns: 0, input_tokens: 0, output_tokens: 0, web_search_requests: 0};
  let outcome = 'error';
  try {
    const body = JSON.stringify({model: settings.model, max_tokens: CAPTION_MAX_TOKENS, temperature: 0.4, tools: [CAPTION_TOOL], tool_choice: {type: 'tool', name: CAPTION_TOOL.name},
      messages: [{role: 'user', content: captionPrompt(facts)}]});
    const response = await fetcher(API, {method: 'POST', signal: AbortSignal.timeout(CAPTION_TIMEOUT_MS),
      headers: {'x-api-key': env.ANTHROPIC_API_KEY, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'}, body});
    usage.turns = 1;
    if (!response.ok) throw Error(`caption HTTP ${response.status}`);
    const data = await response.json() as {content?: {type: string; name?: string; input?: {line?: unknown}}[]; usage?: Record<string, number>};
    usage.input_tokens = (data.usage?.input_tokens ?? 0) + (data.usage?.cache_read_input_tokens ?? 0) + (data.usage?.cache_creation_input_tokens ?? 0);
    usage.output_tokens = data.usage?.output_tokens ?? 0;
    const line = acceptableLine((data.content ?? []).find(b => b.type === 'tool_use' && b.name === CAPTION_TOOL.name)?.input?.line, facts);
    if (!line) { outcome = 'invalid'; return {line: fallbackLine(facts), source: 'fixed'}; }
    outcome = 'ok';
    await db.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at')
      .bind(captionKey(mediaId), JSON.stringify({line, language: facts.language}), new Date(now).toISOString()).run();
    return {line, source: 'model'};
  } catch (error) {
    advisorLog('warn', 'advisor_caption_failed', {reason: String((error as Error)?.message).slice(0, 120)});
    return {line: fallbackLine(facts), source: 'fixed'};
  } finally {
    if (usage.turns) recordLlm(env, 'advisor:caption', outcome, usage);
  }
}

/** The caption from its parts: the line, the credit, the report, the CTA, then the hashtags after a blank line. Trimmed to the limits. */
export function composeCaption(parts: {line: string; credit: string; report: string | null; cta: string; hashtags: readonly string[]}): string {
  const body = [parts.line, parts.credit, parts.report, parts.cta].filter((p): p is string => Boolean(p)).join('\n');
  const tags = parts.hashtags.slice(0, HASHTAGS_MAX).map(h => `#${h}`).join(' ');
  const caption = tags ? `${body}\n\n${tags}` : body;
  return Array.from(caption).length > CAPTION_MAX ? Array.from(caption).slice(0, CAPTION_MAX).join('').trimEnd() : caption;
}

// ---- drafts --------------------------------------------------------------------------------------

export type DraftOutcome = {status: 'created' | 'exists'; postId: string} | {status: 'skipped'; reason: string};

/**
 * One draft for one media item (09 § Drafts). `boat` null is an angler's photo
 * (credit "Photo: {credit}", no collaborators, no tag). `report` is the boat's
 * published report of the photo's day, for the numbers line. Writes the post
 * and its review (both idempotent on the media id); returns whether it was new.
 */
export async function draftFromMedia(env: Env, media: MediaForDraft, boat: BoatForDraft | null, report: ReportForCaption | null, language: Language = FEED_LANGUAGE,
  deps: DraftDeps & {region?: string} = {}): Promise<DraftOutcome> {
  const db = env.DB!, now = deps.now ?? Date.now(), at = new Date(now).toISOString(), settings = advisorSettings(env);
  const kind = postKindFor(media);
  const region = boat?.region ?? deps.region ?? settings.regionDefault;
  const handle = boat?.instagram && HANDLE.test(boat.instagram) ? boat.instagram : null;
  const reportSpecies = report ? countsOf(report.counts_json).filter(c => c.kept && !c.uncertain && c.species_key !== 'other').map(c => c.species_key) : [];
  const species = [...new Set([...photoSpecies(media), ...reportSpecies])];
  let caption = '';
  if (kind !== 'story') {
    const port = boat ? portName(boat.port) ?? boat.port : null;
    const numbers = reportLine(report, language);
    const facts: CaptionFacts = {kind, language, species: species.map(k => speciesName(k)!).filter(Boolean).slice(0, 4), boat: boat?.name ?? null, port,
      report: numbers, note: deps.hint ? String(deps.hint).replace(/\s+/g, ' ').trim().slice(0, 200) : null};
    const {line} = await captionLine(env, media.id, facts, deps);
    const anonymous = !media.credit || /^(?:anonymous|an[oó]nimo)$/i.test(media.credit.trim());
    const credit = boat
      ? (handle ? t(language, 'caption_credit_boat_handle', {boat: boat.name, handle, port: port!}) : t(language, 'caption_credit_boat', {boat: boat.name, port: port!}))
      : anonymous ? t(language, 'caption_credit_anonymous') : t(language, 'caption_credit_angler', {credit: media.credit!.trim()});
    caption = composeCaption({line, credit, report: numbers, cta: t(language, 'caption_cta', {number: displayNumber(settings.number)}),
      hashtags: hashtagsFor(region, species, {angler: !boat})});
  }
  const collaborators = handle && kind !== 'story' ? [handle] : null;
  const userTags: UserTag[] | null = handle && kind === 'photo' ? [{username: handle, x: 0.5, y: 0.5}] : null;
  const id = await postIdForMedia(media.id);
  const review = await reviewId('post', id, REVIEW_REASON);
  const [inserted] = await db.batch([
    db.prepare(`INSERT INTO advisor_posts(id,kind,region,boat_id,media_json,caption,collaborators_json,user_tags_json,targets_json,status,created_by,created_at,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,'draft',?,?,?) ON CONFLICT(id) DO NOTHING`)
      .bind(id, kind, region, boat?.id ?? null, JSON.stringify([media.id]), caption, collaborators ? JSON.stringify(collaborators) : null,
        userTags ? JSON.stringify(userTags) : null, JSON.stringify(TARGETS_FOR[kind]), deps.createdBy ?? 'engine', at, at),
    // The review only while the post is a draft: a retry after the team decided opens nothing.
    db.prepare(`INSERT INTO advisor_reviews(id,kind,ref_id,reason,status,opened_at) SELECT ?,'post',?,?,'open',? WHERE EXISTS (SELECT 1 FROM advisor_posts WHERE id=? AND status='draft')
      ON CONFLICT(id) DO NOTHING`).bind(review, id, REVIEW_REASON, at, id),
  ]);
  const created = (inserted?.meta.changes ?? 0) > 0;
  if (created) advisorLog('info', 'advisor_post_drafted', {kind, angler: !boat, hashtags: captionStats(caption).hashtags});
  return {status: created ? 'created' : 'exists', postId: id};
}

/** The boat's published report for the local day the media was taken in (for the numbers line), or null. */
async function sameDayReport(db: D1Database, boat: BoatForDraft, createdAt: string): Promise<ReportForCaption | null> {
  const ms = Date.parse(createdAt);
  if (!Number.isFinite(ms)) return null;
  const day = localDate(ms, regionConfig(boat.region)?.timezone ?? PACIFIC);
  return db.prepare("SELECT anglers,counts_json FROM advisor_reports WHERE boat_id=? AND report_date=? AND status='published' ORDER BY updated_at DESC LIMIT 1")
    .bind(boat.id, day).first<ReportForCaption>();
}

/**
 * The checks, then draftFromMedia. A boat's photo or video needs it queued or
 * approved, the boat not rejected and photo consent active (05 § Consent: no
 * draft without it). An angler's photo needs the team's approval of the share
 * (06 § Angler photos: "approved angler photos become a post.draft").
 */
export async function ensureMediaDraft(env: Env, mediaId: string, deps: DraftDeps = {}): Promise<DraftOutcome> {
  const db = env.DB!;
  if (!/^[\w-]{1,64}$/.test(String(mediaId))) return {status: 'skipped', reason: 'invalid'};
  const media = await db.prepare('SELECT id,contact_id,boat_id,kind,mime,classification_json,has_person,publish_state,credit,created_at FROM advisor_media WHERE id=?')
    .bind(mediaId).first<MediaForDraft>();
  if (!media || (media.kind !== 'image' && media.kind !== 'video')) return {status: 'skipped', reason: 'not-media'};
  if (media.publish_state !== 'queued' && media.publish_state !== 'approved') return {status: 'skipped', reason: 'not-queued'};
  const existing = await db.prepare('SELECT id FROM advisor_posts WHERE id=?').bind(await postIdForMedia(media.id)).first<{id: string}>();
  if (existing) return {status: 'exists', postId: existing.id};
  const language = deps.language ?? FEED_LANGUAGE;
  if (media.boat_id) {
    const boat = await db.prepare('SELECT id,name,slug,port,region,instagram,status,consent_photos_at,consent_revoked_at FROM advisor_boats WHERE id=?').bind(media.boat_id).first<BoatForDraft>();
    if (!boat || boat.status === 'rejected') return {status: 'skipped', reason: 'boat'};
    if (!consentActive(boat)) return {status: 'skipped', reason: 'no-consent'};
    return draftFromMedia(env, media, boat, await sameDayReport(db, boat, media.created_at), language, deps);
  }
  if (media.publish_state !== 'approved') return {status: 'skipped', reason: 'not-approved'};
  const contact = await db.prepare('SELECT home_port FROM advisor_contacts WHERE id=?').bind(media.contact_id).first<{home_port: string | null}>();
  const region = portRegion(contact?.home_port) ?? undefined;
  return draftFromMedia(env, media, null, null, language, {...deps, ...(region ? {region} : {})});
}

/** Close the open `post` reviews of these posts (the post was rejected outside the queue). */
export async function closeReviews(db: D1Database, postIds: string[], at: string, note: string): Promise<void> {
  if (!postIds.length) return;
  await db.prepare(`UPDATE advisor_reviews SET status='rejected',decided_at=?,note=COALESCE(note,?) WHERE kind='post' AND status='open' AND ref_id IN (${postIds.map(() => '?').join(',')})`)
    .bind(at, note, ...postIds).run();
}

/**
 * 05 § Consent: "revoke" sets every draft or approved post of the boat to
 * rejected (posted ones stay; the runbook covers deleting them on Meta) and
 * closes their reviews. Returns how many posts it rejected.
 */
export async function revokeBoatPosts(db: D1Database, boatId: string, now: number): Promise<number> {
  const at = new Date(now).toISOString();
  const ids = (await db.prepare("SELECT id FROM advisor_posts WHERE boat_id=? AND status IN ('draft','approved')").bind(boatId).all<{id: string}>()).results.map(r => r.id);
  if (!ids.length) return 0;
  await db.prepare(`UPDATE advisor_posts SET status='rejected',error='consent_revoked',updated_at=? WHERE boat_id=? AND status IN ('draft','approved')`).bind(at, boatId).run();
  await closeReviews(db, ids, at, 'consent revoked');
  advisorLog('info', 'advisor_posts_revoked', {count: ids.length});
  return ids.length;
}

/** A photo the team rejected: its draft or approved posts are rejected too (a post never goes out with a rejected photo). */
export async function rejectPostsForMedia(db: D1Database, mediaId: string, now: number): Promise<number> {
  const at = new Date(now).toISOString();
  const ids = (await db.prepare(`SELECT p.id FROM advisor_posts p WHERE p.status IN ('draft','approved') AND EXISTS (SELECT 1 FROM json_each(p.media_json) j WHERE j.value=?)`)
    .bind(mediaId).all<{id: string}>()).results.map(r => r.id);
  if (!ids.length) return 0;
  await db.prepare(`UPDATE advisor_posts SET status='rejected',error='media_rejected',updated_at=? WHERE id IN (${ids.map(() => '?').join(',')})`).bind(at, ...ids).run();
  await closeReviews(db, ids, at, 'photo rejected');
  return ids.length;
}
