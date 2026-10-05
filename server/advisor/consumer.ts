// Text Advisor queue consumer (docs/plans/text-advisor/01-architecture.md
// § request flow, steps 5-7, and § Idempotency and failure rules).
//
//   ADVISOR_QUEUE {message_id} -> load the stored inbound row -> mark processing
//   -> handler (the engine, engine.ts; warmUpHandler when none is passed) -> apply its
//   actions in order -> mark done -> ack.
//
// Every write is idempotent, so a re-delivered message repeats nothing it
// already did: outbound rows have deterministic ids (ids.ts outboundId), are
// written as 'sending' before the send and never sent again once 'sent'; a row
// left 'sending' by a crash may have been delivered, so a retry marks it
// 'unknown' instead of resending (BlueBubbles' updated-message webhook confirms
// it as sent when the relay reports delivery; the cron-side reconciliation by
// provider query in 01 is not built yet).
// Review items use reviewId's deterministic id with the same UPSERT as
// forgetContact. A handler that throws is retried with backoff; after
// max_retries (scripts/wrangler_config.mjs ADVISOR_QUEUES) Cloudflare moves the
// message to the dead-letter queue, whose consumer marks it failed and sends
// the contact one apology an hour at most.
//
// Outbound goes through deps.channelFor(env, contact) (channels/index.ts, wired
// in server/index.ts). A text longer than the channel allows is split
// (splitForChannel) and sent as one row per chunk, 300 ms apart. While the
// Mac relay is down (job_state advisor.relay, cron.ts) a BlueBubbles send is
// written as 'held' and not attempted; releaseHeld, run by the cron, sends the
// held rows once the relay is back and fails those older than 6 hours.
//
// TA-C4: before the handler, every placeholder media row of the message is
// downloaded through the receiving adapter's fetchMediaByRef, sniffed, stripped
// and stored (media.ts ingestInboundMedia). A failed download retries the
// message (at most MEDIA_RETRIES extra attempts); after that the handler runs
// with that media rejected and the inbound row's error 'fetch-failed'.
//
// TA-E1: the engine (engine.ts) is the handler; it owns STOP/blocked and the
// daily caps (its stage 0). The appliers for its new actions sit in the
// "TA-E1" block of applyActions: set_status (applyStop/applyStart), forget
// (the confirmation text, then forgetContact), export (exportContact to R2 and
// a signed 24 h link), send_file (an attachment on BlueBubbles, the link
// elsewhere), link_start/link_merge (the web phone link, 03 § web) and
// admin_review (the text admin fallback, 08); review_open also texts the admin
// contact about new skipper and media items (notifyAdmin).
//
// TA-I1: skipper registration, consent and crew (05). boat_create inserts the
// pending boat and makes the contact its skipper; flow_set writes or clears
// job_state advisor.flow.<contact_id>; consent records consent_photos_at with
// the message id, or consent_revoked_at; post_revoke rejects the boat's draft
// and approved posts (TA-S1);
// crew_add (hardening) finds or creates the contact, records a pending
// invitation and texts it through its own channel; crew_accept (its YES within
// 72 h) makes the link, crew_decline (NO) silences the boat for 30 days;
// crew_remove sets removed_at and clears the boat. Verifying
// or rejecting a new_skipper review by text now also texts the boat's owner.
//
// TA-I2: skipper reports (05). report_draft inserts the pending report (a
// same-day one becomes an edit), report_publish / report_withdraw / report_edit
// run intake/reports.ts (edits rows, version, clean_reports, the pages version
// and the port's daily answer), auto_publish toggles SC-5, media_queue puts a
// consented photo in the feed queue, boat_instagram stores the handle asked
// once, mark_once records a one-time line. Each re-checks that the contact
// posts for the boat.
//
// TA-M1: an image a vision provider cannot take as stored (over 4.5 MB, or
// HEIC) waits for the advisor-media job's public.jpg: the consumer dispatches
// the job and re-queues the message (retry, 30 s) on its first DERIVED_WAITS
// attempts; the vision chain then reads public.jpg. On the last attempt the
// handler runs anyway and a photo still too large gets the upload link. A
// media review approved by text, and a photo put in the feed queue, start the
// job too (thumb.jpg and public.jpg for the admin queue and the pages).
//
// TA-I3: angler photos (06 § Angler photos). share_state writes or clears the
// AC-1 offer (job_state advisor.share.<contact_id>); angler_share queues the
// angler's own photo for review and stores the credit they gave.
//
// TA-W2: the text admin's decision runs admin/decisions.ts decideReview, the
// same code the admin queue uses; teamSender is how either sends the texts a
// decision owes (created_by set for the admin queue's).
//
// TA-S6: Instagram (09 § Inbox). An Instagram contact's address is its IGSID and
// its channel the Instagram adapter (channels/index.ts channelFor); comment_reply
// answers a comment once, privately or publicly (channels/instagram.ts commentChannel).
//
// TA-S1: social drafts (09 § Drafts). media_queue also makes the photo's post
// draft and its `post` review (social/drafts.ts ensureMediaDraft: consent
// re-checked, one model call for the caption line through deps.engine.fetcher);
// post_draft drafts a photo already queued (propose_post); post_revoke rejects
// the boat's draft and approved posts.
import {advisorSettings} from './settings.ts';
import {reviewId, applyStop, applyStart, forgetContact, exportContact, deriveKeys} from './contacts.ts';
// TA-E1: the engine's export link, the web phone link's code channel and the admin notifications.
import {exportKey, mintExportToken} from './exports.ts';
import {channelFor as defaultChannelFor} from './channels/index.ts';
import {linkKey} from './tools/offer_text_link.ts';
import {t} from './strings.ts';
import {localClock} from './cron.ts';
import {outboundId, randomId} from './ids.ts';
import {advisorLog, redact} from './log.ts';
import {recordAdvisorTurn} from './analytics.ts';
import {relayState} from './relay.ts';
import {splitForChannel, ChannelNotImplemented, CHUNK_GAP_MS} from './channels/index.ts';
import type {AdapterName} from './channels/index.ts';
// TA-S6: an Instagram comment's private or public reply.
import {commentChannel} from './channels/instagram.ts';
// TA-C4: media intake before the handler.
import {ingestInboundMedia} from './media.ts';
// TA-M1: waiting for the media job's derived image.
import {awaitingDerived, requestMediaJob} from './media.ts';
import {fetchMediaByRef as adapterFetchMediaByRef} from './channels/index.ts';
// TA-I1: the skipper flow's state key and the crew invite.
import {flowKey, isVerified, crewDeclined, readCrewInvite, crewInviteKey, crewDeclineKey, CREW_INVITE_TTL_MS} from './intake/skippers.ts';
import type {CrewInvite} from './intake/skippers.ts';
import {MAX_CREW} from './tools/add_crew.ts';
// TA-I2: reports, the media queue and the one-time lines.
import {insertDraft, publishReport, withdrawReport, applyEdit, postsFor, ONCE_PREFIX} from './intake/reports.ts';
// TA-I3: the AC-1 offer state and the angler's shared photo.
import {shareKey, CREDIT_MAX} from './intake/anglers.ts';
// TA-W2: admin decisions, shared by the text admin and the admin queue.
import {decideReview} from './admin/decisions.ts';
import type {TeamSend} from './admin/decisions.ts';
// TA-S1: social drafts.
import {ensureMediaDraft, revokeBoatPosts} from './social/drafts.ts';
import type {Env} from '../env.ts';
import type {Action, AdvisorContactRow, AdvisorMessage, AdvisorMessageRow, ConsumerDeps, ContactFields, EngineResult, Handler, OutboundChannel, OutboundMessage, ReviewKind, SendResult} from './types.ts';

// Must match scripts/wrangler_config.mjs ADVISOR_QUEUES (tests/test_advisor_consumer.mjs checks).
export const ADVISOR_QUEUE_NAME = 'skippercast-advisor';
export const ADVISOR_DLQ_NAME = 'skippercast-advisor-dlq';

export const TURN_TIMEOUT_MS = 45000;          // 01 § request flow: hard stop per message
export const TIMEOUT_RETRY_SECONDS = 20;
export const ERROR_NOTICE_MS = 60 * 60000;     // one apology per contact per hour
export const MAX_BODY = 4000;                  // 02 § advisor_messages.body
// TA-A6: the consumer's own texts come from catalog/advisor/strings.json in the contact's language; these are the English ones.
export const WARM_UP_TEXT = t('en', 'warming_up');
export const STILL_WORKING_TEXT = t('en', 'still_working');
export const APOLOGY_TEXT = t('en', 'apology');
export const HOLD_MAX_MS = 6 * 3600000;        // 01: held outbound older than this becomes failed
export const RELEASE_BATCH = 50;               // held rows sent per cron tick
export const MEDIA_RETRIES = 2;                // TA-C4: extra attempts after a failed media download
// TA-M1: attempts that may wait for public.jpg. The queue's max_retries is 3 (scripts/wrangler_config.mjs
// ADVISOR_QUEUES), so the fourth delivery is the last: it always runs the handler.
export const DERIVED_WAITS = 3;
export const DERIVED_RETRY_SECONDS = 30;

