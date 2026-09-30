// Confidence badge and freshness pill states (P4-04, guide §5.5 and §5.8).
//
// Pure mapping from data the app already has to what the badges say. A state
// is only ever derived from a flag the data sets; nothing here upgrades a
// claim. In particular "verified" needs the target's own depth qualification
// (depth_qualified with the full geometry screened on a named datum), fish
// presence is never better than "unknown" (no catch model exists), and a
// terrain grade is an estimate by definition (an uncalibrated rank).
//
// Erasable TypeScript only: the Node tests and dist/*.js modules import it.
import {
  FISH_UNVERIFIED, MAPPED_HABITAT_CANDIDATE, RESEARCH_ONLY_LOCATION, terrainConfidence,
  type Limitation,
} from './disclaimers.ts';

export type BadgeState = 'verified' | 'estimated' | 'unknown';

export interface Badge {
  /** Stable key: 'depth', 'terrain', 'fish'. */
  id: string;
  /** What the badge is about, shown before the state ("Depth"). */
  label: string;
  state: BadgeState;
  /** The one-line "why", shown when the badge is opened. */
  why: Limitation;
}

export const BADGE_MARK: Record<BadgeState, string> = {verified: '✓', estimated: '~', unknown: '?'};
export const BADGE_WORD: Record<BadgeState, string> = {verified: 'Verified', estimated: 'Estimated', unknown: 'Unknown'};

/** The fields of an atlas target the badges read. */
export interface TargetEvidence {
  research_only?: boolean;
  depth_qualified?: boolean;
  center_depth_ft?: number | null;
  vertical_datum?: string | null;
  habitat_grade?: string | null;
  confidence?: string | null;
  evidence_status?: string | null;
  qualification?: {full_geometry_screened?: boolean; native_datum?: string | null; note?: string | null} | null;
}

const UNNAMED_DATUM = /unverified|not recorded|unknown/i;

/** A datum the survey actually names (MLLW, NAVD88), not a placeholder. */
function namedDatum(value: string | null | undefined): boolean {
  return typeof value === 'string' && value.trim() !== '' && !UNNAMED_DATUM.test(value);
}

/** Depth: verified only for a depth-qualified target screened on a named datum. */
export function depthBadge(t: TargetEvidence, datumLabel?: string): Badge {
  const base = {id: 'depth', label: 'Depth'};
  if (typeof t.center_depth_ft !== 'number' || !Number.isFinite(t.center_depth_ft))
    return {...base, state: 'unknown', why: {text: 'No survey depth is recorded at this target.'}};
  if (t.research_only) return {...base, state: 'estimated', why: RESEARCH_ONLY_LOCATION};
  const q = t.qualification;
  if (t.depth_qualified === true && q?.full_geometry_screened === true
      && namedDatum(t.vertical_datum) && (q.native_datum == null || q.native_datum === t.vertical_datum)
      && typeof q.note === 'string' && q.note)
    return {...base, state: 'verified', why: {text: q.note}};
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

export type PillState = 'fresh' | 'stale' | 'unavailable';
export interface Pill { state: PillState; label: string }

/** What live-conditions.js freshness() returns for one reading. */
export interface Reading {
  /** Observation time, epoch ms (NaN when there is none). */
  epoch: number;
  fresh: boolean;
  /** freshness() label: "4 min ago", "Stale", "Unavailable", "Update unavailable", "Check source time". */
  label: string;
  /** When the reading was judged, epoch ms. */
  now: number;
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
 * "Buoy unavailable"). The state comes from freshness() as is: this only
 * words it, so a stale or unavailable reading can never read as fresh.
 */
export function freshnessPill(r: Reading, source = 'Buoy'): Pill {
  if (r.fresh) return {state: 'fresh', label: `${source} ${r.label}`};
  if (r.label === 'Stale' && Number.isFinite(r.epoch)) return {state: 'stale', label: `${source} stale ${ageText(r.now - r.epoch)}`};
  return {state: 'unavailable', label: `${source} ${r.label.charAt(0).toLowerCase()}${r.label.slice(1)}`};
}
