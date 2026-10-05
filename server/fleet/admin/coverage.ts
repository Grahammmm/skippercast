// GET /api/admin/fleet/coverage?region= — how complete the registry is (docs/plans/charter-fleet/
// design.md § 13 Coverage, US-O2; CF-35). Read from D1 only: active vessels by region, port
// and class, with boats, completeness by field group, % with an MMSI, % seen in AIS in the
// last 30 days, sources per boat and single-source boats, plus the latest pipeline runs.
//
// AIS presence is reported as "seen" or "not-seen", never as compliance: most six-packs
// carry no transponder and none has to, so a boat with no AIS is only not seen.
// "Seen" means a watched fleet_ais_watch row for the vessel last heard within 30 days.
// Sources count the distinct source_id of the vessel's current (not superseded) facts,
// leaving out admin facts (an admin edit is not a source that found the boat) and AIS facts
// (method 'ais', CF-46: AIS presence is reported separately as seen or not seen).
// Percentages are 0-100 to one decimal, null when there is nothing to divide by.

const REGION = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?$/;
const DAY_MS = 86_400_000;
export const SEEN_DAYS = 30;
const MAX_VESSELS = 5000;
const MAX_SINGLE = 200;
const RUN_LIMIT = 25;

/** The resolver's completeness target columns (src/skippercast/fleet/resolve.py TARGET), grouped for the view. */
export const FIELD_GROUPS = {
  identity: ['vessel_class', 'waters_json', 'port_id', 'landing_id'],
  registry: ['uscg_doc', 'state_reg', 'hull_id', 'call_sign', 'mmsi'],
  specs: ['year_built', 'passengers_max', 'bunks', 'length_ft', 'beam_ft', 'cruise_kn'],
  contact: ['website', 'booking_url', 'booking_platform', 'phone_business', 'email_business'],
} as const;
export type FieldGroup = keyof typeof FIELD_GROUPS;
const GROUPS = Object.keys(FIELD_GROUPS) as FieldGroup[];
const COLUMNS = GROUPS.flatMap(g => FIELD_GROUPS[g] as readonly string[]);

export type AisPresence = 'seen' | 'not-seen';
export interface Cell {
  boats: number;
  mmsi: {n: number; pct: number | null};
  ais: {seen: number; not_seen: number; seen_pct: number | null};
  single_source: number;
  completeness: {mean_pct: number | null; groups: Record<FieldGroup, number | null>};
}
export interface ClassRow extends Cell {vessel_class: string | null}
export interface PortRow extends Cell {region: string; port_id: string | null; classes: ClassRow[]}
export interface SingleSource {id: string; slug: string; name: string; region: string; port_id: string | null; vessel_class: string | null; source_id: string; ais: AisPresence}
export interface RunRow {id: string; region: string; step: string; sink: string; started_at: string; finished_at: string | null; status: string; counts: unknown; error: string | null}
export interface CoverageReport {
  generated_at: string; region: string | null; seen_days: number; seen_since: string;
  groups: typeof FIELD_GROUPS;
  totals: Cell; ports: PortRow[];
  sources_per_boat: {'0': number; '1': number; '2': number; '3+': number};
  single_source: SingleSource[]; truncated: boolean;
  runs: RunRow[];
}

interface VesselRow {id: string; slug: string; name: string; region: string; port_id: string | null; vessel_class: string | null; completeness: number;
  sources: number; source_id: string | null; seen: number; [col: string]: unknown}

/** Percent of n in d, 0-100 to one decimal; null when d is 0. */
export const pct = (n: number, d: number): number | null => d ? Math.round(1000 * n / d) / 10 : null;
const filled = (col: string, value: unknown): boolean =>
  value !== null && value !== undefined && value !== '' && !(col.endsWith('_json') && (value === '[]' || value === 'null'));

/** Parse ?region=; an error string for an invalid one. */
export function coverageQuery(region: string | undefined): {region: string | null} | {error: string} {
  if (region && !REGION.test(region)) return {error: 'invalid region'};
  return {region: region || null};
}

