// The Instagram channel (docs/plans/text-advisor/09-social.md § Inbox,
// 03-channels.md § Instagram adapter; TA-S6). Dark until Meta approves the app
// (ADVISOR_INBOX_ENABLED, 09 § Setup step 5).
//
// Inbound arrives through Meta's webhook (social/inbox.ts parses and checks
// it; routes/advisor.ts mounts it), so `normalize` here is not used: the route
// needs the raw body for the X-Hub-Signature-256 check before anything parses it.
//
// Outbound, through the Graph client (social/meta.ts) with the Page token:
//   send          a DM: POST /<ig-user-id>/messages recipient {id: IGSID}, text at
//                 most 1,000 characters (the consumer splits longer replies), then one
//                 image message per attached media key (approved or posted media only,
//                 as the public /media/<id>.jpg Meta fetches). Only inside Meta's
//                 24-hour window after the person's last DM: outside it the row is
//                 failed 'outside-window' without a call (Meta's own refusal, code 10
//                 subcode 2018278, maps to the same).
//   commentChannel  the answer to one comment: `private` is Meta's single private reply
//                 (recipient {comment_id}, within 7 days of the comment), `public` a reply
//                 under it (POST /<comment-id>/replies); one send per comment in a turn.
//
// Every send is one try (attempts 1): a POST that failed with a 5xx or timed out
// may have gone out, so it is recorded 'unknown' and never resent (01 §
// idempotency). Errors are short codes; the IGSID and the text are never logged.
import {advisorSettings} from '../settings.ts';
import {MetaError, igCommentReply, igSendMessage, metaConfig, OUTSIDE_WINDOW, IG_COMMENT_MAX} from '../social/meta.ts';
import type {Fetcher, MetaConfig} from '../social/meta.ts';
import {IG_SID} from '../contacts.ts';
import type {Env} from '../../env.ts';
import type {OutboundChannel, OutboundMessage, SendResult} from '../types.ts';
import type {ChannelAdapter} from './index.ts';

export const DM_WINDOW_MS = 24 * 3600000;          // Meta: a reply within 24 h of the person's last message
export const PRIVATE_REPLY_WINDOW_MS = 7 * 86400000; // Meta: a private reply within 7 days of the comment
export const MAX_IMAGES = 4;                         // image messages per outbound row (v1: approved media only)
export const DOWNLOAD_TIMEOUT_MS = 60000;
/** Hosts Meta serves DM attachments from (lookaside.fbsbx.com, the fbcdn and cdninstagram CDNs). */
const MEDIA_HOST = /(?:^|\.)(?:fbsbx\.com|fbcdn\.net|cdninstagram\.com)$/;
const MEDIA_ID = /^[\w-]{1,64}$/;
const PUBLIC_STATES = new Set(['approved', 'posted']);

export interface InstagramOptions {fetcher?: Fetcher; now?: () => number}

/** A Meta media URL we may download a DM attachment from: https on one of Meta's CDN hosts, nothing else. */
export function isMetaMediaUrl(ref: string): boolean {
  try {
    const url = new URL(ref);
    return url.protocol === 'https:' && !url.username && !url.password && MEDIA_HOST.test(url.hostname);
  } catch { return false; }
}

/** The short failure code for a Meta error: the 24-hour window, the recipient gone, else HTTP class. */
export function sendError(error: unknown): SendResult {
  if (!(error instanceof MetaError)) return {providerId: null, status: 'failed', error: error instanceof TypeError ? 'invalid-message' : 'error'};
  if (error.code === OUTSIDE_WINDOW.code && error.subcode === OUTSIDE_WINDOW.subcode) return {providerId: null, status: 'failed', error: 'outside-window'};
  if (error.status === 0 || error.status >= 500) return {providerId: null, status: 'unknown', error: error.status ? `meta-${error.status}` : 'network'};
  return {providerId: null, status: 'failed', error: `meta-${error.status}${error.code !== null ? `-${error.code}` : ''}`};
}

/** When this IGSID last wrote to us by DM (ISO), or null. */
async function lastDm(db: D1Database, igSid: string): Promise<string | null> {
  const row = await db.prepare(`SELECT MAX(m.created_at) AS at FROM advisor_messages m JOIN advisor_contacts c ON c.id=m.contact_id
    WHERE c.ig_sid=? AND m.direction='in' AND m.channel='instagram_dm'`).bind(igSid).first<{at: string | null}>();
  return row?.at ?? null;
}

/**
 * Public URLs (${publicBase}/media/<id>.jpg) for R2 keys, as the Twilio adapter
 * maps them: a derived key carries its media id, any other is looked up by
 * advisor_media.r2_key; only approved or posted media are public. A string is the error code.
 */
async function imageUrls(env: Env, keys: string[]): Promise<string[] | string> {
  if (!keys.length) return [];
  if (keys.length > MAX_IMAGES) return 'too-many-media';
  if (!env.DB) return 'no-db';
  const base = advisorSettings(env).publicBase, urls: string[] = [];
  for (const key of keys) {
    const derived = /^advisor\/derived\/([\w-]{1,64})\//.exec(key)?.[1];
    const row = await (derived
      ? env.DB.prepare('SELECT id,publish_state FROM advisor_media WHERE id=?').bind(derived)
      : env.DB.prepare("SELECT id,publish_state FROM advisor_media WHERE r2_key=? AND r2_key<>'' LIMIT 1").bind(key)).first<{id: string; publish_state: string}>();
    if (!row || !MEDIA_ID.test(row.id)) return 'media-missing';
    if (!PUBLIC_STATES.has(row.publish_state)) return 'media-not-public';
    urls.push(`${base}/media/${row.id}.jpg`);
  }
  return urls;
}

