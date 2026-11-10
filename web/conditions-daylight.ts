// SC2252-08: the dock day's sunrise and sunset under Conditions → Tide events, for every profile, in the region zone.
// Display only: the brief's own astronomy (packages/coast daily.ts astro) is read, never recomputed or guessed. Both
// events must be readable explicit-offset clocks on the selected regional date, sunset after sunrise; otherwise the
// whole pair is unavailable, never one time on its own.
import {dateKey} from '../packages/coast/src/daily.ts';
import {alertInstant} from './alert-time.ts';
import {clock} from './brief/clock.ts';
import {t, type Language} from './i18n.ts';

export type DaylightFields = {readonly date: string; readonly sunrise: string | null; readonly sunset: string | null};

/** The zone's short name at `at` ("PDT", "PST"), read in the region zone at that instant. */
const zoneName = (at: Date, tz: string): string =>
  new Intl.DateTimeFormat('en-US', {timeZone: tz, timeZoneName: 'short'}).formatToParts(at).find(p => p.type === 'timeZoneName')?.value ?? '';

/** "Sunrise 6:52 am · sunset 5:04 pm PST" for `day` in `tz`, or the unavailable sentence. */
export function daylightText(brief: DaylightFields | null | undefined, day: string, tz: string, lang: Language): string {
  const none = t('conditions.daylight.unavailable', lang);
  if (!brief || brief.date !== day) return none;
  const rise = alertInstant(brief.sunrise), set = alertInstant(brief.sunset);
  if (!rise || !set || set.getTime() <= rise.getTime() || dateKey(rise, tz) !== day || dateKey(set, tz) !== day) return none;
  const riseZone = zoneName(rise, tz), setZone = zoneName(set, tz);
  const sunrise = clock(rise.toISOString(), tz, lang) + (riseZone === setZone ? '' : ` ${riseZone}`);
  return t('conditions.daylight', lang, {sunrise, sunset: clock(set.toISOString(), tz, lang), zone: setZone});
}
