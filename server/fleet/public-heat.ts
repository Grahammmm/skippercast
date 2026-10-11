// GET /api/fleet/public/heat — the public charter-fleet heat map (docs/plans/charter-fleet/design.md
// § 14, § 15 pick 1; N6, #469 D21): aggregate cells only, never a boat, pin, track, port or class.
//
// Anonymous: mounted with the public routes (routes/public.ts), ahead of the private gate, and
// limited per IP on PUBLIC_LIMITER like /go/<slug>. It answers 404 unless both FLEET_ENABLED and
// FLEET_PUBLIC_HEAT_ENABLED are "true"; every other /api/fleet/public/* path is always 404.
//
// Query: region (required), kind (one fishing mode), season (a year), season_part (omitted: the
// whole-season cells, season_part NULL, so a dwell is never counted twice), limit (<= 5,000), cursor.
// Only module 'grid' cells. The floors (PUBLIC_HEAT) are applied in SQL and checked again here:
//   - vessels_n >= 3 distinct vessels;
//   - the cell's last_date (a local calendar date) wholly at least 72 h old in any time zone, so a
//     cell holds nothing newer than 72 h (publicCutoffDate);
//   - rights in an allowlist, so internal-only (aisstream today) and noaa-planning-only
//     (MarineCadastre, D9) cells never appear. The server has no paid tier, so "off paid surfaces"
//     means off this route (§ 15). While aisstream stays internal-only this route returns no cells.
// Each feature is a Polygon ring with exactly kind, season, season_part, dwell_min, vessels_n,
// basis and computed_at: no id, cell id, event count, first date, rights or source.
import type {Context, MiddlewareHandler} from 'hono';
import {json} from '../http.ts';
import {fleetSettings} from './settings.ts';
import {BASIS, CAPS, FISHING_KINDS, REGION, SEASON, TOKEN, cellRing, cellSize, decodeCursor, encodeCursor} from './map.ts';
import type {AppEnv} from '../env.ts';

export const PUBLIC_HEAT = Object.freeze({
  min_vessels: 3,
  delay_hours: 72,
  rights: Object.freeze(['public-domain', 'public-record', 'facts-only', 'api-terms'] as const),
});
const HOUR_MS = 3_600_000;
const DATE_SPAN_HOURS = 36;   // a local date ends at most 36 h after its UTC midnight (UTC-12)
const NOT_FOUND = (): Response => json({error: 'Not found'}, 404);

/** The latest last_date a public cell may carry at `nowMs`: every instant of it is >= delay_hours ago. */
export function publicCutoffDate(nowMs: number): string {
  return new Date(nowMs - (PUBLIC_HEAT.delay_hours + DATE_SPAN_HOURS) * HOUR_MS).toISOString().slice(0, 10);
}

export interface PublicHeatQuery {region: string; kind: string | null; season: string | null; season_part: string | null; limit: number; cursor: string[] | null}

/** Parse and validate a public heat query; an error string for anything malformed. */
export function publicHeatQuery(params: Record<string, string | undefined>): PublicHeatQuery | {error: string} {
  const region = params.region ?? '';
  if (!REGION.test(region)) return {error: 'region is required'};
  const kind = params.kind || null, season = params.season || null, season_part = params.season_part || null;
  if (kind && !(FISHING_KINDS as readonly string[]).includes(kind)) return {error: 'invalid kind'};
  if (season && !SEASON.test(season)) return {error: 'season must be a year'};
  if (season_part && !TOKEN.test(season_part)) return {error: 'invalid season_part'};
  const limit = params.limit === undefined || params.limit === '' ? CAPS.heat : Number(params.limit);
  if (!Number.isInteger(limit) || limit < 1 || limit > CAPS.heat) return {error: `limit must be 1-${CAPS.heat}`};
  const cursor = params.cursor ? decodeCursor(params.cursor, ['n', 's']) : null;
  if (params.cursor && !cursor) return {error: 'invalid cursor'};
  return {region, kind, season, season_part, limit, cursor};
}

