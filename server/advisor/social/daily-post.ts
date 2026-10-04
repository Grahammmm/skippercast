// The daily "what's biting" post (SO-2) and the weekly roundup (SP-5)
// (docs/plans/text-advisor/09-social.md § Daily post and roundup; TA-S4).
//
//   draftDailyPosts(env, now)   the `daily-post` slot, 06:30 local: for each active region whose
//                               previous local day has at least one published report from a verified
//                               boat, the card's data (the place, the boats and their counts, the top
//                               counts, today's conditions line, the landing reports' confidence word:
//                               never a probability), the media job's `daily` graphic, a template
//                               caption (no model call) with the call to action and hashtags, and the
//                               draft `daily:<region>:<date>` (sha256, 02) with its `post` review.
//   draftRoundups(env, now)     the `weekly-roundup` slot, Sundays 17:00: the week's approved catch
//                               photos of verified, consenting boats (and approved angler shares) of the
//                               region, spread by port and species, at most 9 (with the cover card that
//                               is Meta's 10-item carousel limit); boats as collaborators (3 at most,
//                               the rest mentioned), the `roundup` graphic (cover and one slide per
//                               photo) and the draft `roundup:<region>:<date>`.
//
// The date in a daily id is the local date the post goes out (its reports are from the day
// before), so a rerun the same day updates the draft rather than making a second. A draft is
// updated only while it is a draft: an approved post is never changed. Today's draft supersedes
// an older one of the region that is still a draft or approved without a time (rejected,
// error 'superseded'), so a stale day never goes out. One approval posts it to Instagram and the
// Page (social/publish.ts, at the calendar's slot).
import {advisorSettings} from '../settings.ts';
import {advisorLog} from '../log.ts';
import {t} from '../strings.ts';
import {portName, portRegion} from '../links.ts';
import {regionConfig} from '../answers/regions.ts';
import {addDays, localDate, PACIFIC} from '../answers/time.ts';
import {activePorts, conditionsText, dailyInputs} from '../answers/reports.ts';
import type {DailyDeps, DailyInputs} from '../answers/reports.ts';
import {countsOf} from '../intake/reports.ts';
import {consentActive} from '../intake/skippers.ts';
import {speciesName} from '../vision/species.ts';
import {reviewId} from '../contacts.ts';
import {graphicState, requestGraphic} from '../media.ts';
import type {GraphicKind} from '../media.ts';
import {CAPTION_MAX, COLLABORATORS_MAX, FEED_LANGUAGE, HANDLE, REVIEW_REASON, TARGETS_FOR, closeReviews, displayNumber, hashtagsFor, photoSpecies} from './drafts.ts';
import type {PostKind} from './drafts.ts';
import {GRAPHIC_FILE, graphicKey} from './graphics.ts';
import {dailyPostId, roundupPostId} from './calendar.ts';
import type {Env} from '../../env.ts';
import type {Language} from '../types.ts';

export const DAILY_BOATS_MAX = 6;        // boats named in the caption
export const CARD_BOATS_MAX = 4;         // boats on the card (it has room for about ten lines)
export const TOP_COUNTS_MAX = 5;
export const ROUNDUP_PHOTOS_MAX = 9;     // + the cover card = Meta's 10 carousel items
export const ROUNDUP_DAYS = 7;
const LADDER = ['Insufficient', 'Low', 'Moderate'];

export interface SocialDraftDeps extends DailyDeps {dispatch?: (env: Env, file: string) => Promise<number>}
export type GeneratedOutcome = {region: string; status: 'created' | 'updated' | 'kept' | 'skipped'; postId?: string; reason?: string};

/** Active regions (status active in regions/<id>/region.json), from the ports the daily answers keep. */
export const activeRegions = (): string[] => [...new Set(activePorts().map(p => portRegion(p)).filter((r): r is string => Boolean(r)))];

