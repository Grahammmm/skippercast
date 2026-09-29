// Comfort feedback: how a trip actually felt, for calibrating boat factors.
import {Hono} from 'hono';
import {regions, regionById} from '../config.ts';
import {json, body, db} from '../http.ts';
import {ClientError} from '../errors.ts';
import type {AppEnv} from '../env.ts';

export const feedback = new Hono<AppEnv>();
feedback.post('/api/comfort', async c => {
  const owner = c.var.owner;
  const b = await body(c.req.raw); if (!regionById(b.region) || !Number.isInteger(b.rating) || b.rating < 1 || b.rating > 10 || !['outbound', 'fishing', 'return'].includes(b.phase)) throw new ClientError('invalid feedback');
  for (const [key, max] of [['wind', 200], ['sea', 100], ['period', 60], ['heading', 360]] as const) if (b[key] != null && (typeof b[key] !== 'number' || !Number.isFinite(b[key]) || b[key] < 0 || b[key] > max)) throw new ClientError('invalid feedback context');
  if (b.point != null && !regions[b.region]!.forecast_points.some(p => p.id === b.point)) throw new ClientError('invalid feedback point');
  await db(c.env).prepare('INSERT INTO comfort_feedback(id,owner,region,observed_at,rating,context) VALUES(?,?,?,?,?,?)').bind(crypto.randomUUID(), owner, b.region, new Date().toISOString(), b.rating, JSON.stringify({phase: b.phase, wind: b.wind ?? null, sea: b.sea ?? null, period: b.period ?? null, heading: b.heading ?? null, point: b.point ?? null})).run(); return json({saved: true}, 201);
});
feedback.get('/api/comfort', async c => json({feedback: (await db(c.env).prepare('SELECT * FROM comfort_feedback WHERE owner=? ORDER BY observed_at DESC LIMIT 100').bind(c.var.owner).all()).results}));
