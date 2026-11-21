import {WATCH_LAYERS, WATCH_OPS, type WatchLayer, type WatchOp} from './spot-watch-rules.ts';

export type Watch = {
  id: string;
  spotId: string;
  layer: WatchLayer;
  op: WatchOp;
  a: number;
  b: number | null;
  enabled: boolean;
  lastState: 'true' | 'false' | 'unknown' | null;
  lastSampleAt: string | null;
  lastFiredAt: string | null;
  createdAt: string;
};

function ownSpotId(row: unknown): unknown {
  try {
    if (row !== null && (typeof row === 'object' || typeof row === 'function') && Object.hasOwn(row, 'spot_id')) {
      return (row as Record<string, unknown>).spot_id;
    }
  } catch {
    // An unreadable spot ID cannot be attributed to this list.
  }
  return undefined;
}

function finite(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function project(row: unknown, spotId: unknown): Watch | null {
  try {
    if (typeof spotId !== 'string' || spotId === '') return null;
    if (row === null || typeof row !== 'object' || Array.isArray(row)) return null;
    const prototype: unknown = Object.getPrototypeOf(row);
    if (prototype !== Object.prototype && prototype !== null) return null;

    const fields = row as Record<string, unknown>;
    const {id, layer: rawLayer, op: rawOp, a, enabled, last_state: lastState,
      last_sample_at: lastSampleAt, last_fired_at: lastFiredAt, created_at: createdAt} = fields;
    if (typeof id !== 'string' || id === '' || typeof createdAt !== 'string' || createdAt === '') return null;
    const layer = WATCH_LAYERS.find(value => value === rawLayer);
    const op = WATCH_OPS.find(value => value === rawOp);
    if (layer === undefined || op === undefined || !finite(a)) return null;
    const b = Object.hasOwn(fields, 'b') ? fields.b : null;
    if (op === 'between') {
      if (!finite(b) || b <= a) return null;
    } else if (b !== null) return null;
    if (enabled !== 0 && enabled !== 1) return null;
    if (lastState !== null && lastState !== 'true' && lastState !== 'false' && lastState !== 'unknown') return null;
    if (lastSampleAt !== null && typeof lastSampleAt !== 'string') return null;
    if (lastFiredAt !== null && typeof lastFiredAt !== 'string') return null;
    return {id, spotId, layer, op, a, b,
      enabled: enabled === 1, lastState, lastSampleAt, lastFiredAt, createdAt};
  } catch {
    return null;
  }
}

export function watchView(row: unknown): Watch | null {
  return project(row, ownSpotId(row));
}

export function watchList(rows: readonly unknown[], spotId: string): {watches: Watch[]; dropped: number} {
  const watches: Watch[] = [];
  let dropped = 0;
  for (const row of rows) {
    const own = ownSpotId(row);
    if (own !== spotId) continue;
    const watch = project(row, own);
    if (watch === null) dropped++;
    else watches.push(watch);
  }
  watches.sort((a, b) => {
    const left = a.createdAt === b.createdAt ? a.id : a.createdAt;
    const right = a.createdAt === b.createdAt ? b.id : b.createdAt;
    return left < right ? -1 : left > right ? 1 : 0;
  });
  return {watches, dropped};
}
