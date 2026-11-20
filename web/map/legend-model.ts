// MB-11a: the legend's decision logic as pure functions (no DOM, no fetch), so the
// later Legend.tsx edit (MB-11b) is wiring only. Plan: REPLAN-PARALLEL.md § 2 E3;
// design: MAP-BUILD-BATCH.md MB-11 (with the t_7a52c90b amendment), E2E-IMPL-BATCH.md
// MB-11 amendment, MAP-DESIGN-LOCK.md § 1.2 and § 10.2.
//
// Everything returned is a string ID or plain data, never display text. MB-11b adds
// the catalogue strings (en + es) for every NEW id listed below.
//
// Erasable syntax only: tests/test_legend_model.mjs imports this file by type stripping.
//
// ── Depth chips ─────────────────────────────────────────────────────────────────
// Ramp B has no palette token yet (§ 10.2: "relief PNG (no token)"), and web/ may not
// hold colour literals (scripts/check_tokens.mjs). The chips therefore name a token:
// `depthB0` … `depthB10` (CSS `--depth-b-0` … `--depth-b-10`). MB-11b adds them to
// PALETTE_TOKENS and web/tokens.css with the § 1.2 / § 10.2 values, identical in both
// themes (§ 10.1). `depthChips` resolves `color` only when it is handed a palette.
//
// ── Survey-detail chips ─────────────────────────────────────────────────────────
// Input keys are MB-22's decode output (web/map/survey-detail.ts): the per-footprint
// `tier` ('1m-measured' | '2m' | '5m' | 'estimated' | 'none') and, for a compiled
// grid, `grid_tier: '4-16m-compiled'` (always with tier 'estimated'). Anything else
// is ignored: an unknown class never lights a chip.
//
// ── Depth-lines copy ids ────────────────────────────────────────────────────────
// v1 (and a file with no `set`): exactly today's ids (Legend.tsx DepthContoursRow).
// ft-v2: NEW ids for MB-11b to add, en + es (no source names anywhere, G 11-18):
//   layer.depth-contours.v2.basis    lines in feet, closer together as you zoom in,
//                                    heavier at 60, 150 and 300 ft, to 300 ft,
//                                    estimated from the reviewed survey grids,
//                                    NOT FOR NAVIGATION kept
//   layer.depth-contours.v2.legend0  depth lines in feet; closer as you zoom in;
//                                    heavier at 60, 150 and 300 ft
//   layer.depth-contours.v2.legend1  survey edge: no reviewed grid beyond
//   layer.depth-contours.v2.planner  planner contour-track text with no fixed interval
//                                    ("Published index contours as tracks, with
//                                    survey, date and datum; not for navigation.")
// MB-11b may point `planner` at one reworded shared id instead (the amendment drops
// "every 150 ft" for both sets); this model keeps v1 on today's id until it does.

export type ContourSet = 'v1' | 'ft-v2';
export type LegendTheme = 'dark' | 'light';

/** The always-present footer id (today's `legend.notForNav`). */
export const NOT_FOR_NAVIGATION_ID = 'legend.notForNav';

// ── Depth chips ──────────────────────────────────────────────────────────────────

/** Palette keys MB-11b adds for ramp B, shallow to deep. */
export const RAMP_B_TOKENS = ['depthB0', 'depthB1', 'depthB2', 'depthB3', 'depthB4', 'depthB5',
  'depthB6', 'depthB7', 'depthB8', 'depthB9', 'depthB10'] as const;
export type RampBToken = typeof RAMP_B_TOKENS[number];

/** § 1.2 legend depths in feet: 0, 10, 20, 33, 50, 66, 100, 150, 200, 300, then 300+. */
const RAMP_B_FEET = [0, 10, 20, 33, 50, 66, 100, 150, 200, 300, 300] as const;
/** The 0–66 ft (0–20 m) spearfishing band ends at the 66 ft chip. */
export const SHALLOW_BAND_FT = 66;

export type DepthChip = {
  token: RampBToken;
  /** The legend depth in feet; for the last chip, the depth it exceeds. */
  feet: number;
  /** True for the deepest chip ("300+"). */
  orMore: boolean;
  /** Light theme draws the chips with a 1 px inset ring (§ 10.2). */
  ring: boolean;
  /** The token's value when a palette was supplied; never a literal of this module. */
  color?: string;
};

export function depthChips(theme: LegendTheme, palette?: Readonly<Partial<Record<RampBToken, string>>>): DepthChip[] {
  return RAMP_B_TOKENS.map((token, i) => {
    const chip: DepthChip = {token, feet: RAMP_B_FEET[i] ?? 0, orMore: i === RAMP_B_TOKENS.length - 1, ring: theme === 'light'};
    const color = palette?.[token];
    if (color !== undefined) chip.color = color;
    return chip;
  });
}

