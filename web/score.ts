// The one conditions model: the graded score and verdict shared by the
// Tomorrow card, the meteogram, the search plans, the trip planner and the
// text advisor (server/advisor/answers/comfort.ts), and the window rule the
// brief's lower-exposure windows use (packages/coast/src/assessment.ts,
// daily.ts). Pure and dependency-free: every number here is a disclosed
// planning heuristic tuned on the reference 23 ft deep-V (see
// dist/boat-handling.js), not a sea-keeping calculation and not a safety
// clearance. Change a threshold here and the golden tests in
// tests/test_score.mjs will show exactly which ratings move.
//
// Two questions, deliberately answered differently (docs/conditions-model.md):
// the score grades how comfortable and fishable an hour is on a 0-10 scale;
// the window rule asks whether an hour sits inside the person's own numerical
// limits (packages/coast/src/limits.ts), which they can set looser or
// stricter. Both live here so neither copies the other's numbers.
//
// Erasable TypeScript only: legacy dist/*.js modules and Node tests import it.

export type ControlMode = 'bottom' | 'water-column' | 'boat-comfort';
export type Verdict = 'go' | 'marginal' | 'no-go' | 'unknown';

/** Multipliers on the tuned thresholds for a boat (boat-handling.js boatFactors). */
export interface BoatFactors {
  sea: number;
  wind: number;
  chopPeriod: number;
}

/** One model's reading of an hour; nulls are unknown, never zero. */
export interface HourConditions {
  wind: number | null;
  gust: number | null;
  sea: {height: number | null; period?: number | null; from?: number | null};
  chop: {height: number | null; period: number | null; from?: number | null};
  swell: {height: number | null; period?: number | null; from: number | null};
  secondary: {height: number | null; period?: number | null; from: number | null};
}

export interface Scores {
  comfort: number;
  control: number | null;
  conditions: number;
  score_scope: 'boat-comfort' | 'comfort-and-control';
  bite: null;
  overall: null;
}

/** Every tuned number in one place. Units: knots, feet, seconds, points out of 10. */
export const THRESHOLDS = Object.freeze({
  /** A conditions score at or above this is "go". */
  go: 7,
  /** Below this is "no-go". */
  noGo: 4,
  /** Caps: any uncertainty, a limited (partial-field) estimate, an active hazard. */
  capUncertain: 7.9,
  capLimited: 6.9,
  capHazard: 1.9,
  /** Comfort: wind and gust above these knots (times the boat's wind factor) start to cost. */
  comfortWindStart: 4,
  comfortGustStart: 7,
  comfortWindSlope: 0.22,
  comfortGustSlope: 0.1,
  /** Comfort: combined seas and wind chop above these feet (times the sea factor). */
  comfortSeaStart: 1.5,
  comfortSeaSlope: 0.7,
  comfortChopStart: 0.4,
  comfortChopSlope: 0.9,
  /** Control (holding a drift or a spot): more wind-sensitive when fishing the bottom. */
  controlWindStart: 4,
  controlWindSlopeBottom: 0.32,
  controlWindSlopeColumn: 0.22,
  controlGustStart: 8,
  controlGustSlope: 0.08,
  controlSeaStart: 2,
  controlSeaSlope: 0.45,
  controlChopStart: 0.4,
  controlChopSlopeBottom: 1.1,
  controlChopSlopeColumn: 0.8,
  /** Flat penalties: a crossing secondary swell, short steep chop. */
  crossingSecondaryHeight: 1,
  crossingAngle: 60,
  crossingPenalty: 0.7,
  shortChopHeight: 0.5,
  shortChopPenalty: 0.8,
  /** Wind and wave burdens overlap: the larger in full, this share of the smaller. */
  overlap: 0.45,
});

export const clamp = (n: number): number => Math.round(Math.max(0, Math.min(10, n)) * 10) / 10;

/** Charge the larger burden in full, then a share of the smaller, to keep a combined-sea penalty. */
export const combinedBurden = (wind: number, wave: number): number =>
  Math.max(wind, wave) + THRESHOLDS.overlap * Math.min(wind, wave);

/** Smallest angle between two bearings in degrees. */
export function angleBetween(a: number | null | undefined, b: number | null | undefined): number | null {
  return Number.isFinite(a as number) && Number.isFinite(b as number)
    ? Math.abs((((a as number) - (b as number) + 540) % 360) - 180)
    : null;
}

