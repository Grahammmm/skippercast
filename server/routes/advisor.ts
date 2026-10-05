// Text Advisor public routes (docs/plans/text-advisor/). Mounted before the
// private gate; every path the advisor owns passes through `gate` first, so it
// all answers 404 until TEXT_ADVISOR_ENABLED=true is deployed. The prefixes are
// reserved here, ahead of their routes, so later tasks inherit the gate and a
// path such as /ports/x never falls through to the static site while dark.
import {Hono} from 'hono';
import type {Context} from 'hono';
import {gate, boatsGate} from '../advisor/gate.ts';
import {fleetSettings} from '../fleet/settings.ts';
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
import {ingestMedia, verifyUploadToken, readUploadToken, derivedKey, derivedKeys, derivedVideoKey, MAX_MEDIA_BYTES, LEGACY_LINK_GONE_MS} from '../advisor/media.ts';
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
import {verifyExportToken, readExportToken, EXPORT_PAGE} from '../advisor/exports.ts';
// Hardening: the hashed client address for the per-address limits.
import {ipHash} from '../advisor/outbound-guard.ts';
// TA-M1: the advisor-media runner job's two endpoints, behind a GitHub Actions identity.
import {verifyJobToken} from '../job-auth.ts';
import type {JobClaims, JobScope} from '../job-auth.ts';
import {deployment, build} from '../config.ts';
import {body, budget} from '../http.ts';
import {mediaJobWork, mediaJobDone} from '../advisor/media.ts';
// TA-S6: Meta's webhook (the inbox).
import {handshake, readRawBody, verifyMetaSignature, parseMetaWebhook, classifyComment, inboxReady} from '../advisor/social/inbox.ts';
import type {MetaPayload} from '../advisor/social/inbox.ts';
// TA-S4: generated post graphics for Meta's fetch.
import {GRAPHIC_NAME, GRAPHIC_PUBLIC_STATUSES, servableGraphic} from '../advisor/social/graphics.ts';
// TA-W1: the public pages, their cache key and the sitemap.
import {cacheKey, cached} from '../edge-cache.ts';
import {pageLanguage, pageResponse} from '../advisor/pages/render.ts';
import {pagesVersion, notFoundPage} from '../advisor/pages/data.ts';
import type {PageDeps} from '../advisor/pages/data.ts';
import {portPage, PORT_MAX_AGE} from '../advisor/pages/port.ts';
import {speciesPage, speciesPageKey, SPECIES_MAX_AGE} from '../advisor/pages/species.ts';
import {boatPage, BOAT_MAX_AGE} from '../advisor/pages/boat.ts';
import {sitemapXml, robotsTxt, SITEMAP_PATH, SITEMAP_MAX_AGE} from '../advisor/pages/sitemap.ts';
import type {PageLanguage} from '../../web/advisor/copy.ts';

export const advisorPublic = new Hono<AppEnv>();

// Webhooks, web chat and APIs; public pages; media; upload links; contact card; the text deep link; its QR code (TA-C6).
// TA-C3: the web chat page (dist/chat.html) stays dark with the rest; when on, it falls through to its page shell.
// Hardening: '/u' and '/my-data' are the upload and export pages (the token in the fragment).
// CF-33: '/boats/*' passes when either the advisor or the charter fleet is on (boatsGate).
export const ADVISOR_PATHS = ['/api/advisor/*', '/ports/*', '/species/*', '/media/*', '/u', '/u/*', '/my-data', '/contact.vcf', '/text', '/qr/*', '/chat.html'] as const;
for (const path of ADVISOR_PATHS) advisorPublic.use(path, gate);
advisorPublic.use('/boats/*', boatsGate);

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

