// Text Advisor public routes (docs/plans/text-advisor/). Mounted before the
// private gate; every path the advisor owns passes through `gate` first, so it
// all answers 404 until TEXT_ADVISOR_ENABLED=true is deployed. The prefixes are
// reserved here, ahead of their routes, so later tasks inherit the gate and a
// path such as /ports/x never falls through to the static site while dark.
import {Hono} from 'hono';
import type {Context} from 'hono';
import {gate} from '../advisor/gate.ts';
import {advisorSettings} from '../advisor/settings.ts';
import {deriveKeys, findOrCreateContact} from '../advisor/contacts.ts';
import {runInline, MAX_BODY} from '../advisor/consumer.ts';
import {relayState} from '../advisor/relay.ts';
import {ADAPTERS, channelFor} from '../advisor/channels/index.ts';
import type {ChannelAdapter, InboundMessage} from '../advisor/channels/index.ts';
import {advisorLog} from '../advisor/log.ts';
import {randomId} from '../advisor/ids.ts';
import {overLimit, clientIP, tooManyRequests} from '../edge-cache.ts';
import {json} from '../http.ts';
import {ClientError} from '../errors.ts';
import type {AppEnv, Env} from '../env.ts';

export const advisorPublic = new Hono<AppEnv>();

// Webhooks, web chat and APIs; public pages; media; upload links; contact card; the text deep link.
export const ADVISOR_PATHS = ['/api/advisor/*', '/ports/*', '/species/*', '/boats/*', '/media/*', '/u/*', '/contact.vcf', '/text'] as const;
for (const path of ADVISOR_PATHS) advisorPublic.use(path, gate);

// Liveness and configuration shape only: never a secret, the number or the relay URL.
advisorPublic.get('/api/advisor/health', async c => {
  const settings = advisorSettings(c.env);
  const relay = await relayState(c.env).catch(() => null);
  return json({enabled: true, channel: settings.channel, providers: settings.visionProviders, relay: relay ? {state: relay.state, checked_at: relay.checked_at} : null});
});

const encoder = new TextEncoder();
/** Constant-time string equality: both sides are hashed first, so length and content leak nothing. */
export async function sameSecret(given: string, expected: string): Promise<boolean> {
  const [a, b] = await Promise.all([given, expected].map(s => crypto.subtle.digest('SHA-256', encoder.encode(s))));
  const x = new Uint8Array(a!), y = new Uint8Array(b!);
  let diff = 0;
  for (let i = 0; i < x.length; i++) diff |= x[i]! ^ y[i]!;
  return diff === 0 && expected.length > 0;
}

const MEDIA_KIND = (mime: string | null): 'image' | 'video' | 'audio' => mime?.startsWith('video/') ? 'video' : mime?.startsWith('audio/') ? 'audio' : 'image';

/**
 * Store one normalized inbound message (01 § request flow, steps 2-3): the
 * contact (created on first contact), the advisor_messages row ('queued') and
 * one placeholder advisor_media row per attachment (r2_key '' and the
 * provider's reference in provider_ref until TA-C4 downloads it). The message
 * and its media go in one batch; a second delivery of the same provider id
 * changes nothing. Returns the new message id, or null for a duplicate.
 */
