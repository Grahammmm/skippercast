// Fishing-friend per-factor explainer, slice 3 (issue #3845; G BESTBET 2026-11-28): for one ranked
// best-bets row, the inputs behind the call, each marked helps / neutral / hurts with where the
// reading comes from, so the friend can say why in plain words ("the wind is light, the bottom is
// prime reef, the two forecasts agree"). Every effect comes from a rule the engine already uses:
//  - sea comfort: the shared comfort word (web/score.ts via windowConditions): Comfortable helps,
//    Bumpy is neutral (a gate closes Rough, so a ranked row is never Rough);
//  - forecast agreement: windowConditions' models_agree (true helps, false hurts, unknown neutral);
//  - marine alerts: a ranked row passed a complete, current NWS check with no advisory (helps);
//  - reef structure: H on the atlas terrain grade cut-offs (A >= 75, B >= 55, else C;
//    src/skippercast/atlas/scoring.py habitat_grade): A helps, B neutral, C hurts;
//  - moon and pressure: listed as untested and never weighted (G's research: hypotheses, not facts).
// Pure: no I/O, no clock. No percentage, score number or coordinate in any reading.
import {COMFORT_WORD} from '../answers/comfort.ts';
import {MODELS_DISAGREE, type ScoreRow} from './best-bets.ts';

export type Effect = 'helps' | 'neutral' | 'hurts';
export interface Factor {factor: string; reading: string; effect: Effect; source: string}

/** The atlas terrain grade cut-offs (habitat_score 0-100), applied to H (0-1). */
export const GRADE_A = 0.75, GRADE_B = 0.55;
export const UNTESTED: Factor = Object.freeze({factor: 'moon and pressure', reading: 'not used: untested', effect: 'neutral', source: 'not tested yet'});

/** The factors behind a ranked row, in a fixed order; [] for a row a gate closed or that has no rank (no call is explained). */
export function factorsFor(row: ScoreRow): Factor[] {
  if (row.rank === null || row.gate !== 'pass') return [];
  const c = row.conditions, h = row.habitat;
  const readings = c.reasons.filter(r => r !== MODELS_DISAGREE);
  const comfort: Effect = c.comfort === COMFORT_WORD.go ? 'helps' : 'neutral';
  const agree = c.models_agree;
  const grade = h.value === null ? null : h.value >= GRADE_A ? 'A' : h.value >= GRADE_B ? 'B' : 'C';
  return [
    {factor: 'sea comfort', reading: [c.comfort, ...readings].join(', '), effect: comfort, source: 'marine forecast'},
    {factor: 'forecast agreement', reading: agree === true ? 'forecast models agree' : agree === false ? MODELS_DISAGREE : 'one forecast model only',
      effect: agree === true ? 'helps' : agree === false ? 'hurts' : 'neutral', source: 'marine forecast'},
    {factor: 'marine alerts', reading: 'no marine advisory for these hours', effect: 'helps', source: 'NWS marine alerts'},
    {factor: 'reef structure', reading: [`best reef marks average grade ${grade}`, ...h.reasons].join(', '),
      effect: grade === 'A' ? 'helps' : grade === 'B' ? 'neutral' : 'hurts', source: 'seafloor map'},
    {...UNTESTED},
  ];
}