// ---- TA-S6: Meta's webhook for Instagram DMs and comments (09 § Inbox) -------------
// GET is the subscription handshake (META_VERIFY_TOKEN); POST carries
// X-Hub-Signature-256 over the raw body (META_APP_SECRET), checked before
// anything is parsed. With ADVISOR_INBOX_ENABLED off a signed delivery is
// acknowledged and nothing is written. Meta retries a delivery that is not
// answered 200, so a dependency failure answers 503 and the retry is
// deduplicated by message or comment id.
const plainText = (body: string, status: number): Response => new Response(body, {status, headers: {'Content-Type': 'text/plain; charset=utf-8', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'}});
advisorPublic.get('/api/advisor/inbound/meta', async c => {
  if (await overLimit(c.env.PUBLIC_LIMITER, 'advisor-inbound:' + clientIP(c.req.raw))) return tooManyRequests();
  const answer = await handshake(new URL(c.req.url).searchParams, c.env.META_VERIFY_TOKEN);
  if (answer.status !== 200) advisorLog('warn', 'advisor_webhook_unauthorized', {channel: 'meta-handshake', count: 1, configured: Boolean(c.env.META_VERIFY_TOKEN)});
  return plainText(answer.body, answer.status);
});
advisorPublic.post('/api/advisor/inbound/meta', async c => {
  const env = c.env;
  if (await overLimit(env.PUBLIC_LIMITER, 'advisor-inbound:' + clientIP(c.req.raw))) return tooManyRequests();
  try {
    const raw = await readRawBody(c.req.raw);
    if (!await verifyMetaSignature(env.META_APP_SECRET, raw, c.req.header('X-Hub-Signature-256') ?? null)) {
      advisorLog('warn', 'advisor_webhook_unauthorized', {channel: 'meta', count: 1, configured: Boolean(env.META_APP_SECRET)});
      return json({error: 'Unauthorized'}, 401);
    }
    const settings = advisorSettings(env);
    if (!inboxReady(env, settings)) return json({});   // dark: verified, acknowledged, nothing written
    if (!env.DB) throw Error('storage unavailable');
    let payload: unknown;
    try { payload = JSON.parse(new TextDecoder().decode(raw)); } catch { throw new ClientError('invalid JSON'); }
    const events = parseMetaWebhook(payload as MetaPayload, env.META_IG_USER_ID!);
    // A comment is kept only when it needs an answer (a keyword, or a question with public replies on).
    const comments = events.comments.filter(m => classifyComment(m.text, settings));
    let stored = 0, duplicates = 0;
    const ignored = events.skipped + events.comments.length - comments.length;
    for (const message of [...events.dms, ...comments]) {
      const id = await storeInbound(env, message);
      if (!id) { duplicates++; continue; }
      stored++;
      await dispatch(c, id);
    }
    if (stored || duplicates || ignored) advisorLog('info', 'advisor_meta_webhook', {stored, duplicates, ignored});
    return json({});
  } catch (error) {
    const client = error instanceof ClientError;
    advisorLog(client ? 'warn' : 'error', 'advisor_webhook_failed', {channel: 'meta', type: client ? 'validation' : 'dependency', reason: String((error as Error)?.message).slice(0, 200)});
    return client ? json({error: (error as Error).message}, 400) : json({error: 'This service is temporarily unavailable.'}, 503);
  }
});
// TA-S6 end.

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

// Hardening (threat model § 9.3): the token never travels in a URL. The link is /u#<token>: the page is the same for
// everyone, reads the token from location.hash (never sent to the server) and sends it in the X-Upload-Token header.
const UPLOAD_TOKEN_HEADER = 'X-Upload-Token';
const pageHeaders = {'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex'};

/** A page shell (dist/<page>) at another path, with no token check (the token is in the fragment). */
async function tokenPage(c: Context<AppEnv>, page: string, failure: string): Promise<Response> {
  if (await overLimit(c.env.PUBLIC_LIMITER, 'advisor-upload:' + clientIP(c.req.raw))) return tooManyRequests();
  try {
    const shell = await shellResponse(c, page);
    if (!shell.ok) return NOT_FOUND();
    // Its hashed assets are linked relative to the site root.
    const html = (await shell.text()).replace(/<head>/i, '<head><base href="/">');
    return new Response(html, {status: 200, headers: pageHeaders});
  } catch (error) {
    advisorLog('error', failure, {reason: String((error as Error)?.message).slice(0, 200)});
    return json({error: 'This service is temporarily unavailable.'}, 503);
  }
}

// The upload page: the dist/upload.html shell.
advisorPublic.get('/u', c => tokenPage(c, '/upload.html', 'advisor_upload_page_failed'));

/** What an old-form link says (410). */
export const LEGACY_GONE = Object.freeze({
  upload: 'This upload link has been replaced. Text LINK to SkipperCast for a new one.',
  export: 'This data link has been replaced. Text SEND ME MY DATA to SkipperCast for a new one.',
});

/**
 * Links already sent in the old form (/u/<token>, /api/advisor/upload/<token>,
 * /api/advisor/export/<token>) answer 410 Gone, without serving anything, for 7
 * days after their token expired (so for about 8 days after they were sent);
 * anything else, or later, is the gate's 404. Answered here, never logged with the path.
 */
async function legacyTokenRoute(c: Context<AppEnv>, kind: 'upload' | 'export', page: boolean): Promise<Response> {
  const env = c.env;
  if (await overLimit(env.PUBLIC_LIMITER, `advisor-${kind}:` + clientIP(c.req.raw))) return tooManyRequests();
  try {
    if (!env.ADVISOR_PHONE_KEY) return NOT_FOUND();
    const keys = await deriveKeys(env.ADVISOR_PHONE_KEY), token = c.req.param('token') ?? '';
    const read = kind === 'upload' ? await readUploadToken(keys, token) : await readExportToken(keys, token);
    if (!read || read.expiresAt + LEGACY_LINK_GONE_MS <= Date.now()) return NOT_FOUND();
    const text = LEGACY_GONE[kind];
    return page ? new Response(`${text}\n`, {status: 410, headers: {'Content-Type': 'text/plain; charset=utf-8', 'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex', 'X-Content-Type-Options': 'nosniff'}})
      : json({error: text}, 410);
  } catch (error) {
    advisorLog('error', 'advisor_legacy_link_failed', {kind, reason: String((error as Error)?.message).slice(0, 200)});
    return json({error: 'This service is temporarily unavailable.'}, 503);
  }
}
advisorPublic.get('/u/:token', c => legacyTokenRoute(c, 'upload', true));
advisorPublic.post('/api/advisor/upload/:token', c => legacyTokenRoute(c, 'upload', false));

// One file (multipart, at most 300 MB) through ingestMedia, then a synthetic inbound message dispatched like a webhook's.
advisorPublic.post('/api/advisor/upload', async c => {
  const env = c.env;
  if (await overLimit(env.PUBLIC_LIMITER, 'advisor-upload:' + clientIP(c.req.raw))) return tooManyRequests();
  // Errors are answered here, not by the shared onError, so no log line ever sits next to the request.
  try {
    const contact = await uploadContact(env, c.req.header(UPLOAD_TOKEN_HEADER) ?? '');
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

const MEDIA_FILE = /^([\w-]{1,64})(\.story)?\.(jpg|png|mp4)$/;
const EXT_MIME: Record<string, string> = {jpg: 'image/jpeg', png: 'image/png'};
const MEDIA_HEADERS = {'Cache-Control': 'public, max-age=3600', 'X-Robots-Tag': 'noindex', 'X-Content-Type-Options': 'nosniff'};

/**
 * One `Range: bytes=` header against an object of `size` bytes (a single range:
 * `a-b`, `a-` or `-n`). null when absent or not a single bytes range (served
 * whole); 'unsatisfiable' when it starts past the end.
 */
export function byteRange(header: string | null | undefined, size: number): {offset: number; length: number} | 'unsatisfiable' | null {
  const m = header ? /^bytes=(\d*)-(\d*)$/.exec(header.trim()) : null;
  if (!m || (m[1] === '' && m[2] === '')) return null;
  if (m[1] === '') {
    const n = Number(m[2]);
    if (!n) return 'unsatisfiable';
    const length = Math.min(n, size);
    return {offset: size - length, length};
  }
  const start = Number(m[1]), end = m[2] === '' ? size - 1 : Math.min(Number(m[2]), size - 1);
  if (start >= size || end < start) return 'unsatisfiable';
  return {offset: start, length: end - start + 1};
}

/**
 * A public image: advisor/derived/<id>/public.jpg once the media job has made
 * it, else the metadata-stripped original, only for publish_state approved or
 * posted. Originals that were not stripped (HEIC, GIF, WebP, audio) are
 * never served, nor a stripped JPEG whose EXIF orientation was 2-8 (its pixels
 * are sideways without the tag; the media job's upright public.jpg is served
 * once it exists). Anything else is the same 404 as a missing id.
 *
 * TA-S2 (09 § Media that Meta fetches): <id>.story.jpg is the job's 1080 x 1920
 * story.jpg (no fallback), and <id>.mp4 is an approved or posted video with
 * single-range support (206 / 416), which Meta's video fetchers use.
 *
 * Video privacy (00 principle 7): <id>.mp4 is only ever the media job's
 * stripped copy, advisor/derived/<id>/video.mp4 (no container metadata, no
 * location atoms), served as video/mp4. The original is never served: until the
 * copy exists, or when stripping failed, the answer is the same 404.
 */
advisorPublic.get('/media/:file', async c => {
  const env = c.env, match = MEDIA_FILE.exec(c.req.param('file'));
  if (!match || !env.DB || !env.ADVISOR_MEDIA) return NOT_FOUND();
  const [, id, story, ext] = match as unknown as [string, string, string | undefined, string];
  if (story && ext !== 'jpg') return NOT_FOUND();
  const row = await env.DB.prepare('SELECT kind,mime,r2_key,exif_stripped,publish_state,orientation,derived_at,derived_error FROM advisor_media WHERE id=?').bind(id)
    .first<{kind: string; mime: string; r2_key: string; exif_stripped: number; publish_state: string; orientation: number | null; derived_at: string | null; derived_error: string | null}>();
  if (!row || !PUBLIC_STATES.has(row.publish_state)) return NOT_FOUND();
  if (ext === 'mp4') {
    if (row.kind !== 'video' || !row.r2_key || !row.derived_at || row.derived_error) return NOT_FOUND();
    const key = derivedVideoKey(id);
    const head = await env.ADVISOR_MEDIA.head(key);
    if (!head) return NOT_FOUND();
    const range = byteRange(c.req.header('range'), head.size);
    if (range === 'unsatisfiable') return new Response(null, {status: 416, headers: {...MEDIA_HEADERS, 'Content-Range': `bytes */${head.size}`, 'Accept-Ranges': 'bytes'}});
    const object = await env.ADVISOR_MEDIA.get(key, range ? {range} : {});
    if (!object) return NOT_FOUND();
    const headers: Record<string, string> = {...MEDIA_HEADERS, 'Content-Type': 'video/mp4', 'Accept-Ranges': 'bytes', 'Content-Length': String(range ? range.length : head.size)};
    if (range) headers['Content-Range'] = `bytes ${range.offset}-${range.offset + range.length - 1}/${head.size}`;
    return new Response(object.body, {status: range ? 206 : 200, headers});
  }
  if (row.kind !== 'image') return NOT_FOUND();
  let object: R2ObjectBody | null = null, type = row.mime;
  if (story) { object = await env.ADVISOR_MEDIA.get(derivedKeys(id).story); if (object) type = 'image/jpeg'; }
  else {
    if (ext === 'jpg') { object = await env.ADVISOR_MEDIA.get(derivedKey(id)); if (object) type = 'image/jpeg'; }
    const upright = (row.orientation ?? 1) === 1;
    if (!object && upright && row.r2_key && row.exif_stripped === 1 && row.mime === EXT_MIME[ext]) object = await env.ADVISOR_MEDIA.get(row.r2_key);
  }
  if (!object) return NOT_FOUND();
  return new Response(object.body, {status: 200, headers: {...MEDIA_HEADERS, 'Content-Type': type, 'Content-Length': String(object.size)}});
});

/**
 * TA-S4 (09 § Media that Meta fetches): a post's generated graphic, the media
 * job's advisor/posts/<post>/<name> (the daily card, the roundup's cover and
 * slides, a Story card), only for an approved post or one being or already
 * published, and only a name the graphic's done state lists. Anything else is
 * the same 404 as a missing id.
 */
advisorPublic.get('/media/post/:post/:name', async c => {
  const env = c.env, id = c.req.param('post'), name = c.req.param('name');
  if (!/^[\w-]{1,64}$/.test(id) || !GRAPHIC_NAME.test(name) || !env.DB || !env.ADVISOR_MEDIA) return NOT_FOUND();
  const post = await env.DB.prepare('SELECT status FROM advisor_posts WHERE id=?').bind(id).first<{status: string}>();
  if (!post || !GRAPHIC_PUBLIC_STATUSES.includes(post.status)) return NOT_FOUND();
  const key = await servableGraphic(env.DB, id, name);
  const object = key ? await env.ADVISOR_MEDIA.get(key) : null;
  if (!object) return NOT_FOUND();
  return new Response(object.body, {status: 200, headers: {...MEDIA_HEADERS, 'Content-Type': 'image/jpeg', 'Content-Length': String(object.size)}});
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
 * TA-S7: with `s=ig` and a post id `p` (^[\w-]{1,64}$, the per-post link
 * /text?s=ig&p=<post_id>, 09 § Insights) the marker is " [via ig:<p>]"; a bad `p` is dropped.
 */
export const POST_PARAM = /^[\w-]{1,64}$/;
export function textBody(message: string | null | undefined, source: string | null | undefined, post?: string | null): string {
  const clean = Array.from(String(message ?? '').replace(/[\u0000-\u001f\u007f]/g, ' ').trim()).slice(0, TEXT_MAX_MESSAGE).join('').trim();
  const valid = typeof source === 'string' && SOURCE_PATTERN.test(source) ? source : null;
  const marker = valid === 'ig' && typeof post === 'string' && POST_PARAM.test(post) ? `ig:${post}` : valid;
  return `${clean || TEXT_DEFAULT_MESSAGE}${marker ? ` [via ${marker}]` : ''}`;
}

// The `?&body=` form is the one iOS and Android both open with the body filled in (03).
advisorPublic.get('/text', c => {
  const settings = advisorSettings(c.env);
  if (!settings.number) return NO_NUMBER();
  const body = textBody(c.req.query('m'), c.req.query('s'), c.req.query('p'));
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
  // Hardening: the client address, hashed, keys the per-address limits (outbound guard, web model budget).
  const run = runInline(env, id, {channel: collector, handler: webChat.handler ?? engineHandler, ipHash: await ipHash(env.ADVISOR_PHONE_KEY, clientIP(c.req.raw))});
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
// contact or a missing object is the gate's 404. Errors are answered here.
// Hardening: the link is /my-data#<token>; the page POSTs the token in the
// X-Export-Token header, so it is in no request URL (and no Workers Logs line).
advisorPublic.get(EXPORT_PAGE, c => tokenPage(c, '/my-data.html', 'advisor_export_page_failed'));
advisorPublic.get('/api/advisor/export/:token', c => legacyTokenRoute(c, 'export', false));
advisorPublic.post('/api/advisor/export', async c => {
  const env = c.env;
  if (await overLimit(env.PUBLIC_LIMITER, 'advisor-export:' + clientIP(c.req.raw))) return tooManyRequests();
  try {
    if (!env.ADVISOR_PHONE_KEY || !env.DB || !env.ADVISOR_MEDIA) return NOT_FOUND();
    const valid = await verifyExportToken(await deriveKeys(env.ADVISOR_PHONE_KEY), c.req.header('X-Export-Token') ?? '');
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

// ---- TA-W1: public port, species and boat pages, the sitemap and robots.txt ------------
// (08 § Public pages, 05 § The boat page.) Server-rendered HTML in English or
// Spanish (?lang=es, else Accept-Language), cached at the edge under the build
// and the job_state pages version (one D1 read per request), so a publish, an
// edit, a verification or a photo decision is the purge. The per-IP limit
// applies only to renders the cache could not answer.

/** Test seam: the feed reader and clock the page reads use (the engine's EngineDeps shape). */
export const pagesDeps: PageDeps = {};
advisorPublic.use(SITEMAP_PATH, gate);

type Render = (env: Env, language: PageLanguage, settings: ReturnType<typeof advisorSettings>) => Promise<string | null>;

/** The cache key of a page: path, the resolved language, the build and the pages version. */
export const pageCacheKey = (url: URL, language: PageLanguage, version: string): Request =>
  cacheKey(`${url.origin}${url.pathname}?lang=${language}`, {params: ['lang'], build: `${build()}:${version}`});

/**
 * CF-33: the pages version with the flags that change a page's content, so flipping
 * FLEET_ENABLED (or the advisor while the fleet is on) is a cache miss. Unchanged while the
 * fleet is off, so the advisor's keys stay as they were.
 */
export const flagsVersion = (env: Env, version: string): string =>
  fleetSettings(env).enabled ? `${version}:fleet${advisorSettings(env).enabled ? '' : '-solo'}` : version;

async function servePage(c: Context<AppEnv>, maxAge: number, render: Render): Promise<Response> {
  const env = c.env, url = new URL(c.req.url);
  const language = pageLanguage(url, c.req.header('accept-language'));
  const settings = advisorSettings(env);
  try {
    if (!env.DB) return json({error: 'This service is temporarily unavailable.'}, 503);
    const key = pageCacheKey(url, language, flagsVersion(env, await pagesVersion(env.DB)));
    return await cached(key, waitUntil(c), async () => {
      const body = await render(env, language, settings);
      return {response: body === null ? pageResponse(notFoundPage(language, settings, url.pathname, settings.enabled), {status: 404, language}) : pageResponse(body, {maxAge, language})};
    }, async () => await overLimit(env.PUBLIC_LIMITER, 'advisor-page:' + clientIP(c.req.raw)) ? tooManyRequests() : null);
  } catch (error) {
    advisorLog('error', 'advisor_page_failed', {reason: String((error as Error)?.message).slice(0, 200)});
    return json({error: 'This service is temporarily unavailable.'}, 503);
  }
}

advisorPublic.get('/ports/:id', c => servePage(c, PORT_MAX_AGE, (env, language, settings) => portPage(env, c.req.param('id'), language, settings, pagesDeps)));

advisorPublic.get('/species/:key', async c => {
  const segment = c.req.param('key'), key = speciesPageKey(segment);
  // A synonym or another spelling of a page key (california-halibut, Lingcod) moves to the page's own address.
  if (key && key !== segment) return new Response(null, {status: 301, headers: {Location: `/species/${key}${new URL(c.req.url).search}`, 'Cache-Control': 'public, max-age=86400'}});
  return servePage(c, SPECIES_MAX_AGE, (env, language, settings) => key ? speciesPage(env, key, language, settings, pagesDeps) : Promise.resolve(null));
});

advisorPublic.get('/boats/:slug', c => servePage(c, BOAT_MAX_AGE, (env, language, settings) => boatPage(env, c.req.param('slug'), language, settings, pagesDeps)));

advisorPublic.get(SITEMAP_PATH, async c => {
  const env = c.env;
  if (!env.DB) return json({error: 'This service is temporarily unavailable.'}, 503);
  const key = cacheKey(new URL(SITEMAP_PATH, c.req.url), {params: [], build: `${build()}:${flagsVersion(env, await pagesVersion(env.DB))}`});
  return cached(key, waitUntil(c), async () => ({response: new Response(await sitemapXml(env.DB!, advisorSettings(env).publicBase, {fleet: fleetSettings(env).enabled}), {status: 200, headers: {
    'Content-Type': 'application/xml; charset=utf-8', 'Cache-Control': `public, max-age=${SITEMAP_MAX_AGE}`, 'X-Content-Type-Options': 'nosniff'}})}));
});

// No robots.txt is published: while the advisor is dark the request falls through to the
// static site exactly as before; when it is on, the Worker answers with the sitemap line.
advisorPublic.get('/robots.txt', async (c, next) => {
  const settings = advisorSettings(c.env);
  if (!settings.enabled) { await next(); return; }
  return new Response(robotsTxt(settings.publicBase), {status: 200, headers: {'Content-Type': 'text/plain; charset=utf-8', 'Cache-Control': 'public, max-age=3600'}});
});
// TA-W1 end.
