// Text Advisor admin (TA-W2; docs/plans/text-advisor/08-website.md § Admin):
// requireAdmin's 404 for everyone but an admin on every admin route (and for
// everyone while the advisor is off), is_admin on /api/session, the shell, the
// queue's list and per-kind detail, each decision's rows and texts through a
// recording channel, idempotent repeats, the admin-only media bytes route, the
// health shape and the queue's keyboard shortcuts. Offline: real migrations in
// node:sqlite, a memory R2, real session cookies (fixtures/test-sessions.mjs).
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';
import {memoryBucket} from './_advisor_r2.mjs';
import {withSessions} from './fixtures/test-sessions.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html', '/admin.html': '/admin.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
const {default: deployed} = await import('../server/index.ts');
const {Hono} = await import('hono');
const {context} = await import('../server/middleware/context.ts');
const {requireUser} = await import('../server/middleware/auth.ts');
const {onError} = await import('../server/middleware/error.ts');
const {adminRoutes, thumbKey} = await import('../server/routes/admin.ts');
const {decideReview} = await import('../server/advisor/admin/decisions.ts');
const {PAGE_SIZE, decodeCursor, encodeCursor} = await import('../server/advisor/admin/queue.ts');
const {teamSender} = await import('../server/advisor/consumer.ts');
const {reviewId} = await import('../server/advisor/contacts.ts');
const {outboundId} = await import('../server/advisor/ids.ts');
const {derivedKey} = await import('../server/advisor/media.ts');
const {RELAY_KEY} = await import('../server/advisor/relay.ts');
const {downKey, lastOkKey} = await import('../server/advisor/vision/index.ts');
const {visionLine, when} = await import('../web/admin/api.ts');
const {PAGES_VERSION_KEY} = await import('../server/advisor/intake/reports.ts');
const {shortcutFor, decisionsFor, typingIn} = await import('../web/admin/keys.ts');
const {ADMIN_COPY} = await import('../web/advisor/copy.ts');
const {t} = await import('../server/advisor/strings.ts');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const ORIGIN = 'https://skippercast.com';
const ADMIN = 'admin-user-1', OTHER = 'plain-user-1';
const ASSETS = {fetch: async request => new Response(`shell:${new URL(request.url).pathname}`, {status: 200, headers: {'Cache-Control': 'public, max-age=60'}})};
const quiet = async fn => { const saved = {log: console.log, warn: console.warn, error: console.error}, lines = []; console.log = console.warn = console.error = (...a) => lines.push(a.join(' ')); try { return {value: await fn(), lines}; } finally { Object.assign(console, saved); } };
const iso = ms => new Date(ms).toISOString();
const T0 = Date.parse('2026-10-04T15:00:00Z');

function recorder(name = 'bluebubbles') { const sent = []; return {sent, name, async send(m) { sent.push(structuredClone(m)); return {providerId: `${name}-${sent.length}`, status: 'sent'}; }}; }

/** The Worker as deployed, and the same admin routes on a test app whose channel is a recorder (the order app.ts uses: context, requireUser on /api/*, admin). */
function apps(ch) {
  const app = new Hono({getPath: request => new URL(request.url).pathname});
  app.use('*', context);
  app.use('/api/*', requireUser);
  app.route('/', adminRoutes({channelFor: () => ch}));
  app.onError(onError);
  return {real: withSessions(deployed), withChannel: withSessions({fetch: (request, env, ctx) => app.fetch(request, env, ctx)})};
}

function setup({env = {}} = {}) {
  const {sql, db} = advisorDatabase();
  sql.prepare("INSERT INTO users(id,created_at,role) VALUES(?,?,'admin')").run(ADMIN, iso(T0));
  sql.prepare('INSERT INTO users(id,created_at) VALUES(?,?)').run(OTHER, iso(T0));
  const ch = recorder();
  return {sql, db, ch, ...apps(ch), env: {TEXT_ADVISOR_ENABLED: 'true', DB: db, ADVISOR_MEDIA: memoryBucket(), ASSETS, ...env}};
}
const get = (worker, env, path, owner) => worker.fetch(new Request(ORIGIN + path, {headers: owner ? {'x-test-owner': owner} : {}}), env);
const post = (worker, env, path, owner, body, headers = {Origin: ORIGIN}) => worker.fetch(new Request(ORIGIN + path, {method: 'POST',
  headers: {'Content-Type': 'application/json', ...(owner ? {'x-test-owner': owner} : {}), ...headers}, body: JSON.stringify(body)}), env);