const ID = /^[\w-]{1,64}$/;
const CODE = /^[a-z][\w.:-]{0,47}$/i;
const REVIEW_KINDS: readonly ReviewKind[] = ['media', 'report', 'post', 'skipper', 'conversation', 'rule'];
const ROLES = ['angler', 'skipper', 'crew', 'admin-test'];
// Contact columns an action may set; every other column belongs to contacts.ts or the admin.
const CONTACT_FIELDS: readonly (keyof ContactFields)[] = ['role', 'boat_id', 'display_name', 'language', 'home_port', 'targets_json', 'source'];

/**
 * The stub handler until the engine lands (TA-E1): one warm-up text, and
 * nothing for a stopped or blocked contact (STOP means no outbound of any kind,
 * 02 § Retention and deletion; the engine's stage 0/1 owns that from TA-E1 on).
 */
export const warmUpHandler: Handler = async ({contact}) => contact?.status === 'active'
  ? {actions: [{type: 'send_text', text: t(contact.language, 'warming_up')}], intent: 'stub'}
  : {actions: [], intent: 'stub'};

/** A short reason for the error column and logs: redacted, at most 200 characters, never a payload. */
export const reason = (error: unknown): string => String(redact(String((error as Error)?.message ?? error))).slice(0, 200);

export interface AdvisorConsumeResult {messages: number; done: number; held: number; dropped: number; retried: number; invalid: number; failed: number; sends: number}

type QueueMessage = Message<AdvisorMessage>;
const clock = (deps: ConsumerDeps): number => (deps.now ?? Date.now)();
const iso = (deps: ConsumerDeps): string => new Date(clock(deps)).toISOString();

async function inbound(db: D1Database, id: string): Promise<AdvisorMessageRow | null> {
  return db.prepare("SELECT * FROM advisor_messages WHERE id=? AND direction='in'").bind(id).first<AdvisorMessageRow>();
}
async function setStatus(db: D1Database, id: string, status: string, from: string[], error: string | null = null): Promise<boolean> {
  const r = await db.prepare(`UPDATE advisor_messages SET status=?,error=? WHERE id=? AND status IN (${from.map(() => '?').join(',')})`).bind(status, error, id, ...from).run();
  return (r.meta.changes ?? 0) > 0;
}

/** Where a channel sends: the encrypted number (decrypted only inside the adapter), the web session hash, or (TA-S6) the IGSID. */
const address = (contact: AdvisorContactRow): string | null => contact.phone_enc ?? contact.web_session ?? contact.ig_sid ?? null;
/** The adapter for this contact: a fixed test channel, else channelFor, else none. */
const channelOf = (env: Env, deps: ConsumerDeps, contact: AdvisorContactRow): OutboundChannel | null => deps.channel ?? deps.channelFor?.(env, contact) ?? null;
const hint = (channel: string): OutboundMessage['channelHint'] => channel === 'imessage' || channel === 'sms' ? channel : undefined;
const sleep = (deps: ConsumerDeps, ms: number): Promise<void> => (deps.sleep ?? (n => new Promise<void>(resolve => setTimeout(resolve, n))))(ms);

/** True while the relay watchdog says the Mac is down and this adapter is BlueBubbles (01 § idempotency). */
async function relayHold(env: Env, adapter: OutboundChannel | null): Promise<boolean> {
  return adapter?.name === 'bluebubbles' && (await relayState(env))?.state === 'down';
}

/** Send through the adapter and normalise the outcome. A throw is 'unknown' (the provider may have accepted it), except a stub adapter's. */
async function deliver(env: Env, contact: AdvisorContactRow, adapter: OutboundChannel | null, message: Omit<OutboundMessage, 'to'>): Promise<SendResult> {
  const to = address(contact);
  if (contact.status === 'blocked') return {providerId: null, status: 'failed', error: 'blocked'};
  if (!to) return {providerId: null, status: 'failed', error: 'no-address'};
  if (!adapter) return {providerId: null, status: 'failed', error: 'no-channel'};
  const outbound: OutboundMessage = {...message, to, ...(hint(contact.channel) ? {channelHint: hint(contact.channel)} : {})};
  return adapter.send(outbound, env).catch((error: unknown) => error instanceof ChannelNotImplemented
    ? {providerId: null, status: 'failed' as const, error: reason(error)}
    : {providerId: null, status: 'unknown' as const, error: reason(error)});
}

async function recordResult(db: D1Database, deps: ConsumerDeps, id: string, result: SendResult): Promise<boolean> {
  const status = ['sent', 'failed', 'unknown'].includes(result.status) ? result.status : 'unknown';
  await db.prepare('UPDATE advisor_messages SET status=?,provider_id=?,sent_at=?,error=? WHERE id=?')
    .bind(status, result.providerId ?? null, status === 'sent' ? iso(deps) : null, result.error ? String(redact(result.error)).slice(0, 200) : null, id).run();
  if (status !== 'sent') advisorLog('warn', 'advisor_send_not_sent', {status, error: result.error ? String(result.error).slice(0, 200) : null});
  return status === 'sent';
}

/**
 * Send one outbound message at most once. `key` is the action index (or a
 * fixed word for the consumer's own texts). Returns true when this call sent it.
 *   none -> 'sending' -> send -> 'sent' | 'failed' | 'unknown'
 *   none -> 'held' while the relay is down (sent later by releaseHeld)
 *   'sent' / 'unknown' / 'held' -> skipped; 'sending' (a crash mid-send) -> 'unknown', skipped;
 *   'failed' -> sent again.
 * media_json on an outbound row holds the R2 keys it attaches, so a held row can be sent later.
 */
