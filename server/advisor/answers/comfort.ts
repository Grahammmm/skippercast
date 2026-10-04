// The boat-comfort score and word for get_conditions (06 § planning step 2):
// the comfort half of hourScores()/limitedScores() in web/score.ts, copied
// because server/ does not import web/. Only the comfort lines are here (no
// control score: the person's boat and rig are unknown by text), for the
// reference 23 ft boat (factors {sea: 1, wind: 1, chopPeriod: 6}), which the
// reply calls "a mid-size center console". tests/test_advisor_tools.mjs pins
// it to web/score.ts over the 150 golden cases in tests/fixtures/score-golden.json.
// A planning heuristic, never a safety clearance; an advisory makes it 'rough'.

export interface BoatFactors {sea: number; wind: number; chopPeriod: number}
export const REFERENCE_BOAT: Readonly<BoatFactors> = Object.freeze({sea: 1, wind: 1, chopPeriod: 6});
export const BOAT_PHRASE = 'a mid-size center console';

/** web/score.ts THRESHOLDS, the comfort and verdict lines only. */
export const COMFORT = Object.freeze({
  go: 7, noGo: 4, capLimited: 6.9,
  comfortWindStart: 4, comfortGustStart: 7, comfortWindSlope: 0.22, comfortGustSlope: 0.1,
  comfortSeaStart: 1.5, comfortSeaSlope: 0.7, comfortChopStart: 0.4, comfortChopSlope: 0.9,
  crossingSecondaryHeight: 1, crossingAngle: 60, crossingPenalty: 0.7, shortChopHeight: 0.5, shortChopPenalty: 0.8, overlap: 0.45,
});

export interface Partition {height: number | null; period?: number | null; from?: number | null}
export interface HourConditions {wind: number | null; gust: number | null; sea: Partition; chop: Partition; swell: Partition; secondary: Partition}

const clamp = (n: number): number => Math.round(Math.max(0, Math.min(10, n)) * 10) / 10;
const burden = (wind: number, wave: number): number => Math.max(wind, wave) + COMFORT.overlap * Math.min(wind, wave);
const finite = (v: number | null | undefined): number => (Number.isFinite(v as number) ? (v as number) : 0);
function angleBetween(a: number | null | undefined, b: number | null | undefined): number | null {
  return Number.isFinite(a as number) && Number.isFinite(b as number) ? Math.abs((((a as number) - (b as number) + 540) % 360) - 180) : null;
}

/** web/score.ts hourScores(...).comfort: the rougher wind and seas of two models, the checked gust, the first model's partitions. */
export function hourComfort(c: HourConditions, other: {wind: number | null; sea: {height: number | null}}, checkedGust: number, boat: BoatFactors = REFERENCE_BOAT): number {
  const T = COMFORT, S = boat.sea, W = boat.wind;
  const wind = Math.max(finite(c.wind), finite(other.wind));
  const sea = Math.max(finite(c.sea.height), finite(other.sea.height));
  const chop = finite(c.chop.height);
  const crossing = finite(c.secondary.height) >= T.crossingSecondaryHeight * S && (angleBetween(c.swell.from, c.secondary.from) ?? -1) >= T.crossingAngle ? T.crossingPenalty : 0;
  const short = chop >= T.shortChopHeight * S && finite(c.chop.period) <= boat.chopPeriod ? T.shortChopPenalty : 0;
  const wave = Math.max(Math.max(0, sea - T.comfortSeaStart * S) * T.comfortSeaSlope / S, Math.max(0, chop - T.comfortChopStart * S) * T.comfortChopSlope / S);
  const windCost = Math.max(0, wind - T.comfortWindStart * W) * T.comfortWindSlope / W + Math.max(0, checkedGust - T.comfortGustStart * W) * T.comfortGustSlope / W;
  return clamp(10 - burden(windCost, wave) - crossing - short);
}

/** web/score.ts limitedScores(...).comfort, when chop, swell or a consistent gust is missing. */
export function limitedComfort(wind: number, sea: number, gust: number | null, boat: BoatFactors = REFERENCE_BOAT): number {
  const T = COMFORT, S = boat.sea, W = boat.wind;
  const windCost = Math.max(0, wind - T.comfortWindStart * W) * T.comfortWindSlope / W + (gust === null ? 0 : Math.max(0, gust - T.comfortGustStart * W) * T.comfortGustSlope / W);
  return clamp(10 - burden(windCost, Math.max(0, sea - T.comfortSeaStart * S) * T.comfortSeaSlope / S));
}

export type Verdict = 'go' | 'marginal' | 'no-go' | 'unknown';
/** web/score.ts verdictFor. */
export function verdictFor(rating: {conditions?: number | null; hazard?: boolean} | null | undefined): Verdict {
  if (!rating || !Number.isFinite(rating.conditions as number)) return 'unknown';
  if (rating.hazard || (rating.conditions as number) < COMFORT.noGo) return 'no-go';
  return (rating.conditions as number) >= COMFORT.go ? 'go' : 'marginal';
}

/** The word a text uses for a verdict: never "go", which reads as a clearance. */
export const COMFORT_WORD: Readonly<Record<Verdict, string>> = Object.freeze({go: 'comfortable', marginal: 'bumpy', 'no-go': 'rough', unknown: 'unknown'});
