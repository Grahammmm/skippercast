// Confidence badge and freshness pill states (P4-04, guide §5.5 and §5.8).
//
// Pure mapping from data the app already has to what the badges say. A state
// is only ever derived from a flag the data sets; nothing here upgrades a
// claim. In particular "qualified" needs the target's own depth qualification
// (depth_qualified with the full geometry screened on a named datum and a
// stated product uncertainty), and even then it is a measured-depth screen,
// never "verified": the skipper still checks the sounder. Fish
// presence is never better than "unknown" (no catch model exists), and a
// terrain grade is an estimate by definition (an uncalibrated rank).
//
// Erasable TypeScript only: the Node tests and dist/*.js modules import it.
import {
  FISH_UNVERIFIED, MAPPED_HABITAT_CANDIDATE, RESEARCH_ONLY_LOCATION, qualifiedDepth, terrainConfidence,
  type Limitation,
} from './disclaimers.ts';
import {freshness, sourceFresh} from '../dist/live-conditions.js';

export type BadgeState = 'qualified' | 'estimated' | 'unknown';

export interface Badge {
  /** Stable key: 'depth', 'terrain', 'fish'. */
  id: string;
  /** What the badge is about, shown before the state ("Depth"). */
  label: string;
  state: BadgeState;
  /** The one-line "why", shown when the badge is opened. */
  why: Limitation;
  /** Open the why when the sheet opens (research-only depth). */
  open?: boolean;
}

export const BADGE_MARK: Record<BadgeState, string> = {qualified: '✓', estimated: '~', unknown: '?'};
export const BADGE_WORD: Record<BadgeState, string> = {qualified: 'Qualified', estimated: 'Estimated', unknown: 'Unknown'};

/** The fields of an atlas target the badges read. */
export interface TargetEvidence {
  research_only?: boolean;
  depth_qualified?: boolean;
  center_depth_ft?: number | null;
  vertical_datum?: string | null;
  habitat_grade?: string | null;
  confidence?: string | null;
  evidence_status?: string | null;
  qualification?: {
    full_geometry_screened?: boolean; native_datum?: string | null; note?: string | null;
    maximum_product_uncertainty_m?: number | null; planning_margin_m?: number | null;
  } | null;
}

const UNNAMED_DATUM = /unverified|not recorded|unknown/i;

/** A datum the survey actually names (MLLW, NAVD88), not a placeholder. */
function namedDatum(value: string | null | undefined): boolean {
  return typeof value === 'string' && value.trim() !== '' && !UNNAMED_DATUM.test(value);
}

const finite = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n);

/**
 * Depth: qualified only for a depth-qualified target screened over its full
 * geometry on a named datum with a stated product uncertainty. Research-only
 * depth is an estimate and its why opens with the sheet.
 */
export function depthBadge(t: TargetEvidence, datumLabel?: string): Badge {
  const base = {id: 'depth', label: 'Depth'};
  if (!finite(t.center_depth_ft))
    return {...base, state: 'unknown', why: {text: 'No survey depth is recorded at this target.'}};
  // The caveat's lead ("Research-only location.") is the answer line's marker, so the why starts at its text.
  if (t.research_only) return {...base, state: 'estimated', why: {text: RESEARCH_ONLY_LOCATION.text}, open: true};
  const q = t.qualification;
  if (t.depth_qualified === true && q?.full_geometry_screened === true
      && namedDatum(t.vertical_datum) && (q.native_datum == null || q.native_datum === t.vertical_datum)
      && finite(q.maximum_product_uncertainty_m) && q.maximum_product_uncertainty_m >= 0)
    return {...base, state: 'qualified', why: {text: qualifiedDepth(t.vertical_datum!, q.maximum_product_uncertainty_m, q.planning_margin_m)}};
  return {...base, state: 'estimated', why: {text: t.evidence_status || `Vertical datum: ${datumLabel || t.vertical_datum || 'not recorded'}.`}};
}

/** Terrain grade: always an estimate (an uncalibrated habitat rank). */
export function terrainBadge(t: TargetEvidence): Badge {
  const base = {id: 'terrain', label: 'Terrain'};
  if (!t.habitat_grade) return {...base, state: 'unknown', why: {text: 'No terrain grade is recorded at this target.'}};
  return {...base, state: 'estimated', why: {lead: MAPPED_HABITAT_CANDIDATE + '.', text: terrainConfidence(t.confidence || 'not recorded')}};
}

/** Fish: unknown everywhere; no verified catch or calibrated catch model exists. */
export function fishBadge(): Badge {
  return {id: 'fish', label: 'Fish', state: 'unknown', why: FISH_UNVERIFIED};
}

/** The spot sheet's badges, in reading order. */
export function spotBadges(t: TargetEvidence, datumLabel?: string): Badge[] {
  return [depthBadge(t, datumLabel), terrainBadge(t), fishBadge()];
}

/**
 * The answer line's depth: "123 ft" only when the depth badge is qualified,
 * otherwise "~123 ft (estimated)"; null when there is no depth.
 */
export function depthText(t: TargetEvidence, badge: Badge = depthBadge(t)): string | null {
  if (!finite(t.center_depth_ft)) return null;
  return badge.state === 'qualified' ? `${t.center_depth_ft} ft` : `~${t.center_depth_ft} ft (estimated)`;
}

export type PillState = 'fresh' | 'stale' | 'unavailable';
export interface Pill { state: PillState; label: string }

/**
 * One source's latest observation as the feed gave it: the reading time and
 * the feed's own state. The pill judges freshness from these at render time
 * (never a stored label), so a reading that ages on screen turns stale.
 */
export interface Observation {
  /** Station the reading came from (for example NDBC "46011"). */
  station: string;
  /** Observation time, epoch ms (NaN when there is none). */
  epoch: number;
  /** When the feed carrying it was generated, epoch ms (NaN when unknown). */
  feedEpoch: number;
  /** The feed's status for this station ("ok" when the last fetch worked). */
  sourceStatus: string | null;
}

/** "2 h", "3 d", "45 min": how old an observation is. */
export function ageText(ms: number): string {
  const minutes = Math.max(0, Math.floor(ms / 60000));
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return hours < 48 ? `${hours} h` : `${Math.floor(hours / 24)} d`;
}

/**
 * The freshness pill for one source ("Buoy 4 min ago", "Buoy stale 2 h",
 * "Buoy unavailable"), judged by live-conditions.js freshness() at `now`.
 * No observation (the spot's buoy has not loaded or has no reading) is
 * "unavailable": another station's reading is never shown in its place.
 */
export function freshnessPill(o: Observation | null | undefined, now: number, source = 'Buoy'): Pill {
  if (!o) return {state: 'unavailable', label: `${source} unavailable`};
  const r = freshness(o.epoch, now, sourceFresh(o.feedEpoch, o.sourceStatus, now));
  if (r.fresh) return {state: 'fresh', label: `${source} ${r.label}`};
  if (r.label === 'Stale' && Number.isFinite(o.epoch)) return {state: 'stale', label: `${source} stale ${ageText(now - o.epoch)}`};
  return {state: 'unavailable', label: `${source} ${r.label.charAt(0).toLowerCase()}${r.label.slice(1)}`};
}
