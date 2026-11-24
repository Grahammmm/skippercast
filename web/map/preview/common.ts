// Shared by the MAPLIVE-1 preview layers (web/map/preview-layers.ts). Loaded only with a layer's own chunk.
import type {PreviewContext, PreviewHandle} from '../preview-layers.ts';

export const HOUR = 3_600_000;
export const BEFORE_APP_LAYERS = ['swell', 'mpa-fill'] as const;

/** A private JSON file, never from cache; throws a short reason when it is missing or unreadable. */
export async function getJson(ctx: PreviewContext, path: string): Promise<unknown> {
  const response = await ctx.fetchFn(ctx.url(path), {cache: 'no-store', signal: ctx.signal});
  if (!response.ok) throw new Error(`data file not found (HTTP ${response.status})`);
  try { return await response.json(); } catch { throw new Error('data file is not valid JSON'); }
}

export const hoursOld = (iso: string, now: Date): number => (now.getTime() - Date.parse(iso)) / HOUR;
export const ageText = (hours: number): string => hours >= 48 ? `${Math.round(hours / 24)} days old` : `${hours.toFixed(1)} h old`;
export const utc = (iso: string): string => {
  const ms = Date.parse(iso);
  const text = Number.isFinite(ms) ? new Date(ms).toISOString() : iso;
  return `${text.slice(0, 16).replace('T', ' ')} UTC`;
};

export const isPositiveFiniteHours = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value) && value > 0;

// Require a zone on a clock time; Date.parse otherwise uses the device's zone for local date-times.
const zonedTime = /^(\d{4}|[+-]\d{6})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)? *(?:Z|UTC|[+-]\d{2}:?\d{2}) *$/i;

// Date.parse normalises a date that does not exist (Feb 30 reads as Mar 2), so check the calendar date and clock ourselves.
const isRealDateAndClock = (parts: RegExpExecArray): boolean => {
  // Groups 1-5 always take part in a match; group 6 (seconds) is optional. `?? 0` satisfies noUncheckedIndexedAccess.
  const [year, month, day, hour, minute, second] = [1, 2, 3, 4, 5, 6].map((i) => Number(parts[i] ?? 0)) as [number, number, number, number, number, number];
  if (hour > 24 || minute > 59 || second > 59) return false;
  const check = new Date(0);
  check.setUTCFullYear(year, month - 1, day);
  return check.getUTCMonth() === month - 1 && check.getUTCDate() === day;
};

/** Usable when a zoned time parses and is within `limitHours` (with 5 min of future clock slack). */
export const freshWithin = (iso: unknown, limitHours: number, now: Date): iso is string => {
  if (typeof iso !== 'string') return false;
  const parts = zonedTime.exec(iso);
  if (!parts || !isRealDateAndClock(parts)) return false;
  const age = hoursOld(iso, now);
  return age >= -5 / 60 && age <= limitHours;
};

/**
 * Re-checks `check` every minute while a layer is on: when the data has aged out, `expire` removes it and the
 * status reads stale (the withheld-after-limit rule holds while the page stays open).
 */
export function expireWhenStale(ctx: PreviewContext, check: () => boolean, expire: () => void): () => void {
  const timer = setInterval(() => { if (!check()) { clearInterval(timer); expire(); } }, 60_000);
  return () => clearInterval(timer);
}

export const handle = (...cleanups: Array<() => void>): PreviewHandle => ({destroy() { for (const c of cleanups) c(); }});
