export type WatchCondition =
  | {op: '>=' | '<='; a: number; b?: number | null}
  | {op: 'between'; a: number; b: number};

export type WatchState = 'true' | 'false' | 'unknown';

export interface WatchSnapshot {
  /** Last known result, or 'unknown' if no known reading has been evaluated. */
  readonly state: WatchState;
  /** Timestamp of the latest evaluation, including an unknown result. */
  readonly lastSampleAt: string | null;
}

/** Compare in the layer's units, with inclusive bounds (both ends of `between`).
 * Threshold validation (layer ranges and a < b) belongs to the watch API.
 * Null (e.g. a gap or a withheld layer) or a nonfinite reading is unknown.
 */
export function conditionMet(value: number | null, {op, a, b}: WatchCondition): boolean | null {
  if (value === null || !Number.isFinite(value)) return null;
  switch (op) {
    case '>=': return value >= a;
    case '<=': return value <= a;
    case 'between': return value >= a && value <= b;
  }
}

// Compare zoned sample timestamps by instant, not by their spelling.
function sampleTime(sampleAt: string | null): number {
  return sampleAt !== null && /T.*(?:Z|[+-]\d{2}:\d{2})$/.test(sampleAt) ? Date.parse(sampleAt) : NaN;
}

/**
 * R4: It fires only on a false → true transition with a newer `sample_at`
 * than the last evaluation. An `unknown` result never fires and never resets state.
 * Start with {state: 'unknown', lastSampleAt: null}; an initial true only sets the baseline.
 */
export function nextWatchState(
  prev: WatchSnapshot, value: number | null, sampleAt: string | null, cond: WatchCondition,
): WatchSnapshot & {fire: boolean} {
  const sample = sampleTime(sampleAt);
  if (!Number.isFinite(sample) || (prev.lastSampleAt !== null && !(sample > sampleTime(prev.lastSampleAt)))) {
    return {state: prev.state, fire: false, lastSampleAt: prev.lastSampleAt};
  }

  const met = conditionMet(value, cond);
  return {
    state: met === null ? prev.state : met ? 'true' : 'false',
    fire: prev.state === 'false' && met === true,
    lastSampleAt: sampleAt,
  };
}
