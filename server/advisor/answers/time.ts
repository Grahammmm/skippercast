// Local calendar helpers for the data tools, kept free of the cron and consumer
// modules so a tool file imports nothing that needs the Worker's globals.
const formats = new Map<string, Intl.DateTimeFormat>();
function format(tz: string): Intl.DateTimeFormat {
  let f = formats.get(tz);
  if (!f) { f = new Intl.DateTimeFormat('en-US', {timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', weekday: 'short', hourCycle: 'h23'}); formats.set(tz, f); }
  return f;
}
export const PACIFIC = 'America/Los_Angeles';

/** The local date (YYYY-MM-DD), hour (0-23) and weekday (0 = Sunday) of `epochMs` in `tz`. */
export function localParts(epochMs: number, tz = PACIFIC): {date: string; hour: number; weekday: number} {
  const p: Record<string, string> = {};
  for (const {type, value} of format(tz).formatToParts(new Date(epochMs))) p[type] = value;
  return {date: `${p.year}-${p.month}-${p.day}`, hour: Number(p.hour) % 24, weekday: ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].indexOf(p.weekday!)};
}
/** The local date of `epochMs` in `tz`. */
export const localDate = (epochMs: number, tz = PACIFIC): string => localParts(epochMs, tz).date;
/** A YYYY-MM-DD date plus `days` (calendar arithmetic, no time zone). */
export const addDays = (date: string, days: number): string => new Date(Date.parse(`${date}T12:00:00Z`) + days * 86400000).toISOString().slice(0, 10);
/** Whole days from `a` to `b` (both YYYY-MM-DD). */
export const daysBetween = (a: string, b: string): number => Math.round((Date.parse(`${b}T12:00:00Z`) - Date.parse(`${a}T12:00:00Z`)) / 86400000);
