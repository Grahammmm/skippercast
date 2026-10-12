// The boat-comfort score and word for get_conditions (06 § planning step 2):
// the comfort half of hourScores()/limitedScores() from web/score.ts, the one
// conditions model, so the advisor cannot drift from the brief and planner.
// Only the comfort score is used (no control score: the person's boat and rig
// are unknown by text), for the reference 23 ft boat (factors {sea: 1, wind: 1,
// chopPeriod: 6}), which the reply calls "a mid-size center console".
// tests/test_advisor_tools.mjs pins it over the 150 golden cases in
// tests/fixtures/score-golden.json.
// A planning heuristic, never a safety clearance; an advisory makes it 'rough'.

import {hourScores, limitedScores, verdictFor, type BoatFactors, type HourConditions, type Verdict} from '../../../web/score.ts';

export {verdictFor};
export type {BoatFactors, HourConditions, Verdict};
export const REFERENCE_BOAT: Readonly<BoatFactors> = Object.freeze({sea: 1, wind: 1, chopPeriod: 6});
export const BOAT_PHRASE = 'a mid-size center console';

/** hourScores(...).comfort: the rougher wind and seas of two models, the checked gust, the first model's partitions. */
export function hourComfort(c: HourConditions, other: {wind: number | null; sea: {height: number | null}}, checkedGust: number, boat: BoatFactors = REFERENCE_BOAT): number {
  return hourScores(c, other, 'boat-comfort', checkedGust, boat).comfort;
}

/** limitedScores(...).comfort, when chop, swell or a consistent gust is missing (uncapped; callers cap it at THRESHOLDS.capLimited). */
export function limitedComfort(wind: number, sea: number, gust: number | null, boat: BoatFactors = REFERENCE_BOAT): number {
  return limitedScores(wind, sea, gust, 'boat-comfort', boat).comfort;
}

/** The word a text uses for a verdict: never "go", which reads as a clearance. */
export const COMFORT_WORD: Readonly<Record<Verdict, string>> = Object.freeze({go: 'comfortable', marginal: 'bumpy', 'no-go': 'rough', unknown: 'unknown'});
