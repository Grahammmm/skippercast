// BlueBubbles adapter: the Mac relay's REST API and webhook normalizer
// (docs/plans/text-advisor/03-channels.md § BlueBubbles adapter).
//
// Every call goes to {BLUEBUBBLES_URL}/api/v1/... with ?password=<server
// password> and the Cloudflare Access service-token headers, a 15 s timeout and
// one retry on a network error (never on an HTTP status or a timeout, where
// the relay may already have acted). Responses are {status, message, data,
// error?}; a 200 whose body carries `error` is a failure (seen on SMS sends).
// The URL carries the password, so neither a URL nor a response body is ever
// logged or returned as an error: errors are short codes.
//
// The number is decrypted from the contact's phone_enc blob inside send(),
// typing() and markRead() only (02 § privacy invariants).
import {advisorSettings} from '../settings.ts';
import {decryptPhone, deriveKeys, e164} from '../contacts.ts';
import {advisorLog} from '../log.ts';
import {body as readBody} from '../../http.ts';
import type {Env} from '../../env.ts';
import type {OutboundMessage, SendResult} from '../types.ts';
import type {ChannelAdapter, InboundMedia, InboundMessage} from './index.ts';

export const TIMEOUT_MS = 15000;
export const HEALTH_TIMEOUT_MS = 10000;
export const DOWNLOAD_TIMEOUT_MS = 60000;
export const MAX_WEBHOOK_BYTES = 65536;
export const MAX_MEDIA_BYTES = 100 * 1024 * 1024;

export type Fetcher = (url: string, init: RequestInit) => Promise<Response>;
export interface BlueBubblesOptions {fetcher?: Fetcher}

/** BlueBubbles' response envelope. */
export interface Envelope {status?: number; message?: string; data?: unknown; error?: unknown}
interface CallResult {ok: boolean; status: number; envelope: Envelope | null; error?: string}

const GUID = /^[\w.:;+@-]{1,200}$/;
const HEX_ID = /^[0-9a-f]{32}/;

function relayConfig(env: Env): {base: string; password: string; headers: Record<string, string>} | null {
  const base = (env.BLUEBUBBLES_URL ?? '').trim().replace(/\/+$/, '');
  if (!base || !env.BLUEBUBBLES_PASSWORD) return null;
  try { if (new URL(base).protocol !== 'https:' && !/^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(base)) return null; } catch { return null; }
  const headers: Record<string, string> = {Accept: 'application/json'};
  if (env.CF_ACCESS_CLIENT_ID && env.CF_ACCESS_CLIENT_SECRET) {
    headers['CF-Access-Client-Id'] = env.CF_ACCESS_CLIENT_ID;
    headers['CF-Access-Client-Secret'] = env.CF_ACCESS_CLIENT_SECRET;
  }
  return {base, password: env.BLUEBUBBLES_PASSWORD, headers};
}

/** The URL of an API path with the password appended. Never logged. */
function apiUrl(base: string, password: string, path: string, query: Record<string, string> = {}): string {
  const url = new URL(base + '/api/v1/' + path.replace(/^\/+/, ''));
  for (const [k, v] of Object.entries(query)) url.searchParams.set(k, v);
  url.searchParams.set('password', password);
  return url.toString();
}

/** A 200-with-`error` body, a non-200 `status` inside the body, or `data.error` set: a failure. */
export function envelopeError(envelope: Envelope | null): string | null {
  if (!envelope || typeof envelope !== 'object') return 'not-json';
  if (envelope.error != null && envelope.error !== false && envelope.error !== '') return 'relay-error';
  if (typeof envelope.status === 'number' && (envelope.status < 200 || envelope.status > 299)) return `relay-status-${envelope.status}`;
  const data = envelope.data as {error?: unknown} | null | undefined;
  if (data && typeof data === 'object' && typeof data.error === 'number' && data.error !== 0) return `message-error-${data.error}`;
  return null;
}

const errorCode = (error: unknown): string => (error as Error)?.name === 'TimeoutError' || (error as Error)?.name === 'AbortError' ? 'timeout' : 'network';