function addContact(sql, c) {
  sql.prepare(`INSERT INTO advisor_contacts(id,phone_hash,phone_enc,channel,role,language,boat_id,display_name,status,last_seen_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)`)
    .run(c.id, c.phone_hash ?? `h-${c.id}`, c.phone_enc ?? `ENC-${c.id}`, c.channel ?? 'imessage', c.role ?? 'angler', c.language ?? 'en', c.boat_id ?? null, c.display_name ?? null, c.status ?? 'active', iso(T0), iso(T0), iso(T0));
}
function addBoat(sql, b) {
  sql.prepare(`INSERT INTO advisor_boats(id,slug,name,landing,port,region,instagram,owner_contact_id,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)`)
    .run(b.id, b.slug, b.name, b.landing ?? null, b.port ?? 'morro-bay', 'morro-bay', b.instagram ?? null, b.owner ?? null, b.status ?? 'pending', iso(T0), iso(T0));
}
let seq = 0;
function addMessage(sql, contact, direction, body, at = T0 + (++seq) * 1000, extra = {}) {
  const id = extra.id ?? `m${++seq}`;
  sql.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,body,status,created_at,created_by) VALUES(?,?,?,'imessage',?,?,?,?)`).run(id, contact, direction, body, extra.status ?? 'done', iso(at), extra.created_by ?? null);
  return id;
}
async function addReview(sql, kind, ref, reason, at = T0) {
  const id = await reviewId(kind, ref, reason);
  sql.prepare(`INSERT INTO advisor_reviews(id,kind,ref_id,reason,status,opened_at) VALUES(?,?,?,?,'open',?)`).run(id, kind, ref, reason, iso(at));
  return id;
}
function addMedia(sql, m) {
  sql.prepare(`INSERT INTO advisor_media(id,contact_id,boat_id,kind,mime,bytes,r2_key,sha256,exif_stripped,classification_json,has_person,publish_state,credit,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)`)
    .run(m.id, m.contact ?? 'c1', m.boat ?? null, m.kind ?? 'image', m.mime ?? 'image/jpeg', m.bytes ?? 1000, m.r2_key ?? `advisor/media/${m.contact ?? 'c1'}/${m.id}.jpg`, 'sha', 1,
      m.classification ?? null, m.has_person ?? null, m.state ?? 'queued', m.credit ?? null, iso(T0));
}
function addReport(sql, r) {
  sql.prepare(`INSERT INTO advisor_reports(id,boat_id,contact_id,region,port,report_date,trip_type,anglers,counts_json,source,status,verified,version,created_at,updated_at) VALUES(?,?,?,'morro-bay','morro-bay',?,?,?,?,'text',?,0,1,?,?)`)
    .run(r.id, r.boat, r.contact ?? 'c1', r.date ?? '2026-10-04', r.trip ?? 'half-day', r.anglers ?? 20, JSON.stringify(r.counts ?? [{species_key: 'lingcod', label: 'lings', kept: 12, released: 0}]), r.status ?? 'pending_confirm', iso(T0), iso(T0));
}
const reviewOf = (sql, id) => sql.prepare('SELECT * FROM advisor_reviews WHERE id=?').get(id);

// ---- the gate ----------------------------------------------------------------------------

dbTest('every admin route is a 404 for a signed-in non-admin, for anyone while the advisor is off, and needs a session and Origin', async () => {
  const {sql, env, real} = setup();
  addContact(sql, {id: 'c1'});
  addMedia(sql, {id: 'p1'});
  env.ADVISOR_MEDIA.objects.set('advisor/media/c1/p1.jpg', {bytes: new Uint8Array([0xff, 0xd8, 0xff, 0xd9]), httpMetadata: {}});
  const review = await addReview(sql, 'media', 'p1', 'has_person');
  const routes = [['GET', '/admin'], ['GET', '/admin.html'], ['GET', '/api/admin/reviews'], ['GET', '/api/admin/reviews?status=open&kind=media'], ['GET', '/api/admin/health'],
    ['GET', '/api/admin/media/p1'], ['GET', '/api/admin/media/p1?v=original'], ['POST', `/api/admin/reviews/${review}`]];
  const hit = (method, path, owner, e = env) => method === 'GET' ? get(real, e, path, owner) : post(real, e, path, owner, {decision: 'approve'});
  for (const [method, path] of routes) {
    const response = await hit(method, path, OTHER);
    assert.equal(response.status, 404, `${method} ${path} for a non-admin`);
    assert.doesNotMatch(await response.text(), /admin/i, 'the 404 does not name the admin');
  }
  for (const [method, path] of routes) {
    const response = await hit(method, path, null);
    assert.equal(response.status, path.startsWith('/api/') ? 401 : 404, `${method} ${path} signed out: the private gate's 401 or the page 404`);
  }
  const off = {...env, TEXT_ADVISOR_ENABLED: 'false'};
  for (const [method, path] of routes) assert.equal((await hit(method, path, ADMIN, off)).status, 404, `${method} ${path} while the advisor is off`);
  // The admin passes; a POST without an allowed Origin does not.
  assert.equal((await post(real, env, `/api/admin/reviews/${review}`, ADMIN, {decision: 'approve'}, {Origin: 'https://attacker.test'})).status, 400);
  assert.equal(reviewOf(sql, review).status, 'open', 'a rejected Origin changes nothing');
  assert.equal((await get(real, env, '/api/admin/reviews', ADMIN)).status, 200);
  assert.equal(sql.prepare("SELECT publish_state FROM advisor_media WHERE id='p1'").get().publish_state, 'queued', 'no decision was applied by the non-admin attempts');
});

dbTest('/api/session says is_admin (and nothing more about the role); /admin redirects and /admin.html is the uncached shell for an admin', async () => {
  const {env, real} = setup();
  const session = async owner => (await get(real, env, '/api/session', owner)).json();
  assert.equal((await session(ADMIN)).is_admin, true);
  assert.equal((await session(OTHER)).is_admin, false);
  assert.equal((await session(null)).is_admin, false);
  assert.ok(!JSON.stringify(await session(ADMIN)).includes('"role"'), '02: never exposed beyond is_admin');
  const redirect = await get(real, env, '/admin', ADMIN);
  assert.equal(redirect.status, 302);
  assert.equal(redirect.headers.get('Location'), '/admin.html');
  const shell = await get(real, env, '/admin.html', ADMIN);
  assert.equal(shell.status, 200);
  assert.equal(await shell.text(), 'shell:/admin.0123456789');
  assert.equal(shell.headers.get('Cache-Control'), 'no-store');
});