/** "Sat Oct 3" / "sáb 3 oct" for a YYYY-MM-DD date. */
export function shortDate(date: string, language: Language): string {
  const d = new Date(`${date}T12:00:00Z`);
  const wd = new Intl.DateTimeFormat(language === 'es' ? 'es' : 'en-US', {weekday: 'short', timeZone: 'UTC'}).format(d).replace(/\.$/, '');
  const mo = new Intl.DateTimeFormat(language === 'es' ? 'es' : 'en-US', {month: 'short', timeZone: 'UTC'}).format(d).replace(/\.$/, '');
  return language === 'es' ? `${wd} ${d.getUTCDate()} ${mo}` : `${wd} ${mo} ${d.getUTCDate()}`;
}

const cut = (text: string, max = CAPTION_MAX): string => Array.from(text).length > max ? Array.from(text).slice(0, max).join('').trimEnd() : text;
const tags = (list: readonly string[]): string => list.map(h => `#${h}`).join(' ');

// ---- the shared draft write ----------------------------------------------------------------------

interface GeneratedDraft {
  id: string; kind: PostKind; region: string; media: string[]; caption: string; collaborators: string[];
  graphic: {kind: GraphicKind; data: Record<string, unknown>; file: string};
}

/**
 * Write (or update, while it is a draft) a generated post and its `post`
 * review, then ask the media job for its graphic when the graphic's inputs
 * changed. Older drafts of the same kind and region are superseded.
 */
export async function upsertGeneratedDraft(env: Env, draft: GeneratedDraft, now: number, deps: SocialDraftDeps = {}): Promise<GeneratedOutcome> {
  const db = env.DB!, at = new Date(now).toISOString();
  const before = await db.prepare('SELECT status FROM advisor_posts WHERE id=?').bind(draft.id).first<{status: string}>();
  if (before && before.status !== 'draft') return {region: draft.region, status: 'kept', postId: draft.id, reason: `the post is ${before.status}`};
  const review = await reviewId('post', draft.id, REVIEW_REASON);
  await db.batch([
    db.prepare(`INSERT INTO advisor_posts(id,kind,region,boat_id,media_json,caption,collaborators_json,user_tags_json,targets_json,status,created_by,created_at,updated_at)
      VALUES(?,?,?,NULL,?,?,?,NULL,?,'draft','engine',?,?)
      ON CONFLICT(id) DO UPDATE SET media_json=excluded.media_json,caption=excluded.caption,collaborators_json=excluded.collaborators_json,updated_at=excluded.updated_at
      WHERE advisor_posts.status='draft'`)
      .bind(draft.id, draft.kind, draft.region, JSON.stringify(draft.media), draft.caption, draft.collaborators.length ? JSON.stringify(draft.collaborators) : null,
        JSON.stringify(TARGETS_FOR[draft.kind]), at, at),
    db.prepare(`INSERT INTO advisor_reviews(id,kind,ref_id,reason,status,opened_at) SELECT ?,'post',?,?,'open',? WHERE EXISTS (SELECT 1 FROM advisor_posts WHERE id=? AND status='draft')
      ON CONFLICT(id) DO NOTHING`).bind(review, draft.id, REVIEW_REASON, at, draft.id),
  ]);
  // Supersede: an older post of this kind and region that is still a draft, or approved without a time.
  const stale = (await db.prepare(`SELECT id FROM advisor_posts WHERE kind=? AND region=? AND id<>? AND (status='draft' OR (status='approved' AND scheduled_for IS NULL))`)
    .bind(draft.kind, draft.region, draft.id).all<{id: string}>()).results.map(r => r.id);
  if (stale.length) {
    await db.prepare(`UPDATE advisor_posts SET status='rejected',error='superseded',updated_at=? WHERE id IN (${stale.map(() => '?').join(',')})`).bind(at, ...stale).run();
    await closeReviews(db, stale, at, 'superseded by a newer post');
    advisorLog('info', 'advisor_post_superseded', {kind: draft.kind, count: stale.length});
  }
  const current = await graphicState(db, draft.id);
  const same = current && current.status !== 'failed' && current.kind === draft.graphic.kind && JSON.stringify(current.data) === JSON.stringify(draft.graphic.data)
    && JSON.stringify(current.media_ids ?? []) === JSON.stringify(draft.media.slice(0, 10));
  if (!same) {
    await requestGraphic(env, draft.id, {kind: draft.graphic.kind, ...(draft.media.length ? {media_ids: draft.media.slice(0, 10)} : {}), data: draft.graphic.data,
      out_key: graphicKey(draft.id, draft.graphic.file)}, now, deps.dispatch ? {dispatch: deps.dispatch} : {});
  }
  advisorLog('info', before ? 'advisor_post_redrafted' : 'advisor_post_drafted', {kind: draft.kind, graphic: same ? 'kept' : 'requested'});
  return {region: draft.region, status: before ? 'updated' : 'created', postId: draft.id};
}

