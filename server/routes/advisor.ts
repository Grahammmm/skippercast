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
// TA-C2: the Twilio status callback and its empty TwiML reply.
import {statusCallback as twilioStatusCallback, TWIML_EMPTY} from '../advisor/channels/twilio.ts';
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
// TA-C6: contact card, the text deep link and its QR code.
import {contactCard} from '../advisor/pages/contact-card.ts';
import {qrSvg} from '../advisor/pages/qr.ts';
import {SOURCE_PATTERN} from '../advisor/intents.ts';
// TA-C3: the web chat channel and its inline turn.
import {normalizeWeb, createWebCollector, newWebSession, webSessionOf, webSessionCookie} from '../advisor/channels/web.ts';
import type {InboundMessage} from '../advisor/channels/index.ts';
import {runInline} from '../advisor/consumer.ts';
import {findOrCreateContact} from '../advisor/contacts.ts';
import {rejectMedia, sniffMime} from '../advisor/media.ts';
import {randomId, sha256} from '../advisor/ids.ts';
import {requireOrigin} from '../http.ts';
import type {Handler} from '../advisor/types.ts';
// TA-E1: the engine is the inline handler, and "send me my data" links here.
import {engineHandler} from '../advisor/engine.ts';
import {verifyExportToken} from '../advisor/exports.ts';
// TA-M1: the advisor-media runner job's two endpoints, behind a GitHub Actions identity.
import {verifyJobToken} from '../job-auth.ts';
import type {JobClaims, JobScope} from '../job-auth.ts';
import {deployment} from '../config.ts';
import {body, budget} from '../http.ts';
import {mediaJobWork, mediaJobDone} from '../advisor/media.ts';

export const advisorPublic = new Hono<AppEnv>();

// Webhooks, web chat and APIs; public pages; media; upload links; contact card; the text deep link; its QR code (TA-C6).
// TA-C3: the web chat page (dist/chat.html) stays dark with the rest; when on, it falls through to its page shell.
export const ADVISOR_PATHS = ['/api/advisor/*', '/ports/*', '/species/*', '/boats/*', '/media/*', '/u/*', '/contact.vcf', '/text', '/qr/*', '/chat.html'] as const;
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

/** One provider webhook: token, rate limit, normalize, store each message, dispatch, 200 {} (or the adapter's `accepted` reply). */
// TA-C2: `accepted` lets Twilio's webhook answer TwiML instead of {}.
async function inboundWebhook(c: Context<AppEnv>, adapter: ChannelAdapter, token: string, accepted: () => Response = () => json({})): Promise<Response> {
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
    if (result === 'ignore') return accepted();
    let duplicates = 0;
    for (const message of result) {
      const id = await storeInbound(env, message);
      if (!id) { duplicates++; continue; }
      await dispatch(c, id);
    }
    if (duplicates) advisorLog('info', 'advisor_webhook_duplicate', {channel: adapter.name, count: duplicates});
    return accepted();
  } catch (error) {
    const client = error instanceof ClientError;
    advisorLog(client ? 'warn' : 'error', 'advisor_webhook_failed', {channel: adapter.name, type: client ? 'validation' : 'dependency', reason: String((error as Error)?.message).slice(0, 200)});
    return client ? json({error: (error as Error).message}, 400) : json({error: 'This service is temporarily unavailable.'}, 503);
  }
}

// BlueBubbles sends no signature: the path carries ADVISOR_WEBHOOK_TOKEN (03 § owner checklist step 6).
advisorPublic.post('/api/advisor/inbound/bluebubbles/:token', c => inboundWebhook(c, ADAPTERS.bluebubbles, c.req.param('token')));

