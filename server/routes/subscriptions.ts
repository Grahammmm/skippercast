// Web Push subscriptions (allow-listed push services, five devices per person).
import {Hono} from 'hono';
import {validateSubscription} from '../trips.ts';
import {json, body, db, hash} from '../http.ts';
import type {AppEnv} from '../env.ts';

export const subscriptions = new Hono<AppEnv>();
subscriptions.post('/api/subscription', async c => {
  const owner = c.var.owner, d = db(c.env);
  const s = validateSubscription(await body(c.req.raw)), id = await hash(s.endpoint);
  // One conditional write enforces both rules when SQLite runs it: a new device needs a free slot (an owned device may always refresh),
  // and a conflicting endpoint is only updated, keys only, when the same owner holds it. Concurrent requests cannot pass a stale pre-check.
  const written = await d.prepare('INSERT INTO subscriptions(id,owner,endpoint,p256dh,auth,created_at) SELECT ?,?,?,?,?,? WHERE EXISTS (SELECT 1 FROM subscriptions WHERE id=? AND owner=?) OR (SELECT COUNT(*) FROM subscriptions WHERE owner=?) < 5 ON CONFLICT(id) DO UPDATE SET p256dh=excluded.p256dh,auth=excluded.auth WHERE subscriptions.owner=excluded.owner')
    .bind(id, owner, s.endpoint, s.keys.p256dh, s.keys.auth, new Date().toISOString(), id, owner, owner).run();
  if (written.meta.changes > 0) return json({enabled: true});
  // Nothing was written. This read only chooses the refusal wording; it never authorizes a write.
  const existing = await d.prepare('SELECT owner FROM subscriptions WHERE id=?').bind(id).first<{owner: string}>();
  return json({error: existing && existing.owner !== owner ? 'Subscription belongs to another signed-in user' : 'Limit of five notification devices'}, 409);
});
subscriptions.delete('/api/subscription', async c => { await db(c.env).prepare('DELETE FROM subscriptions WHERE owner=?').bind(c.var.owner).run(); return json({enabled: false}); });
