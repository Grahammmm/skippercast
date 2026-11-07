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
export const utc = (iso: string): string => `${iso.slice(0, 16).replace('T', ' ')} UTC`;

/** Usable when the time parses, is not in the future (5 min of clock slack) and is within `limitHours`. */
export const freshWithin = (iso: unknown, limitHours: number, now: Date): iso is string =>
  typeof iso === 'string' && Number.isFinite(Date.parse(iso)) && hoursOld(iso, now) >= -5 / 60 && hoursOld(iso, now) <= limitHours;

/**
 * Re-checks `check` every minute while a layer is on: when the data has aged out, `expire` removes it and the
 * status reads stale (the withheld-after-limit rule holds while the page stays open).
 */
export function expireWhenStale(ctx: PreviewContext, check: () => boolean, expire: () => void): () => void {
  const timer = setInterval(() => { if (!check()) { clearInterval(timer); expire(); } }, 60_000);
  return () => clearInterval(timer);
}

export const handle = (...cleanups: Array<() => void>): PreviewHandle => ({destroy() { for (const c of cleanups) c(); }});
