// BF-catch-log: the signed-in person's own private effort log. A blank is a first-class outcome.
// Read and written only here and in the owner's /api/privacy export; coordinates are never shared,
// and nothing in this file feeds a public route, feed, score or aggregate.
import {Hono} from 'hono';
import {json, body, db} from '../http.ts';
import {ClientError} from '../errors.ts';
import type {AppEnv} from '../env.ts';

export const catchLog = new Hono<AppEnv>();
export const OUTCOMES = ['fish', 'blank', 'unknown'] as const;
const MAX_COUNT = 9999, NOTE_CHARS = 1000, LIST_LIMIT = 200;
const ISO = /^\d{4}-\d\d-\d\dT\d\d:\d\d(:\d\d(\.\d{1,3})?)?(Z|[+-]\d\d:\d\d)$/;
const notFound = () => json({error: 'Not found'}, 404);

/** An optional short text: absent or null is null; a non-string or an over-long one is refused by name. */
function text(v: unknown, name: string, max: number): string | null {
  if (v === undefined || v === null) return null;
  if (typeof v !== 'string' || [...v].length > max) throw new ClientError(`${name} must be text of at most ${max} characters`);
  return v.trim() ? v : null;
}
function when(v: unknown, name: string): string | null {
  if (v === undefined || v === null) return null;
  if (typeof v !== 'string' || !ISO.test(v) || Number.isNaN(Date.parse(v))) throw new ClientError(`${name} must be an ISO date and time with a zone`);
  return new Date(v).toISOString();
}
/** Both coordinates or neither. Finite numbers strictly inside the poles and the antimeridian; stored as entered. */
export function coordinates(lat: unknown, lon: unknown): {lat: number; lon: number} | null {
  const none = (v: unknown) => v === undefined || v === null;
  if (none(lat) && none(lon)) return null;
  if (none(lat) || none(lon)) throw new ClientError('coordinates_incomplete: send latitude and longitude together or neither');
  if (typeof lat !== 'number' || typeof lon !== 'number' || !Number.isFinite(lat) || !Number.isFinite(lon)) throw new ClientError('coordinates_not_finite: latitude and longitude must be finite numbers');
  if (!(lat > -90 && lat < 90) || !(lon > -180 && lon < 180)) throw new ClientError('coordinates_out_of_range: latitude must be between -90 and 90 and longitude between -180 and 180, both exclusive');
  return {lat, lon};
}

export function validateLogEntry(input: Record<string, unknown>) {
  const outcome = input.outcome;
  if (typeof outcome !== 'string' || !(OUTCOMES as readonly string[]).includes(outcome)) throw new ClientError('outcome must be fish, blank or unknown');
  const count = input.count === undefined || input.count === null ? 0 : input.count;
  if (typeof count !== 'number' || !Number.isInteger(count) || count < 0 || count > MAX_COUNT) throw new ClientError(`count must be a whole number from 0 to ${MAX_COUNT}`);
  // A blank is stored as a blank with a zero count; a count only goes with fish.
  if (outcome === 'fish' && count < 1) throw new ClientError('a fish entry needs a count of at least 1');
  if (outcome !== 'fish' && count !== 0) throw new ClientError(`a ${outcome} entry has a count of 0`);
  const started_at = when(input.started_at, 'started_at'), ended_at = when(input.ended_at, 'ended_at');
  if (!started_at) throw new ClientError('started_at is required');
  if (ended_at && ended_at < started_at) throw new ClientError('ended_at is before started_at');
  const trip_id = text(input.trip_id, 'trip_id', 64), c = coordinates(input.lat, input.lon);
  return {trip_id, started_at, ended_at, method: text(input.method, 'method', 40), species: text(input.species, 'species', 60), outcome, count, lat: c?.lat ?? null, lon: c?.lon ?? null, note: text(input.note, 'note', NOTE_CHARS)};
}

catchLog.get('/api/catch-log', async c => {
  const rows = (await db(c.env).prepare('SELECT * FROM catch_log WHERE owner=? ORDER BY started_at DESC, id LIMIT ?').bind(c.var.owner, LIST_LIMIT).all()).results;
  return json({entries: rows});
});
// Another account's id answers exactly what an id that never existed answers.
catchLog.get('/api/catch-log/:id', async c => {
  const row = await db(c.env).prepare('SELECT * FROM catch_log WHERE id=? AND owner=?').bind(c.req.param('id'), c.var.owner).first();
  return row ? json(row) : notFound();
});
catchLog.post('/api/catch-log', async c => {
  const owner = c.var.owner, d = db(c.env), e = validateLogEntry(await body(c.req.raw, 4096 + NOTE_CHARS * 4));
  if (e.trip_id && !await d.prepare('SELECT 1 AS ok FROM trips WHERE id=? AND owner=?').bind(e.trip_id, owner).first()) return notFound();
  const id = crypto.randomUUID(), created_at = new Date().toISOString();
  await d.prepare('INSERT INTO catch_log(id,owner,trip_id,started_at,ended_at,method,species,outcome,count,lat,lon,note,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)')
    .bind(id, owner, e.trip_id, e.started_at, e.ended_at, e.method, e.species, e.outcome, e.count, e.lat, e.lon, e.note, created_at).run();
  return json({id, owner, ...e, created_at}, 201);
});
catchLog.delete('/api/catch-log/:id', async c => {
  const done = await db(c.env).prepare('DELETE FROM catch_log WHERE id=? AND owner=?').bind(c.req.param('id'), c.var.owner).run();
  return done.meta.changes ? json({deleted: true}) : notFound();
});
