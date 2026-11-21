import type {AnalysisAlert} from './analysis-alerts.ts';

type AlertPolicyResult = {
  due: AnalysisAlert[];
  held: {alert: AnalysisAlert; reason: 'bad-clock' | 'no-zone' | 'sent-today'}[];
};

type RegionDay = {format: Intl.DateTimeFormat; today: string};

// A numeric offset must follow a clock, not be mistaken for part of a bare date.
const EXPLICIT_ZONE = /(?:\dZ\b|\d:\d{1,2}(?::\d{1,2}(?:\.\d+)?)?\s*[+-]\d{1,4}(?::\d{2})?\b|\b(?:Z|UT|UTC|GMT|[ECMP][SD]T)\b)/i;

function hasExplicitZone(text: string): boolean {
  // Legacy date strings can contain nested comments, which Date.parse ignores.
  let depth = 0;
  return EXPLICIT_ZONE.test(text.replace(/[()]|[^()]+/g, part => {
    if (part === '(') depth++;
    else if (part === ')') depth--;
    else if (depth === 0) return part;
    return ' ';
  }));
}

function readSent(row: unknown) {
  if (row === null || typeof row !== 'object') return;
  try {
    const {owner, region, layer, sentAt} = row as Record<string, unknown>;
    if (typeof owner !== 'string' || typeof region !== 'string' ||
        typeof layer !== 'string' || typeof sentAt !== 'string') return;
    const at = Date.parse(sentAt);
    if (!Number.isFinite(at) || !hasExplicitZone(sentAt)) return;
    return {owner, region, layer, at};
  } catch {
    // An unreadable row is malformed, not a delivery receipt.
  }
}

function clockTime(now: Date): number {
  try {
    return Date.prototype.getTime.call(now);
  } catch {
    return NaN;
  }
}

function regionDay(region: string, at: number, zoneOf: (region: string) => string | null): RegionDay | null {
  try {
    const timeZone = zoneOf(region);
    if (timeZone === null) return null;
    const format = new Intl.DateTimeFormat('en-CA', {
      timeZone, calendar: 'gregory', era: 'short', year: 'numeric', month: 'numeric', day: 'numeric',
    });
    return {format, today: format.format(at)};
  } catch {
    // A failed lookup or rejected time zone cannot establish a local day.
    return null;
  }
}

function alertKey({owner, region, layer}: Pick<AnalysisAlert, 'owner' | 'region' | 'layer'>): string {
  return JSON.stringify([owner, region, layer]);
}

/** Decide which publication candidates may be delivered; no delivery is performed here. */
export function dueAnalysisAlerts(
  candidates: readonly AnalysisAlert[],
  sent: readonly unknown[],
  now: Date,
  zoneOf: (region: string) => string | null,
): AlertPolicyResult {
  const at = clockTime(now);
  if (!Number.isFinite(at)) return {due: [], held: candidates.map(alert => ({alert, reason: 'bad-clock'}))};

  const days = new Map<string, RegionDay | null>();
  for (const {region} of candidates) {
    if (!days.has(region)) days.set(region, regionDay(region, at, zoneOf));
  }

  const seen = new Set<string>();
  for (const row of sent) {
    const receipt = readSent(row);
    if (!receipt) continue;
    const day = days.get(receipt.region);
    if (day && day.format.format(receipt.at) === day.today) seen.add(alertKey(receipt));
  }

  const result: AlertPolicyResult = {due: [], held: []};
  for (const alert of candidates) {
    if (!days.get(alert.region)) {
      result.held.push({alert, reason: 'no-zone'});
      continue;
    }
    const key = alertKey(alert);
    if (seen.has(key)) result.held.push({alert, reason: 'sent-today'});
    else {
      seen.add(key);
      result.due.push(alert);
    }
  }
  return result;
}
