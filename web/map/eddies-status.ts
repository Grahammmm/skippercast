import type {EddiesParse} from './eddies-feed.ts';

export type EddiesStatus =
  | {state: 'loading'}
  | {state: 'withheld'; reason: 'bad-tile' | 'bad-time' | 'other-frame'}
  | {state: 'shown'; frameTime: string; count: number; cw: number; ccw: number; largestKm: number | null};

export function eddiesStatus(parsed: EddiesParse | null, validAt: string): EddiesStatus {
  if (parsed === null) return {state: 'loading'};
  if (!parsed.ok) return {state: 'withheld', reason: 'bad-tile'};

  const instant = Date.parse(validAt);
  if (!Number.isFinite(instant)) return {state: 'withheld', reason: 'bad-time'};
  const {frameTime, eddies} = parsed;
  if (Date.parse(frameTime) !== instant) return {state: 'withheld', reason: 'other-frame'};

  let cw = 0;
  let ccw = 0;
  let largest = 0;
  for (const {sense, diameterKm} of eddies) {
    if (sense === 'cw') cw++;
    else ccw++;
    largest = Math.max(largest, diameterKm);
  }
  const count = cw + ccw;
  return {state: 'shown', frameTime, count, cw, ccw, largestKm: count === 0 ? null : Number(largest.toFixed(1))};
}
