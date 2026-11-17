// Browser-only saved-window export. Explicit fields only: never serialize a private plan.
import type {SavedTrip} from './alerts.ts';
import {DEFAULT_ZONE} from './zone.ts';
import {t, type Language} from './i18n.ts';

/** RFC 5545 TEXT, including all common newline encodings. */
export const escapeText = (text: string): string => text.replace(/\\/g, '\\\\').replace(/\r\n|\r|\n/g, '\\n').replace(/;/g, '\\;').replace(/,/g, '\\,');

/** 75 UTF-8 octets including the continuation space; iterate code points, not code units. */
export function foldLine(line: string): string {
  const encoder = new TextEncoder();
  let out = '', size = 0;
  for (const char of line) {
    const bytes = encoder.encode(char).length;
    if (size + bytes > 75) { out += '\r\n '; size = 1; }
    out += char; size += bytes;
  }
  return out;
}

/** Resolve offsets on the trip's date, never today's or the browser's offset.
 * Repeated wall hours use the first occurrence; missing hours use the offset before the gap (RFC 5545).
 */
export function zonedInstant(date: string, hour: number, zone: string): Date {
  const wall = Date.parse(date + 'T00:00:00Z');
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || !Number.isFinite(wall) || new Date(wall).toISOString().slice(0, 10) !== date || !Number.isInteger(hour) || hour < 0 || hour > 23) throw new RangeError('Invalid trip time');
  const wanted = wall + hour * 3600000;
  const fmt = new Intl.DateTimeFormat('en-CA', {timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23'});
  const local = (at: number) => {
    const p = Object.fromEntries(fmt.formatToParts(at).map(p => [p.type, p.value]));
    return Date.parse(`${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}:${p.second}Z`);
  };
  const offsets = new Set([-86400000, 0, 86400000].map(delta => local(wanted + delta) - (wanted + delta)));
  const candidates = [...offsets].map(offset => wanted - offset).sort((a, b) => a - b);
  return new Date(candidates.find(at => local(at) === wanted) ?? candidates[candidates.length - 1]!);
}

const utc = (date: Date) => date.toISOString().replace(/[-:]/g, '').replace(/\.\d{3}Z$/, 'Z');
export type CalendarOptions = {areaName?: string; speciesNames: string[]; limits: string; appUrl: string; now: Date; timeZone?: string; lang?: Language};

/** One event, built without storage, network or DOM access. */
export function tripCalendar(trip: SavedTrip, {areaName, speciesNames, limits, appUrl, now, timeZone = DEFAULT_ZONE, lang = 'en'}: CalendarOptions): string {
  if (!(trip.end_hour > trip.start_hour)) throw new RangeError('Invalid trip window');
  const start = zonedInstant(trip.date, trip.start_hour, timeZone), end = zonedInstant(trip.date, trip.end_hour, timeZone);
  if (!(end > start)) throw new RangeError('Trip window has no elapsed time');
  const description = [t('alerts.plan.targets', lang, {names: speciesNames.join(' · ')}), limits, t('alerts.calendar.caveat', lang)].join('\n');
  return [
    'BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//SkipperCast//Saved trip//EN', 'CALSCALE:GREGORIAN', 'BEGIN:VEVENT',
    `UID:trip-${escapeText(trip.id)}@skippercast`, `DTSTAMP:${utc(now)}`, `DTSTART:${utc(start)}`, `DTEND:${utc(end)}`,
    `SUMMARY:${escapeText(t('alerts.calendar.summary', lang, {area: areaName || trip.point}))}`,
    `DESCRIPTION:${escapeText(description)}`, `URL:${appUrl.replace(/\/$/, '')}/map#alerts`, 'END:VEVENT', 'END:VCALENDAR',
  ].map(foldLine).join('\r\n') + '\r\n';
}
