import {localParts} from './hour.ts';
import {fromStored, unitSymbol} from './spot-watch-units.ts';

type StoredWatch = {
  layer: string;
  op: string;
  a: number;
  b: number | null;
  enabled: boolean;
  lastValue: number | null;
  lastSampleAt: string | null;
};

export type WatchStatus = {
  op: '>=' | '<=' | 'between';
  values: [number] | [number, number];
  unit: string;
  last: {value: number; day: string} | null;
  paused: boolean;
  needsNotifications: boolean;
};

const ISO_INSTANT = /^(\d{4}-\d{2}-\d{2})T(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d(?:\.\d+)?)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/;

function sampleInstant(sample: string): Date | null {
  const day = ISO_INSTANT.exec(sample)?.[1];
  if (!day) return null;
  const at = new Date(sample);
  // Date parses some impossible dates by rolling them into the next month.
  if (!Number.isFinite(at.getTime()) || new Date(day).getUTCDate() !== Number(day.slice(-2))) return null;
  return at;
}

export function watchStatus(w: StoredWatch, temp: 'F' | 'C', tz: string, pushReady: boolean): WatchStatus | null {
  const {layer, op, a, b, enabled, lastValue, lastSampleAt} = w;
  if (layer !== 'water-temp' && layer !== 'chlorophyll' && layer !== 'sst-contrast') return null;
  if (op !== '>=' && op !== '<=' && op !== 'between') return null;
  if (!Number.isFinite(a)) return null;

  const first = fromStored(layer, a, temp);
  let values: WatchStatus['values'] = [first];
  if (op === 'between') {
    if (b === null || !Number.isFinite(b) || b <= a) return null;
    values = [first, fromStored(layer, b, temp)];
  }

  let last: WatchStatus['last'] = null;
  if (lastValue !== null && Number.isFinite(lastValue) && lastSampleAt !== null) {
    const at = sampleInstant(lastSampleAt);
    if (at !== null) last = {value: fromStored(layer, lastValue, temp), day: localParts(at, tz).day};
  }
  return {op, values, unit: unitSymbol(layer, temp), last, paused: !enabled, needsNotifications: enabled && !pushReady};
}
