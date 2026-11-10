// SC1407-04 (#1762 R2): hot per-hour and per-render paths reuse one Intl.DateTimeFormat per locale, zone and
// options instead of constructing a new one on every call. Shared by packages/coast and the web app through direct
// relative imports. The formatter is exactly `new Intl.DateTimeFormat(locale, {...options, timeZone})`, so every
// formatted string is unchanged; a locale or zone Intl rejects throws the native error and is never cached.
// At most 64 formatters are kept (the cap web/zone.ts uses); the oldest inserted one is dropped first.
const CAP = 64;
const formatters = new Map<string, Intl.DateTimeFormat>();

export function dateTimeFormat(locale: string, timeZone: string, options: Readonly<Omit<Intl.DateTimeFormatOptions, 'timeZone'>>): Intl.DateTimeFormat {
  const pattern = Object.entries(options).filter(([, value]) => value !== undefined).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0);
  const key = JSON.stringify([locale, timeZone, pattern]);
  let format = formatters.get(key);
  if (!format) {
    format = new Intl.DateTimeFormat(locale, {...options, timeZone});
    if (formatters.size >= CAP) formatters.delete(formatters.keys().next().value!);
    formatters.set(key, format);
  }
  return format;
}
