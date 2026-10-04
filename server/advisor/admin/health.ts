// The admin Health view's data (docs/plans/text-advisor/08-website.md § Admin,
// Health; TA-W2): GET /api/admin/health. Read-only: nothing here pings a
// provider or counts against a cap, except Meta's publishing quota (TA-S0):
// GET content_publishing_limit, at most once per META_QUOTA_TTL_MS (the banner
// reads this every minute), cached in job_state advisor.meta.quota. The
// Facebook-Login Page token does not expire (09 § facts), so there is no
// token expiry to show. Hermes health comes with the Hermes vision provider.
// TA-S6: the inbox switches, and subscribeWebhooks (the "Subscribe webhooks" action).
import {advisorSettings} from '../settings.ts';
import {relayState} from '../relay.ts';
import {downKey} from '../vision/index.ts';
import {mediaJobPending} from '../media.ts';
import {igPublishingLimit, igSubscribeApps, metaConfig, metaConfigured, MetaError, SUBSCRIBED_FIELDS} from '../social/meta.ts';
import type {Fetcher} from '../social/meta.ts';
import type {Env} from '../../env.ts';

export const STALE_QUEUED_MS = 2 * 60000;          // 08: open `queued` messages older than 2 min
export const META_QUOTA_TTL_MS = 10 * 60000;       // TA-S0: the publishing quota is read from Meta at most every 10 minutes
export const META_QUOTA_KEY = 'advisor.meta.quota';

/** 09 § Publishing: whether the Meta secrets are set, and the Instagram publishing quota (50 API posts per 24 h). */
export interface MetaHealth {configured: boolean; quota_usage: number | null; quota_total: number | null; checked_at: string | null; error: 'unavailable' | null}

export interface AdminHealth {
  checked_at: string;
  enabled: boolean; replies_enabled: boolean; channel: string;
  relay: {state: 'up' | 'down'; failures: number; checked_at: string; last_ok_at: string | null} | null;
  queue: {stale_queued: number; oldest_queued_at: string | null; held_outbound: number; failed_today: number};
  vision: {name: string; down_until: string | null}[];
  caps: {day: string; llm: {used: number; limit: number}; vision: {used: number; limit: number}};
  media_jobs: {pending: number};
  reviews: {open: number};
  meta: MetaHealth;
  // TA-S6: the Instagram inbox switches and whether Meta's webhook can be verified (09 § Inbox).
  inbox: {enabled: boolean; public_replies: boolean; webhook_ready: boolean};
}

const count = async (db: D1Database, sql: string, ...args: unknown[]): Promise<number> => (await db.prepare(sql).bind(...args).first<{n: number}>())?.n ?? 0;

/**
 * The Meta line: not configured (no call), the cached quota when younger than
 * META_QUOTA_TTL_MS, else one content_publishing_limit read (stored either way,
 * so a failing Meta is asked again only after the TTL).
 */
export async function metaHealth(env: Env, now: number, fetcher?: Fetcher): Promise<MetaHealth> {
  if (!metaConfigured(env)) return {configured: false, quota_usage: null, quota_total: null, checked_at: null, error: null};
  const db = env.DB!;
  const cached = await db.prepare('SELECT value FROM job_state WHERE key=?').bind(META_QUOTA_KEY).first<{value: string}>();
  try {
    const value = JSON.parse(cached?.value ?? 'null') as MetaHealth | null;
    if (value?.checked_at && now - Date.parse(value.checked_at) < META_QUOTA_TTL_MS && now >= Date.parse(value.checked_at)) return {...value, configured: true};
  } catch { /* re-read */ }
  const at = new Date(now).toISOString();
  let result: MetaHealth;
  try {
    // A health read is one try: a rate-limited Meta is shown as unavailable rather than retried in the request.
    const limit = await igPublishingLimit(metaConfig(env, {...(fetcher ? {fetcher} : {}), attempts: 1})!, env.META_IG_USER_ID!);
    result = {configured: true, quota_usage: limit.quota_usage, quota_total: limit.quota_total, checked_at: at, error: null};
  } catch {
    result = {configured: true, quota_usage: null, quota_total: null, checked_at: at, error: 'unavailable'};
  }
  await db.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at')
    .bind(META_QUOTA_KEY, JSON.stringify(result), at).run();
  return result;
}

