export type EntryTimePlace = {started_at: string; lat: number | null; lon: number | null};

export type SnapshotAction =
  | {action: 'compute'}
  | {action: 'keep'}
  | {action: 'store'; conditions: {v: 1; missing: 'future time' | 'bad time'} | {v: 1; pending: true}};

// Date.parse also accepts bare dates and local times. Look for an offset after
// the clock so that a date's own hyphens don't look like offsets.
const EXPLICIT_ZONE = /(?:\dZ\b|\d:\d{1,2}(?::\d{1,2}(?:\.\d+)?)?\s*[+-]\d{1,4}(?::\d{2})?\b|\b(?:Z|UT|UTC|GMT|[ECMP][SD]T)\b)/i;

export function snapshotAction(before: EntryTimePlace | null, after: EntryTimePlace, now: Date, degraded: boolean): SnapshotAction {
  try {
    const startedAt = after.started_at;
    const at = Date.parse(startedAt);
    // Compare instants before validating the new spelling, and never equate two NaNs.
    if (before !== null && Date.parse(before.started_at) === at
        && Object.is(before.lat, after.lat) && Object.is(before.lon, after.lon)) return {action: 'keep'};
    if (!Number.isNaN(at) && EXPLICIT_ZONE.test(startedAt.replace(/\([^()]*\)/g, ''))) {
      if (at > Date.prototype.getTime.call(now)) return {action: 'store', conditions: {v: 1, missing: 'future time'}};
      return degraded ? {action: 'store', conditions: {v: 1, pending: true}} : {action: 'compute'};
    }
  } catch {
    // Unreadable time/place inputs cannot be used to compute a snapshot.
  }
  return {action: 'store', conditions: {v: 1, missing: 'bad time'}};
}

export function isPending(conditions: unknown): boolean {
  if (conditions === null || typeof conditions !== 'object') return false;
  try {
    if (Array.isArray(conditions)) return false;
    const proto = Object.getPrototypeOf(conditions);
    if (proto !== Object.prototype && proto !== null) return false;
    const marker = conditions as {v?: unknown; pending?: unknown};
    return marker.v === 1 && marker.pending === true;
  } catch {
    return false;
  }
}

export function pendingBatch(entries: readonly {id: string; created_at: string; conditions: unknown}[], max: number): string[] {
  if (!Number.isInteger(max) || max < 1 || max > 500) throw new RangeError('max must be an integer from 1 to 500');

  const pending: {id: string; at: number}[] = [];
  for (const entry of entries) {
    try {
      if (!isPending(entry.conditions)) continue;
      const at = Date.parse(entry.created_at);
      pending.push({id: entry.id, at: Number.isNaN(at) ? Infinity : at});
    } catch {
      // An unreadable row must not stop the rest of the batch.
    }
  }
  pending.sort((a, b) => a.at === b.at ? (a.id < b.id ? -1 : a.id > b.id ? 1 : 0) : a.at - b.at);
  return pending.slice(0, max).map(entry => entry.id);
}
