// The Text Advisor admin gate (docs/plans/text-advisor/08-website.md § Admin,
// 01 § security notes; TA-W2): a passkey session and users.role='admin'. Runs
// after requireUser on /api/admin/* (which already checked the session, the
// Origin of every mutation and the request budget); the admin page routes call
// adminUser directly. Anyone else, and everyone while both TEXT_ADVISOR_ENABLED
// and FLEET_ENABLED are off, gets the same 404 as a path that does not exist, so
// the admin's existence is never confirmed to a non-admin. Each feature's admin
// routes keep their own flag check (routes/admin.ts, routes/fleet.ts). The role
// is set only by scripts/advisor/grant-admin.mjs.
import type {Context, MiddlewareHandler} from 'hono';
import {json} from '../http.ts';
import {advisorSettings} from '../advisor/settings.ts';
import {fleetSettings} from '../fleet/settings.ts';
import type {AppEnv} from '../env.ts';

/** True when users.id `id` has the admin role. */
export async function isAdminUser(db: D1Database | undefined, id: string | null | undefined): Promise<boolean> {
  if (!db || !id) return false;
  return (await db.prepare('SELECT role FROM users WHERE id=?').bind(id).first<{role: string | null}>())?.role === 'admin';
}

/** The signed-in admin's users.id, or null (not signed in, not an admin, or both the advisor and the fleet are off). */
export async function adminUser(c: Context<AppEnv>): Promise<string | null> {
  if (!advisorSettings(c.env).enabled && !fleetSettings(c.env).enabled) return null;
  const id = c.var.owner || (await c.var.identify())?.id || null;
  return await isAdminUser(c.env.DB, id) ? id : null;
}

export const NOT_FOUND = (): Response => json({error: 'Not found'}, 404);

export const requireAdmin: MiddlewareHandler<AppEnv> = async (c, next) => {
  if (!await adminUser(c)) return NOT_FOUND();
  await next();
};
