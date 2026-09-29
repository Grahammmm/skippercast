// Web Push subscriptions (allow-listed push services, five devices per person).
import {Hono} from 'hono';
import {validateSubscription} from '../trips.ts';
import {json, body, db, hash} from '../http.ts';
import type {AppEnv} from '../env.ts';
import type {CountRow} from '../types.ts';

export const subscriptions = new Hono<AppEnv>();
subscriptions.post('/api/subscription', async c => {
  const owner = c.var.owner, d = db(c.env);
  const s = validateSubscription(await body(c.req.raw)), id = await hash(s.endpoint); const existing = await d.prepare('SELECT owner FROM subscriptions WHERE id=?').bind(id).first<{owner: string}>(); if (existing && existing.owner !== owner) return json({error: 'Subscription belongs to another signed-in user'}, 409);
  const count = (await d.prepare('SELECT COUNT(*) AS n FROM subscriptions WHERE owner=?').bind(owner).first<CountRow>())!; if (!existing && count.n >= 5) return json({error: 'Limit of five notification devices'}, 409);
  await d.prepare('INSERT INTO subscriptions(id,owner,endpoint,p256dh,auth,created_at) VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET p256dh=excluded.p256dh,auth=excluded.auth').bind(id, owner, s.endpoint, s.keys.p256dh, s.keys.auth, new Date().toISOString()).run(); return json({enabled: true});
});
subscriptions.delete('/api/subscription', async c => { await db(c.env).prepare('DELETE FROM subscriptions WHERE owner=?').bind(c.var.owner).run(); return json({enabled: false}); });
