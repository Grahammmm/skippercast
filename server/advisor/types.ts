// Shared types of the Text Advisor (docs/plans/text-advisor/01-architecture.md).
// TA-F1 added the settings shape and the queue message, TA-F3 the consumer's
// contract (actions, engine result, handler, the outbound channel); later tasks
// add InboundMessage, ChannelAdapter and the rest here, next to these, so every
// advisor module imports its types from one file.
import type {Env} from '../env.ts';
import type {LlmUsage} from '../analytics.ts';

export type AdvisorChannel = 'bluebubbles' | 'twilio';
export type VisionProviderName = 'hermes' | 'claude';

/** Every runtime var in 01 § "Feature flags", parsed and defaulted by advisorSettings(). */
export interface AdvisorSettings {
  enabled: boolean;                 // TEXT_ADVISOR_ENABLED: hard switch, every advisor route 404s when off
  repliesEnabled: boolean;          // ADVISOR_REPLIES_ENABLED: soft switch, inbound stored but nothing sent
  number: string | null;            // ADVISOR_NUMBER: the owned number, E.164 (+1 and ten digits)
  channel: AdvisorChannel;          // ADVISOR_CHANNEL: adapter for outbound texts
  privateApi: boolean;              // BLUEBUBBLES_PRIVATE_API: typing indicators and read receipts
  adminContactId: string | null;    // ADVISOR_ADMIN_CONTACT_ID: owner's contact for the text admin fallback
  inboxPublicReplies: boolean;      // ADVISOR_INBOX_PUBLIC_REPLIES: public replies to non-keyword IG comments
  model: string;                    // ADVISOR_MODEL: text model id
  visionModel: string;              // ADVISOR_VISION_MODEL: Claude vision fallback model id
  visionProviders: VisionProviderName[]; // ADVISOR_VISION_PROVIDERS: ordered provider chain, never empty
  dailyMessagesPerContact: number;  // ADVISOR_DAILY_MESSAGES_PER_CONTACT
  dailyLlmPerContact: number;       // ADVISOR_DAILY_LLM_PER_CONTACT
  globalDailyLlm: number;           // ADVISOR_GLOBAL_DAILY_LLM
  globalDailyVision: number;        // ADVISOR_GLOBAL_DAILY_VISION
  publicBase: string;               // ADVISOR_PUBLIC_BASE: https origin (and optional path), no trailing slash
  regionDefault: string;            // ADVISOR_REGION_DEFAULT: region id for contacts with no home port
  autoPublishAfter: number;         // ADVISOR_AUTO_PUBLISH_AFTER: clean reports before auto-publish is offered
  socialEnabled: boolean;           // ADVISOR_SOCIAL_ENABLED: publishing to Meta
  inboxEnabled: boolean;            // ADVISOR_INBOX_ENABLED: IG DM and comment handling
}

/** The one message shape on ADVISOR_QUEUE: the stored inbound message to process. */
export interface AdvisorMessage {message_id: string}

/** An advisor_contacts row as D1 returns it (02 § advisor_contacts). phone_enc never leaves the server. */
export interface AdvisorContactRow {
  id: string; phone_hash: string | null; phone_enc: string | null; web_session: string | null;
  channel: string; role: string; boat_id: string | null; display_name: string | null; language: string;
  home_port: string | null; targets_json: string | null; source: string | null; status: 'active' | 'stopped' | 'blocked';
  messages_today: number; messages_day: string | null; last_seen_at: string; last_error_notice_at: string | null;
  created_at: string; updated_at: string;
}

/** The subkeys HKDF derives from ADVISOR_PHONE_KEY (02 § advisor_contacts). Non-extractable. */
export interface PhoneKeys {
  hashKey: CryptoKey; encKey: CryptoKey;
  // TA-C4: HMAC key for upload-link tokens (HKDF info 'upload', 03 § Uploads for compressed channels).
  uploadKey: CryptoKey;
}

/** An advisor_messages row as D1 returns it (02 § advisor_messages). */
export interface AdvisorMessageRow {
  id: string; contact_id: string; direction: 'in' | 'out'; channel: string; provider_id: string | null;
  body: string | null; media_json: string | null; intent: string | null; status: string; error: string | null;
  in_reply_to: string | null; tokens_in: number | null; tokens_out: number | null; created_by: string | null;
  created_at: string; sent_at: string | null;
}

/** The contact columns an action may change (02 § advisor_contacts); everything else is owned by contacts.ts. */
export interface ContactFields {
  role?: 'angler' | 'skipper' | 'crew' | 'admin-test';
  boat_id?: string | null;
  display_name?: string | null;
  language?: 'en' | 'es';
  home_port?: string | null;
  targets_json?: string | null;     // JSON array of species keys
  source?: string | null;
}

/** advisor_reviews.kind (02 § advisor_reviews). */
export type ReviewKind = 'media' | 'report' | 'post' | 'skipper' | 'conversation' | 'rule';

/**
 * What the engine asks the consumer to do, applied in order by
 * server/advisor/consumer.ts (01 § request flow, step 5). Each is idempotent
 * by a stable id derived from (message_id, action index), so a retried message
 * repeats nothing it already did. Later tasks add report and social actions
 * (report_draft, report_confirm, post_draft, ...) to this union, each with its
 * applier in the consumer.
 */
