// Catch-log pairing (US-B4; docs/plans/charter-fleet/design.md § 5 `fleet_trip_reports`, § 6):
// pairs AIS trips with the reports for the same boat and day. Run by POST
// /api/fleet/jobs/activity (server/fleet/activity.ts), in the same D1 batch as the trips:
//
//   advisor  a published advisor_reports row whose boat is linked to the trip's vessel
//            (advisor_boats.fleet_vessel_id, set only by an admin) with report_date equal to
//            the trip's local_date: match 'boat-date', confidence 0.9. Paired for the request's
//            own trips and in the sweep; a pairing whose report is no longer published or
//            whose link changed is removed by the sweep.
//   landing  a row of a coastal region's daily feed (`reports[]`, parsers.charter_reports():
//            id, date, boat, port) whose boat name, normalised as fleet name_norm, is the
//            name_norm or an alias_norm of exactly one vessel of the region, whose port is a
//            landing name of the trip's port (catalog/advisor/port-aliases.json) and whose
//            date is the trip's local_date: match 'alias-port-date', confidence 0.8,
//            report_ref the feed row id. Paired only in the sweep.
//
// The sweep runs with `processed`, which the processor sends once at the end of each
// scheduled run, after all of that run's trips: it covers the region's trips of the last
// SWEEP_DAYS days (the daily feed keeps 30 days of reports), so a report published after
// its trip was written still pairs. Feeds come from R2 when bound (readFeed); a feed that
// cannot be read skips only its ports' landing pairs. Every write is INSERT OR IGNORE on
// (trip_id, report_kind, report_ref), so a re-run leaves the same rows. Pairing never
// changes the trips or their events: species attribution is a later step.
import homePorts from '../../catalog/home-ports.json' with {type: 'json'};
import portAliases from '../../catalog/advisor/port-aliases.json' with {type: 'json'};
import {regions} from '../config.ts';
import {readFeed} from '../feeds.ts';
import type {ExternalJSON} from '../types.ts';

export const SWEEP_DAYS = 31;
export const CONFIDENCE = {advisor: 0.9, landing: 0.8} as const;
/** Test seam: where a daily feed is read from. */
export const pairingDeps: {readFeed: (url: string) => Promise<ExternalJSON>} = {readFeed};

/** A trip condition on fleet_trips t, with its arguments. */
export interface TripScope {sql: string; args: (string | number)[]}
interface LandingRow {id: string; norm: string; port: string; date: string}

const PREFIXES = new Set(['THE', 'M/V', 'F/V', 'M.V.', 'F.V.']);
const ROMAN = /^(?=[IVX]+$)X{0,3}(IX|IV|V?I{0,3})$/, ROMAN_VALUES: Record<string, number> = {I: 1, V: 5, X: 10};

/** fleet name_norm, as src/skippercast/fleet/normalize.py: accents dropped, leading THE/M/V/F/V dropped, a trailing roman numeral as digits, then A-Z and 0-9 only. */
export function nameNorm(name: string): string {
  const tokens = (name || '').normalize('NFKD').replace(/\p{M}/gu, '').toUpperCase().split(/\s+/).filter(Boolean);
  while (tokens.length > 1 && PREFIXES.has(tokens[0]!)) tokens.shift();
  if (tokens.length > 1 && /^[IVX]+\.?$/.test(tokens.at(-1)!)) {
    const roman = tokens.at(-1)!.replace(/[^A-Z]/g, '');
    if (ROMAN.test(roman)) {
      let total = 0;
      [...roman].forEach((c, i) => { const v = ROMAN_VALUES[c]!, next = ROMAN_VALUES[roman[i + 1] ?? ''] ?? 0; total += next > v ? -v : v; });
      tokens[tokens.length - 1] = String(total);
    }
  }
  return tokens.join('').replace(/[^A-Z0-9]/g, '');
}

// Port id -> coastal region (catalog/home-ports.json) and landing label -> port id (port-aliases landing_names).
const portRegion = new Map(homePorts.ports.map(p => [p.id, p.region]));
const landingPort = new Map<string, string>();
for (const [id, port] of Object.entries(portAliases.ports as Record<string, {landing_names?: string[]}>))
  for (const name of port.landing_names ?? []) landingPort.set(name.toLowerCase(), id);