// ---- the daily post ------------------------------------------------------------------------------

interface DailyReportRow {id: string; boat_id: string; port: string; anglers: number | null; counts_json: string; boat: string; updated_at: string}

export interface DailyBoat {boat: string; port: string; anglers: number | null; counts: {label: string; species_key: string; kept: number}[]; total: number}
export interface DailyPostData {
  region: string; date: string; posted_on: string; place: string; ports: string[]; boats: DailyBoat[];
  top: {label: string; kept: number}[]; species: string[]; conditions: string | null; confidence: string | null;
}

/** The previous local day's published reports from verified boats in the region, one per boat (its latest), most fish first. */
export async function dailyReports(db: D1Database, region: string, date: string): Promise<DailyBoat[]> {
  const rows = (await db.prepare(`SELECT r.id,r.boat_id,r.port,r.anglers,r.counts_json,r.updated_at,b.name AS boat FROM advisor_reports r JOIN advisor_boats b ON b.id=r.boat_id
      WHERE r.region=? AND r.report_date=? AND r.status='published' AND r.verified=1 AND b.status='verified' ORDER BY r.updated_at DESC, r.id`)
    .bind(region, date).all<DailyReportRow>()).results;
  const seen = new Set<string>(), boats: DailyBoat[] = [];
  for (const r of rows) {
    if (seen.has(r.boat_id)) continue;
    seen.add(r.boat_id);
    const counts = countsOf(r.counts_json).filter(c => c.kept && !c.uncertain).map(c => ({label: c.label, species_key: c.species_key, kept: c.kept!}))
      .sort((a, b) => b.kept - a.kept);
    boats.push({boat: r.boat, port: r.port, anglers: r.anglers, counts, total: counts.reduce((n, c) => n + c.kept, 0)});
  }
  return boats.sort((a, b) => b.total - a.total || a.boat.localeCompare(b.boat));
}

/** The best ladder word among the landing reports' targets with trips (Moderate > Low), 'Insufficient' with none, null when the feed did not load. */
export function confidenceWord(inputs: Pick<DailyInputs, 'feeds' | 'landing'>): string | null {
  if (!inputs.feeds.daily || !inputs.landing.available) return null;
  const words = inputs.landing.activity.filter(a => a.trips > 0).map(a => a.confidence);
  return words.sort((a, b) => LADDER.indexOf(b) - LADDER.indexOf(a))[0] ?? 'Insufficient';
}

/** The card and caption's facts for a region's daily post (null without a report). */
export async function dailyPostData(env: Env, region: string, now: number, deps: DailyDeps = {}): Promise<DailyPostData | null> {
  const config = regionConfig(region), tz = config?.timezone ?? PACIFIC;
  const today = localDate(now, tz), date = addDays(today, -1);
  const boats = await dailyReports(env.DB!, region, date);
  if (!boats.length) return null;
  const ports = [...new Set(boats.map(b => b.port))];
  // The port with the most boats reporting, for the conditions line (the catalog order breaks ties).
  const order = activePorts();
  const main = [...ports].sort((a, b) => boats.filter(x => x.port === b).length - boats.filter(x => x.port === a).length || order.indexOf(a) - order.indexOf(b))[0]!;
  const totals = new Map<string, {label: string; kept: number}>();
  for (const b of boats) for (const c of b.counts) {
    const key = c.label.toLowerCase(), entry = totals.get(key) ?? {label: c.label, kept: 0};
    entry.kept += c.kept; totals.set(key, entry);
  }
  const top = [...totals.values()].sort((a, b) => b.kept - a.kept || a.label.localeCompare(b.label)).slice(0, TOP_COUNTS_MAX);
  let conditions: string | null = null, confidence: string | null = null;
  try {
    const inputs = await dailyInputs(env, main, today, deps, now);
    conditions = inputs.feeds.intelligence || inputs.conditions.advisories.length ? conditionsText(inputs.conditions, FEED_LANGUAGE) : null;
    confidence = confidenceWord(inputs);
  } catch (error) {
    advisorLog('warn', 'advisor_daily_post_inputs_failed', {reason: String((error as Error)?.message).slice(0, 120)});
  }
  const place = ports.length === 1 ? portName(ports[0]) ?? ports[0]! : config?.name ?? region;
  const species = [...new Set(boats.flatMap(b => b.counts.map(c => c.species_key)).filter(k => k !== 'other'))];
  return {region, date, posted_on: today, place, ports, boats, top, species, conditions, confidence};
}

