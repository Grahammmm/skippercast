// The morning Stories (docs/plans/text-advisor/09-social.md § Stories, SP-4;
// TA-S5). Slot `morning-stories`, 07:00 local, while social publishing is on
// and Meta is configured, for every active region:
//
//   count boards   each verified boat with photo consent and a count-board photo from the previous
//                  local day (its latest): the photo's Story post (TA-S1's draft, sha256('post:media:'
//                  + id)[:32], made now if missing) is approved by the engine, with no admin decision:
//                  Stories need no admin approval once the source photo is approved or has no hold
//                  (09). admin/posts.ts approvalHold still applies, so a has_person photo whose review
//                  is not approved, an open photo review, a rejected photo, revoked consent or an
//                  unverified boat keeps it back. The photo becomes `approved` (public for Meta's
//                  fetch of its story.jpg, which carries the "Text SkipperCast" footer) and the post's
//                  open review is closed as approved with the note 'auto: story'.
//   the card       the day's conditions card: a Story with no photo (`media_json` []), its graphic
//                  requestGraphic(kind 'story') with the title and today's conditions line and the
//                  landing reports' word, id sha256('story:conditions:<region>:<date>')[:32], approved
//                  at once (generated from public data, nothing to review). No forecast: no card.
//
// Both get scheduled_for = today's Stories slot (catalog/advisor/calendar.json, 07:00) so they
// fill it, and go out through social/publish.ts on the next tick (the card once rendered).
// Reruns change nothing that already exists.
import {advisorSettings} from '../settings.ts';
import {advisorLog} from '../log.ts';
import {t} from '../strings.ts';
import {portName, portRegion} from '../links.ts';
import {regionConfig} from '../answers/regions.ts';
import {addDays, localDate, PACIFIC} from '../answers/time.ts';
import {activePorts, conditionsText, dailyInputs} from '../answers/reports.ts';
import {sha256} from '../ids.ts';
import {consentActive} from '../intake/skippers.ts';
import {requestGraphic, requestMediaJob} from '../media.ts';
import {approvalHold, mediaIdsOf} from '../admin/posts.ts';
import type {PostRow} from '../admin/posts.ts';
import {FEED_LANGUAGE, TARGETS_FOR, ensureMediaDraft, postIdForMedia} from './drafts.ts';
import {GRAPHIC_FILE, graphicKey} from './graphics.ts';
import {CALENDAR, zonedInstant} from './calendar.ts';
import type {Calendar} from './calendar.ts';
import {activeRegions, confidenceWord} from './daily-post.ts';
import type {SocialDraftDeps} from './daily-post.ts';
import {metaConfigured} from './meta.ts';
import type {Env} from '../../env.ts';

export const AUTO_NOTE = 'auto: story';
export type StoryOutcome = {region: string; kind: 'count_board' | 'conditions'; status: 'approved' | 'exists' | 'held' | 'skipped'; postId?: string; reason?: string};

/** The id of a region's conditions card for a local date. */
export const conditionsStoryId = async (region: string, date: string): Promise<string> => (await sha256(`story:conditions:${region}:${date}`)).slice(0, 32);

/** Today's Stories slot time for a region (the calendar's `story` slot), or now when the region has none. */
export function storySlotAt(region: string, now: number, cal: Calendar = CALENDAR): string {
  const tz = regionConfig(region)?.timezone ?? PACIFIC;
  const slot = cal.slots.find(s => s.kind === 'story' && s.region === region);
  return slot ? zonedInstant(localDate(now, tz), slot.time_local, tz) : new Date(now).toISOString();
}

interface CountBoardRow {id: string; boat_id: string; boat_status: string; consent_photos_at: string | null; consent_revoked_at: string | null; publish_state: string; created_at: string}

/** Each verified, consenting boat's latest count-board photo taken during `date` (local) in the region. */
async function countBoards(db: D1Database, region: string, date: string, tz: string): Promise<CountBoardRow[]> {
  const from = zonedInstant(date, '00:00', tz), to = zonedInstant(addDays(date, 1), '00:00', tz);
  const rows = (await db.prepare(`SELECT m.id,m.boat_id,m.publish_state,m.created_at,b.status AS boat_status,b.consent_photos_at,b.consent_revoked_at
      FROM advisor_media m JOIN advisor_boats b ON b.id=m.boat_id
      WHERE b.region=? AND m.kind='image' AND m.r2_key<>'' AND m.publish_state IN ('queued','approved','posted') AND m.created_at>=? AND m.created_at<?
        AND json_valid(m.classification_json) AND json_extract(m.classification_json,'$.classify.kind')='count_board'
      ORDER BY m.created_at DESC, m.id`).bind(region, from, to).all<CountBoardRow>()).results;
  const seen = new Set<string>();
  return rows.filter(r => r.boat_status === 'verified' && consentActive(r) && !seen.has(r.boat_id) && seen.add(r.boat_id));
}

