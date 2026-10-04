// The web chat channel (docs/plans/text-advisor/03-channels.md § Web adapter,
// 08 § Web chat; TA-C3). A visitor is identified by the `sc_adv` cookie (32
// random bytes, base64url, 90 days); advisor_contacts.web_session holds its
// SHA-256, never the value. The HTTP handler (server/routes/advisor.ts) stores
// the message through the shared storeInbound and runs the turn inline; the
// replies come back in the same response, so `send` writes into a per-request
// collector (createWebCollector) that the handler passes to the consumer as its
// channel. The registered adapter (ADAPTERS.web) has no request to answer: a
// send through it (a retry or a held-row release outside a request) is recorded
// as failed.
//
// Media are uploaded first (POST /api/advisor/web/upload, already stored and
// stripped) and referenced by id; normalize accepts only ids of this contact's
// own stored images that no message has used yet.
import {body as readJson} from '../../http.ts';
import {ClientError} from '../../errors.ts';
import {sha256} from '../ids.ts';
import type {Env} from '../../env.ts';
import type {ChannelAdapter, InboundMessage} from './index.ts';
import type {OutboundChannel, OutboundMessage, SendResult} from '../types.ts';

export const WEB_COOKIE = 'sc_adv';
export const WEB_COOKIE_MAX_AGE = 7776000;           // 90 days (03 § Web adapter)
export const WEB_BODY_BYTES = 8192;                  // the JSON body cap
export const WEB_TEXT_CHARS = 2000;                  // one chat message
export const WEB_MAX_MEDIA = 4;                      // media ids per message
const SESSION = /^[\w-]{16,128}$/;
const MEDIA_ID = /^[\w-]{1,64}$/;

/** A new cookie value: 32 random bytes, base64url without padding (43 characters). */
export function newWebSession(): string {
  let s = ''; for (const b of crypto.getRandomValues(new Uint8Array(32))) s += String.fromCharCode(b);
  return btoa(s).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '');
}

/** The well-formed `sc_adv` value in the request's Cookie header, or null. */
export function webSessionOf(request: Request): string | null {
  for (const part of (request.headers.get('Cookie') || '').split(';')) {
    const at = part.indexOf('=');
    if (at < 0 || part.slice(0, at).trim() !== WEB_COOKIE) continue;
    const value = part.slice(at + 1).trim();
    return SESSION.test(value) ? value : null;
  }
  return null;
}

/** The Set-Cookie value for a session (03: HttpOnly; Secure; SameSite=Lax; Max-Age 90 days). */
export const webSessionCookie = (value: string): string => `${WEB_COOKIE}=${value}; Max-Age=${WEB_COOKIE_MAX_AGE}; Path=/; Secure; HttpOnly; SameSite=Lax`;

/**
 * The one inbound message in a web chat request. `session` is the cookie value
 * (the handler passes the one it just issued, which is not in the request yet).
 * Throws ClientError for a bad body: over 8 KB, not JSON, text not a string or
 * over 2,000 characters, no text and no media, more than 4 media ids, or an id
 * that is not an unused stored image of this visitor.
 */
export async function normalizeWeb(request: Request, env: Env, session: string | null): Promise<InboundMessage[] | 'unauthorized'> {
  if (!session || !SESSION.test(session)) return 'unauthorized';
  const input = await readJson(request, WEB_BODY_BYTES);
  const text = input.text ?? '';
  if (typeof text !== 'string') throw new ClientError('text must be a string');
  const clean = text.replace(/\r\n?/g, '\n').trim();
  if (Array.from(clean).length > WEB_TEXT_CHARS) throw new ClientError('message too long');
  const ids = input.media_ids ?? [];
  if (!Array.isArray(ids) || ids.length > WEB_MAX_MEDIA || !ids.every(id => typeof id === 'string' && MEDIA_ID.test(id))) throw new ClientError('invalid media_ids');
  const mediaIds = [...new Set(ids as string[])];
  if (!clean && !mediaIds.length) throw new ClientError('empty message');
  if (mediaIds.length) {
    if (!env.DB) throw Error('storage unavailable');
    // The visitor's own, stored (not rejected), image, not yet attached to a message.
    const owned = (await env.DB.prepare(`SELECT m.id FROM advisor_media m JOIN advisor_contacts c ON c.id=m.contact_id
      WHERE c.web_session=? AND m.id IN (${mediaIds.map(() => '?').join(',')}) AND m.message_id IS NULL AND m.kind='image' AND m.r2_key<>'' AND m.publish_state<>'rejected'`)
      .bind(await sha256(session), ...mediaIds).all<{id: string}>()).results;
    if (owned.length !== mediaIds.length) throw new ClientError('unknown media');
  }
  return [{channel: 'web', providerId: `web:${crypto.randomUUID()}`, from: session, to: 'web', text: clean, media: [], mediaIds,
    receivedAt: new Date().toISOString(), isGroup: false}];
}

/** One reply as the web chat returns it. `media` holds R2 keys; the handler turns them into URLs. */
export interface WebReply {id: string; text: string; mediaKeys: string[]}

/**
 * A per-request outbound channel: every send lands in `replies` and counts as
 * sent. After close() (the handler answered "pending" at its timeout) sends
 * are recorded as failed, since nobody is listening for them any more.
 */
export function createWebCollector(): OutboundChannel & {name: 'web'; replies: WebReply[]; close(): void} {
  const replies: WebReply[] = [];
  let open = true;
  return {
    name: 'web', replies,
    close() { open = false; },
    async send(message: OutboundMessage): Promise<SendResult> {
      if (!open) return {providerId: null, status: 'failed', error: 'web-closed'};
      replies.push({id: message.id, text: message.text ?? '', mediaKeys: message.mediaKeys ?? []});
      return {providerId: message.id, status: 'sent'};
    },
  };
}

/** The registered adapter (ADAPTERS.web): normalize reads the cookie; send has no open request to answer. */
export const web: ChannelAdapter = {
  name: 'web',
  normalize: (request, env) => normalizeWeb(request, env, webSessionOf(request)),
  async send(): Promise<SendResult> { return {providerId: null, status: 'failed', error: 'web-no-request'}; },
  async health() { return {ok: true, detail: 'web chat is served by the Worker'}; },
  // Media arrive already stored through /api/advisor/web/upload, so there is nothing to fetch by reference.
  capabilities: {media: true, maxMediaBytes: 8 * 1024 * 1024, typing: false, read: false, segments: null},
};