export async function storeInbound(env: Env, message: InboundMessage, now: Date = new Date()): Promise<string | null> {
  const db = env.DB!;
  const seen = await db.prepare('SELECT id FROM advisor_messages WHERE channel=? AND provider_id=?').bind(message.channel, message.providerId).first<{id: string}>();
  if (seen) return null;
  if (!env.ADVISOR_PHONE_KEY) throw Error('ADVISOR_PHONE_KEY is not set');
  const contact = await findOrCreateContact(db, await deriveKeys(env.ADVISOR_PHONE_KEY), {e164: message.from, channel: message.channel}, now);
  const id = randomId(), at = now.toISOString();
  const media = message.media.map(m => ({id: randomId(), ...m}));
  const statements = [
    db.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,provider_id,body,media_json,status,created_at) VALUES(?,?,'in',?,?,?,?,'queued',?) ON CONFLICT DO NOTHING`)
      .bind(id, contact.id, message.channel, message.providerId, message.text.slice(0, MAX_BODY) || null, media.length ? JSON.stringify(media.map(m => m.id)) : null, at),
    // Only if this call's message row exists, i.e. it was not a concurrent duplicate.
    ...media.map(m => db.prepare(`INSERT INTO advisor_media(id,contact_id,message_id,boat_id,kind,mime,bytes,width,height,r2_key,sha256,publish_state,provider_ref,created_at)
      SELECT ?,?,?,?,?,?,?,?,?,'','','private',?,? WHERE EXISTS (SELECT 1 FROM advisor_messages WHERE id=?)`)
      .bind(m.id, contact.id, id, contact.boat_id, MEDIA_KIND(m.mime), m.mime ?? 'application/octet-stream', m.bytes ?? 0, m.width ?? null, m.height ?? null, m.providerRef, at, id)),
  ];
  const [inserted] = await db.batch(statements);
  return inserted?.meta.changes ? id : null;
}

/** Hand a stored message to the queue, or run it inline under waitUntil when there is no queue (or the send fails). */
async function dispatch(c: Context<AppEnv>, id: string): Promise<void> {
  const env = c.env;
  if (env.ADVISOR_QUEUE) {
    try { await env.ADVISOR_QUEUE.send({message_id: id}); return; }
    catch (error) { advisorLog('error', 'advisor_enqueue_failed', {reason: String((error as Error)?.message).slice(0, 200)}); }
  }
  const run = runInline(env, id, {channelFor}).catch(error => { advisorLog('error', 'advisor_inline_failed', {reason: String((error as Error)?.message).slice(0, 200)}); });
  let ctx: ExecutionContext | null = null;
  try { ctx = c.executionCtx as ExecutionContext; } catch { ctx = null; }
  if (ctx) ctx.waitUntil(run); else await run;   // no execution context (tests): run before answering
}

/** One provider webhook: token, rate limit, normalize, store each message, dispatch, 200 {}. */
async function inboundWebhook(c: Context<AppEnv>, adapter: ChannelAdapter, token: string): Promise<Response> {
  const env = c.env;
  if (await overLimit(env.PUBLIC_LIMITER, 'advisor-inbound:' + clientIP(c.req.raw))) return tooManyRequests();
  if (!await sameSecret(token, env.ADVISOR_WEBHOOK_TOKEN ?? '')) {
    advisorLog('warn', 'advisor_webhook_unauthorized', {channel: adapter.name, count: 1, configured: Boolean(env.ADVISOR_WEBHOOK_TOKEN)});
    return json({error: 'Unauthorized'}, 401);
  }
  // Errors are answered here, not by the shared onError: its log line carries the
  // request path, and this path carries the webhook token.
  try {
    if (!env.DB) throw Error('storage unavailable');
    const result = await adapter.normalize(c.req.raw, env);
    if (result === 'unauthorized') { advisorLog('warn', 'advisor_webhook_unauthorized', {channel: adapter.name, count: 1}); return json({error: 'Unauthorized'}, 401); }
    if (result === 'ignore') return json({});
    let duplicates = 0;
    for (const message of result) {
      const id = await storeInbound(env, message);
      if (!id) { duplicates++; continue; }
      await dispatch(c, id);
    }
    if (duplicates) advisorLog('info', 'advisor_webhook_duplicate', {channel: adapter.name, count: duplicates});
    return json({});
  } catch (error) {
    const client = error instanceof ClientError;
    advisorLog(client ? 'warn' : 'error', 'advisor_webhook_failed', {channel: adapter.name, type: client ? 'validation' : 'dependency', reason: String((error as Error)?.message).slice(0, 200)});
    return client ? json({error: (error as Error).message}, 400) : json({error: 'This service is temporarily unavailable.'}, 503);
  }
}

// BlueBubbles sends no signature: the path carries ADVISOR_WEBHOOK_TOKEN (03 § owner checklist step 6).
advisorPublic.post('/api/advisor/inbound/bluebubbles/:token', c => inboundWebhook(c, ADAPTERS.bluebubbles, c.req.param('token')));
