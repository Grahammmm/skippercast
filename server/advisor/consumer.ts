// Text Advisor queue consumer (docs/plans/text-advisor/01-architecture.md
// § request flow, steps 5-7, and § Idempotency and failure rules).
//
//   ADVISOR_QUEUE {message_id} -> load the stored inbound row -> mark processing
//   -> handler (the engine from TA-E1; until then warmUpHandler) -> apply its
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
// Not here yet, by design: STOP/blocked and the daily caps (the engine's
// stage 0, TA-E1).
import {advisorSettings} from './settings.ts';
import {reviewId} from './contacts.ts';
import {outboundId} from './ids.ts';
import {advisorLog, redact} from './log.ts';
import {recordAdvisorTurn} from './analytics.ts';
import {relayState} from './relay.ts';
import {splitForChannel, ChannelNotImplemented, CHUNK_GAP_MS} from './channels/index.ts';
// TA-C4: media intake before the handler.
import {ingestInboundMedia} from './media.ts';
import {fetchMediaByRef as adapterFetchMediaByRef} from './channels/index.ts';
import type {Env} from '../env.ts';
import type {Action, AdvisorContactRow, AdvisorMessage, AdvisorMessageRow, ConsumerDeps, ContactFields, EngineResult, Handler, OutboundChannel, OutboundMessage, ReviewKind, SendResult} from './types.ts';

// Must match scripts/wrangler_config.mjs ADVISOR_QUEUES (tests/test_advisor_consumer.mjs checks).
export const ADVISOR_QUEUE_NAME = 'skippercast-advisor';
export const ADVISOR_DLQ_NAME = 'skippercast-advisor-dlq';

export const TURN_TIMEOUT_MS = 45000;          // 01 § request flow: hard stop per message
export const TIMEOUT_RETRY_SECONDS = 20;
export const ERROR_NOTICE_MS = 60 * 60000;     // one apology per contact per hour
export const MAX_BODY = 4000;                  // 02 § advisor_messages.body
export const WARM_UP_TEXT = 'SkipperCast is warming up. Check back soon.';
export const STILL_WORKING_TEXT = 'Still working on that, one moment';
export const APOLOGY_TEXT = 'Sorry, something went wrong on my end. Please send that again.';
export const HOLD_MAX_MS = 6 * 3600000;        // 01: held outbound older than this becomes failed
export const RELEASE_BATCH = 50;               // held rows sent per cron tick
export const MEDIA_RETRIES = 2;                // TA-C4: extra attempts after a failed media download

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
  ? {actions: [{type: 'send_text', text: WARM_UP_TEXT}], intent: 'stub'}
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

/** Where a channel sends: the encrypted number (decrypted only inside the adapter) or the web session hash. */
const address = (contact: AdvisorContactRow): string | null => contact.phone_enc ?? contact.web_session ?? null;
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
async function sendOnce(env: Env, deps: ConsumerDeps, contact: AdvisorContactRow, inId: string, key: number | string, content: {text?: string; mediaKeys?: string[]}): Promise<boolean> {
  const db = env.DB!, id = await outboundId(inId, key), at = iso(deps);
  const body = content.text == null ? null : content.text.slice(0, MAX_BODY);
  const adapter = channelOf(env, deps, contact);
  const existing = await db.prepare('SELECT status FROM advisor_messages WHERE id=?').bind(id).first<{status: string}>();
  if (existing) {
    if (existing.status === 'sending') { await setStatus(db, id, 'unknown', ['sending'], 'interrupted'); return false; }
    if (existing.status !== 'failed' || !await setStatus(db, id, 'sending', ['failed'])) return false;
  } else {
    const held = await relayHold(env, adapter);
    const r = await db.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,body,media_json,status,error,in_reply_to,created_at) VALUES(?,?,'out',?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING`)
      .bind(id, contact.id, contact.channel, body, content.mediaKeys?.length ? JSON.stringify(content.mediaKeys) : null, held ? 'held' : 'sending', held ? 'relay-down' : null, inId, at).run();
    if (!r.meta.changes) return false;   // a concurrent delivery got there first
    if (held) { advisorLog('warn', 'advisor_send_held', {reason: 'relay-down'}); return false; }
  }
  const result = await deliver(env, contact, adapter, {id, ...(content.text != null ? {text: content.text} : {}), ...(content.mediaKeys ? {mediaKeys: content.mediaKeys} : {})});
  return recordResult(db, deps, id, result);
}

/**
 * A send_text action: split for the contact's channel and sent one row per
 * chunk, in order, 300 ms apart. Chunk 0 keeps the action's key, so an
 * unsplit text has the same outbound id as before; chunk n is "<key>.<n>".
 */
async function sendText(env: Env, deps: ConsumerDeps, contact: AdvisorContactRow, inId: string, key: number | string, text: string): Promise<number> {
  const adapter = channelOf(env, deps, contact);
  const chunks = adapter?.name ? splitForChannel(text, {name: adapter.name as 'bluebubbles' | 'twilio' | 'web'}, contact.channel) : [text];
  let sends = 0;
  for (const [n, chunk] of chunks.entries()) {
    if (n > 0) await sleep(deps, CHUNK_GAP_MS);
    sends += Number(await sendOnce(env, deps, contact, inId, n === 0 ? key : `${key}.${n}`, {text: chunk}));
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
        await db.prepare(`INSERT INTO advisor_reviews(id,kind,ref_id,reason,status,opened_at) VALUES(?,?,?,?,'open',?)
          ON CONFLICT(id) DO UPDATE SET status='open',opened_at=excluded.opened_at,decided_at=NULL,decided_by=NULL`)
          .bind(await reviewId(action.kind, action.refId, action.reason), action.kind, action.refId, action.reason, iso(deps)).run();
        break;
      case 'log':
        advisorLog('info', CODE.test(String(action.event)) ? action.event : 'advisor_action_log', action.fields ?? {});
        break;
      default:
        advisorLog('warn', 'advisor_action_unknown', {index, type: String((action as {type?: unknown})?.type).slice(0, 40)});
    }
  }
  return sends;
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
      if (contact.status === 'active') out.sends += Number(await sendOnce(env, deps, contact, id, 'still-working', {text: STILL_WORKING_TEXT}));
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
  return sendOnce(env, deps, contact, inId, 'error', {text: APOLOGY_TEXT});
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
  const result = await consumeAdvisor(batch, env, {mediaRetries: 0, ...deps});
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
