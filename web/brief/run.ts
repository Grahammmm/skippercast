// Return window and fishing time (roadmap P2): for a Boat brief, how long the
// run takes from the harbor to the chosen place at the user's own cruise
// speed, when to turn back to be in by the end of the brief's lower-exposure
// window, and how much fishing time that leaves.
//
// Every input is disclosed and nothing is filled in:
// - the window is the brief's own (packages/coast buildDaily: the user's
//   limits or the defaults, alerts, daylight, the hazard rules and the bar at
//   the window's first and last hour); no window means no return time, and
//   the reason names the input that is missing; a window whose bar reads
//   caution or unknown keeps that note beside the run time;
// - the distance is the water route from the harbor (web/route.ts) when one is
//   computed, else the straight line from it (web/ranking.ts), labelled as such;
//   the real run is at least the straight line, so the fishing time is at most this;
// - the speed is the one the user typed on this device (web/limits.ts
//   cruiseSpeed); there is no default, and without it the brief says so.
// Sea state, the bar crossing itself and fuel are left to the skipper; this
// is a planning sum, not a passage plan or a promise of a safe return.
//
// Erasable syntax only: Node tests import this file by type stripping.
import type {Window} from '../../packages/coast/src/types.ts';
import {PLANNING_MARGIN_M, screenPlace, type PlaceVerdict} from '../../dist/geo-screen.js';
import type {RoutedPick} from '../ranking.ts';
import type {RouteFailure, RoutePoint} from '../route.ts';
import type {Brief} from './types.ts';

const MINUTE = 60_000;
/** Times round to this many minutes: the run up, the turn-back time down, so fishing time is never overstated. */
export const ROUND_MIN = 5;

/** The chosen place the run goes to: `nm` is the water route's length ('water'), or the straight line with `why` no route was computed ('straight'). */
export interface RunPlace {readonly name: string; readonly nm: number; readonly basis: 'water' | 'straight'; readonly why?: RouteFailure}

export type RunState =
  | {readonly kind: 'no-speed'}
  | {readonly kind: 'no-place'}
  | {readonly kind: 'no-window'; readonly reason: string}
  | {readonly kind: 'over'; readonly window: Window}
  | {readonly kind: 'no-time'; readonly window: Window; readonly place: RunPlace; readonly speedKn: number; readonly runMin: number}
  | {readonly kind: 'ok'; readonly window: Window; readonly place: RunPlace; readonly speedKn: number; readonly runMin: number;
    /** Leave the harbor: the window's start, or now when the window is already open. */
    readonly depart: string; readonly arrive: string; readonly turnBack: string;
    /** In by: the window's end. */
    readonly back: string; readonly fishMin: number};

const up = (min: number) => Math.ceil(min / ROUND_MIN) * ROUND_MIN;
const floorTo = (ms: number) => Math.floor(ms / (ROUND_MIN * MINUTE)) * ROUND_MIN * MINUTE;
const ceilTo = (ms: number) => Math.ceil(ms / (ROUND_MIN * MINUTE)) * ROUND_MIN * MINUTE;
const iso = (ms: number) => new Date(ms).toISOString();

/** Minutes for a one-way run of `nm` at `speedKn`, rounded up to ROUND_MIN; null when either is unusable. */
export function runMinutes(nm: number, speedKn: number): number | null {
  if (!Number.isFinite(nm) || nm < 0 || !Number.isFinite(speedKn) || speedKn <= 0) return null;
  return Math.max(ROUND_MIN, up(nm / speedKn * 60));
}

/** Why a Boat brief has no window to plan a return in, naming the input that is missing. */
export function noWindowReason(brief: Pick<Brief, 'alerts' | 'missing' | 'tiles' | 'limits'>): string {
  const wind = brief.tiles.find(t => t.id === 'wind');
  if (brief.alerts.length) return 'No return time while a marine alert is in effect.';
  if (wind?.state === 'unavailable') return 'No return time without a forecast for this day.';
  if (wind?.state === 'stale') return 'No return time from a stale forecast.';
  if (brief.missing.includes('Current marine alert check unavailable')) return 'No return time while the marine alert check is unavailable.';
  if (brief.missing.some(m => m.endsWith('missing for some forecast hours'))) return 'No return time: some forecast hours are incomplete.';
  return brief.limits?.custom ? 'No lower-exposure window within your limits, so no return time.' : 'No lower-exposure window for this day, so no return time.';
}