// ---- the queue ---------------------------------------------------------------------------

dbTest('the queue lists newest first, 50 a page with a cursor, filters by kind and status, and refuses unknown filters', async () => {
  const {sql, env, real} = setup();
  addContact(sql, {id: 'c1'});
  for (let i = 0; i < 52; i++) await addReview(sql, i % 2 ? 'conversation' : 'rule', `ref-${i}`, 'refused', T0 + i * 60000);
  const first = await (await get(real, env, '/api/admin/reviews', ADMIN)).json();
  assert.equal(first.items.length, PAGE_SIZE);
  assert.ok(first.next);
  assert.deepEqual(first.items.slice(0, 2).map(i => i.ref_id), ['ref-51', 'ref-50'], 'newest first');
  const second = await (await get(real, env, `/api/admin/reviews?cursor=${first.next}`, ADMIN)).json();
  assert.deepEqual(second.items.map(i => i.ref_id), ['ref-1', 'ref-0']);
  assert.equal(second.next, null);
  const rules = await (await get(real, env, '/api/admin/reviews?kind=rule', ADMIN)).json();
  assert.ok(rules.items.length === 26 && rules.items.every(i => i.kind === 'rule'));
  sql.prepare("UPDATE advisor_reviews SET status='rejected' WHERE ref_id='ref-51'").run();
  assert.deepEqual((await (await get(real, env, '/api/admin/reviews?status=rejected', ADMIN)).json()).items.map(i => i.ref_id), ['ref-51']);
  assert.equal((await (await get(real, env, '/api/admin/reviews?status=all', ADMIN)).json()).items[0].ref_id, 'ref-51');
  for (const bad of ['status=closed', 'kind=phone', 'kind=media%27']) assert.equal((await get(real, env, `/api/admin/reviews?${bad}`, ADMIN)).status, 400, bad);
  assert.equal(decodeCursor('not a cursor'), null);
  assert.deepEqual(decodeCursor(encodeCursor({opened_at: iso(T0), id: 'a'.repeat(32)})), {opened_at: iso(T0), id: 'a'.repeat(32)});
});

dbTest('each kind carries what its card needs, and no phone number or hash reaches the browser', async () => {
  const {sql, env, real} = setup();
  addContact(sql, {id: 'c1', role: 'skipper', boat_id: 'b1', display_name: 'Rita', phone_hash: 'HASH-SECRET', phone_enc: 'ENC-SECRET'});
  addBoat(sql, {id: 'b1', slug: 'rita-g', name: 'Rita G', landing: "Virg's", instagram: 'ritag', owner: 'c1'});
  for (let i = 1; i <= 8; i++) addMessage(sql, 'c1', i % 2 ? 'in' : 'out', `message ${i}`, T0 + i * 1000, i === 8 ? {created_by: ADMIN} : {});
  const flagged = addMessage(sql, 'c1', 'in', 'is it legal to keep a cowcod', T0 + 9000, {id: 'flagged-1'});
  addMedia(sql, {id: 'p1', boat: 'b1', has_person: 1, credit: 'Rita G', classification: JSON.stringify({classify: {kind: 'fish', kind_confidence: 0.91, has_person: true, person_confidence: 0.88, nsfw: false, provider: 'claude', model: 'x', ms: 3}})});
  addReport(sql, {id: 'r1', boat: 'b1', counts: [{species_key: 'lingcod', label: 'lings', kept: 12, released: 2}, {species_key: 'other', label: 'reds', kept: 40, released: null, uncertain: true}]});
  const ids = {
    media: await addReview(sql, 'media', 'p1', 'has_person', T0 + 1),
    report: await addReview(sql, 'report', 'r1', 'unverified_boat', T0 + 2),
    skipper: await addReview(sql, 'skipper', 'b1', 'new_skipper', T0 + 3),
    conversation: await addReview(sql, 'conversation', flagged, 'refused', T0 + 4),
    post: await addReview(sql, 'post', 'post-1', 'social_draft', T0 + 5),
  };
  const response = await get(real, env, '/api/admin/reviews', ADMIN), text = await response.text();
  assert.doesNotMatch(text, /SECRET/, 'phone_enc and phone_hash never leave the server');
  const by = Object.fromEntries(JSON.parse(text).items.map(i => [i.kind, i]));
  assert.deepEqual(Object.keys(by).sort(), ['conversation', 'media', 'post', 'report', 'skipper']);
  const m = by.media.detail.media;
  assert.equal(m.thumb, '/api/admin/media/p1');
  assert.equal(m.has_person, true);
  assert.deepEqual(m.labels, {kind: 'fish', kind_confidence: 0.91, has_person: true, person_confidence: 0.88, nsfw: false, provider: 'claude'});
  assert.deepEqual(m.boat, {id: 'b1', name: 'Rita G', slug: 'rita-g'});
  const r = by.report.detail.report;
  assert.deepEqual(r.counts.map(c => [c.label, c.kept, c.released]), [['lings', 12, 2], ['reds', 40, null]]);
  assert.deepEqual([r.anglers, r.status, r.version, r.boat.name, r.boat.status], [20, 'pending_confirm', 1, 'Rita G', 'pending']);
  const s = by.skipper.detail;
  assert.deepEqual([s.boat.name, s.boat.landing, s.boat.instagram, s.contact.channel, s.contact.display_name], ['Rita G', "Virg's", 'ritag', 'imessage', 'Rita']);
  assert.deepEqual(s.messages, ['message 1', 'message 3', 'message 5'], 'the first three inbound messages, bodies only');
  const c = by.conversation.detail;
  assert.equal(c.messages.length, 6);
  assert.deepEqual(c.messages.map(x => x.body), ['message 4', 'message 5', 'message 6', 'message 7', 'message 8', 'is it legal to keep a cowcod'], 'the last six, oldest first');
  assert.deepEqual(c.messages.map(x => x.team), [false, false, false, false, true, false], 'a team reply is marked');
  assert.equal(c.flagged_message, flagged);
  assert.equal(by.post.detail, null, 'a post review whose post is gone has no detail (TA-S1 renders existing drafts: test_advisor_social_drafts.mjs)');
  assert.equal(by.media.id, ids.media);
});

