// Fishing-friend "best bets" engine, slice 1 (issue #3845): for one region, one mode (boat) and
// one species group (reef: lingcod and rockfish), score every named public ground x
// 3-hour block x day of the forecast, and pick the best few.
//
// Two explainable parts, each 0-1, behind hard gates:
//  - C, conditions: the advisor's one comfort model (answers/conditions.ts
//    windowConditions, the same web/score.ts rubric get_conditions and the brief use)
//    at the ground's nearest coastal forecast point, held by the forecast clock; a
//    boating advisory or a Rough block is a gate, not a low score.
//  - H, habitat: the mean of the three best terrain scores among the reef search
//    targets mapped inside the ground (dist/data/atlas.json habitat_score via
//    dist/data/charter-grounds.json nearby_target_ids). Structure, not abundance.
// rank = w_C * C + w_H * H (weights versioned, WEIGHTS_V1). Recent catch evidence (E),
// season gates, the harbour bar and kayak/shore modes are later slices; the file says so.
//
// Pure: no I/O, no clock, no model call. Nothing here is a catch probability, and the
// output names only allowlisted public grounds and forecast point ids: never a
// coordinate (tests/test_advisor_score.mjs checks it). Not registered as a tool yet.
import {advisoriesFrom, advisoryCheckTime, regionZones, windowConditions, windowEpochs, withForecastClock, type DayConditions} from '../answers/conditions.ts';
import {forecastClock} from '../answers/forecast-clock.ts';
import {COMFORT_WORD} from '../answers/comfort.ts';
import type {Confidence} from '../answers/confidence.ts';
import type {Region} from '../../types.ts';

export const SCORE_SCHEMA = 1;
export const WEIGHTS_V1 = Object.freeze({version: 'v1', conditions: 0.55, habitat: 0.45, models_disagree: 0.8});
export type Weights = typeof WEIGHTS_V1;

/** Local-hour blocks, both ends inclusive (windowConditions' window). */
export const BLOCKS = Object.freeze([
  {id: 'morning', start: 6, end: 8}, {id: 'midday', start: 9, end: 11},
  {id: 'afternoon', start: 12, end: 14}, {id: 'evening', start: 15, end: 17},
] as const);
export type BlockId = typeof BLOCKS[number]['id'];

export interface PublicGroundIn {name: string; charter_ground_id: string; species: string[]}
export interface CharterGroundIn {id: string; latitude: number; longitude: number; nearby_target_ids?: string[]}
export interface TargetIn {id: string; habitat_score: number; habitat_grade?: string; confidence?: string}
export interface Ground {name: string; ground_id: string; point: string; target_ids: string[]}

export type Gate = 'pass' | 'advisory' | 'rough';
export interface Part {value: number | null; evidence: Confidence; reasons: string[]}
export interface ConditionsPart extends Part {gate: Gate; comfort: string}
export interface ScoreRow {
  area: string; ground_id: string; point: string; date: string; block: BlockId;
  gate: Gate; conditions: ConditionsPart; habitat: Part; rank: number | null; evidence: Confidence;
}
export interface ScoreFile {
  schema_version: number; weights_version: string; region_id: string; mode: 'boat'; group: 'reef'; species: string[];
  generated_at: string; forecast_issued: string | null; forecast_age_hours: number | null; advisories_checked: boolean;
  method: string; limitations: string[]; rows: ScoreRow[];
}

const LADDER: readonly Confidence[] = ['Insufficient', 'Low', 'Moderate'];
const weakest = (...levels: Confidence[]): Confidence => LADDER[Math.min(...levels.map(l => LADDER.indexOf(l)))]!;
const round = (n: number, places = 3) => Math.round(n * 10 ** places) / 10 ** places;
const REEF = ['lingcod', 'rockfish'];