/** Build the BlueBubbles adapter. `fetcher` is injectable for tests (default: the global fetch). */
export function createBlueBubbles(options: BlueBubblesOptions = {}): ChannelAdapter & {
  call(env: Env, path: string, init?: {method?: string; json?: unknown; form?: FormData; query?: Record<string, string>; timeoutMs?: number}): Promise<CallResult>;
} {
  const doFetch: Fetcher = (url, init) => (options.fetcher ?? fetch)(url, init);

  /** One API call: timeout, one retry on a network error, envelope parsed. Never throws. */
  async function call(env: Env, path: string, init: {method?: string; json?: unknown; form?: FormData; query?: Record<string, string>; timeoutMs?: number} = {}): Promise<CallResult> {
    const config = relayConfig(env);
    if (!config) return {ok: false, status: 0, envelope: null, error: 'not-configured'};
    const headers: Record<string, string> = {...config.headers};
    let payload: BodyInit | undefined;
    if (init.json !== undefined) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(init.json); }
    else if (init.form) payload = init.form;
    const url = apiUrl(config.base, config.password, path, init.query);
    let response: Response | null = null, failure = '';
    for (let attempt = 0; attempt < 2 && !response; attempt++) {
      try { response = await doFetch(url, {method: init.method ?? 'GET', headers, body: payload, signal: AbortSignal.timeout(init.timeoutMs ?? TIMEOUT_MS)}); }
      catch (error) { failure = errorCode(error); if (failure === 'timeout') break; }
    }
    if (!response) return {ok: false, status: 0, envelope: null, error: failure};
    let envelope: Envelope | null = null;
    try { envelope = await response.json() as Envelope; } catch { envelope = null; }
    if (!response.ok) return {ok: false, status: response.status, envelope, error: `http-${response.status}`};
    const bad = envelopeError(envelope);
    return bad ? {ok: false, status: response.status, envelope, error: bad} : {ok: true, status: response.status, envelope};
  }

  /** The clear number from a stored phone_enc blob, or null. */
  async function number(env: Env, to: string): Promise<string | null> {
    if (!env.ADVISOR_PHONE_KEY || typeof to !== 'string' || !to) return null;
    try { return await decryptPhone(await deriveKeys(env.ADVISOR_PHONE_KEY), to); } catch { return null; }
  }

  /** The chat GUID: from the contact's last channel, else from iMessage availability (SMS when unknown). */
  async function chatGuid(env: Env, phone: string, hint: OutboundMessage['channelHint']): Promise<string> {
    if (hint === 'imessage') return `iMessage;-;${phone}`;
    if (hint === 'sms') return `SMS;-;${phone}`;
    const check = await call(env, 'handle/availability/imessage', {query: {address: phone}});
    const available = check.ok && (check.envelope?.data as {available?: unknown} | undefined)?.available === true;
    if (!check.ok) advisorLog('warn', 'advisor_bluebubbles_availability_failed', {error: check.error});
    return available ? `iMessage;-;${phone}` : `SMS;-;${phone}`;
  }

  const guidOf = (r: CallResult): string | null => {
    const guid = (r.envelope?.data as {guid?: unknown} | undefined)?.guid;
    return typeof guid === 'string' && guid ? guid : null;
  };

  async function send(message: OutboundMessage, env: Env): Promise<SendResult> {
    if (!relayConfig(env)) return {providerId: null, status: 'failed', error: 'not-configured'};
    const phone = await number(env, message.to);
    if (!phone) return {providerId: null, status: 'failed', error: env.ADVISOR_PHONE_KEY ? 'bad-address' : 'no-phone-key'};
    const settings = advisorSettings(env), method = settings.privateApi ? 'private-api' : 'apple-script';
    const chat = await chatGuid(env, phone, message.channelHint);
    let providerId: string | null = null, sentSomething = false;
    const text = typeof message.text === 'string' ? message.text : '';
    if (text.trim()) {
      const payload: Record<string, unknown> = {chatGuid: chat, tempGuid: message.id, message: text, method};
      if (settings.privateApi && message.replyToProviderId && GUID.test(message.replyToProviderId)) { payload.selectedMessageGuid = message.replyToProviderId; payload.partIndex = 0; }
      const r = await call(env, 'message/text', {method: 'POST', json: payload});
      if (!r.ok) return {providerId: null, status: r.error === 'timeout' ? 'unknown' : 'failed', error: r.error};
      providerId = guidOf(r); sentSomething = true;
    }
    for (const [i, key] of (message.mediaKeys ?? []).entries()) {
      const failed = (error: string): SendResult => sentSomething
        // Text already went out: never 'failed', which would resend it.
        ? {providerId, status: 'unknown', error: `media-${error}`}
        : {providerId: null, status: error === 'timeout' ? 'unknown' : 'failed', error};
      const object = env.ADVISOR_MEDIA ? await env.ADVISOR_MEDIA.get(key) : null;
      if (!object) return failed('missing');
      if (object.size > MAX_MEDIA_BYTES) return failed('too-large');
      const name = key.split('/').pop() || 'photo.jpg';
      const form = new FormData();
      form.set('attachment', new File([await object.arrayBuffer()], name, {type: object.httpMetadata?.contentType || 'image/jpeg'}));
      form.set('chatGuid', chat);
      form.set('name', name);
      form.set('tempGuid', `${message.id}-m${i}`);
      const r = await call(env, 'message/attachment', {method: 'POST', form});
      if (!r.ok) return failed(r.error ?? 'error');
      providerId ??= guidOf(r); sentSomething = true;
    }
    if (!sentSomething) return {providerId: null, status: 'failed', error: 'empty'};
    return {providerId, status: 'sent'};
  }

  async function typing(to: string, on: boolean, env: Env): Promise<void> {
    if (!advisorSettings(env).privateApi) return;
    const phone = await number(env, to);
    if (!phone) return;
    const r = await call(env, `chat/${encodeURIComponent(`iMessage;-;${phone}`)}/typing`, {method: on ? 'POST' : 'DELETE'});
    if (!r.ok) advisorLog('warn', 'advisor_bluebubbles_typing_failed', {error: r.error});
  }

  async function markRead(to: string, env: Env): Promise<void> {
    if (!advisorSettings(env).privateApi) return;
    const phone = await number(env, to);
    if (!phone) return;
    const r = await call(env, `chat/${encodeURIComponent(`iMessage;-;${phone}`)}/read`, {method: 'POST'});
    if (!r.ok) advisorLog('warn', 'advisor_bluebubbles_read_failed', {error: r.error});
  }

  async function health(env: Env): Promise<{ok: boolean; detail: string}> {
    if (!relayConfig(env)) return {ok: false, detail: 'not-configured'};
    const deadline = Date.now() + HEALTH_TIMEOUT_MS;
    const ping = await call(env, 'ping', {timeoutMs: HEALTH_TIMEOUT_MS});
    if (!ping.ok) return {ok: false, detail: `ping ${ping.error}`};
    const info = await call(env, 'server/info', {timeoutMs: Math.max(1000, deadline - Date.now())});
    if (!info.ok) return {ok: false, detail: `server/info ${info.error}`};
    return {ok: true, detail: serverInfoDetail(info.envelope?.data)};
  }

  return {
    name: 'bluebubbles',
    normalize: (request, env) => normalize(request, env, doFetch),
    send, typing, markRead, health, call,
    // typing/read work only with BLUEBUBBLES_PRIVATE_API=true; the methods no-op otherwise.
    capabilities: {media: true, maxMediaBytes: MAX_MEDIA_BYTES, typing: true, read: true, segments: null},
  };
}