async function sendOnce(env: Env, deps: ConsumerDeps, contact: AdvisorContactRow, inId: string, key: number | string,
  content: {text?: string; mediaKeys?: string[]; files?: OutboundMessage['files']; createdBy?: string | null}, adapterOverride?: OutboundChannel | null): Promise<boolean> {
  const db = env.DB!, id = await outboundId(inId, key), at = iso(deps);
  const body = content.text == null ? null : content.text.slice(0, MAX_BODY);
  const adapter = adapterOverride !== undefined ? adapterOverride : channelOf(env, deps, contact);
  const existing = await db.prepare('SELECT status FROM advisor_messages WHERE id=?').bind(id).first<{status: string}>();
  if (existing) {
    if (existing.status === 'sending') { await setStatus(db, id, 'unknown', ['sending'], 'interrupted'); return false; }
    if (existing.status !== 'failed' || !await setStatus(db, id, 'sending', ['failed'])) return false;
  } else {
    const held = await relayHold(env, adapter);
    // TA-W2: created_by is the admin's users.id for a text sent from the admin queue (02 § advisor_messages).
    const r = await db.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,body,media_json,status,error,in_reply_to,created_by,created_at) VALUES(?,?,'out',?,?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING`)
      .bind(id, contact.id, contact.channel, body, content.mediaKeys?.length ? JSON.stringify(content.mediaKeys) : null, held ? 'held' : 'sending', held ? 'relay-down' : null, inId, content.createdBy ?? null, at).run();
    if (!r.meta.changes) return false;   // a concurrent delivery got there first
    if (held) { advisorLog('warn', 'advisor_send_held', {reason: 'relay-down'}); return false; }
  }
  const result = await deliver(env, contact, adapter, {id, ...(content.text != null ? {text: content.text} : {}), ...(content.mediaKeys ? {mediaKeys: content.mediaKeys} : {}),
    ...(content.files?.length ? {files: content.files} : {})});
  return recordResult(db, deps, id, result);
}

/**
 * A send_text action: split for the contact's channel and sent one row per
 * chunk, in order, 300 ms apart. Chunk 0 keeps the action's key, so an
 * unsplit text has the same outbound id as before; chunk n is "<key>.<n>".
 */
async function sendText(env: Env, deps: ConsumerDeps, contact: AdvisorContactRow, inId: string, key: number | string, text: string, adapterOverride?: OutboundChannel | null, createdBy: string | null = null): Promise<number> {
  const adapter = adapterOverride !== undefined ? adapterOverride : channelOf(env, deps, contact);
  const chunks = adapter?.name ? splitForChannel(text, {name: adapter.name as AdapterName}, contact.channel) : [text];
  let sends = 0;
  for (const [n, chunk] of chunks.entries()) {
    if (n > 0) await sleep(deps, CHUNK_GAP_MS);
    sends += Number(await sendOnce(env, deps, contact, inId, n === 0 ? key : `${key}.${n}`, {text: chunk, ...(createdBy ? {createdBy} : {})}, adapterOverride));
  }
  return sends;
}

function contactPatch(fields: ContactFields): [string, string | null][] {
  const out: [string, string | null][] = [];
  for (const [key, value] of Object.entries(fields ?? {})) {
    if (!(CONTACT_FIELDS as readonly string[]).includes(key)) { advisorLog('warn', 'advisor_contact_field_rejected', {field: String(key).slice(0, 40)}); continue; }
    if (value !== null && typeof value !== 'string') continue;
    let v = value === null ? null : value.trim();
    if (key === 'role' && (v === null || !ROLES.includes(v))) continue;
    if (key === 'language' && v !== 'en' && v !== 'es') continue;
    if (key === 'display_name' && v !== null) { v = v.replace(/[\u0000-\u001f\u007f]/g, '').slice(0, 60); if (!v) v = null; }
    if (v !== null && v.length > 2000) continue;
    out.push([key, v]);
  }
  return out;
}

/** Apply the engine's actions in order. Returns the number of texts actually sent by this call. */
async function applyActions(env: Env, deps: ConsumerDeps, contact: AdvisorContactRow, message: AdvisorMessageRow, actions: Action[]): Promise<number> {
  const db = env.DB!;
  let sends = 0;
  for (const [index, action] of actions.entries()) {
    switch (action?.type) {
      case 'send_text':
        if (typeof action.text === 'string' && action.text.trim()) sends += await sendText(env, deps, contact, message.id, index, action.text);
        break;
      case 'send_media':
        if (typeof action.r2Key === 'string' && action.r2Key) sends += Number(await sendOnce(env, deps, contact, message.id, index, {text: action.caption, mediaKeys: [action.r2Key]}));
        break;
      case 'contact_update': {
        const patch = contactPatch(action.fields);
        if (!patch.length) break;
        await db.prepare(`UPDATE advisor_contacts SET ${patch.map(([k]) => `${k}=?`).join(',')},updated_at=? WHERE id=?`)
          .bind(...patch.map(([, v]) => v), iso(deps), contact.id).run();
        break;
      }
      case 'review_open':
        if (!REVIEW_KINDS.includes(action.kind) || !ID.test(String(action.refId)) || !CODE.test(String(action.reason))) { advisorLog('warn', 'advisor_review_rejected', {kind: String(action.kind).slice(0, 20)}); break; }
      {
        const id = await reviewId(action.kind, action.refId, action.reason);
        const wasOpen = await db.prepare("SELECT 1 AS x FROM advisor_reviews WHERE id=? AND status='open'").bind(id).first();
        await db.prepare(`INSERT INTO advisor_reviews(id,kind,ref_id,reason,status,opened_at) VALUES(?,?,?,?,'open',?)
          ON CONFLICT(id) DO UPDATE SET status='open',opened_at=excluded.opened_at,decided_at=NULL,decided_by=NULL`)
          .bind(id, action.kind, action.refId, action.reason, iso(deps)).run();
        // TA-E1: the owner hears about a new skipper or media item by text (08 § text-based admin).
        if (!wasOpen) sends += Number(await notifyAdmin(env, {id, kind: action.kind, reason: action.reason}, deps, message.id));
        break;
      }
      case 'log':
        advisorLog('info', CODE.test(String(action.event)) ? action.event : 'advisor_action_log', action.fields ?? {});
        break;
      // ---- TA-E1: the engine's actions ----
      case 'set_status': {
        const changed = action.status === 'stopped' ? await applyStop(db, contact.id, new Date(clock(deps))) : action.status === 'active' ? await applyStart(db, contact.id, new Date(clock(deps))) : false;
        if (changed) contact.status = action.status;
        break;
      }
      case 'forget': {
        // The confirmation goes out first: the send needs the number, which the delete removes (02 § forget me).
        sends += await sendText(env, deps, contact, message.id, index, t(action.language, 'forget_done'));
        const removed = await forgetContact(db, env.ADVISOR_MEDIA, contact.id, new Date(clock(deps)));
        advisorLog('info', 'advisor_forget', {...removed});
        break;
      }
      case 'export':
        sends += await applyExport(env, deps, contact, message.id, index, action.language);
        break;
      case 'send_file':
        sends += await applySendFile(env, deps, contact, message.id, index, action);
        break;
      case 'link_start':
        sends += await applyLinkStart(env, deps, contact, message.id, index, action);
        break;
      case 'link_merge':
        await applyLinkMerge(env, deps, contact, action.phoneContactId);
        break;
      case 'admin_review':
        sends += await applyAdminReview(env, deps, contact, message.id, index, action.reviewId, action.decision);
        break;
      // ---- TA-I1: skipper registration, consent and crew ----
      case 'boat_create':
        await applyBoatCreate(env, deps, contact, action.boat);
        break;
      case 'flow_set':
        await applyFlowSet(env, deps, contact, action.state);
        break;
      case 'consent':
        await applyConsent(env, deps, contact, message, action.boatId, action.decision);
        break;
      case 'post_revoke':
        // 05 § Consent: every draft or approved post of the boat is rejected; posted ones stay.
        if (await ownsBoat(db, contact.id, action.boatId)) advisorLog('info', 'advisor_post_revoke', {rejected: await revokeBoatPosts(db, action.boatId, clock(deps))});
        break;
      case 'crew_add':
        sends += await applyCrewAdd(env, deps, contact, message.id, index, action);
        break;
      case 'crew_remove':
        await applyCrewRemove(env, deps, contact, action.boatId, action.contactId);
        break;
      case 'crew_accept':
        sends += await applyCrewAccept(env, deps, contact, message.id, index, action);
        break;
      case 'crew_decline':
        sends += await applyCrewDecline(env, deps, contact, message.id, index, action);
        break;
      // ---- TA-I2: reports, the media queue, auto-publish ----
      case 'report_draft':
        if (ID.test(String(action.report?.id)) && ID.test(String(action.report?.boat_id))) await insertDraft(db, contact, message.id, action.report, action.publish === true, clock(deps), String(index));
        break;
      case 'report_publish':
        if (ID.test(String(action.reportId))) await publishReport(db, contact, action.reportId, clock(deps));
        break;
      case 'report_withdraw':
        if (ID.test(String(action.reportId))) await withdrawReport(db, contact, action.reportId, clock(deps));
        break;
      case 'report_edit':
        if (ID.test(String(action.reportId)) && action.fields && typeof action.fields === 'object')
          await applyEdit(db, contact, message.id, String(index), action.reportId, action.fields, {reopen: action.reopen === true, publish: action.publish === true}, clock(deps));
        break;
      case 'auto_publish':
        if (await ownsBoat(db, contact.id, action.boatId)) await db.prepare('UPDATE advisor_boats SET auto_publish=?,updated_at=? WHERE id=?').bind(action.on ? 1 : 0, iso(deps), action.boatId).run();
        break;
      case 'media_queue':
        await applyMediaQueue(env, deps, contact, action.mediaId, action.hint);
        break;
      case 'post_draft':
        await applyPostDraft(env, deps, contact, action.mediaId, action.hint);
        break;
      case 'boat_instagram':
        if (/^[a-z0-9._]{1,30}$/.test(String(action.instagram)) && await ownsBoat(db, contact.id, action.boatId))
          await db.prepare('UPDATE advisor_boats SET instagram=?,updated_at=? WHERE id=? AND instagram IS NULL').bind(action.instagram, iso(deps), action.boatId).run();
        break;
      case 'mark_once':
        if (/^[a-z]{1,20}\.[\w-]{1,64}$/.test(String(action.key)))
          // A re-said line (the weekly no-consent line) moves its time; the others are only marked when not yet said.
          await db.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET updated_at=excluded.updated_at').bind(ONCE_PREFIX + action.key, '1', iso(deps)).run();
        break;
      // ---- TA-I3: angler photos (AC-1) ----
      case 'share_state':
        await applyShareState(env, deps, contact, action.state);
        break;
      case 'angler_share':
        await applyAnglerShare(env, contact, action.mediaId, action.credit);
        break;
      // ---- TA-S6: an Instagram comment's answer (09 § Inbox) ----
      case 'comment_reply':
        sends += await applyCommentReply(env, deps, contact, message, action);
        break;
      default:
        advisorLog('warn', 'advisor_action_unknown', {index, type: String((action as {type?: unknown})?.type).slice(0, 40)});
    }
  }
  return sends;
}

// ---- TA-E1: appliers for the engine's actions -------------------------------------

const LANGS = new Set(['en', 'es']);
const lang = (value: string): 'en' | 'es' => LANGS.has(value) ? value as 'en' | 'es' : 'en';

/** "Send me my data": the export JSON to R2 (advisor/exports/<id>/<local date>.json) and a signed 24 h link by text. */
async function applyExport(env: Env, deps: ConsumerDeps, contact: AdvisorContactRow, inId: string, index: number, language: string): Promise<number> {
  const l = lang(language);
  if (!env.ADVISOR_MEDIA || !env.ADVISOR_PHONE_KEY) return sendText(env, deps, contact, inId, index, t(l, 'export_unavailable'));
  const data = await exportContact(env.DB!, contact.id);
  if (!data) return 0;
  const key = exportKey(contact.id, localClock(clock(deps)).date);
  await env.ADVISOR_MEDIA.put(key, JSON.stringify({exported_at: iso(deps), ...data}, null, 2), {httpMetadata: {contentType: 'application/json'}});
  const token = await mintExportToken(await deriveKeys(env.ADVISOR_PHONE_KEY), contact.id, key, clock(deps));
  return sendText(env, deps, contact, inId, index, t(l, 'export_ready', {link: `${advisorSettings(env).publicBase}/api/advisor/export/${token}`}));
}

/** A file: attached on BlueBubbles (inline bytes, or an R2 object), otherwise its caption and fallback link as text. */
async function applySendFile(env: Env, deps: ConsumerDeps, contact: AdvisorContactRow, inId: string, index: number, action: Extract<Action, {type: 'send_file'}>): Promise<number> {
  const adapter = channelOf(env, deps, contact);
  const caption = typeof action.caption === 'string' ? action.caption : '';
  if (adapter?.name === 'bluebubbles' && !await relayHold(env, adapter)) {
    if (action.inlineBytes && /^[A-Za-z0-9+/=]{1,200000}$/.test(action.inlineBytes)) {
      return Number(await sendOnce(env, deps, contact, inId, index, {text: caption || undefined, files: [{name: String(action.name).slice(0, 80), mime: String(action.mime).slice(0, 80), base64: action.inlineBytes}]}));
    }
    if (action.r2Key) return Number(await sendOnce(env, deps, contact, inId, index, {text: caption || undefined, mediaKeys: [action.r2Key]}));
  }
  const text = [caption, action.fallbackUrl].filter(Boolean).join(' ');
  return text ? sendText(env, deps, contact, inId, index, text) : 0;
}

/**
 * The web phone link, step 1 (03 § web): the phone contact found or created by
 * hash (an existing one keeps its channel), the pending code stored as its
 * SHA-256 in job_state advisor.link.<web contact id>, and the code texted to
 * the number through its own channel (never the web collector). The outbound
 * row stores the text without the code.
 */
async function applyLinkStart(env: Env, deps: ConsumerDeps, web: AdvisorContactRow, inId: string, index: number, action: Extract<Action, {type: 'link_start'}>): Promise<number> {
  const db = env.DB!, at = iso(deps);
  if (!/^[0-9a-f]{64}$/.test(action.phoneHash) || !/^[0-9a-f]{64}$/.test(action.codeHash) || !/^\d{6}$/.test(action.codeText)) return 0;
  // A new phone contact's last channel is 'web' (where it came from), so BlueBubbles checks iMessage availability for the code text.
  const phone = await db.prepare(`INSERT INTO advisor_contacts(id,phone_hash,phone_enc,channel,language,source,last_seen_at,created_at,updated_at) VALUES(?,?,?,'web',?,'web',?,?,?)
    ON CONFLICT(phone_hash) DO UPDATE SET updated_at=advisor_contacts.updated_at RETURNING *`)
    .bind(randomId(), action.phoneHash, action.phoneEnc, web.language, at, at, at).first<AdvisorContactRow>();
  if (!phone || phone.status !== 'active') return sendText(env, deps, web, inId, index, t(web.language, 'link_failed'));
  await db.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at')
    .bind(linkKey(web.id), JSON.stringify({code_hash: action.codeHash, expires_at: action.expiresAt, phone_contact_hash: action.phoneHash, phone_contact_id: phone.id}), at).run();
  const adapter = (deps.channelFor ?? defaultChannelFor)(env, phone);
  if (await relayHold(env, adapter)) return sendText(env, deps, web, inId, `${index}.failed`, t(web.language, 'link_failed'));
  const id = await outboundId(inId, `${index}.code`);
  const inserted = await db.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,body,status,in_reply_to,created_at) VALUES(?,?,'out',?,?,'sending',?,?) ON CONFLICT(id) DO NOTHING`)
    .bind(id, phone.id, phone.channel, t(phone.language, 'link_code_text', {code: '······'}), inId, at).run();
  if (!inserted.meta.changes) return 0;
  const result = await deliver(env, phone, adapter, {id, text: t(phone.language, 'link_code_text', {code: action.codeText})});
  if (await recordResult(db, deps, id, result)) return 1;
  return sendText(env, deps, web, inId, `${index}.failed`, t(web.language, 'link_failed'));
}

