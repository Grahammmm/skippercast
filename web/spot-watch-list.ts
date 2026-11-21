export const WATCH_LAYERS = Object.freeze(['water-temp', 'chlorophyll', 'sst-contrast'] as const);
export const WATCH_OPS = Object.freeze(['>=', '<=', 'between'] as const);

export interface WatchRow {
  id: string;
  layer: typeof WATCH_LAYERS[number];
  op: typeof WATCH_OPS[number];
  a: number | null;
  b: number | null;
  enabled: boolean;
  firing: boolean;
  lastFiredAt: string | null;
}

// Read data without running getters. Proxy descriptor traps can still throw.
function field(row: unknown, key: string | number): unknown {
  if (row === null || typeof row !== 'object') return undefined;
  try {
    return Object.getOwnPropertyDescriptor(row, key)?.value;
  } catch {
    return undefined;
  }
}

function* entries(rows: readonly unknown[]): Generator<unknown> {
  const length = field(rows, 'length');
  if (typeof length !== 'number' || !Number.isSafeInteger(length) || length > 0xffffffff) return;
  for (let i = 0; i < length; i++) yield field(rows, i);
}

const nonEmpty = (value: unknown): value is string => typeof value === 'string' && value.length > 0;
const finite = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null;
const text = (value: unknown): string | null => typeof value === 'string' ? value : null;
const compare = (a: string, b: string): number => a < b ? -1 : a > b ? 1 : 0;

function compareDates(a: string | null, b: string | null): number {
  if (a === b) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  return compare(a, b);
}

export function watchList(watches: readonly unknown[], spots: readonly unknown[]): {
  groups: {spotId: string; spotName: string; watches: WatchRow[]}[];
  orphans: number;
} {
  const bySpot = new Map<string, {spotName: string; entries: {created: string | null; row: WatchRow}[]}>();
  for (const spot of entries(spots)) {
    const id = field(spot, 'id'), name = field(spot, 'name');
    if (nonEmpty(id) && nonEmpty(name) && !bySpot.has(id)) bySpot.set(id, {spotName: name, entries: []});
  }

  let orphans = 0;
  for (const watch of entries(watches)) {
    const id = field(watch, 'id');
    const rawLayer = field(watch, 'layer'), rawOp = field(watch, 'op');
    const layer = WATCH_LAYERS.find(option => option === rawLayer);
    const op = WATCH_OPS.find(option => option === rawOp);
    if (!nonEmpty(id) || layer === undefined || op === undefined) continue;
    const spotId = field(watch, 'spot_id');
    const spot = typeof spotId === 'string' ? bySpot.get(spotId) : undefined;
    if (!spot) {
      orphans++;
      continue;
    }

    const rawEnabled = field(watch, 'enabled');
    const enabled = rawEnabled === 1 || rawEnabled === true;
    spot.entries.push({created: text(field(watch, 'created_at')), row: {
      id, layer, op, a: finite(field(watch, 'a')), b: finite(field(watch, 'b')), enabled,
      firing: enabled && field(watch, 'last_state') === 'true',
      lastFiredAt: text(field(watch, 'last_fired_at')),
    }});
  }

  const groups = Array.from(bySpot, ([spotId, {spotName, entries}]) => ({spotId, spotName,
    watches: entries.sort((a, b) => compareDates(a.created, b.created) || compare(a.row.id, b.row.id))
      .map(({row}) => row),
  })).filter(group => group.watches.length > 0);
  groups.sort((a, b) => a.spotName.localeCompare(b.spotName, undefined, {sensitivity: 'base'})
    || compare(a.spotId, b.spotId));
  return {groups, orphans};
}