export type Action =
  | {type: 'send_text'; text: string; chunkIndex?: number}        // chunkIndex: position after splitForChannel (TA-C1)
  | {type: 'send_media'; r2Key: string; caption?: string}          // a derived public JPEG in ADVISOR_MEDIA
  | {type: 'contact_update'; fields: ContactFields}
  | {type: 'review_open'; kind: ReviewKind; refId: string; reason: string}
  | {type: 'log'; event: string; fields?: Record<string, unknown>}
  // TA-E1: the engine's commands and flows (04 § stage 1, 02 § retention and deletion, 03 § web linking, 08 § text admin).
  | {type: 'set_status'; status: 'stopped' | 'active'}               // STOP / START through contacts.ts applyStop / applyStart
  | {type: 'forget'; language: Language}                              // send the confirmation, then forgetContact
  | {type: 'export'; language: Language}                              // exportContact -> R2 -> a signed 24 h link by text
  | {type: 'send_file'; name: string; mime: string; r2Key?: string; inlineBytes?: string; caption?: string; fallbackUrl?: string}  // inlineBytes: base64
  | {type: 'link_start'; phoneHash: string; phoneEnc: string; codeHash: string; expiresAt: number; codeText: string}
  | {type: 'link_merge'; phoneContactId: string}
  | {type: 'admin_review'; reviewId: string; decision: 'approved' | 'rejected'};

/** TA-E1: the two reply languages (02 § advisor_contacts.language). */
export type Language = 'en' | 'es';

/** One processed turn (04): the actions, the intent recorded on the inbound row, model usage. */
export interface EngineResult {actions: Action[]; intent: string; usage?: LlmUsage; model?: string | null}

/** TA-E1: what the engine can be handed so every test runs offline and deterministic (04). */
export interface EngineDeps {
  fetcher?: (url: string, init: RequestInit) => Promise<Response>;   // the Messages API; default fetch
  clock?: () => number;                                               // epoch ms; default Date.now
  random?: () => number;                                              // the web-link code; default crypto
  sleep?: (ms: number) => Promise<void>;                              // the 429/529 back-off; default setTimeout
  vision?: unknown;                                                   // TA-I2/I3: the vision chain
  feeds?: (url: string) => Promise<unknown>;                          // TA-E2: the data tools' feed reader; default readFeed (tests pass fixtures)
}

/**
 * The outbound message a channel sends (03 § adapter interface). `to` is the
 * contact's address as stored: the phone_enc blob for a phone contact (the
 * adapter decrypts it inside send(), so the number never exists outside a
 * channel, 02 § privacy invariants), the web_session hash for a web visitor.
 */
export interface OutboundMessage {
  id: string;                       // advisor_messages.id, deterministic
  to: string;
  text?: string;
  mediaKeys?: string[];             // R2 keys to attach (derived public JPEGs)
  replyToProviderId?: string;       // threads the reply where the channel supports it
  channelHint?: 'imessage' | 'sms'; // the contact's last channel: picks the BlueBubbles chat GUID (TA-C1)
  files?: {name: string; mime: string; base64: string}[];   // TA-E1: small inline attachments (the contact card); BlueBubbles only
}
export interface SendResult {providerId: string | null; status: 'sent' | 'failed' | 'unknown'; error?: string}
/** The part of 03's ChannelAdapter the consumer needs (channels/index.ts ChannelAdapter implements it). */
export interface OutboundChannel {name?: string; send(message: OutboundMessage, env: Env): Promise<SendResult>}

/** Injectable dependencies of the consumer, so tests run offline and deterministic. */
export interface ConsumerDeps {
  now?: () => number;               // epoch ms; default Date.now
  random?: () => number;            // default Math.random (for the engine)
  channel?: OutboundChannel;        // a fixed channel for every contact (tests); wins over channelFor
  channelFor?: (env: Env, contact: AdvisorContactRow) => OutboundChannel; // per-contact adapter; server/index.ts passes channels/index.ts channelFor
  sleep?: (ms: number) => Promise<void>; // the gap between split chunks; default setTimeout
  handler?: Handler;                // default: warmUpHandler; server/index.ts, inbound.ts and the web route pass engineHandler (TA-E1)
  turnTimeoutMs?: number;           // hard stop per message; default 45 s (01 § request flow)
  // TA-C4: media download before the handler (server/advisor/media.ts).
  fetchMediaByRef?: (ref: string, channel: string, env: Env) => Promise<Response>; // default: the receiving adapter's fetchMediaByRef
  mediaRetries?: number;            // extra queue attempts after a failed download; default 2, runInline 0
  engine?: EngineDeps;              // TA-E1: passed through to the engine handler (tests: the fake Messages API)
}

export interface HandlerInput {env: Env; contact: AdvisorContactRow; message: AdvisorMessageRow; now: number; deps: ConsumerDeps; signal: AbortSignal}
/** One stored inbound message in, actions out. `signal` aborts when the hard stop fires. */
export type Handler = (input: HandlerInput) => Promise<EngineResult>;
