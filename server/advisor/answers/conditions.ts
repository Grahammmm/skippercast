// Conditions for get_conditions (docs/plans/text-advisor/06-angler-answers.md §
// planning, AD-4): the trip date in the person's words, the fishing window's
// wind, gusts, seas, swell period and direction from the regional forecast feed
// (regions/<id>/region.json intelligence_feed, the same feed the trip checker
// reads through server/trips.ts; its parser is private, so this is a small one
// of our own, tested on tests/fixtures/feeds/intelligence.json), the comfort
// word for the reference boat (answers/comfort.ts), and the NWS small craft /
// gale / hazardous seas alerts the daily feed recorded for the region's zones.
// Never a catch number, never a clearance.
import {addDays, daysBetween, localParts, PACIFIC, realDate} from './time.ts';
import {fold} from './resolve.ts';
import {verdictFor, COMFORT_WORD, BOAT_PHRASE} from './comfort.ts';
import {LONG_PERIOD_SWELL, MODEL_GAP, rateComfort, REFERENCE_BOAT, type BoatFactors, type FeedHour} from '../../../web/score.ts';
import type {Verdict} from './comfort.ts';
import type {ForecastClock} from './forecast-clock.ts';
import type {Region} from '../../types.ts';

export const HORIZON_DAYS = 7;
export interface Window {start: number; end: number}
export const WINDOW: Readonly<Window> = Object.freeze({start: 6, end: 14});
/** comfort_for when the request sent its boat's factors (MYB-2); BOAT_PHRASE, the reference boat, otherwise. */
export const OWN_BOAT_PHRASE = 'your boat';

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
  if (iso && realDate(iso[1])) return out([iso[1]!]);
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

export interface Hour extends FeedHour {time: number}

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

/** Comfort score for one hour, as the app scores it: the full rubric when every part is there, else the limited one (capped); for `boat`'s factors (the reference boat by default). */
export function rateHour(h: Hour, boat: BoatFactors = REFERENCE_BOAT): number | null {
  return rateComfort(h, boat)?.score ?? null;
}

/**
 * MYB-2: optional boat factors from a request, checked like dist/boat-handling.js boatFactors
 * (sea clamped to 0.45-2.6, wind to 0.6-1.8, chopPeriod finite and above zero). Anything else,
 * NaN included, is rejected (null), so the reference boat rates the hour. The server never reads
 * a browser's saved boat; only what the caller sends.
 */
