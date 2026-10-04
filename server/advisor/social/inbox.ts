// The Instagram inbox: Meta's webhook, DMs and comment keywords
// (docs/plans/text-advisor/09-social.md § Inbox, SP-8, SP-9; TA-S6). Dark until
// the app is Live with Advanced Access and ADVISOR_INBOX_ENABLED=true (09 §
// Setup step 5, the runbook docs/operations/runbooks/advisor-meta-app-review.md).
//
//   GET  /api/advisor/inbound/meta   the subscription handshake: hub.mode=subscribe and
//                                    hub.verify_token = META_VERIFY_TOKEN -> hub.challenge
//   POST /api/advisor/inbound/meta   X-Hub-Signature-256 = sha256=<hex HMAC-SHA256 of the raw
//                                    body keyed with META_APP_SECRET>, checked in constant time
//                                    before the body is parsed; at most 256 KB
//
// A signed POST with the inbox off is acknowledged and nothing is written. On:
//   messaging[] (field `messages`)  a DM: one InboundMessage on channel 'instagram_dm', keyed
//                                   by Meta's message id (mid) and from the sender's IGSID;
//                                   images become media placeholders downloaded from Meta's
//                                   CDN by the Instagram adapter. Echoes of our own sends,
//                                   reactions, reads, edits and deletions are skipped.
//   changes[] (field `comments`)    a comment, kept only when it needs an answer: its first
//                                   word is a keyword (catalog/advisor/keywords.json: one
//                                   private reply), or, with ADVISOR_INBOX_PUBLIC_REPLIES on,
//                                   it is a question (the engine's public reply). Anything
//                                   else, and our own comments, are not stored at all.
// Both are stored through inbound.ts storeInbound (deduplicated by channel and
// provider id, so Meta's retries change nothing) and run by the engine like a text.
// Comment and DM text is untrusted input, exactly as a text message is: it
// reaches the model only as the user turn, under the same system prompt.
import keywordsCatalog from '../../../catalog/advisor/keywords.json' with {type: 'json'};
import {ClientError} from '../../errors.ts';
import {hex} from '../ids.ts';
import {fold, resolvePort, resolveSpecies} from '../answers/resolve.ts';
import {resolveLinks} from '../links.ts';
import {t} from '../strings.ts';
import type {StringKey} from '../strings.ts';
import {parseCommand} from '../intents.ts';
import {IG_SID} from '../contacts.ts';
import {isMetaMediaUrl} from '../channels/instagram.ts';
import type {InboundMedia, InboundMessage} from '../channels/index.ts';
import type {AdvisorSettings, Language} from '../types.ts';
import type {Env} from '../../env.ts';

export const META_BODY_MAX = 256 * 1024;   // the webhook body cap
export const MAX_DM_IMAGES = 4;            // image attachments kept per DM
export const COMMENT_TEXT_MAX = 2200;      // Instagram's comment limit
const encoder = new TextEncoder();
const ID = /^[\w.:=-]{1,200}$/;            // Meta's message and comment ids

// ---- the handshake and the signature -------------------------------------------------------

/** Constant-time equality of two secrets: both are hashed first, so neither length nor content leaks. */
export async function equalSecret(given: string, expected: string): Promise<boolean> {
  const [a, b] = await Promise.all([given, expected].map(s => crypto.subtle.digest('SHA-256', encoder.encode(s))));
  const x = new Uint8Array(a!), y = new Uint8Array(b!);
  let diff = 0;
  for (let i = 0; i < x.length; i++) diff |= x[i]! ^ y[i]!;
  return diff === 0 && expected.length > 0;
}

/**
 * The GET handshake (Meta's "Verification Requests"): the challenge, echoed as
 * text, when hub.mode is subscribe and hub.verify_token is META_VERIFY_TOKEN;
 * otherwise 403. A challenge is digits in practice; anything over 200
 * characters or with markup is refused rather than echoed.
 */
export async function handshake(query: URLSearchParams, verifyToken: string | undefined): Promise<{status: 200 | 403; body: string}> {
  const challenge = query.get('hub.challenge') ?? '';
  if (query.get('hub.mode') !== 'subscribe' || !/^[\w.-]{1,200}$/.test(challenge)) return {status: 403, body: 'Forbidden'};
  if (!await equalSecret(query.get('hub.verify_token') ?? '', verifyToken ?? '')) return {status: 403, body: 'Forbidden'};
  return {status: 200, body: challenge};
}

/** The raw body as bytes, read as a stream and capped (ClientError 'body too large' beyond). */
export async function readRawBody(request: Request, max = META_BODY_MAX): Promise<Uint8Array<ArrayBuffer>> {
  if (Number(request.headers.get('content-length')) > max) throw new ClientError('body too large');
  const reader = request.body?.getReader();
  if (!reader) return new Uint8Array(0);
  const chunks: Uint8Array[] = []; let size = 0;
  for (;;) {
    const {done, value} = await reader.read();
    if (done) break;
    size += value.length;
    if (size > max) { await reader.cancel().catch(() => {}); throw new ClientError('body too large'); }
    chunks.push(value);
  }
  const bytes = new Uint8Array(size); let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  return bytes;
}

