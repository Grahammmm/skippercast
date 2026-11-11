// SC2252-04: clock times for the trip plan's stops and the return to port. Pure arithmetic over tripLegs' own at-least run minutes
// (each leg already rounded up) plus a fixed time fishing at each stop. A planning sum, not a navigation or safe-return promise.
// Every instant is epoch milliseconds, resolved in the region's IANA zone (never the device zone); durations are elapsed, so a DST day is right.
import {getTimes} from 'suncalc';
import type {tripLegs} from './trip-legs.ts';

export type TripTimingInputs = {leavePortAt: string; fishMin: number};
export const DEFAULT_TIMING: TripTimingInputs = {leavePortAt: '07:00', fishMin: 60};
export const MAX_FISH_MIN = 600;
const TIME = /^([01]\d|2[0-3]):([0-5]\d)$/, MINUTE = 60_000, DAY = 86_400_000;

/** The two typed values, only if both are valid (HH:mm and a whole number 0..600); else null. */
export function parseTiming(leavePortAt: unknown, fishMin: unknown): TripTimingInputs | null {
  const fish = typeof fishMin === 'string' ? (/^\d{1,3}$/.test(fishMin.trim()) ? Number(fishMin.trim()) : NaN) : fishMin;
  if (typeof leavePortAt !== 'string' || !TIME.test(leavePortAt) || typeof fish !== 'number' || !Number.isInteger(fish) || fish < 0 || fish > MAX_FISH_MIN) return null;
  return {leavePortAt, fishMin: fish};
}
/** A stored value read back: each field that is not valid falls back to its default. */
export function timingInputs(value: unknown): TripTimingInputs {
  const v = (value && typeof value === 'object' ? value : {}) as Record<string, unknown>;
  const ok = parseTiming(v.leavePortAt, DEFAULT_TIMING.fishMin), fish = parseTiming(DEFAULT_TIMING.leavePortAt, v.fishMin);
  return {leavePortAt: ok ? ok.leavePortAt : DEFAULT_TIMING.leavePortAt, fishMin: fish ? fish.fishMin : DEFAULT_TIMING.fishMin};
}

export type TripStopTime = {id: string; arriveAt: number; leaveAt: number; arriveAfterSunset: boolean; leaveAfterSunset: boolean};
export type TripTimesInput = {
  date: string; zone: string; timing: TripTimingInputs; port: {lat: number; lon: number} | null;
  stops: readonly {id: string; fishing: boolean}[]; route: ReturnType<typeof tripLegs>;
};
export type TripTimeReason = 'no-port' | 'no-speed' | 'no-stops' | 'invalid-departure' | 'invalid-route';
export type TripTimes =
  | {state: 'ready'; departAt: number; sunsetAt: number | null; firstOccurrence: boolean; stops: TripStopTime[]; backAt: number; backAfterSunset: boolean}
  | {state: 'unavailable'; reasons: TripTimeReason[]};

