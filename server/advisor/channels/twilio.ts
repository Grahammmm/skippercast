// Twilio adapter: SMS/MMS on the advisor's number after a port
// (docs/plans/text-advisor/03-channels.md § Twilio adapter). Dark until the
// owner sets ADVISOR_CHANNEL=twilio (03 § runbook); its inbound and status
// webhooks are always mounted so a port in progress loses nothing.
//
// Inbound: Twilio POSTs application/x-www-form-urlencoded and signs it with
// X-Twilio-Signature = base64(HMAC-SHA1(auth token, public URL + every POST
// parameter as key+value, sorted by key)). The public URL is rebuilt from
// ADVISOR_PUBLIC_BASE + the request path + query, never from the Host header,
// and the signature is checked with WebCrypto's HMAC verify (constant time).
//
// Outbound: POST /2010-04-01/Accounts/<sid>/Messages.json with Basic auth
// (account sid : auth token), a 15 s timeout and one retry on a network error,
// as BlueBubbles does; never on an HTTP status (a 4xx is final, and after a 5xx or a
// timeout Twilio may already have accepted the message, so the row is 'unknown').
// Error 21610 (the recipient texted STOP to Twilio) stops the contact.
//
// The number is decrypted from the contact's phone_enc blob inside send() only
// (02 § privacy invariants). Neither the auth token nor a number is ever logged
// or returned as an error: errors are short codes.
import {advisorSettings} from '../settings.ts';
import {applyStop, decryptPhone, deriveKeys, e164, phoneHash} from '../contacts.ts';
import {advisorLog} from '../log.ts';
import {ClientError} from '../../errors.ts';
import type {Env} from '../../env.ts';
import type {OutboundMessage, SendResult} from '../types.ts';
import type {ChannelAdapter, InboundMedia, InboundMessage} from './index.ts';

export const API_BASE = 'https://api.twilio.com';
export const TIMEOUT_MS = 15000;
export const HEALTH_TIMEOUT_MS = 10000;
export const DOWNLOAD_TIMEOUT_MS = 60000;
export const MAX_WEBHOOK_BYTES = 65536;
export const MAX_MEDIA_BYTES = 5 * 1024 * 1024;   // Twilio MMS: 5 MB total per message
export const MAX_MEDIA_URLS = 10;                 // Twilio: at most 10 MediaUrl per message
export const SEGMENTS = 3;                        // splitForChannel's 480-character SMS chunks
export const OPTED_OUT = 21610;                   // "Attempt to send to unsubscribed recipient"
/** The empty TwiML reply: Twilio sends nothing back on its own; the engine replies through send(). */
export const TWIML_EMPTY = '<?xml version="1.0" encoding="UTF-8"?><Response/>';

export type Fetcher = (url: string, init: RequestInit) => Promise<Response>;
export interface TwilioOptions {fetcher?: Fetcher}

const SID = /^AC[0-9a-f]{32}$/;
const MESSAGE_SID = /^[A-Z]{2}[0-9a-f]{32}$/;
const E164 = /^\+[1-9]\d{6,14}$/;
const encoder = new TextEncoder();

interface TwilioConfig {sid: string; token: string; auth: string}
/** The account sid and auth token when both are set and the sid is well formed. */
function twilioConfig(env: Env): TwilioConfig | null {
  const sid = (env.TWILIO_ACCOUNT_SID ?? '').trim(), token = (env.TWILIO_AUTH_TOKEN ?? '').trim();
  if (!SID.test(sid) || !token) return null;
  return {sid, token, auth: 'Basic ' + btoa(`${sid}:${token}`)};
}

const errorCode = (error: unknown): string => (error as Error)?.name === 'TimeoutError' || (error as Error)?.name === 'AbortError' ? 'timeout' : 'network';

// ---- signature --------------------------------------------------------------------

/**
 * The string Twilio signs: the URL, then each parameter name followed by its
 * value, names in code-unit order; a repeated name contributes each of its
 * values, sorted (as twilio-node's validateRequest does).
 */
export function signedData(url: string, params: URLSearchParams | Record<string, string>): string {
  const grouped = new Map<string, string[]>();
  const entries = params instanceof URLSearchParams ? [...params.entries()] : Object.entries(params);
  for (const [k, v] of entries) grouped.set(k, [...(grouped.get(k) ?? []), v]);
  let data = url;
  for (const key of [...grouped.keys()].sort()) for (const value of [...grouped.get(key)!].sort()) data += key + value;
  return data;
}