const boatCounts = (b: DailyBoat): string => b.counts.slice(0, 4).map(c => `${c.kept} ${c.label}`).join(', ');

/** The caption: heading, one line per boat, today's conditions, the confidence word, the call to action, the hashtags. No model, no probability. */
export function dailyCaption(d: DailyPostData, number: string | null, language: Language = FEED_LANGUAGE): string {
  const lines = [t(language, 'daily_post_heading', {place: d.place, date: shortDate(d.date, language)})];
  for (const b of d.boats.slice(0, DAILY_BOATS_MAX)) {
    const counts = boatCounts(b);
    if (!counts) continue;
    lines.push(b.anglers ? t(language, 'daily_post_boat', {boat: b.boat, counts, anglers: b.anglers}) : `${b.boat}: ${counts}.`);
  }
  if (d.conditions) lines.push(d.conditions);
  if (d.confidence) lines.push(t(language, 'daily_post_confidence', {label: d.confidence}));
  lines.push(t(language, 'caption_cta', {number: displayNumber(number)}));
  return cut(`${lines.join('\n')}\n\n${tags(hashtagsFor(d.region, d.species))}`);
}

/** The `daily` graphic's data (media_job.py daily_graphic: title, lines, conditions, confidence). */
export function dailyGraphicData(d: DailyPostData, language: Language = FEED_LANGUAGE): Record<string, unknown> {
  const lines: {label: string; value: string}[] = [];
  if (d.top.length) lines.push({label: t(language, 'daily_post_top_label'), value: d.top.map(c => `${c.kept} ${c.label}`).join(', ')});
  for (const b of d.boats.slice(0, CARD_BOATS_MAX)) {
    const counts = boatCounts(b);
    if (counts) lines.push({label: b.boat, value: counts});
  }
  return {title: t(language, 'daily_post_title', {place: d.place}), port: d.place, date: shortDate(d.date, language), lines,
    ...(d.conditions ? {conditions: d.conditions} : {}), ...(d.confidence ? {confidence: t(language, 'daily_post_confidence_short', {label: d.confidence})} : {})};
}

/**
 * The `daily-post` slot (06:30 local). Every active region; one failing region
 * does not stop the others, and the slot is released (retried next tick) when
 * any failed.
 */
export async function draftDailyPosts(env: Env, now: number, deps: SocialDraftDeps = {}): Promise<GeneratedOutcome[]> {
  const out: GeneratedOutcome[] = [];
  let failed = 0;
  const number = advisorSettings(env).number;
  for (const region of activeRegions()) {
    try {
      const data = await dailyPostData(env, region, now, deps);
      if (!data) { out.push({region, status: 'skipped', reason: 'no published verified report yesterday'}); continue; }
      out.push(await upsertGeneratedDraft(env, {id: await dailyPostId(region, data.posted_on), kind: 'daily', region, media: [], caption: dailyCaption(data, number),
        collaborators: [], graphic: {kind: 'daily', data: dailyGraphicData(data), file: GRAPHIC_FILE.daily}}, now, deps));
    } catch (error) {
      failed++;
      advisorLog('warn', 'advisor_daily_post_failed', {region, reason: String((error as Error)?.message).slice(0, 120)});
    }
  }
  if (failed) throw Error(`daily post failed for ${failed} region(s)`);
  return out;
}

