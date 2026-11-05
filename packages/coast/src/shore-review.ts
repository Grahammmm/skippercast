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

/** The target-detail evidence line. Dated runs keep their exact wording; absent clocks say "not yet reviewed", never a date. */
export function shoreEvidence(p: ShoreReviewProps): string {
  const access = p.checkedAt === null ? 'Access inventory not yet reviewed.' : 'Access inventory checked ' + new Date(p.checkedAt as string).toLocaleDateString() + '.';
  const legal = p.legalReviewExpiresAt === null ? 'legal review: not yet reviewed.' : 'the prior legal review expired ' + new Date(p.legalReviewExpiresAt as string).toLocaleDateString() + '.';
  return 'Original NOAA shoreline vertices; no offshore depth or species fit inferred. Physical context only. ' + access + ' Current legal/access conditions require rechecking; ' + legal;
}
