// Conditions for get_conditions (docs/plans/text-advisor/06-angler-answers.md §
// planning, AD-4): the trip date in the person's words, the fishing window's
// wind, gusts, seas, swell period and direction from the regional forecast feed
// (regions/<id>/region.json intelligence_feed, the same feed the trip checker
// reads through server/trips.ts; its parser is private, so this is a small one
// of our own, tested on tests/fixtures/feeds/intelligence.json), the comfort
// word for the reference boat (answers/comfort.ts), and the NWS small craft /
// gale / hazardous seas alerts the daily feed recorded for the region's zones.
// Never a catch number, never a clearance.
import {addDays, daysBetween, localParts, PACIFIC} from './time.ts';
import {fold} from './resolve.ts';
import {hourComfort, limitedComfort, verdictFor, COMFORT_WORD, BOAT_PHRASE} from './comfort.ts';
import type {Verdict} from './comfort.ts';
import type {Region} from '../../types.ts';

export const HORIZON_DAYS = 7;
export interface Window {start: number; end: number}
export const WINDOW: Readonly<Window> = Object.freeze({start: 6, end: 14});

// ---- dates ------------------------------------------------------------------------------

const WEEKDAYS: [string[], number][] = [
  [['sunday', 'sun', 'domingo', 'dom'], 0], [['monday', 'mon', 'lunes', 'lun'], 1], [['tuesday', 'tue', 'tues', 'martes', 'mar'], 2],
  [['wednesday', 'wed', 'miercoles', 'mie'], 3], [['thursday', 'thu', 'thur', 'thurs', 'jueves', 'jue'], 4],
  [['friday', 'fri', 'viernes', 'vie'], 5], [['saturday', 'sat', 'sabado', 'sab'], 6],
];
export interface TripDates {dates: string[]; beyond_horizon: boolean; days_ahead: number; parsed: boolean; past?: boolean}

/**
 * The local dates a word means (06 § planning step 1): ISO dates; today/hoy;
 * tomorrow/mañana; the day after tomorrow/pasado mañana; a weekday name in
 * English or Spanish (the next one, today counts); "this weekend"/"fin de
 * semana" (both days, from today when it is already the weekend); "next
 * <weekday>" (a week later when it is within three days). Nothing parsed →
 * today, parsed: false. Beyond seven days → beyond_horizon.
 */
export function parseTripDate(text: string | null | undefined, now: number, tz = PACIFIC): TripDates {
  const today = localParts(now, tz), raw = String(text ?? '').trim(), t = ` ${fold(raw)} `;
  const out = (dates: string[], parsed = true): TripDates => {
    const ahead = daysBetween(today.date, dates.at(-1)!);
    return {dates, parsed, days_ahead: daysBetween(today.date, dates[0]!), beyond_horizon: ahead > HORIZON_DAYS, ...(daysBetween(today.date, dates[0]!) < 0 ? {past: true} : {})};
  };
  const iso = /\b(\d{4}-\d{2}-\d{2})\b/.exec(raw);
  if (iso && Number.isFinite(Date.parse(`${iso[1]}T12:00:00Z`))) return out([iso[1]!]);
  if (/ (?:day after tomorrow|pasado manana) /.test(t)) return out([addDays(today.date, 2)]);
  if (/ (?:tomorrow|tmrw|tmr|manana) /.test(t)) return out([addDays(today.date, 1)]);
  if (/ (?:today|tonight|this morning|hoy) /.test(t)) return out([today.date]);
  if (/ (?:weekend|fin de semana|finde) /.test(t)) {
    const toSat = (6 - today.weekday + 7) % 7;
    const next = / next weekend | proximo fin de semana /.test(t) && today.weekday !== 0 && today.weekday !== 6 ? 7 : 0;
    if (today.weekday === 0 && !next) return out([today.date]);
    const sat = addDays(today.date, toSat + next);
    return out([sat, addDays(sat, 1)]);
  }
  for (const [names, day] of WEEKDAYS) {
    if (!names.some(n => t.includes(` ${n} `))) continue;
    let ahead = (day - today.weekday + 7) % 7;
    if (/ (?:next|proximo|el otro) /.test(t) && ahead <= 3) ahead += 7;
    return out([addDays(today.date, ahead)]);
  }
  return out([today.date], false);
}

// ---- the regional forecast feed ----------------------------------------------------------

/* eslint-disable @typescript-eslint/no-explicit-any */
type Feed = any;
const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
function sample(data: Feed, key: string, time: number, unit: string): number | null {
  const h = data?.hourly, i = Array.isArray(h?.time) ? h.time.indexOf(time) : -1;
  if (data?.hourly_units?.[key] !== unit || data?.hourly_units?.time !== 'unixtime' || i < 0 || !finite(h?.[key]?.[i])) return null;
  return h[key][i];
}