/** Bottom fishing needs the boat to hold position; the water column and boat comfort do not. */
export function controlModeFor(species: string, configured?: string | null): ControlMode {
  if (configured === 'bottom' || configured === 'water-column' || configured === 'boat-comfort') return configured;
  return ['reef', 'lingcod', 'rockfish', 'halibut', 'dungeness'].includes(species) ? 'bottom' : 'water-column';
}

const finite = (v: number | null | undefined): number => (Number.isFinite(v as number) ? (v as number) : 0);

/** What each input costs an hour's comfort score, in points out of 10, before the wind and wave burdens overlap. */
export interface ComfortCosts {wind: number; seas: number; chop: number; crossing: number; short: number}

/**
 * The comfort score's charges for one full-detail hour, each input on its own:
 * hourScores combines them; chargedCosts says what each actually took off.
 */
export function comfortCosts(
  c: HourConditions,
  other: {wind: number | null; sea: {height: number | null}},
  checkedGust: number,
  boat: BoatFactors,
): {wind: number; gust: number; sea: number; chop: number; costs: ComfortCosts} {
  const T = THRESHOLDS, S = boat.sea, W = boat.wind;
  const wind = Math.max(finite(c.wind), finite(other.wind));
  const gust = checkedGust;
  const sea = Math.max(finite(c.sea.height), finite(other.sea.height));
  const chop = finite(c.chop.height);
  const crossing =
    finite(c.secondary.height) >= T.crossingSecondaryHeight * S && (angleBetween(c.swell.from, c.secondary.from) ?? -1) >= T.crossingAngle
      ? T.crossingPenalty : 0;
  const short = chop >= T.shortChopHeight * S && Number.isFinite(c.chop.period) && (c.chop.period as number) <= boat.chopPeriod ? T.shortChopPenalty : 0;
  return {wind, gust, sea, chop, costs: {
    wind: Math.max(0, wind - T.comfortWindStart * W) * T.comfortWindSlope / W + Math.max(0, gust - T.comfortGustStart * W) * T.comfortGustSlope / W,
    seas: Math.max(0, sea - T.comfortSeaStart * S) * T.comfortSeaSlope / S,
    chop: Math.max(0, chop - T.comfortChopStart * S) * T.comfortChopSlope / S,
    crossing, short,
  }};
}

/**
 * What each input actually took off the comfort score, as hourScores and
 * limitedScores combine the costs: the larger of the wind and wave burdens in
 * full and THRESHOLDS.overlap of the smaller, where the wave burden is the
 * larger of seas and chop (ties to seas), so the other costs nothing; the
 * crossing and short-chop penalties are flat. They sum to 10 minus the
 * unclamped score. The brief names the largest as the day's limit.
 */
export function chargedCosts(costs: ComfortCosts): ComfortCosts {
  const wave = Math.max(costs.seas, costs.chop), windFull = costs.wind >= wave;
  const waveTaken = windFull ? THRESHOLDS.overlap * wave : wave, seasPicked = costs.seas >= costs.chop;
  return {
    wind: windFull ? costs.wind : THRESHOLDS.overlap * costs.wind,
    seas: seasPicked ? waveTaken : 0, chop: seasPicked ? 0 : waveTaken,
    crossing: costs.crossing, short: costs.short,
  };
}

/**
 * Full-detail scores for one hour from two models: the rougher wind and seas of
 * the two, the checked gust, and the first model's chop and swell partitions.
 */
export function hourScores(
  c: HourConditions,
  other: {wind: number | null; gust?: number | null; sea: {height: number | null}},
  mode: ControlMode,
  checkedGust: number,
  boat: BoatFactors,
): Scores {
  const T = THRESHOLDS, S = boat.sea, W = boat.wind;
  const {wind, gust, sea, chop, costs} = comfortCosts(c, other, checkedGust, boat);
  const {crossing, short} = costs;
  const comfort = clamp(10 - combinedBurden(costs.wind, Math.max(costs.seas, costs.chop)) - crossing - short);
  const bottom = mode === 'bottom';
  const controlWavePenalty = Math.max(
    Math.max(0, sea - T.controlSeaStart * S) * T.controlSeaSlope / S,
    Math.max(0, chop - T.controlChopStart * S) * (bottom ? T.controlChopSlopeBottom : T.controlChopSlopeColumn) / S,
  );
  const controlWind = Math.max(0, wind - T.controlWindStart * W) * (bottom ? T.controlWindSlopeBottom : T.controlWindSlopeColumn) / W
    + Math.max(0, gust - T.controlGustStart * W) * T.controlGustSlope / W;
  const control = clamp(10 - combinedBurden(controlWind, controlWavePenalty) - crossing - short);
  return finish(comfort, control, mode);
}

