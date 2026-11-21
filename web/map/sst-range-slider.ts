import type {SstRangeMode} from './sst-range.ts';

export const STEP_F = 0.5;

const PAGE_STEP_F = 5 * STEP_F;
type Range = {min: number; max: number};
type Handle = keyof Range;
type Bounds = {lo: number; hi: number};

export function sliderBounds(analysis: Range): Bounds | null {
  const lo = Math.ceil(analysis.min / STEP_F) * STEP_F;
  const hi = Math.floor(analysis.max / STEP_F) * STEP_F;
  if (!Number.isFinite(lo) || !Number.isFinite(hi) || hi - lo < STEP_F) return null;
  return {lo, hi};
}

// Move only the selected handle of an existing slider range.
export function moveHandle(range: Range, which: Handle, value: number, bounds: Bounds): Range {
  if (!Number.isFinite(value)) return {min: range.min, max: range.max};
  const snapped = Math.round(value / STEP_F) * STEP_F;
  const clamped = Math.min(bounds.hi, Math.max(bounds.lo, snapped));
  return which === 'min'
    ? {min: Math.min(clamped, range.max - STEP_F), max: range.max}
    : {min: range.min, max: Math.max(clamped, range.min + STEP_F)};
}

export function keyHandle(range: Range, which: Handle, key: string, bounds: Bounds): Range | null {
  const current = range[which];
  let value: number;
  switch (key) {
    case 'ArrowLeft':
    case 'ArrowDown': value = current - STEP_F; break;
    case 'ArrowRight':
    case 'ArrowUp': value = current + STEP_F; break;
    case 'PageDown': value = current - PAGE_STEP_F; break;
    case 'PageUp': value = current + PAGE_STEP_F; break;
    case 'Home': value = bounds.lo; break;
    case 'End': value = bounds.hi; break;
    default: return null;
  }
  return moveHandle(range, which, value, bounds);
}

export function customMode({min, max}: Range): Extract<SstRangeMode, {mode: 'custom'}> {
  return {mode: 'custom', min, max};
}
