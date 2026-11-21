import { frontDistanceNm } from './front-distance.ts';

type FrontItem = { value: number; product: string; sample_at: string }
  | { missing: 'no position' | 'bad time' | 'not archived' | 'no fronts' };

// Require a zone before parsing: Date.parse also accepts host-local timestamps.
// A bare numeric offset must follow a clock time, not the final part of a date.
const EXPLICIT_ZONE = /(?:Z|\b(?:UT|UTC|GMT|[ECMP][SD]T)(?:[+-]\d{2}:?\d{2})?|:\d{2}(?:\.\d+)?\s*[+-]\d{2}:?\d{2})$/i;

function instant(value: unknown): number {
  if (typeof value !== 'string') return NaN;
  const text = value.trim();
  return EXPLICIT_ZONE.test(text) ? Date.parse(text) : NaN;
}

export function catchFrontItem(
  point: { lat: number; lon: number } | null, doc: unknown, startedAt: string, tz: string,
): FrontItem {
  if (point === null) return { missing: 'no position' };
  const started = instant(startedAt);
  if (!Number.isFinite(started)) return { missing: 'bad time' };
  let calendar: Intl.DateTimeFormat;
  try {
    calendar = new Intl.DateTimeFormat('en-CA', {
      timeZone: tz, era: 'short', year: 'numeric', month: 'numeric', day: 'numeric',
    });
  } catch {
    return { missing: 'bad time' };
  }

  try {
    if (doc === null || typeof doc !== 'object' || Array.isArray(doc)) return { missing: 'not archived' };
    const proto = Object.getPrototypeOf(doc);
    if (proto !== Object.prototype && proto !== null) return { missing: 'not archived' };
    const { product, observed_at } = doc as Record<string, unknown>;
    if (typeof product !== 'string' || !product.trim() || [...product].length > 200) {
      return { missing: 'not archived' };
    }
    const observed = instant(observed_at);
    if (!Number.isFinite(observed) || calendar.format(observed) !== calendar.format(started)) {
      return { missing: 'not archived' };
    }
    const value = frontDistanceNm(point, doc);
    return value === null ? { missing: 'no fronts' } : { value, product, sample_at: new Date(observed).toISOString() };
  } catch {
    // Unknown documents can throw even during prototype or property access.
    return { missing: 'not archived' };
  }
}