// ---- decisions ---------------------------------------------------------------------------

dbTest('media: approve sets approved, a repeat changes nothing, reject sets rejected, edit sets the credit and approves', async () => {
  const {sql, env, real} = setup();
  addContact(sql, {id: 'c1'});
  for (const id of ['p1', 'p2', 'p3']) addMedia(sql, {id});
  const [a, b, c] = [await addReview(sql, 'media', 'p1', 'has_person'), await addReview(sql, 'media', 'p2', 'angler_photo'), await addReview(sql, 'media', 'p3', 'angler_photo')];
  const decide = (id, body) => quiet(() => post(real, env, `/api/admin/reviews/${id}`, ADMIN, body)).then(x => x.value);
  const first = await decide(a, {decision: 'approve', note: '  fine  '});
  assert.equal(first.status, 200);
  const body = await first.json();
  assert.deepEqual([body.review.status, body.review.decided_by, body.review.note, body.sends], ['approved', ADMIN, 'fine', 0]);
  assert.equal(sql.prepare("SELECT publish_state FROM advisor_media WHERE id='p1'").get().publish_state, 'approved');
  const decidedAt = reviewOf(sql, a).decided_at;
  const again = await (await decide(a, {decision: 'reject'})).json();
  assert.deepEqual([again.repeated, again.review.status], [true, 'approved'], 'idempotent: the first decision stands');
  assert.equal(reviewOf(sql, a).decided_at, decidedAt);
  assert.equal(sql.prepare("SELECT publish_state FROM advisor_media WHERE id='p1'").get().publish_state, 'approved');
  assert.equal((await decide(b, {decision: 'reject'})).status, 200);
  assert.equal(sql.prepare("SELECT publish_state FROM advisor_media WHERE id='p2'").get().publish_state, 'rejected');
  assert.equal((await decide(c, {decision: 'edit', patch: {}})).status, 400, 'an edit without a credit is refused');
  assert.equal((await decide(c, {decision: 'edit', patch: {credit: 'Capt. Lu / Lucero'}})).status, 200);
  assert.deepEqual({...sql.prepare("SELECT publish_state,credit FROM advisor_media WHERE id='p3'").get()}, {publish_state: 'approved', credit: 'Capt. Lu / Lucero'});
  assert.equal(reviewOf(sql, c).status, 'edited');
  const fresh = await addReview(sql, 'media', 'p4', 'has_person');
  for (const bad of [{decision: 'publish'}, {}, {decision: 'approve', reply: 'hi'}]) assert.equal((await decide(fresh, bad)).status, 400, JSON.stringify(bad));
  assert.equal(reviewOf(sql, fresh).status, 'open', 'a refused decision changes nothing');
  assert.equal((await decide('f'.repeat(32), {decision: 'approve'})).status, 404, 'an unknown review');
});

dbTest('media: an approve (and an edit) requests the media job for public.jpg; a reject does not', async () => {
  const {sql, env} = setup({env: {GITHUB_TOKEN: 'gh-test'}});
  addContact(sql, {id: 'c1'});
  for (const id of ['p1', 'p2', 'p3']) addMedia(sql, {id});
  const dispatched = [];
  const dispatch = async (_env, file) => { dispatched.push(file); return 204; };
  const send = async () => 0;
  const decide = async (ref, decision, now, extra = {}) => (await quiet(async () => decideReview(env, {reviewId: await addReview(sql, 'media', ref, 'angler_photo'), decision, by: ADMIN, inId: 'x', key: 'admin', ...extra}, {now, send, dispatch}))).value;
  assert.equal((await decide('p1', 'reject', T0)).status, 'applied');
  assert.deepEqual(dispatched, [], 'a rejected photo is never derived for publication');
  assert.equal((await decide('p2', 'approve', T0)).status, 'applied');
  assert.deepEqual(dispatched, ['advisor-media.yml']);
  assert.equal((await decide('p3', 'edit', T0 + 2 * 60000, {patch: {credit: 'Rita G'}})).status, 'applied');
  assert.deepEqual(dispatched, ['advisor-media.yml', 'advisor-media.yml'], 'an edit approves too (a minute later: past the throttle)');
});

