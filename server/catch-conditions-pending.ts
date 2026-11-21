import { parseConditionsV1, type ConditionsV1 } from './conditions-v1.ts';

export const PENDING_MAX_AGE_DAYS = 8;
export const PENDING_BATCH_MAX = 100;
const MAX_AGE_MS = PENDING_MAX_AGE_DAYS * 24 * 60 * 60 * 1000;
const FUTURE_SKEW_MS = 5 * 60 * 1000;

type PendingRow = { id: string; started_at: string; conditions: unknown };
type Candidate = { id: string; time: number };

function isPending(conditions: unknown): boolean {
  if (typeof conditions === 'string') {
    try {
      conditions = JSON.parse(conditions);
    } catch {
      return false;
    }
  }
  const parsed = parseConditionsV1(conditions);
  return parsed.ok && 'pending' in parsed.value;
}

function utcTime(value: string): number {
  if (typeof value !== 'string' || !/^(?:\d{4}|[+-]\d{6})-\d{2}-\d{2}T(?:[01]\d|2[0-3]):\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|\+00:00)$/.test(value)) return NaN;
  const time = Date.parse(value);
  // Reject calendar rollover and dates whose interpretation would depend on the host zone.
  return Number.isFinite(time) && new Date(time).toISOString().split('T')[0] === value.split('T')[0] ? time : NaN;
}

export function pendingBatch(rows: readonly PendingRow[], now: Date, limit: number): {
  fill: string[]; expire: string[]; skipped: number;
} {
  const nowMs = now.getTime();
  const cap = Number.isInteger(limit) && limit >= 0 ? Math.min(limit, PENDING_BATCH_MAX) : 0;
  const fill: Candidate[] = [];
  const expire: Candidate[] = [];
  let skipped = 0;

  for (const { id, started_at, conditions } of rows) {
    if (!isPending(conditions)) continue;
    const time = utcTime(started_at);
    const age = nowMs - time;
    if (typeof id !== 'string' || id.length === 0 || !Number.isFinite(age) || age < -FUTURE_SKEW_MS) {
      skipped++;
      continue;
    }
    (age > MAX_AGE_MS ? expire : fill).push({ id, time });
  }

  fill.sort((a, b) => a.time - b.time || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  expire.sort((a, b) => a.time - b.time);
  return { fill: fill.slice(0, cap).map(row => row.id), expire: expire.map(row => row.id), skipped };
}

export function expiredConditions(): Extract<ConditionsV1, { missing: string }> {
  return { v: 1, missing: 'not archived' };
}
