// Shore-run priority and guidance (FE-36, docs/plans/front-end/design.md § 8
// "Where to look" for Shore, § 9 Shore runs). This restates the role of
// `fish`'s src/opportunity.ts from the design's description of it: an ESI
// sandy-shore run is ranked 0–3 by its review clocks (source, access, rules),
// the run-time protected-area check and whether a fresh nearshore model sample
// covers its area. The rank orders places to check; it never says fish are
// there, and no label or line here predicts a catch.
//
// - Blocked (0): the protected-area check is current and the run or one of its
//   access points lies in a protected area.
// - Hold (0): the access or rules review has expired, or the protected-area
//   check is not current. A run past its source review is not shown at all.
// - Recheck soon (1): every clock is current but one expires within 24 hours.
// - No surf model (2): current, but no fresh nearshore model sample for its area.
// - Current (3): current, with a fresh nearshore model sample for its area.
//
// Erasable syntax only: tests/test_shore.mjs imports it by type stripping.

const HOUR = 3_600_000;
/** A review clock that ends within this window drops the run to "Recheck soon". */
export const RECHECK_WINDOW_MS = 24 * HOUR;
/** The official CDFW regional rules map (the link packages/coast's methods page gives). */
export const CDFW_RULES_URL = 'https://wildlife.ca.gov/Fishing/Ocean/Regulations/Fishing-Map';

export type ShorePriority = 0 | 1 | 2 | 3;
export type ShoreLabel = 'Blocked' | 'Hold' | 'Recheck soon' | 'No surf model' | 'Current';

/** The run properties the priority reads (schemas/shore-habitat.schema.json `run.properties`). */
export interface ShoreRunClocks {
  readonly reviewExpiresAt: string;
  readonly accessReviewedAt: string;
  readonly accessReviewExpiresAt: string;
  readonly legalReviewedAt: string;
  readonly legalReviewExpiresAt: string;
  readonly checkedAt: string;
}

export interface ShoreInputs {
  readonly now: number;
  /** Protected areas the run or its access points lie in; null while the protected-area check is not current. */
  readonly inside: readonly string[] | null;
  /** True when a fresh nearshore model sample covers the run's area. */
  readonly conditions: boolean;
}

export interface ShoreStatus {
  readonly priority: ShorePriority;
  readonly label: ShoreLabel;
  /** Plain reasons, one per clock or check that set the label. */
  readonly reasons: readonly string[];
}

const time = (s: string): number => { const t = Date.parse(s); return Number.isFinite(t) ? t : -Infinity; };
const day = (s: string): string => Number.isFinite(Date.parse(s))
  ? new Date(s).toLocaleDateString('en-US', {month: 'short', day: 'numeric', year: 'numeric', timeZone: 'America/Los_Angeles'}) : 'date unknown';

/** Whether the run may be shown at all: its source review has not expired (the terrain's own rule). */
export const shoreShown = (run: Pick<ShoreRunClocks, 'reviewExpiresAt'>, now: number): boolean => time(run.reviewExpiresAt) > now;

/** The run's priority and label at `now`. */
export function shoreStatus(run: ShoreRunClocks, {now, inside, conditions}: ShoreInputs): ShoreStatus {
  if (inside && inside.length) return {priority: 0, label: 'Blocked', reasons: [`Inside ${inside.join('; ')}`]};
  const clocks = [
    {name: 'Access review', end: time(run.accessReviewExpiresAt)},
    {name: 'Rules review', end: time(run.legalReviewExpiresAt)},
    {name: 'Source review', end: time(run.reviewExpiresAt)},
  ];
  const expired = clocks.filter(c => c.end <= now).map(c => `${c.name} expired`);
  if (!inside) expired.push('Protected-area check not current');
  if (expired.length) return {priority: 0, label: 'Hold', reasons: expired};
  const ending = clocks.filter(c => c.end - now <= RECHECK_WINDOW_MS).map(c => `${c.name} ends within 24 h`);
  if (ending.length) return {priority: 1, label: 'Recheck soon', reasons: ending};
  if (!conditions) return {priority: 2, label: 'No surf model', reasons: ['No fresh nearshore model sample for this area']};
  return {priority: 3, label: 'Current', reasons: ['Reviews current; a fresh nearshore model sample covers this area']};
}

/** The review dates the card shows. */
export function shoreReviewLines(run: ShoreRunClocks): string {
  return `Access checked ${day(run.accessReviewedAt)}, review until ${day(run.accessReviewExpiresAt)} · `
    + `rules checked ${day(run.legalReviewedAt)}, review until ${day(run.legalReviewExpiresAt)} · source review until ${day(run.reviewExpiresAt)}`;
}

export interface ShoreGuidance {readonly text: string; readonly href: string; readonly label: string}

const CHECKS = 'Before you go, check the current CDFW rules for this area, the access point\'s posted status, the surf and the county\'s beach water-quality status.';
/** Method guidance for the shore target, with the official rules link. It describes how to check a run, not what it holds. */
export function shoreGuidance(target: string): ShoreGuidance {
  const lead = target === 'surfperch'
    ? 'Surfperch: a sandy-beach surf method; the run marks historical sandy shore to look along.'
    : target === 'halibut'
      ? 'California halibut: a sandy-bottom method; the run marks historical sandy shore to look along, and size and bag limits apply.'
      : 'The run marks historical sandy shore to look along.';
  return {text: `${lead} Fish presence is unverified. ${CHECKS}`, href: CDFW_RULES_URL, label: 'Official CDFW regional rules'};
}

/** Runs in rank order: highest priority first, then by name. */
export function rankRuns<T extends {readonly status: ShoreStatus; readonly name: string}>(runs: readonly T[]): T[] {
  return [...runs].sort((a, b) => b.status.priority - a.status.priority || a.name.localeCompare(b.name));
}