export function requestBoat(input: unknown): BoatFactors | null {
  if (!input || typeof input !== 'object') return null;
  const {sea, wind, chopPeriod} = input as Record<string, unknown>;
  if (!finite(sea) || !finite(wind) || !finite(chopPeriod) || chopPeriod <= 0) return null;
  return {sea: Math.min(2.6, Math.max(0.45, sea)), wind: Math.min(1.8, Math.max(0.6, wind)), chopPeriod};
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
/** `upper: 'up'` rounds the maximum up to a whole foot (1e-9 absorbs float noise), so a printed maximum is never below the value the window rule used; the minimum still rounds to nearest and never exceeds it. */
const range = (values: (number | null)[], step = 1, upper: 'nearest' | 'up' = 'nearest'): [number, number] | null => {
  const v = values.filter(finite);
  if (!v.length) return null;
  const high = upper === 'up' ? Math.ceil(Math.max(...v) - 1e-9) : round(Math.max(...v), step)!;
  return [Math.min(round(Math.min(...v), step)!, high), high];
};

export interface DayConditions {
  date: string; window: string; available: boolean; reason?: string;
  wind_kt: [number, number] | null; wind_from: string | null; gusts_kt: number | null;
  seas_ft: [number, number] | null; sea_period_s: number | null;
  swell_ft: [number, number] | null; swell_period_s: number | null; swell_from: string | null;
  comfort: string; comfort_for: string; models_agree: boolean | null;
  /** Why a comfort word was held above what the score alone says: Bumpy for a long-period swell hour, Unknown for an old model run; absent when nothing holds it. */
  comfort_held?: string;
}

/** The day as the model run's age allows (forecast-clock.ts): fresh unchanged; held keeps the readings and a rough word but holds any calmer word at unknown; unusable reads as no forecast. */
export function withForecastClock(day: DayConditions, clock: ForecastClock): DayConditions {
  if (clock.state === 'fresh' || !day.available) return day;
  if (clock.state === 'held') return day.comfort === COMFORT_WORD['no-go'] ? day : {...day, comfort: COMFORT_WORD.unknown, comfort_held: `forecast run is ${clock.ageHours} h old`};
  return {date: day.date, window: day.window, comfort_for: day.comfort_for, available: false, reason: 'forecast run is more than 36 hours old or has no run time',
    wind_kt: null, wind_from: null, gusts_kt: null, seas_ft: null, sea_period_s: null, swell_ft: null, swell_period_s: null, swell_from: null, comfort: COMFORT_WORD.unknown, models_agree: null};
}

/** The fishing window at a forecast point on one local date; `boat` (requestBoat) rates it for the caller's boat, else the reference boat. */
export function windowConditions(feed: Feed, region: Region, pointId: string, date: string, window: Window = WINDOW, boat: BoatFactors | null = null): DayConditions {
  const base = {date, window: `${String(window.start).padStart(2, '0')}:00-${String(window.end).padStart(2, '0')}:00`, comfort_for: boat ? OWN_BOAT_PHRASE : BOAT_PHRASE};
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
  // Cached timestamps are not measurements; only readHour's validated samples count.
  if (!hours.some(h => [h.wind, h.gust, h.wind_from, h.sea, h.sea_period, h.chop, h.chop_period,
    h.swell, h.swell_period, h.swell_from, h.secondary, h.secondary_from, h.other_wind, h.other_gust, h.other_sea].some(finite))) {
    return empty('no usable forecast measurements for this window');
  }
  const rows = hours.map(hour => ({hour, score: rateHour(hour, boat ?? REFERENCE_BOAT)}));
  const rated = rows.map(r => r.score).filter(finite);
  const verdict: Verdict = rated.length ? verdictFor({conditions: Math.min(...rated)}) : 'unknown';
  // SC1952-05: the brief's long-period swell hold (verdict.ts longPeriodHour): a Comfortable day with a rated hour in the rule says Bumpy and names the hour.
  const swell = verdict === 'go' ? longPeriodHour(rows.filter(r => finite(r.score)).map(r => r.hour), region.timezone) : null;
  const agree = hours.filter(h => [h.wind, h.other_wind, h.sea, h.other_sea].every(finite));
  return {...base, available: true,
    wind_kt: range(hours.map(h => h.wind)), wind_from: compass(meanBearing(hours.map(h => h.wind_from))),
    gusts_kt: round(Math.max(...hours.map(h => h.gust).filter(finite), -Infinity)) ?? null,
    seas_ft: range(hours.map(h => Math.max(h.sea ?? -Infinity, h.other_sea ?? -Infinity)).map(v => v === -Infinity ? null : v), 1, 'up'),
    sea_period_s: round(median(hours.map(h => h.sea_period))),
    swell_ft: range(hours.map(h => h.swell)), swell_period_s: round(median(hours.map(h => h.swell_period))), swell_from: compass(meanBearing(hours.map(h => h.swell_from))),
    comfort: swell ? COMFORT_WORD.marginal : COMFORT_WORD[verdict], ...(swell ? {comfort_held: swell} : {}),
    models_agree: agree.length ? agree.every(h => Math.abs(h.wind! - h.other_wind!) <= MODEL_GAP.wind && Math.abs(h.sea! - h.other_sea!) <= MODEL_GAP.sea) : null,
  };
}
const clock = (ms: number, tz: string): string => { const h = localParts(ms, tz).hour; return h === 12 ? 'noon' : h === 0 ? 'midnight' : `${h % 12} ${h < 12 ? 'am' : 'pm'}`; };
/**
 * The earliest hour in the long-period swell rule (score.ts LONG_PERIOD_SWELL: the rougher model's seas at the height or more, with the GFS-Wave sea or swell period
 * at the period or more, both from the same hour), named as web/brief/verdict.ts longPeriodHour names it; null when none. The physical threshold is not scaled by any boat.
 */
function longPeriodHour(hours: readonly Hour[], tz: string): string | null {
  for (const hour of [...hours].sort((a, b) => a.time - b.time)) {
    const heights = [hour.sea, hour.other_sea].filter(finite), periods = [hour.sea_period, hour.swell_period].filter(finite).filter(p => p >= LONG_PERIOD_SWELL.period);
    const h = heights.length ? Math.max(...heights) : NaN;
    if (h >= LONG_PERIOD_SWELL.height && periods.length) return `long-period swell (${Number(h.toFixed(1))} ft at ${Math.round(Math.max(...periods))} s) at ${clock(hour.time * 1000, tz)}`;
  }
  return null;
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
