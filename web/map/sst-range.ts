export type SstRangeMode = {mode: 'analysis'} | {mode: 'view'} | {mode: 'custom'; min: number; max: number};

type Range = {min: number; max: number};

export type ShownRange = {
  min: number;
  max: number;
  mode: 'analysis' | 'view' | 'custom';
  note: null | 'no-water-in-view' | 'clamped' | 'reverted';
};

function cellCentre(start: number, end: number, i: number, n: number): number {
  const t = (i + 0.5) / n;
  const span = end - start;
  // Finite endpoints on either side of zero can have an infinite span.
  return Number.isFinite(span) ? start + span * t : start * (1 - t) + end * t;
}

export function viewSamples(
  sample: (lon: number, lat: number) => number | null | undefined,
  bounds: readonly [number, number, number, number],
  n = 32,
): number[] {
  const [west, south, east, north] = bounds;
  if (![west, south, east, north].every(Number.isFinite) || west >= east || south >= north
      || !Number.isInteger(n) || n <= 0) return [];

  const values: number[] = [];
  for (let row = 0; row < n; row++) {
    const lat = cellCentre(south, north, row, n);
    for (let col = 0; col < n; col++) {
      const lon = cellCentre(west, east, col, n);
      let value: number | null | undefined;
      try {
        value = sample(lon, lat);
      } catch {
        continue;
      }
      if (typeof value === 'number' && Number.isFinite(value)) values.push(value);
    }
  }
  return values;
}

export function rangeOf(values: readonly number[]): Range | null {
  let min = Infinity;
  let max = -Infinity;
  for (const value of values) {
    if (!Number.isFinite(value)) continue;
    min = Math.min(min, value);
    max = Math.max(max, value);
  }
  if (min === Infinity) return null;
  return min === max ? {min: min - 0.5, max: max + 0.5} : {min, max};
}

export function shownRange(
  mode: SstRangeMode,
  analysis: Range,
  view: Range | null,
  previous: Range | null = null,
): ShownRange {
  if (mode.mode === 'analysis') {
    return {min: analysis.min, max: analysis.max, mode: 'analysis', note: null};
  }
  if (mode.mode === 'view') {
    const {min, max} = view ?? previous ?? analysis;
    return {min, max, mode: 'view', note: view === null ? 'no-water-in-view' : null};
  }
  const min = Math.max(mode.min, analysis.min);
  const max = Math.min(mode.max, analysis.max);
  if (Number.isFinite(min) && Number.isFinite(max) && min < max) {
    return {min, max, mode: 'custom', note: min !== mode.min || max !== mode.max ? 'clamped' : null};
  }
  return {min: analysis.min, max: analysis.max, mode: 'analysis', note: 'reverted'};
}