/** Landing rows of the daily feeds of `ports`' regions dated on or after `from`; feeds that fail are counted, not thrown. */
export async function landingRows(ports: Iterable<string>, from: string): Promise<{rows: LandingRow[]; feeds: number; unavailable: number}> {
  const wanted = new Set(ports), urls = new Set<string>();
  for (const port of wanted) { const url = regions[portRegion.get(port) ?? '']?.daily_feed; if (url) urls.add(url); }
  const loaded = await Promise.allSettled([...urls].map(url => pairingDeps.readFeed(url)));
  const rows: LandingRow[] = [], seen = new Set<string>();
  for (const result of loaded) {
    if (result.status !== 'fulfilled' || !Array.isArray(result.value?.reports)) continue;
    for (const r of result.value.reports) {
      const port = typeof r?.port === 'string' ? landingPort.get(r.port.toLowerCase()) : undefined;
      const norm = typeof r?.boat === 'string' ? nameNorm(r.boat) : '';
      if (!port || !wanted.has(port) || !norm || typeof r.id !== 'string' || seen.has(r.id)) continue;
      if (typeof r.date !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(r.date) || r.date < from) continue;
      seen.add(r.id);
      rows.push({id: r.id, norm, port, date: r.date});
    }
  }
  return {rows, feeds: urls.size, unavailable: loaded.filter(r => r.status !== 'fulfilled' || !Array.isArray(r.value?.reports)).length};
}

const ADVISOR_JOIN = `JOIN advisor_boats b ON b.fleet_vessel_id=t.vessel_id
  JOIN advisor_reports r ON r.boat_id=b.id AND r.report_date=t.local_date AND r.status='published'`;
const INSERT = 'INSERT OR IGNORE INTO fleet_trip_reports(trip_id,report_kind,report_ref,match,confidence,created_at)';
// One report pairs with at most one trip: of the vessel's trips that day, the one with the most fishing time, then the earliest.
const ONE_TRIP = 'ORDER BY t.fishing_min DESC, t.departed_at, t.id';
const ADVISOR_RANKED = `SELECT t.id trip_id, r.id report_id, ROW_NUMBER() OVER (PARTITION BY r.id ${ONE_TRIP}) rn FROM fleet_trips t ${ADVISOR_JOIN}`;

/** The statement pairing the trips in `scope` with published advisor reports of their linked boat and day (each report to one trip). */
export const advisorPairs = (db: D1Database, scope: TripScope, now: string): D1PreparedStatement =>
  db.prepare(`${INSERT} SELECT x.trip_id,'advisor',x.report_id,'boat-date',?,? FROM (${ADVISOR_RANKED}) x
    WHERE x.rn=1 AND x.trip_id IN (SELECT t.id FROM fleet_trips t WHERE ${scope.sql})`)
    .bind(CONFIDENCE.advisor, now, ...scope.args);

/** The statement removing advisor pairings of the trips in `scope` whose report is unpublished, whose boat link changed or whose report now pairs with another trip. */
export const advisorPrune = (db: D1Database, scope: TripScope): D1PreparedStatement =>
  db.prepare(`DELETE FROM fleet_trip_reports WHERE report_kind='advisor' AND trip_id IN (SELECT t.id FROM fleet_trips t WHERE ${scope.sql})
    AND NOT EXISTS (SELECT 1 FROM (${ADVISOR_RANKED}) x WHERE x.rn=1 AND x.trip_id=fleet_trip_reports.trip_id AND x.report_id=fleet_trip_reports.report_ref)`).bind(...scope.args);

const LANDING_CHUNK = 2000;   // feed rows per statement (one JSON parameter, well under D1's 2 MB value limit)

/** Statements pairing the trips of `region` in `scope` with `rows`; a name that fits two of the region's vessels pairs nothing, and a report pairs with one trip. */
export function landingPairs(db: D1Database, region: string, scope: TripScope, rows: LandingRow[], now: string): D1PreparedStatement[] {
  const out: D1PreparedStatement[] = [];
  for (let i = 0; i < rows.length; i += LANDING_CHUNK) out.push(db.prepare(`${INSERT}
    WITH l AS (SELECT json_extract(value,'$.id') id, json_extract(value,'$.norm') norm, json_extract(value,'$.port') port,
        json_extract(value,'$.date') date FROM json_each(?)),
      names AS (SELECT id vessel_id, name_norm norm FROM fleet_vessels WHERE region=?
        UNION SELECT a.vessel_id, a.alias_norm FROM fleet_aliases a JOIN fleet_vessels v ON v.id=a.vessel_id WHERE v.region=?),
      hits AS (SELECT l.id, l.port, l.date, n.vessel_id FROM l JOIN names n ON n.norm=l.norm),
      sole AS (SELECT id FROM hits GROUP BY id HAVING COUNT(DISTINCT vessel_id)=1)
    SELECT x.trip_id,'landing',x.id,'alias-port-date',?,? FROM (
      SELECT t.id trip_id, h.id, ROW_NUMBER() OVER (PARTITION BY h.id ${ONE_TRIP}) rn
      FROM hits h JOIN sole s ON s.id=h.id
      JOIN fleet_trips t ON t.vessel_id=h.vessel_id AND t.local_date=h.date AND h.port IN (t.depart_port_id,t.return_port_id)) x
    WHERE x.rn=1 AND x.trip_id IN (SELECT t.id FROM fleet_trips t WHERE ${scope.sql})`).bind(JSON.stringify(rows.slice(i, i + LANDING_CHUNK)), region, region, CONFIDENCE.landing, now, ...scope.args));
  return out;
}
