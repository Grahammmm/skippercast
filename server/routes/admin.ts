// The Text Advisor admin (docs/plans/text-advisor/08-website.md § Admin; TA-W2):
// the page shell and its API. Mounted in app.ts after `privacy`, so every
// /api/admin/* request has already passed requireUser (session, Origin on
// mutations, request budget); requireAdmin then checks users.role='admin' and
// answers 404 otherwise. The page paths (/admin, /admin.html) are outside /api/
// and check the role themselves: a non-admin gets the same 404 as a missing
// page. The built shell also exists at its hashed name (admin.<build>.html)
// like every page; it holds no data, so the gate that matters is the API's.
//
//   GET  /admin                     302 -> /admin.html (admins only)
//   GET  /admin.html                the admin app shell (dist/admin.html, web/admin/app.tsx)
//   GET  /api/admin/reviews         ?status=open|approved|edited|rejected|all &kind= &cursor=   newest first, 50 a page
//   POST /api/admin/reviews/:id     {decision: approve|edit|reject, patch?, note?, reply?}   admin/decisions.ts
//   GET  /api/admin/media/:id       the photo's bytes from R2: thumb.jpg, public.jpg or the stripped original (?v=original: the original)
//   GET  /api/admin/health          admin/health.ts
import {Hono} from 'hono';
import {json, body} from '../http.ts';
import {requireAdmin, adminUser, NOT_FOUND} from '../middleware/admin.ts';
import {shellResponse} from './assets.ts';
import {advisorSettings} from '../advisor/settings.ts';
import {listReviews, REVIEW_KINDS, REVIEW_STATUSES} from '../advisor/admin/queue.ts';
import {decideReview, DECISIONS} from '../advisor/admin/decisions.ts';
import type {Decision} from '../advisor/admin/decisions.ts';
import {adminHealth} from '../advisor/admin/health.ts';
import {teamSender} from '../advisor/consumer.ts';
import {derivedKey} from '../advisor/media.ts';
import type {AppEnv} from '../env.ts';
import type {ConsumerDeps} from '../advisor/types.ts';

const PAGE_NOT_FOUND = (): Response => new Response('Not found', {status: 404, headers: {'Content-Type': 'text/plain; charset=utf-8', 'Cache-Control': 'no-store'}});
const REVIEW_ID = /^[0-9a-f]{32}$/;
const MEDIA_ID = /^[\w-]{1,64}$/;
/** Types a browser shows inline; anything else is served only as ?v=original. */
const VIEWABLE = new Set(['image/jpeg', 'image/png', 'image/gif', 'image/webp']);
export const thumbKey = (id: string): string => `advisor/derived/${id}/thumb.jpg`;   // 02 § R2, written by the advisor-media job (TA-M1)

/** The admin routes; `deps` lets tests pass a recording channel (production uses channels/index.ts channelFor). */
export function adminRoutes(deps: ConsumerDeps = {}): Hono<AppEnv> {
  const admin = new Hono<AppEnv>();

  admin.get('/admin', async c => (await adminUser(c)) ? new Response(null, {status: 302, headers: {Location: '/admin.html', 'Cache-Control': 'no-store'}}) : PAGE_NOT_FOUND());
  admin.get('/admin.html', async c => {
    if (!await adminUser(c)) return PAGE_NOT_FOUND();
    const shell = await shellResponse(c, '/admin.html');
    const fresh = new Response(shell.body, shell);
    fresh.headers.set('Cache-Control', 'no-store');
    return fresh;
  });

  admin.use('/api/admin/*', requireAdmin);

  admin.get('/api/admin/reviews', async c => {
    const status = c.req.query('status') || 'open', kind = c.req.query('kind') || null, cursor = c.req.query('cursor') || null;
    if (status !== 'all' && !(REVIEW_STATUSES as readonly string[]).includes(status)) return json({error: 'unknown status'}, 400);
    if (kind && !(REVIEW_KINDS as readonly string[]).includes(kind)) return json({error: 'unknown kind'}, 400);
    return json(await listReviews(c.env.DB!, {status, kind, cursor}));
  });

  admin.post('/api/admin/reviews/:id', async c => {
    const id = c.req.param('id');
    if (!REVIEW_ID.test(id)) return NOT_FOUND();
    const input = await body(c.req.raw, 16384);
    const decision = (input.decision ?? (input.reply != null ? 'approve' : null)) as Decision;
    if (!DECISIONS.includes(decision)) return json({error: 'decision must be approve, edit or reject'}, 400);
    const by = c.var.owner;
    const outcome = await decideReview(c.env, {reviewId: id, decision, patch: input.patch, note: input.note, reply: input.reply, by, inId: id, key: 'admin'},
      {now: Date.now(), send: teamSender(c.env, deps), sendsEnabled: advisorSettings(c.env).repliesEnabled});
    switch (outcome.status) {
      case 'applied': return json({review: outcome.review, sends: outcome.sends, ...(outcome.held ? {held: outcome.held} : {})});
      case 'repeated': return json({review: outcome.review, repeated: true});
      case 'not-found': return NOT_FOUND();
      case 'invalid': return json({error: outcome.error}, 400);
      case 'conflict': return json({error: outcome.error}, 409);
    }
  });

  admin.get('/api/admin/media/:id', async c => {
    const id = c.req.param('id'), env = c.env, original = c.req.query('v') === 'original';
    if (!MEDIA_ID.test(id) || !env.DB || !env.ADVISOR_MEDIA) return NOT_FOUND();
    const row = await env.DB.prepare('SELECT mime,r2_key FROM advisor_media WHERE id=?').bind(id).first<{mime: string; r2_key: string}>();
    if (!row?.r2_key) return NOT_FOUND();
    let object: R2ObjectBody | null = null, type = row.mime;
    if (!original) {
      for (const key of [thumbKey(id), derivedKey(id)]) { object = await env.ADVISOR_MEDIA.get(key); if (object) { type = 'image/jpeg'; break; } }
      if (!object && VIEWABLE.has(row.mime)) object = await env.ADVISOR_MEDIA.get(row.r2_key);
    } else {
      object = await env.ADVISOR_MEDIA.get(row.r2_key);
    }
    if (!object) return NOT_FOUND();
    return new Response(object.body, {status: 200, headers: {'Content-Type': type, 'Content-Length': String(object.size), 'Content-Disposition': 'inline',
      'Cache-Control': 'private, no-store', 'X-Robots-Tag': 'noindex', 'X-Content-Type-Options': 'nosniff'}});
  });

  admin.get('/api/admin/health', async c => json(await adminHealth(c.env)));

  return admin;
}

export const admin = adminRoutes();