export interface Hour {
  time: number; wind: number | null; gust: number | null; wind_from: number | null;
  sea: number | null; sea_period: number | null; chop: number | null; chop_period: number | null;
  swell: number | null; swell_period: number | null; swell_from: number | null;
  secondary: number | null; secondary_from: number | null;
  other_wind: number | null; other_sea: number | null; other_gust: number | null;
}

/** One hour at one forecast point: GFS wind and GFS-Wave partitions, with ECMWF wind and WAM seas as the second opinion. */
export function readHour(feed: Feed, point: number, time: number): Hour {
  const m = feed?.forecast?.models ?? {};
  const at = (id: string, key: string, unit: string) => m[id]?.error ? null : sample(m[id]?.data?.[point], key, time, unit);
  const period = at('ncep_gfswave016', 'wave_period', 's');
  const valid = period === null || period > 0;
  return {
    time, wind: at('gfs_global', 'wind_speed_10m', 'kn'), gust: at('gfs_global', 'wind_gusts_10m', 'kn'), wind_from: at('gfs_global', 'wind_direction_10m', '°'),
    sea: valid ? at('ncep_gfswave016', 'wave_height', 'ft') : null, sea_period: valid ? period : null,
    chop: at('ncep_gfswave016', 'wind_wave_height', 'ft'), chop_period: at('ncep_gfswave016', 'wind_wave_period', 's'),
    swell: at('ncep_gfswave016', 'swell_wave_height', 'ft'), swell_period: at('ncep_gfswave016', 'swell_wave_period', 's'), swell_from: at('ncep_gfswave016', 'swell_wave_direction', '°'),
    secondary: at('ncep_gfswave016', 'secondary_swell_wave_height', 'ft'), secondary_from: at('ncep_gfswave016', 'secondary_swell_wave_direction', '°'),
    other_wind: at('ecmwf_ifs025', 'wind_speed_10m', 'kn'), other_gust: at('ecmwf_ifs025', 'wind_gusts_10m', 'kn'), other_sea: at('ecmwf_wam', 'wave_height', 'ft'),
  };
}

/** Comfort score for one hour, as the app scores it: the full rubric when every part is there, else the limited one (capped). */
export function rateHour(h: Hour): number | null {
  const winds = [h.wind, h.other_wind].filter(finite), seas = [h.sea, h.other_sea].filter(finite);
  if (!winds.length || !seas.length) return null;
  const gusts = ([[h.wind, h.gust], [h.other_wind, h.other_gust]] as const).filter(([w, g]) => finite(w) && finite(g) && g >= w).map(([, g]) => g as number);
  const complete = [h.wind, h.sea, h.sea_period, h.chop, h.swell, h.swell_from, h.other_wind, h.other_sea].every(finite) && gusts.length === 2;
  if (complete) return hourComfort({wind: h.wind, gust: h.gust, sea: {height: h.sea}, chop: {height: h.chop, period: h.chop_period}, swell: {height: h.swell, from: h.swell_from},
    secondary: {height: h.secondary, from: h.secondary_from}}, {wind: h.other_wind, sea: {height: h.other_sea}}, Math.max(...gusts));
  return Math.min(6.9, limitedComfort(Math.max(...winds), Math.max(...seas), gusts.length ? Math.max(...gusts) : null));
}

const COMPASS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
export const compass = (deg: number | null): string | null => finite(deg) ? COMPASS[Math.round((((deg % 360) + 360) % 360) / 22.5) % 16]! : null;
/** Circular mean of bearings. */
function meanBearing(values: (number | null)[]): number | null {
  const v = values.filter(finite);
  if (!v.length) return null;
  const x = v.reduce((s, d) => s + Math.cos(d * Math.PI / 180), 0), y = v.reduce((s, d) => s + Math.sin(d * Math.PI / 180), 0);
  return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
}
const round = (n: number | null, step = 1): number | null => finite(n) ? Math.round(n / step) * step : null;
const range = (values: (number | null)[], step = 1): [number, number] | null => {
  const v = values.filter(finite);
  return v.length ? [round(Math.min(...v), step)!, round(Math.max(...v), step)!] : null;
};

export interface DayConditions {
  date: string; window: string; available: boolean; reason?: string;
  wind_kt: [number, number] | null; wind_from: string | null; gusts_kt: number | null;
  seas_ft: [number, number] | null; sea_period_s: number | null;
  swell_ft: [number, number] | null; swell_period_s: number | null; swell_from: string | null;
  comfort: string; comfort_for: string; models_agree: boolean | null;
}