const formatter = (zone: string, options: Intl.DateTimeFormatOptions, locale = 'en-US') => new Intl.DateTimeFormat(locale, {timeZone: zone, ...options});
/** Minutes the zone is ahead of UTC at this instant. */
function offsetMinutes(at: number, zone: string): number {
  const parts = formatter(zone, {year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23'}).formatToParts(at);
  const n = (type: string) => Number(parts.find(p => p.type === type)!.value);
  return (Date.UTC(n('year'), n('month') - 1, n('day'), n('hour'), n('minute'), n('second')) - Math.floor(at / 1000) * 1000) / MINUTE;
}
/** The zone's calendar date (YYYY-MM-DD) at this instant. */
export function dateKey(at: number, zone: string): string { return formatter(zone, {year: 'numeric', month: '2-digit', day: '2-digit'}, 'en-CA').format(at); }
function validDate(date: string): number | null {
  const ms = /^\d{4}-\d{2}-\d{2}$/.test(date) ? Date.parse(`${date}T00:00:00Z`) : NaN;
  return Number.isFinite(ms) && new Date(ms).toISOString().slice(0, 10) === date ? ms : null;
}
/** The instants a wall time on a date can be in the zone: none in a spring gap, two in a repeated fall hour (earlier first). */
export function wallInstants(date: string, hour: number, minute: number, zone: string): number[] {
  const day = validDate(date);
  if (day === null) return [];
  const wall = day + (hour * 60 + minute) * MINUTE, found = new Set<number>();
  for (const probe of [wall - DAY, wall + DAY]) {
    const candidate = wall - offsetMinutes(probe, zone) * MINUTE;
    if (candidate + offsetMinutes(candidate, zone) * MINUTE === wall) found.add(candidate);
  }
  return [...found].sort((a, b) => a - b);
}
/** Sunset at the port on this local date: suncalc, called as packages/coast/src/daily.ts astro does (local noon, the zone's offset, same-date check). */
export function sunsetAt(date: string, zone: string, lat: number, lon: number): number | null {
  // suncalc never returns for a nonfinite coordinate (its sunset search loops), so refuse one before calling it.
  if (!validPoint({lat, lon})) return null;
  try {
    const noon = wallInstants(date, 12, 0, zone)[0];
    if (noon === undefined) return null;
    const value = (getTimes as (d: Date, lat: number, lon: number, height: number, offset: number) => {sunset: Date})(new Date(noon), lat, lon, 0, offsetMinutes(noon, zone)).sunset;
    const at = value?.getTime();
    return Number.isFinite(at) && dateKey(at, zone) === date ? at : null;
  } catch { return null; }
}
const validPoint = (p: {lat: number; lon: number} | null): p is {lat: number; lon: number} => !!p && Number.isFinite(p.lat) && Math.abs(p.lat) <= 90 && Number.isFinite(p.lon) && Math.abs(p.lon) <= 180;

export function tripTimes(input: TripTimesInput): TripTimes {
  const {date, zone, timing, port, route} = input, reasons: TripTimeReason[] = [];
  if (!validPoint(port)) reasons.push('no-port');
  if (route.totalRunMin === null || !Number.isFinite(route.totalRunMin)) reasons.push('no-speed');
  if (!input.stops.length) reasons.push('no-stops');
  if (reasons.length) return {state: 'unavailable', reasons};
  const ids = new Set<string>(), stops = input.stops.filter(s => !ids.has(s.id) && !!ids.add(s.id));
  if (route.skipped.length || route.legs.length !== stops.length + 1 || route.legs.some(l => l.runMin === null || !Number.isFinite(l.runMin) || l.runMin < 0)) return {state: 'unavailable', reasons: ['invalid-route']};
  const parsed = parseTiming(timing.leavePortAt, timing.fishMin);
  let instants: number[] = [];
  try { if (parsed) instants = wallInstants(date, Number(parsed.leavePortAt.slice(0, 2)), Number(parsed.leavePortAt.slice(3)), zone); } catch { /* unknown zone */ }
  if (!parsed || !instants.length) return {state: 'unavailable', reasons: ['invalid-departure']};
  const departAt = instants[0]!, sunset = sunsetAt(date, zone, port!.lat, port!.lon), after = (at: number): boolean => sunset !== null && at > sunset;
  let clock = departAt;
  const out: TripStopTime[] = stops.map((stop, i) => {
    clock += route.legs[i]!.runMin! * MINUTE;
    const arriveAt = clock;
    clock += (stop.fishing ? parsed.fishMin : 0) * MINUTE;
    return {id: stop.id, arriveAt, leaveAt: clock, arriveAfterSunset: after(arriveAt), leaveAfterSunset: after(clock)};
  });
  const backAt = clock + route.legs[stops.length]!.runMin! * MINUTE;
  return {state: 'ready', departAt, sunsetAt: sunset, firstOccurrence: instants.length > 1, stops: out, backAt, backAfterSunset: after(backAt)};
}

/** A clock time in the plan's zone, e.g. `7:05 AM PDT`; a later local date adds `next day` (the next date) or the date itself. `dayWord` is the translated "next day". */
export function clockText(at: number, zone: string, planDate: string, language: string, dayWord: string): string {
  const time = formatter(zone, {hour: 'numeric', minute: '2-digit', timeZoneName: 'short'}, language === 'es' ? 'es-US' : 'en-US').format(at), day = dateKey(at, zone);
  if (day === planDate) return time;
  const plan = validDate(planDate), here = validDate(day);
  return plan !== null && here !== null && here - plan === DAY ? `${time} (${dayWord})` : `${time} (${day})`;
}
