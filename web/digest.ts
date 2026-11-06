// Preview-only content; no delivery or scheduling. Erasable syntax for node tests.
import {statusLabel, type AlertNames, type SavedTrip} from './alerts.ts';
import {t, type Language} from './i18n.ts';

type DigestTrip = SavedTrip & {enabled?: number; last_assessment?: string | null};
export type WeekendDigest = {days: {date: string; lines: string[]}[]; empty: boolean};
/** The English empty line, kept for callers that read it; toText(digest, lang) says it in `lang`. */
export const EMPTY_WEEKEND = t('digest.empty', 'en');

/** Calendar dates, independent of the machine's zone (the caller supplies its region's today). */
export function nextWeekend(today: string): {sat: string | null; sun: string} {
  const day = new Date(today + 'T12:00:00Z');
  const weekday = day.getUTCDay();
  const plus = (n: number) => new Date(day.getTime() + n * 86400000).toISOString().slice(0, 10);
  return weekday === 0 ? {sat: null, sun: today} : {sat: plus(6 - weekday), sun: plus(7 - weekday)};
}

/** What an assessment's own status means, in numerical-preference words (not a go/no-go or a clearance). */
const ASSESSMENT_WORD = {
  'within limits': 'digest.within',
  'above limits': 'digest.above',
  'unverified': 'digest.unverified',
} as const;

/** Stored hazard notes count only as a whole list of non-empty strings; one bad entry drops them all. */
function storedNotes(hazards: unknown): string[] {
  if (!Array.isArray(hazards) || !hazards.every(note => typeof note === 'string' && note.trim().length > 0)) return [];
  return hazards;
}

/** The chosen status word, then each stored note exactly as stored and in order, behind the prefix server/alert-policy.ts alertMessage writes (only that prefix is translated). */
function statusWord(trip: DigestTrip, lang: Language): string {
  try {
    const assessment: unknown = JSON.parse(trip.last_assessment ?? 'null');
    if (assessment && typeof assessment === 'object' && !Array.isArray(assessment)) {
      const {status, hazards} = assessment as {status?: unknown; hazards?: unknown};
      if (typeof status === 'string' && status) {
        const word = Object.hasOwn(ASSESSMENT_WORD, status) ? t(ASSESSMENT_WORD[status as keyof typeof ASSESSMENT_WORD], lang) : statusLabel(status, lang);
        return word + storedNotes(hazards).map(note => ` ${t('digest.hazard', lang)} ${note}`).join('');
      }
    }
  } catch { /* A missing or malformed assessment is not a verdict. */ }
  return t('digest.notAssessed', lang);
}

/** Keep every enabled weekend trip; sort a copy, never mutate the saved records. The order never depends on the language. */
export function weekendDigest(trips: readonly DigestTrip[], names: AlertNames, today: string, lang: Language = 'en'): WeekendDigest {
  const {sat, sun} = nextWeekend(today);
  const sortName = (trip: DigestTrip) => names.point.get(trip.point) ?? t('digest.spot', 'en');
  const point = (trip: DigestTrip) => names.point.get(trip.point) ?? t('digest.spot', lang);
  const days = (sat ? [sat, sun] : [sun]).map(date => ({date, lines: trips
    .filter(trip => trip.enabled !== 0 && trip.date === date)
    .sort((a, b) => a.start_hour - b.start_hour || sortName(a).localeCompare(sortName(b)))
    .map(trip => `${point(trip)} · ${names.species.get(trip.species) ?? trip.species} · ${trip.start_hour}:00–${trip.end_hour}:00 — ${statusWord(trip, lang)}`)}));
  return {days, empty: days.every(d => d.lines.length === 0)};
}

/** The same plain text is available to a future, separately authorized sender. */
export function toText(digest: WeekendDigest, lang: Language = 'en'): string {
  return digest.empty ? t('digest.empty', lang) : digest.days.filter(d => d.lines.length)
    .map(d => [d.date, ...d.lines].join('\n')).join('\n\n');
}