const hmacKey = (secret: string, usage: 'sign' | 'verify'): Promise<CryptoKey> =>
  crypto.subtle.importKey('raw', encoder.encode(secret), {name: 'HMAC', hash: 'SHA-256'}, false, [usage]);

/** The X-Hub-Signature-256 value Meta sends for `body`: "sha256=" and the lowercase hex HMAC-SHA256. */
export async function metaSignature(appSecret: string, body: Uint8Array<ArrayBuffer> | string): Promise<string> {
  const bytes = typeof body === 'string' ? encoder.encode(body) : body;
  return 'sha256=' + hex(await crypto.subtle.sign('HMAC', await hmacKey(appSecret, 'sign'), bytes));
}

/** True when `header` is the valid X-Hub-Signature-256 for `body`. WebCrypto's HMAC verify compares in constant time. */
export async function verifyMetaSignature(appSecret: string | undefined, body: Uint8Array<ArrayBuffer>, header: string | null): Promise<boolean> {
  const match = /^sha256=([0-9a-f]{64})$/i.exec(header ?? '');
  if (!appSecret || !match) return false;
  const given = new Uint8Array(32);
  for (let i = 0; i < 32; i++) given[i] = parseInt(match[1]!.slice(i * 2, i * 2 + 2), 16);
  return crypto.subtle.verify('HMAC', await hmacKey(appSecret, 'verify'), given, body);
}

// ---- the payload ----------------------------------------------------------------------------

interface MetaAttachment {type?: unknown; payload?: {url?: unknown} | null}
interface MetaMessaging {
  sender?: {id?: unknown}; recipient?: {id?: unknown}; timestamp?: unknown;
  message?: {mid?: unknown; text?: unknown; attachments?: MetaAttachment[]; is_echo?: unknown; is_deleted?: unknown; is_unsupported?: unknown} | null;
}
interface MetaChange {field?: unknown; value?: {id?: unknown; text?: unknown; from?: {id?: unknown}; media?: {id?: unknown}; parent_id?: unknown} | null}
interface MetaEntry {id?: unknown; time?: unknown; messaging?: MetaMessaging[]; changes?: MetaChange[]}
export interface MetaPayload {object?: unknown; entry?: MetaEntry[]}

/** What a webhook delivery holds: DMs to store, comment events (not yet classified), and how many events were skipped. */
export interface MetaEvents {dms: InboundMessage[]; comments: InboundMessage[]; skipped: number}

/** Meta's time: epoch ms (messaging) or seconds (entry.time on changes), to ISO; `fallback` when absent. */
function isoTime(value: unknown, fallback: number): string {
  const n = typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : null;
  return new Date(n === null ? fallback : n < 1e12 ? n * 1000 : n).toISOString();
}
const str = (v: unknown, pattern: RegExp): string | null => typeof v === 'string' && pattern.test(v) ? v : null;
const cleanText = (v: unknown): string => typeof v === 'string' ? v.replace(/\r\n?/g, '\n').replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, '').trim() : '';

/** An image attachment as a media placeholder, downloaded later from Meta's CDN (the Instagram adapter's fetchMediaByRef). */
function imageMedia(attachment: MetaAttachment): InboundMedia | null {
  const url = attachment?.type === 'image' && typeof attachment.payload?.url === 'string' ? attachment.payload.url : null;
  if (!url || url.length > 2048 || !isMetaMediaUrl(url)) return null;
  return {providerRef: url, mime: null, bytes: null, name: null, fetch: () => fetch(url, {signal: AbortSignal.timeout(60000)})};
}

/**
 * The events in a verified webhook body for our Instagram account (`igUserId`):
 * entries of another account and anything from our own account (echoes of our
 * DMs, our public replies) are skipped.
 */
export function parseMetaWebhook(payload: MetaPayload, igUserId: string, now: number = Date.now()): MetaEvents {
  const out: MetaEvents = {dms: [], comments: [], skipped: 0};
  if (payload?.object !== 'instagram' || !Array.isArray(payload.entry)) return out;
  for (const entry of payload.entry.slice(0, 100)) {
    if (str(entry?.id, ID) !== igUserId) { out.skipped++; continue; }
    for (const m of Array.isArray(entry.messaging) ? entry.messaging.slice(0, 100) : []) {
      const message = m?.message, sender = str(m?.sender?.id, IG_SID), mid = str(message?.mid, ID);
      if (!message || !sender || !mid || sender === igUserId || message.is_echo === true || message.is_deleted === true || message.is_unsupported === true) { out.skipped++; continue; }
      const media = (Array.isArray(message.attachments) ? message.attachments : []).map(imageMedia).filter((x): x is InboundMedia => Boolean(x)).slice(0, MAX_DM_IMAGES);
      const text = cleanText(message.text);
      if (!text && !media.length) { out.skipped++; continue; }   // a sticker, a share or a reel: nothing the advisor can read
      out.dms.push({channel: 'instagram_dm', providerId: mid, from: sender, to: igUserId, text, media, receivedAt: isoTime(m.timestamp, now), isGroup: false});
    }
    for (const c of Array.isArray(entry.changes) ? entry.changes.slice(0, 100) : []) {
      const value = c?.value, from = str(value?.from?.id, IG_SID), id = str(value?.id, ID);
      if (c?.field !== 'comments' || !value || !from || !id || from === igUserId) { out.skipped++; continue; }
      const text = cleanText(value.text).slice(0, COMMENT_TEXT_MAX);
      if (!text) { out.skipped++; continue; }
      // `to` is the commented media's id (the post), kept for the engine's brief; the comment id is the provider id.
      out.comments.push({channel: 'instagram_comment', providerId: id, from, to: str(value.media?.id, ID) ?? igUserId, text, media: [],
        receivedAt: isoTime(entry.time, now), isGroup: false});
    }
  }
  return out;
}

