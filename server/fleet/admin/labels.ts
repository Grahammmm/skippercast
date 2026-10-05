// Trip labelling for the AIS classifier's validation (docs/plans/charter-fleet/design.md § 11
// Validation, § 13 Labelling, D10; CF-48). The admin functions are mounted in routes/admin.ts
// behind requireUser and requireAdmin (the FLEET_ENABLED gate in routes/fleet.ts runs first);
// the job read is mounted in routes/fleet.ts behind requireFleetJob.
//
//   GET  /api/admin/fleet/trips        ?region= &labelled=all|yes|no &cursor=   newest departure first, PAGE a page,
//                                      with the labelling progress (labelled trips, labels by labeller kind, ports,
//                                      labelled minutes per label) against the 30-trip target
//   GET  /api/admin/fleet/trips/:id    the trip, its vessel, its segments (decoded tracks, mean SOG) and its labels
//   POST /api/admin/fleet/trips/:id/labels   {started_at, ended_at, label, basis}: a hand label of a time range
//   POST /api/admin/fleet/labels/:id/delete  removes one label
//   GET  /api/fleet/jobs/labels        ?region= &cursor=   labelled trips with their labels, by trip id, for
//                                      `python -m skippercast.fleet.ais validate` (src/skippercast/fleet/ais/validate.py)
//
// A label is a time range of one trip marked in-port, transit, fishing-drift or fishing-troll,
// with its basis (what the labeller went on: the track's shape, a skipper's log, a landing
// report...). `labeller` records who: the admin's users.id; an agent-labelled set carries
// `agent:<name>` and is counted apart so the owner can review and approve it. Ranges of one
// trip never overlap, so every labelled minute has one truth. Labels are keyed by trip id
// and time and survive reprocessing (fleet/activity.ts never touches them).
//
// Everything the view shows of a trip besides the labels is inferred from movement: segment
// kinds, speeds and fishing minutes are the classifier's output (D10), never confirmed fishing.
// Raw positions never reach D1; the processor's runner copies a labelled trip's raw positions
// to <FLEET_VAR>/<region>/ais/validation/ on its next run, where retention never reaches them,
// and drops the copy once the trip has no label left (design § 5 Retention).
import {decodePolyline} from '../map.ts';
import type {AdminOutcome} from '../../advisor/admin/skippers.ts';

export const LABELS = ['in-port', 'transit', 'fishing-drift', 'fishing-troll'] as const;
export type TripLabel = typeof LABELS[number];
export const BASIS = 'inferred-from-movement';
export const TARGET_TRIPS = 30;
export const PAGE = 50;
export const JOB_PAGE = 90;            // trips a job page; their labels are read in the same request
export const MAX_LABELS = 200;         // labels a trip
export const MAX_BASIS = 500;
const MIN_LABEL_MS = 60_000;           // validation scores whole minutes

const HEX32 = /^[0-9a-f]{32}$/;
const REGION = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?$/;
const ISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,3})?)?Z$/;
const CURSOR = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z)~([0-9a-f]{32})$/;
const FILTERS = ['all', 'yes', 'no'] as const;

const newId = (): string => [...crypto.getRandomValues(new Uint8Array(16))].map(b => b.toString(16).padStart(2, '0')).join('');
/** An ISO UTC time with a Z, normalised to milliseconds; null if it is not one. */
export function isoTime(v: unknown): string | null {
  if (typeof v !== 'string' || !ISO.test(v)) return null;
  const t = Date.parse(v);
  return Number.isFinite(t) ? new Date(t).toISOString() : null;
}

export interface TripRow {
  id: string; region: string; vessel_id: string; vessel_name: string | null; vessel_class: string | null; mmsi: string;
  depart_port_id: string | null; return_port_id: string | null; departed_at: string; returned_at: string | null; local_date: string;
  status: string; distance_nm: number | null; fishing_min: number | null; source: string; rights: string; labels: number;
}
export interface LabelRow {id: string; trip_id: string; started_at: string; ended_at: string; label: string; labeller: string; basis: string | null; created_at: string}
export interface Progress {
  trips: number; labels: number; by_labeller: {admin: number; agent: number}; ports: number;
  minutes: Record<TripLabel, number>; target_trips: number;
}
export interface SegmentView {
  id: string; seq: number; kind: string; started_at: string; ended_at: string; points_n: number | null;
  mean_sog: number | null; straightness: number | null; heading_var: number | null; coordinates: [number, number][];
}
export interface TripDetail {
  trip: TripRow & {classifier_version: string; computed_at: string; max_offshore_nm: number | null; positions_n: number | null; gap_min: number | null};
  window: {from: string; to: string};
  segments: SegmentView[]; labels: LabelRow[]; basis: typeof BASIS; label_kinds: readonly string[];
}

