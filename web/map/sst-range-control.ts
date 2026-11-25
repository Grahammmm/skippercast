import type {ShownRange, SstRangeMode} from './sst-range.ts';

export const RANGE_MODES = ['analysis', 'view', 'custom'] as const;

type RangeMode = (typeof RANGE_MODES)[number];
type Ends = {min: number; max: number};

export function modeKey(
  current: RangeMode,
  key: 'ArrowLeft' | 'ArrowRight' | 'Home' | 'End',
): RangeMode {
  if (key === 'Home') return RANGE_MODES[0];
  if (key === 'End') return RANGE_MODES[2];
  const step = key === 'ArrowLeft' ? -1 : 1;
  return RANGE_MODES[RANGE_MODES.indexOf(current) + step] ?? current;
}

function validEnds({min, max}: Ends): boolean {
  return Number.isFinite(min) && Number.isFinite(max) && min < max;
}

export function chooseRangeMode(
  target: RangeMode,
  shown: ShownRange,
  lastCustom: Ends | null,
): SstRangeMode {
  if (target !== 'custom') return {mode: target};
  if (lastCustom !== null && validEnds(lastCustom)) {
    return {mode: 'custom', min: lastCustom.min, max: lastCustom.max};
  }
  if (!validEnds(shown)) return {mode: 'analysis'};

  const min = Math.ceil(shown.min * 2) / 2;
  const max = Math.floor(shown.max * 2) / 2;
  // Keep the displayed span if it cannot fit two distinct half-degree steps.
  return min < max ? {mode: 'custom', min, max} : {mode: 'custom', min: shown.min, max: shown.max};
}

export function rememberCustom(previous: Ends | null, mode: SstRangeMode): Ends | null {
  return mode.mode === 'custom' ? {min: mode.min, max: mode.max} : previous;
}
