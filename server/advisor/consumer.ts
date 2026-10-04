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
// 'unknown' (reconciled against the provider by TA-C1) instead of resending.
// Review items use reviewId's deterministic id with the same UPSERT as
// forgetContact. A handler that throws is retried with backoff; after
// max_retries (scripts/wrangler_config.mjs ADVISOR_QUEUES) Cloudflare moves the
// message to the dead-letter queue, whose consumer marks it failed and sends
// the contact one apology an hour at most.
//
// Not here yet, by design: media download (TA-C4), the relay-down hold of new
// outbound rows and their release (TA-C1), STOP/blocked and the daily caps
// (the engine's stage 0, TA-E1).
import {advisorSettings} from './settings.ts';
import {reviewId} from './contacts.ts';
import {outboundId} from './ids.ts';
import {advisorLog, redact} from './log.ts';
import {recordAdvisorTurn} from './analytics.ts';
import type {Env} from '../env.ts';
import type {Action, AdvisorContactRow, AdvisorMessage, AdvisorMessageRow, ConsumerDeps, ContactFields, EngineResult, Handler, OutboundMessage, ReviewKind, SendResult} from './types.ts';

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

/**
 * Send one outbound message at most once. `key` is the action index (or a
 * fixed word for the consumer's own texts). Returns true when this call sent it.
 *   none -> 'sending' -> send -> 'sent' | 'failed' | 'unknown'
 *   'sent' / 'unknown' / 'held' -> skipped; 'sending' (a crash mid-send) -> 'unknown', skipped;
 *   'failed' -> sent again.
 */
async function sendOnce(env: Env, deps: ConsumerDeps, contact: AdvisorContactRow, inId: string, key: number | string, content: {text?: string; mediaKeys?: string[]}): Promise<boolean> {
  const db = env.DB!, id = await outboundId(inId, key), at = iso(deps);
  const body = content.text == null ? null : content.text.slice(0, MAX_BODY);
  const existing = await db.prepare('SELECT status FROM advisor_messages WHERE id=?').bind(id).first<{status: string}>();
  if (existing) {
    if (existing.status === 'sending') { await setStatus(db, id, 'unknown', ['sending'], 'interrupted'); return false; }
    if (existing.status !== 'failed' || !await setStatus(db, id, 'sending', ['failed'])) return false;
  } else {
    const r = await db.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,body,status,in_reply_to,created_at) VALUES(?,?,'out',?,?,'sending',?,?) ON CONFLICT(id) DO NOTHING`)
      .bind(id, contact.id, contact.channel, body, inId, at).run();
    if (!r.meta.changes) return false;   // a concurrent delivery got there first
  }
  const to = address(contact);
  let result: SendResult;
  if (contact.status === 'blocked') result = {providerId: null, status: 'failed', error: 'blocked'};
  else if (!to) result = {providerId: null, status: 'failed', error: 'no-address'};
  else if (!deps.channel) result = {providerId: null, status: 'failed', error: 'no-channel'};
  else {
    const message: OutboundMessage = {id, to, ...(content.text != null ? {text: content.text} : {}), ...(content.mediaKeys ? {mediaKeys: content.mediaKeys} : {})};
    // A throw leaves us not knowing whether the provider accepted it: unknown, never resent blindly.
    result = await deps.channel.send(message, env).catch((error: unknown) => ({providerId: null, status: 'unknown' as const, error: reason(error)}));
  }
  const status = ['sent', 'failed', 'unknown'].includes(result.status) ? result.status : 'unknown';
  await db.prepare('UPDATE advisor_messages SET status=?,provider_id=?,sent_at=?,error=? WHERE id=?')
    .bind(status, result.providerId ?? null, status === 'sent' ? iso(deps) : null, result.error ? String(redact(result.error)).slice(0, 200) : null, id).run();
  if (status !== 'sent') advisorLog('warn', 'advisor_send_not_sent', {status, error: result.error ? String(result.error).slice(0, 200) : null});
  return status === 'sent';
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
        if (typeof action.text === 'string' && action.text.trim()) sends += Number(await sendOnce(env, deps, contact, message.id, index, {text: action.text}));
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
  await db.prepare("UPDATE advisor_messages SET status='done',intent=?,error=NULL,tokens_in=?,tokens_out=? WHERE id=?")
    .bind(intent, usage.input_tokens ?? null, usage.output_tokens ?? null, id).run();
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
  const result = await consumeAdvisor(batch, env, deps);
  if (retried) {
    const dead = await consumeAdvisorDeadLetters({...batch, queue: ADVISOR_DLQ_NAME} as MessageBatch<AdvisorMessage>, env, deps);
    result.failed += dead.failed; result.sends += dead.apologies;
  }
  return result;
}
