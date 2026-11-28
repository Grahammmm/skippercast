// Fishing-friend per-factor explainer, slice 3 (issue #3845; G BESTBET 2026-11-28): for one ranked
// best-bets row, the inputs behind the call, each marked helps / neutral / hurts with where the
// reading comes from, so the friend can say why in plain words ("the wind is light, the bottom is
// prime reef, the two forecasts agree"). Every effect comes from a rule the engine already uses:
//  - sea comfort: the shared comfort word (web/score.ts via windowConditions): Comfortable helps,
//    Bumpy is neutral (a gate closes Rough, so a ranked row is never Rough);
//  - forecast agreement: windowConditions' models_agree over the hours both models could be compared
//    (models_compared): agree in every hour helps, agree in only some is reported but neutral, any
//    disagreement hurts, no comparable hour is "could not be compared" (neutral), and "one forecast
//    model only" only when no second-model reading exists at all;
//  - marine alerts: a ranked row passed a complete, current NWS check with no overlapping advisory
//    (helps), worded as the last check (up to ALERT_CHECK_MAX_HOURS old), never a live all-clear;
//  - reef structure: H on the atlas terrain grade cut-offs (A >= 75, B >= 55, else C;
//    src/skippercast/atlas/scoring.py habitat_grade): A helps, B neutral, C hurts;
//  - moon and pressure: listed as untested and never weighted (G's research: hypotheses, not facts).
// Pure: no I/O, no clock. No percentage, score number or coordinate in any reading.
import {COMFORT_WORD} from '../answers/comfort.ts';
import {MODELS_DISAGREE, type ConditionsPart, type ScoreRow} from './best-bets.ts';

export type Effect = 'helps' | 'neutral' | 'hurts';
export interface Factor {factor: string; reading: string; effect: Effect; source: string}

/** The atlas terrain grade cut-offs (habitat_score 0-100), applied to H (0-1). */
export const GRADE_A = 0.75, GRADE_B = 0.55;
export const UNTESTED: Factor = Object.freeze({factor: 'moon and pressure', reading: 'not used: untested', effect: 'neutral', source: 'not tested yet'});

/** The forecast-agreement factor, worded for the hours the two models could actually be compared (models_compared). */
export function agreementFactor(c: ConditionsPart): Factor {
  const src = {factor: 'forecast agreement', source: 'marine forecast'};
  const n = c.models_compared, partial = n !== null && n.paired > 0 && n.paired < n.hours;
  const of = partial ? ` in the ${n.paired} of ${n.hours} hours both could be compared` : '';
  if (c.models_agree === false) return {...src, reading: `${MODELS_DISAGREE}${of}`, effect: 'hurts'};
  // Agreement helps only when every hour of the block was compared; a partial comparison is reported, not counted.
  if (c.models_agree === true && n !== null) return {...src, reading: `forecast models agree${of}`, effect: partial ? 'neutral' : 'helps'};
  if (n !== null && n.second === 0) return {...src, reading: 'one forecast model only', effect: 'neutral'};
  return {...src, reading: NOT_COMPARED, effect: 'neutral'};
}
/** No hour with both models' wind and seas (or no record of the comparison): agreement is unknown, never "one model". */
export const NOT_COMPARED = 'forecast models could not be compared for these hours';
/** A ranked row passed the last recorded NWS check (alertCheckCurrent: up to ALERT_CHECK_MAX_HOURS old); it is not a live all-clear for a later trip. */
export const ALERTS_AT_LAST_CHECK = 'no overlapping marine advisory was listed at the last NWS check; check current NWS marine alerts before leaving';

/** The factors behind a ranked row, in a fixed order; [] for a row a gate closed or that has no rank (no call is explained). */
export function factorsFor(row: ScoreRow): Factor[] {
  if (row.rank === null || row.gate !== 'pass') return [];
  const c = row.conditions, h = row.habitat;
  const readings = c.reasons.filter(r => r !== MODELS_DISAGREE);
  const comfort: Effect = c.comfort === COMFORT_WORD.go ? 'helps' : 'neutral';
  const grade = h.value === null ? null : h.value >= GRADE_A ? 'A' : h.value >= GRADE_B ? 'B' : 'C';
  return [
    {factor: 'sea comfort', reading: [c.comfort, ...readings].join(', '), effect: comfort, source: 'marine forecast'},
    agreementFactor(c),
    {factor: 'marine alerts', reading: ALERTS_AT_LAST_CHECK, effect: 'helps', source: 'NWS marine alerts'},
    {factor: 'reef structure', reading: [`best reef marks average grade ${grade}`, ...h.reasons].join(', '),
      effect: grade === 'A' ? 'helps' : grade === 'B' ? 'neutral' : 'hurts', source: 'seafloor map'},
    {...UNTESTED},
  ];
}