const hmacKey = (token: string, usage: 'sign' | 'verify'): Promise<CryptoKey> =>
  crypto.subtle.importKey('raw', encoder.encode(token), {name: 'HMAC', hash: 'SHA-1'}, false, [usage]);

/** base64(HMAC-SHA1(token, signedData(url, params))): what X-Twilio-Signature must be. */
export async function twilioSignature(token: string, url: string, params: URLSearchParams | Record<string, string>): Promise<string> {
  const mac = new Uint8Array(await crypto.subtle.sign('HMAC', await hmacKey(token, 'sign'), encoder.encode(signedData(url, params))));
  let s = ''; for (const b of mac) s += String.fromCharCode(b);
  return btoa(s);
}

/** True when `signature` is the valid header for (url, params). HMAC verify compares in constant time. */
export async function verifySignature(token: string, url: string, params: URLSearchParams, signature: string | null): Promise<boolean> {
  if (!token || !signature || signature.length > 100 || !/^[A-Za-z0-9+/]+=*$/.test(signature)) return false;
  let given: Uint8Array<ArrayBuffer>;
  try { given = Uint8Array.from(atob(signature), c => c.charCodeAt(0)); } catch { return false; }
  return crypto.subtle.verify('HMAC', await hmacKey(token, 'verify'), given, encoder.encode(signedData(url, params)));
}

/** The URL Twilio was configured with: ADVISOR_PUBLIC_BASE + the raw request path + query, never the Host header. */
export function publicUrl(request: Request, env: Env): string {
  const url = new URL(request.url);
  return advisorSettings(env).publicBase + url.pathname + url.search;
}

/** The form body as parameters, read as a stream and capped at 64 KB (ClientError 'body too large' beyond). */
export async function readForm(request: Request, max = MAX_WEBHOOK_BYTES): Promise<URLSearchParams> {
  if (Number(request.headers.get('content-length')) > max) throw new ClientError('body too large');
  const reader = request.body?.getReader();
  if (!reader) return new URLSearchParams();
  const chunks: Uint8Array[] = []; let size = 0;
  for (;;) {
    const {done, value} = await reader.read();
    if (done) break;
    size += value.length;
    if (size > max) { await reader.cancel(); throw new ClientError('body too large'); }
    chunks.push(value);
  }
  const bytes = new Uint8Array(size); let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  return new URLSearchParams(new TextDecoder().decode(bytes));
}

/**
 * A Twilio webhook request's parameters when its signature is valid for our
 * public URL (and its AccountSid is ours), else 'unauthorized'. Used by the
 * inbound webhook and the status callback.
 */
export async function verifiedParams(request: Request, env: Env): Promise<URLSearchParams | 'unauthorized'> {
  const config = twilioConfig(env);
  const params = await readForm(request);
  if (!config) return 'unauthorized';
  if (!await verifySignature(config.token, publicUrl(request, env), params, request.headers.get('x-twilio-signature'))) return 'unauthorized';
  const account = params.get('AccountSid');
  if (account != null && account !== config.sid) return 'unauthorized';
  return params;
}

// ---- media ------------------------------------------------------------------------

/** A Twilio media URL we may fetch with our credentials: https://api.twilio.com/..., nothing else. */
export function isTwilioMediaUrl(ref: string): boolean {
  if (typeof ref !== 'string' || ref.length > 500) return false;
  try {
    const u = new URL(ref);
    return u.origin === API_BASE && !u.username && !u.password && ref.startsWith(API_BASE + '/');
  } catch { return false; }
}

/**
 * GET a media URL with Basic auth (60 s). Twilio answers with a redirect to a
 * short-lived signed URL on its CDN; that hop is followed without the
 * Authorization header, so the credentials only ever go to api.twilio.com.
 */
