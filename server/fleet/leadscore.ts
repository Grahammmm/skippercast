// The outreach lead score (docs/plans/charter-fleet/design.md § 13, US-S2; CF-32):
// 0-100 from the weights in catalog/fleet/lead-score.json, bundled at build. Each
// part is scored 0-1, weighted and scaled; the admin shows the parts and which
// inputs were missing (a missing input counts as zero). Computed on read from D1, so
// a weight change takes effect on the next deploy and nothing stale is stored.
//
//   landing_report_volume  trips of the operator's vessels paired with a landing report
//                          in the last 365 days (fleet_trip_reports), full marks at 100
//   reporting_frequency    weeks of the last 12 with a paired report of any kind, of 12
//   social_presence        a current social.* fact from the operator's own site (operator-site)
//   ais_seen_30d           a watched MMSI of the operator's vessels seen in the last 30 days
//
// Missing: no paired report at all (pairing not run, or not a reporter) for the first
// two; no current operator-site fact (site not read) for social; no watched MMSI for AIS.
import catalog from '../../catalog/fleet/lead-score.json' with {type: 'json'};

export const LEAD_PARTS = ['landing_report_volume', 'reporting_frequency', 'social_presence', 'ais_seen_30d'] as const;
export type LeadPart = typeof LEAD_PARTS[number];
/** Raw inputs per part; null is a missing input. */
export type LeadInputs = Record<LeadPart, number | null>;
export const LEAD_WINDOWS = {volumeDays: 365, volumeFull: 100, frequencyWeeks: 12, aisDays: 30} as const;

const UNIT: Record<LeadPart, (raw: number) => number> = {
  landing_report_volume: n => Math.min(1, n / LEAD_WINDOWS.volumeFull),
  reporting_frequency: n => Math.min(1, n / LEAD_WINDOWS.frequencyWeeks),
  social_presence: n => n > 0 ? 1 : 0,
  ais_seen_30d: n => n > 0 ? 1 : 0,
};

export interface LeadPartScore {part: LeadPart; weight: number; raw: number | null; value: number; points: number; missing: boolean}
export interface LeadScore {score: number; parts: LeadPartScore[]; missing: LeadPart[]}

const WEIGHTS = catalog.weights as Record<string, number>;
for (const part of LEAD_PARTS) if (typeof WEIGHTS[part] !== 'number') throw new Error(`catalog/fleet/lead-score.json: no weight for ${part}`);

const round1 = (n: number): number => Math.round(n * 10) / 10;

/** The score of one operator's inputs: 0-100, with each part's weight, raw input, 0-1 value and points. */
export function leadScore(inputs: LeadInputs, weights: Record<string, number> = WEIGHTS, scale: number = catalog.scale): LeadScore {
  const parts = LEAD_PARTS.map(part => {
    const raw = inputs[part], weight = weights[part] ?? 0;
    const value = raw === null ? 0 : UNIT[part](Math.max(0, raw));
    return {part, weight, raw, value: Math.round(value * 100) / 100, points: round1(value * weight * scale), missing: raw === null};
  });
  const total = parts.reduce((sum, p) => sum + p.points, 0);
  return {score: Math.round(Math.min(scale, total)), parts, missing: parts.filter(p => p.missing).map(p => p.part)};
}

const day = (ms: number): string => new Date(ms).toISOString().slice(0, 10);

/**
 * The inputs for every operator matching `scope` (an SQL condition on fleet_operators o,
 * with its arguments), keyed by operator id; operators with no data get all-null inputs.
 */
export async function leadInputs(db: D1Database, scope: {sql: string; args: (string | number)[]}, now: string): Promise<Map<string, LeadInputs>> {
  const t = Date.parse(now), today = day(t);
  const volumeFrom = day(t - LEAD_WINDOWS.volumeDays * 86400e3), weeksFrom = day(t - LEAD_WINDOWS.frequencyWeeks * 7 * 86400e3);
  const aisFrom = new Date(t - LEAD_WINDOWS.aisDays * 86400e3).toISOString();
  const ops = `SELECT o.id FROM fleet_operators o WHERE ${scope.sql}`;
  const [reports, social, ais, ids] = await Promise.all([
    db.prepare(`SELECT v.operator_id AS op,
        COUNT(DISTINCT CASE WHEN r.report_kind='landing' AND t.local_date>=? THEN t.id END) AS volume,
        COUNT(DISTINCT CASE WHEN t.local_date>=? THEN CAST((julianday(?)-julianday(t.local_date))/7 AS INTEGER) END) AS weeks
      FROM fleet_trip_reports r JOIN fleet_trips t ON t.id=r.trip_id JOIN fleet_vessels v ON v.id=t.vessel_id
      WHERE v.operator_id IN (${ops}) GROUP BY v.operator_id`).bind(volumeFrom, weeksFrom, today, ...scope.args).all<{op: string; volume: number; weeks: number}>(),
    db.prepare(`SELECT v.operator_id AS op, MAX(f.field LIKE 'social.%') AS social FROM fleet_vessel_facts f JOIN fleet_vessels v ON v.id=f.vessel_id
      WHERE f.source_id='operator-site' AND f.superseded_at IS NULL AND v.operator_id IN (${ops}) GROUP BY v.operator_id`).bind(...scope.args).all<{op: string; social: number}>(),
    db.prepare(`SELECT v.operator_id AS op, MAX(w.last_seen_at>=?) AS seen FROM fleet_ais_watch w JOIN fleet_vessels v ON v.id=w.vessel_id
      WHERE w.status='watched' AND v.operator_id IN (${ops}) GROUP BY v.operator_id`).bind(aisFrom, ...scope.args).all<{op: string; seen: number}>(),
    db.prepare(ops).bind(...scope.args).all<{id: string}>(),
  ]);
  const out = new Map<string, LeadInputs>(ids.results.map(r => [r.id, {landing_report_volume: null, reporting_frequency: null, social_presence: null, ais_seen_30d: null}]));
  for (const r of reports.results) { const i = out.get(r.op); if (i) { i.landing_report_volume = r.volume; i.reporting_frequency = r.weeks; } }
  for (const r of social.results) { const i = out.get(r.op); if (i) i.social_presence = r.social ? 1 : 0; }
  for (const r of ais.results) { const i = out.get(r.op); if (i) i.ais_seen_30d = r.seen ? 1 : 0; }
  return out;
}
