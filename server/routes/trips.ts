// Saved trips and their alert events (owner-scoped).
import {Hono} from 'hono';
import {validateTrip} from '../trips.ts';
import {dateInZone} from '../alert-policy.ts';
import {regions} from '../config.ts';
import {json, body, db} from '../http.ts';
import {ClientError} from '../errors.ts';
import type {AppEnv} from '../env.ts';
import type {AlertEventRow, CountRow} from '../types.ts';

export const trips = new Hono<AppEnv>();
trips.get('/api/trips', async c => {
  const owner = c.var.owner, d = db(c.env);
  return json({trips: (await d.prepare('SELECT * FROM trips WHERE owner=? ORDER BY date DESC LIMIT 50').bind(owner).all()).results, events: (await d.prepare('SELECT id,trip_id,kind,message,status,created_at FROM alert_events WHERE owner=? ORDER BY created_at DESC LIMIT 30').bind(owner).all()).results});
});
trips.post('/api/trips', async c => {
  const owner = c.var.owner, env = c.env;
  const t = validateTrip(await body(c.req.raw)); const count = (await db(env).prepare('SELECT COUNT(*) AS n FROM trips WHERE owner=? AND enabled=1 AND final_delivered_at IS NULL AND date>=?').bind(owner, dateInZone(Date.now(), regions[t.region]!.timezone)).first<CountRow>())!; if (count.n >= 20) return json({error: 'Limit of 20 active trips'}, 409);
  const id = crypto.randomUUID(); await db(env).prepare('INSERT INTO trips(id,owner,region,point,species,date,start_hour,end_hour,wind_limit,gust_limit,sea_limit,enabled,created_at,boat_name,boat_sea,boat_wind,boat_chop_period) VALUES(?,?,?,?,?,?,?,?,?,?,?,1,?,?,?,?,?)').bind(id, owner, t.region, t.point, t.species, t.date, t.start_hour, t.end_hour, t.wind_limit, t.gust_limit, t.sea_limit, new Date().toISOString(), t.boat?.name ?? null, t.boat?.sea ?? null, t.boat?.wind ?? null, t.boat?.chop_period ?? null).run(); return json({id}, 201);
});
trips.delete('/api/trips', async c => {
  const owner = c.var.owner, d = db(c.env);
  const {id} = await body(c.req.raw); if (typeof id !== 'string' || !id || id.length > 64) throw new ClientError('trip id required');
  await d.batch([d.prepare('DELETE FROM delivery_receipts WHERE event_id IN (SELECT id FROM alert_events WHERE trip_id=? AND owner=?)').bind(id, owner), d.prepare('DELETE FROM alert_events WHERE trip_id=? AND owner=?').bind(id, owner), d.prepare('DELETE FROM trips WHERE id=? AND owner=?').bind(id, owner)]); return json({deleted: true});
});
trips.post('/api/events/ack', async c => {
  const owner = c.var.owner, d = db(c.env);
  // Event ids are SHA-256 hex digests; never bind an unchecked value.
  const {id} = await body(c.req.raw); if (typeof id !== 'string' || !/^[0-9a-f]{64}$/.test(id)) throw new ClientError('event id required');
  const event = await d.prepare('SELECT * FROM alert_events WHERE id=? AND owner=?').bind(id, owner).first<AlertEventRow>();
  if (!event) return json({error: 'Not found'}, 404);
  await d.prepare('UPDATE alert_events SET status=?,delivered_at=? WHERE id=? AND owner=?').bind('read', new Date().toISOString(), id, owner).run();
  if (['final', 'missed-final'].includes(event.kind)) await d.prepare('UPDATE trips SET final_delivered_at=? WHERE id=? AND owner=?').bind(new Date().toISOString(), event.trip_id, owner).run();
  return json({read: true});
});