/** Approve a story post by the engine: status approved (no approved_by), its time, its photos approved, its open review closed. */
async function autoApprove(env: Env, post: PostRow, at: string, slot: string, now: number, deps: SocialDraftDeps): Promise<void> {
  const db = env.DB!, ids = mediaIdsOf(post);
  await db.batch([
    db.prepare("UPDATE advisor_posts SET status='approved',approved_by=NULL,approved_at=?,scheduled_for=COALESCE(scheduled_for,?),updated_at=? WHERE id=? AND status='draft'")
      .bind(at, slot, at, post.id),
    ...(ids.length ? [db.prepare(`UPDATE advisor_media SET publish_state='approved' WHERE publish_state='queued' AND id IN (${ids.map(() => '?').join(',')})`).bind(...ids)] : []),
    db.prepare("UPDATE advisor_reviews SET status='approved',decided_at=?,decided_by=NULL,note=COALESCE(note,?) WHERE kind='post' AND ref_id=? AND status='open'").bind(at, AUTO_NOTE, post.id),
  ]);
  // story.jpg (the photo above the footer band) comes from the media job.
  await requestMediaJob(env, now, deps.dispatch ? {dispatch: deps.dispatch} : {});
}

/** The count-board Stories of one region (the header). */
async function countBoardStories(env: Env, region: string, now: number, deps: SocialDraftDeps): Promise<StoryOutcome[]> {
  const db = env.DB!, tz = regionConfig(region)?.timezone ?? PACIFIC, at = new Date(now).toISOString(), slot = storySlotAt(region, now);
  const out: StoryOutcome[] = [];
  for (const photo of await countBoards(db, region, addDays(localDate(now, tz), -1), tz)) {
    const id = await postIdForMedia(photo.id);
    let post = await db.prepare('SELECT * FROM advisor_posts WHERE id=?').bind(id).first<PostRow>();
    if (!post) {
      const made = await ensureMediaDraft(env, photo.id, {now});
      if (made.status === 'skipped') { out.push({region, kind: 'count_board', status: 'skipped', reason: made.reason}); continue; }
      post = await db.prepare('SELECT * FROM advisor_posts WHERE id=?').bind(id).first<PostRow>();
    }
    if (!post || post.kind !== 'story') { out.push({region, kind: 'count_board', status: 'skipped', reason: 'not a story post'}); continue; }
    if (post.status !== 'draft') { out.push({region, kind: 'count_board', status: 'exists', postId: id}); continue; }
    const hold = await approvalHold(db, post);
    if (hold) { out.push({region, kind: 'count_board', status: 'held', postId: id, reason: hold}); continue; }
    await autoApprove(env, post, at, slot, now, deps);
    out.push({region, kind: 'count_board', status: 'approved', postId: id});
  }
  return out;
}

/** The region's conditions card Story (the header): null outcome reason when there is no forecast. */
async function conditionsStory(env: Env, region: string, now: number, deps: SocialDraftDeps): Promise<StoryOutcome> {
  const db = env.DB!, config = regionConfig(region), tz = config?.timezone ?? PACIFIC, today = localDate(now, tz), at = new Date(now).toISOString();
  const id = await conditionsStoryId(region, today);
  if (await db.prepare('SELECT 1 AS x FROM advisor_posts WHERE id=?').bind(id).first()) return {region, kind: 'conditions', status: 'exists', postId: id};
  const port = activePorts().find(p => portRegion(p) === region);
  if (!port) return {region, kind: 'conditions', status: 'skipped', reason: 'no port'};
  const inputs = await dailyInputs(env, port, today, deps, now);
  if (!inputs.conditions.day && !inputs.conditions.advisories.length) return {region, kind: 'conditions', status: 'skipped', reason: 'no forecast'};
  const word = confidenceWord(inputs);
  const place = config?.name ?? portName(port) ?? region;
  const data = {title: t(FEED_LANGUAGE, 'story_conditions_title', {place}),
    lines: [conditionsText(inputs.conditions, FEED_LANGUAGE), ...(word ? [t(FEED_LANGUAGE, 'daily_post_confidence_short', {label: word})] : [])]};
  await db.prepare(`INSERT INTO advisor_posts(id,kind,region,boat_id,media_json,caption,targets_json,status,scheduled_for,created_by,approved_at,created_at,updated_at)
    VALUES(?,'story',?,NULL,'[]','',?,'approved',?,'engine',?,?,?) ON CONFLICT(id) DO NOTHING`)
    .bind(id, region, JSON.stringify(TARGETS_FOR.story), storySlotAt(region, now), at, at, at).run();
  await requestGraphic(env, id, {kind: 'story', data, out_key: graphicKey(id, GRAPHIC_FILE.story)}, now, deps.dispatch ? {dispatch: deps.dispatch} : {});
  return {region, kind: 'conditions', status: 'approved', postId: id};
}

/**
 * The `morning-stories` slot (07:00 local). Nothing while ADVISOR_SOCIAL_ENABLED
 * is off or Meta is not configured (Stories are approved here, so they are made
 * only when they can go out the same morning). A failing region is logged and
 * the slot released for the next tick.
 */
export async function morningStories(env: Env, now: number, deps: SocialDraftDeps = {}): Promise<StoryOutcome[]> {
  if (!env.DB || !advisorSettings(env).socialEnabled || !metaConfigured(env)) return [];
  const out: StoryOutcome[] = [];
  let failed = 0;
  for (const region of activeRegions()) {
    try {
      out.push(...await countBoardStories(env, region, now, deps));
      out.push(await conditionsStory(env, region, now, deps));
    } catch (error) {
      failed++;
      advisorLog('warn', 'advisor_morning_stories_failed', {region, reason: String((error as Error)?.message).slice(0, 120)});
    }
  }
  const approved = out.filter(o => o.status === 'approved').length, held = out.filter(o => o.status === 'held').length;
  if (approved || held) advisorLog('info', 'advisor_morning_stories', {approved, held});
  if (failed) throw Error(`morning stories failed for ${failed} region(s)`);
  return out;
}
