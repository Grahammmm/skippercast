// Review presentation for shore runs (SC1952-08). A run that has never been reviewed carries null review
// clocks; that is a state of its own: not current, not expired, and never a date. Pure and offline: the 3D
// viewer imports it, and tests/coast/shore-review.test.ts runs it without WebGL or network.
// A malformed non-null clock stays "unknown" (withheld like any unparseable date), never "not yet reviewed".

export type ShoreClock = string | null | undefined;
export type SourceReview = 'unreviewed' | 'current' | 'expired' | 'unknown';

export interface ShoreReviewProps {
  readonly substrate?: string;
  readonly checkedAt?: ShoreClock;
  readonly reviewExpiresAt?: ShoreClock;
  readonly legalReviewExpiresAt?: ShoreClock;
}

/** Where a run's source review stands at `now`; only an explicit null is "never reviewed". */
export function sourceReview(expiresAt: ShoreClock, now: number): SourceReview {
  if (expiresAt === null) return 'unreviewed';
  const t = typeof expiresAt === 'string' ? Date.parse(expiresAt) : NaN;
  return Number.isFinite(t) ? (t > now ? 'current' : 'expired') : 'unknown';
}

/** Splits shore features into those the viewer may draw (source review still current) and a count of never-reviewed runs. */
export function admitShore<T extends {readonly geometry?: {readonly type?: string}; readonly properties?: ShoreReviewProps}>(features: readonly T[], now: number): {readonly shown: T[]; readonly unreviewed: number} {
  const lines = features.filter(f => f.geometry?.type === 'MultiLineString');
  return {
    shown: lines.filter(f => sourceReview(f.properties?.reviewExpiresAt, now) === 'current'),
    unreviewed: lines.filter(f => sourceReview(f.properties?.reviewExpiresAt, now) === 'unreviewed').length,
  };
}

/** "sandy-shore", "rocky-shore", or plain "shore" when the shown runs mix substrates. */
export function shoreContext(substrates: Iterable<string | undefined>): string {
  const kinds = new Set([...substrates].map(s => s === 'rocky' ? 'rocky' : 'sandy'));
  return kinds.size > 1 ? 'shore' : `${[...kinds][0] ?? 'sandy'}-shore`;
}

/** The withheld-context sentence appended to the shore status; empty when nothing is unreviewed. */
export function unreviewedStatus(count: number): string {
  return count > 0 ? ` ${count} shore run${count === 1 ? '' : 's'} not yet reviewed ${count === 1 ? 'is' : 'are'} withheld.` : '';
}

function shoreEvidenceDate(clock: ShoreClock): string | undefined {
  if (typeof clock !== 'string') return undefined;
  const day = clock.slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return undefined;

  // Date parsing can roll an impossible calendar day into the next month.
  const calendar = new Date(`${day}T00:00:00Z`);
  if (!Number.isFinite(calendar.getTime()) || calendar.toISOString().slice(0, 10) !== day) return undefined;
  if (clock === day) {
    const monthDay = calendar.toLocaleDateString('en-US', {timeZone: 'UTC', month: 'short', day: 'numeric'});
    return `${monthDay}, ${day.slice(0, 4)}`;
  }

  // Only a zoned instant has a well-defined Los Angeles day.
  if (!/^T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})$/.test(clock.slice(10))) return undefined;
  const instant = new Date(clock);
  if (!Number.isFinite(instant.getTime())) return undefined;
  return instant.toLocaleDateString('en-US', {timeZone: 'America/Los_Angeles', month: 'short', day: 'numeric', year: 'numeric'});
}

/** The target-detail evidence line distinguishes never-reviewed clocks from unknown dates. */
export function shoreEvidence(p: ShoreReviewProps): string {
  const accessDate = shoreEvidenceDate(p.checkedAt);
  const legalDate = shoreEvidenceDate(p.legalReviewExpiresAt);
  const access = p.checkedAt === null ? 'Access inventory not yet reviewed.'
    : accessDate === undefined ? 'Access inventory check date unknown.' : `Access inventory checked ${accessDate}.`;
  const legal = p.legalReviewExpiresAt === null ? 'legal review: not yet reviewed.'
    : legalDate === undefined ? 'legal review date unknown.' : `the prior legal review expired ${legalDate}.`;
  return 'Original NOAA shoreline vertices; no offshore depth or species fit inferred. Physical context only. ' + access + ' Current legal/access conditions require rechecking; ' + legal;
}