/**
 * The web phone link, step 2: the web contact's messages, media and reviews
 * move to the phone contact, its session cookie moves too (so the web chat
 * keeps talking as the phone contact), and the web contact is deleted.
 */
async function applyLinkMerge(env: Env, deps: ConsumerDeps, web: AdvisorContactRow, phoneContactId: string): Promise<void> {
  const db = env.DB!, at = iso(deps);
  if (!ID.test(phoneContactId) || phoneContactId === web.id || web.phone_enc) return;
  const phone = await db.prepare('SELECT id,web_session FROM advisor_contacts WHERE id=?').bind(phoneContactId).first<{id: string; web_session: string | null}>();
  if (!phone) return;
  await db.batch([
    db.prepare('UPDATE advisor_messages SET contact_id=? WHERE contact_id=?').bind(phone.id, web.id),
    db.prepare('UPDATE advisor_media SET contact_id=? WHERE contact_id=?').bind(phone.id, web.id),
    db.prepare('UPDATE advisor_reviews SET ref_id=? WHERE ref_id=?').bind(phone.id, web.id),
    db.prepare('UPDATE advisor_contacts SET web_session=NULL WHERE id=?').bind(web.id),
    db.prepare('UPDATE advisor_contacts SET web_session=?,updated_at=? WHERE id=? AND web_session IS NULL').bind(web.web_session, at, phone.id),
    db.prepare('DELETE FROM advisor_contacts WHERE id=?').bind(web.id),
    db.prepare('DELETE FROM job_state WHERE key=?').bind(linkKey(web.id)),
  ]);
  advisorLog('info', 'advisor_web_linked', {count: 1});
}

/**
 * The text admin fallback (08): the engine already checked the contact; this
 * re-checks it and applies the decision to one open skipper or media review
 * through the decision code the admin queue uses (admin/decisions.ts, TA-W2):
 * skipper/new_skipper verifies (or rejects) the boat and texts its owner;
 * media sets publish_state. The decider is a contact, so verified_by and
 * decided_by stay null and the review's note is 'text admin'.
 */
async function applyAdminReview(env: Env, deps: ConsumerDeps, contact: AdvisorContactRow, inId: string, index: number, id: string, decision: string): Promise<number> {
  const settings = advisorSettings(env);
  if (contact.id !== settings.adminContactId || contact.role !== 'admin-test' || !/^[0-9a-f]{32}$/.test(id) || !['approved', 'rejected'].includes(decision)) return 0;
  const outcome = await decideReview(env, {reviewId: id, decision: decision === 'approved' ? 'approve' : 'reject', note: 'text admin', by: null, kinds: ['skipper', 'media'], inId, key: String(index)},
    {now: clock(deps), send: teamSender(env, deps), ...(deps.dispatchWorkflow ? {dispatch: deps.dispatchWorkflow} : {}), ...(deps.engine?.fetcher ? {fetcher: deps.engine.fetcher} : {})});
  if (outcome.status !== 'applied') return 0;
  advisorLog('info', 'advisor_text_admin', {kind: outcome.review.kind, decision});
  return outcome.sends;
}

/**
 * TA-W2: how a decision texts someone (the skipper's verification, "reply as
 * team"): through the contact's own channel, at most once per (inId, key),
 * held while the relay is down, with created_by set to the admin's users.id
 * when an admin sent it from the queue. Shared by the text admin and the
 * admin queue (server/routes/admin.ts).
 */
export function teamSender(env: Env, deps: ConsumerDeps = {}): TeamSend {
  return (contact, inId, key, text, createdBy) => sendText(env, deps, contact, inId, key, text, (deps.channelFor ?? defaultChannelFor)(env, contact), createdBy);
}

// ---- TA-I1: skipper registration, consent and crew (05) ---------------------------------

const SLUG_RE = /^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$/;
const ownsBoat = async (db: D1Database, contactId: string, boatId: string): Promise<boolean> =>
  ID.test(String(boatId)) && Boolean(await db.prepare('SELECT 1 AS x FROM advisor_boats WHERE id=? AND owner_contact_id=?').bind(boatId, contactId).first());

/**
 * boat.create (05 § Becoming a skipper): the boat row with status 'pending',
 * the contact its owner and skipper (an admin-test contact keeps its role, so
 * the owner can try registration from the admin phone), and the contact's home
 * port when it has none (FC-2). Idempotent on the boat id; a slug taken in a
 * race throws, and the retried turn picks the next free one.
 */
