// Shore-run priority and guidance (FE-36). Review dates are historical context:
// they never set Hold or Recheck soon. Source publication visibility remains a
// separate gate in shoreShown; the importer still rejects closed/nonpublic access.
//
// - Blocked (0): a current protected-area check finds the run or an access point inside.
// - Hold (0): the protected-area check is not current, the marine alert check is not current
//   (packages/coast daily.ts: `nws-alerts` fetched OK within 2 h), a marine alert for the area
//   is in effect or starts within a day, or the county posts a beach-health advisory, closure or
//   warning for the area (#422: the original Fish shore rules hold for both).
// - No surf model (2): no fresh nearshore model sample covers the area.
// - Current (3): the protected-area check and nearshore sample are current.
// The rank orders places to check, not legal permission or a prediction of fish.
//
// Erasable syntax only: tests/test_shore.mjs imports it by type stripping.

import type {StringId} from '../i18n.ts';
import {cp, type MarkCopyPart} from '../mark-copy.ts';
import {DEFAULT_ZONE} from '../zone.ts';

/** The official CDFW regional rules map (the link packages/coast's methods page gives). */
export const CDFW_RULES_URL = 'https://wildlife.ca.gov/Fishing/Ocean/Regulations/Fishing-Map';

export type ShorePriority = 0 | 2 | 3;
export type ShoreLabel = 'Blocked' | 'Hold' | 'No surf model' | 'Current';

/**
 * The run review dates (schemas/shore-habitat.schema.json `run.properties`). A run that has never been reviewed
 * carries null for both ends of a pair: that is "not yet reviewed", not expired, and no date is borrowed for it.
 */
export interface ShoreRunClocks {
  readonly reviewExpiresAt: string | null;
  readonly accessReviewedAt: string | null;
  readonly accessReviewExpiresAt: string | null;
  readonly legalReviewedAt: string | null;
  readonly legalReviewExpiresAt: string | null;
  readonly checkedAt: string | null;
}

