// GET /go/<slug>?t=booking|website&p=profile|directory|map — the charter fleet's
// outbound link (docs/plans/charter-fleet/design.md § 12, D15; threat model § 10.1).
//
// It redirects only to the vessel's own stored https URL: nothing in the request
// (`url=`, `next=`, any other parameter, a header) can choose or change the
// target, so the route is no open redirect. `t` picks which stored URL and `p`
// only labels the placement in the count. Unknown slug, a vessel that is not
// public (display.ts publicVesselSql: `status='active'`, `profile_status='listed'`,
// no removal request), no URL for `t`, or a stored URL
// that is not plain https → 404. UTM tags are appended, keeping every existing
// parameter (and any utm_* already there) as stored.
//
// Each click adds one to the day's fleet_link_clicks row (vessel, target,
// placement, UTC day) and writes one Analytics Engine point (slug, target,
// placement) when ANALYTICS is bound. Nothing about the visitor is stored: no
// IP, user agent, referrer, cookie or user id. Counts are raw redirects, not
// visitors. Gated by FLEET_ENABLED and the per-IP PUBLIC_LIMITER in routes/fleet.ts.
import type {Context} from 'hono';
import {json} from '../http.ts';
import {recordFleetClick} from '../analytics.ts';
import {waitUntil} from '../routes/util.ts';
import {publicVesselSql} from './display.ts';
import type {AppEnv, Env} from '../env.ts';

export const TARGETS = ['booking', 'website'] as const;
export const PLACEMENTS = ['profile', 'directory', 'map', 'other'] as const;
export type Target = typeof TARGETS[number];
export type Placement = typeof PLACEMENTS[number];

const SLUG = /^[a-z0-9](?:[a-z0-9-]{0,78}[a-z0-9])?$/;
const MAX_URL = 2048;
const NOT_FOUND = (): Response => json({error: 'Not found'}, 404);

/** The stored URL as a redirect target: https, a host, no credentials, bounded; else null. */
export function safeTarget(stored: unknown): URL | null {
  if (typeof stored !== 'string' || !stored || stored.length > MAX_URL) return null;
  let url: URL;
  try { url = new URL(stored.trim()); } catch { return null; }
  if (url.protocol !== 'https:' || !url.hostname || url.username || url.password) return null;
  return url;
}

/** `target` with the referral UTM tags appended; existing parameters (utm_* included) are kept as stored. */
export function withUtm(target: URL, region: string, placement: Placement): string {
  const url = new URL(target.href), have = url.searchParams;
  const tags: [string, string][] = [['utm_source', 'skippercast'], ['utm_medium', 'referral'],
    ['utm_campaign', 'fleet-' + region], ['utm_content', placement]];
  const add = new URLSearchParams(tags.filter(([key]) => !have.has(key))).toString();
  if (add) url.search = url.search ? url.search.slice(1) + '&' + add : add;
  return url.href;
}

/** UTC calendar day (YYYY-MM-DD) of `now`. */
export const utcDay = (now: Date): string => now.toISOString().slice(0, 10);

/** One more click on the day's counter row. */
export async function countClick(db: D1Database, vesselId: string, target: Target, placement: Placement, day: string): Promise<void> {
  await db.prepare(`INSERT INTO fleet_link_clicks(vessel_id,target,placement,day,count) VALUES(?,?,?,?,1)
    ON CONFLICT(vessel_id,target,placement,day) DO UPDATE SET count=count+1`).bind(vesselId, target, placement, day).run();
}

interface VesselLink {id: string; region: string; website: string | null; booking_url: string | null}

/** The /go/<slug> handler (mounted behind fleetGate and PUBLIC_LIMITER). */
export async function fleetGo(c: Context<AppEnv>, now: () => Date = () => new Date()): Promise<Response> {
  const env: Env = c.env, slug = c.req.param('slug') ?? '';
  const t = c.req.query('t'), p = c.req.query('p');
  if (!SLUG.test(slug) || !(TARGETS as readonly string[]).includes(t ?? '')) return NOT_FOUND();
  const target = t as Target;
  const placement: Placement = p && (PLACEMENTS as readonly string[]).includes(p) ? p as Placement : 'other';
  if (!env.DB) return json({error: 'This service is temporarily unavailable.'}, 503);
  const vessel = await env.DB.prepare(`SELECT id,region,website,booking_url FROM fleet_vessels
    WHERE slug=? AND ${publicVesselSql()}`).bind(slug).first<VesselLink>();
  if (!vessel) return NOT_FOUND();
  const url = safeTarget(target === 'booking' ? vessel.booking_url : vessel.website);
  if (!url) return NOT_FOUND();
  // HEAD (link checkers, prefetch) answers the same redirect without counting.
  if (c.req.method !== 'HEAD') {
    const work = countClick(env.DB, vessel.id, target, placement, utcDay(now())).catch(() => { /* a failed count never blocks the visitor */ });
    const ctx = waitUntil(c);
    if (ctx) ctx.waitUntil(work); else await work;
    recordFleetClick(env, slug, target, placement);
  }
  return new Response(null, {status: 302, headers: {Location: withUtm(url, vessel.region, placement), 'Cache-Control': 'no-store',
    'X-Robots-Tag': 'noindex', 'Referrer-Policy': 'strict-origin-when-cross-origin'}});
}
