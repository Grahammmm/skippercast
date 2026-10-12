// Return window and fishing time (roadmap P2): for a Boat brief, how long the
// run takes from the harbor to the chosen place at the user's own cruise
// speed, when to turn back to be in by the end of the brief's lower-exposure
// window, and how much fishing time that leaves.
//
// Every input is disclosed and nothing is filled in:
// - the window is the brief's own (packages/coast buildDaily: the user's
//   limits or the defaults, alerts, daylight, the hazard rules and the bar at
//   departure and return); no window means no return time, and the reason
//   names the input that is missing;
// - the distance is straight-line from the region's harbor (web/ranking.ts),
//   so the real run is at least this long and the fishing time at most this;
// - the speed is the one the user typed on this device (web/limits.ts
//   cruiseSpeed); there is no default, and without it the brief says so.
// Sea state, the bar crossing itself and fuel are left to the skipper; this
// is a planning sum, not a passage plan or a promise of a safe return.
//
// Erasable syntax only: Node tests import this file by type stripping.
import type {Window} from '../../packages/coast/src/types.ts';
import type {Brief} from './types.ts';

const MINUTE = 60_000;
/** Times round to this many minutes: the run up, the turn-back time down, so fishing time is never overstated. */
export const ROUND_MIN = 5;

/** The chosen place the run goes to. */
export interface RunPlace {readonly name: string; readonly nm: number}

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
  for (const window of brief.windows) {
    const start = Date.parse(window.start), end = Date.parse(window.end);
    if (!Number.isFinite(start) || !Number.isFinite(end)) continue;
    const depart = Math.max(start, ceilTo(t)), turnBack = floorTo(end - run);
    if (turnBack <= t) continue;
    const arrive = depart + run, fishMin = Math.floor((turnBack - arrive) / MINUTE);
    if (fishMin <= 0) return {kind: 'no-time', window, place, speedKn, runMin};
    return {kind: 'ok', window, place, speedKn, runMin, depart: iso(depart), arrive: iso(arrive), turnBack: iso(turnBack), back: window.end, fishMin};
  }
  return {kind: 'over', window: brief.windows.at(-1)!};
}

/** "45 min", "2 h", "1 h 50 min". */
export function durationText(min: number): string {
  const h = Math.floor(min / 60), m = min % 60;
  return h ? `${h} h${m ? ` ${m} min` : ''}` : `${m} min`;
}