/**
 * The run for a Boat brief: the first lower-exposure window still open at `now` whose turn-back time
 * has not passed, the one-way run there and back, and the fishing time between.
 */
export function planRun(brief: Pick<Brief, 'windows' | 'alerts' | 'missing' | 'tiles' | 'limits'>, place: RunPlace | null, speedKn: number | null, now: Date): RunState {
  if (!brief.windows.length) return {kind: 'no-window', reason: noWindowReason(brief)};
  if (speedKn === null || !(speedKn > 0)) return {kind: 'no-speed'};
  if (!place || !Number.isFinite(place.nm)) return {kind: 'no-place'};
  const runMin = runMinutes(place.nm, speedKn)!;
  const t = now.getTime(), run = runMin * MINUTE;
  // A short window the run fills does not hide a later one with fishing time.
  let full: RunState | null = null;
  for (const window of brief.windows) {
    const start = Date.parse(window.start), end = Date.parse(window.end);
    if (!Number.isFinite(start) || !Number.isFinite(end)) continue;
    const depart = Math.max(start, ceilTo(t)), turnBack = floorTo(end - run);
    if (turnBack <= t) continue;
    const arrive = depart + run, fishMin = Math.floor((turnBack - arrive) / MINUTE);
    if (fishMin <= 0) { full ??= {kind: 'no-time', window, place, speedKn, runMin}; continue; }
    return {kind: 'ok', window, place, speedKn, runMin, depart: iso(depart), arrive: iso(arrive), turnBack: iso(turnBack), back: window.end, fishMin};
  }
  return full ?? {kind: 'over', window: brief.windows.at(-1)!};
}

/** The window's bar note (daily.ts: bar caution or unknown at its first or last hour), shown beside a run time. */
export const barNote = (window: Window): string | null => window.reasons.find(reason => / bar caution or unknown /.test(reason)) ?? null;

/** "45 min", "2 h", "1 h 50 min". */
export function durationText(min: number): string {
  const h = Math.floor(min / 60), m = min % 60;
  return h ? `${h} h${m ? ` ${m} min` : ''}` : `${m} min`;
}

const usable = (p: unknown): p is RoutePoint => {
  const q = p as Partial<RoutePoint> | null | undefined;
  return !!q && typeof q.latitude === 'number' && Number.isFinite(q.latitude) && Math.abs(q.latitude) <= 90
    && typeof q.longitude === 'number' && Number.isFinite(q.longitude) && Math.abs(q.longitude) <= 180;
};

/**
 * SC0452-07: the shared protected-area verdict for the line the run is timed along: the harbor, the water route's bends
 * (`routePoints`, snapped ends included) and the place for a 'water' pick, the straight line between them for a labelled
 * fallback. One whole-line screenPlace, as trip legs do (web/trip-legs.ts). Anything it cannot say (no pick, origin or place,
 * a coordinate that is not a usable position, a water pick without its route points, a screen that is missing, not current,
 * not covering the line or throwing) is `screened: false`: never a clear verdict, and a bad point never shortens the line.
 * Reads the pick's own handoff; never searches a route or fetches.
 */
export function runRouteScreen(origin: RoutePoint | null | undefined, pick: RoutedPick | null, screen: unknown): PlaceVerdict {
  const none: PlaceVerdict = {inside: false, name: null, distanceM: null, screened: false};
  if (!pick || !usable(origin) || !usable(pick.at)) return none;
  const bends: unknown = pick.basis === 'water' ? pick.routePoints : [];
  if (!Array.isArray(bends) || !bends.every(usable)) return none;
  try {
    const line = [origin, ...bends, pick.at].map(p => [p.longitude, p.latitude]);
    const verdict = screenPlace(screen, {geometry: {type: 'LineString', coordinates: line}});
    return verdict && typeof verdict.screened === 'boolean' ? verdict : none;
  } catch { return none; }
}

/** SC0452-07: the run line's words for a route verdict: what was found, or that it was not checked; nothing at all for a clear line (no reassurance, no claim about transit rules). */
export function runRouteNote(verdict: PlaceVerdict): string | null {
  if (!verdict.screened) return 'Route: protected areas not checked.';
  const name = verdict.name?.trim() ? verdict.name : 'a protected area';
  if (verdict.inside) return `Route crosses or touches ${name}.`;
  return verdict.distanceM !== null && verdict.distanceM <= PLANNING_MARGIN_M ? `Route passes within ${PLANNING_MARGIN_M} m of ${name}.` : null;
}
