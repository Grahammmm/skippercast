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
  const held = await d.prepare('SELECT COUNT(*) AS n FROM saved_spots WHERE owner=?').bind(owner).first<{n: number}>();
  if ((held?.n ?? 0) >= MAX_SPOTS) throw new ClientError(`you can keep at most ${MAX_SPOTS} saved spots; remove one first`);
  const id = crypto.randomUUID(), created_at = new Date().toISOString();
  await d.prepare('INSERT INTO saved_spots(id,owner,name,lat,lon,note,created_at) VALUES(?,?,?,?,?,?,?)').bind(id, owner, s.name, s.lat, s.lon, s.note, created_at).run();
  return json({id, owner, ...s, created_at}, 201);
});
spots.delete('/api/spots/:id', async c => {
  const done = await db(c.env).prepare('DELETE FROM saved_spots WHERE id=? AND owner=?').bind(c.req.param('id'), c.var.owner).run();
  return done.meta.changes ? json({deleted: true}) : notFound();
});
