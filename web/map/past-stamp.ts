import {localParts} from '../hour.ts';
import type {PastDayChoice} from '../past-day.ts';

// Match pastDays in hour.ts: an observation must carry an explicit zone.
const ISO_INSTANT = /^(\d{4}-\d{2}-\d{2})T(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})$/;

type PastStamp =
  | {show: true; day: string; weekday: string}
  | {show: false; reason: 'today' | 'unshown' | 'no-frame' | 'bad-time' | 'day-mismatch'};

export function pastStamp(choice: PastDayChoice, frameSampleAt: string | null, tz: string): PastStamp {
  if (choice.kind === 'today') return {show: false, reason: 'today'};
  if (choice.kind === 'unshown') return {show: false, reason: 'unshown'};
  if (frameSampleAt === null) return {show: false, reason: 'no-frame'};

  const date = ISO_INSTANT.exec(frameSampleAt)?.[1];
  if (!date) return {show: false, reason: 'bad-time'};
  const at = new Date(frameSampleAt);
  // Date may normalize an impossible date instead of rejecting it.
  if (!Number.isFinite(at.getTime()) || new Date(date).getUTCDate() !== Number(date.slice(-2))) {
    return {show: false, reason: 'bad-time'};
  }

  const {day, weekday} = localParts(at, tz);
  if (day !== choice.day) return {show: false, reason: 'day-mismatch'};
  return {show: true, day, weekday};
}