/** The "0–66 ft (0–20 m)" bar: the 0 ft colour, with the same light-theme ring. */
export function shallowBand(theme: LegendTheme): {token: RampBToken; fromFeet: number; toFeet: number; ring: boolean} {
  return {token: RAMP_B_TOKENS[0], fromFeet: 0, toFeet: SHALLOW_BAND_FT, ring: theme === 'light'};
}

// ── Survey-detail chips ──────────────────────────────────────────────────────────

export const SURVEY_DETAIL_CHIPS = ['1m-measured', '2m', '5m', '4-16m-compiled', 'estimated', 'none'] as const;
export type SurveyDetailChipId = typeof SURVEY_DETAIL_CHIPS[number];
export const SURVEY_DETAIL_TITLE_ID = 'legend.surveyDetail.title';

export type SurveyDetailChip = {id: SurveyDetailChipId; labelId: string; bold: boolean};

const known = (value: string): value is SurveyDetailChipId => (SURVEY_DETAIL_CHIPS as readonly string[]).includes(value);
/** Coarser-than-1 m products: in 0–66 ft water the legend reports them as "estimated". */
const REPORTED_AS_ESTIMATED_IN_SHALLOWS: readonly SurveyDetailChipId[] = ['2m', '5m', '4-16m-compiled'];

/**
 * Which chips are bold (present) and which are greyed (absent).
 *
 * `classesInView`: every class drawn in the view, at any depth.
 * `shallowClasses`: the classes present in 0–66 ft water (the caller knows the band;
 * the decode output does not carry it). A class may ALSO occur deeper.
 * `deeperClasses`: the classes present deeper than 66 ft. Shallow and deeper presence
 * are independent, so one class can be in both sets.
 *
 * 0–66 ft rule (E2E-IMPL-BATCH MB-11 amendment): the band is shown as `1m-measured` or
 * `estimated` only. A 2 m, 5 m or compiled class present in the shallows makes
 * `estimated` bold; it never shows as `2m` for that band. The class's own chip is bold
 * only if it is also present outside the shallows (deeper, or in view with no band
 * given). An interpolated 1 m grid arrives as `estimated` (MB-09) and so never lights
 * `1m-measured`. Without band sets the view is taken as drawn.
 */
export function surveyDetailChips(
  classesInView: ReadonlySet<string>,
  shallowClasses: ReadonlySet<string> = new Set(),
  deeperClasses: ReadonlySet<string> = new Set(),
): SurveyDetailChip[] {
  const bold = new Set<SurveyDetailChipId>();
  // Outside the shallows: deeper classes, and in-view classes the caller did not place in the shallows.
  for (const id of classesInView) if (known(id) && !shallowClasses.has(id)) bold.add(id);
  for (const id of deeperClasses) if (known(id)) bold.add(id);
  for (const id of shallowClasses) {
    if (!known(id)) continue;
    if (REPORTED_AS_ESTIMATED_IN_SHALLOWS.includes(id)) bold.add('estimated');
    else bold.add(id);
  }
  return SURVEY_DETAIL_CHIPS.map(id => ({id, labelId: `legend.surveyDetail.chip.${id}`, bold: bold.has(id)}));
}

// ── Depth-lines copy ids ─────────────────────────────────────────────────────────

export type ContourCopy = {
  set: ContourSet;
  /** The row's name and its popover title, shared by both sets. */
  label: string;
  summary: string;
  basis: string;
  /** [contour key, survey-edge key]. */
  legend: [string, string];
  plannerLabel: string;
  plannerText: string;
  notForNavigation: typeof NOT_FOR_NAVIGATION_ID;
};

const V1 = {
  label: 'layer.depth-contours.label', summary: 'legend.bs.depth', basis: 'layer.depth-contours.basis',
  legend: ['layer.depth-contours.legend0', 'layer.depth-contours.legend1'],
  plannerLabel: 'planner.layer.contours', plannerText: 'planner.layer.contours.text',
} as const;
const V2 = {
  label: V1.label, summary: V1.summary, basis: 'layer.depth-contours.v2.basis',
  legend: ['layer.depth-contours.v2.legend0', 'layer.depth-contours.v2.legend1'],
  plannerLabel: V1.plannerLabel, plannerText: 'layer.depth-contours.v2.planner',
} as const;

/** An absent `set` is a v1 file. Any other unknown value throws rather than show copy that may be wrong. */
export function contourCopy(set: ContourSet | undefined): ContourCopy {
  if (set !== undefined && set !== 'v1' && set !== 'ft-v2') throw new RangeError(`Unknown contour set: ${String(set)}`);
  const ids = set === 'ft-v2' ? V2 : V1;
  return {set: set === 'ft-v2' ? 'ft-v2' : 'v1', label: ids.label, summary: ids.summary, basis: ids.basis,
    legend: [ids.legend[0], ids.legend[1]], plannerLabel: ids.plannerLabel, plannerText: ids.plannerText,
    notForNavigation: NOT_FOR_NAVIGATION_ID};
}