dbTest('report: edit writes an edits row and bumps the version, approve publishes a pending report, reject unpublishes and bumps the pages version', async () => {
  const {sql, env, real} = setup();
  addContact(sql, {id: 'c1', role: 'skipper', boat_id: 'b1'});
  addBoat(sql, {id: 'b1', slug: 'rita-g', name: 'Rita G', owner: 'c1'});
  addReport(sql, {id: 'r1', boat: 'b1'});
  addReport(sql, {id: 'r2', boat: 'b1', date: '2026-10-03'});
  addReport(sql, {id: 'r3', boat: 'b1', date: '2026-10-02', status: 'published'});
  const [e, p, x] = [await addReview(sql, 'report', 'r1', 'unverified_boat'), await addReview(sql, 'report', 'r2', 'unverified_boat'), await addReview(sql, 'report', 'r3', 'unverified_boat')];
  const decide = (id, body) => quiet(() => post(real, env, `/api/admin/reviews/${id}`, ADMIN, body)).then(x => x.value);
  assert.equal((await decide(e, {decision: 'edit', patch: {phone: '+15555550100'}})).status, 400, 'only report fields');
  const edited = await decide(e, {decision: 'edit', patch: {anglers: 22, counts: [{species_key: 'lingcod', label: 'lings', kept: 14, released: 0}]}});
  assert.equal(edited.status, 200);
  const row = sql.prepare("SELECT * FROM advisor_reports WHERE id='r1'").get();
  assert.deepEqual([row.version, row.anglers, JSON.parse(row.counts_json)[0].kept, row.status], [2, 22, 14, 'pending_confirm']);
  const edit = sql.prepare("SELECT * FROM advisor_report_edits WHERE report_id='r1'").get();
  assert.deepEqual([edit.contact_id, edit.message_id], [null, null], 'a team edit has no contact or message');
  assert.deepEqual(JSON.parse(edit.patch_json).map(c => c.field).sort(), ['anglers', 'counts']);
  assert.equal(reviewOf(sql, e).status, 'edited');
  assert.equal((await (await decide(e, {decision: 'edit', patch: {anglers: 30}})).json()).repeated, true);
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM advisor_report_edits WHERE report_id='r1'").get().n, 1, 'a repeat writes no second edit');

  assert.equal((await decide(p, {decision: 'approve'})).status, 200);
  const published = sql.prepare("SELECT status,published_at,confirmed_at,verified FROM advisor_reports WHERE id='r2'").get();
  assert.equal(published.status, 'published');
  assert.ok(published.published_at);
  assert.equal(published.confirmed_at, null, 'the team publishing is not the skipper confirming');
  const version = Number(sql.prepare('SELECT value FROM job_state WHERE key=?').get(PAGES_VERSION_KEY).value);
  assert.equal((await decide(x, {decision: 'reject'})).status, 200);
  assert.equal(sql.prepare("SELECT status FROM advisor_reports WHERE id='r3'").get().status, 'rejected');
  assert.equal(Number(sql.prepare('SELECT value FROM job_state WHERE key=?').get(PAGES_VERSION_KEY).value), version + 1, 'pages re-render without it');
});

dbTest('pages version: every admin-app decision that changes a public page bumps advisor.pages.version (TA-W1); one that changes nothing does not', async () => {
  const {sql, env, withChannel} = setup();
  addContact(sql, {id: 'c1', role: 'skipper', boat_id: 'b1'});
  addBoat(sql, {id: 'b1', slug: 'rita-g', name: 'Rita G', owner: 'c1'});
  addBoat(sql, {id: 'b2', slug: 'lucero', name: 'Lucero'});
  for (const id of ['p1', 'p2', 'p3']) addMedia(sql, {id, boat: 'b1'});
  addReport(sql, {id: 'r1', boat: 'b1', date: '2026-10-03'});
  addReport(sql, {id: 'r2', boat: 'b1', date: '2026-10-02', status: 'published'});
  addReport(sql, {id: 'r3', boat: 'b1', date: '2026-10-01', status: 'published'});
  const version = () => Number(sql.prepare('SELECT value FROM job_state WHERE key=?').get(PAGES_VERSION_KEY)?.value ?? 0);
  const decide = async (kind, ref, reason, body) => {
    const id = await addReview(sql, kind, ref, reason);
    const r = (await quiet(() => post(withChannel, env, `/api/admin/reviews/${id}`, ADMIN, body))).value;
    assert.equal(r.status, 200, `${kind} ${ref} ${body.decision}`);
  };
  const steps = [
    ['media', 'p1', 'angler_photo', {decision: 'approve'}, 'a photo approved'],
    ['media', 'p2', 'angler_photo', {decision: 'edit', patch: {credit: 'Capt. Lu'}}, 'a photo credited and approved'],
    ['media', 'p1', 'has_person', {decision: 'reject'}, 'an approved photo taken back'],
    ['skipper', 'b1', 'new_skipper', {decision: 'approve'}, 'a boat verified'],
    ['skipper', 'b2', 'new_skipper', {decision: 'reject'}, 'a boat rejected'],
    ['report', 'r1', 'low_confidence', {decision: 'approve'}, 'a report published'],
    ['report', 'r2', 'low_confidence', {decision: 'edit', patch: {anglers: 12}}, 'a published report edited'],
    ['report', 'r3', 'low_confidence', {decision: 'reject'}, 'a published report rejected'],
  ];
  for (const [kind, ref, reason, body, what] of steps) {
    const before = version();
    await decide(kind, ref, reason, body);
    assert.ok(version() > before, `${what} bumps the pages version`);
  }
  const before = version();
  await decide('media', 'p3', 'has_person', {decision: 'reject'});
  await decide('rule', 'x', 'rule_source_changed', {decision: 'approve'});
  await decide('skipper', 'b1', 'owner_forgotten', {decision: 'approve'});
  assert.equal(version(), before, 'a queued photo rejected (never public), a rule review and an owner_forgotten review change no page');
});

