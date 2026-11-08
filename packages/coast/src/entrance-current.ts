// Harbor-entrance current timing (SC-TIDAL-1): is the water at the entrance flooding or ebbing, and when does it turn
// (slack)? A rough estimate from two sources the app already has, never a measurement in the channel:
//
// - NOAA tide predictions (the daily feed's highs and lows at the region's tide station). The tide rises (flood) between
//   a low and the next high and falls (ebb) between a high and the next low; the current turns near each high and low.
//   A harbor's own current can lag the station's tide by an unknown time, so the turn is shown as a window of
//   CURRENT.slackMin minutes either side of the predicted high or low, never as a minute.
// - The NOAA WCOFS surface-current forecast at the region's forecast point (about 4 km, offshore of the entrance, so it
//   cannot see the channel). It is used only as a second opinion: when it runs clearly out of the entrance while the tide
//   says flood or slack, the entrance is read as a possible ebb, so the bar caution is never calmer than the worse source
//   (bar-conditions.ts BAR_RANK). When it cannot be read at an entrance where it could have been compared, an ebb cannot be
//   ruled out either, so an aging or missing forecast never makes the caution calmer. A bearing-less entrance cannot be
//   compared and says so.
//
// The caution reuses bar-conditions.ts bands unchanged (swell height and period, tide stage, wind against the ebb), read
// again at the tide phase of the instant itself. Stale or missing tide or swell data read Unknown (which ranks above
// Caution), never No bar flag, and a Hazardous reading stays Hazardous. Nothing here says a bar is safe.
//
// Erasable syntax only: Node tests import this file by type stripping.
import {BAR_RANK, barBand, barTide, tideBracket, windAgainstEbb} from './bar-conditions.ts';
import type {BarBand, BarHour, BarTide, Entrance} from './bar-conditions.ts';
import type {TideEvent} from './types.ts';

const MIN = 60_000;
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);

/** This module's own screening choices (not from NOAA or the Coast Guard); every one is a rule of thumb. */
export const CURRENT = {
  /** Minutes either side of a predicted high or low water that read as slack: the station's tide turns there, the harbor's current may lag it. */
  slackMin: 30,
  /** WCOFS offshore flow counts only at or above `minKn`; within `withinDeg` of the seaward bearing it runs out, within `withinDeg` of the opposite it runs in. */
  offshore: {minKn: 0.5, withinDeg: 45},
} as const;

export type Flow = 'ebb' | 'flood';
export type Phase = Flow | 'slack';
/** The tide-derived timing at one instant. `turnsTo` is the flow that follows the nearest turn; `slackFrom` and `slackUntil` bound that turn's slack window. */
export type EntranceTiming =
  | {state: 'ok'; at: number; phase: Phase; turnsTo: Flow; turnAt: number; turnType: 'H' | 'L'; slackFrom: number; slackUntil: number}
  | {state: 'unknown'; at: number; reason: 'no-tide' | 'stale-tide'};

/** The flow before a turn of this type: a high is followed by ebb, a low by flood. */
const after = (type: 'H' | 'L'): Flow => type === 'H' ? 'ebb' : 'flood';

/**
 * Flood, ebb or slack at `at` (epoch ms) from the predicted highs and lows, and the next turn. `fresh` false (the tide
 * predictions are old) or no bracketing high and low gives `unknown`, with the reason, and no time.
 */
export function entranceTiming(at: number, events: readonly TideEvent[], fresh = true): EntranceTiming {
  if (!fresh) return {state: 'unknown', at, reason: 'stale-tide'};
  const bracket = tideBracket(at, events);
  if (!bracket) return {state: 'unknown', at, reason: 'no-tide'};
  const half = CURRENT.slackMin * MIN, {previous, next} = bracket;
  // The nearest turn: the one just passed while still inside its slack window, else the next one.
  const event = at - previous.at <= half ? previous : next;
  const slack = Math.abs(at - event.at) <= half;
  const phase: Phase = slack ? 'slack' : previous.type === 'H' ? 'ebb' : 'flood';
  return {state: 'ok', at, phase, turnsTo: after(event.type), turnAt: event.at, turnType: event.type, slackFrom: event.at - half, slackUntil: event.at + half};
}