type Row = {id: string; cell_id: string; params_json: string; lat: number; lon: number; kind: string; season: string; season_part: string | null;
  dwell_min: number; vessels_n: number; last_date: string | null; rights: string; computed_at: string};

/** True when a row clears every public floor (the re-check of the SQL filter). */
export function publicCell(row: Pick<Row, 'vessels_n' | 'last_date' | 'rights'>, cutoff: string): boolean {
  return Number.isInteger(row.vessels_n) && row.vessels_n >= PUBLIC_HEAT.min_vessels && typeof row.last_date === 'string' &&
    row.last_date <= cutoff && (PUBLIC_HEAT.rights as readonly string[]).includes(row.rights);
}

/** One page of public heat cells, most dwell first. */
export async function publicHeat(db: D1Database, q: PublicHeatQuery, nowMs: number): Promise<Record<string, unknown>> {
  const cutoff = publicCutoffDate(nowMs), rights = PUBLIC_HEAT.rights;
  const where = [`region=? AND module='grid' AND vessels_n>=? AND last_date IS NOT NULL AND last_date<=? AND rights IN (${rights.map(() => '?').join(',')})`];
  const args: (string | number)[] = [q.region, PUBLIC_HEAT.min_vessels, cutoff, ...rights];
  if (q.kind) { where.push('kind=?'); args.push(q.kind); }
  if (q.season) { where.push('season=?'); args.push(q.season); }
  if (q.season_part) { where.push('season_part=?'); args.push(q.season_part); } else where.push('season_part IS NULL');
  if (q.cursor) { where.push('(dwell_min<? OR (dwell_min=? AND id>?))'); args.push(Number(q.cursor[0]), Number(q.cursor[0]), q.cursor[1]!); }
  const rows = (await db.prepare(`SELECT id, cell_id, params_json, lat, lon, kind, season, season_part, dwell_min, vessels_n, last_date, rights, computed_at
    FROM fleet_aggregates WHERE ${where.join(' AND ')} ORDER BY dwell_min DESC, id ASC LIMIT ?`).bind(...args, q.limit + 1).all<Row>()).results;
  const capped = rows.length > q.limit, shown = rows.slice(0, q.limit), last = shown.at(-1);
  const sizes = new Set<number>();
  const features = shown.filter(r => publicCell(r, cutoff)).map(r => {
    const size = cellSize(r.cell_id, r.params_json);
    sizes.add(size);
    return {type: 'Feature', geometry: {type: 'Polygon', coordinates: [cellRing(r.lat, r.lon, size)]}, properties: {
      kind: r.kind, season: r.season, season_part: r.season_part, dwell_min: r.dwell_min, vessels_n: r.vessels_n, basis: BASIS, computed_at: r.computed_at}};
  });
  return {type: 'FeatureCollection', features, meta: {region: q.region, cell_m: [...sizes].sort((a, b) => a - b),
    min_vessels: PUBLIC_HEAT.min_vessels, delay_hours: PUBLIC_HEAT.delay_hours, count: features.length, capped,
    next: capped && last ? encodeCursor([last.dwell_min, last.id]) : null}};
}

/** 404 unless FLEET_ENABLED and FLEET_PUBLIC_HEAT_ENABLED; runs before the rate limit. */
export const publicHeatGate: MiddlewareHandler<AppEnv> = async (c, next) => {
  const settings = fleetSettings(c.env);
  if (!settings.enabled || !settings.publicHeatEnabled) return NOT_FOUND();
  await next();
};

/** GET /api/fleet/public/heat, behind publicHeatGate and PUBLIC_LIMITER (routes/public.ts). */
export async function publicHeatRoute(c: Context<AppEnv>): Promise<Response> {
  if (!c.env.DB) return json({error: 'This service is temporarily unavailable.'}, 503);
  const q = publicHeatQuery(c.req.query());
  if ('error' in q) return json({error: q.error}, 400);
  return json(await publicHeat(c.env.DB, q, Date.now()));
}