dbTest('skipper: verify sets verified, verified_at and verified_by and texts the skipper once through their channel; reject texts the reject line', async () => {
  const {sql, env, ch, withChannel} = setup();
  addContact(sql, {id: 'c1', role: 'skipper', boat_id: 'b1'});
  addContact(sql, {id: 'c2', role: 'skipper', boat_id: 'b2', language: 'es'});
  addBoat(sql, {id: 'b1', slug: 'rita-g', name: 'Rita G', owner: 'c1'});
  addBoat(sql, {id: 'b2', slug: 'lucero', name: 'Lucero', owner: 'c2'});
  const [v, r] = [await addReview(sql, 'skipper', 'b1', 'new_skipper'), await addReview(sql, 'skipper', 'b2', 'new_skipper')];
  const decide = (id, body) => quiet(() => post(withChannel, env, `/api/admin/reviews/${id}`, ADMIN, body)).then(x => x.value);
  assert.equal((await decide(v, {decision: 'edit', patch: {name: 'x'}})).status, 400, 'boat fields are edited in the Skippers view (TA-W3)');
  const verified = await (await decide(v, {decision: 'approve'})).json();
  assert.equal(verified.sends, 1);
  const boat = sql.prepare("SELECT status,verified_at,verified_by FROM advisor_boats WHERE id='b1'").get();
  assert.deepEqual([boat.status, boat.verified_by], ['verified', ADMIN]);
  assert.ok(boat.verified_at);
  assert.deepEqual(ch.sent.map(m => [m.to, m.text]), [['ENC-c1', 'Rita G is verified. Your page: skippercast.com/boats/rita-g']]);
  const out = sql.prepare("SELECT * FROM advisor_messages WHERE direction='out' AND contact_id='c1'").get();
  assert.deepEqual([out.status, out.created_by, out.in_reply_to, out.id], ['sent', ADMIN, v, await outboundId(v, 'admin.skipper')]);
  assert.equal((await (await decide(v, {decision: 'approve'})).json()).repeated, true);
  assert.equal(ch.sent.length, 1, 'a repeat sends nothing');
  assert.equal((await decide(r, {decision: 'reject'})).status, 200);
  assert.equal(sql.prepare("SELECT status FROM advisor_boats WHERE id='b2'").get().status, 'rejected');
  assert.equal(ch.sent.at(-1).to, 'ENC-c2');
  assert.equal(ch.sent.at(-1).text, t('es', 'boat_rejected', {name: 'Lucero', slug: 'lucero'}), "05's reject line, in the skipper's language");
  // owner_forgotten has no boat change: approve only records that someone looked.
  const forgotten = await addReview(sql, 'skipper', 'b1', 'owner_forgotten');
  assert.equal((await decide(forgotten, {decision: 'approve'})).status, 200);
  assert.equal(ch.sent.length, 2);
});

dbTest('conversation: "reply as team" sends through the channel as an out row with created_by; a repeat sends nothing; STOP and replies-off are refused', async () => {
  const {sql, env, ch, withChannel} = setup();
  addContact(sql, {id: 'c1'});
  addContact(sql, {id: 'c2', status: 'stopped'});
  const flagged = addMessage(sql, 'c1', 'in', 'can I keep a cowcod', T0, {id: 'flag-1'});
  const flagged2 = addMessage(sql, 'c2', 'in', 'help', T0, {id: 'flag-2'});
  const [a, b] = [await addReview(sql, 'conversation', flagged, 'refused'), await addReview(sql, 'conversation', flagged2, 'low_confidence')];
  const decide = (id, body, e = env) => quiet(() => post(withChannel, e, `/api/admin/reviews/${id}`, ADMIN, body)).then(x => x.value);
  assert.equal((await decide(a, {reply: 'Cowcod are closed to retention statewide. Release it.'}, {...env, ADVISOR_REPLIES_ENABLED: 'false'})).status, 409, 'nothing goes out while replies are off');
  assert.equal(reviewOf(sql, a).status, 'open');
  const sent = await (await decide(a, {reply: '  Cowcod are closed to retention statewide. Release it.  '})).json();
  assert.equal(sent.sends, 1);
  assert.deepEqual(ch.sent.map(m => [m.to, m.text]), [['ENC-c1', 'Cowcod are closed to retention statewide. Release it.']]);
  const out = sql.prepare("SELECT * FROM advisor_messages WHERE direction='out' AND contact_id='c1'").get();
  assert.deepEqual([out.created_by, out.in_reply_to, out.status, out.body], [ADMIN, flagged, 'sent', 'Cowcod are closed to retention statewide. Release it.']);
  assert.equal((await (await decide(a, {reply: 'Cowcod are closed to retention statewide. Release it.'})).json()).repeated, true);
  assert.equal(ch.sent.length, 1);
  assert.equal((await decide(b, {reply: 'hello'})).status, 409, 'STOP means no outbound of any kind');
  assert.equal(ch.sent.length, 1);
  assert.equal((await decide(b, {decision: 'reject'})).status, 200, 'dismissing needs no text');
  const post_ = await addReview(sql, 'post', 'post-1', 'social_draft');
  const gone = await decide(post_, {decision: 'approve'});
  assert.equal(gone.status, 409, 'TA-S1 decides post reviews; one whose post is gone is a conflict');
  assert.match((await gone.json()).error, /no longer exists/);
});

