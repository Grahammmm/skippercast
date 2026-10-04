// An angler's photos (docs/plans/text-advisor/04-advisor-engine.md § stage 2,
// 06 § Fish ID and § Angler photos; ID-1..ID-3, AC-1): the Stage 2 flow for a
// contact who is not a skipper or crew (their media go through TA-I2's
// intake/reports.ts, which runs first and never falls through to here for a
// contact with a boat).
//
//   media-only message  classify (07) -> 'fish' -> identifyFish -> the 06 reply (answers/fishid.ts),
//                       then the AC-1 offer when the ID was >= 0.6
//                    -> anything else: "Nice shot. Want me to ID a fish, or can we share this with credit?"
//   offer outstanding   (job_state advisor.share.<contact_id>, 24 h)
//                       yes / sí / sure / ok ... -> queued for review, reason angler_photo; credit asked once
//                       "id" (after "Nice shot") -> the fish ID of that photo
//                       anything else            -> the offer lapses and the message goes on
//   credit outstanding  a first name (1-4 words) or "anonymous" -> stored on advisor_media.credit
//
// No chat model call on any of these paths. A photo with a caption goes to the
// model, which has identify_fish and share_angler_photo (the same code).
import {t} from '../strings.ts';
import type {StringKey} from '../strings.ts';
import {resolveLinks} from '../links.ts';
import {decideHold, MediaTooLarge} from '../vision/index.ts';
import type {Classification} from '../vision/index.ts';
import {identify, offerShare} from '../answers/fishid.ts';
import type {MediaInput} from '../answers/fishid.ts';
import {chainFor, imageOf, norm} from './reports.ts';
import {uploadLinkText} from '../tools/send_upload_link.ts';
import {advisorLog} from '../log.ts';
import {capReply} from '../reply.ts';
import type {Action, AdvisorContactRow, AdvisorSettings, EngineResult, Language, ShareState} from '../types.ts';
import type {Flow, FlowContext} from '../engine.ts';

export const SHARE_KEY_PREFIX = 'advisor.share.';
export const shareKey = (contactId: string): string => SHARE_KEY_PREFIX + contactId;
export const SHARE_MAX_AGE_MS = 24 * 3600000;   // 04 § stage 2: the AC-1 offer answers YES for 24 h
export const CREDIT_MAX = 40;

/** 10 § TA-I3: the words that accept the AC-1 offer. */
export const SHARE_YES: ReadonlySet<string> = new Set(['yes', 'y', 'yep', 'yeah', 'yup', 'sure', 'ok', 'okay', 'k', 'go ahead', 'share it', 'sure thing', 'of course',
  'sí', 'si', 'claro', 'dale', 'va', 'de acuerdo', 'por supuesto', 'compártela', 'compartela']);