// ---- comments: keywords and questions ----------------------------------------------------------

export interface Keyword {key: string; string: StringKey; guide: string; species_default?: string; words: Record<Language, string[]>}
export const KEYWORDS: readonly Keyword[] = keywordsCatalog.keywords as Keyword[];
export const KEYWORD_TEXT_SOURCE: string = keywordsCatalog.text_source;
const WORDS = new Map<string, {keyword: Keyword; language: Language}>();
for (const keyword of KEYWORDS) for (const language of ['en', 'es'] as const) for (const word of keyword.words[language]) WORDS.set(word, {keyword, language});

/** The comment's words, folded (lower case, no accents), with leading @mentions dropped. */
const words = (text: string): string[] => fold(String(text ?? '').replace(/^(?:\s*@[\w.]+)+/u, '')).split(' ').filter(Boolean);

/** The keyword a comment starts with ("RIG", "rig please", "@us Reporte"), its language and the rest of the words, or null. */
export function matchKeyword(text: string): {keyword: Keyword; language: Language; rest: string} | null {
  const [first, ...rest] = words(text);
  const hit = first ? WORDS.get(first) : undefined;
  return hit ? {...hit, rest: rest.join(' ')} : null;
}

const QUESTION_WORDS = new Set(['how', 'what', 'whats', 'when', 'where', 'which', 'who', 'why', 'is', 'are', 'can', 'do', 'does', 'did', 'any', 'anyone', 'should', 'will',
  'como', 'que', 'cuando', 'donde', 'cual', 'cuales', 'quien', 'por', 'hay', 'puedo', 'se']);
/** A comment that asks something: a question mark (either language) or a question word first. */
export function isQuestion(text: string): boolean {
  if (/[?¿]/u.test(text)) return true;
  const first = words(text)[0];
  return Boolean(first && QUESTION_WORDS.has(first));
}

export type CommentKind = {kind: 'keyword'; keyword: Keyword; language: Language; rest: string} | {kind: 'question'} | null;
/**
 * What a comment needs: a keyword's private reply, or (only with
 * ADVISOR_INBOX_PUBLIC_REPLIES on) a question for the engine's public reply.
 * A command word ("stop", "help?") is neither: STOP and HELP are for DMs and texts.
 */
export function classifyComment(text: string, settings: Pick<AdvisorSettings, 'inboxPublicReplies'>): CommentKind {
  const keyword = matchKeyword(text);
  if (keyword) return {kind: 'keyword', ...keyword};
  if (settings.inboxPublicReplies && isQuestion(text) && !parseCommand(text)) return {kind: 'question'};
  return null;
}

/**
 * The keyword's private reply in its language: the catalog string with the
 * guide link (a port or species named in the comment, else the region's first
 * port or the keyword's default species) and the text-us link, visit source `ig`.
 */
export function keywordReply(match: {keyword: Keyword; language: Language; rest: string}, settings: Pick<AdvisorSettings, 'publicBase' | 'regionDefault'>): string {
  const port = resolvePort(match.rest, null, settings)?.port ?? '';
  const species = resolveSpecies(match.rest)?.key ?? match.keyword.species_default ?? '';
  const link = (spec: string): string | null => resolveLinks(`{{link:${spec}}}`, settings.publicBase, 1, KEYWORD_TEXT_SOURCE).links[0] ?? null;
  const guide = link(match.keyword.guide.replace('{port}', port).replace('{species}', species)) ?? link('home')!;
  const text = link(`text:${KEYWORD_TEXT_SOURCE}`)!;
  return t(match.language, match.keyword.string, {guide, text});
}

/** True when the inbox may act: the switch is on and the Meta secrets and the verify token are set. */
export const inboxReady = (env: Env, settings: Pick<AdvisorSettings, 'inboxEnabled'>): boolean =>
  settings.inboxEnabled && Boolean(env.META_APP_SECRET && env.META_IG_USER_ID && env.META_PAGE_TOKEN);