/**
 * Limited scores when chop, swell or a consistent gust is missing: only the
 * observed wind and combined seas are charged, nothing is assumed to be zero,
 * and the result can never clear the limited cap.
 */
export function limitedScores(wind: number, sea: number, gust: number | null, mode: ControlMode, boat: BoatFactors): Scores {
  const T = THRESHOLDS, S = boat.sea, W = boat.wind, bottom = mode === 'bottom';
  const comfortWind = Math.max(0, wind - T.comfortWindStart * W) * T.comfortWindSlope / W
    + (gust === null ? 0 : Math.max(0, gust - T.comfortGustStart * W) * T.comfortGustSlope / W);
  const controlWind = Math.max(0, wind - T.controlWindStart * W) * (bottom ? T.controlWindSlopeBottom : T.controlWindSlopeColumn) / W
    + (gust === null ? 0 : Math.max(0, gust - T.controlGustStart * W) * T.controlGustSlope / W);
  const comfort = clamp(10 - combinedBurden(comfortWind, Math.max(0, sea - T.comfortSeaStart * S) * T.comfortSeaSlope / S));
  const control = clamp(10 - combinedBurden(controlWind, Math.max(0, sea - T.controlSeaStart * S) * T.controlSeaSlope / S));
  const scores = finish(comfort, control, mode);
  return {...scores, conditions: Math.min(T.capLimited, scores.conditions)};
}

function finish(comfort: number, control: number, mode: ControlMode): Scores {
  const comfortOnly = mode === 'boat-comfort';
  return {
    comfort,
    control: comfortOnly ? null : control,
    conditions: comfortOnly ? comfort : Math.min(comfort, control),
    score_scope: comfortOnly ? 'boat-comfort' : 'comfort-and-control',
    bite: null,
    overall: null,
  };
}

/** go / marginal / no-go from a rated hour or window; a hazard is always no-go. */
export function verdictFor(rating: {conditions?: number | null; hazard?: boolean} | null | undefined): Verdict {
  if (!rating || !Number.isFinite(rating.conditions as number)) return 'unknown';
  if (rating.hazard || (rating.conditions as number) < THRESHOLDS.noGo) return 'no-go';
  return (rating.conditions as number) >= THRESHOLDS.go ? 'go' : 'marginal';
}

/** Worse verdicts rank higher. */
export const VERDICT_RANK: Record<Verdict, number> = Object.freeze({go: 0, marginal: 1, unknown: 2, 'no-go': 3});
/** The worse of two verdicts (a window takes the worse of its hours). */
export const worseVerdict = (a: Verdict, b: Verdict): Verdict => (VERDICT_RANK[a] >= VERDICT_RANK[b] ? a : b);

/** A window rule's wind, gust and seas limits. Units: knots and feet. */
export interface WindowLimits {wind: number; gust: number; wave: number}

/** The brief's default window limits: boat, and the other profiles. The user's own limits replace them. */
export const WINDOW_LIMITS: Readonly<Record<'boat' | 'other', Readonly<WindowLimits>>> = Object.freeze({
  boat: Object.freeze({wind: 10, gust: 15, wave: 4}),
  other: Object.freeze({wind: 8, gust: 12, wave: 3}),
});

/** Seas at least this high (ft) at least this period (s) keep an hour out of a window whatever the limits. */
export const LONG_PERIOD_SWELL = Object.freeze({height: 2.5, period: 15});

/** One hour's window inputs; nulls are unknown, and an unknown never fits a window. */
export interface WindowHour {wind: number | null; gust: number | null; wave: number | null; period: number | null}

/**
 * Whether an hour's wind, gusts and seas sit inside the limits. `waveOk`, when a
 * profile judges the water from its own nearshore model (spear surge), replaces
 * the seas test and the long-period swell rule. Daylight, alerts and per-hour
 * hazards are the caller's.
 */
