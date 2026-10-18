// Shore-run priority and guidance (FE-36). Review dates are historical context:
// they never set Hold or Recheck soon. Source publication visibility remains a
// separate gate in shoreShown; the importer still rejects closed/nonpublic access.
//
// - Blocked (0): a current protected-area check finds the run or an access point inside.
// - Hold (0): the protected-area check is not current, a marine alert for the area is in
//   effect or starts within a day, or the county posts a beach-health advisory, closure or
//   warning for the area (#422: the original Fish shore rules hold for both).
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
  /** Marine alerts for the run's area in effect now or within a day (`activeAlerts`), by event name. */
  readonly alerts?: readonly string[];
  /** The area's beaches under a fresh county advisory, closure or warning (`beachNotices`), by name. */
  readonly notices?: readonly string[];
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
export function shoreStatus(_run: ShoreRunClocks, {now, inside, conditions, alerts = [], notices = []}: ShoreInputs): ShoreStatus {
  if (inside && inside.length) return {priority: 0, label: 'Blocked', reasons: [`Inside ${inside.join('; ')}`]};
  const held = [
    ...(inside ? [] : ['Protected-area check not current']),
    ...alerts.map(event => `Marine alert: ${event}`),
    ...notices.map(name => `Beach-health notice: ${name}`),
  ];
  if (held.length) return {priority: 0, label: 'Hold', reasons: held};
  if (!conditions) return {priority: 2, label: 'No surf model', reasons: ['No fresh nearshore model sample for this area']};
  return {priority: 3, label: 'Current', reasons: ['Protected-area check current; a fresh nearshore model sample covers this area']};
}

const HOUR = 3_600_000;

/** A marine alert as the coast report carries it (packages/coast/src/types.ts `Alert`). */
export interface ShoreAlert {readonly event: string; readonly effective: string | null; readonly expires: string | null; readonly areaIds?: readonly string[]}
/**
 * Alerts for `areaId` in effect at `now` or starting within a day: packages/coast daily.ts
 * `relevantAlerts`' rule over that span. An unparseable clock counts as in effect.
 */
export function activeAlerts(alerts: readonly ShoreAlert[], areaId: string, now: number): ShoreAlert[] {
  return alerts.filter(alert => {
    if (alert.areaIds && !alert.areaIds.includes(areaId)) return false;
    const effective = alert.effective ? Date.parse(alert.effective) : -Infinity, expires = alert.expires ? Date.parse(alert.expires) : Infinity;
    return (Number.isNaN(effective) || effective < now + 24 * HOUR) && (Number.isNaN(expires) || expires > now);
  });
}

/** The county beach-health source (packages/coast enrichment). */
export const BEACH_HEALTH_SOURCE = 'slo-beach-water-quality';
/** A published status that is a notice; "Beach Open" is not. The v1 rule (packages/coast presentation.ts reportPanel, ui/briefing.ts). */
export const BEACH_NOTICE_STATUS = /advisory|closed|warning/i;
const BEACH_HEALTH_MAX_AGE_MS = 3 * HOUR, BEACH_HEALTH_SKEW_MS = 5 * 60_000;
export interface ShoreWaterQuality {readonly areaId?: string; readonly name: string; readonly status: string; readonly advisory?: string | null; readonly url: string}
export interface ShoreReportPart {
  readonly sources: readonly {readonly id: string; readonly outcome: string; readonly fetchedAt: string}[];
  readonly waterQuality?: readonly ShoreWaterQuality[];
}
/**
 * The area's beaches under an advisory, closure or warning, decided as v1 does: from the
 * status, and only while the county source fetched cleanly within 3 h. The advisory text is not
 * the test: the county writes one for open beaches too ("There are no advisory notes at this time.").
 */
export function beachNotices(report: ShoreReportPart, areaId: string, now: number): ShoreWaterQuality[] {
  const health = report.sources.find(item => item.id === BEACH_HEALTH_SOURCE);
  const age = health ? now - Date.parse(health.fetchedAt) : NaN;
  if (health?.outcome !== 'ok' || !(age >= -BEACH_HEALTH_SKEW_MS && age < BEACH_HEALTH_MAX_AGE_MS)) return [];
  return (report.waterQuality ?? []).filter(item => item.areaId === areaId && BEACH_NOTICE_STATUS.test(item.status));
}

/** "review until Oct 10, 2026", or "review expired Oct 10, 2026" once that date has passed: a lapsed review is said, never shown as current. */
const until = (expires: string, now: number): string =>
  Number.isFinite(Date.parse(expires)) ? `review ${time(expires) > now ? 'until' : 'expired'} ${day(expires)}` : 'review date unknown';

/** The review dates the card shows at `now`. */
export function shoreReviewLines(run: ShoreRunClocks, now = Date.now()): string {
  return `Access checked ${day(run.accessReviewedAt)}, ${until(run.accessReviewExpiresAt, now)} · `
    + `rules checked ${day(run.legalReviewedAt)}, ${until(run.legalReviewExpiresAt, now)} · source ${until(run.reviewExpiresAt, now)}`;
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