dbTest('the text admin and the queue share one decision path: decideReview with kinds limits the text admin to skipper and media', async () => {
  const {sql, env, ch} = setup();
  addContact(sql, {id: 'c1'});
  const flagged = addMessage(sql, 'c1', 'in', 'x', T0, {id: 'flag-1'});
  const conversation = await addReview(sql, 'conversation', flagged, 'refused');
  const send = teamSender(env, {channelFor: () => ch});
  const textAdmin = await decideReview(env, {reviewId: conversation, decision: 'approve', by: null, kinds: ['skipper', 'media'], inId: 'in-1', key: '0'}, {now: T0, send});
  assert.equal(textAdmin.status, 'not-found');
  addMedia(sql, {id: 'p1'});
  const media = await addReview(sql, 'media', 'p1', 'has_person');
  const {value: outcome} = await quiet(() => decideReview(env, {reviewId: media, decision: 'approve', note: 'text admin', by: null, kinds: ['skipper', 'media'], inId: 'in-1', key: '0'}, {now: T0, send}));
  assert.deepEqual([outcome.status, outcome.review.status, outcome.review.note, outcome.review.decided_by], ['applied', 'approved', 'text admin', null]);
});

// ---- media bytes and health ----------------------------------------------------------------

dbTest('the media route serves admins only: thumb.jpg, then public.jpg, then a viewable original; ?v=original the stored original', async () => {
  const {sql, env, real} = setup();
  addContact(sql, {id: 'c1'});
  addMedia(sql, {id: 'p1'});
  addMedia(sql, {id: 'h1', mime: 'image/heic', r2_key: 'advisor/media/c1/h1.heic'});
  addMedia(sql, {id: 'gone', r2_key: ''});
  const bucket = env.ADVISOR_MEDIA, put = (key, text) => bucket.objects.set(key, {bytes: new TextEncoder().encode(text), httpMetadata: {}});
  put('advisor/media/c1/p1.jpg', 'ORIGINAL');
  put('advisor/media/c1/h1.heic', 'HEIC');
  const body = async (path, owner = ADMIN) => { const r = await get(real, env, path, owner); return [r.status, r.status === 200 ? await r.text() : null, r.headers.get('Content-Type'), r.headers.get('Cache-Control')]; };
  assert.deepEqual(await body('/api/admin/media/p1'), [200, 'ORIGINAL', 'image/jpeg', 'private, no-store']);
  put(derivedKey('p1'), 'PUBLIC');
  assert.equal((await body('/api/admin/media/p1'))[1], 'PUBLIC');
  put(thumbKey('p1'), 'THUMB');
  assert.equal((await body('/api/admin/media/p1'))[1], 'THUMB');
  assert.equal((await body('/api/admin/media/p1?v=original'))[1], 'ORIGINAL');
  assert.equal((await body('/api/admin/media/h1'))[0], 404, 'a HEIC original is not shown inline until the media job derives a JPEG');
  addMedia(sql, {id: 'r1', r2_key: 'advisor/media/c1/r1.jpg'});
  sql.prepare("UPDATE advisor_media SET orientation=6 WHERE id='r1'").run();
  put('advisor/media/c1/r1.jpg', 'SIDEWAYS');
  assert.equal((await body('/api/admin/media/r1'))[0], 404, 'nor a JPEG stored sideways (orientation 6) until the job writes its upright thumb.jpg');
  assert.equal((await body('/api/admin/media/r1?v=original'))[1], 'SIDEWAYS', 'the original is still there on request');
  put(thumbKey('r1'), 'UPRIGHT');
  assert.equal((await body('/api/admin/media/r1'))[1], 'UPRIGHT');
  assert.deepEqual((await body('/api/admin/media/h1?v=original')).slice(0, 3), [200, 'HEIC', 'image/heic']);
  assert.equal((await body('/api/admin/media/gone'))[0], 404);
  assert.equal((await body('/api/admin/media/nope'))[0], 404);
  assert.equal((await body('/api/admin/media/p1', OTHER))[0], 404);
});