export function withinWindowLimits(h: WindowHour, limits: WindowLimits, waveOk?: boolean): boolean {
  if (!Number.isFinite(h.wind as number) || !Number.isFinite(h.gust as number) || !Number.isFinite(h.wave as number) || !Number.isFinite(h.period as number)) return false;
  const wave = (h.wave as number), period = (h.period as number);
  const seasOk = waveOk ?? (wave <= limits.wave && !(wave >= LONG_PERIOD_SWELL.height && period >= LONG_PERIOD_SWELL.period));
  return (h.wind as number) <= limits.wind && (h.gust as number) <= limits.gust && seasOk;
}

/** The reference boat every threshold was tuned on: dist/boat-handling.js factors with no saved boat. */
export const REFERENCE_BOAT: Readonly<BoatFactors> = Object.freeze({sea: 1, wind: 1, chopPeriod: 6});

/**
 * One hour of the dual-model forecast feed, flattened: NOAA GFS wind and the
 * GFS-Wave partitions, with ECMWF IFS wind and WAM seas as the second opinion.
 * Units: knots, feet, seconds, degrees true (from). Nulls are unknown.
 */
export interface FeedHour {
  wind: number | null; gust: number | null; wind_from: number | null;
  sea: number | null; sea_period: number | null; chop: number | null; chop_period: number | null;
  swell: number | null; swell_period: number | null; swell_from: number | null;
  secondary: number | null; secondary_from: number | null;
  other_wind: number | null; other_sea: number | null; other_gust: number | null;
}

/** A feed hour's comfort rating, with what it charged so a caller can name the limit. */
export interface ComfortRating {
  /** The score as rated: a limited estimate is capped at THRESHOLDS.capLimited. */
  score: number;
  /** The same score before the limited cap. */
  uncapped: number;
  /** Built from the wind and combined seas only: a partition, the second model or a consistent gust is missing. */
  limited: boolean;
  /** The rougher of the two models' wind and seas, the checked gust (null when neither is consistent), and the first model's chop. */
  wind: number; gust: number | null; sea: number; chop: number | null;
  costs: ComfortCosts;
}

const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);

/**
 * The comfort score for one feed hour, as every surface rates it: the full
 * rubric when both models and every partition are there, otherwise the limited
 * one on the wind and seas actually forecast, capped. Null without a wind and a
 * seas forecast. Gusts below their sustained wind are dropped, never raised.
 */
export function rateComfort(h: FeedHour, boat: BoatFactors = REFERENCE_BOAT): ComfortRating | null {
  const winds = [h.wind, h.other_wind].filter(isNum), seas = [h.sea, h.other_sea].filter(isNum);
  if (!winds.length || !seas.length) return null;
  const gusts = ([[h.wind, h.gust], [h.other_wind, h.other_gust]] as const).filter(([w, g]) => isNum(w) && isNum(g) && g >= w).map(([, g]) => g as number);
  const complete = [h.wind, h.sea, h.sea_period, h.chop, h.chop_period, h.swell, h.swell_from, h.other_wind, h.other_sea].every(isNum) && gusts.length === 2;
  if (complete) {
    const c: HourConditions = {wind: h.wind, gust: h.gust, sea: {height: h.sea}, chop: {height: h.chop, period: h.chop_period},
      swell: {height: h.swell, from: h.swell_from}, secondary: {height: h.secondary, from: h.secondary_from}};
    const other = {wind: h.other_wind, sea: {height: h.other_sea}}, gust = Math.max(...gusts);
    const score = hourScores(c, other, 'boat-comfort', gust, boat).comfort;
    const parts = comfortCosts(c, other, gust, boat);
    return {score, uncapped: score, limited: false, wind: parts.wind, gust, sea: parts.sea, chop: parts.chop, costs: parts.costs};
  }
  const wind = Math.max(...winds), sea = Math.max(...seas), gust = gusts.length ? Math.max(...gusts) : null;
  const uncapped = limitedScores(wind, sea, gust, 'boat-comfort', boat).comfort;
  const T = THRESHOLDS, S = boat.sea, W = boat.wind;
  const costs: ComfortCosts = {
    wind: Math.max(0, wind - T.comfortWindStart * W) * T.comfortWindSlope / W + (gust === null ? 0 : Math.max(0, gust - T.comfortGustStart * W) * T.comfortGustSlope / W),
    seas: Math.max(0, sea - T.comfortSeaStart * S) * T.comfortSeaSlope / S, chop: 0, crossing: 0, short: 0,
  };
  return {score: Math.min(T.capLimited, uncapped), uncapped, limited: true, wind, gust, sea, chop: null, costs};
}
