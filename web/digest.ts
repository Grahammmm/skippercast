// Preview-only content; no delivery or scheduling. Erasable syntax for node tests.
import {STATUS_LABEL, type AlertNames, type SavedTrip} from './alerts.ts';

type DigestTrip = SavedTrip & {enabled?: number; last_assessment?: string | null};
export type WeekendDigest = {days: {date: string; lines: string[]}[]; empty: boolean};
export const EMPTY_WEEKEND = 'No saved trips this weekend. Save a date above to get a day-before assessment.';

/** Calendar dates, independent of the machine's zone (the caller supplies its region's today). */
export function nextWeekend(today: string): {sat: string | null; sun: string} {
  const day = new Date(today + 'T12:00:00Z');
  const weekday = day.getUTCDay();
  const plus = (n: number) => new Date(day.getTime() + n * 86400000).toISOString().slice(0, 10);
  return weekday === 0 ? {sat: null, sun: today} : {sat: plus(6 - weekday), sun: plus(7 - weekday)};
}

function statusWord(trip: DigestTrip): string {
  try {
    const status: unknown = JSON.parse(trip.last_assessment ?? 'null')?.status;
    if (typeof status === 'string' && status) return Object.hasOwn(STATUS_LABEL, status) ? STATUS_LABEL[status]! : status;
  } catch { /* A missing or malformed assessment is not a verdict. */ }
  return 'not assessed yet';
}

/** Keep every enabled weekend trip; sort a copy, never mutate the saved records. */
export function weekendDigest(trips: readonly DigestTrip[], names: AlertNames, today: string): WeekendDigest {
  const {sat, sun} = nextWeekend(today);
  const point = (t: DigestTrip) => names.point.get(t.point) ?? 'a saved spot';
  const days = (sat ? [sat, sun] : [sun]).map(date => ({date, lines: trips
    .filter(t => t.enabled !== 0 && t.date === date)
    .sort((a, b) => a.start_hour - b.start_hour || point(a).localeCompare(point(b)))
    .map(t => `${point(t)} · ${names.species.get(t.species) ?? t.species} · ${t.start_hour}:00–${t.end_hour}:00 — ${statusWord(t)}`)}));
  return {days, empty: days.every(d => d.lines.length === 0)};
}

/** The same plain text is available to a future, separately authorized sender. */
export function toText(digest: WeekendDigest): string {
  return digest.empty ? EMPTY_WEEKEND : digest.days.filter(d => d.lines.length)
    .map(d => [d.date, ...d.lines].join('\n')).join('\n\n');
}
