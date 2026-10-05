// GET /api/admin/fleet/clicks?days=7|30|90&region= — /go/ redirect counts for the
// admin (docs/plans/charter-fleet/design.md § 12, D15; CF-34). Read from the daily
// fleet_link_clicks counters only; there is nothing per visitor to read. Counts
// are raw redirects, not visitors: they are not deduplicated (threat model § 10.1),
// so a figure shown to an operator must say so.
import type {Target, Placement} from '../go.ts';
import {TARGETS, PLACEMENTS, utcDay} from '../go.ts';

export const CLICK_DAYS = [7, 30, 90] as const;
export type ClickDays = typeof CLICK_DAYS[number];
const REGION = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?$/;
const MAX_VESSELS = 200;

type Counts = Record<Target, number> & {total: number};
export interface VesselClicks extends Counts {vessel_id: string; slug: string | null; name: string | null; region: string | null; placements: Record<Placement, number>}
export interface ClickReport {
  days: ClickDays; since: string; until: string; region: string | null;
  unit: 'redirects';   // raw /go/ redirects, not visitors
  totals: Counts & {placements: Record<Placement, number>};
  daily: {day: string; count: number}[];
  vessels: VesselClicks[];
}

const zero = <K extends string>(keys: readonly K[]): Record<K, number> => Object.fromEntries(keys.map(k => [k, 0])) as Record<K, number>;
const counts = (): Counts => ({...zero(TARGETS), total: 0});

/** Parse ?days= (default 30) and ?region=; an error string for anything else. */
export function clickQuery(days: string | undefined, region: string | undefined): {days: ClickDays; region: string | null} | {error: string} {
  const d = Number(days || 30);
  if (!(CLICK_DAYS as readonly number[]).includes(d)) return {error: 'days must be 7, 30 or 90'};
  if (region && !REGION.test(region)) return {error: 'invalid region'};
  return {days: d as ClickDays, region: region || null};
}

/** Counts for the `days` UTC days ending today, by vessel, target and placement, most clicked first. */
export async function clickReport(db: D1Database, days: ClickDays, region: string | null, now: Date): Promise<ClickReport> {
  const until = utcDay(now), since = utcDay(new Date(now.getTime() - (days - 1) * 86_400_000));
  const where = 'c.day>=? AND c.day<=?' + (region ? ' AND v.region=?' : '');
  const args = region ? [since, until, region] : [since, until];
  const rows = (await db.prepare(`SELECT c.vessel_id, v.slug, v.name, v.region, c.target, c.placement, SUM(c.count) AS n
    FROM fleet_link_clicks c LEFT JOIN fleet_vessels v ON v.id=c.vessel_id WHERE ${where}
    GROUP BY c.vessel_id, c.target, c.placement`).bind(...args).all<{vessel_id: string; slug: string | null; name: string | null; region: string | null; target: string; placement: string; n: number}>()).results;
  const daily = (await db.prepare(`SELECT c.day AS day, SUM(c.count) AS count FROM fleet_link_clicks c LEFT JOIN fleet_vessels v ON v.id=c.vessel_id
    WHERE ${where} GROUP BY c.day ORDER BY c.day`).bind(...args).all<{day: string; count: number}>()).results;

  const totals = {...counts(), placements: zero(PLACEMENTS)};
  const byVessel = new Map<string, VesselClicks>();
  for (const row of rows) {
    const n = Number(row.n) || 0;
    const target = (TARGETS as readonly string[]).includes(row.target) ? row.target as Target : null;
    const placement = (PLACEMENTS as readonly string[]).includes(row.placement) ? row.placement as Placement : 'other';
    let vessel = byVessel.get(row.vessel_id);
    if (!vessel) byVessel.set(row.vessel_id, vessel = {vessel_id: row.vessel_id, slug: row.slug, name: row.name, region: row.region, ...counts(), placements: zero(PLACEMENTS)});
    if (target) { vessel[target] += n; totals[target] += n; }
    vessel.total += n; vessel.placements[placement] += n;
    totals.total += n; totals.placements[placement] += n;
  }
  const vessels = [...byVessel.values()].sort((a, b) => b.total - a.total || a.vessel_id.localeCompare(b.vessel_id)).slice(0, MAX_VESSELS);
  return {days, since, until, region, unit: 'redirects', totals, daily: daily.map(d => ({day: d.day, count: Number(d.count) || 0})), vessels};
}