const ID_WORDS = /^(?:id|i\.d\.?|id it|id the fish|identify|identify it|what fish|what is it|what kind|which fish|identif[ií]calo|identif[ií]cala|identif[ií]ca|qu[eé] pez|qu[eé] pez es)$/u;
const ANONYMOUS = /^(?:anonymous|anon|anonymously|no name|none|nobody|an[oó]nimo|an[oó]nima|sin nombre)$/u;
const CREDIT_LEAD = /^(?:credit|call me|it'?s|i'?m|name'?s|just|me llamo|soy|ponle|pon)\s+/iu;
const NAME = /^[\p{L}][\p{L}.'’ -]*$/u;

/** A credit from a reply: 'anonymous', a short name (1-4 words, letters only, 40 characters at most), or null when it is not one. */
export function parseCredit(text: string | null | undefined): string | null {
  const raw = String(text ?? '').normalize('NFC').trim().replace(/^["'“”‘’]+|["'“”‘’.!]+$/gu, '').trim();
  if (!raw) return null;
  if (ANONYMOUS.test(raw.toLowerCase())) return 'anonymous';
  const name = raw.replace(CREDIT_LEAD, '').replace(/\s+/g, ' ').trim();
  if (!name || name.length > CREDIT_MAX || !NAME.test(name) || name.split(' ').length > 4) return null;
  if (SHARE_YES.has(name.toLowerCase()) || /^(?:no|nope|nah|n)$/i.test(name)) return null;
  return name;
}

/** The outstanding offer, or null (none, unreadable, or older than 24 h). */
export async function readShare(db: D1Database, contactId: string, now: number): Promise<ShareState | null> {
  const row = await db.prepare('SELECT value FROM job_state WHERE key=?').bind(shareKey(contactId)).first<{value: string}>();
  if (!row) return null;
  try {
    const v = JSON.parse(row.value) as ShareState;
    if (!v || (v.step !== 'offered' && v.step !== 'credit') || typeof v.media_id !== 'string' || !(now - Date.parse(v.asked_at) <= SHARE_MAX_AGE_MS)) return null;
    return v;
  } catch { return null; }
}

/** The credit this contact gave for an earlier shared photo ("asked once", 06 § Angler photos), or null. */
export async function knownCredit(db: D1Database, contactId: string): Promise<string | null> {
  const row = await db.prepare("SELECT credit FROM advisor_media WHERE contact_id=? AND boat_id IS NULL AND credit IS NOT NULL AND publish_state<>'private' ORDER BY created_at DESC LIMIT 1")
    .bind(contactId).first<{credit: string}>();
  return row?.credit ?? null;
}

const say = (settings: AdvisorSettings, language: Language, key: StringKey, vars: Record<string, string | number> = {}): Action =>
  ({type: 'send_text', text: resolveLinks(t(language, key, vars), settings.publicBase).text});
const offeredState = (mediaId: string, now: number, idOffered = false): Action =>
  ({type: 'share_state', state: {step: 'offered', media_id: mediaId, asked_at: new Date(now).toISOString(), ...(idOffered ? {id_offered: true} : {})}});

export interface ShareArgs {db: D1Database; settings: AdvisorSettings; contact: Pick<AdvisorContactRow, 'id'>; mediaId: string; language: Language; now: number}
/**
 * The actions of a yes (the engine's pre-router and share_angler_photo): the
 * photo queued, the angler_photo review, and the credit: the one given before
 * (no question), else "How should we credit you?" and the credit step.
 */
export async function shareActions(a: ShareArgs): Promise<{actions: Action[]; credit: string | null; asked: boolean}> {
  const credit = await knownCredit(a.db, a.contact.id);
  const base: Action[] = [{type: 'angler_share', mediaId: a.mediaId, ...(credit ? {credit} : {})}, {type: 'review_open', kind: 'media', refId: a.mediaId, reason: 'angler_photo'}];
  if (credit) return {actions: [...base, {type: 'share_state', state: null}, credit === 'anonymous' ? say(a.settings, a.language, 'share_queued_anonymous') : say(a.settings, a.language, 'share_queued_known', {credit})], credit, asked: false};
  return {actions: [...base, {type: 'share_state', state: {step: 'credit', media_id: a.mediaId, asked_at: new Date(a.now).toISOString()}}, say(a.settings, a.language, 'share_credit_ask')], credit: null, asked: true};
}

/** The actions for a credit reply. */
export function creditActions(settings: AdvisorSettings, language: Language, mediaId: string, credit: string): Action[] {
  return [{type: 'angler_share', mediaId, credit}, {type: 'share_state', state: null},
    credit === 'anonymous' ? say(settings, language, 'share_queued_anonymous') : say(settings, language, 'share_queued', {credit})];
}

interface MediaRow extends MediaInput {kind: string; bytes: number; publish_state: string}
/** The contact's own stored media rows for these ids, in message order. */
async function ownMedia(db: D1Database, contactId: string, ids: readonly string[]): Promise<MediaRow[]> {
  if (!ids.length) return [];
  const rows = (await db.prepare(`SELECT id,kind,mime,bytes,width,height,r2_key,publish_state,orientation FROM advisor_media WHERE contact_id=? AND id IN (${ids.map(() => '?').join(',')})`)
    .bind(contactId, ...ids).all<MediaRow>()).results;
  return rows.sort((a, b) => ids.indexOf(a.id) - ids.indexOf(b.id));
}

/** The fish-ID texts and the AC-1 offer for one photo (shared by the media path and the "id" reply). */
async function idActions(f: FlowContext, row: MediaRow): Promise<{actions: Action[]; intent: string}> {
  const result = await identify(f.env, row, f.contact, {vision: chainFor(f.env, f.deps), language: f.language, now: f.now, settings: f.settings});
  if (!result.ok) {
    if (result.error === 'too_large') return {actions: [await uploadAction(f, 'media_too_large')], intent: 'fishid.upload_link'};
    return {actions: [say(f.settings, f.language, 'fishid_unavailable')], intent: 'fishid.unavailable'};
  }
  const resolved = resolveLinks(result.answer.text, f.settings.publicBase);
  const actions: Action[] = [{type: 'send_text', text: capReply(resolved.text, resolved.links)}];
  if (offerShare(result.answer, f.contact.role)) actions.push(say(f.settings, f.language, 'fishid_offer'), offeredState(row.id, f.now));
  return {actions, intent: `fishid.${result.answer.band}`};
}

async function uploadAction(f: FlowContext, key: StringKey): Promise<Action> {
  const link = await uploadLinkText({env: f.env, contact: f.contact, language: f.language, settings: f.settings, now: f.now});
  return link.ok ? say(f.settings, f.language, key, {link: link.text.slice(link.text.lastIndexOf(' ') + 1)}) : {type: 'send_text', text: link.text};
}

/**
 * A media-only message from an angler (04 § stage 2): the first stored image
 * is classified; a fish gets the fish ID (06), anything else "Nice shot..."
 * with the offer recorded. A file the intake rejected gets the upload link.
 * Null when nothing stored is readable (the engine's acknowledgement answers).
 */
async function mediaTurn(f: FlowContext): Promise<EngineResult | null> {
  const rows = await ownMedia(f.db, f.contact.id, f.media.slice(0, 10));
  if (!rows.length) return null;
  const rejected = rows.find(r => r.publish_state === 'rejected' || r.kind === 'unknown');
  const row = rows.find(r => r.kind === 'image' && r.r2_key && r.publish_state !== 'rejected');
  if (!row || !f.env.ADVISOR_MEDIA) {
    if (rejected) { advisorLog('info', 'advisor_media_upload_offered', {bytes: rejected.bytes}); return {actions: [await uploadAction(f, 'media_use_upload')], intent: 'media.upload_link'}; }
    const video = rows.find(r => r.kind === 'video');
    if (video) return {actions: [say(f.settings, f.language, 'fishid_nice_shot'), offeredState(video.id, f.now)], intent: 'media.nice_shot'};
    return null;
  }
  let c: Classification;
  try {
    c = await chainFor(f.env, f.deps).classify(imageOf(f.env, row));
  } catch (error) {
    if (error instanceof MediaTooLarge) return {actions: [await uploadAction(f, 'media_too_large')], intent: 'media.upload_link'};
    advisorLog('warn', 'advisor_vision_failed', {name: (error as Error)?.name ?? 'Error'});
    return {actions: [say(f.settings, f.language, 'fishid_unavailable')], intent: 'fishid.unavailable'};
  }
  if (c.kind === 'fish') return idActions(f, row);
  // Not a fish photo (a deck, a sunset, a person): offer both, never publish anything without a yes.
  if (decideHold(c)) advisorLog('info', 'advisor_angler_photo_person', {count: 1});
  return {actions: [say(f.settings, f.language, 'fishid_nice_shot'), offeredState(row.id, f.now, true)], intent: 'media.nice_shot'};
}

/**
 * TA-I3's Stage 2 flow: the AC-1 replies (YES, the credit, "id") while an
 * offer is outstanding, then the media-only angler path. Skippers and crew
 * never get here with media: their boat's report flow answers first, and the
 * role check below keeps a boatless skipper on the plain acknowledgement.
 */
export async function anglerFlow(f: FlowContext): Promise<EngineResult | null> {
  if (f.contact.role === 'skipper' || f.contact.role === 'crew') return null;
  if (f.text) {
    const share = await readShare(f.db, f.contact.id, f.now);
    if (!share) return null;
    const words = norm(f.text);
    if (share.step === 'credit') {
      const credit = parseCredit(f.text);
      if (credit) return {actions: creditActions(f.settings, f.language, share.media_id, credit), intent: 'photo.credit'};
      f.carry.push({type: 'share_state', state: null});   // not a name: the photo stays queued without a credit
      return null;
    }
    if (SHARE_YES.has(words)) {
      const {actions} = await shareActions({db: f.db, settings: f.settings, contact: f.contact, mediaId: share.media_id, language: f.language, now: f.now});
      return {actions, intent: 'photo.share'};
    }
    if (share.id_offered && ID_WORDS.test(words)) {
      const [row] = await ownMedia(f.db, f.contact.id, [share.media_id]);
      if (row && row.kind === 'image' && f.env.ADVISOR_MEDIA) return idActions(f, row);
    }
    f.carry.push({type: 'share_state', state: null});    // anything else: the offer lapses (10 § TA-I3: "else ignore")
    return null;
  }
  if (f.media.length) return mediaTurn(f);
  return null;
}

/** The flows TA-I3 registers in engine.ts STAGE_TWO_FLOWS, after TA-I2's. */
export const ANGLER_FLOWS: readonly Flow[] = [{name: 'anglers', run: anglerFlow}];
