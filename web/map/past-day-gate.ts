import type {TimeBehaviour} from './layers.ts';

export type PastDayGate =
  | {draw: true; reason: null}
  | {draw: false; reason: 'forecast-only' | 'no-frame' | 'other-day' | 'bad-input'};

const DAY = /^\d{4}-\d{2}-\d{2}$/;
const INSTANT = /^((?:\d{4}|[+-]\d{6})-\d{2}-\d{2})T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})$/;

function isCalendarDate(day: string): boolean {
  const midnight = new Date(`${day}T00:00:00Z`);
  // Date parsing alone can roll an impossible day (e.g. February 30) into the next month.
  return Number.isFinite(midnight.getTime()) && midnight.toISOString().split('T')[0] === day;
}

/** Today leaves the live gates alone. A past observation belongs to one day in the region's zone. */
export function pastDayGate(
  behaviour: TimeBehaviour, selectedDay: string | null, frameSampleAt: string | null, zone: string,
): PastDayGate {
  if (selectedDay === null) return {draw: true, reason: null};
  if (typeof selectedDay !== 'string' || !DAY.test(selectedDay) || !isCalendarDate(selectedDay)
    || typeof zone !== 'string' || (behaviour !== 'static' && behaviour !== 'hour' && behaviour !== 'observed')) {
    return {draw: false, reason: 'bad-input'};
  }

  try {
    const formatter = new Intl.DateTimeFormat('en-US', {
      timeZone: zone, calendar: 'gregory', era: 'short', year: 'numeric', month: '2-digit', day: '2-digit',
    });
    if (behaviour === 'static') return {draw: true, reason: null};
    if (behaviour === 'hour') return {draw: false, reason: 'forecast-only'};
    if (typeof frameSampleAt !== 'string') return {draw: false, reason: 'no-frame'};
    const sampleDay = INSTANT.exec(frameSampleAt)?.[1];
    if (!sampleDay || !isCalendarDate(sampleDay)) return {draw: false, reason: 'no-frame'};
    const instant = Date.parse(frameSampleAt);
    if (!Number.isFinite(instant)) return {draw: false, reason: 'no-frame'};

    const parts = formatter.formatToParts(instant);
    const part = (type: Intl.DateTimeFormatPartTypes) => parts.find(p => p.type === type)?.value;
    // Gregorian era years start at 1 BC, which ISO dates spell as year 0000.
    const year = Number(part('year'));
    const isoYear = part('era') === 'BC' ? 1 - year : year;
    const localDay = `${String(isoYear).padStart(4, '0')}-${part('month')}-${part('day')}`;
    return localDay === selectedDay ? {draw: true, reason: null} : {draw: false, reason: 'other-day'};
  } catch {
    return {draw: false, reason: 'bad-input'};
  }
}