/** The coastal (not offshore) forecast point nearest a ground, by equirectangular distance; null without one. */
export function nearestPoint(region: Region, latitude: number, longitude: number): string | null {
  const k = Math.cos(latitude * Math.PI / 180);
  let best: string | null = null, bestD = Infinity;
  for (const p of region.forecast_points as {id: string; latitude: number; longitude: number; offshore?: boolean}[]) {
    if (p.offshore) continue;
    const d = (p.latitude - latitude) ** 2 + ((p.longitude - longitude) * k) ** 2;
    if (d < bestD) { bestD = d; best = p.id; }
  }
  return best;
}

/** The region's allowlisted reef grounds joined to their charter ground; a ground missing from either list, or without a forecast point, is dropped. */
export function reefGrounds(region: Region, publicGrounds: readonly PublicGroundIn[], charter: readonly CharterGroundIn[]): Ground[] {
  const byId = new Map(charter.map(c => [c.id, c] as const));
  const out: Ground[] = [];
  for (const g of publicGrounds) {
    const c = byId.get(g.charter_ground_id);
    if (!c || !g.species.some(s => REEF.includes(s)) || !Number.isFinite(c.latitude) || !Number.isFinite(c.longitude)) continue;
    const point = nearestPoint(region, c.latitude, c.longitude);
    if (point) out.push({name: g.name, ground_id: c.id, point, target_ids: [...(c.nearby_target_ids ?? [])]});
  }
  return out;
}

/** H: mean of the three best mapped terrain scores (0-100) in the ground, as 0-1. Moderate only when those three are all Moderate-confidence targets. */
export function habitatFit(ground: Ground, targets: readonly TargetIn[]): Part {
  const byId = new Map(targets.map(t => [t.id, t] as const));
  const mine = ground.target_ids.map(id => byId.get(id)).filter((t): t is TargetIn => Boolean(t) && Number.isFinite(t!.habitat_score))
    .sort((a, b) => b.habitat_score - a.habitat_score);
  if (!mine.length) return {value: null, evidence: 'Insufficient', reasons: ['no graded reef targets mapped here']};
  const top = mine.slice(0, 3);
  const value = round(top.reduce((s, t) => s + t.habitat_score, 0) / top.length / 100, 2);
  const evidence: Confidence = top.length === 3 && top.every(t => t.confidence === 'Moderate') ? 'Moderate' : 'Low';
  const grade = top[0]!.habitat_grade ? `, best terrain grade ${top[0]!.habitat_grade}` : '';
  return {value, evidence, reasons: [`${mine.length} mapped reef search targets${grade}`, 'terrain grade measures structure, not fish']};
}

/** C from one block's DayConditions: Comfortable 1, Bumpy 0.5, Unknown none; Rough or an advisory closes the gate; model disagreement scales C down. */
export function conditionsFit(day: DayConditions, weights: Weights = WEIGHTS_V1, advisory: string | null = null): ConditionsPart {
  const base = {comfort: day.comfort};
  // An advisory closes the gate even when the forecast itself is unusable (withForecastClock drops day.advisory then).
  const event = day.advisory ?? advisory;
  if (event) return {...base, gate: 'advisory', value: 0, evidence: 'Moderate', reasons: [event]};
  if (!day.available) return {...base, gate: 'pass', value: null, evidence: 'Insufficient', reasons: [day.reason ?? 'no forecast']};
  const span = (r: [number, number]) => r[0] === r[1] ? `${r[0]}` : `${r[0]}-${r[1]}`;
  const reasons = [
    day.wind_kt ? `wind ${span(day.wind_kt)} kt${day.wind_from ? ` ${day.wind_from}` : ''}` : null,
    day.seas_ft ? `seas ${span(day.seas_ft)} ft${day.sea_period_s ? ` at ${day.sea_period_s} s` : ''}` : null,
    day.comfort_held ?? null,
  ].filter((r): r is string => r !== null);
  if (day.comfort === COMFORT_WORD['no-go']) return {...base, gate: 'rough', value: 0, evidence: 'Moderate', reasons};
  const raw = day.comfort === COMFORT_WORD.go ? 1 : day.comfort === COMFORT_WORD.marginal ? 0.5 : null;
  if (raw === null) return {...base, gate: 'pass', value: null, evidence: 'Insufficient', reasons};
  if (day.models_agree === false) reasons.push('forecast models disagree');
  return {...base, gate: 'pass', value: day.models_agree === false ? round(raw * weights.models_disagree, 2) : raw,
    evidence: day.models_agree === true ? 'Moderate' : 'Low', reasons};
}