const TRIP_COLUMNS = `t.id,t.region,t.vessel_id,v.name AS vessel_name,v.vessel_class,t.mmsi,t.depart_port_id,t.return_port_id,t.departed_at,
  t.returned_at,t.local_date,t.status,t.distance_nm,t.fishing_min,t.source,t.rights,(SELECT count(*) FROM fleet_segment_labels l WHERE l.trip_id=t.id) AS labels`;

/** GET /api/admin/fleet/trips. */
export async function listTrips(db: D1Database, q: {region?: string; labelled?: string; cursor?: string}):
  Promise<{trips: TripRow[]; next: string | null; progress: Progress} | {error: string}> {
  const where: string[] = [], args: string[] = [];
  if (q.region) { if (!REGION.test(q.region)) return {error: 'invalid region'}; where.push('t.region=?'); args.push(q.region); }
  const labelled = q.labelled || 'all';
  if (!(FILTERS as readonly string[]).includes(labelled)) return {error: 'labelled must be all, yes or no'};
  if (labelled !== 'all') where.push(`${labelled === 'no' ? 'NOT ' : ''}EXISTS(SELECT 1 FROM fleet_segment_labels l WHERE l.trip_id=t.id)`);
  if (q.cursor) {
    const m = CURSOR.exec(q.cursor);
    if (!m) return {error: 'invalid cursor'};
    where.push('(t.departed_at<? OR (t.departed_at=? AND t.id<?))'); args.push(m[1]!, m[1]!, m[2]!);
  }
  const rows = (await db.prepare(`SELECT ${TRIP_COLUMNS} FROM fleet_trips t LEFT JOIN fleet_vessels v ON v.id=t.vessel_id
    ${where.length ? 'WHERE ' + where.join(' AND ') : ''} ORDER BY t.departed_at DESC,t.id DESC LIMIT ?`).bind(...args, PAGE + 1).all<TripRow>()).results;
  const page = rows.slice(0, PAGE), last = page[page.length - 1];
  return {trips: page, next: rows.length > PAGE && last ? `${last.departed_at}~${last.id}` : null, progress: await progress(db, q.region || null)};
}

/** Labelled trips, labels by labeller kind, distinct departure ports and labelled minutes per label. */
export async function progress(db: D1Database, region: string | null): Promise<Progress> {
  const filter = region ? 'WHERE t.region=?' : '';
  const args = region ? [region] : [];
  const [totals, minutes] = await Promise.all([
    db.prepare(`SELECT count(DISTINCT l.trip_id) AS trips,count(*) AS labels,SUM(l.labeller LIKE 'agent:%') AS agent,
      count(DISTINCT t.depart_port_id) AS ports FROM fleet_segment_labels l JOIN fleet_trips t ON t.id=l.trip_id ${filter}`).bind(...args)
      .first<{trips: number; labels: number; agent: number | null; ports: number}>(),
    db.prepare(`SELECT l.label,SUM((julianday(l.ended_at)-julianday(l.started_at))*1440) AS minutes FROM fleet_segment_labels l
      JOIN fleet_trips t ON t.id=l.trip_id ${filter} GROUP BY l.label`).bind(...args).all<{label: string; minutes: number}>(),
  ]);
  const labels = Number(totals?.labels) || 0, agent = Number(totals?.agent) || 0;
  const byLabel = Object.fromEntries(LABELS.map(k => [k, 0])) as Record<TripLabel, number>;
  for (const r of minutes.results) if ((LABELS as readonly string[]).includes(r.label)) byLabel[r.label as TripLabel] = Math.round(Number(r.minutes) || 0);
  return {trips: Number(totals?.trips) || 0, labels, by_labeller: {admin: labels - agent, agent}, ports: Number(totals?.ports) || 0,
    minutes: byLabel, target_trips: TARGET_TRIPS};
}

