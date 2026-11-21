import {parseEddiesTile, type Eddy} from './eddies-feed.ts';

type ManifestFrame = {validAt: string; tile: unknown};
type EddiesFrame =
  | {state: 'ready'; frameTime: string; eddies: Eddy[]}
  | {state: 'none'; reason: 'bad-time' | 'no-frame' | 'bad-tile'};

export function eddiesFrameTimes(frames: readonly ManifestFrame[]): string[] {
  const byInstant = new Map<number, string>();
  for (const {validAt} of frames) {
    const instant = Date.parse(validAt);
    if (!Number.isNaN(instant) && !byInstant.has(instant)) byInstant.set(instant, validAt);
  }
  return [...byInstant].sort(([a], [b]) => a - b).map(([, validAt]) => validAt);
}

export function eddiesFrameFor(frames: readonly ManifestFrame[], validAt: string): EddiesFrame {
  const instant = Date.parse(validAt);
  if (Number.isNaN(instant)) return {state: 'none', reason: 'bad-time'};

  for (const frame of frames) {
    if (Date.parse(frame.validAt) !== instant) continue;
    try {
      const parsed = parseEddiesTile(frame.tile);
      if (parsed.ok && Date.parse(parsed.frameTime) === instant) {
        return {state: 'ready', frameTime: parsed.frameTime, eddies: parsed.eddies};
      }
    } catch {
      // Reading the tile property itself can fail before the parser runs.
    }
    return {state: 'none', reason: 'bad-tile'};
  }
  return {state: 'none', reason: 'no-frame'};
}
