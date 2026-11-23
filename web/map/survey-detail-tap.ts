import {t, type Language} from '../i18n.ts';

// Finest to coarsest, following the decoded tier rather than the numeric grid.
const TIERS = ['1m-measured', '2m', '5m', 'estimated', 'none'] as const;
type Tier = typeof TIERS[number];

/** A decoded feature's properties, paired with its owning collection's region ID. */
export interface SurveyDetailHit {
  readonly region: string;
  readonly properties: Readonly<Record<string, unknown>>;
}

export interface SurveyDetailReadout {
  tier: Tier;
  gridM: number | null;
  date: string | null;
  text: string;
  sourcesHref: string;
}

/** Keep the first hit at the finest tier, unless a duplicate has stronger metadata.
 * As elsewhere in the app, pass the ready language. */
export function confidenceAt(features: readonly SurveyDetailHit[], lang: Language): SurveyDetailReadout | null {
  let best: SurveyDetailHit | undefined;
  let rank: number = TIERS.length;
  let metadataRank = 0;
  let gridM: number | null = null;
  let date: string | null = null;
  for (const feature of features) {
    const {tier: rawTier, grid_m, date: rawDate} = feature.properties;
    const next = TIERS.findIndex(tier => tier === rawTier);
    if (next < 0 || next > rank || (next === rank && feature.region !== best?.region)) continue;

    const nextGrid = rawTier !== 'none' && typeof grid_m === 'number' && Number.isFinite(grid_m) && grid_m > 0 ? grid_m : null;
    const nextDate = rawTier !== 'none' && typeof rawDate === 'string' && rawDate.trim() ? rawDate : null;
    const nextMetadata = nextGrid !== null ? 2 : nextDate !== null ? 1 : 0;
    if (next === rank && nextMetadata <= metadataRank) continue;

    best = feature;
    rank = next;
    metadataRank = nextMetadata;
    gridM = nextGrid;
    date = nextDate;
  }
  const tier = TIERS[rank];
  if (!best || !tier) return null;

  // Never display feature label or provenance: the catalogue owns all readout copy.
  const text = tier === 'estimated' && gridM !== null
    ? t('legend.surveyDetail.estimateGrid', lang, {grid: gridM})
    : t(`legend.surveyDetail.chip.${tier}`, lang);
  return {tier, gridM, date, text, sourcesHref: `/sources#region-${best.region}`};
}
