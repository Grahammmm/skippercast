import type {WatchCondition} from './spot-watch-state.ts';
import {fToC, M_PER_NMI} from '../web/units.ts';

const KM_PER_NMI = M_PER_NMI / 1000;
const gradientToFeed = (value: number): number => value * 5 / 9 / KM_PER_NMI;

/** Convert stored thresholds to the units of the watch layer's tile field. */
export function toFeedCondition(layer: string, cond: WatchCondition): WatchCondition | null {
  const {a, b} = cond;
  if (!Number.isFinite(a) || (typeof b === 'number' && !Number.isFinite(b))) return null;

  let convert: (value: number) => number;
  switch (layer) {
    case 'water-temp': convert = fToC; break;
    case 'sst-contrast': convert = gradientToFeed; break;
    case 'chlorophyll': return cond;
    default: return null;
  }

  // Preserve an absent b as absent, and an explicit null as null.
  return typeof b === 'number'
    ? {...cond, a: convert(a), b: convert(b)}
    : {...cond, a: convert(a)};
}

/** Convert a tile reading back to the stored watch units. */
export function fromFeedValue(layer: string, value: number | null): number | null {
  if (value === null || !Number.isFinite(value)) return null;
  switch (layer) {
    case 'water-temp': return value * 1.8 + 32;
    case 'sst-contrast': return value * 1.8 * KM_PER_NMI;
    case 'chlorophyll': return value;
    default: return null;
  }
}
