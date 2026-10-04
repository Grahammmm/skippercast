// Text Advisor public routes (docs/plans/text-advisor/). Mounted before the
// private gate; every path the advisor owns passes through `gate` first, so it
// all answers 404 until TEXT_ADVISOR_ENABLED=true is deployed. The prefixes are
// reserved here, ahead of their routes, so later tasks inherit the gate and a
// path such as /ports/x never falls through to the static site while dark.
import {Hono} from 'hono';
import type {Context} from 'hono';
import {gate} from '../advisor/gate.ts';
import {advisorSettings} from '../advisor/settings.ts';
import {relayState} from '../advisor/relay.ts';
import {ADAPTERS} from '../advisor/channels/index.ts';
import type {ChannelAdapter} from '../advisor/channels/index.ts';
import {advisorLog} from '../advisor/log.ts';
// TA-C4: shared inbound path, media intake, upload links and media serving.
import {storeInbound, dispatchInbound, storeUpload} from '../advisor/inbound.ts';
import {deriveKeys} from '../advisor/contacts.ts';
import {ingestMedia, verifyUploadToken, derivedKey, MAX_MEDIA_BYTES} from '../advisor/media.ts';
import {firstFile} from '../advisor/multipart.ts';
import {shellResponse} from './assets.ts';
import {waitUntil} from './util.ts';
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

// TA-C4: storing and dispatching moved to server/advisor/inbound.ts, shared with the upload link.
export {storeInbound};

/** Hand a stored message to the queue, or run it inline (under waitUntil when there is an execution context). */
async function dispatch(c: Context<AppEnv>, id: string): Promise<void> {
  const ctx = waitUntil(c);
  await dispatchInbound(c.env, id, ctx ? p => ctx.waitUntil(p) : undefined);
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

// ---- TA-C4: upload link and media serving ----------------------------------------
// (03 § Uploads for compressed channels, 02 § R2, 09 § Media that Meta fetches.)

const NOT_FOUND = (): Response => json({error: 'Not found'}, 404);   // the gate's body: a bad token looks like a missing page
const PUBLIC_STATES = new Set(['approved', 'posted']);

/** The contact an upload token was minted for, or null (bad, expired or tampered token, no key, unknown contact). */
async function uploadContact(env: Env, token: string, now = Date.now()): Promise<{id: string; channel: string; boat_id: string | null; status: string} | null> {
  if (!env.ADVISOR_PHONE_KEY || !env.DB) return null;
  let contactId: string | null = null;
  try { contactId = await verifyUploadToken(await deriveKeys(env.ADVISOR_PHONE_KEY), token, now); } catch { return null; }
  if (!contactId) return null;
  return env.DB.prepare('SELECT id,channel,boat_id,status FROM advisor_contacts WHERE id=?').bind(contactId).first();
}

// The upload page: the dist/upload.html shell for a valid token, the gate's 404 otherwise.
advisorPublic.get('/u/:token', async c => {
  if (await overLimit(c.env.PUBLIC_LIMITER, 'advisor-upload:' + clientIP(c.req.raw))) return tooManyRequests();
  try {
    const contact = await uploadContact(c.env, c.req.param('token'));
    if (!contact || contact.status === 'blocked') return NOT_FOUND();
    const shell = await shellResponse(c, '/upload.html');
    if (!shell.ok) return NOT_FOUND();
    // The page lives at /u/<token>; its hashed assets are linked relative to the site root.
    const html = (await shell.text()).replace(/<head>/i, '<head><base href="/">');
    return new Response(html, {status: 200, headers: {'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex'}});
  } catch (error) {
    // Logged without the path: it carries the token.
    advisorLog('error', 'advisor_upload_page_failed', {reason: String((error as Error)?.message).slice(0, 200)});
    return json({error: 'This service is temporarily unavailable.'}, 503);
  }
});

// One file (multipart, at most 300 MB) through ingestMedia, then a synthetic inbound message dispatched like a webhook's.
advisorPublic.post('/api/advisor/upload/:token', async c => {
  const env = c.env;
  if (await overLimit(env.PUBLIC_LIMITER, 'advisor-upload:' + clientIP(c.req.raw))) return tooManyRequests();
  // Errors are answered here, not by the shared onError: its log line carries the path, and the path carries the token.
  try {
    const contact = await uploadContact(env, c.req.param('token'));
    if (!contact || contact.status === 'blocked') return NOT_FOUND();
    if (!env.DB || !env.ADVISOR_MEDIA) return json({error: 'This service is temporarily unavailable.'}, 503);
    if (Number(c.req.header('content-length')) > MAX_MEDIA_BYTES + 64 * 1024) return json({error: 'That file is too large.'}, 413);
    const file = await firstFile(c.req.raw);
    const result = await ingestMedia(env, {contactId: contact.id, messageId: null, boatId: contact.boat_id, providerRef: null,
      fetchBytes: async () => new Response(file.body), claimedMime: file.type, name: file.name});
    if (result.status === 'rejected') return result.reason === 'too-large' ? json({error: 'That file is too large.'}, 413) : json({error: 'That file type is not supported.'}, 415);
    const id = await storeUpload(env, {id: contact.id, channel: contact.channel}, result.id);
    if (id) await dispatch(c, id);
    return json({ok: true});
  } catch (error) {
    const client = error instanceof ClientError;
    advisorLog(client ? 'warn' : 'error', 'advisor_upload_failed', {type: client ? 'validation' : 'dependency', reason: String((error as Error)?.message).slice(0, 200)});
    return client ? json({error: (error as Error).message}, 400) : json({error: 'This service is temporarily unavailable.'}, 503);
  }
});

const MEDIA_FILE = /^([\w-]{1,64})\.(jpg|png)$/;
const EXT_MIME: Record<string, string> = {jpg: 'image/jpeg', png: 'image/png'};

/**
 * A public image: advisor/derived/<id>/public.jpg once the media job has made
 * it, else the metadata-stripped original, only for publish_state approved or
 * posted. Originals that were not stripped (HEIC, GIF, WebP, video, audio) are
 * never served. Anything else is the same 404 as a missing id.
 */
advisorPublic.get('/media/:file', async c => {
  const env = c.env, match = MEDIA_FILE.exec(c.req.param('file'));
  if (!match || !env.DB || !env.ADVISOR_MEDIA) return NOT_FOUND();
  const [, id, ext] = match as unknown as [string, string, string];
  const row = await env.DB.prepare('SELECT mime,r2_key,exif_stripped,publish_state FROM advisor_media WHERE id=?').bind(id)
    .first<{mime: string; r2_key: string; exif_stripped: number; publish_state: string}>();
  if (!row || !PUBLIC_STATES.has(row.publish_state)) return NOT_FOUND();
  let object: R2ObjectBody | null = null, type = row.mime;
  if (ext === 'jpg') { object = await env.ADVISOR_MEDIA.get(derivedKey(id)); if (object) type = 'image/jpeg'; }
  if (!object && row.r2_key && row.exif_stripped === 1 && row.mime === EXT_MIME[ext]) object = await env.ADVISOR_MEDIA.get(row.r2_key);
  if (!object) return NOT_FOUND();
  return new Response(object.body, {status: 200, headers: {'Content-Type': type, 'Content-Length': String(object.size), 'Cache-Control': 'public, max-age=3600',
    'X-Robots-Tag': 'noindex', 'X-Content-Type-Options': 'nosniff'}});
});
