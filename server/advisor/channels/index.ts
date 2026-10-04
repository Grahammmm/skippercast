// Text Advisor channel adapters (docs/plans/text-advisor/03-channels.md
// § The adapter interface). One adapter per transport: BlueBubbles (the Mac
// relay: iMessage and forwarded SMS), Twilio (SMS/MMS after a port, TA-C2),
// the web chat (TA-C3) and Instagram DMs (TA-S6, dark until Meta's App Review). Inbound webhooks for every adapter are always mounted;
// outbound goes through channelFor(env, contact).
import {advisorSettings} from '../settings.ts';
import {bluebubbles} from './bluebubbles.ts';
// TA-C2: the Twilio adapter replaces its stub.
import {twilio} from './twilio.ts';
// TA-C3: the web chat adapter replaces its stub.
import {web} from './web.ts';
// TA-S6: Instagram DMs (09 § Inbox).
import {instagram} from './instagram.ts';
import type {Env} from '../../env.ts';
import type {AdvisorContactRow, OutboundMessage, SendResult} from '../types.ts';

export type {OutboundMessage, SendResult} from '../types.ts';

export type InboundChannel = 'imessage' | 'sms' | 'web' | 'instagram_dm' | 'instagram_comment';
export type AdapterName = 'bluebubbles' | 'twilio' | 'web' | 'instagram';

export interface InboundMedia {
  providerRef: string;             // attachment guid / media URL / IG attachment id
  mime: string | null;             // provider's claim; sniffed again after download (TA-C4)
  bytes: number | null;
  name: string | null;
  width?: number | null;
  height?: number | null;
  fetch: (env: Env) => Promise<Response>;   // authenticated download
}

export interface InboundMessage {
  channel: InboundChannel;
  providerId: string;              // unique per channel
  from: string;                    // E.164, or web session id, or IGSID
  to: string;                      // our number / page id
  text: string;                    // '' when media-only
  media: InboundMedia[];
  receivedAt: string;              // ISO
  isGroup: boolean;                // group chats are dropped by the adapter (03)
  raw?: unknown;                   // never persisted
  // TA-C3: media already stored for this contact (the web chat uploads first), attached by id.
  mediaIds?: string[];
}

export interface ChannelCapabilities {media: boolean; maxMediaBytes: number; typing: boolean; read: boolean; segments: number | null}

export interface ChannelAdapter {
  name: AdapterName;
  normalize(request: Request, env: Env): Promise<InboundMessage[] | 'ignore' | 'unauthorized'>;
  send(message: OutboundMessage, env: Env): Promise<SendResult>;
  /** `to` is the stored address (OutboundMessage.to), never a clear number. */
  typing?(to: string, on: boolean, env: Env): Promise<void>;
  /** BlueBubbles marks a chat read, not a message, so this takes the stored address too. */
  markRead?(to: string, env: Env): Promise<void>;
  health(env: Env): Promise<{ok: boolean; detail: string}>;
  capabilities: ChannelCapabilities;
  // TA-C4: download an attachment by the provider_ref stored on its placeholder
  // advisor_media row (the consumer runs after the webhook, so InboundMedia.fetch
  // no longer exists). Rejects on a network error; the caller checks response.ok.
  // Optional so an adapter written in parallel still type-checks; a missing one
  // counts as a failed download.
  fetchMediaByRef?(ref: string, env: Env): Promise<Response>;
}

/** Thrown by an adapter that does not exist yet; the consumer records the send as failed, not unknown. */
export class ChannelNotImplemented extends Error {
  constructor(name: string) { super(`${name} channel not implemented`); this.name = 'ChannelNotImplemented'; }
}

/** A placeholder adapter: every call throws ChannelNotImplemented. TA-C2 and TA-C3 replaced the twilio and web stubs. */
export function stubAdapter(name: AdapterName): ChannelAdapter {
  const fail = async (): Promise<never> => { throw new ChannelNotImplemented(name); };
  return {name, normalize: fail, send: fail, health: fail, fetchMediaByRef: fail, capabilities: {media: false, maxMediaBytes: 0, typing: false, read: false, segments: null}};
}

/** Every adapter by name. */
export const ADAPTERS: Record<AdapterName, ChannelAdapter> = {
  bluebubbles,
  twilio,   // TA-C2
  web,      // TA-C3
  instagram, // TA-S6
};

/**
 * Outbound adapter for a contact: web for a web-only visitor, Instagram for a
 * contact known only by its Instagram id (TA-S6), otherwise the one ADVISOR_CHANNEL names.
 */