dbTest('health: relay state, queued messages older than 2 minutes, held outbound, vision providers (configured, skip, last answer), today\'s caps, open reviews; Meta not configured (TA-S0)', async () => {
  const {sql, env, real} = setup();
  const now = Date.now(), day = Math.floor(now / 86400000);
  addContact(sql, {id: 'c1'});
  addMessage(sql, 'c1', 'in', 'old', now - 5 * 60000, {status: 'queued'});
  addMessage(sql, 'c1', 'in', 'new', now - 30000, {status: 'queued'});
  addMessage(sql, 'c1', 'out', 'held', now - 60000, {status: 'held'});
  sql.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?)').run(RELAY_KEY, JSON.stringify({state: 'down', failures: 4, checked_at: iso(now - 60000), last_ok_at: iso(now - 3600000)}), iso(now));
  sql.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?)').run(downKey('hermes'), iso(now + 300000), iso(now));
  sql.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?)').run(lastOkKey('claude'), iso(now - 120000), iso(now - 120000));
  sql.prepare('INSERT INTO request_limits(id,count,expires_at) VALUES(?,?,?)').run(`global:advisor-llm:${day}`, 17, (day + 2) * 86400);
  sql.prepare('INSERT INTO request_limits(id,count,expires_at) VALUES(?,?,?)').run(`global:vision:${day}`, 3, (day + 2) * 86400);
  await addReview(sql, 'rule', 'x', 'rule_source_changed');
  // TA-M1 mediaJobPending: queued and sideways images without derived_at, and pending graphics, wait for the job.
  addMedia(sql, {id: 'q1', state: 'queued'});
  addMedia(sql, {id: 's1', state: 'private'});
  sql.prepare("UPDATE advisor_media SET orientation=6 WHERE id='s1'").run();
  addMedia(sql, {id: 'd1', state: 'approved'});
  sql.prepare("UPDATE advisor_media SET derived_at=? WHERE id='d1'").run(iso(now));
  addMedia(sql, {id: 'e1', state: 'private'});
  sql.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?)').run('advisor.graphic.g1', JSON.stringify({kind: 'daily', data: {}, out_key: 'advisor/posts/p1/daily.jpg', status: 'pending', requested_at: iso(now)}), iso(now));
  const hermesSecrets = {HERMES_VISION_URL: 'https://hermes.example', HERMES_VISION_TOKEN: 'hv-PLACEHOLDER', ANTHROPIC_API_KEY: 'k'};
  const h = await (await get(real, {...env, ...hermesSecrets, ADVISOR_GLOBAL_DAILY_LLM: '100'}, '/api/admin/health', ADMIN)).json();
  assert.deepEqual(h.relay, {state: 'down', failures: 4, checked_at: iso(now - 60000), last_ok_at: iso(now - 3600000)});
  assert.equal(h.queue.stale_queued, 1, 'only the one queued over 2 minutes');
  assert.equal(h.queue.oldest_queued_at, iso(now - 5 * 60000));
  assert.equal(h.queue.held_outbound, 1);
  // TA-V2: configured (secrets set), the skip, and the last answer per provider; never a secret.
  assert.deepEqual(h.vision, [{name: 'hermes', configured: true, down_until: iso(now + 300000), last_ok_at: null}, {name: 'claude', configured: true, down_until: null, last_ok_at: iso(now - 120000)}]);
  assert.ok(!JSON.stringify(h).includes('hermes.example') && !JSON.stringify(h).includes('hv-PLACEHOLDER'), 'no Hermes URL or token in the answer');
  const bare = await (await get(real, env, '/api/admin/health', ADMIN)).json();
  assert.deepEqual(bare.vision.map(v => [v.name, v.configured]), [['hermes', false], ['claude', false]], 'no secrets: neither is configured');
  assert.equal(visionLine(h.vision[0]), `Skipped until ${when(iso(now + 300000))} · last answer none yet`);
  assert.equal(visionLine(h.vision[1]), `Available · last answer ${when(iso(now - 120000))}`);
  assert.equal(visionLine(bare.vision[0]), 'Not configured');
  assert.deepEqual(h.caps.llm, {used: 17, limit: 100});
  assert.deepEqual(h.caps.vision, {used: 3, limit: 400});
  assert.equal(h.reviews.open, 1);
  assert.equal(h.media_jobs.pending, 3, 'the queued and the sideways image and the graphic; not the derived one or a private upright one');
  assert.deepEqual(h.meta, {configured: false, quota_usage: null, quota_total: null, checked_at: null, error: null}, 'no META_* secrets: no Meta call (test_advisor_meta.mjs covers the quota)');
  assert.deepEqual([h.enabled, h.replies_enabled, h.channel], [true, true, 'bluebubbles']);
});

// ---- the client's keys and strings ---------------------------------------------------------

test('keyboard: a approves, r rejects, e edits on a focused item; never with a modifier or while typing; each kind offers its decisions', () => {
  assert.equal(shortcutFor({key: 'a'}), 'approve');
  assert.equal(shortcutFor({key: 'R'}), 'reject');
  assert.equal(shortcutFor({key: 'e'}), 'edit');
  for (const e of [{key: 'x'}, {key: 'a', ctrlKey: true}, {key: 'a', metaKey: true}, {key: 'a', altKey: true}, {key: 'a', isComposing: true}, {key: 'Enter'},
    {key: 'a', target: {tagName: 'INPUT'}}, {key: 'r', target: {tagName: 'textarea'}}, {key: 'e', target: {tagName: 'DIV', isContentEditable: true}}]) assert.equal(shortcutFor(e), null, JSON.stringify(e));
  assert.ok(typingIn({tagName: 'SELECT'}) && !typingIn({tagName: 'BUTTON'}) && !typingIn(null));
  assert.deepEqual(decisionsFor('media', 'has_person'), ['approve', 'edit', 'reject']);
  assert.deepEqual(decisionsFor('skipper', 'new_skipper'), ['approve', 'reject']);
  assert.deepEqual(decisionsFor('skipper', 'owner_forgotten'), ['approve']);
  assert.deepEqual(decisionsFor('post', 'social_draft'), ['approve', 'edit', 'reject'], 'TA-S1: edit opens the post editor');
  for (const view of ['queue', 'skippers', 'rules', 'posts', 'funnel', 'health']) assert.ok(ADMIN_COPY.views[view], view);
  for (const kind of ['media', 'report', 'post', 'skipper', 'conversation', 'rule']) assert.ok(ADMIN_COPY.kinds[kind], kind);
});