// ---- the weekly roundup -----------------------------------------------------------------------

interface RoundupRow {
  id: string; boat_id: string | null; classification_json: string | null; credit: string | null; created_at: string; home_port: string | null;
  boat: string | null; port: string | null; instagram: string | null; boat_status: string | null; boat_region: string | null;
  consent_photos_at: string | null; consent_revoked_at: string | null;
}
export interface RoundupPhoto {id: string; boat: string | null; handle: string | null; credit: string | null; port: string; species: string | null; created_at: string}

const isCatch = (json: string | null): boolean => { try { return JSON.parse(json ?? 'null')?.classify?.kind === 'fish'; } catch { return false; } };

/**
 * The week's photos for a region: images approved or posted in the last 7
 * days, classified as a fish (a catch), with no open photo review; a boat's
 * only while the boat is verified with photo consent, an angler's when their
 * home port is in the region. Spread by (port, species): the largest group
 * first, newest photo first in each, round robin, at most ROUNDUP_PHOTOS_MAX.
 */
export async function roundupPhotos(db: D1Database, region: string, now: number): Promise<RoundupPhoto[]> {
  const rows = (await db.prepare(`SELECT m.id,m.boat_id,m.classification_json,m.credit,m.created_at,c.home_port,b.name AS boat,b.port,b.instagram,b.status AS boat_status,
      b.region AS boat_region,b.consent_photos_at,b.consent_revoked_at
      FROM advisor_media m LEFT JOIN advisor_boats b ON b.id=m.boat_id LEFT JOIN advisor_contacts c ON c.id=m.contact_id
      WHERE m.kind='image' AND m.r2_key<>'' AND m.publish_state IN ('approved','posted') AND m.created_at>=?
        AND NOT EXISTS (SELECT 1 FROM advisor_reviews r WHERE r.kind='media' AND r.ref_id=m.id AND r.status='open')
      ORDER BY m.created_at DESC, m.id LIMIT 300`).bind(new Date(now - ROUNDUP_DAYS * 86400000).toISOString()).all<RoundupRow>()).results;
  const photos: RoundupPhoto[] = [];
  for (const r of rows) {
    if (!isCatch(r.classification_json)) continue;
    if (r.boat_id) {
      if (r.boat_region !== region || r.boat_status !== 'verified' || !consentActive(r)) continue;
    } else if (portRegion(r.home_port) !== region) continue;
    const port = r.boat_id ? r.port! : r.home_port!;
    photos.push({id: r.id, boat: r.boat_id ? r.boat : null, handle: r.instagram && HANDLE.test(r.instagram) ? r.instagram : null, credit: r.credit,
      port, species: photoSpecies(r)[0] ?? null, created_at: r.created_at});
  }
  const groups = new Map<string, RoundupPhoto[]>();
  for (const p of photos) { const key = `${p.port}|${p.species ?? ''}`; groups.set(key, [...(groups.get(key) ?? []), p]); }
  const ordered = [...groups.entries()].sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0])).map(([, list]) => list);
  const picked: RoundupPhoto[] = [];
  for (let round = 0; picked.length < ROUNDUP_PHOTOS_MAX && ordered.some(list => list.length > round); round++) {
    for (const list of ordered) if (list[round] && picked.length < ROUNDUP_PHOTOS_MAX) picked.push(list[round]!);
  }
  return picked;
}

const speciesWord = (key: string | null, language: Language): string => (key && speciesName(key)) || t(language, 'roundup_species_other');
const anglerCredit = (p: RoundupPhoto, language: Language): string =>
  !p.credit || /^(?:anonymous|an[oó]nimo)$/i.test(p.credit.trim()) ? t(language, 'roundup_angler_anonymous') : p.credit.trim();

export interface RoundupDraftParts {caption: string; collaborators: string[]; data: Record<string, unknown>}

