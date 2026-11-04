/** The web client's fallback zone until a region's own `timezone` loads (every active region is Pacific; RF0935-2). */
export const DEFAULT_ZONE = 'America/Los_Angeles';

const zones = new Map<string, boolean>();
/** RF0510-2: a region's zone is a 1..64-char string Intl knows; answers are cached (few region ids, at most 64 kept). */
export function validZone(value: unknown): value is string {
  if (typeof value !== 'string' || !value || value.length > 64) return false;
  let ok = zones.get(value);
  if (ok === undefined) { try { new Intl.DateTimeFormat('en-US', {timeZone: value}); ok = true; } catch { ok = false; } if (zones.size < 64) zones.set(value, ok); }
  return ok;
}
