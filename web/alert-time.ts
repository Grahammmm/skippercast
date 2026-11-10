// SC2252-07: when a marine alert under Conditions → Before you go starts and ends, in the region zone.
// Display only: the alert's published clocks are read, never rewritten, clipped or guessed. Each end is
// judged on its own, so a readable start survives an unreadable end and the other way round.
import {t, type Language} from './i18n.ts';
import {localTime} from './view-copy.ts';

// An explicit-offset ISO date-time: a date-only or zone-less clock would be read in the device zone.
const ISO = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?(?:Z|[+-](\d{2}):(\d{2}))$/;
const FORMAT: Intl.DateTimeFormatOptions = {weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short'};

/** The instant `value` names, or null when it is not a readable explicit-offset clock on the calendar. */
export function alertInstant(value: string | null | undefined): Date | null {
  const m = typeof value === 'string' ? ISO.exec(value.trim()) : null;
  if (!m) return null;
  const [y, mo, d, h, mi, s, oh, om] = m.slice(1).map(x => Number(x ?? 0));
  const lastDay = new Date(Date.UTC(y!, mo!, 0)).getUTCDate();   // day 0 of the next month: this month's last day
  if (mo! < 1 || mo! > 12 || d! < 1 || d! > lastDay || h! > 23 || mi! > 59 || s! > 59 || oh! > 23 || om! > 59) return null;
  const at = Date.parse(m[0]);
  return Number.isFinite(at) ? new Date(at) : null;
}

/** "from <start> to <end>", "until <end>", "from <start>" or null (no readable clock), each end with its own zone name. */
export function alertTimeSpan(effective: string | null, expires: string | null, tz: string, lang: Language): string | null {
  const start = alertInstant(effective), end = alertInstant(expires);
  const text = (at: Date) => localTime(at, tz, lang, FORMAT);
  if (start && end) return t('conditions.alert.range', lang, {start: text(start), end: text(end)});
  if (end) return t('conditions.alert.until', lang, {end: text(end)});
  if (start) return t('conditions.alert.from', lang, {start: text(start)});
  return null;
}