export interface ShoreInputs {
  readonly now: number;
  /** Protected areas the run or its access points lie in; null while the protected-area check is not current. */
  readonly inside: readonly string[] | null;
  /** True when a fresh nearshore model sample covers the run's area. */
  readonly conditions: boolean;
  /** False while the marine alert check is not current (`alertCheckCurrent`); then no alert list can be trusted. */
  readonly alertCheck?: boolean;
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

// A null clock is handled before any Date is built: Date.parse(null) is NaN and new Date(null) is the epoch.
const time = (s: string | null): number => { const t = typeof s === 'string' ? Date.parse(s) : NaN; return Number.isFinite(t) ? t : -Infinity; };
const day = (s: string | null, timeZone: string = DEFAULT_ZONE): string => typeof s === 'string' && Number.isFinite(Date.parse(s))
  ? new Date(s).toLocaleDateString('en-US', {month: 'short', day: 'numeric', year: 'numeric', timeZone}) : 'date unknown';

/** Whether the run may be shown at all: its source review has not expired (the terrain's own rule). A never-reviewed run is not shown. */
export const shoreShown = (run: Pick<ShoreRunClocks, 'reviewExpiresAt'>, now: number): boolean => time(run.reviewExpiresAt) > now;

/** True when the run's source review pair is null: no owner review has happened yet (a review state, not an expiry). */
export const shoreNeverReviewed = (run: Pick<ShoreRunClocks, 'checkedAt' | 'reviewExpiresAt'>): boolean => run.checkedAt === null && run.reviewExpiresAt === null;

/** "1 shore run not yet reviewed is not shown"; empty when there is none. */
export const unreviewedNote = (count: number): string =>
  count > 0 ? `${count} shore run${count === 1 ? '' : 's'} not yet reviewed ${count === 1 ? 'is' : 'are'} not shown.` : '';

/** The run's priority and label at `now`. */
export function shoreStatus(_run: ShoreRunClocks, {now, inside, conditions, alertCheck = true, alerts = [], notices = []}: ShoreInputs): ShoreStatus {
  if (inside && inside.length) return {priority: 0, label: 'Blocked', reasons: [`Inside ${inside.join('; ')}`]};
  const held = [
    ...(inside ? [] : ['Protected-area check not current']),
    ...(alertCheck ? [] : ['Marine alert check not current']),
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

/** packages/coast daily.ts' rule: the `nws-alerts` source fetched OK within 2 h (1 h of clock skew). */
export function alertCheckCurrent(report: ShoreReportPart, now: number): boolean {
  const source = report.sources.find(item => item.id === 'nws-alerts');
  const age = source ? now - Date.parse(source.fetchedAt) : NaN;
  return source?.outcome === 'ok' && Number.isFinite(age) && age >= -HOUR && age <= 2 * HOUR;
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

/**
 * The next threshold at or after `now` at which a hold input can change on its own: an alert expiring or
 * entering the day ahead, the alert check passing 2 h, or the beach-health source passing 3 h. A threshold
 * equal to `now` is kept: the strict comparisons (`effective < now + 24 h`, `age <= 2 h`) only flip just
 * after it, so the caller re-checks a moment later. Null when none is ahead.
 */
export function nextShoreChange(report: ShoreReportPart & {readonly alerts?: readonly ShoreAlert[]}, now: number): number | null {
  const at = (s: string | null | undefined, plus = 0): number => { const t = s ? Date.parse(s) : NaN; return Number.isFinite(t) ? t + plus : NaN; };
  const fetched = (id: string, maxAge: number) => at(report.sources.find(item => item.id === id)?.fetchedAt, maxAge);
  const times = [
    ...(report.alerts ?? []).flatMap(a => [at(a.expires), at(a.effective, -24 * HOUR)]),
    fetched('nws-alerts', 2 * HOUR), fetched(BEACH_HEALTH_SOURCE, BEACH_HEALTH_MAX_AGE_MS),
  ].filter(t => Number.isFinite(t) && t >= now);
  return times.length ? Math.min(...times) : null;
}

/** "review until Oct 10, 2026", or "review expired Oct 10, 2026" once that date has passed: a lapsed review is said, never shown as current. */
const until = (expires: string | null, now: number, tz: string): string =>
  typeof expires === 'string' && Number.isFinite(Date.parse(expires)) ? `review ${time(expires) > now ? 'until' : 'expired'} ${day(expires, tz)}` : 'review date unknown';

/** The review dates the card shows at `now`, as calendar days in `tz` (the region's zone; Pacific by default). Expiry compares instants, never zones. */
export function shoreReviewLines(run: ShoreRunClocks, now = Date.now(), tz: string = DEFAULT_ZONE): string {
  // Only a pair that is null at both ends says "not yet reviewed"; a one-sided or malformed pair stays "date unknown".
  const none = (a: string | null, b: string | null): boolean => a === null && b === null;
  const access = none(run.accessReviewedAt, run.accessReviewExpiresAt) ? 'Access not yet reviewed' : `Access checked ${day(run.accessReviewedAt, tz)}, ${until(run.accessReviewExpiresAt, now, tz)}`;
  const rules = none(run.legalReviewedAt, run.legalReviewExpiresAt) ? 'rules not yet reviewed' : `rules checked ${day(run.legalReviewedAt, tz)}, ${until(run.legalReviewExpiresAt, now, tz)}`;
  const source = none(run.checkedAt, run.reviewExpiresAt) ? 'source not yet reviewed' : `source ${until(run.reviewExpiresAt, now, tz)}`;
  return `${access} · ${rules} · ${source}`;
}

export interface ShoreGuidance {readonly text: string; readonly href: string; readonly label: string}

const CHECKS = 'Before you go, check the current CDFW rules for this area, the access point\'s posted status, the surf and the county\'s beach water-quality status.';
/** Method guidance for the shore target and the run's substrate (sand or rocky), with the official rules link. It describes how to check a run, not what it holds. */
export function shoreGuidance(target: string, substrate: string = 'sand'): ShoreGuidance {
  const lead = substrate === 'rocky'
    ? target === 'surfperch'
      ? 'Surfperch: a rocky-shore surf method; the run marks historical rocky shore to look along.'
      : target === 'halibut'
        ? 'California halibut: usually a sandy-bottom fish; the run marks historical rocky shore, so look at sand pockets beside it, and size and bag limits apply.'
        : 'The run marks historical rocky shore to look along.'
    : substrate !== 'sand' ? 'The run marks historical shore to look along.'
    : target === 'surfperch'
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

// SC1352-08: display-only wording for the card. Everything above stays the English decision and API; these
// helpers build catalogue parts from the SAME inputs, never from the translated or English label text, and
// the card resolves them in the page's language at render.
const sid = (key: string): StringId => `mark.layer.shore.${key}` as StringId;
const STATUS_ID: Readonly<Record<ShoreLabel, string>> = {Blocked: 'status.blocked', Hold: 'status.hold', 'No surf model': 'status.noModel', Current: 'status.current'};
/** The catalogue part for a canonical status label; null for any other value (a legacy or hand-built label stays as it is). */
export const shoreLabelCopy = (label: string): MarkCopyPart | null => Object.hasOwn(STATUS_ID, label) ? cp(sid(STATUS_ID[label as ShoreLabel])) : null;

export interface ShoreStatusCopy {readonly reasons: readonly MarkCopyPart[]}
/**
 * The reasons of `status` as catalogue parts, joined by the card with "; ". Rebuilt from the inputs `shoreStatus` was
 * given, in its order; null when the inputs do not reproduce the status (then the reasons stay as written).
 */
export function shoreStatusCopy({inside, alertCheck = true, alerts = [], notices = []}: Pick<ShoreInputs, 'inside' | 'alertCheck' | 'alerts' | 'notices'>, status: ShoreStatus): ShoreStatusCopy | null {
  let reasons: MarkCopyPart[];
  if (status.label === 'Blocked') reasons = [cp(sid('reason.inside'), {areas: (inside ?? []).join('; ')})];
  else if (status.label === 'Hold') {
    reasons = [
      ...(inside ? [] : [cp(sid('reason.mpaNotCurrent'))]), ...(alertCheck ? [] : [cp(sid('reason.alertNotCurrent'))]),
      ...alerts.map(event => cp(sid('reason.alert'), {event})), ...notices.map(name => cp(sid('reason.notice'), {name})),
    ];
  } else if (status.label === 'No surf model') reasons = [cp(sid('reason.noSample'))];
  else if (status.label === 'Current') reasons = [cp(sid('reason.current'))];
  else return null;
  return reasons.length === status.reasons.length ? {reasons} : null;
}

const esDay = (s: string | null, timeZone: string): string => typeof s === 'string' && Number.isFinite(Date.parse(s))
  ? new Date(s).toLocaleDateString('es', {month: 'short', day: 'numeric', year: 'numeric', timeZone}) : '';
const untilCopy = (expires: string | null, now: number, tz: string): MarkCopyPart =>
  typeof expires === 'string' && Number.isFinite(Date.parse(expires)) ? cp(sid(time(expires) > now ? 'review.until' : 'review.expired'), {date: esDay(expires, tz)}) : cp(sid('review.unknown'));
const dayCopy = (s: string | null, tz: string): MarkCopyPart | string => esDay(s, tz) || cp(sid('review.dateUnknown'));

/** `shoreReviewLines` as catalogue parts: the same pairs, order, expiry comparison and zone; the dates in Spanish. */
export function shoreReviewCopy(run: ShoreRunClocks, now = Date.now(), tz: string = DEFAULT_ZONE): MarkCopyPart[] {
  const none = (a: string | null, b: string | null): boolean => a === null && b === null;
  return [
    ...(none(run.accessReviewedAt, run.accessReviewExpiresAt) ? [cp(sid('review.accessNone'))] : [cp(sid('review.access'), {date: dayCopy(run.accessReviewedAt, tz), until: untilCopy(run.accessReviewExpiresAt, now, tz)})]),
    ' · ',
    ...(none(run.legalReviewedAt, run.legalReviewExpiresAt) ? [cp(sid('review.rulesNone'))] : [cp(sid('review.rules'), {date: dayCopy(run.legalReviewedAt, tz), until: untilCopy(run.legalReviewExpiresAt, now, tz)})]),
    ' · ',
    ...(none(run.checkedAt, run.reviewExpiresAt) ? [cp(sid('review.sourceNone'))] : [cp(sid('review.source'), {until: untilCopy(run.reviewExpiresAt, now, tz)})]),
  ];
}

/** `shoreGuidance`'s text and link label as catalogue parts: the same seven lead branches, then the unverified statement and the checks. */
export function shoreGuidanceCopy(target: string, substrate: string = 'sand'): {readonly text: readonly MarkCopyPart[]; readonly label: readonly MarkCopyPart[]} {
  const lead = substrate === 'rocky' ? (target === 'surfperch' ? 'lead.rockySurfperch' : target === 'halibut' ? 'lead.rockyHalibut' : 'lead.rocky')
    : substrate !== 'sand' ? 'lead.unknown' : target === 'surfperch' ? 'lead.sandySurfperch' : target === 'halibut' ? 'lead.sandyHalibut' : 'lead.sandy';
  return {text: [cp(sid(lead)), ' ', cp(sid('unverified')), ' ', cp(sid('checks'))], label: [cp(sid('regsLabel'))]};
}