const config = (env: Env, options: InstagramOptions): MetaConfig | null => metaConfig(env, {attempts: 1, ...(options.fetcher ? {fetcher: options.fetcher} : {})});

/** The Instagram adapter. `fetcher` and `now` are injected by tests. */
export function createInstagram(options: InstagramOptions = {}): ChannelAdapter {
  const now = options.now ?? Date.now;
  const doFetch: Fetcher = options.fetcher ?? ((url, init) => fetch(url, init));

  async function send(message: OutboundMessage, env: Env): Promise<SendResult> {
    const cfg = config(env, options);
    if (!cfg || !env.DB) return {providerId: null, status: 'failed', error: 'not-configured'};
    if (!IG_SID.test(message.to)) return {providerId: null, status: 'failed', error: 'no-address'};
    const last = await lastDm(env.DB, message.to);
    if (!last || now() - Date.parse(last) > DM_WINDOW_MS) return {providerId: null, status: 'failed', error: 'outside-window'};
    const urls = await imageUrls(env, message.mediaKeys ?? []);
    if (typeof urls === 'string') return {providerId: null, status: 'failed', error: urls};
    const text = (message.text ?? '').trim();
    if (!text && !urls.length) return {providerId: null, status: 'failed', error: 'empty'};
    let first: string | null = null, sent = 0;
    try {
      // The text first, then each photo: a text and a photo are separate messages on Instagram.
      if (text) { first = await igSendMessage(cfg, env.META_IG_USER_ID!, {id: message.to}, {text}); sent++; }
      for (const url of urls) {
        const id = await igSendMessage(cfg, env.META_IG_USER_ID!, {id: message.to}, {attachment: {type: 'image', payload: {url}}});
        first ??= id; sent++;
      }
    } catch (error) {
      // Something already went out and a later photo failed: the row is sent (the person has the answer), with the error noted.
      if (sent) return {providerId: first, status: 'sent', error: 'image-failed'};
      return sendError(error);
    }
    return {providerId: first, status: 'sent'};
  }

  async function fetchMediaByRef(ref: string): Promise<Response> {
    if (!isMetaMediaUrl(ref)) throw Error('not a Meta media URL');
    const response = await doFetch(ref, {redirect: 'follow', signal: AbortSignal.timeout(DOWNLOAD_TIMEOUT_MS)});
    if (response.url && response.redirected && !isMetaMediaUrl(response.url)) { await response.body?.cancel().catch(() => {}); throw Error('media redirect left Meta'); }
    return response;
  }

  return {
    name: 'instagram',
    // Inbound is the signed Meta webhook (social/inbox.ts), not a per-adapter normalize.
    async normalize() { return 'ignore'; },
    send,
    async health(env: Env) {
      const settings = advisorSettings(env);
      return {ok: Boolean(metaConfig(env)), detail: !metaConfig(env) ? 'Meta secrets are not set' : settings.inboxEnabled ? 'inbox on' : 'inbox off (ADVISOR_INBOX_ENABLED)'};
    },
    fetchMediaByRef: (ref: string) => fetchMediaByRef(ref),
    // Text only, split at 1,000 characters (splitForChannel); images by URL only (approved media).
    capabilities: {media: true, maxMediaBytes: 8 * 1024 * 1024, typing: false, read: false, segments: null},
  };
}

export const instagram = createInstagram();

/**
 * The outbound channel for one comment's answer (consumer.ts comment_reply).
 * `private`: the one private reply Meta allows, a DM through recipient.comment_id,
 * refused after 7 days; `public`: a reply under the comment. Every send of the
 * same channel after the first is refused ('one-reply'), so a split or a second
 * text can never become a second reply.
 */
export function commentChannel(env: Env, comment: {providerId: string; receivedAt: string}, mode: 'private' | 'public', options: InstagramOptions = {}): OutboundChannel {
  const now = options.now ?? Date.now;
  let used = false;
  return {
    name: 'instagram',
    async send(message: OutboundMessage): Promise<SendResult> {
      if (used) return {providerId: null, status: 'failed', error: 'one-reply'};
      used = true;
      const cfg = config(env, options);
      if (!cfg) return {providerId: null, status: 'failed', error: 'not-configured'};
      const text = (message.text ?? '').trim();
      if (!text) return {providerId: null, status: 'failed', error: 'empty'};
      try {
        if (mode === 'private') {
          if (now() - Date.parse(comment.receivedAt) > PRIVATE_REPLY_WINDOW_MS) return {providerId: null, status: 'failed', error: 'outside-window'};
          return {providerId: await igSendMessage(cfg, env.META_IG_USER_ID!, {comment_id: comment.providerId}, {text: Array.from(text).slice(0, 1000).join('')}), status: 'sent'};
        }
        return {providerId: await igCommentReply(cfg, comment.providerId, Array.from(text).slice(0, IG_COMMENT_MAX).join('')), status: 'sent'};
      } catch (error) { return sendError(error); }
    },
  };
}