async function downloadMedia(ref: string, env: Env, fetcher: Fetcher): Promise<Response> {
  const config = twilioConfig(env);
  if (!config) throw Error('twilio not configured');
  if (!isTwilioMediaUrl(ref)) throw Error('not a Twilio media URL');
  const signal = AbortSignal.timeout(DOWNLOAD_TIMEOUT_MS);
  const first = await fetcher(ref, {headers: {Authorization: config.auth}, redirect: 'manual', signal});
  if (first.status < 300 || first.status > 399) return first;
  const location = first.headers.get('location');
  if (!location) return first;
  const next = new URL(location, ref);
  if (next.protocol !== 'https:') throw Error('media redirect is not https');
  return fetcher(next.toString(), {signal});
}

// ---- adapter ----------------------------------------------------------------------

/** Twilio's JSON error / message body (only the fields read here). */
interface TwilioBody {sid?: unknown; status?: unknown; error_code?: unknown; code?: unknown}

const MEDIA_ID = /^[\w-]{1,64}$/;
const DERIVED = /^advisor\/derived\/([\w-]{1,64})\/public\.jpg$/;
const PUBLIC_STATES = new Set(['approved', 'posted']);

/** Build the Twilio adapter. `fetcher` is injectable for tests (default: the global fetch). */
export function createTwilio(options: TwilioOptions = {}): ChannelAdapter & {mediaUrls(env: Env, keys: string[]): Promise<string[] | string>} {
  const doFetch: Fetcher = (url, init) => (options.fetcher ?? fetch)(url, init);

  /** One API call: Basic auth, timeout, one retry on a network error (never on a status or a timeout). Never throws. */
  async function call(config: TwilioConfig, path: string, init: {method?: string; form?: URLSearchParams; timeoutMs?: number} = {}): Promise<{status: number; body: TwilioBody | null; error?: string}> {
    const headers: Record<string, string> = {Authorization: config.auth, Accept: 'application/json'};
    if (init.form) headers['Content-Type'] = 'application/x-www-form-urlencoded';
    let response: Response | null = null, failure = '';
    for (let attempt = 0; attempt < 2 && !response; attempt++) {
      try { response = await doFetch(`${API_BASE}/2010-04-01/Accounts/${config.sid}${path}`, {method: init.method ?? 'GET', headers, body: init.form?.toString(), signal: AbortSignal.timeout(init.timeoutMs ?? TIMEOUT_MS)}); }
      catch (error) { failure = errorCode(error); if (failure === 'timeout') break; }
    }
    if (!response) return {status: 0, body: null, error: failure};
    let body: TwilioBody | null = null;
    try { body = await response.json() as TwilioBody; } catch { body = null; }
    return {status: response.status, body};
  }

  /** The clear number from a stored phone_enc blob, or null. */
  async function number(env: Env, to: string): Promise<string | null> {
    if (!env.ADVISOR_PHONE_KEY || typeof to !== 'string' || !to) return null;
    try { return await decryptPhone(await deriveKeys(env.ADVISOR_PHONE_KEY), to); } catch { return null; }
  }

  /**
   * Public URLs for R2 keys: ${publicBase}/media/<id>.jpg, the TA-C4 media
   * route Twilio fetches. A derived key carries its media id; any other key is
   * looked up by advisor_media.r2_key. The route serves only approved or posted
   * media, so anything else is an error code here rather than an MMS Twilio
   * cannot fetch.
   */
  async function mediaUrls(env: Env, keys: string[]): Promise<string[] | string> {
    if (!keys.length) return [];
    if (keys.length > MAX_MEDIA_URLS) return 'too-many-media';
    if (!env.DB) return 'no-storage';
    const base = advisorSettings(env).publicBase, urls: string[] = [];
    for (const key of keys) {
      const derived = DERIVED.exec(key)?.[1];
      const row = await (derived
        ? env.DB.prepare('SELECT id,publish_state FROM advisor_media WHERE id=?').bind(derived)
        : env.DB.prepare("SELECT id,publish_state FROM advisor_media WHERE r2_key=? AND r2_key<>'' LIMIT 1").bind(key)).first<{id: string; publish_state: string}>();
      if (!row || !MEDIA_ID.test(row.id)) return 'media-missing';
      if (!PUBLIC_STATES.has(row.publish_state)) return 'media-not-public';
      urls.push(`${base}/media/${row.id}.jpg`);
    }
    return urls;
  }

  /** 21610: Twilio holds a STOP from this number, so the contact is stopped here too (FC-4). */
  async function stopRecipient(env: Env, phone: string): Promise<void> {
    if (!env.DB || !env.ADVISOR_PHONE_KEY) return;
    const hash = await phoneHash(await deriveKeys(env.ADVISOR_PHONE_KEY), phone);
    const contact = await env.DB.prepare('SELECT id FROM advisor_contacts WHERE phone_hash=?').bind(hash).first<{id: string}>();
    if (contact) await applyStop(env.DB, contact.id);
    advisorLog('warn', 'advisor_twilio_opted_out', {stopped: Boolean(contact)});
  }

  async function send(message: OutboundMessage, env: Env): Promise<SendResult> {
    const config = twilioConfig(env), from = (env.TWILIO_FROM ?? '').trim();
    if (!config || !E164.test(from)) return {providerId: null, status: 'failed', error: 'not-configured'};
    const phone = await number(env, message.to);
    if (!phone) return {providerId: null, status: 'failed', error: env.ADVISOR_PHONE_KEY ? 'bad-address' : 'no-phone-key'};
    const text = typeof message.text === 'string' ? message.text : '';
    const urls = await mediaUrls(env, message.mediaKeys ?? []);
    if (typeof urls === 'string') return {providerId: null, status: 'failed', error: urls};
    if (!text.trim() && !urls.length) return {providerId: null, status: 'failed', error: 'empty'};
    const form = new URLSearchParams({To: phone, From: from});
    if (text.trim()) form.set('Body', text);
    for (const url of urls) form.append('MediaUrl', url);
    if (env.ADVISOR_WEBHOOK_TOKEN) form.set('StatusCallback', `${advisorSettings(env).publicBase}/api/advisor/inbound/twilio-status/${encodeURIComponent(env.ADVISOR_WEBHOOK_TOKEN)}`);
    const r = await call(config, '/Messages.json', {method: 'POST', form});
    if (r.error) return {providerId: null, status: r.error === 'timeout' ? 'unknown' : 'failed', error: r.error};
    const code = typeof r.body?.code === 'number' ? r.body.code : typeof r.body?.error_code === 'number' ? r.body.error_code : null;
    if (code === OPTED_OUT) { await stopRecipient(env, phone); return {providerId: null, status: 'failed', error: 'opted-out'}; }
    // After a 5xx Twilio may still have queued it: 'unknown', never resent blindly.
    if (r.status >= 500) return {providerId: null, status: 'unknown', error: `http-${r.status}`};
    if (r.status < 200 || r.status > 299) return {providerId: null, status: 'failed', error: code ? `twilio-${code}` : `http-${r.status}`};
    const sid = typeof r.body?.sid === 'string' && MESSAGE_SID.test(r.body.sid) ? r.body.sid : null;
    if (code || r.body?.status === 'failed' || r.body?.status === 'undelivered') return {providerId: sid, status: 'failed', error: code ? `twilio-${code}` : 'twilio-failed'};
    if (!sid) return {providerId: null, status: 'unknown', error: 'no-sid'};
    return {providerId: sid, status: 'sent'};
  }

  async function health(env: Env): Promise<{ok: boolean; detail: string}> {
    const config = twilioConfig(env);
    if (!config) return {ok: false, detail: 'not-configured'};
    const r = await call(config, '.json', {timeoutMs: HEALTH_TIMEOUT_MS});
    if (r.error) return {ok: false, detail: `account ${r.error}`};
    const status = typeof r.body?.status === 'string' ? r.body.status.replace(/[^\w-]/g, '').slice(0, 20) : 'unknown';
    return r.status === 200 ? {ok: true, detail: `account ${status}`} : {ok: false, detail: `account http-${r.status}`};
  }

  return {
    name: 'twilio',
    normalize: (request, env) => normalize(request, env, doFetch),
    send, health, mediaUrls,
    fetchMediaByRef: (ref, env) => downloadMedia(ref, env, doFetch),
    capabilities: {media: true, maxMediaBytes: MAX_MEDIA_BYTES, typing: false, read: false, segments: SEGMENTS},
  };
}

