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
//   GET  /api/admin/media/:id       the photo's bytes from R2: thumb.jpg, public.jpg or the stripped original if upright (?v=original: the original)
//   GET  /api/admin/health          admin/health.ts
//   GET  /api/admin/boats           admin/skippers.ts listBoats (TA-W3)
//   POST /api/admin/boats/invite    {phone, boat_name?, language?}   the number is hashed on receipt and never echoed; 20 a day
//   POST /api/admin/boats/:id       {fields?, status?: verified|rejected, consent_note?}
//   POST /api/admin/boats/:id/crew/:contactId/remove
//   GET  /api/admin/contacts/:id    one contact by id (no search by number), last 50 messages
//   GET  /api/admin/contacts/:id/export   the contact's data as a JSON download (contacts.ts exportContact)
//   POST /api/admin/contacts/:id/block    {blocked: boolean}
//   GET  /api/admin/funnel          ?days=7|30   admin/funnel.ts (TA-W4): D1 counts and Analytics Engine SQL reads, numbers only
//   GET  /api/admin/rules           ?jurisdiction= &status=active|review|retired|due   admin/rules.ts (TA-A4)
//   POST /api/admin/rules           create (active: the admin reviewed it)
//   POST /api/admin/rules/:id       edit or confirm: reviewed_at now, review_due, status active, updated_by
//   POST /api/admin/rules/:id/retire
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
// TA-W3: skippers, crew, invites and contacts.
import {listBoats, editBoat, removeCrew, inviteSkipper, contactView, setBlocked, validId} from '../advisor/admin/skippers.ts';
import type {AdminOutcome} from '../advisor/admin/skippers.ts';
import {exportContact} from '../advisor/contacts.ts';
// TA-W4: the funnel.
import {adminFunnel, FUNNEL_DAYS} from '../advisor/admin/funnel.ts';
import type {FunnelDays, SqlFetcher} from '../advisor/admin/funnel.ts';
// TA-A4: the rules editor.
import {listRules, createRule, editRule, retireRule} from '../advisor/admin/rules.ts';
import type {RuleOutcome} from '../advisor/admin/rules.ts';
import type {Fetcher} from '../advisor/social/meta.ts';
import type {AppEnv} from '../env.ts';
import type {ConsumerDeps} from '../advisor/types.ts';

/** The JSON answer for an admin/rules.ts outcome. */
function ruleAnswer(outcome: RuleOutcome): Response {
  switch (outcome.status) {
    case 'ok': return json({rule: outcome.rule});
    case 'not-found': return NOT_FOUND();
    case 'invalid': return json({error: outcome.error}, 400);
    case 'conflict': return json({error: outcome.error}, 409);
  }
}

/** The JSON answer for an admin/skippers.ts outcome. */
function answer<T>(outcome: AdminOutcome<T>): Response {
  switch (outcome.status) {
    case 'ok': return json(outcome.value);
    case 'not-found': return NOT_FOUND();
    case 'invalid': return json({error: outcome.error}, 400);
    case 'conflict': return json({error: outcome.error}, 409);
    case 'unavailable': return json({error: outcome.error}, 503);
  }
}

const PAGE_NOT_FOUND = (): Response => new Response('Not found', {status: 404, headers: {'Content-Type': 'text/plain; charset=utf-8', 'Cache-Control': 'no-store'}});
const REVIEW_ID = /^[0-9a-f]{32}$/;
const MEDIA_ID = /^[\w-]{1,64}$/;
/** Types a browser shows inline; anything else is served only as ?v=original. */
const VIEWABLE = new Set(['image/jpeg', 'image/png', 'image/gif', 'image/webp']);
export const thumbKey = (id: string): string => `advisor/derived/${id}/thumb.jpg`;   // 02 § R2, written by the advisor-media job (TA-M1)

/** What the admin routes take besides the consumer's deps (tests): the funnel's Analytics Engine SQL reader and the Graph API fetcher (TA-S0). */
export interface AdminDeps extends ConsumerDeps {analyticsSql?: SqlFetcher | null; metaFetcher?: Fetcher}