export async function adminHealth(env: Env, now: number = Date.now(), deps: {metaFetcher?: Fetcher} = {}): Promise<AdminHealth> {
  const db = env.DB!, settings = advisorSettings(env), at = new Date(now).toISOString();
  const day = Math.floor(now / 86400000), dayStart = new Date(day * 86400000).toISOString();
  const stale = new Date(now - STALE_QUEUED_MS).toISOString();
  const relay = await relayState(env).catch(() => null);
  const oldest = await db.prepare("SELECT MIN(created_at) AS at FROM advisor_messages WHERE direction='in' AND status='queued' AND created_at<?").bind(stale).first<{at: string | null}>();
  const used = async (key: string): Promise<number> => (await db.prepare('SELECT count FROM request_limits WHERE id=?').bind(`${key}:${day}`).first<{count: number}>())?.count ?? 0;
  const vision = await Promise.all(settings.visionProviders.map(async name => {
    const v = (await db.prepare('SELECT value FROM job_state WHERE key=?').bind(downKey(name)).first<{value: string}>())?.value ?? null;
    return {name, down_until: v && Date.parse(v) > now ? v : null};
  }));
  return {
    checked_at: at, enabled: settings.enabled, replies_enabled: settings.repliesEnabled, channel: settings.channel,
    relay: relay ? {state: relay.state, failures: relay.failures, checked_at: relay.checked_at, last_ok_at: relay.last_ok_at} : null,
    queue: {
      stale_queued: await count(db, "SELECT COUNT(*) AS n FROM advisor_messages WHERE direction='in' AND status='queued' AND created_at<?", stale),
      oldest_queued_at: oldest?.at ?? null,
      held_outbound: await count(db, "SELECT COUNT(*) AS n FROM advisor_messages WHERE direction='out' AND status='held'"),
      failed_today: await count(db, "SELECT COUNT(*) AS n FROM advisor_messages WHERE status='failed' AND created_at>=?", dayStart),
    },
    vision,
    // The engine's and the vision provider's UTC-day counters (engine.ts countToday, vision/claude.ts takeVisionCall).
    caps: {day: dayStart.slice(0, 10), llm: {used: await used('global:advisor-llm'), limit: settings.globalDailyLlm}, vision: {used: await used('global:vision'), limit: settings.globalDailyVision}},
    // TA-M1 media.ts mediaJobPending: images without derived_at the job still has to derive (over 4.5 MB,
    // HEIC, stored sideways, or queued/approved/posted) plus pending graphics, the same count the cron dispatches on.
    media_jobs: {pending: await mediaJobPending(db)},
    reviews: {open: await count(db, "SELECT COUNT(*) AS n FROM advisor_reviews WHERE status='open'")},
    meta: await metaHealth(env, now, deps.metaFetcher),   // TA-S0
    inbox: {enabled: settings.inboxEnabled, public_replies: settings.inboxPublicReplies, webhook_ready: Boolean(env.META_VERIFY_TOKEN && env.META_APP_SECRET)},
  };
}

export type SubscribeOutcome = {status: 'ok'; subscribed: boolean; fields: string} | {status: 'not-configured' | 'failed'; error: string};
/**
 * TA-S6, the Health view's "Subscribe webhooks": POST /<ig-user-id>/subscribed_apps
 * with subscribed_fields=messages,comments, so Meta delivers the account's DMs
 * and comments to the app's webhook (09 § Inbox). One try; the answer carries
 * Meta's codes only.
 */
export async function subscribeWebhooks(env: Env, fetcher?: Fetcher): Promise<SubscribeOutcome> {
  const cfg = metaConfig(env, {...(fetcher ? {fetcher} : {}), attempts: 1});
  if (!cfg) return {status: 'not-configured', error: 'the META_* secrets are not set'};
  try {
    return {status: 'ok', subscribed: await igSubscribeApps(cfg, env.META_IG_USER_ID!), fields: SUBSCRIBED_FIELDS};
  } catch (error) {
    return {status: 'failed', error: error instanceof MetaError ? error.message : 'the request failed'};
  }
}
