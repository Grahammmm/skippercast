// Kept in the lazy alerts body: the brief need not load the form or the planner's alert code.
import {dateRange, profileTripDefaults, validAlertDate, type AlertFields, type RegionAlerts} from '../alerts.ts';
import type {BriefAlertSeed} from '../brief-alerts.ts';
import type {StringId} from '../i18n.ts';
import {nearestArea} from '../planner-alerts.ts';

const HOUR = 3600000, DAY = 24 * HOUR;

function windowHours(seed: BriefAlertSeed, timeZone: string): [number, number] | null {
  const {start, end, date} = seed;
  if (![start, end].every(at => Number.isFinite(new Date(at).getTime()) && at % 1000 === 0)) return null;
  const clock = new Intl.DateTimeFormat('en-CA', {timeZone, year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23'});
  // Represent local clock readings as UTC numbers for comparison only, not as instants to save.
  const wall = (at: number) => {
    const {year, month, day, hour, minute, second} = Object.fromEntries(clock.formatToParts(at).map(p => [p.type, p.value]));
    return Date.parse(`${year}-${month}-${day}T${hour}:${minute}:${second}Z`);
  };
  const midnight = Date.parse(`${date}T00:00:00Z`);
  if (!Number.isFinite(midnight) || new Date(midnight).toISOString().slice(0, 10) !== date) return null;
  const a = wall(start), b = wall(end), from = (a - midnight) / HOUR, until = (b - midnight) / HOUR;
  if (!Number.isInteger(from) || !Number.isInteger(until) || from < 0 || until > 23 || from >= until || b - a !== end - start) return null;
  // Even when the elapsed span is right, an endpoint in a repeated hour cannot name which occurrence to watch.
  const repeated = (at: number, local: number) => [at - DAY, at + DAY].some(sample => {
    const other = local - (wall(sample) - sample);
    return other !== at && wall(other) === local;
  });
  return repeated(start, a) || repeated(end, b) ? null : [from, until];
}

/** Project against the region and clock the sheet actually loaded. Missing fields remain honest blanks. */
export function briefAlertPrefill(seed: BriefAlertSeed, region: RegionAlerts, now = Date.now()) {
  const date = validAlertDate(seed.date, dateRange(region.timezone, now)) ? seed.date : '';
  const hours = windowHours(seed, region.timezone);
  const forecast_points = region.forecast_points.flatMap(p =>
    typeof p?.latitude === 'number' && typeof p.longitude === 'number' ? [{...p, latitude: p.latitude, longitude: p.longitude}] : []);
  const point = (seed.port ? nearestArea({...region, forecast_points}, seed.port)?.id : null) ?? '';
  const fields: AlertFields = {point, start_hour: hours?.[0] ?? '', end_hour: hours?.[1] ?? ''};
  if (seed.ownLimits) {
    const {wind, gust, sea} = profileTripDefaults(seed.ownLimits);
    Object.assign(fields, {wind_limit: wind, gust_limit: gust, sea_limit: sea});
  }
  const notes: StringId[] = [];
  if (!date) notes.push('alerts.problem.date');
  if (!point) notes.push('alerts.prefill.area');
  if (!hours) notes.push('alerts.prefill.hours');
  return {date, fields, notes};
}