/** The admin routes; `deps` lets tests pass a recording channel (production uses channels/index.ts channelFor). */
export function adminRoutes(deps: AdminDeps = {}): Hono<AppEnv> {
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
      {now: Date.now(), send: teamSender(c.env, deps), sendsEnabled: advisorSettings(c.env).repliesEnabled, ...(deps.dispatchWorkflow ? {dispatch: deps.dispatchWorkflow} : {})});
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
    const row = await env.DB.prepare('SELECT mime,r2_key,orientation FROM advisor_media WHERE id=?').bind(id).first<{mime: string; r2_key: string; orientation: number | null}>();
    if (!row?.r2_key) return NOT_FOUND();
    let object: R2ObjectBody | null = null, type = row.mime;
    if (!original) {
      for (const key of [thumbKey(id), derivedKey(id)]) { object = await env.ADVISOR_MEDIA.get(key); if (object) { type = 'image/jpeg'; break; } }
      // A JPEG stored sideways (EXIF orientation 2-8, stripped at intake) waits for the job's upright files, like a HEIC.
      if (!object && VIEWABLE.has(row.mime) && (row.orientation ?? 1) <= 1) object = await env.ADVISOR_MEDIA.get(row.r2_key);
    } else {
      object = await env.ADVISOR_MEDIA.get(row.r2_key);
    }
    if (!object) return NOT_FOUND();
    return new Response(object.body, {status: 200, headers: {'Content-Type': type, 'Content-Length': String(object.size), 'Content-Disposition': 'inline',
      'Cache-Control': 'private, no-store', 'X-Robots-Tag': 'noindex', 'X-Content-Type-Options': 'nosniff'}});
  });

  admin.get('/api/admin/health', async c => json(await adminHealth(c.env, (deps.now ?? Date.now)(), deps.metaFetcher ? {metaFetcher: deps.metaFetcher} : {})));

  // ---- TA-W3: skippers, crew, invites, contacts ----
  const now = (): number => (deps.now ?? Date.now)();
  admin.get('/api/admin/boats', async c => json(await listBoats(c.env.DB!, now())));
  // Registered before /api/admin/boats/:id, which would otherwise take "invite" as an id.
  admin.post('/api/admin/boats/invite', async c => {
    const input = await body(c.req.raw, 4096);
    return answer(await inviteSkipper(c.env, {phone: input.phone, boat_name: input.boat_name, language: input.language, by: c.var.owner, now: now()},
      {send: teamSender(c.env, deps), sendsEnabled: advisorSettings(c.env).repliesEnabled}));
  });
  admin.post('/api/admin/boats/:id', async c => {
    const input = await body(c.req.raw, 8192);
    return answer(await editBoat(c.env, c.req.param('id'), {fields: input.fields, status: input.status, consent_note: input.consent_note, by: c.var.owner, now: now()},
      {send: teamSender(c.env, deps), sendsEnabled: advisorSettings(c.env).repliesEnabled, ...(deps.dispatchWorkflow ? {dispatch: deps.dispatchWorkflow} : {})}));
  });
  admin.post('/api/admin/boats/:id/crew/:contactId/remove', async c => answer(await removeCrew(c.env.DB!, c.req.param('id'), c.req.param('contactId'), now())));
  admin.get('/api/admin/contacts/:id', async c => {
    const detail = await contactView(c.env.DB!, c.req.param('id'));
    return detail ? json(detail) : NOT_FOUND();
  });
  admin.get('/api/admin/contacts/:id/export', async c => {
    const id = c.req.param('id');
    const data = validId(id) ? await exportContact(c.env.DB!, id) : null;
    if (!data) return NOT_FOUND();
    return new Response(JSON.stringify(data, null, 2), {status: 200, headers: {'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'private, no-store',
      'Content-Disposition': `attachment; filename="skippercast-contact-${id}.json"`, 'X-Content-Type-Options': 'nosniff'}});
  });
  // ---- TA-W4: the funnel ----
  admin.get('/api/admin/funnel', async c => {
    const days = Number(c.req.query('days') || 7) as FunnelDays;
    if (!FUNNEL_DAYS.includes(days)) return json({error: 'days must be 7 or 30'}, 400);
    return json(await adminFunnel(c.env, days, {now: now(), ...(deps.analyticsSql !== undefined ? {sql: deps.analyticsSql} : {})}));
  });

  // ---- TA-A4: rules ----
  admin.get('/api/admin/rules', async c => {
    const list = await listRules(c.env.DB!, {jurisdiction: c.req.query('jurisdiction') || null, status: c.req.query('status') || null}, now());
    return 'error' in list ? json({error: list.error}, 400) : json(list);
  });
  admin.post('/api/admin/rules', async c => ruleAnswer(await createRule(c.env.DB!, await body(c.req.raw, 16384), c.var.owner, now())));
  admin.post('/api/admin/rules/:id/retire', async c => ruleAnswer(await retireRule(c.env.DB!, c.req.param('id'), c.var.owner, now())));
  admin.post('/api/admin/rules/:id', async c => ruleAnswer(await editRule(c.env.DB!, c.req.param('id'), await body(c.req.raw, 16384), c.var.owner, now())));

  admin.post('/api/admin/contacts/:id/block', async c => {
    const input = await body(c.req.raw, 1024);
    if (typeof input.blocked !== 'boolean') return json({error: 'blocked must be true or false'}, 400);
    return answer(await setBlocked(c.env.DB!, c.req.param('id'), input.blocked, now()));
  });

  return admin;
}

export const admin = adminRoutes();