/** "version 1.9.9, private API on, helper connected, macOS 15.1" from server/info's data. */
export function serverInfoDetail(data: unknown): string {
  const d = (data && typeof data === 'object' ? data : {}) as Record<string, unknown>;
  const s = (v: unknown) => typeof v === 'string' ? v.replace(/[^\w .:-]/g, '').slice(0, 40) : '';
  const parts = [`version ${s(d.server_version) || 'unknown'}`, `private API ${d.private_api === true ? 'on' : 'off'}`];
  if (typeof d.helper_connected === 'boolean') parts.push(`helper ${d.helper_connected ? 'connected' : 'not connected'}`);
  if (s(d.os_version)) parts.push(`macOS ${s(d.os_version)}`);
  return parts.join(', ');
}

// ---- webhooks -------------------------------------------------------------------

/** What a webhook's message `data` looks like (only the fields read here). */
interface BBMessage {
  guid?: unknown; tempGuid?: unknown; text?: unknown; isFromMe?: unknown; itemType?: unknown; dateCreated?: unknown;
  associatedMessageGuid?: unknown; associatedMessageType?: unknown; isDelivered?: unknown; dateDelivered?: unknown; dateRead?: unknown; error?: unknown;
  handle?: {address?: unknown; service?: unknown} | null;
  chats?: {guid?: unknown; style?: unknown}[] | null;
  attachments?: {guid?: unknown; mimeType?: unknown; transferName?: unknown; totalBytes?: unknown; width?: unknown; height?: unknown}[] | null;
}

