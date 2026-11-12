// UXFIX-07: one readable form for a calendar date in text and accessible names: "Tue 10 Nov" / "mar 10 nov".
// The platform's own en-US order prints "Tue, Nov 10", so the parts are put in a fixed order here. Data stays ISO.
import {localeOf, type Language} from './i18n-core.ts';

const formats = new Map<string, Intl.DateTimeFormat>();
const format = (locale: string, timeZone: string): Intl.DateTimeFormat => {
  const key = `${locale}|${timeZone}`;
  let f = formats.get(key);
  if (!f) {
    if (formats.size >= 16) formats.clear();   // bounded: a handful of languages and region zones
    formats.set(key, f = new Intl.DateTimeFormat(locale, {weekday: 'short', day: 'numeric', month: 'short', timeZone}));
  }
  return f;
};

/** `iso` ("2026-11-10") as "Tue 10 Nov" (en) or "mar 10 nov" (es), the same calendar day in `timeZone`; anything else prints as given. */
export function readableDate(iso: string, lang: Language | string, timeZone: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!m) return iso;
  try {
    const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
    const utcNoon = Date.UTC(y, mo - 1, d, 12);
    if (new Date(utcNoon).getUTCDate() !== d) return iso;   // 2026-02-31 is not a day
    // Noon of that day in `timeZone` (not of UTC), so the printed day never slips across the zone's offset.
    const zoned = Object.fromEntries(new Intl.DateTimeFormat('en-US', {timeZone, hourCycle: 'h23', year: 'numeric', month: 'numeric', day: 'numeric', hour: 'numeric', minute: 'numeric'})
      .formatToParts(utcNoon).map(x => [x.type, Number(x.value)])) as Record<string, number>;
    const noon = utcNoon - (Date.UTC(zoned.year!, zoned.month! - 1, zoned.day!, zoned.hour!, zoned.minute!) - utcNoon);
    const p = Object.fromEntries(format(localeOf(lang), timeZone).formatToParts(noon).map(x => [x.type, x.value.replace(/\.$/, '')]));
    return `${p.weekday} ${p.day} ${p.month}`;
  } catch { return iso; }   // an unknown time zone must not break the sheet
}
