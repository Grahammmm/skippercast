// BF-saved-spots: the signed-in person's own private places, each with an optional private note.
// Read and written only here and in the owner's /api/privacy export. There is no visibility column:
// private is the only state. Nothing in this file feeds a public route, feed, preview or other account.
// The protected-area screen and the GPX name cleaning run where a spot is shown or exported (dist/account.js).
import {Hono} from 'hono';
import {json, body, db} from '../http.ts';
import {ClientError} from '../errors.ts';
import {coordinates} from './catch-log.ts';
import type {AppEnv} from '../env.ts';

export const spots = new Hono<AppEnv>();
// 100 is what a GPX export of saved points carries (dist/trip-export.js userWaypoints); 80 UTF-16 units is its name limit.
export const MAX_SPOTS = 100, NAME_UNITS = 80, NOTE_CHARS = 1000;
const notFound = () => json({error: 'Not found'}, 404);

/** A spot as stored. The name may be blank or hold characters GPX forbids; export cleans it, so the store keeps what was typed. */
export function validateSpot(input: Record<string, unknown>) {
  const name = input.name ?? '';
  if (typeof name !== 'string' || name.length > NAME_UNITS) throw new ClientError(`name must be text of at most ${NAME_UNITS} characters`);
  const note = input.note ?? null;
  if (note !== null && (typeof note !== 'string' || [...note].length > NOTE_CHARS)) throw new ClientError(`note must be text of at most ${NOTE_CHARS} characters`);
  const c = coordinates(input.lat, input.lon);
  if (!c) throw new ClientError('coordinates_required: send latitude and longitude');
  return {name, lat: c.lat, lon: c.lon, note: typeof note === 'string' && note.trim() ? note : null};
}

spots.get('/api/spots', async c => json({spots: (await db(c.env).prepare('SELECT * FROM saved_spots WHERE owner=? ORDER BY created_at DESC, id LIMIT ?').bind(c.var.owner, MAX_SPOTS).all()).results}));
// Another account's id answers exactly what an id that never existed answers.
spots.get('/api/spots/:id', async c => {
  const row = await db(c.env).prepare('SELECT * FROM saved_spots WHERE id=? AND owner=?').bind(c.req.param('id'), c.var.owner).first();
  return row ? json(row) : notFound();
});
spots.post('/api/spots', async c => {
  const owner = c.var.owner, d = db(c.env), s = validateSpot(await body(c.req.raw, 4096 + NOTE_CHARS * 4));
  const id = crypto.randomUUID(), created_at = new Date().toISOString();
  // Capacity check and insert are one statement, so two saves at 99 cannot both pass a stale count.
  const added = await d.prepare('INSERT INTO saved_spots(id,owner,name,lat,lon,note,created_at) SELECT ?,?,?,?,?,?,? WHERE (SELECT COUNT(*) FROM saved_spots WHERE owner=?) < ?').bind(id, owner, s.name, s.lat, s.lon, s.note, created_at, owner, MAX_SPOTS).run();
  if (!added.meta.changes) throw new ClientError(`you can keep at most ${MAX_SPOTS} saved spots; remove one first`);
  return json({id, owner, ...s, created_at}, 201);
});
// Rename or re-note a spot. Only these two columns can change: a new position is a new spot, because the
// protected-area screen runs where a spot is shown or exported. Column names come from this list, never from the request.
const EDITABLE = ['name', 'note'] as const;
spots.patch('/api/spots/:id', async c => {
  const owner = c.var.owner, d = db(c.env), id = c.req.param('id');
  // Ownership first: an id that is missing and one owned by someone else answer alike, whatever the body holds.
  const row = await d.prepare('SELECT lat,lon FROM saved_spots WHERE id=? AND owner=?').bind(id, owner).first<{lat: number; lon: number}>();
  if (!row) return notFound();
  const edit = await body(c.req.raw, 4096 + NOTE_CHARS * 4);
  for (const key of ['lat', 'lon']) if (Object.hasOwn(edit, key)) throw new ClientError(`${key} cannot be changed; save a new spot for a different position`);
  if (Object.keys(edit).some(key => !(EDITABLE as readonly string[]).includes(key))) throw new ClientError('only name and note can be changed');
  const sent = EDITABLE.filter(key => Object.hasOwn(edit, key));
  if (!sent.length) throw new ClientError('send name and/or note');
  // Same checks as a save; the spot's own position stands in for the coordinates this request may not carry.
  const s = validateSpot({name: edit.name, note: edit.note, lat: row.lat, lon: row.lon});
  // Only the supplied columns are written, so a name edit and a note edit in flight together both survive.
  const saved = await d.prepare(`UPDATE saved_spots SET ${sent.map(key => key + '=?').join(',')} WHERE id=? AND owner=? RETURNING *`).bind(...sent.map(key => s[key]), id, owner).first();
  return saved ? json(saved) : notFound();
});
spots.delete('/api/spots/:id', async c => {
  const done = await db(c.env).prepare('DELETE FROM saved_spots WHERE id=? AND owner=?').bind(c.req.param('id'), c.var.owner).run();
  return done.meta.changes ? json({deleted: true}) : notFound();
});