/** The roundup's caption, collaborators (the boats with the most photos, 3 at most; the others mentioned) and graphic data. */
export function roundupParts(region: string, photos: readonly RoundupPhoto[], number: string | null, language: Language = FEED_LANGUAGE): RoundupDraftParts {
  const config = regionConfig(region), ports = [...new Set(photos.map(p => p.port))];
  const place = ports.length === 1 ? portName(ports[0]) ?? ports[0]! : config?.name ?? region;
  const boats = new Map<string, {name: string; handle: string | null; n: number}>();
  for (const p of photos) if (p.boat) { const b = boats.get(p.boat) ?? {name: p.boat, handle: p.handle, n: 0}; b.n++; boats.set(p.boat, b); }
  const byCount = [...boats.values()].sort((a, b) => b.n - a.n || a.name.localeCompare(b.name));
  const handles = [...new Set(byCount.map(b => b.handle).filter((h): h is string => Boolean(h)))];
  const collaborators = handles.slice(0, COLLABORATORS_MAX), mentioned = handles.slice(COLLABORATORS_MAX);
  const lines = [boats.size > 1 ? t(language, 'roundup_heading', {place, photos: photos.length, boats: boats.size}) : t(language, 'roundup_heading_one_boat', {place, photos: photos.length})];
  const portLines: {label: string; value: string}[] = [];
  for (const port of ports) {
    const species = [...new Set(photos.filter(p => p.port === port && p.species).map(p => speciesWord(p.species, language)))];
    const name = portName(port) ?? port;
    if (species.length) lines.push(`${name}: ${species.join(', ')}.`);
    portLines.push({label: name, value: `${photos.filter(p => p.port === port).length} · ${species.join(', ') || speciesWord(null, language)}`});
  }
  if (byCount.length) lines.push(t(language, 'roundup_aboard', {boats: byCount.map(b => b.name).join(', ')}));
  if (mentioned.length) lines.push(t(language, 'roundup_also', {handles: mentioned.map(h => `@${h}`).join(', ')}));
  const anglers = [...new Set(photos.filter(p => !p.boat).map(p => anglerCredit(p, language)))];
  if (anglers.length) lines.push(t(language, 'roundup_anglers', {credits: anglers.join(', ')}));
  lines.push(t(language, 'caption_cta', {number: displayNumber(number)}));
  const species = [...new Set(photos.map(p => p.species).filter((s): s is string => Boolean(s)))];
  const caption = cut(`${lines.join('\n')}\n\n${tags(hashtagsFor(region, species, {angler: anglers.length > 0}))}`);
  const captions = photos.map(p => {
    const who = p.boat ?? anglerCredit(p, language), port = portName(p.port) ?? p.port;
    return [who, port, ...(p.species ? [speciesWord(p.species, language)] : [])].join(' · ');
  });
  return {caption, collaborators, data: {title: t(language, 'roundup_title', {place}), lines: portLines, captions}};
}

/** The `weekly-roundup` slot (Sundays 17:00 local): every active region with at least one photo this week. */
export async function draftRoundups(env: Env, now: number, deps: SocialDraftDeps = {}): Promise<GeneratedOutcome[]> {
  const out: GeneratedOutcome[] = [];
  let failed = 0;
  const number = advisorSettings(env).number;
  for (const region of activeRegions()) {
    try {
      const photos = await roundupPhotos(env.DB!, region, now);
      if (!photos.length) { out.push({region, status: 'skipped', reason: 'no approved catch photo this week'}); continue; }
      const parts = roundupParts(region, photos, number);
      const date = localDate(now, regionConfig(region)?.timezone ?? PACIFIC);
      out.push(await upsertGeneratedDraft(env, {id: await roundupPostId(region, date), kind: 'roundup', region, media: photos.map(p => p.id), caption: parts.caption,
        collaborators: parts.collaborators, graphic: {kind: 'roundup', data: parts.data, file: GRAPHIC_FILE.roundup}}, now, deps));
    } catch (error) {
      failed++;
      advisorLog('warn', 'advisor_roundup_failed', {region, reason: String((error as Error)?.message).slice(0, 120)});
    }
  }
  if (failed) throw Error(`roundup failed for ${failed} region(s)`);
  return out;
}
