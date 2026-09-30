// The one conditions score and verdict, shared by the Tomorrow card, the
// meteogram, the search plans and the trip planner. Pure and dependency-free:
// every number here is a disclosed planning heuristic tuned on the reference
// 23 ft deep-V (see dist/boat-handling.js), not a sea-keeping calculation and
// not a safety clearance. Change a threshold here and the golden tests in
// tests/test_score.mjs will show exactly which ratings move.
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
  const wind = Math.max(finite(c.wind), finite(other.wind));
  const gust = checkedGust;
  const sea = Math.max(finite(c.sea.height), finite(other.sea.height));
  const chop = finite(c.chop.height);
  const crossing =
    finite(c.secondary.height) >= T.crossingSecondaryHeight * S && (angleBetween(c.swell.from, c.secondary.from) ?? -1) >= T.crossingAngle
      ? T.crossingPenalty : 0;
  const short = chop >= T.shortChopHeight * S && finite(c.chop.period) <= boat.chopPeriod ? T.shortChopPenalty : 0;
  const wavePenalty = Math.max(
    Math.max(0, sea - T.comfortSeaStart * S) * T.comfortSeaSlope / S,
    Math.max(0, chop - T.comfortChopStart * S) * T.comfortChopSlope / S,
  );
  const comfortWind = Math.max(0, wind - T.comfortWindStart * W) * T.comfortWindSlope / W
    + Math.max(0, gust - T.comfortGustStart * W) * T.comfortGustSlope / W;
  const comfort = clamp(10 - combinedBurden(comfortWind, wavePenalty) - crossing - short);
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