// ---- webhooks -------------------------------------------------------------------

function drop(reason: string): 'ignore' { advisorLog('info', 'advisor_twilio_dropped', {reason, count: 1}); return 'ignore'; }

/**
 * Signed inbound parameters as one InboundMessage. STOP, HELP and every other
 * keyword arrive as plain text: whatever Twilio forwards reaches the engine,
 * which owns the STOP/START/HELP paths (OptOutType is not needed for that).
 */
export function inboundFromParams(params: URLSearchParams, env: Env, fetcher: Fetcher = (url, init) => fetch(url, init)): InboundMessage[] | 'ignore' {
  // A status callback posted to the inbound URL, or anything that is not a received message.
  if (params.has('MessageStatus')) return drop('status');
  const smsStatus = params.get('SmsStatus');
  if (smsStatus != null && smsStatus !== 'received') return drop('status');
  const providerId = params.get('MessageSid') ?? params.get('SmsMessageSid') ?? '';
  if (!MESSAGE_SID.test(providerId)) return drop('no-sid');
  const from = e164(params.get('From'));
  if (!from) return drop('not-nanp');
  const text = (params.get('Body') ?? '').trim();
  const count = Math.min(MAX_MEDIA_URLS, Math.max(0, Math.floor(Number(params.get('NumMedia') ?? 0)) || 0));
  const media: InboundMedia[] = [];
  for (let i = 0; i < count; i++) {
    const url = params.get(`MediaUrl${i}`) ?? '';
    if (!isTwilioMediaUrl(url)) continue;
    const mime = params.get(`MediaContentType${i}`);
    media.push({providerRef: url, mime: mime && mime.length <= 100 ? mime : null, bytes: null, name: null, fetch: (e: Env) => downloadMedia(url, e, fetcher)});
  }
  if (!text && !media.length) return drop('empty');
  return [{channel: 'sms', providerId, from, to: e164(params.get('To')) ?? advisorSettings(env).number ?? '', text, media, receivedAt: new Date().toISOString(), isGroup: false}];
}

