// Worker bindings, variables and secrets, written from wrangler.jsonc. Every
// binding is optional here because the Worker must degrade (fail closed or no-op)
// where one is absent: local tests, a bare `wrangler dev`, a new deployment.
// tests/test_worker_types.mjs checks this list against wrangler.jsonc.
import type {SessionUser} from './auth.ts';
import type {TripCheckMessage} from './trip-queue.ts';
import type {AdvisorMessage} from './advisor/types.ts';

export interface Env {
  // Bindings (wrangler.jsonc)
  ASSETS?: Fetcher;                  // assets.binding: the built site in dist/client
  DB?: D1Database;                   // d1_databases: accounts, trips, alerts, limits
  FEEDS?: R2Bucket;                  // r2_buckets: published feeds and tiles
  PUBLIC_LIMITER?: RateLimit;        // ratelimits: /api/om and /api/telemetry, 60 a minute per IP each
  FEED_LIMITER?: RateLimit;          // ratelimits: /feeds/, 300 a minute per IP
  // Added to the deploy config only with ENABLE_ANALYTICS / ENABLE_QUEUES=true (scripts/wrangler_config.mjs):
  ANALYTICS?: AnalyticsEngineDataset; // analytics_engine_datasets: skippercast_events (server/analytics.ts)
  TRIP_QUEUE?: Queue<TripCheckMessage>; // queues.producers: skippercast-trip-checks (server/trip-queue.ts)
  // Added only with ENABLE_ADVISOR=true (docs/plans/text-advisor/01-architecture.md):
  ADVISOR_MEDIA?: R2Bucket;          // r2_buckets: skippercast-advisor-media, private (never served directly)
  ADVISOR_QUEUE?: Queue<AdvisorMessage>; // queues.producers: skippercast-advisor (inbound messages to process)
  // Variables (wrangler.jsonc "vars", or the dashboard)
  IDENTITY_PROVIDER?: string;        // "skippercast" (passkeys) or none
  BOAT_LOOKUP_ENABLED?: string;      // "false" is the kill switch
  BOAT_LOOKUP_GLOBAL_DAILY_LIMIT?: string;
  BOAT_AI_MODEL?: string;
  EXTRA_ORIGINS?: string;            // comma-separated extra allowed origins (staging, wrangler dev)
  // Text Advisor vars (repository variables copied by scripts/wrangler_config.mjs);
  // read only through advisorSettings() in server/advisor/settings.ts, which holds the defaults.
  TEXT_ADVISOR_ENABLED?: string;     // "true" turns the advisor on; anything else: every advisor route 404s
  ADVISOR_REPLIES_ENABLED?: string;  // "false" stores and acks inbound but sends nothing and calls no model
  ADVISOR_NUMBER?: string;           // the owned number, E.164 (+1XXXXXXXXXX)
  ADVISOR_CHANNEL?: string;          // outbound adapter: "bluebubbles" (default) or "twilio"
  BLUEBUBBLES_PRIVATE_API?: string;  // "true": typing indicators and read receipts (Private API on the Mac)
  ADVISOR_ADMIN_CONTACT_ID?: string; // owner's contact id for the text-based admin fallback
  ADVISOR_INBOX_PUBLIC_REPLIES?: string; // "true": public replies to non-keyword Instagram comments
  ADVISOR_MODEL?: string;            // text model id
  ADVISOR_VISION_MODEL?: string;     // Claude vision fallback model id
  ADVISOR_VISION_PROVIDERS?: string; // ordered comma list of hermes, claude
  ADVISOR_DAILY_MESSAGES_PER_CONTACT?: string;
  ADVISOR_DAILY_LLM_PER_CONTACT?: string;
  ADVISOR_GLOBAL_DAILY_LLM?: string;
  ADVISOR_GLOBAL_DAILY_VISION?: string;
  ADVISOR_PUBLIC_BASE?: string;      // https base for links in replies and Meta-fetchable media
  ADVISOR_REGION_DEFAULT?: string;   // region id for contacts with no home port
  ADVISOR_AUTO_PUBLISH_AFTER?: string; // clean reports before auto-publish is offered
  ADVISOR_SOCIAL_ENABLED?: string;   // "true": publish to Meta; otherwise drafts queue only
  ADVISOR_INBOX_ENABLED?: string;    // "true": Instagram DM and comment handling
  // Secrets (wrangler secret put)
  VAPID_PUBLIC_KEY?: string;
  VAPID_PRIVATE_KEY?: string;
  ANTHROPIC_API_KEY?: string;
  GITHUB_TOKEN?: string;             // cron watchdog and the advisor-media dispatch (TA-M1): Actions read and write
  // Text Advisor secrets: declared now, uploaded by the task that first needs each
  // (01 secrets table); a missing one disables only the feature that needs it.
  ADVISOR_WEBHOOK_TOKEN?: string;    // BlueBubbles webhook path secret
  BLUEBUBBLES_URL?: string;          // Cloudflare Tunnel to the Mac relay
  BLUEBUBBLES_PASSWORD?: string;
  CF_ACCESS_CLIENT_ID?: string;      // Cloudflare Access service token presented to the Tunnel
  CF_ACCESS_CLIENT_SECRET?: string;
  TWILIO_ACCOUNT_SID?: string;       // Twilio adapter and signature check
  TWILIO_AUTH_TOKEN?: string;
  TWILIO_FROM?: string;
  HERMES_VISION_URL?: string;        // Hermes local classifier
  HERMES_VISION_TOKEN?: string;
  META_APP_ID?: string;              // Graph API app and webhook verification
  META_APP_SECRET?: string;
  META_VERIFY_TOKEN?: string;
  META_IG_USER_ID?: string;          // Instagram professional account and long-lived token
  META_IG_TOKEN?: string;
  META_PAGE_ID?: string;             // Facebook Page and Page token
  META_PAGE_TOKEN?: string;
  ADVISOR_PHONE_KEY?: string;        // 32-byte master key (base64) for phone hashing and encryption
  CF_ANALYTICS_TOKEN?: string;       // Analytics Engine SQL reads for the admin funnel
  CLOUDFLARE_ACCOUNT_ID?: string;    // TA-W4: the account the Analytics Engine SQL API reads (uploaded with CF_ANALYTICS_TOKEN)
}

/** Per-request values the middleware sets for the routes. */
export interface Variables {
  requestId: string;
  path: string;                       // raw (still percent-encoded) URL path, as routed
  identityProvider: string;
  extraOrigins: Set<string>;
  identify: () => Promise<SessionUser | null>;
  user: SessionUser | null | undefined; // set once identify() has run
  owner: string;                      // the signed-in user id on private routes
}

export type AppEnv = {Bindings: Env; Variables: Variables};
