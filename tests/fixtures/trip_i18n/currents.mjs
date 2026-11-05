// The dock's frame time (web/map/currents.ts frameTime), copied so the Trip page can be bundled without the map's stylesheet and fonts.
export const frameTime = (iso, tz) => new Intl.DateTimeFormat('en-US', {timeZone: tz, weekday: 'short', hour: 'numeric'}).format(new Date(iso)).replace(',', '').replace('AM', 'am').replace('PM', 'pm');