/** The fishing window at a forecast point on one local date. */
export function windowConditions(feed: Feed, region: Region, pointId: string, date: string, window: Window = WINDOW): DayConditions {
  const base = {date, window: `${String(window.start).padStart(2, '0')}:00-${String(window.end).padStart(2, '0')}:00`, comfort_for: BOAT_PHRASE};
  const empty = (reason: string): DayConditions => ({...base, available: false, reason, wind_kt: null, wind_from: null, gusts_kt: null, seas_ft: null, sea_period_s: null,
    swell_ft: null, swell_period_s: null, swell_from: null, comfort: COMFORT_WORD.unknown, models_agree: null});
  const point = region.forecast_points.findIndex(p => p.id === pointId);
  if (point < 0 || feed?.region_id !== region.id) return empty('regional forecast unavailable');
  const times: number[] = (feed?.forecast?.models?.gfs_global?.data?.[point]?.hourly?.time ?? []).filter((t: unknown) => {
    if (!finite(t)) return false;
    const p = localParts(t * 1000, region.timezone);
    return p.date === date && p.hour >= window.start && p.hour <= window.end;
  });
  if (!times.length) return empty('the forecast does not cover this window yet');
  const hours = times.map(t => readHour(feed, point, t));
  const scores = hours.map(rateHour);
  const rated = scores.filter(finite);
  const verdict: Verdict = rated.length ? verdictFor({conditions: Math.min(...rated)}) : 'unknown';
  const agree = hours.filter(h => [h.wind, h.other_wind, h.sea, h.other_sea].every(finite));
  return {...base, available: true,
    wind_kt: range(hours.map(h => h.wind)), wind_from: compass(meanBearing(hours.map(h => h.wind_from))),
    gusts_kt: round(Math.max(...hours.map(h => h.gust).filter(finite), -Infinity)) ?? null,
    seas_ft: range(hours.map(h => Math.max(h.sea ?? -Infinity, h.other_sea ?? -Infinity)).map(v => v === -Infinity ? null : v)),
    sea_period_s: round(median(hours.map(h => h.sea_period))),
    swell_ft: range(hours.map(h => h.swell)), swell_period_s: round(median(hours.map(h => h.swell_period))), swell_from: compass(meanBearing(hours.map(h => h.swell_from))),
    comfort: COMFORT_WORD[verdict],
    models_agree: agree.length ? agree.every(h => Math.abs(h.wind! - h.other_wind!) <= 4 && Math.abs(h.sea! - h.other_sea!) <= 1) : null,
  };
}
function median(values: (number | null)[]): number | null {
  const v = values.filter(finite).sort((a, b) => a - b);
  return v.length ? v[Math.floor(v.length / 2)]! : null;
}

// ---- advisories --------------------------------------------------------------------------

export const ADVISORY = /small craft|gale|storm warning|hurricane force|hazardous seas|high surf|special marine|beach hazards/i;
export interface Advisory {event: string; headline: string | null; zone: string; onset: string | null; ends: string | null}

/**
 * NWS alerts the daily feed recorded for the region's marine zones
 * (sources['alerts-<zone>'].data.alerts), keeping the boating ones that overlap
 * [from, to] (epoch ms). Small craft, gale and hazardous seas come first.
 */
export function advisoriesFrom(daily: Feed, zones: readonly string[], from: number, to: number): Advisory[] {
  const out: Advisory[] = [];
  for (const zone of zones) {
    const alerts = daily?.sources?.[`alerts-${zone}`]?.data?.alerts;
    if (!Array.isArray(alerts)) continue;
    for (const a of alerts) {
      if (typeof a?.event !== 'string' || !ADVISORY.test(a.event)) continue;
      const start = Date.parse(a.onset ?? a.effective ?? ''), end = Date.parse(a.ends ?? a.expires ?? '');
      if ((Number.isFinite(start) && start > to) || (Number.isFinite(end) && end < from)) continue;
      if (!out.some(o => o.event === a.event && o.onset === (a.onset ?? null))) out.push({event: a.event, headline: typeof a.headline === 'string' ? a.headline.slice(0, 200) : null, zone, onset: a.onset ?? null, ends: a.ends ?? a.expires ?? null});
    }
  }
  const rank = (e: string) => /gale|storm|hurricane/i.test(e) ? 0 : /small craft/i.test(e) ? 1 : /hazardous seas/i.test(e) ? 2 : 3;
  return out.sort((a, b) => rank(a.event) - rank(b.event));
}

/** The zones whose alerts the daily feed checked, for a region (coastal first). */
export function regionZones(region: Region): string[] {
  const zones = Object.values(region.marine_zones ?? {});
  return [...new Set(zones)];
}

/** The local epoch range of [start hour, end hour] on `date` in `tz`, approximately (to the hour). */
export function windowEpochs(date: string, tz: string, window: Window = WINDOW): [number, number] {
  // Find the UTC instant whose local date and hour match, searching around noon UTC of the date.
  const base = Date.parse(`${date}T00:00:00Z`);
  let start = NaN, end = NaN;
  for (let h = -14; h <= 38; h++) {
    const t = base + h * 3600000, p = localParts(t, tz);
    if (p.date !== date) continue;
    if (p.hour === window.start && Number.isNaN(start)) start = t;
    if (p.hour === window.end) end = t + 3599999;
  }
  return [start, end];
}