// TA-C2: Twilio webhooks (03 § Twilio adapter). Both carry ADVISOR_WEBHOOK_TOKEN in
// the path like BlueBubbles' and are also signed (X-Twilio-Signature over
// ADVISOR_PUBLIC_BASE + path + sorted form params); the adapter checks the signature.
const twiml = (): Response => new Response(TWIML_EMPTY, {status: 200, headers: {'Content-Type': 'text/xml; charset=utf-8', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'}});
advisorPublic.post('/api/advisor/inbound/twilio/:token', c => inboundWebhook(c, ADAPTERS.twilio, c.req.param('token'), twiml));

// Delivery status for a message we sent: our outbound row by provider_id becomes sent or failed. 204.
advisorPublic.post('/api/advisor/inbound/twilio-status/:token', async c => {
  const env = c.env;
  if (await overLimit(env.PUBLIC_LIMITER, 'advisor-inbound:' + clientIP(c.req.raw))) return tooManyRequests();
  if (!await sameSecret(c.req.param('token'), env.ADVISOR_WEBHOOK_TOKEN ?? '')) {
    advisorLog('warn', 'advisor_webhook_unauthorized', {channel: 'twilio-status', count: 1, configured: Boolean(env.ADVISOR_WEBHOOK_TOKEN)});
    return json({error: 'Unauthorized'}, 401);
  }
  // Answered here, not by the shared onError: the path carries the token.
  try {
    if (!env.DB) throw Error('storage unavailable');
    if (await twilioStatusCallback(c.req.raw, env) === 'unauthorized') {
      advisorLog('warn', 'advisor_webhook_unauthorized', {channel: 'twilio-status', count: 1});
      return json({error: 'Unauthorized'}, 401);
    }
    return new Response(null, {status: 204});
  } catch (error) {
    const client = error instanceof ClientError;
    advisorLog(client ? 'warn' : 'error', 'advisor_webhook_failed', {channel: 'twilio-status', type: client ? 'validation' : 'dependency', reason: String((error as Error)?.message).slice(0, 200)});
    return client ? json({error: (error as Error).message}, 400) : json({error: 'This service is temporarily unavailable.'}, 503);
  }
});
// TA-C2 end.

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

// ---- TA-C6: contact card, text deep link and QR ----------------------------------
// (03 § Contact card and deep links, FC-3, FC-5.) All three are gated; /contact.vcf
// and /text answer 503 until ADVISOR_NUMBER is set, since there is nothing to save or text.

const NO_NUMBER = (): Response => new Response('SkipperCast texting is not set up yet.\n', {status: 503,
  headers: {'Content-Type': 'text/plain; charset=utf-8', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'}});
export const TEXT_DEFAULT_MESSAGE = 'Hi SkipperCast';
export const TEXT_MAX_MESSAGE = 140;

advisorPublic.get('/contact.vcf', c => {
  const settings = advisorSettings(c.env);
  if (!settings.number) return NO_NUMBER();
  return new Response(contactCard({number: settings.number, publicBase: settings.publicBase}), {status: 200, headers: {
    'Content-Type': 'text/vcard; charset=utf-8', 'Content-Disposition': 'attachment; filename="SkipperCast.vcf"',
    'Cache-Control': 'public, max-age=86400', 'X-Content-Type-Options': 'nosniff'}});
});

/**
 * The pre-filled text body for /text: `m` (control characters removed, trimmed,
 * at most 140 characters; default "Hi SkipperCast") plus " [via <s>]" when `s`
 * is a valid source (^[a-z0-9:_-]{1,32}$); any other `s` is dropped.
 */
export function textBody(message: string | null | undefined, source: string | null | undefined): string {
  const clean = Array.from(String(message ?? '').replace(/[\u0000-\u001f\u007f]/g, ' ').trim()).slice(0, TEXT_MAX_MESSAGE).join('').trim();
  const valid = typeof source === 'string' && SOURCE_PATTERN.test(source) ? source : null;
  return `${clean || TEXT_DEFAULT_MESSAGE}${valid ? ` [via ${valid}]` : ''}`;
}

// The `?&body=` form is the one iOS and Android both open with the body filled in (03).
advisorPublic.get('/text', c => {
  const settings = advisorSettings(c.env);
  if (!settings.number) return NO_NUMBER();
  const body = textBody(c.req.query('m'), c.req.query('s'));
  return new Response(null, {status: 302, headers: {Location: `sms:${settings.number}?&body=${encodeURIComponent(body)}`, 'Cache-Control': 'no-store'}});
});

// The printable QR code of <ADVISOR_PUBLIC_BASE>/text?s=qr. Needs no number: it encodes the deep link, which does.
advisorPublic.get('/qr/text.svg', c => new Response(qrSvg(`${advisorSettings(c.env).publicBase}/text?s=qr`), {status: 200, headers: {
  'Content-Type': 'image/svg+xml; charset=utf-8', 'Cache-Control': 'public, max-age=86400', 'X-Content-Type-Options': 'nosniff'}}));
// TA-C6 end.

// ---- TA-C3: web chat --------------------------------------------------------------
// (03 § Web adapter, 08 § Web chat, 01 § Request flow: web chat.) First-party
// JSON endpoints for the chat island: the same Origin check as private
// mutations, the per-IP PUBLIC_LIMITER, and the sc_adv cookie issued on the
// first call. The turn runs inline (no queue) with a per-request collector as
// the outbound channel, so the replies come back in the response.

/**
 * Test seams: the handler the inline turn runs (default: the engine, TA-E1)
 * and the server-side wait before answering `pending` (08: 40 s).
 */
export const webChat: {handler?: Handler; timeoutMs: number} = {timeoutMs: 40000};
export const WEB_UPLOAD_BYTES = 8 * 1024 * 1024;     // 08: multipart, 8 MB, images only

/** The visitor's session: the cookie's, or a new one and the Set-Cookie to send with the answer. */
function webSession(c: Context<AppEnv>): {session: string; cookie: string | null} {
  const existing = webSessionOf(c.req.raw);
  if (existing) return {session: existing, cookie: null};
  const session = newWebSession();
  return {session, cookie: webSessionCookie(session)};
}
const withCookie = (response: Response, cookie: string | null): Response => { if (cookie) response.headers.append('Set-Cookie', cookie); return response; };
/** A derived public image key (advisor/derived/<id>/public.jpg) as its /media URL; other keys are not public. */
const mediaUrl = (key: string): string | null => { const m = /^advisor\/derived\/([\w-]{1,64})\/public\.jpg$/.exec(key); return m ? `/media/${m[1]}.jpg` : null; };

advisorPublic.post('/api/advisor/web/message', async c => {
  const env = c.env;
  requireOrigin(c.req.raw, c.var.extraOrigins);
  if (await overLimit(env.PUBLIC_LIMITER, 'advisor-web:' + clientIP(c.req.raw))) return tooManyRequests();
  if (!env.DB) return json({error: 'This service is temporarily unavailable.'}, 503);
  const {session, cookie} = webSession(c);
  const [message] = await normalizeWeb(c.req.raw, env, session) as InboundMessage[];
  const id = await storeInbound(env, message!);
  if (!id) throw Error('web message not stored');
  const collector = createWebCollector();
  const run = runInline(env, id, {channel: collector, handler: webChat.handler ?? engineHandler});
  let timer: ReturnType<typeof setTimeout> | undefined;
  const outcome = await Promise.race([
    run.then(() => 'done' as const),
    new Promise<'pending'>(resolve => { timer = setTimeout(() => resolve('pending'), webChat.timeoutMs); }),
  ]).finally(() => { if (timer !== undefined) clearTimeout(timer); });
  if (outcome === 'pending') {
    // Still running: let it finish (its replies are recorded, not delivered here) and tell the island to keep waiting.
    collector.close();
    const ctx = waitUntil(c), rest = run.catch(error => advisorLog('error', 'advisor_web_turn_failed', {reason: String((error as Error)?.message).slice(0, 200)}));
    if (ctx) ctx.waitUntil(rest);
    advisorLog('warn', 'advisor_web_pending', {count: 1});
    return withCookie(json({replies: [], pending: true}), cookie);
  }
  // TA-E1: `linked` is true once the session belongs to a phone contact (the web phone link merged it).
  const contact = await env.DB.prepare('SELECT language,phone_hash FROM advisor_contacts WHERE web_session=?').bind(await sha256(session)).first<{language: string; phone_hash: string | null}>();
  const replies = collector.replies.map(r => ({id: r.id, text: r.text, links: [] as string[], media: r.mediaKeys.map(mediaUrl).filter((u): u is string => u !== null)}));
  return withCookie(json({replies, contact: {language: contact?.language ?? 'en', linked: Boolean(contact?.phone_hash)}}), cookie);
});

/** The upload body as a stream that errors past `limit` bytes or when its first bytes are not an image. */
function imageOnly(body: ReadableStream<Uint8Array>, limit: number): ReadableStream<Uint8Array> {
  let size = 0, head = new Uint8Array(0), checked = false;
  const check = (final: boolean): void => {
    if (checked || (!final && head.length < 64)) return;
    checked = true;
    if (sniffMime(head)?.kind !== 'image') throw new UploadRefused('unsupported');
  };
  return body.pipeThrough(new TransformStream<Uint8Array, Uint8Array>({
    transform(chunk, controller) {
      size += chunk.length;
      if (size > limit) throw new UploadRefused('too-large');
      if (!checked) { const next = new Uint8Array(head.length + chunk.length); next.set(head); next.set(chunk, head.length); head = next; }
      check(false);
      controller.enqueue(chunk);
    },
    flush() { check(true); },
  }));
}
class UploadRefused extends Error {
  readonly reason: 'too-large' | 'unsupported';
  constructor(reason: 'too-large' | 'unsupported') { super(reason); this.reason = reason; this.name = 'UploadRefused'; }
}

advisorPublic.post('/api/advisor/web/upload', async c => {
  const env = c.env;
  requireOrigin(c.req.raw, c.var.extraOrigins);
  if (await overLimit(env.PUBLIC_LIMITER, 'advisor-web:' + clientIP(c.req.raw))) return tooManyRequests();
  if (!env.DB || !env.ADVISOR_MEDIA) return json({error: 'This service is temporarily unavailable.'}, 503);
  if (Number(c.req.header('content-length')) > WEB_UPLOAD_BYTES + 64 * 1024) return json({error: 'That photo is too large.'}, 413);
  const {session, cookie} = webSession(c);
  const contact = await findOrCreateContact(env.DB, null, {webSession: session, channel: 'web'});
  if (contact.status === 'blocked') return NOT_FOUND();
  const file = await firstFile(c.req.raw);
  const mediaId = randomId();
  let result;
  try {
    result = await ingestMedia(env, {mediaId, contactId: contact.id, messageId: null, boatId: contact.boat_id, providerRef: null,
      fetchBytes: async () => new Response(imageOnly(file.body, WEB_UPLOAD_BYTES)), claimedMime: file.type, name: file.name});
  } catch (error) {
    if (!(error instanceof UploadRefused)) throw error;
    await rejectMedia(env.DB, mediaId, error.reason);
    result = {status: 'rejected' as const, reason: error.reason};
  }
  if (result.status === 'rejected') return withCookie(result.reason === 'too-large' ? json({error: 'That photo is too large.'}, 413) : json({error: 'Send a photo: JPEG, PNG, HEIC, GIF or WebP.'}, 415), cookie);
  return withCookie(json({media_id: mediaId}), cookie);
});
// TA-C3 end.

// ---- TA-E1: "send me my data" -------------------------------------------------------
// (02 § Retention and deletion.) The export the engine wrote to
// advisor/exports/<contact_id>/<date>.json, behind a signed 24-hour token
// (server/advisor/exports.ts). A bad, tampered or expired token, a deleted
// contact or a missing object is the gate's 404. Errors are answered here: the
// path carries the token.
advisorPublic.get('/api/advisor/export/:token', async c => {
  const env = c.env;
  if (await overLimit(env.PUBLIC_LIMITER, 'advisor-export:' + clientIP(c.req.raw))) return tooManyRequests();
  try {
    if (!env.ADVISOR_PHONE_KEY || !env.DB || !env.ADVISOR_MEDIA) return NOT_FOUND();
    const valid = await verifyExportToken(await deriveKeys(env.ADVISOR_PHONE_KEY), c.req.param('token'));
    if (!valid) return NOT_FOUND();
    const contact = await env.DB.prepare('SELECT id FROM advisor_contacts WHERE id=?').bind(valid.contactId).first<{id: string}>();
    if (!contact) return NOT_FOUND();
    const object = await env.ADVISOR_MEDIA.get(valid.key);
    if (!object) return NOT_FOUND();
    return new Response(object.body, {status: 200, headers: {'Content-Type': 'application/json; charset=utf-8', 'Content-Length': String(object.size),
      'Content-Disposition': 'attachment; filename="skippercast-data.json"', 'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex', 'X-Content-Type-Options': 'nosniff'}});
  } catch (error) {
    advisorLog('error', 'advisor_export_failed', {reason: String((error as Error)?.message).slice(0, 200)});
    return json({error: 'This service is temporarily unavailable.'}, 503);
  }
});
// TA-E1 end.

// ---- TA-M1: the advisor-media runner job ------------------------------------------
// (09 § Derived images and graphics.) .github/workflows/advisor-media.yml asks
// for its work and reports each item, authorised like the trip check
// (server/job-auth.ts) by a short-lived GitHub Actions OIDC token, here
// requested for the audience <public_origin>/api/advisor/jobs and accepted only
// from advisor-media.yml (deployments/production.json scheduler.workflows). The
// gate applies: dark until TEXT_ADVISOR_ENABLED. 240 requests a minute per run.

export const ADVISOR_JOB_SCOPE: JobScope = {audiencePath: '/api/advisor/jobs', workflows: ['advisor-media.yml']};
/** Test seam: the token check (default: verifyJobToken with ADVISOR_JOB_SCOPE). */
export const advisorJobs: {verify: (token: string | undefined) => Promise<JobClaims | false>} = {
  verify: token => verifyJobToken(token, deployment, ADVISOR_JOB_SCOPE),
};
const JOB_BUDGET = 240;

async function jobClaims(c: Context<AppEnv>): Promise<JobClaims | null> {
  const token = c.req.header('Authorization')?.replace(/^Bearer /, '');
  const claims = await advisorJobs.verify(token);
  if (!claims) return null;
  await budget(c.env, 'advisor-job:' + claims.jti, JOB_BUDGET);
  return claims;
}

advisorPublic.get('/api/advisor/jobs/media', async c => {
  if (!await jobClaims(c)) return json({error: 'Unauthorized'}, 401);
  if (!c.env.DB) return json({error: 'This service is temporarily unavailable.'}, 503);
  return json(await mediaJobWork(c.env.DB));
});

advisorPublic.post('/api/advisor/jobs/media-done', async c => {
  if (!await jobClaims(c)) return json({error: 'Unauthorized'}, 401);
  if (!c.env.DB) return json({error: 'This service is temporarily unavailable.'}, 503);
  const result = await mediaJobDone(c.env, await body(c.req.raw));
  if (!result.ok) return result.error === 'not-found' ? NOT_FOUND() : json({error: 'invalid media-done report'}, 400);
  return json(result);
});
// TA-M1 end.
