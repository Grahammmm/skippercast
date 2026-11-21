import {localParts, pastDays} from './hour.ts';

const MAX_OFFSET = 7;

export type PastDayChoice =
  | {kind: 'today'}
  | {kind: 'past'; offset: number; day: string; weekday: string}
  | {kind: 'unshown'; offset: number; day: string; reason: 'not-observed'};

export function parsePastOffset(value: string | null): number | null {
  if (value === null || value.length !== 2 || !/^-[1-7]$/.test(value)) return null;
  return -Number(value);
}

/** `now` must be a valid Date. Offsets count local calendar days, not observations. */
export function resolvePastDay(value: string | null, now: Date, tz: string, available: readonly string[]): PastDayChoice {
  const offset = parsePastOffset(value);
  if (offset === null) return {kind: 'today'};

  const [year, month, date] = localParts(now, tz).day.split('-').map(Number);
  // Use UTC only for arithmetic on the local date, not for choosing Today.
  const target = new Date(0);
  target.setUTCFullYear(year!, month! - 1, date! - offset);
  const day = `${target.getUTCFullYear()}-${String(target.getUTCMonth() + 1).padStart(2, '0')}-${String(target.getUTCDate()).padStart(2, '0')}`.padStart(10, '0');
  const observed = pastDays(now, tz, available).find(d => d.day.padStart(10, '0') === day);
  return observed
    ? {kind: 'past', offset, day, weekday: observed.weekday}
    : {kind: 'unshown', offset, day, reason: 'not-observed'};
}

export function pastDayParam(offset: number): string {
  if (!Number.isInteger(offset) || offset < 1 || offset > MAX_OFFSET) {
    throw new RangeError('Past day offset must be an integer from 1 to 7');
  }
  return `-${offset}`;
}