function cell(rows: VesselRow[]): Cell {
  const boats = rows.length;
  const mmsi = rows.filter(v => filled('mmsi', v.mmsi)).length, seen = rows.filter(v => v.seen).length;
  const groups = Object.fromEntries(GROUPS.map(g => {
    const cols = FIELD_GROUPS[g] as readonly string[];
    const n = rows.reduce((sum, v) => sum + cols.filter(c => filled(c, v[c])).length, 0);
    return [g, pct(n, boats * cols.length)];
  })) as Record<FieldGroup, number | null>;
  const mean = boats ? pct(rows.reduce((s, v) => s + (Number(v.completeness) || 0), 0), boats) : null;
  return {
    boats, mmsi: {n: mmsi, pct: pct(mmsi, boats)},
    ais: {seen, not_seen: boats - seen, seen_pct: pct(seen, boats)},
    single_source: rows.filter(v => v.sources === 1).length,
    completeness: {mean_pct: mean, groups},
  };
}

const parse = (text: string | null): unknown => { if (text === null) return null; try { return JSON.parse(text); } catch { return null; } };
// Nulls last, then by name: ports and classes in a stable order.
const byKey = (a: string | null, b: string | null): number => a === b ? 0 : a === null ? 1 : b === null ? -1 : a.localeCompare(b);

/** The coverage report for active vessels (one region, or all), as of `now`. */
export async function coverageReport(db: D1Database, region: string | null, now: Date): Promise<CoverageReport> {
  const since = new Date(now.getTime() - SEEN_DAYS * DAY_MS).toISOString();
  const where = "v.status='active'" + (region ? ' AND v.region=?' : '');
  const facts = "FROM fleet_vessel_facts f WHERE f.vessel_id=v.id AND f.superseded_at IS NULL AND f.source_id<>'admin' AND f.method<>'ais'";
  const rows = (await db.prepare(`SELECT v.id,v.slug,v.name,v.region,v.completeness,${COLUMNS.map(c => 'v.' + c).join(',')},
      (SELECT COUNT(DISTINCT f.source_id) ${facts}) AS sources,
      (SELECT MIN(f.source_id) ${facts}) AS source_id,
      EXISTS (SELECT 1 FROM fleet_ais_watch w WHERE w.vessel_id=v.id AND w.status='watched' AND w.last_seen_at>=?) AS seen
    FROM fleet_vessels v WHERE ${where} ORDER BY v.region,v.port_id,v.vessel_class,v.name_norm,v.id LIMIT ?`)
    .bind(since, ...(region ? [region] : []), MAX_VESSELS + 1).all<VesselRow>()).results;
  const truncated = rows.length > MAX_VESSELS, vessels = rows.slice(0, MAX_VESSELS).map(v => ({...v, sources: Number(v.sources) || 0, seen: Number(v.seen) || 0}));

  const ports = new Map<string, VesselRow[]>();
  for (const v of vessels) {
    const key = JSON.stringify([v.region, v.port_id]);
    ports.set(key, [...(ports.get(key) ?? []), v]);
  }
  const portRows: PortRow[] = [...ports.values()].map(list => {
    const classes = new Map<string | null, VesselRow[]>();
    for (const v of list) classes.set(v.vessel_class, [...(classes.get(v.vessel_class) ?? []), v]);
    return {region: list[0]!.region, port_id: list[0]!.port_id, ...cell(list),
      classes: [...classes.entries()].sort((a, b) => byKey(a[0], b[0])).map(([vessel_class, l]) => ({vessel_class, ...cell(l)}))};
  }).sort((a, b) => a.region.localeCompare(b.region) || byKey(a.port_id, b.port_id));

  const spread = {'0': 0, '1': 0, '2': 0, '3+': 0};
  for (const v of vessels) spread[v.sources >= 3 ? '3+' : String(v.sources) as '0' | '1' | '2']++;
  const single = vessels.filter(v => v.sources === 1).slice(0, MAX_SINGLE).map(v => ({id: v.id, slug: v.slug, name: v.name, region: v.region,
    port_id: v.port_id, vessel_class: v.vessel_class, source_id: v.source_id ?? '', ais: (v.seen ? 'seen' : 'not-seen') as AisPresence}));

  const runs = (await db.prepare(`SELECT id,region,step,sink,started_at,finished_at,status,counts_json,error FROM fleet_runs
    ${region ? 'WHERE region=?' : ''} ORDER BY started_at DESC,id LIMIT ?`).bind(...(region ? [region] : []), RUN_LIMIT)
    .all<Omit<RunRow, 'counts'> & {counts_json: string | null}>()).results;

  return {
    generated_at: now.toISOString(), region, seen_days: SEEN_DAYS, seen_since: since, groups: FIELD_GROUPS,
    totals: cell(vessels), ports: portRows, sources_per_boat: spread, single_source: single, truncated,
    runs: runs.map(({counts_json, ...r}) => ({...r, counts: parse(counts_json)})),
  };
}