type TripFull = TripDetail['trip'];
const tripRow = (db: D1Database, id: string): Promise<TripFull | null> =>
  HEX32.test(id) ? db.prepare(`SELECT ${TRIP_COLUMNS},t.classifier_version,t.computed_at,t.max_offshore_nm,t.positions_n,t.gap_min
    FROM fleet_trips t LEFT JOIN fleet_vessels v ON v.id=t.vessel_id WHERE t.id=?`).bind(id).first<TripFull>() : Promise.resolve(null);
const labelsOf = async (db: D1Database, tripId: string): Promise<LabelRow[]> =>
  (await db.prepare('SELECT id,trip_id,started_at,ended_at,label,labeller,basis,created_at FROM fleet_segment_labels WHERE trip_id=? ORDER BY started_at,id')
    .bind(tripId).all<LabelRow>()).results;

/** The time a trip may be labelled in: departure to return, else to its last segment's end (an open trip), else its computation. */
function windowOf(trip: TripFull, segments: {ended_at: string}[]): {from: string; to: string} {
  const lastEnd = segments.reduce<string | null>((m, s) => (m === null || s.ended_at > m ? s.ended_at : m), null);
  return {from: trip.departed_at, to: trip.returned_at ?? lastEnd ?? trip.computed_at};
}

/** GET /api/admin/fleet/trips/:id. */
export async function tripDetail(db: D1Database, id: string): Promise<TripDetail | null> {
  const trip = await tripRow(db, id);
  if (!trip) return null;
  const [segments, labels] = await Promise.all([
    db.prepare(`SELECT id,seq,kind,started_at,ended_at,geometry,points_n,mean_sog,straightness,heading_var FROM fleet_segments
      WHERE trip_id=? ORDER BY seq`).bind(id).all<Omit<SegmentView, 'coordinates'> & {geometry: string | null}>(),
    labelsOf(db, id),
  ]);
  const views = segments.results.map(({geometry, ...s}) => ({...s, coordinates: geometry ? decodePolyline(geometry) : []}));
  return {trip, window: windowOf(trip, views), segments: views, labels, basis: BASIS, label_kinds: LABELS};
}

/** POST /api/admin/fleet/trips/:id/labels: the label, by `labeller` (the admin's users.id), and the trip's labels after it. */
export async function addLabel(db: D1Database, tripId: string, input: Record<string, unknown>, labeller: string, now: string):
  Promise<AdminOutcome<{label: LabelRow; labels: LabelRow[]}>> {
  const trip = await tripRow(db, tripId);
  if (!trip) return {status: 'not-found'};
  const extra = Object.keys(input).find(k => !['started_at', 'ended_at', 'label', 'basis'].includes(k));
  if (extra) return {status: 'invalid', error: `unknown field ${extra}`};
  const startedAt = isoTime(input.started_at), endedAt = isoTime(input.ended_at);
  if (!startedAt || !endedAt) return {status: 'invalid', error: 'started_at and ended_at must be ISO UTC times'};
  if (Date.parse(endedAt) - Date.parse(startedAt) < MIN_LABEL_MS) return {status: 'invalid', error: 'a label covers at least one minute'};
  if (typeof input.label !== 'string' || !(LABELS as readonly string[]).includes(input.label)) return {status: 'invalid', error: `label must be one of ${LABELS.join(', ')}`};
  const basis = typeof input.basis === 'string' ? input.basis.trim() : '';
  if (basis.length < 2 || basis.length > MAX_BASIS) return {status: 'invalid', error: `basis is required (2 to ${MAX_BASIS} characters)`};
  if (!labeller) return {status: 'invalid', error: 'no labeller'};
  const segments = (await db.prepare('SELECT ended_at FROM fleet_segments WHERE trip_id=?').bind(tripId).all<{ended_at: string}>()).results;
  const window = windowOf(trip, segments);
  if (startedAt < window.from || endedAt > window.to) return {status: 'invalid', error: `the range must fall within the trip (${window.from} to ${window.to})`};
  const existing = await labelsOf(db, tripId);
  if (existing.length >= MAX_LABELS) return {status: 'conflict', error: `a trip holds at most ${MAX_LABELS} labels`};
  const clash = existing.find(l => l.started_at < endedAt && l.ended_at > startedAt);
  if (clash) return {status: 'conflict', error: `overlaps the ${clash.label} label from ${clash.started_at} to ${clash.ended_at}; delete it first`};
  const label: LabelRow = {id: newId(), trip_id: tripId, started_at: startedAt, ended_at: endedAt, label: input.label, labeller, basis, created_at: now};
  await db.prepare('INSERT INTO fleet_segment_labels(id,trip_id,started_at,ended_at,label,labeller,basis,created_at) VALUES(?,?,?,?,?,?,?,?)')
    .bind(label.id, label.trip_id, label.started_at, label.ended_at, label.label, label.labeller, label.basis, label.created_at).run();
  return {status: 'ok', value: {label, labels: await labelsOf(db, tripId)}};
}