export type TurnEvent = {at: number; type: 'H' | 'L'; turnsTo: Flow; slackFrom: number; slackUntil: number};

/** The turns (slack windows centred on each predicted high or low) whose window ends at or after `from` and starts before `to`, oldest first. Unreadable events are skipped. */
export function entranceTurns(events: readonly TideEvent[], from: number, to: number): TurnEvent[] {
  const half = CURRENT.slackMin * MIN, seen = new Map<number, 'H' | 'L' | null>();
  for (const event of events) {
    if (!event || typeof event !== 'object' || (event.type !== 'H' && event.type !== 'L') || typeof event.at !== 'string') continue;
    // Same rule as bar-conditions.ts: an offset-less time is not read as device-local time.
    if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d{1,3})?)?(Z|[+-]\d{2}:\d{2})$/.test(event.at)) continue;
    const time = Date.parse(event.at);
    if (!Number.isFinite(time)) continue;
    if (!seen.has(time)) seen.set(time, event.type);
    else if (seen.get(time) !== event.type) seen.set(time, null);
  }
  return [...seen].filter((e): e is [number, 'H' | 'L'] => e[1] !== null).sort((a, b) => a[0] - b[0])
    .filter(([time]) => time + half >= from && time - half < to)
    .map(([time, type]) => ({at: time, type, turnsTo: after(type), slackFrom: time - half, slackUntil: time + half}));
}

/** One WCOFS sample at the forecast point, as the app reads it: speed in knots, bearing the water flows toward (degrees true). */
export type OffshoreSample = {speedKn: number; towardDeg: number; validAt: number};
/** What the offshore sample says about the entrance. `missing` carries why the forecast could not be read (old, absent or outside its hours). */
export type OffshoreFlow =
  | {kind: 'out' | 'in' | 'across' | 'weak' | 'unjudged'; speedKn: number; towardDeg: number; validAt: number}
  | {kind: 'missing'; reason: string};

const angle = (a: number, b: number) => Math.abs((((a - b) % 360) + 540) % 360 - 180);

/** The offshore flow against the entrance: out of it, into it, along the coast, too weak to count, or not comparable (no seaward bearing). */
export function offshoreFlow(sample: OffshoreSample | null | undefined, entrance: Entrance, missing = 'no forecast sample'): OffshoreFlow {
  if (!sample || !finite(sample.speedKn) || !finite(sample.towardDeg) || !finite(sample.validAt) || sample.speedKn < 0 || sample.towardDeg < 0 || sample.towardDeg > 360) return {kind: 'missing', reason: missing};
  const {speedKn, towardDeg, validAt} = sample, {minKn, withinDeg} = CURRENT.offshore;
  const base = {speedKn, towardDeg, validAt};
  if (speedKn < minKn) return {kind: 'weak', ...base};
  if (entrance.seawardDeg === null) return {kind: 'unjudged', ...base};
  const off = angle(towardDeg, entrance.seawardDeg);
  return {kind: off <= withinDeg ? 'out' : off >= 180 - withinDeg ? 'in' : 'across', ...base};
}

export type CautionWhy = 'tide-stale' | 'tide-missing' | 'swell-stale' | 'swell-missing' | 'wcofs-ebb' | 'wcofs-missing' | 'slack-ebb';
export type EntranceReading = {
  timing: EntranceTiming;
  offshore: OffshoreFlow;
  /** The worse of the sources: the bar band at this instant, held at Unknown when a driver is old or missing, raised when an ebb cannot be ruled out. */
  band: BarBand;
  /** Why the band is not simply the bar hour's own, in the order they apply; empty when it is. */
  why: CautionWhy[];
  /** The band was also read as if ebbing, because WCOFS runs out of the entrance while the tide says flood, slack or nothing. */
  ebbAssumed: boolean;
  /** The flow the caution is about: ebb when the tide says so or WCOFS runs out; else the tide's flood; null at slack or without a tide. */
  flow: Flow | null;
  swellFt: number | null;
  periodS: number | null;
};

