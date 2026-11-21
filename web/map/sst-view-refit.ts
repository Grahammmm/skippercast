import {rangeOf, viewSamples} from './sst-range.ts';

export const REFIT_DELAY_MS = 250;

type Bounds = readonly [w: number, s: number, e: number, n: number];

type Options = {
  sample: (lon: number, lat: number) => number | null | undefined;
  onRange: (range: {min: number; max: number} | null) => void;
  setTimer: (fn: () => void, ms: number) => unknown;
  clearTimer: (handle: unknown) => void;
  delayMs?: number;
};

export function createViewRefit(o: Options): {moveEnd(bounds: Bounds): void; dispose(): void} {
  let pending: {handle: unknown} | undefined;
  let lastFitted: Bounds | undefined;
  let disposed = false;

  function cancelPending(): void {
    if (!pending) return;
    const {handle} = pending;
    pending = undefined;
    o.clearTimer(handle);
  }

  return {
    moveEnd(bounds) {
      if (disposed || !Array.isArray(bounds) || bounds.length !== 4) return;
      const [w, s, e, n] = bounds;
      const view: Bounds = [w, s, e, n];
      if (!view.every(Number.isFinite) || w >= e || s >= n) return;

      // Returning to the fitted view also invalidates any queued fit for another view.
      cancelPending();
      if (lastFitted?.every((edge, i) => Math.abs(edge - view[i]!) <= 1e-9)) return;

      const timer: {handle: unknown} = {handle: undefined};
      pending = timer;
      timer.handle = o.setTimer(() => {
        if (pending !== timer) return;
        pending = undefined;
        // viewSamples already discards throwing samples on a per-cell basis.
        const range = rangeOf(viewSamples(o.sample, view));
        try {
          o.onRange(range);
          lastFitted = view;
        } catch {
          // A failed delivery remains eligible for a retry on the next moveEnd.
        }
      }, o.delayMs ?? REFIT_DELAY_MS);
    },
    dispose() {
      disposed = true;
      cancelPending();
    },
  };
}
