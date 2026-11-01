// The session probe (public) and the signed-in person's own data: export and
// complete deletion.
import {Hono} from 'hono';
import {exportAccount, deleteAccountStatements, clearCookie} from '../auth.ts';
import {json, db} from '../http.ts';
import {signInPath} from '../middleware/context.ts';
// TA-W2: is_admin (02 § users: the role is never exposed beyond this boolean).
import {isAdminUser} from '../middleware/admin.ts';
import type {AppEnv} from '../env.ts';

export const session = new Hono<AppEnv>();
session.get('/api/session', async c => {
  const who = await c.var.identify(), owner = who?.id || null, signIn = signInPath(c.var.identityProvider);
  const is_admin = owner ? await isAdminUser(c.env.DB, owner) : false;
  return json({signedIn: !!owner, publicKey: c.env.VAPID_PUBLIC_KEY || null, signIn, user: owner ? {id: owner, display_name: who!.display_name ?? null} : null, is_admin});
});

// SC1537-08: a notification device is exported as its push service host and created date only;
// the endpoint path, its hash id, p256dh and auth never leave the database.
export function deviceRow(r: {endpoint: unknown; created_at: unknown}): {push_service: string; created_at: string | null} {
  let push_service = 'unknown';
  try { if (typeof r.endpoint === 'string') push_service = new URL(r.endpoint).hostname.toLowerCase() || 'unknown'; } catch { /* legacy garbage */ }
  return {push_service, created_at: typeof r.created_at === 'string' ? r.created_at : null};
}

export const privacy = new Hono<AppEnv>();
privacy.get('/api/privacy', async c => {
  const owner = c.var.owner, d = db(c.env);
  const devices = (await d.prepare('SELECT endpoint, created_at FROM subscriptions WHERE owner=? ORDER BY created_at DESC').bind(owner).all<{endpoint: unknown; created_at: unknown}>()).results.map(deviceRow);
  return json({account: await exportAccount(d, owner), trips: (await d.prepare('SELECT * FROM trips WHERE owner=?').bind(owner).all()).results, feedback: (await d.prepare('SELECT * FROM comfort_feedback WHERE owner=?').bind(owner).all()).results, events: (await d.prepare('SELECT message,created_at,status FROM alert_events WHERE owner=?').bind(owner).all()).results, devices});
});
privacy.delete('/api/privacy', async c => {
  const owner = c.var.owner, d = db(c.env);
  // Deleting records deletes the account too: its passkeys, sessions and user row.
  await d.batch([d.prepare('DELETE FROM delivery_receipts WHERE event_id IN (SELECT id FROM alert_events WHERE owner=?)').bind(owner), ...['trips', 'subscriptions', 'alert_events', 'comfort_feedback'].map(t => d.prepare(`DELETE FROM ${t} WHERE owner=?`).bind(owner)), ...deleteAccountStatements(d, owner)]);
  const done = json({deleted: true, signedIn: false}); done.headers.append('Set-Cookie', clearCookie()); return done;
});