const GROUP_STYLE = 43;   // chat.style: 43 group, 45 one-to-one
const str = (v: unknown, max = 200): string | null => typeof v === 'string' && v.length <= max ? v : null;
const num = (v: unknown): number | null => typeof v === 'number' && Number.isFinite(v) && v >= 0 ? Math.floor(v) : null;

/** Why a new-message is skipped, or null when it is a real inbound (03 § BlueBubbles normalize). */
export function skipReason(data: BBMessage): string | null {
  if (data.isFromMe === true) return 'from-me';
  if ((data.associatedMessageType != null && data.associatedMessageType !== 0 && data.associatedMessageType !== '') || (typeof data.associatedMessageGuid === 'string' && data.associatedMessageGuid)) return 'reaction';
  if (data.itemType != null && data.itemType !== 0) return 'item-type';
  const chats = Array.isArray(data.chats) ? data.chats : [];
  if (chats.length > 1 || chats.some(c => c?.style === GROUP_STYLE || (typeof c?.guid === 'string' && c.guid.includes(';+;')))) return 'group';
  return null;
}

function drop(reason: string): 'ignore' { advisorLog('info', 'advisor_bluebubbles_dropped', {reason, count: 1}); return 'ignore'; }

function inbound(data: BBMessage, env: Env, fetcher: Fetcher): InboundMessage[] | 'ignore' {
  const skip = skipReason(data);
  if (skip) return drop(skip);
  const providerId = str(data.guid);
  if (!providerId || !GUID.test(providerId)) return drop('no-guid');
  const from = e164(data.handle?.address);
  if (!from) return drop('not-nanp');
  const service = typeof data.handle?.service === 'string' ? data.handle.service.toLowerCase() : '';
  // U+FFFC is the placeholder iMessage puts in the text where an attachment sits.
  const text = typeof data.text === 'string' ? data.text.replace(/￼/g, '').trim() : '';
  const media: InboundMedia[] = [];
  for (const a of Array.isArray(data.attachments) ? data.attachments : []) {
    const guid = str(a?.guid);
    if (!guid || !GUID.test(guid)) continue;
    media.push({
      providerRef: guid, mime: str(a.mimeType, 100), bytes: num(a.totalBytes), name: str(a.transferName, 200),
      width: num(a.width), height: num(a.height),
      fetch: async (e: Env) => {
        const config = relayConfig(e);
        if (!config) throw Error('relay not configured');
        return fetcher(apiUrl(config.base, config.password, `attachment/${encodeURIComponent(guid)}/download`), {headers: config.headers, signal: AbortSignal.timeout(DOWNLOAD_TIMEOUT_MS)});
      },
    });
  }
  if (!text && !media.length) return drop('empty');
  const created = num(data.dateCreated);
  return [{
    channel: service === 'imessage' ? 'imessage' : 'sms', providerId, from, to: advisorSettings(env).number ?? '',
    text, media, receivedAt: new Date(created ?? Date.now()).toISOString(), isGroup: false,
  }];
}