/** The inbound webhook (already token-checked by the route): body capped at 64 KB, signature, then inboundFromParams. */
async function normalize(request: Request, env: Env, fetcher: Fetcher): Promise<InboundMessage[] | 'ignore' | 'unauthorized'> {
  const params = await verifiedParams(request, env);
  if (params === 'unauthorized') return 'unauthorized';
  return inboundFromParams(params, env, fetcher);
}

/**
 * A status callback (signed like the inbound webhook) applied to our outbound
 * row by provider_id: delivered or sent confirms it ('sent'), undelivered or
 * failed marks it 'failed' with twilio-<ErrorCode>; 21610 also stops the
 * contact. Other statuses (queued, accepted, sending) change nothing.
 */
export async function statusCallback(request: Request, env: Env): Promise<'unauthorized' | 'ok'> {
  const params = await verifiedParams(request, env);
  if (params === 'unauthorized') return 'unauthorized';
  const sid = params.get('MessageSid') ?? params.get('SmsSid') ?? '', status = params.get('MessageStatus') ?? params.get('SmsStatus') ?? '';
  if (!env.DB || !MESSAGE_SID.test(sid)) return 'ok';
  const row = await env.DB.prepare("SELECT id,contact_id FROM advisor_messages WHERE direction='out' AND channel='sms' AND provider_id=? LIMIT 1").bind(sid).first<{id: string; contact_id: string}>();
  if (!row) return 'ok';
  if (status === 'delivered' || status === 'sent') {
    await env.DB.prepare("UPDATE advisor_messages SET status='sent',error=NULL,sent_at=COALESCE(sent_at,?) WHERE id=? AND status IN ('sending','unknown','sent')")
      .bind(new Date().toISOString(), row.id).run();
  } else if (status === 'undelivered' || status === 'failed') {
    const code = Number(params.get('ErrorCode'));
    const valid = Number.isInteger(code) && code > 0;
    await env.DB.prepare("UPDATE advisor_messages SET status='failed',error=? WHERE id=? AND status IN ('sending','sent','unknown')")
      .bind(code === OPTED_OUT ? 'opted-out' : valid ? `twilio-${code}` : 'twilio-failed', row.id).run();
    if (code === OPTED_OUT) await applyStop(env.DB, row.contact_id);
    advisorLog('warn', 'advisor_twilio_undelivered', {code: valid ? code : null});
  }
  return 'ok';
}

export const twilio = createTwilio();
