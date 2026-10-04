// The admin Health view's data (docs/plans/text-advisor/08-website.md § Admin,
// Health; TA-W2): GET /api/admin/health. Read-only: nothing here pings a
// provider or counts against a cap. Meta's token expiry and publishing quota
// come with TA-S0; Hermes health with the Hermes vision provider.
import {advisorSettings} from '../settings.ts';
import {relayState} from '../relay.ts';
import {downKey} from '../vision/index.ts';
import {mediaJobPending} from '../media.ts';
import type {Env} from '../../env.ts';

export const STALE_QUEUED_MS = 2 * 60000;          // 08: open `queued` messages older than 2 min

export interface AdminHealth {
  checked_at: string;
  enabled: boolean; replies_enabled: boolean; channel: string;
  relay: {state: 'up' | 'down'; failures: number; checked_at: string; last_ok_at: string | null} | null;
  queue: {stale_queued: number; oldest_queued_at: string | null; held_outbound: number; failed_today: number};
  vision: {name: string; down_until: string | null}[];
  caps: {day: string; llm: {used: number; limit: number}; vision: {used: number; limit: number}};
  media_jobs: {pending: number};
  reviews: {open: number};
  meta: null;
}

const count = async (db: D1Database, sql: string, ...args: unknown[]): Promise<number> => (await db.prepare(sql).bind(...args).first<{n: number}>())?.n ?? 0;

export async function adminHealth(env: Env, now: number = Date.now()): Promise<AdminHealth> {
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
    meta: null,   // TA-S0
  };
}