async function applyBoatCreate(env: Env, deps: ConsumerDeps, contact: AdvisorContactRow, boat: Extract<Action, {type: 'boat_create'}>['boat']): Promise<void> {
  const db = env.DB!, at = iso(deps);
  if (!ID.test(String(boat?.id)) || !SLUG_RE.test(String(boat.slug)) || typeof boat.name !== 'string' || !boat.name.trim() || boat.name.length > 60
    || !ID.test(String(boat.port)) || !ID.test(String(boat.region))) { advisorLog('warn', 'advisor_boat_rejected', {}); return; }
  if (await db.prepare('SELECT 1 AS x FROM advisor_boats WHERE owner_contact_id=? AND id<>?').bind(contact.id, boat.id).first()) { advisorLog('warn', 'advisor_boat_duplicate_owner', {}); return; }
  const text = (v: string | null, max: number) => typeof v === 'string' && v.length <= max ? v : null;
  await db.batch([
    db.prepare(`INSERT INTO advisor_boats(id,slug,name,landing,port,region,instagram,booking_url,phone_public,owner_contact_id,status,created_at,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,'pending',?,?) ON CONFLICT(id) DO NOTHING`)
      .bind(boat.id, boat.slug, boat.name.trim(), text(boat.landing, 60), boat.port, boat.region, text(boat.instagram, 30),
        boat.booking_url && /^https:\/\//.test(boat.booking_url) ? text(boat.booking_url, 300) : null, text(boat.phone_public, 16), contact.id, at, at),
    // A crew member who registers a boat of their own leaves the crew (05 § Crew: one boat per contact), and a pending invitation goes.
    db.prepare('UPDATE advisor_crew SET removed_at=? WHERE contact_id=? AND removed_at IS NULL').bind(at, contact.id),
    db.prepare('DELETE FROM job_state WHERE key=?').bind(crewInviteKey(contact.id)),
    db.prepare(`UPDATE advisor_contacts SET role=CASE WHEN role='admin-test' THEN role ELSE 'skipper' END,boat_id=?,home_port=COALESCE(home_port,?),updated_at=? WHERE id=?`)
      .bind(boat.id, boat.port, at, contact.id),
  ]);
  contact.boat_id = boat.id;
  if (contact.role !== 'admin-test') contact.role = 'skipper';
  advisorLog('info', 'advisor_boat_created', {port: boat.port});
}

/** job_state advisor.flow.<contact_id>: the skipper flow's pending question (intake/skippers.ts), or deleted. */
async function applyFlowSet(env: Env, deps: ConsumerDeps, contact: AdvisorContactRow, state: Extract<Action, {type: 'flow_set'}>['state']): Promise<void> {
  const db = env.DB!;
  if (state === null) { await db.prepare('DELETE FROM job_state WHERE key=?').bind(flowKey(contact.id)).run(); return; }
  if (!state || !['register', 'consent'].includes(state.flow)) return;
  const value = JSON.stringify(state);
  if (value.length > 4000) return;
  await db.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at')
    .bind(flowKey(contact.id), value, iso(deps)).run();
}

/**
 * Photo consent (05 § Consent, SK-2), only from the boat's owner: yes records
 * consent_photos_at and the message that said it (and clears an earlier
 * revocation); revoke sets consent_revoked_at and keeps the original consent
 * for the record.
 */
async function applyConsent(env: Env, deps: ConsumerDeps, contact: AdvisorContactRow, message: AdvisorMessageRow, boatId: string, decision: string): Promise<void> {
  const db = env.DB!, at = iso(deps);
  if (!await ownsBoat(db, contact.id, boatId)) return;
  if (decision === 'yes') await db.prepare('UPDATE advisor_boats SET consent_photos_at=?,consent_message_id=?,consent_revoked_at=NULL,updated_at=? WHERE id=?').bind(at, message.id, at, boatId).run();
  else if (decision === 'revoke') await db.prepare('UPDATE advisor_boats SET consent_revoked_at=?,updated_at=? WHERE id=?').bind(at, at, boatId).run();
  else return;
  advisorLog('info', 'advisor_consent', {decision});
}

/**
 * add_crew (05 § Crew, SK-3; hardening): an invitation, not a link. Only the
 * owner of a verified boat. The contact by phone hash (an existing one keeps
 * its channel, language and history; a new one starts as an SMS contact in the
 * skipper's language with source 'skipper-invite'); nothing is invited when it
 * is stopped or blocked, owns a boat, is already crew on this boat or said NO
 * to this boat in the last 30 days. Otherwise the pending invitation is
 * written (job_state advisor.crewinvite.<id>, 72 h; a newer one replaces it)
 * and texted through the contact's own channel. Its role, boat_id and any crew
 * link to another boat are untouched until crew_accept.
 */
async function applyCrewAdd(env: Env, deps: ConsumerDeps, skipper: AdvisorContactRow, inId: string, index: number, action: Extract<Action, {type: 'crew_add'}>): Promise<number> {
  const db = env.DB!, at = iso(deps), now = clock(deps);
  if (!/^[0-9a-f]{64}$/.test(action.phoneHash) || typeof action.phoneEnc !== 'string' || !action.phoneEnc || !await ownsBoat(db, skipper.id, action.boatId)) return 0;
  const boat = await db.prepare('SELECT name,status FROM advisor_boats WHERE id=?').bind(action.boatId).first<{name: string; status: string}>();
  if (!boat || !isVerified(boat.status)) return 0;
  const invite = await outboundId(inId, `${index}.invite`);
  // A retried message finds its invitation already handled (sendOnce skips a sent row).
  const retry = Boolean(await db.prepare('SELECT 1 AS x FROM advisor_messages WHERE id=?').bind(invite).first());
  const crew = await db.prepare(`INSERT INTO advisor_contacts(id,phone_hash,phone_enc,channel,language,source,last_seen_at,created_at,updated_at) VALUES(?,?,?,'sms',?,'skipper-invite',?,?,?)
    ON CONFLICT(phone_hash) DO UPDATE SET updated_at=advisor_contacts.updated_at RETURNING *`)
    .bind(randomId(), action.phoneHash, action.phoneEnc, lang(skipper.language), at, at, at).first<AdvisorContactRow>();
  if (!crew || crew.id === skipper.id || crew.status !== 'active') return 0;
  if (await db.prepare('SELECT 1 AS x FROM advisor_boats WHERE owner_contact_id=?').bind(crew.id).first()) return 0;
  if (await db.prepare('SELECT 1 AS x FROM advisor_crew WHERE boat_id=? AND contact_id=? AND removed_at IS NULL').bind(action.boatId, crew.id).first()) return 0;
  if (await crewDeclined(db, action.boatId, crew.id, now)) { advisorLog('info', 'advisor_crew_invite_suppressed', {count: 1}); return 0; }
  if (!retry) {
    const pending: CrewInvite = {boat_id: action.boatId, added_by: skipper.id, invited_at: at, expires_at: now + CREW_INVITE_TTL_MS};
    await db.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at')
      .bind(crewInviteKey(crew.id), JSON.stringify(pending), at).run();
  }
  const l = lang(crew.language);
  const text = t(l, 'crew_invite', {skipper: skipper.display_name || t(l, 'crew_invite_skipper'), boat: boat.name});
  advisorLog('info', 'advisor_crew_invited', {count: 1});
  return sendText(env, deps, crew, inId, `${index}.invite`, text, (deps.channelFor ?? defaultChannelFor)(env, crew));
}

/**
 * crew_accept (the invitee's YES within 72 h): the invitation must still be
 * pending for this boat, the boat still verified with an owner, the contact
 * still own no boat, and the boat under MAX_CREW. Then any other crew link
 * ends, advisor_crew is upserted with the inviter as added_by, the contact
 * becomes crew on the boat, and the invitation goes. The outcome is texted.
 */
async function applyCrewAccept(env: Env, deps: ConsumerDeps, contact: AdvisorContactRow, inId: string, index: number, action: Extract<Action, {type: 'crew_accept'}>): Promise<number> {
  const db = env.DB!, at = iso(deps), now = clock(deps), l = lang(action.language ?? contact.language);
  if (!ID.test(String(action.boatId))) return 0;
  const invite = await readCrewInvite(db, contact.id);
  const boat = await db.prepare('SELECT name,status,owner_contact_id FROM advisor_boats WHERE id=?').bind(action.boatId).first<{name: string; status: string; owner_contact_id: string | null}>();
  const crewCount = await db.prepare('SELECT COUNT(*) AS n FROM advisor_crew WHERE boat_id=? AND removed_at IS NULL AND contact_id<>?').bind(action.boatId, contact.id).first<{n: number}>();
  const ownsOne = await db.prepare('SELECT 1 AS x FROM advisor_boats WHERE owner_contact_id=?').bind(contact.id).first();
  if (!invite || invite.boat_id !== action.boatId || !(invite.expires_at > now) || !boat || !isVerified(boat.status) || !boat.owner_contact_id
    || ownsOne || (crewCount?.n ?? 0) >= MAX_CREW || contact.status !== 'active') {
    await db.prepare('DELETE FROM job_state WHERE key=?').bind(crewInviteKey(contact.id)).run();
    return sendText(env, deps, contact, inId, index, t(l, 'crew_invite_expired'));
  }
  await db.batch([
    db.prepare('UPDATE advisor_crew SET removed_at=? WHERE contact_id=? AND boat_id<>? AND removed_at IS NULL').bind(at, contact.id, action.boatId),
    db.prepare(`INSERT INTO advisor_crew(boat_id,contact_id,added_by,added_at) VALUES(?,?,?,?)
      ON CONFLICT(boat_id,contact_id) DO UPDATE SET added_by=excluded.added_by,added_at=excluded.added_at,removed_at=NULL`).bind(action.boatId, contact.id, invite.added_by, at),
    db.prepare(`UPDATE advisor_contacts SET role=CASE WHEN role='admin-test' THEN role ELSE 'crew' END,boat_id=?,updated_at=? WHERE id=?`).bind(action.boatId, at, contact.id),
    db.prepare('DELETE FROM job_state WHERE key=? OR key=?').bind(crewInviteKey(contact.id), crewDeclineKey(action.boatId, contact.id)),
  ]);
  contact.boat_id = action.boatId;
  if (contact.role !== 'admin-test') contact.role = 'crew';
  advisorLog('info', 'advisor_crew_added', {count: 1});
  return sendText(env, deps, contact, inId, index, t(l, 'crew_joined', {boat: boat.name}));
}

/** crew_decline: NO clears the invitation and silences that boat's invitations for 30 days; an expired one is only cleared. */
async function applyCrewDecline(env: Env, deps: ConsumerDeps, contact: AdvisorContactRow, inId: string, index: number, action: Extract<Action, {type: 'crew_decline'}>): Promise<number> {
  const db = env.DB!, at = iso(deps);
  if (!ID.test(String(action.boatId))) return 0;
  const invite = await readCrewInvite(db, contact.id);
  if (!invite || invite.boat_id !== action.boatId) return 0;
  if (action.expired) { await db.prepare('DELETE FROM job_state WHERE key=?').bind(crewInviteKey(contact.id)).run(); return 0; }
  const boat = await db.prepare('SELECT name FROM advisor_boats WHERE id=?').bind(action.boatId).first<{name: string}>();
  await db.batch([
    db.prepare('DELETE FROM job_state WHERE key=?').bind(crewInviteKey(contact.id)),
    db.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at')
      .bind(crewDeclineKey(action.boatId, contact.id), '1', at),
  ]);
  advisorLog('info', 'advisor_crew_declined', {count: 1});
  return sendText(env, deps, contact, inId, index, t(lang(action.language ?? contact.language), 'crew_declined', {boat: boat?.name ?? ''}));
}

/** remove_crew (05 § Crew): removed_at on the crew row (kept for audit); the contact loses the boat and is an angler again. */
async function applyCrewRemove(env: Env, deps: ConsumerDeps, skipper: AdvisorContactRow, boatId: string, contactId: string): Promise<void> {
  const db = env.DB!, at = iso(deps);
  if (!ID.test(String(contactId)) || !await ownsBoat(db, skipper.id, boatId)) return;
  await db.batch([
    db.prepare('UPDATE advisor_crew SET removed_at=? WHERE boat_id=? AND contact_id=? AND removed_at IS NULL').bind(at, boatId, contactId),
    db.prepare(`UPDATE advisor_contacts SET boat_id=NULL,role=CASE WHEN role='crew' THEN 'angler' ELSE role END,updated_at=? WHERE id=? AND boat_id=?`).bind(at, contactId, boatId),
  ]);
  advisorLog('info', 'advisor_crew_removed', {count: 1});
}

/**
 * TA-I2 (05 § catch and action photos): a skipper's or crew's photo, video or
 * count board goes to the feed queue (publish_state 'queued', credited to the
 * boat); TA-S1 adds the post draft. Only the contact's own media, only for a
 * boat it posts for and whose photo consent is active, only from 'private'.
 */
async function applyMediaQueue(env: Env, deps: ConsumerDeps, contact: AdvisorContactRow, mediaId: string, hint?: string): Promise<void> {
  const db = env.DB!;
  if (!ID.test(String(mediaId))) return;
  // A retry finds the photo already queued: the draft below is still made if the first try stopped before it.
  const media = await db.prepare("SELECT boat_id,publish_state FROM advisor_media WHERE id=? AND contact_id=? AND publish_state IN ('private','queued')").bind(mediaId, contact.id).first<{boat_id: string | null; publish_state: string}>();
  if (!media?.boat_id || !await postsFor(db, contact.id, media.boat_id)) return;
  const boat = await db.prepare('SELECT name,consent_photos_at,consent_revoked_at FROM advisor_boats WHERE id=?').bind(media.boat_id).first<{name: string; consent_photos_at: string | null; consent_revoked_at: string | null}>();
  if (!boat?.consent_photos_at || (boat.consent_revoked_at && boat.consent_revoked_at >= boat.consent_photos_at)) return;
  if (media.publish_state === 'private') {
    const queued = await db.prepare("UPDATE advisor_media SET publish_state='queued',credit=? WHERE id=? AND publish_state='private'").bind(boat.name.slice(0, 80), mediaId).run();
    advisorLog('info', 'advisor_media_queued', {count: 1});
    // TA-M1: thumb.jpg for the admin queue, public.jpg and story.jpg for posting.
    if (queued.meta.changes) await requestMediaJob(env, clock(deps), deps.dispatchWorkflow ? {dispatch: deps.dispatchWorkflow} : {});
  }
  // TA-S1 (05 § catch photos, SC-3): the post draft and its review; has_person holds its approval, not the draft.
  await draftFor(env, deps, mediaId, hint);
}

/** ensureMediaDraft with the engine's Messages API fetcher (tests) and the hint, at most 200 characters. */
async function draftFor(env: Env, deps: ConsumerDeps, mediaId: string, hint?: string): Promise<void> {
  const clean = typeof hint === 'string' ? hint.replace(/[\u0000-\u001f\u007f]/g, ' ').trim().slice(0, 200) : '';
  const outcome = await ensureMediaDraft(env, mediaId, {now: clock(deps), ...(deps.engine?.fetcher ? {fetcher: deps.engine.fetcher} : {}), ...(clean ? {hint: clean} : {})});
  if (outcome.status === 'skipped') advisorLog('info', 'advisor_post_draft_skipped', {reason: outcome.reason});
}

/**
 * TA-S1 (propose_post): the draft of a photo or video already in the feed
 * queue, for a contact who posts for its boat. ensureMediaDraft re-checks the
 * boat's consent.
 */
async function applyPostDraft(env: Env, deps: ConsumerDeps, contact: AdvisorContactRow, mediaId: string, hint?: string): Promise<void> {
  const db = env.DB!;
  if (!ID.test(String(mediaId))) return;
  const media = await db.prepare("SELECT boat_id FROM advisor_media WHERE id=? AND contact_id=? AND publish_state IN ('queued','approved')").bind(mediaId, contact.id).first<{boat_id: string | null}>();
  if (!media?.boat_id || !await postsFor(db, contact.id, media.boat_id)) return;
  await draftFor(env, deps, mediaId, hint);
}

/**
 * TA-I3 (06 § Angler photos): the AC-1 offer state, job_state
 * advisor.share.<contact_id>; null deletes it. Only for the contact's own
 * media.
 */
async function applyShareState(env: Env, deps: ConsumerDeps, contact: AdvisorContactRow, state: Extract<Action, {type: 'share_state'}>['state']): Promise<void> {
  const db = env.DB!;
  if (state === null) { await db.prepare('DELETE FROM job_state WHERE key=?').bind(shareKey(contact.id)).run(); return; }
  if (!state || (state.step !== 'offered' && state.step !== 'credit') || !ID.test(String(state.media_id))) return;
  if (!await db.prepare('SELECT 1 AS x FROM advisor_media WHERE id=? AND contact_id=?').bind(state.media_id, contact.id).first()) return;
  const value = JSON.stringify({step: state.step, media_id: state.media_id, asked_at: String(state.asked_at), ...(state.id_offered ? {id_offered: true} : {})});
  await db.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at')
    .bind(shareKey(contact.id), value, iso(deps)).run();
}

/**
 * TA-I3 (06 § Angler photos, AC-1): an angler's yes. Their own photo (no boat)
 * goes from 'private' to 'queued' for the team's review; a credit (a name or
 * 'anonymous', at most 40 characters) is stored on advisor_media.credit, also
 * on a photo already queued (the credit reply comes a text later). The
 * angler_photo review is a separate review_open action.
 */
async function applyAnglerShare(env: Env, contact: AdvisorContactRow, mediaId: string, credit: string | null | undefined): Promise<void> {
  const db = env.DB!;
  if (!ID.test(String(mediaId))) return;
  const clean = typeof credit === 'string' ? credit.replace(/\s+/g, ' ').trim().slice(0, CREDIT_MAX) : '';
  const r = await db.prepare(`UPDATE advisor_media SET publish_state=CASE WHEN publish_state='private' THEN 'queued' ELSE publish_state END${clean ? ',credit=?' : ''}
    WHERE id=? AND contact_id=? AND boat_id IS NULL AND publish_state IN ('private','queued')`).bind(...(clean ? [clean] : []), mediaId, contact.id).run();
  if (r.meta.changes) advisorLog('info', 'advisor_angler_photo_queued', {credit: clean ? (clean === 'anonymous' ? 'anonymous' : 'name') : 'none'});
}

/**
 * TA-S6 (09 § Inbox): the answer to an Instagram comment, only on a comment's
 * own inbound row. The outbound key is fixed per mode ('comment:private',
 * 'comment:public'), so with the inbound row unique per comment id there is at
 * most one private reply per comment however often the turn is retried, as
 * Meta allows; the channel itself refuses a second send in the same turn.
 */
async function applyCommentReply(env: Env, deps: ConsumerDeps, contact: AdvisorContactRow, message: AdvisorMessageRow, action: Extract<Action, {type: 'comment_reply'}>): Promise<number> {
  if (message.channel !== 'instagram_comment' || !message.provider_id || (action.mode !== 'private' && action.mode !== 'public') || typeof action.text !== 'string' || !action.text.trim()) return 0;
  const channel = commentChannel(env, {providerId: message.provider_id, receivedAt: message.created_at}, action.mode, deps.instagram ?? {});
  return Number(await sendOnce(env, deps, contact, message.id, `comment:${action.mode}`, {text: action.text}, channel));
}

/**
 * Text the owner's admin-test contact (ADVISOR_ADMIN_CONTACT_ID) about a new
 * skipper or media review, with the 6-character code `ok`/`no` takes (08).
 * Returns true when a text was sent. Nothing for other kinds, without the
 * setting, or when that contact is not an active admin-test contact.
 */
export async function notifyAdmin(env: Env, review: {id: string; kind: string; reason: string}, deps: ConsumerDeps = {}, inId = review.id): Promise<boolean> {
  const settings = advisorSettings(env);
  if (!env.DB || !settings.adminContactId || !['skipper', 'media'].includes(review.kind)) return false;
  const admin = await env.DB.prepare("SELECT * FROM advisor_contacts WHERE id=? AND role='admin-test' AND status='active'").bind(settings.adminContactId).first<AdvisorContactRow>();
  if (!admin) return false;
  const code = review.id.slice(0, 6);
  const text = t(admin.language, 'admin_notify', {kind: review.kind, reason: review.reason, code});
  return sendOnce(env, deps, admin, inId, `notify:${review.id}`, {text}, (deps.channelFor ?? defaultChannelFor)(env, admin));
}

const TIMED_OUT = Symbol('timed out');
/** Run the handler under the hard stop: the signal aborts and the race resolves TIMED_OUT after `ms`. */
async function underHardStop(run: (signal: AbortSignal) => Promise<EngineResult>, ms: number): Promise<EngineResult | typeof TIMED_OUT> {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const stop = new Promise<typeof TIMED_OUT>(resolve => { timer = setTimeout(() => { controller.abort(Error('advisor turn timed out')); resolve(TIMED_OUT); }, ms); });
  try { return await Promise.race([run(controller.signal), stop]); } finally { if (timer !== undefined) clearTimeout(timer); }
}

function turn(env: Env, started: number, deps: ConsumerDeps, message: QueueMessage, intent: string, outcome: string, actions = 0, sends = 0): void {
  recordAdvisorTurn(env, {intent, outcome, ms: clock(deps) - started, actions, sends, retries: Math.max(0, (message.attempts ?? 1) - 1)});
}

async function consumeOne(message: QueueMessage, env: Env, deps: ConsumerDeps, out: AdvisorConsumeResult): Promise<void> {
  const db = env.DB!, started = clock(deps), id = message.body?.message_id;
  if (typeof id !== 'string' || !ID.test(id)) { out.invalid++; message.ack(); return; }
  const row = await inbound(db, id);
  if (!row || !['queued', 'processing'].includes(row.status)) { out.invalid++; message.ack(); return; }
  if (!advisorSettings(env).repliesEnabled) {
    // The soft switch (04 stage 0): stored and acked, nothing sent, no model call.
    await setStatus(db, id, 'held', ['queued', 'processing']);
    out.held++; message.ack(); turn(env, started, deps, message, 'held', 'held'); return;
  }
  await setStatus(db, id, 'processing', ['queued', 'processing']);
  const contact = await db.prepare('SELECT * FROM advisor_contacts WHERE id=?').bind(row.contact_id).first<AdvisorContactRow>();
  if (!contact) { await setStatus(db, id, 'dropped', ['processing'], 'no-contact'); out.dropped++; message.ack(); return; }

  // TA-C4: download, strip and store the message's media before the handler sees it.
  let mediaError: string | null = null;
  if (row.media_json) {
    const media = await ingestInboundMedia(env, row, deps.fetchMediaByRef ?? adapterFetchMediaByRef,
      {attempt: message.attempts ?? 1, retries: deps.mediaRetries ?? MEDIA_RETRIES, now: clock(deps)});
    if (media.retry) {
      await setStatus(db, id, 'queued', ['processing'], 'media-fetch');
      message.retry({delaySeconds: Math.min(300, 20 * Math.max(1, message.attempts ?? 1))});
      out.retried++; turn(env, started, deps, message, 'media', 'retried'); return;
    }
    mediaError = media.error;
    // TA-M1: a photo vision cannot read as stored waits for the media job's public.jpg.
    if ((message.attempts ?? 1) <= (deps.derivedWaits ?? DERIVED_WAITS) && env.GITHUB_TOKEN && await awaitingDerived(db, row.media_json)) {
      const job = await requestMediaJob(env, clock(deps), deps.dispatchWorkflow ? {dispatch: deps.dispatchWorkflow} : {});
      await setStatus(db, id, 'queued', ['processing'], 'media-derive');
      advisorLog('info', 'advisor_media_wait_derived', {attempt: message.attempts ?? 1, job});
      message.retry({delaySeconds: DERIVED_RETRY_SECONDS});
      out.retried++; turn(env, started, deps, message, 'media', 'waiting'); return;
    }
  }

  const handler = deps.handler ?? warmUpHandler;
  let result: EngineResult | typeof TIMED_OUT;
  try {
    result = await underHardStop(signal => handler({env, contact, message: row, now: clock(deps), deps, signal}), deps.turnTimeoutMs ?? TURN_TIMEOUT_MS);
  } catch (error) {
    const why = reason(error);
    await setStatus(db, id, 'queued', ['processing'], why);
    advisorLog('error', 'advisor_turn_failed', {attempt: message.attempts, reason: why});
    message.retry({delaySeconds: Math.min(300, 20 * Math.max(1, message.attempts ?? 1))});
    out.retried++; turn(env, started, deps, message, 'error', 'retried'); return;
  }
  if (result === TIMED_OUT) {
    if ((message.attempts ?? 1) <= 1) {
      // First attempt over the hard stop: tell the person, retry once (01 § request flow).
      await setStatus(db, id, 'queued', ['processing'], 'timeout');
      if (contact.status === 'active') out.sends += Number(await sendOnce(env, deps, contact, id, 'still-working', {text: t(contact.language, 'still_working')}));
      advisorLog('warn', 'advisor_turn_timeout', {attempt: message.attempts});
      message.retry({delaySeconds: TIMEOUT_RETRY_SECONDS});
      out.retried++; turn(env, started, deps, message, 'timeout', 'timeout'); return;
    }
    // The one retry also ran out of time: give up as the dead-letter path would.
    await setStatus(db, id, 'failed', ['processing'], 'timeout');
    out.sends += Number(await apologise(env, deps, contact, id));
    advisorLog('error', 'advisor_turn_timeout', {attempt: message.attempts, final: true});
    message.ack(); out.failed++; turn(env, started, deps, message, 'timeout', 'failed'); return;
  }
  const actions = Array.isArray(result?.actions) ? result.actions : [];
  const intent = typeof result?.intent === 'string' && CODE.test(result.intent) ? result.intent : 'unknown';
  let sends: number;
  try { sends = await applyActions(env, deps, contact, row, actions); }
  catch (error) {
    // Partway through: every applied action is idempotent, so the retry resumes safely.
    const why = reason(error);
    await setStatus(db, id, 'queued', ['processing'], why);
    advisorLog('error', 'advisor_apply_failed', {attempt: message.attempts, reason: why});
    message.retry({delaySeconds: Math.min(300, 20 * Math.max(1, message.attempts ?? 1))});
    out.retried++; turn(env, started, deps, message, intent, 'retried', actions.length); return;
  }
  const usage = result.usage ?? {};
  await db.prepare("UPDATE advisor_messages SET status='done',intent=?,error=?,tokens_in=?,tokens_out=? WHERE id=?")
    .bind(intent, mediaError, usage.input_tokens ?? null, usage.output_tokens ?? null, id).run();   // TA-C4: mediaError, else NULL
  message.ack();
  out.done++; out.sends += sends;
  turn(env, started, deps, message, intent, 'done', actions.length, sends);
}

/**
 * Queue consumer for ADVISOR_QUEUE. Acks a message that is malformed, already
 * handled or whose row is gone; retries one whose handler threw (backoff
 * 20 s x attempts, at most 300 s). With TEXT_ADVISOR_ENABLED off it acks every
 * message and marks the stored row dropped; without D1 it acks and logs (there
 * is nothing to process against).
 */
export async function consumeAdvisor(batch: MessageBatch<AdvisorMessage>, env: Env, deps: ConsumerDeps = {}): Promise<AdvisorConsumeResult> {
  const out: AdvisorConsumeResult = {messages: batch.messages.length, done: 0, held: 0, dropped: 0, retried: 0, invalid: 0, failed: 0, sends: 0};
  if (!env.DB) { advisorLog('error', 'advisor_no_db', {messages: batch.messages.length}); batch.ackAll(); out.dropped = out.messages; return out; }
  if (!advisorSettings(env).enabled) {
    for (const message of batch.messages) {
      const id = message.body?.message_id;
      if (typeof id === 'string' && ID.test(id)) await setStatus(env.DB, id, 'dropped', ['queued', 'processing'], 'disabled').catch(() => false);
      message.ack();
    }
    out.dropped = out.messages;
    return out;
  }
  for (const message of batch.messages) {
    try { await consumeOne(message, env, deps, out); }
    catch (error) {
      // D1 itself failed before the handler ran: retry the whole message.
      out.retried++;
      advisorLog('error', 'advisor_consume_failed', {attempt: message.attempts, reason: reason(error)});
      message.retry({delaySeconds: Math.min(300, 20 * Math.max(1, message.attempts ?? 1))});
    }
  }
  advisorLog('info', 'advisor_batch', {queue: batch.queue, ...out});
  return out;
}

/**
 * The apology text, at most once per contact per hour: claimed atomically on
 * advisor_contacts.last_error_notice_at, then sent through the same idempotent
 * outbound row (key 'error'). Never to a stopped or blocked contact, and not
 * while replies are switched off.
 */
async function apologise(env: Env, deps: ConsumerDeps, contact: AdvisorContactRow, inId: string): Promise<boolean> {
  const settings = advisorSettings(env);
  if (!settings.enabled || !settings.repliesEnabled || contact.status !== 'active') return false;
  const now = clock(deps);
  const claim = await env.DB!.prepare('UPDATE advisor_contacts SET last_error_notice_at=? WHERE id=? AND (last_error_notice_at IS NULL OR last_error_notice_at<=?)')
    .bind(new Date(now).toISOString(), contact.id, new Date(now - ERROR_NOTICE_MS).toISOString()).run();
  if (!claim.meta.changes) return false;
  return sendOnce(env, deps, contact, inId, 'error', {text: t(contact.language, 'apology')});
}

/**
 * Dead-letter consumer: a message lands here after max_retries failed turns.
 * Every message is acknowledged; its inbound row is marked failed and the
 * contact gets the apology (throttled hourly). Counts are logged, never ids.
 */
export async function consumeAdvisorDeadLetters(batch: MessageBatch<AdvisorMessage>, env: Env, deps: ConsumerDeps = {}): Promise<{dead: number; failed: number; apologies: number}> {
  let failed = 0, apologies = 0;
  if (env.DB) for (const message of batch.messages) {
    try {
      const id = message.body?.message_id;
      if (typeof id !== 'string' || !ID.test(id)) continue;
      const row = await inbound(env.DB, id);
      if (!row || !await setStatus(env.DB, id, 'failed', ['queued', 'processing'], row.error ?? 'dead-letter')) continue;
      failed++;
      const contact = await env.DB.prepare('SELECT * FROM advisor_contacts WHERE id=?').bind(row.contact_id).first<AdvisorContactRow>();
      if (contact && await apologise(env, deps, contact, id)) apologies++;
    } catch (error) { advisorLog('error', 'advisor_dead_letter_failed', {reason: reason(error)}); }
  }
  batch.ackAll();
  advisorLog('error', 'advisor_dead_letter', {queue: batch.queue, messages: batch.messages.length, failed, apologies});
  return {dead: batch.messages.length, failed, apologies};
}

/**
 * For deployments without ADVISOR_QUEUE (local dev, ENABLE_ADVISOR off): run
 * one stored message through the consumer in a synthetic batch. Nothing
 * retries it, so a turn that asks for a retry (handler error or the hard stop)
 * goes straight to the dead-letter handling: marked failed, apology sent.
 * The caller wraps this in waitUntil.
 */
export async function runInline(env: Env, messageId: string, deps: ConsumerDeps = {}): Promise<AdvisorConsumeResult> {
  let retried = false;
  const message = {id: `inline-${messageId}`, timestamp: new Date(clock(deps)), body: {message_id: messageId}, attempts: 1,
    ack() {}, retry() { retried = true; }} as unknown as QueueMessage;
  const batch = {queue: ADVISOR_QUEUE_NAME, messages: [message], ackAll() {}, retryAll() { retried = true; }} as unknown as MessageBatch<AdvisorMessage>;
  // TA-C4: nothing re-delivers an inline message, so a failed download is final at once.
  // TA-M1: nor can it wait for the media job's public.jpg (derivedWaits 0).
  const result = await consumeAdvisor(batch, env, {mediaRetries: 0, derivedWaits: 0, ...deps});
  if (retried) {
    const dead = await consumeAdvisorDeadLetters({...batch, queue: ADVISOR_DLQ_NAME} as MessageBatch<AdvisorMessage>, env, deps);
    result.failed += dead.failed; result.sends += dead.apologies;
  }
  return result;
}

export interface ReleaseResult {released: number; failed: number; aged: number; skipped: string | null}

/**
 * Held outbound messages (01 § idempotency): run by the cron on every tick.
 * Rows held for more than 6 hours become 'failed' first. Then, unless the
 * relay is still down and outbound still goes through BlueBubbles, up to 50
 * held rows are sent, oldest first, through the contact's current adapter
 * (so after the owner sets ADVISOR_CHANNEL=twilio they go through Twilio; the
 * switch is never automatic). Each row is claimed held -> sending first, so
 * two ticks never send one twice. A stopped or blocked contact's rows fail.
 */
export async function releaseHeld(env: Env, deps: ConsumerDeps = {}, now: number = clock(deps)): Promise<ReleaseResult> {
  const out: ReleaseResult = {released: 0, failed: 0, aged: 0, skipped: null};
  if (!env.DB) { out.skipped = 'no-db'; return out; }
  const db = env.DB, cutoff = new Date(now - HOLD_MAX_MS).toISOString();
  const aged = await db.prepare("UPDATE advisor_messages SET status='failed',error='held-expired' WHERE direction='out' AND status='held' AND created_at<?").bind(cutoff).run();
  out.aged = aged.meta.changes ?? 0;
  if (out.aged) advisorLog('warn', 'advisor_held_expired', {count: out.aged});
  if (advisorSettings(env).channel === 'bluebubbles' && (await relayState(env))?.state === 'down') { out.skipped = 'relay-down'; return out; }
  const rows = (await db.prepare("SELECT * FROM advisor_messages WHERE direction='out' AND status='held' ORDER BY created_at,id LIMIT ?").bind(RELEASE_BATCH).all<AdvisorMessageRow>()).results;
  const runDeps: ConsumerDeps = {...deps, now: () => now};
  let first = true;
  for (const row of rows) {
    if (!await setStatus(db, row.id, 'sending', ['held'])) continue;     // another tick took it
    const contact = await db.prepare('SELECT * FROM advisor_contacts WHERE id=?').bind(row.contact_id).first<AdvisorContactRow>();
    if (!contact || contact.status !== 'active') {
      await setStatus(db, row.id, 'failed', ['sending'], contact ? contact.status : 'no-contact'); out.failed++; continue;
    }
    if (!first) await sleep(deps, CHUNK_GAP_MS);
    first = false;
    let mediaKeys: string[] | undefined;
    try { const keys = row.media_json ? JSON.parse(row.media_json) : null; if (Array.isArray(keys)) mediaKeys = keys.filter((k): k is string => typeof k === 'string'); } catch { mediaKeys = undefined; }
    const result = await deliver(env, contact, channelOf(env, deps, contact), {id: row.id, ...(row.body != null ? {text: row.body} : {}), ...(mediaKeys?.length ? {mediaKeys} : {})});
    if (await recordResult(db, runDeps, row.id, result)) out.released++; else out.failed++;
  }
  if (rows.length || out.aged) advisorLog('info', 'advisor_held_release', {...out});
  return out;
}