/** POST /api/admin/fleet/labels/:id/delete: the trip's labels after it. */
export async function deleteLabel(db: D1Database, id: string): Promise<AdminOutcome<{deleted: string; trip_id: string; labels: LabelRow[]}>> {
  if (!HEX32.test(id)) return {status: 'not-found'};
  const row = await db.prepare('SELECT trip_id FROM fleet_segment_labels WHERE id=?').bind(id).first<{trip_id: string}>();
  if (!row) return {status: 'not-found'};
  await db.prepare('DELETE FROM fleet_segment_labels WHERE id=?').bind(id).run();
  return {status: 'ok', value: {deleted: id, trip_id: row.trip_id, labels: await labelsOf(db, row.trip_id)}};
}

export interface JobTrip {
  id: string; mmsi: string | null; vessel_id: string | null; source: string | null; departed_at: string | null; returned_at: string | null;
  status: string | null; depart_port_id: string | null; orphan: boolean; labels: Omit<LabelRow, 'trip_id'>[];
}

/**
 * GET /api/fleet/jobs/labels: the region's labelled trips by id, JOB_PAGE a page; `next` is the last id, null after the
 * last page. Labels whose trip a re-run replaced under another id (the trip row is gone, so its region is unknown) come
 * with `orphan: true` and null trip fields on every region's pages: the runner keeps the copy it already holds for them,
 * since raw positions stay exempt from retention while a label exists.
 */
export async function labelledTrips(db: D1Database, region: string | undefined, cursor: string | undefined):
  Promise<{status: number; body: Record<string, unknown>}> {
  if (!region || !REGION.test(region)) return {status: 400, body: {error: 'invalid region'}};
  const after = cursor ?? '';
  if (after !== '' && !HEX32.test(after)) return {status: 400, body: {error: 'invalid cursor'}};
  const ids = (await db.prepare(`SELECT DISTINCT l.trip_id AS id FROM fleet_segment_labels l LEFT JOIN fleet_trips t ON t.id=l.trip_id
    WHERE (t.region=? OR t.id IS NULL) AND l.trip_id>? ORDER BY l.trip_id LIMIT ?`).bind(region, after, JOB_PAGE + 1).all<{id: string}>()).results;
  const page = ids.slice(0, JOB_PAGE).map(r => r.id);
  const byTrip = new Map<string, JobTrip>(page.map(id => [id, {id, mmsi: null, vessel_id: null, source: null, departed_at: null, returned_at: null,
    status: null, depart_port_id: null, orphan: true, labels: []}]));
  if (page.length) {
    const marks = page.map(() => '?').join(',');
    const [trips, labels] = await Promise.all([
      db.prepare(`SELECT id,mmsi,vessel_id,source,departed_at,returned_at,status,depart_port_id FROM fleet_trips WHERE id IN (${marks})`)
        .bind(...page).all<Omit<JobTrip, 'labels' | 'orphan'>>(),
      db.prepare(`SELECT id,trip_id,started_at,ended_at,label,labeller,basis,created_at FROM fleet_segment_labels
        WHERE trip_id IN (${marks}) ORDER BY trip_id,started_at,id`).bind(...page).all<LabelRow>(),
    ]);
    for (const t of trips.results) byTrip.set(t.id, {...t, orphan: false, labels: []});
    for (const {trip_id, ...l} of labels.results) byTrip.get(trip_id)?.labels.push(l);
  }
  return {status: 200, body: {region, trips: [...byTrip.values()], next: ids.length > JOB_PAGE ? page[page.length - 1]! : null}};
}
