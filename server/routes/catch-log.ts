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
/** The written calendar day must exist and the written hour must be 00-23: Date.parse alone rolls 02-30 into March and 24:00 into the next day. */
function realWrittenTime(v: string): boolean {
  const year = Number(v.slice(0, 4)), month = Number(v.slice(5, 7)), day = Number(v.slice(8, 10)), hour = Number(v.slice(11, 13));
  // setUTCFullYear, not Date.UTC, so years 0000-0099 are not mapped to 1900-1999.
  const scratch = new Date(0);
  scratch.setUTCFullYear(year, month - 1, day);
  return hour <= 23 && scratch.getUTCFullYear() === year && scratch.getUTCMonth() === month - 1 && scratch.getUTCDate() === day;
}
function when(v: unknown, name: string): string | null {
  if (v === undefined || v === null) return null;
  if (typeof v !== 'string' || !ISO.test(v) || Number.isNaN(Date.parse(v)) || !realWrittenTime(v)) throw new ClientError(`${name} must be an ISO date and time with a zone`);
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

// SC0922-03: a list page is the LIST_LIMIT newest rows; an optional `cursor` continues after the last row returned.
// A cursor is a position (version, started_at, id), not a capability: the list query is always bound to the caller.
const CURSOR_VERSION = 1, CURSOR_CHARS = 512, CANONICAL_TIME = /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/;
const bad = () => new ClientError('invalid catch-log cursor');
const b64url = (bytes: Uint8Array) => btoa(String.fromCharCode(...bytes)).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '');
export const encodeLogCursor = (started_at: string, id: string): string => b64url(new TextEncoder().encode(JSON.stringify([CURSOR_VERSION, started_at, id])));
export function decodeLogCursor(token: string): {started_at: string; id: string} {
  if (!token || token.length > CURSOR_CHARS || !/^[A-Za-z0-9_-]+$/.test(token)) throw bad();
  let parsed: unknown;
  try {
    const raw = atob(token.replaceAll('-', '+').replaceAll('_', '/') + '='.repeat((4 - token.length % 4) % 4));
    const bytes = Uint8Array.from(raw, ch => ch.charCodeAt(0));
    if (b64url(bytes) !== token) throw bad();   // one spelling per position: no stray trailing bits
    parsed = JSON.parse(new TextDecoder('utf-8', {fatal: true, ignoreBOM: false}).decode(bytes));
  } catch { throw bad(); }
  if (!Array.isArray(parsed) || parsed.length !== 3 || parsed[0] !== CURSOR_VERSION) throw bad();
  const [, started_at, id] = parsed;
  if (typeof started_at !== 'string' || !CANONICAL_TIME.test(started_at) || Number.isNaN(Date.parse(started_at)) || new Date(started_at).toISOString() !== started_at) throw bad();
  if (typeof id !== 'string' || !id || id.length > 64 || /[\u0000-\u001f\u007f]/.test(id)) throw bad();
  return {started_at, id};
}

catchLog.get('/api/catch-log', async c => {
  const given = c.req.queries('cursor');
  const after = given === undefined ? null : given.length === 1 ? decodeLogCursor(given[0]!) : (() => { throw bad(); })();
  const where = after ? ' AND (started_at < ? OR (started_at = ? AND id > ?))' : '';
  const args = after ? [c.var.owner, after.started_at, after.started_at, after.id, LIST_LIMIT + 1] : [c.var.owner, LIST_LIMIT + 1];
  const found = (await db(c.env).prepare(`SELECT * FROM catch_log WHERE owner=?${where} ORDER BY started_at DESC, id ASC LIMIT ?`).bind(...args).all()).results as {started_at: string; id: string}[];
  const rows = found.slice(0, LIST_LIMIT), more = found.length > LIST_LIMIT;
  // The body stays {entries}; the page position travels in headers so a caller that sends no cursor sees today's JSON.
  const res = json({entries: rows});
  res.headers.set('X-SC-Catch-Log-Has-More', more ? 'true' : 'false');
  if (more) { const last = rows[rows.length - 1]!; res.headers.set('X-SC-Catch-Log-Next-Cursor', encodeLogCursor(last.started_at, last.id)); }
  return res;
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
// SC1137-10: PATCH merges the named fields into the stored entry and validates the whole result once. Omitted fields keep their
// stored value; an optional field is cleared with null (or blank text), ended_at only with null, lat/lon only as a pair. id, owner
// and created_at are never writable. A missing or foreign id answers 404 before the body is read, as GET and DELETE do.
const MUTABLE = ['trip_id', 'started_at', 'ended_at', 'method', 'species', 'outcome', 'count', 'lat', 'lon', 'note'] as const;
catchLog.patch('/api/catch-log/:id', async c => {
  const owner = c.var.owner, d = db(c.env), id = c.req.param('id');
  const stored = await d.prepare('SELECT * FROM catch_log WHERE id=? AND owner=?').bind(id, owner).first<Record<string, unknown>>();
  if (!stored) return notFound();
  const patch = await body(c.req.raw, 4096 + NOTE_CHARS * 4), named = Object.keys(patch);
  if (named.some(k => !(MUTABLE as readonly string[]).includes(k))) throw new ClientError(`only ${MUTABLE.join(', ')} can be changed`);
  if (('lat' in patch || 'lon' in patch) && !('lat' in patch && 'lon' in patch)) throw new ClientError('coordinates_incomplete: send latitude and longitude together or neither');
  const e = validateLogEntry({...Object.fromEntries(MUTABLE.map(k => [k, stored[k]])), ...patch});
  if (e.trip_id && !await d.prepare('SELECT 1 AS ok FROM trips WHERE id=? AND owner=?').bind(e.trip_id, owner).first()) return notFound();
  const row = await d.prepare('UPDATE catch_log SET trip_id=?,started_at=?,ended_at=?,method=?,species=?,outcome=?,count=?,lat=?,lon=?,note=? WHERE id=? AND owner=? RETURNING *')
    .bind(e.trip_id, e.started_at, e.ended_at, e.method, e.species, e.outcome, e.count, e.lat, e.lon, e.note, id, owner).first();
  return row ? json(row) : notFound();
});
catchLog.delete('/api/catch-log/:id', async c => {
  const done = await db(c.env).prepare('DELETE FROM catch_log WHERE id=? AND owner=?').bind(c.req.param('id'), c.var.owner).run();
  return done.meta.changes ? json({deleted: true}) : notFound();
});