/** Our outbound row for a webhook's message: by provider guid, or by tempGuid (= our outbound id, plus "-m<i>" for media). */
async function outboundRow(db: D1Database, data: BBMessage): Promise<{id: string; status: string} | null> {
  const guid = str(data.guid), temp = str(data.tempGuid), byId = temp && HEX_ID.test(temp) ? temp.slice(0, 32) : null;
  if (!guid && !byId) return null;
  return db.prepare("SELECT id,status FROM advisor_messages WHERE direction='out' AND channel IN ('imessage','sms') AND (provider_id=? OR id=?) LIMIT 1")
    .bind(guid ?? '', byId ?? '').first<{id: string; status: string}>();
}

/**
 * updated-message on one of our outbound messages: an error code marks the row
 * failed; delivered or read confirms a row left 'unknown' (or 'sending') as
 * sent. 02 has no delivered/read columns, so nothing finer is stored.
 */
async function statusUpdate(data: BBMessage, env: Env): Promise<void> {
  if (!env.DB || data.isFromMe !== true) return;
  const row = await outboundRow(env.DB, data);
  if (!row) return;
  const code = num(data.error);
  if (code) {
    await env.DB.prepare("UPDATE advisor_messages SET status='failed',error=? WHERE id=? AND status IN ('sending','sent','unknown')").bind(`relay-error-${code}`, row.id).run();
    return;
  }
  if (data.isDelivered === true || num(data.dateDelivered) || num(data.dateRead)) {
    await env.DB.prepare("UPDATE advisor_messages SET status='sent',error=NULL,provider_id=COALESCE(provider_id,?),sent_at=COALESCE(sent_at,?) WHERE id=? AND status IN ('sending','unknown')")
      .bind(str(data.guid), new Date().toISOString(), row.id).run();
  }
}

async function sendError(data: BBMessage, env: Env): Promise<void> {
  if (!env.DB) return;
  const row = await outboundRow(env.DB, data);
  if (!row) { advisorLog('warn', 'advisor_bluebubbles_send_error_unmatched', {}); return; }
  const code = num(data.error);
  await env.DB.prepare("UPDATE advisor_messages SET status='failed',error=? WHERE id=? AND status IN ('sending','sent','unknown')").bind(code ? `relay-error-${code}` : 'relay-send-error', row.id).run();
  advisorLog('warn', 'advisor_bluebubbles_send_error', {code});
}

/** A parsed webhook body {type, data}: inbound messages, or 'ignore' after any status bookkeeping. */
export async function normalizePayload(payload: unknown, env: Env, fetcher: Fetcher = (url, init) => fetch(url, init)): Promise<InboundMessage[] | 'ignore'> {
  const {type, data} = (payload && typeof payload === 'object' ? payload : {}) as {type?: unknown; data?: unknown};
  const message = (data && typeof data === 'object' ? data : {}) as BBMessage;
  switch (type) {
    case 'new-message': return inbound(message, env, fetcher);
    case 'updated-message': await statusUpdate(message, env); return 'ignore';
    case 'message-send-error': await sendError(message, env); return 'ignore';
    // With a named tunnel the URL never changes, so this should not fire; log it for the runbook.
    case 'new-server': advisorLog('warn', 'advisor_bluebubbles_new_server', {}); return 'ignore';
    default: return 'ignore';
  }
}

/** The webhook request (already token-checked by the route): body capped at 64 KB, then normalizePayload. */
async function normalize(request: Request, env: Env, fetcher: Fetcher): Promise<InboundMessage[] | 'ignore'> {
  return normalizePayload(await readBody(request, MAX_WEBHOOK_BYTES), env, fetcher);
}

export const bluebubbles = createBlueBubbles();