export type ReadingInput = {
  at: number;
  entrance: Entrance;
  tideEvents: readonly TideEvent[];
  /** The tide predictions are current (the brief's tide tile is fresh). */
  tideFresh: boolean;
  /** The swell forecast is current (the brief's swell tile is fresh). */
  swellFresh: boolean;
  /** The bar reading for the hour that holds `at`, from bar-conditions.ts barHours; null when the hour has none. */
  barHour: BarHour | null;
  offshore: OffshoreFlow;
};

/** The worse (higher-ranked) of two bands. */
export const worseBand = (a: BarBand, b: BarBand): BarBand => BAR_RANK[b] > BAR_RANK[a] ? b : a;

/** An ebb of unknown strength: the stage is ebb, mid-ebb is not claimed. */
const ASSUMED_EBB: BarTide = {stage: 'ebb', midEbb: false, fraction: null};

/**
 * The entrance reading at one instant. Never calmer than its worst source:
 * - the bar hour's own band is kept, and the hour's swell and wind are read again at the tide phase of `at` itself (the
 *   bar hour is the whole hour holding `at`, so a turn inside the hour would otherwise be missed);
 * - an old or missing tide or swell holds the band at Unknown (a Hazardous reading stays Hazardous);
 * - the hour is also read as an ebb, with its wind, when WCOFS runs out of the entrance while the tide says flood, slack or
 *   nothing, when WCOFS cannot be read at an entrance where it could have been compared (a lost cross-check never reads as
 *   no hazard, so an aging run cannot make the caution calmer), and near slack (the harbor's current can turn later than the
 *   station's tide).
 */
export function entranceReading(input: ReadingInput): EntranceReading {
  const {at, entrance, tideFresh, swellFresh, barHour, offshore} = input;
  const tideEvents = Array.isArray(input.tideEvents) ? input.tideEvents : [];
  const timing = entranceTiming(at, tideEvents, tideFresh);
  const why: CautionWhy[] = [];
  let band: BarBand = barHour ? barHour.band : 'Unknown';
  if (timing.state === 'unknown') why.push(timing.reason === 'stale-tide' ? 'tide-stale' : 'tide-missing');
  if (!swellFresh) why.push('swell-stale'); else if (!barHour || barHour.swell.heightFt === null) why.push('swell-missing');
  if (why.length) band = worseBand(band, 'Unknown');
  const tideFlow: Flow | null = timing.state === 'ok' && timing.phase !== 'slack' ? timing.phase : null;
  const tideEbb = timing.state === 'ok' && timing.phase === 'ebb';
  const ebbAssumed = offshore.kind === 'out' && !tideEbb;
  if (barHour && barHour.swell.heightFt !== null) {
    // The same swell and wind at the tide phase of this instant (even when the tide data is old: a worse band is only kept).
    const now = barTide(at, tideEvents);
    band = worseBand(band, barBand(now, barHour.swell, windAgainstEbb(barHour.wind, now, entrance.seawardDeg)).band);
    if (!tideEbb) {
      const asEbb = barBand(ASSUMED_EBB, barHour.swell, windAgainstEbb(barHour.wind, ASSUMED_EBB, entrance.seawardDeg)).band;
      const raises = BAR_RANK[asEbb] > BAR_RANK[band];
      if (ebbAssumed) why.push('wcofs-ebb');
      else if (offshore.kind === 'missing' && entrance.seawardDeg !== null && raises) why.push('wcofs-missing');
      else if (timing.state === 'ok' && timing.phase === 'slack' && raises) why.push('slack-ebb');
      if (ebbAssumed || why.includes('wcofs-missing') || why.includes('slack-ebb')) band = worseBand(band, asEbb);
    }
  }
  return {timing, offshore, band, why, ebbAssumed, flow: tideEbb || ebbAssumed ? 'ebb' : tideFlow,
    swellFt: barHour?.swell.heightFt ?? null, periodS: barHour?.swell.periodS ?? null};
}

