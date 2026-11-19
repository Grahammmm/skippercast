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
// web/ may not hold colour literals (scripts/check_tokens.mjs), so a chip names the
// generated custom property that colours it (`lookDepthKey` below); the ramp-B and
// nearshore chip colours are identical in both themes (§ 10.1).
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
import type {NearshoreStyle} from './nearshore-paint.ts';
import {NEARSHORE_LOOKS, NEARSHORE_STYLE} from './nearshore-style.gen.ts';

export type ContourSet = 'v1' | 'ft-v2';
export type LegendTheme = 'dark' | 'light';

/** The always-present footer id (today's `legend.notForNav`). */
export const NOT_FOR_NAVIGATION_ID = 'legend.notForNav';

// ── Depth chips ──────────────────────────────────────────────────────────────────

/** The 0–66 ft (0–20 m) spearfishing band ends at the 66 ft chip. */
export const SHALLOW_BAND_FT = 66;

// ── Depth chips by look (MSK-2, STYLE-PIPELINE-DESIGN rev 2 § 6) ─────────────────
// The chips follow the look the region's relief tiles were baked with (web/map/relief-data.ts `reliefLook`): the
// pointer's baked digest, or `deep-fixed-v1` (ramp B: § 1.2 depths 0, 10, 20, 33, 50, 66, 100, 150, 200, 300 and
// 300+ on `--depth-b-0` … `--depth-b-10`) for a pointer without a `style` member. The generated
// NEARSHORE_LOOKS table (scripts/style/gen_style.py) holds every active or rolling look, so during a roll-forward or a
// rollback each region's legend shows its own tiles' colours. An unknown or invalid look fails closed: no chips (and
// no band swatch) and one row saying the key is unavailable; never another look's chips.

type LookTable = Readonly<Record<string, {readonly chips: readonly {readonly depth_ft: number; readonly cssVar: string}[]; readonly plus300: string}>>;
export type LookChip = {
  /** The legend depth in feet; for the last chip, the depth it exceeds. */
  feet: number;
  orMore: boolean;
  /** Light theme draws the chips with a 1 px inset ring (§ 10.2). */
  ring: boolean;
  /** The generated custom property that colours the chip (a `--skn-*` or `--depth-b-*` name). */
  cssVar: string;
};
export type DepthKey =
  | {status: 'chips'; chips: LookChip[]; band: {cssVar: string; fromFeet: number; toFeet: number; ring: boolean}}
  | {status: 'unavailable'; rowId: typeof LOOK_UNAVAILABLE_ID};
export const LOOK_UNAVAILABLE_ID = 'legend.relief.lookUnavailable';

export function lookDepthKey(look: string | null, theme: LegendTheme, looks: LookTable = NEARSHORE_LOOKS): DepthKey {
  const entry = look !== null && Object.hasOwn(looks, look) ? looks[look] : undefined;
  if (!entry?.chips.length) return {status: 'unavailable', rowId: LOOK_UNAVAILABLE_ID};
  const ring = theme === 'light';
  const chips = [...entry.chips.map(c => ({feet: c.depth_ft, orMore: false, ring, cssVar: c.cssVar})),
    {feet: entry.chips.at(-1)!.depth_ft, orMore: true, ring, cssVar: entry.plus300}];
  return {status: 'chips', chips, band: {cssVar: entry.chips[0]!.cssVar, fromFeet: 0, toFeet: SHALLOW_BAND_FT, ring}};
}

// ── Nearshore rows (MSK-2) ───────────────────────────────────────────────────────
// Each row shows only when the region's data says the feature is present (pointer, contour or habitat metadata); with
// no flags, no row. The producers that set these flags are MSK-4 (pointer) and MSK-6 (habitat vectors).

export type NearshoreFlags = Readonly<{
  /** Rock piles drawn from a substrate survey, and from relief alone (no substrate survey). */
  pilesSurveyed?: boolean;
  pilesFromRelief?: boolean;
  /** The hard-bottom edge's substrate source: its cell size and year. */
  hardEdge?: Readonly<{cell_m: number; year: number | string}>;
  /** The survey cell size where the view is finer than the data. */
  resolution_m?: number;
}>;
export type NearshoreRow = {id: string; vars?: Record<string, string | number>; cssVar?: string};

export function nearshoreRows(flags: NearshoreFlags, style: Pick<NearshoreStyle, 'rock_piles' | 'bottom_type'> = NEARSHORE_STYLE): NearshoreRow[] {
  const rows: NearshoreRow[] = [];
  if (flags.pilesSurveyed === true) rows.push({id: 'legend.relief.pileSurveyed', cssVar: style.rock_piles.fill});
  if (flags.pilesFromRelief === true) rows.push({id: 'legend.relief.pileRelief', cssVar: style.rock_piles.fill});
  const edge = flags.hardEdge;
  if (edge && Number.isFinite(edge.cell_m) && edge.cell_m > 0 && String(edge.year).trim()) {
    rows.push({id: 'legend.relief.hardEdge', vars: {cell: edge.cell_m, year: edge.year}, cssVar: style.bottom_type.hard_edge.color});
  }
  const cell = flags.resolution_m;
  if (typeof cell === 'number' && Number.isFinite(cell) && cell > 0) rows.push({id: 'legend.relief.resolution', vars: {cell}});
  return rows;
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