export function channelFor(env: Env, contact: Pick<AdvisorContactRow, 'phone_enc' | 'web_session' | 'ig_sid'>): ChannelAdapter {
  if (!contact.phone_enc && contact.web_session) return ADAPTERS.web;
  if (!contact.phone_enc && contact.ig_sid) return ADAPTERS.instagram;
  return ADAPTERS[advisorSettings(env).channel];
}

// TA-C4: which adapter received an inbound attachment. advisor_messages records
// the channel ('imessage', 'sms', 'web'), not the adapter, and SMS arrives through
// BlueBubbles today and Twilio after a port: a Twilio provider_ref is its https
// media URL, a BlueBubbles one is an attachment guid.
// TA-S6: an Instagram DM's attachment is a Meta CDN URL, fetched by the Instagram adapter.
export function adapterForMedia(channel: string, ref: string): ChannelAdapter {
  if (channel === 'web') return ADAPTERS.web;
  if (channel === 'instagram_dm') return ADAPTERS.instagram;
  return /^https:\/\//.test(ref) ? ADAPTERS.twilio : ADAPTERS.bluebubbles;
}

/** TA-C4: the consumer's default media download: the receiving adapter's fetchMediaByRef. */
export async function fetchMediaByRef(ref: string, channel: string, env: Env): Promise<Response> {
  const adapter = adapterForMedia(channel, ref);
  if (!adapter.fetchMediaByRef) throw new ChannelNotImplemented(adapter.name);
  return adapter.fetchMediaByRef(ref, env);
}

// ---- message splitting (03 § adapter interface) -------------------------------

export const IMESSAGE_CHUNK = 1000;
export const SMS_CHUNK = 480;          // three 160-character segments
export const INSTAGRAM_CHUNK = 1000;   // TA-S6: Meta's limit for one Instagram text message
export const CHUNK_GAP_MS = 300;
const SMS_PREFIX_RESERVE = 8;          // "(99/99) "

/** Pack pieces joined by `sep` into chunks of at most `limit`; a piece longer than the limit is split by `finer`. */
function pack(pieces: string[], sep: string, limit: number, finer: (piece: string, limit: number) => string[]): string[] {
  const out: string[] = [];
  let current = '';
  for (const piece of pieces) {
    if (piece.length > limit) {
      if (current) { out.push(current); current = ''; }
      out.push(...finer(piece, limit));
      continue;
    }
    if (!current) current = piece;
    else if (current.length + sep.length + piece.length <= limit) current += sep + piece;
    else { out.push(current); current = piece; }
  }
  if (current) out.push(current);
  return out;
}
function byWord(text: string, limit: number): string[] {
  return pack(text.split(/\s+/).filter(Boolean), ' ', limit, (word, n) => word.match(new RegExp(`[\\s\\S]{1,${n}}`, 'g')) ?? []);
}
function bySentence(text: string, limit: number): string[] {
  return pack(text.split(/(?<=[.!?…])\s+/).map(s => s.trim()).filter(Boolean), ' ', limit, byWord);
}
function byParagraph(text: string, limit: number): string[] {
  return pack(text.split(/\n\s*\n/).map(p => p.trim()).filter(Boolean), '\n\n', limit, bySentence);
}

/**
 * A reply as the chunks to send, in order (03 § adapter interface): at most
 * 1,000 characters each on iMessage and 480 on SMS, broken at paragraph, then
 * sentence, then word boundaries. On SMS every chunk after the first carries a
 * "(2/3) " prefix (inside the 480). The web chat is never split.
 *
 * 03 writes this as splitForChannel(text, adapter); BlueBubbles carries both
 * iMessage and SMS, so the contact's channel ('imessage' | 'sms' | ...) is the
 * third argument. Twilio is always SMS. TA-S6: Instagram splits like iMessage, at 1,000.
 */
export function splitForChannel(text: string, adapter: Pick<ChannelAdapter, 'name'>, channel?: string): string[] {
  const clean = String(text ?? '').replace(/\r\n?/g, '\n').trim();
  if (!clean) return [];
  if (adapter.name === 'web') return [clean];
  const sms = adapter.name === 'twilio' || channel === 'sms';
  const limit = sms ? SMS_CHUNK : adapter.name === 'instagram' ? INSTAGRAM_CHUNK : IMESSAGE_CHUNK;
  if (clean.length <= limit) return [clean];
  if (!sms) return byParagraph(clean, limit);
  const chunks = byParagraph(clean, limit - SMS_PREFIX_RESERVE);
  return chunks.map((chunk, i) => i === 0 ? chunk : `(${i + 1}/${chunks.length}) ${chunk}`);
}
