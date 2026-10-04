// The Mac relay's stored state (docs/plans/text-advisor/01-architecture.md
// § Idempotency and failure rules): job_state key advisor.relay, written by the
// watchdog in cron.ts and read by the consumer's relay-down hold, the held
// release and /api/advisor/health. Its own module so consumer.ts and cron.ts
// can both read it without importing each other.
import type {Env} from '../env.ts';

export const RELAY_KEY = 'advisor.relay';
export interface RelayState {state: 'up' | 'down'; failures: number; checked_at: string; last_ok_at: string | null}

/** The stored relay state, or null when never checked (or unreadable). */
export async function relayState(env: Pick<Env, 'DB'>): Promise<RelayState | null> {
  if (!env.DB) return null;
  const raw = (await env.DB.prepare('SELECT value FROM job_state WHERE key=?').bind(RELAY_KEY).first<{value: string}>())?.value;
  try { const v = raw ? JSON.parse(raw) : null; return v && (v.state === 'up' || v.state === 'down') ? v : null; } catch { return null; }
}
