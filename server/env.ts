// Worker bindings, variables and secrets, written from wrangler.jsonc. Every
// binding is optional here because the Worker must degrade (fail closed or no-op)
// where one is absent: local tests, a bare `wrangler dev`, a new deployment.
// tests/test_worker_types.mjs checks this list against wrangler.jsonc.
import type {SessionUser} from './auth.ts';
import type {TripCheckMessage} from './trip-queue.ts';

export interface Env {
  // Bindings (wrangler.jsonc)
  ASSETS?: Fetcher;                  // assets.binding: the built site in dist/client
  DB?: D1Database;                   // d1_databases: accounts, trips, alerts, limits
  FEEDS?: R2Bucket;                  // r2_buckets: published feeds and tiles
  PUBLIC_LIMITER?: RateLimit;        // ratelimits: /api/om, 60 a minute per IP
  FEED_LIMITER?: RateLimit;          // ratelimits: /feeds/, 300 a minute per IP
  ANALYTICS?: AnalyticsEngineDataset; // optional Workers Analytics Engine dataset (boat lookup usage)
  // Added to the deploy config only with ENABLE_QUEUES=true (scripts/wrangler_config.mjs):
  TRIP_QUEUE?: Queue<TripCheckMessage>; // queues.producers: skippercast-trip-checks (server/trip-queue.ts)
  // Variables (wrangler.jsonc "vars", or the dashboard)
  IDENTITY_PROVIDER?: string;        // "skippercast" (passkeys) or none
  BOAT_LOOKUP_ENABLED?: string;      // "false" is the kill switch
  BOAT_LOOKUP_GLOBAL_DAILY_LIMIT?: string;
  BOAT_AI_MODEL?: string;
  EXTRA_ORIGINS?: string;            // comma-separated extra allowed origins (staging, wrangler dev)
  // Secrets (wrangler secret put)
  VAPID_PUBLIC_KEY?: string;
  VAPID_PRIVATE_KEY?: string;
  ANTHROPIC_API_KEY?: string;
  GITHUB_TOKEN?: string;             // cron watchdog: Actions read and write
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
