// What of the charter fleet registry may be shown in public (docs/plans/charter-fleet/
// design.md § 13, § 17). One place for the rules every public surface shares, so the
// profile (/boats/<slug>), /go/<slug> and later the directory and planner cannot drift:
//
//   - a vessel is public only while `status='active' AND profile_status='listed'` and no
//     removal was ever requested (removal_requested_at stays set when an admin unhides it);
//   - a fact is displayable only when its rights allow display (never `internal-only` or
//     `noaa-planning-only`), its confidence is at least 0.6, it is current (not
//     superseded) and it did not come from AIS (no AIS data on any public page);
//   - a stored link is displayable only when it is a plain https URL (safeTarget) and a
//     displayable fact for that field carries exactly that value.
import {safeTarget} from './go.ts';

/** Rights compatible with public display; `internal-only` and `noaa-planning-only` are not. */
export const DISPLAY_RIGHTS: readonly string[] = Object.freeze(['public-domain', 'facts-only', 'public-record', 'api-terms']);
export const MIN_DISPLAY_CONFIDENCE = 0.6;
/** Google rating and review count: shown only while the fact is this fresh (design § 5 Retention). */
export const GOOGLE_WINDOW_DAYS = 30;

/** SQL condition on fleet_vessels (columns qualified by `alias` when given) for a vessel that may appear in public. */
export const publicVesselSql = (alias = ''): string => {
  const p = alias ? `${alias}.` : '';
  return `${p}status='active' AND ${p}profile_status='listed' AND ${p}removal_requested_at IS NULL`;
};
/** A fleet vessel slug (fleet_vessels.slug, as /go/ accepts it). */
export const FLEET_SLUG = /^[a-z0-9](?:[a-z0-9-]{0,78}[a-z0-9])?$/;

export interface FactRow {
  id: string; field: string; value_json: string; source_url: string; method: string;
  confidence: number; rights: string; retrieved_at: string; superseded_at?: string | null;
}

/** The shared predicate: rights compatible with display, confidence ≥ 0.6, current, not from AIS. */
export function displayableFact(fact: Pick<FactRow, 'rights' | 'confidence' | 'method'> & {superseded_at?: string | null}): boolean {
  return DISPLAY_RIGHTS.includes(fact.rights) && typeof fact.confidence === 'number' && fact.confidence >= MIN_DISPLAY_CONFIDENCE
    && fact.method !== 'ais' && !fact.superseded_at;
}

/** The fact's value, or undefined when value_json does not parse. */
export function factValue(fact: Pick<FactRow, 'value_json'>): unknown {
  try { return JSON.parse(fact.value_json); } catch { return undefined; }
}

/**
 * The shared "displayable link" predicate: `stored` (a fleet_vessels column such as
 * website or booking_url) as a redirect target when it is plain https and a displayable
 * fact for `field` carries the same URL; else null. /go/ may adopt it (CF-34 checks
 * safeTarget only today).
 */
export function displayableLink(stored: unknown, field: string, facts: readonly FactRow[]): URL | null {
  const url = safeTarget(stored);
  if (!url || typeof stored !== 'string') return null;
  return facts.some(f => f.field === field && displayableFact(f) && factValue(f) === stored) ? url : null;
}

/** True while `retrievedAt` is within GOOGLE_WINDOW_DAYS before `now` (and not in the future). */
export function withinGoogleWindow(retrievedAt: string, now: number): boolean {
  const t = Date.parse(retrievedAt);
  return Number.isFinite(t) && t <= now + 5 * 60_000 && now - t <= GOOGLE_WINDOW_DAYS * 86_400_000;
}
