// Shore-run priority and guidance (FE-36). Review dates are historical context:
// they never set Hold or Recheck soon. Source publication visibility remains a
// separate gate in shoreShown; the importer still rejects closed/nonpublic access.
//
// - Blocked (0): a current protected-area check finds the run or an access point inside.
// - Hold (0): the protected-area check is not current.
// - No surf model (2): no fresh nearshore model sample covers the area.
// - Current (3): the protected-area check and nearshore sample are current.
// The rank orders places to check, not legal permission or a prediction of fish.
//
// Erasable syntax only: tests/test_shore.mjs imports it by type stripping.

/** The official CDFW regional rules map (the link packages/coast's methods page gives). */
export const CDFW_RULES_URL = 'https://wildlife.ca.gov/Fishing/Ocean/Regulations/Fishing-Map';

export type ShorePriority = 0 | 2 | 3;
export type ShoreLabel = 'Blocked' | 'Hold' | 'No surf model' | 'Current';

/** The original run review dates (schemas/shore-habitat.schema.json `run.properties`). */
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
  /** Plain reasons for the checks that set the label. */
  readonly reasons: readonly string[];
}

const time = (s: string): number => { const t = Date.parse(s); return Number.isFinite(t) ? t : -Infinity; };
const day = (s: string): string => Number.isFinite(Date.parse(s))
  ? new Date(s).toLocaleDateString('en-US', {month: 'short', day: 'numeric', year: 'numeric', timeZone: 'America/Los_Angeles'}) : 'date unknown';

/** Whether the run may be shown at all: its source review has not expired (the terrain's own rule). */
export const shoreShown = (run: Pick<ShoreRunClocks, 'reviewExpiresAt'>, now: number): boolean => time(run.reviewExpiresAt) > now;

/** The run's priority and label at `now`. */
export function shoreStatus(_run: ShoreRunClocks, {now, inside, conditions}: ShoreInputs): ShoreStatus {
  if (inside && inside.length) return {priority: 0, label: 'Blocked', reasons: [`Inside ${inside.join('; ')}`]};
  if (!inside) return {priority: 0, label: 'Hold', reasons: ['Protected-area check not current']};
  if (!conditions) return {priority: 2, label: 'No surf model', reasons: ['No fresh nearshore model sample for this area']};
  return {priority: 3, label: 'Current', reasons: ['Protected-area check current; a fresh nearshore model sample covers this area']};
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
