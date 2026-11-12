// Web Push subscriptions (allow-listed push services, five devices per person).
import {Hono} from 'hono';
import {validateSubscription} from '../trips.ts';
import {json, body, db, hash} from '../http.ts';
import {ClientError} from '../errors.ts';
import type {AppEnv} from '../env.ts';

export const subscriptions = new Hono<AppEnv>();
const LIMIT_MESSAGE = 'Limit of five notification devices. Stop notifications on another device to free a slot, or use Stop on all devices here.';
const SCOPE_MESSAGE = "Send this device's endpoint or all: true. Update this page before stopping notifications.";
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
  return json({error: existing && existing.owner !== owner ? 'Subscription belongs to another signed-in user' : LIMIT_MESSAGE}, 409);
});
// DELETE names its scope: this device's exact endpoint, or {all: true} for every device of the caller. A body that names neither is refused and
// deletes nothing, so an older cached page (which sent no scope and expected account-wide removal) is asked to refresh instead of silently stopping the phone.
subscriptions.delete('/api/subscription', async c => {
  const owner = c.var.owner, d = db(c.env), b = await body(c.req.raw);
  if (Object.keys(b).some(k => k !== 'endpoint' && k !== 'all')) throw new ClientError('Only endpoint or all can be sent.');
  const hasEndpoint = Object.hasOwn(b, 'endpoint'), hasAll = Object.hasOwn(b, 'all');
  if (hasEndpoint && hasAll) throw new ClientError("Send this device's endpoint or all: true, not both.");
  if (hasAll) {
    if (b.all !== true) throw new ClientError('all must be true');
    await d.prepare('DELETE FROM subscriptions WHERE owner=?').bind(owner).run();
    return json({enabled: false});
  }
  if (!hasEndpoint) throw new ClientError(SCOPE_MESSAGE);
  const endpoint = b.endpoint;
  if (typeof endpoint !== 'string' || !endpoint || endpoint.length > 2000) throw new ClientError('invalid endpoint');
  // The id is the same hash POST stores. An endpoint that is absent and one that belongs to another owner both match no row and answer alike.
  const removed = await d.prepare('DELETE FROM subscriptions WHERE id=? AND owner=?').bind(await hash(endpoint), owner).run();
  return removed.meta.changes > 0 ? json({enabled: false}) : json({error: 'Not found'}, 404);
});
