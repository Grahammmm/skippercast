import {nextWatchState, type WatchCondition, type WatchSnapshot} from './spot-watch-state.ts';
import {cellIndex, sampleAt, type HabitatCellIndex} from '../web/map/habitat-sample.ts';

export type WatchFrame = {
  sampleAt: string;
  fields: readonly string[];
  resolution: readonly [number, number];
  rows: readonly (readonly unknown[])[];
  valueField?: string;
};

export type WatchInput = {
  id: string;
  layer: string;
  cond: WatchCondition;
  prev: WatchSnapshot;
  lat: number;
  lon: number;
};

export type WatchEvaluation = {
  id: string;
  next: WatchSnapshot;
  fire: boolean;
  value: number | null;
  reason: null | 'gap' | 'outside' | 'withheld' | 'bad-tile';
};

export function indexFrame(frame: WatchFrame): HabitatCellIndex {
  return cellIndex(frame.rows, frame.resolution, frame.fields, frame.valueField);
}

function unavailable(w: WatchInput, reason: 'withheld' | 'bad-tile'): WatchEvaluation {
  return {id: w.id, next: w.prev, fire: false, value: null, reason};
}

export function evaluateWatch(w: WatchInput, frame: WatchFrame | null, index?: HabitatCellIndex): WatchEvaluation {
  if (frame === null) return unavailable(w, 'withheld');
  try {
    const sample = sampleAt(index ?? indexFrame(frame), w.lat, w.lon);
    const {value} = sample;
    const reason = 'reason' in sample ? sample.reason : value === null ? 'gap' : null;
    const {state, lastSampleAt, fire} = nextWatchState(w.prev, value, frame.sampleAt, w.cond);
    return {id: w.id, next: {state, lastSampleAt}, fire, value, reason};
  } catch {
    return unavailable(w, 'bad-tile');
  }
}

export function evaluateWatches(
  watches: readonly WatchInput[],
  frames: ReadonlyMap<string, WatchFrame>,
  deps: {index?: (f: WatchFrame) => HabitatCellIndex} = {},
): WatchEvaluation[] {
  const buildIndex = deps.index ?? indexFrame;
  // Key by frame identity and memoize failures too, so bad rows are not retried per watch.
  const indexes = new Map<WatchFrame, HabitatCellIndex | null>();
  return watches.map(w => {
    const frame = frames.get(w.layer);
    if (!frame) return evaluateWatch(w, null);
    let index = indexes.get(frame);
    if (index === undefined) {
      try {
        index = buildIndex(frame);
      } catch {
        index = null;
      }
      indexes.set(frame, index);
    }
    return index === null ? unavailable(w, 'bad-tile') : evaluateWatch(w, frame, index);
  });
}