export interface BuildInput {
  region: Region; intel: unknown; daily: unknown; grounds: readonly Ground[]; targets: readonly TargetIn[];
  dates: readonly string[]; now: number; weights?: Weights;
}

/** The score file for every ground x date x block. Rows a gate closes, or with a part missing, keep their reasons and rank null. */
export function buildScores(input: BuildInput): ScoreFile {
  const {region, intel, daily, grounds, targets, dates, now} = input;
  const weights = input.weights ?? WEIGHTS_V1;
  const tz = region.timezone, zones = regionZones(region), clock = forecastClock(intel, now);
  const checked = advisoryCheckTime((daily as {sources?: Record<string, unknown>} | null)?.sources, zones) !== null;
  const habitat = new Map(grounds.map(g => [g.ground_id, habitatFit(g, targets)] as const));
  const rows: ScoreRow[] = [];
  for (const date of dates) for (const block of BLOCKS) {
    const window = {start: block.start, end: block.end};
    const [from, to] = windowEpochs(date, tz, window);
    if (to < now) continue;   // a block whose last hour has ended is not a bet (windowEpochs' end is the last millisecond of the end hour)
    const advisories = daily ? advisoriesFrom(daily as never, zones, from, to) : [];
    const byPoint = new Map<string, ConditionsPart>();
    for (const g of grounds) {
      if (!byPoint.has(g.point)) {
        const day = withForecastClock(windowConditions(intel as never, region, g.point, date, window, null, advisories, checked), clock);
        byPoint.set(g.point, conditionsFit(day, weights, advisories[0]?.event ?? null));
      }
      const c = byPoint.get(g.point)!, h = habitat.get(g.ground_id)!;
      const open = c.gate === 'pass' && c.value !== null && h.value !== null;
      rows.push({area: g.name, ground_id: g.ground_id, point: g.point, date, block: block.id, gate: c.gate, conditions: c, habitat: h,
        rank: open ? round(weights.conditions * c.value! + weights.habitat * h.value!) : null, evidence: weakest(c.evidence, h.evidence)});
    }
  }
  const run = (intel as {completed_at?: unknown} | null)?.completed_at;
  return {
    schema_version: SCORE_SCHEMA, weights_version: weights.version, region_id: region.id, mode: 'boat', group: 'reef', species: [...REEF],
    generated_at: new Date(now).toISOString(), forecast_issued: typeof run === 'string' ? run : null, forecast_age_hours: clock.ageHours,
    advisories_checked: checked,
    method: 'rank = conditions fit (comfort for a mid-size center console, 3-hour block) and habitat fit (mapped reef structure); never a catch probability',
    limitations: ['no recent catch evidence yet', 'season and rules not checked here (get_rules)', 'harbor bar not judged here (get_conditions)', 'boat mode only'],
    rows,
  };
}

/** The best `n` open rows (rank high to low; ties: earlier date, earlier block, then name), optionally for some dates only. */
export function bestBets(file: ScoreFile, opts: {dates?: readonly string[]; n?: number} = {}): ScoreRow[] {
  const order = new Map(BLOCKS.map((b, i) => [b.id as string, i] as const));
  return file.rows.filter(r => r.rank !== null && (!opts.dates || opts.dates.includes(r.date)))
    .sort((a, b) => b.rank! - a.rank! || a.date.localeCompare(b.date) || order.get(a.block)! - order.get(b.block)! || a.area.localeCompare(b.area))
    .slice(0, opts.n ?? 3);
}
