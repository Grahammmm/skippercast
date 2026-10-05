// Text Advisor admin Skippers and Contacts (TA-W3; docs/plans/text-advisor/08-website.md
// § Admin, Skippers and Contacts; 05 § Crew and § Verification): the gate on every
// new route, the boats list, edits with the registration's validation, verify and
// reject (through the open review or directly, texting once), the consent note,
// crew removal, the invite (number hashed on receipt, never echoed or logged, the
// registration flow started, 20 a day, refused for stopped or blocked contacts and
// while replies are off), the contact view (no number, last 50 messages), the
// export and block/unblock. Offline: real migrations in node:sqlite, real session
// cookies (fixtures/test-sessions.mjs) and a recording channel.
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
const {adminRoutes} = await import('../server/routes/admin.ts');
const {reviewId, deriveKeys, phoneHash, decryptPhone} = await import('../server/advisor/contacts.ts');
const {outboundId} = await import('../server/advisor/ids.ts');
const {PAGES_VERSION_KEY} = await import('../server/advisor/intake/reports.ts');
const {readFlow} = await import('../server/advisor/intake/skippers.ts');
const {INVITES_PER_DAY, inviteOutboundId, boatPatch, NOTE_PREFIX} = await import('../server/advisor/admin/skippers.ts');
const {t} = await import('../server/advisor/strings.ts');
const {routeOf} = await import('../web/admin/route.ts');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const ORIGIN = 'https://skippercast.com';
const ADMIN = 'admin-user-1', OTHER = 'plain-user-1';
const T0 = Date.parse('2026-10-04T18:00:00Z');
const iso = ms => new Date(ms).toISOString();
const KEY = Buffer.alloc(32, 7).toString('base64');
const PHONE = '+18055550142', TYPED = '(805) 555-0142';
const quiet = async fn => { const saved = {log: console.log, warn: console.warn, error: console.error}, lines = []; console.log = console.warn = console.error = (...a) => lines.push(a.join(' ')); try { return {value: await fn(), lines}; } finally { Object.assign(console, saved); } };

function recorder(name = 'bluebubbles') { const sent = []; return {sent, name, async send(m) { sent.push(structuredClone(m)); return {providerId: `${name}-${sent.length}`, status: 'sent'}; }}; }

function setup({env = {}, now = T0} = {}) {
  const {sql, db} = advisorDatabase();
  sql.prepare("INSERT INTO users(id,created_at,role) VALUES(?,?,'admin')").run(ADMIN, iso(T0));
  sql.prepare('INSERT INTO users(id,created_at) VALUES(?,?)').run(OTHER, iso(T0));
  const ch = recorder();
  const app = new Hono({getPath: request => new URL(request.url).pathname});
  app.use('*', context);
  app.use('/api/*', requireUser);
  app.route('/', adminRoutes({channelFor: () => ch, now: () => now}));
  app.onError(onError);
  return {sql, db, ch, real: withSessions(deployed), worker: withSessions({fetch: (request, e, ctx) => app.fetch(request, e, ctx)}),
    env: {TEXT_ADVISOR_ENABLED: 'true', DB: db, ADVISOR_MEDIA: memoryBucket(), ADVISOR_PHONE_KEY: KEY, ...env}};
}
const get = (worker, env, path, owner = ADMIN) => worker.fetch(new Request(ORIGIN + path, {headers: owner ? {'x-test-owner': owner} : {}}), env);
const post = (worker, env, path, body, owner = ADMIN) => worker.fetch(new Request(ORIGIN + path, {method: 'POST',
  headers: {'Content-Type': 'application/json', Origin: ORIGIN, ...(owner ? {'x-test-owner': owner} : {})}, body: JSON.stringify(body)}), env);
const call = async (worker, env, method, path, body) => {
  const {value: response, lines} = await quiet(() => (method === 'GET' ? get(worker, env, path) : post(worker, env, path, body)));
  return {status: response.status, text: await response.text(), headers: response.headers, lines};
};

function addContact(sql, c) {
  sql.prepare(`INSERT INTO advisor_contacts(id,phone_hash,phone_enc,channel,role,language,boat_id,display_name,source,status,last_seen_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)`)
    .run(c.id, c.phone_hash ?? `HASH-${c.id}`, c.phone_enc ?? `ENC-${c.id}`, c.channel ?? 'imessage', c.role ?? 'angler', c.language ?? 'en', c.boat_id ?? null, c.display_name ?? null,
      c.source ?? null, c.status ?? 'active', iso(T0), iso(T0), iso(T0));
}
function addBoat(sql, b) {
  sql.prepare(`INSERT INTO advisor_boats(id,slug,name,landing,port,region,instagram,owner_contact_id,status,consent_photos_at,consent_revoked_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)`)
    .run(b.id, b.slug, b.name, b.landing ?? null, b.port ?? 'morro-bay', 'morro-bay', b.instagram ?? null, b.owner ?? null, b.status ?? 'pending',
      b.consent ?? null, b.revoked ?? null, b.created ?? iso(T0), iso(T0));
}
function addReport(sql, r) {
  sql.prepare(`INSERT INTO advisor_reports(id,boat_id,contact_id,region,port,report_date,counts_json,source,status,verified,version,created_at,updated_at) VALUES(?,?,?,'morro-bay','morro-bay',?,'[]','text',?,0,1,?,?)`)
    .run(r.id, r.boat, r.contact ?? null, r.date, r.status ?? 'published', iso(T0), iso(T0));
}
const boatOf = (sql, id) => ({...sql.prepare('SELECT * FROM advisor_boats WHERE id=?').get(id)});
const version = sql => Number(sql.prepare('SELECT value FROM job_state WHERE key=?').get(PAGES_VERSION_KEY)?.value ?? 0);

// ---- the gate ----------------------------------------------------------------------------

dbTest('every TA-W3 route is a 404 for a non-admin and while the advisor is off, and a 401 signed out', async () => {
  const {sql, env, real} = setup();
  addContact(sql, {id: 'c1'});
  addBoat(sql, {id: 'b1', slug: 'sea-example', name: 'Sea Example', owner: 'c1'});
  const routes = [['GET', '/api/admin/boats'], ['POST', '/api/admin/boats/b1'], ['POST', '/api/admin/boats/invite'], ['POST', '/api/admin/boats/b1/crew/c1/remove'],
    ['GET', '/api/admin/contacts/c1'], ['GET', '/api/admin/contacts/c1/export'], ['POST', '/api/admin/contacts/c1/block']];
  const hit = (method, path, owner, e = env) => quiet(() => (method === 'GET' ? get(real, e, path, owner) : post(real, e, path, {blocked: true, phone: TYPED, status: 'verified'}, owner))).then(x => x.value);
  for (const [method, path] of routes) {
    const response = await hit(method, path, OTHER);
    assert.equal(response.status, 404, `${method} ${path} for a non-admin`);
    assert.doesNotMatch(await response.text(), /admin/i);
    assert.equal((await hit(method, path, null)).status, 401, `${method} ${path} signed out`);
    assert.equal((await hit(method, path, ADMIN, {...env, TEXT_ADVISOR_ENABLED: 'false'})).status, 404, `${method} ${path} while the advisor is off`);
  }
  assert.equal(boatOf(sql, 'b1').status, 'pending', 'nothing was applied');
  assert.equal(sql.prepare("SELECT status FROM advisor_contacts WHERE id='c1'").get().status, 'active');
  assert.equal(sql.prepare('SELECT COUNT(*) AS n FROM advisor_contacts').get().n, 1, 'no invite was stored');
  assert.equal((await hit('GET', '/api/admin/boats', ADMIN)).status, 200, 'the deployed Worker mounts the routes');
});

// ---- the list ----------------------------------------------------------------------------

dbTest('GET /api/admin/boats: pending first, with owner, last report, 30-day reports, posts, consent, crew and the note; no number or hash', async () => {
  const {sql, env, worker} = setup();
  addContact(sql, {id: 'c1', role: 'skipper', boat_id: 'b1', display_name: 'Dana', phone_hash: 'HASH-SECRET', phone_enc: 'ENC-SECRET'});
  addContact(sql, {id: 'c2', role: 'crew', boat_id: 'b1', display_name: 'Deckhand Lu', channel: 'sms'});
  addContact(sql, {id: 'c3', role: 'crew', boat_id: null});
  addBoat(sql, {id: 'b1', slug: 'sea-example', name: 'Sea Example', owner: 'c1', status: 'verified', consent: iso(T0 - 9e6), created: iso(T0 - 9e6)});
  addBoat(sql, {id: 'b2', slug: 'example-two', name: 'Example Two', status: 'pending', created: iso(T0 - 1e6)});
  addBoat(sql, {id: 'b3', slug: 'old-salt', name: 'Old Salt', status: 'rejected', consent: iso(T0 - 9e6), revoked: iso(T0 - 1e6), created: iso(T0)});
  sql.prepare("INSERT INTO advisor_crew(boat_id,contact_id,added_by,added_at) VALUES('b1','c2','c1',?)").run(iso(T0));
  sql.prepare("INSERT INTO advisor_crew(boat_id,contact_id,added_by,added_at,removed_at) VALUES('b1','c3','c1',?,?)").run(iso(T0), iso(T0));
  addReport(sql, {id: 'r1', boat: 'b1', date: '2026-10-03'});
  addReport(sql, {id: 'r2', boat: 'b1', date: '2026-09-20'});
  addReport(sql, {id: 'r3', boat: 'b1', date: '2026-08-01'});
  addReport(sql, {id: 'r4', boat: 'b1', date: '2026-10-04', status: 'rejected'});
  sql.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?)').run(NOTE_PREFIX + 'b1', JSON.stringify({note: 'said yes on the dock', at: iso(T0), by: ADMIN}), iso(T0));
  sql.prepare("INSERT INTO advisor_reviews(id,kind,ref_id,reason,status,opened_at) VALUES(?,'skipper','b2','new_skipper','open',?)").run(await reviewId('skipper', 'b2', 'new_skipper'), iso(T0));
  const {status, text} = await call(worker, env, 'GET', '/api/admin/boats');
  assert.equal(status, 200);
  assert.doesNotMatch(text, /SECRET/, 'no phone_enc or phone_hash leaves the server');
  const {boats} = JSON.parse(text);
  assert.deepEqual(boats.map(b => b.id), ['b2', 'b1', 'b3'], 'pending, verified, rejected');
  const sea = boats[1];
  assert.deepEqual(sea.owner, {id: 'c1', channel: 'imessage', language: 'en', display_name: 'Dana', role: 'skipper', status: 'active'});
  assert.deepEqual([sea.last_report_date, sea.reports_30d, sea.posts, sea.consent], ['2026-10-03', 2, 0, 'given'], 'published reports only; the 30 days count back from today');
  assert.deepEqual(sea.crew.map(c => [c.contact_id, c.display_name, c.channel]), [['c2', 'Deckhand Lu', 'sms']], 'active crew only');
  assert.equal(sea.consent_note.note, 'said yes on the dock');
  assert.deepEqual([boats[0].owner, boats[0].last_report_date, boats[0].reports_30d, boats[0].consent, boats[0].review_open], [null, null, 0, 'not given', true]);
  assert.equal(boats[2].consent, 'revoked');
});

// ---- edits -------------------------------------------------------------------------------

test('boatPatch uses the registration parsers: catalog ports, handles, https links and phones; null clears an optional field', () => {
  assert.deepEqual(boatPatch({name: ' "Sea Example II" ', port: 'Morro', instagram: '@Sea.Example', booking_url: 'https://sea.example/book', landing: null, phone_public: TYPED}).fields,
    {name: 'Sea Example II', port: 'morro-bay', region: 'morro-bay', instagram: 'sea.example', booking_url: 'https://sea.example/book', landing: null, phone_public: PHONE});
  for (const bad of [{port: 'Atlantis'}, {instagram: 'no spaces allowed'}, {booking_url: 'http://insecure.example'}, {phone_public: '12'}, {name: ''}, {name: 'x'.repeat(61)},
    {slug: 'new-slug'}, {status: 'verified'}, {owner_contact_id: 'c9'}, {name: 7}])
    assert.ok('error' in boatPatch(bad), JSON.stringify(bad));
  assert.ok('error' in boatPatch([]));
});

dbTest('POST /api/admin/boats/<id>: fields validated like registration, the slug kept, the pages version bumped; the consent note is a note only', async () => {
  const {sql, env, worker} = setup();
  addContact(sql, {id: 'c1', role: 'skipper', boat_id: 'b1'});
  addBoat(sql, {id: 'b1', slug: 'sea-example', name: 'Sea Example', owner: 'c1'});
  const v0 = version(sql);
  const bad = await call(worker, env, 'POST', '/api/admin/boats/b1', {fields: {instagram: 'not a handle!'}});
  assert.equal(bad.status, 400);
  assert.match(JSON.parse(bad.text).error, /instagram/);
  assert.equal((await call(worker, env, 'POST', '/api/admin/boats/b1', {status: 'pending'})).status, 400);
  assert.equal(version(sql), v0, 'a refused edit changes nothing');
  const ok = await call(worker, env, 'POST', '/api/admin/boats/b1', {fields: {name: 'Sea Example II', landing: "Gull's", instagram: '@seaexample', port: 'Avila'}});
  assert.equal(ok.status, 200, ok.text);
  const row = boatOf(sql, 'b1');
  assert.deepEqual([row.name, row.slug, row.landing, row.instagram, row.port, row.region], ['Sea Example II', 'sea-example', "Gull's", 'seaexample', 'port-san-luis', 'morro-bay'],
    'the slug stays (links already texted keep working); "Avila" is the catalog alias of Port San Luis');
  assert.equal(boatOf(sql, 'b1').region, 'morro-bay');
  const moved = await call(worker, env, 'POST', '/api/admin/boats/b1', {fields: {port: 'Santa Barbara'}});
  assert.deepEqual([JSON.parse(moved.text).boat.port, boatOf(sql, 'b1').region], ['santa-barbara', 'southern-california'], 'the region follows the port');
  assert.ok(version(sql) > v0, 'the boat page re-renders');
  assert.equal(JSON.parse(ok.text).boat.name, 'Sea Example II');

  const noted = await call(worker, env, 'POST', '/api/admin/boats/b1', {consent_note: '  said yes on the dock  '});
  assert.equal(JSON.parse(noted.text).boat.consent_note.note, 'said yes on the dock');
  assert.deepEqual([boatOf(sql, 'b1').consent_photos_at, JSON.parse(noted.text).boat.consent], [null, 'not given'], 'consent itself changes only by the skipper’s text');
  await call(worker, env, 'POST', '/api/admin/boats/b1', {consent_note: null});
  assert.equal(sql.prepare('SELECT COUNT(*) AS n FROM job_state WHERE key=?').get(NOTE_PREFIX + 'b1').n, 0);
  assert.equal((await call(worker, env, 'POST', '/api/admin/boats/nope', {fields: {name: 'X'}})).status, 404);
});

dbTest('verify and reject: the open new_skipper review is decided with the text; without one the boat changes and the text goes out once per status', async () => {
  const {sql, env, worker, ch} = setup();
  addContact(sql, {id: 'c1', role: 'skipper', boat_id: 'b1'});
  addContact(sql, {id: 'c2', role: 'skipper', boat_id: 'b2', language: 'es'});
  addBoat(sql, {id: 'b1', slug: 'sea-example', name: 'Sea Example', owner: 'c1'});
  addBoat(sql, {id: 'b2', slug: 'example-two', name: 'Example Two', owner: 'c2'});
  const review = await reviewId('skipper', 'b1', 'new_skipper');
  sql.prepare("INSERT INTO advisor_reviews(id,kind,ref_id,reason,status,opened_at) VALUES(?,'skipper','b1','new_skipper','open',?)").run(review, iso(T0));
  const verified = await call(worker, env, 'POST', '/api/admin/boats/b1', {status: 'verified'});
  assert.equal(verified.status, 200, verified.text);
  assert.equal(JSON.parse(verified.text).sends, 1);
  assert.deepEqual([boatOf(sql, 'b1').status, boatOf(sql, 'b1').verified_by], ['verified', ADMIN]);
  const r = sql.prepare('SELECT status,decided_by,note FROM advisor_reviews WHERE id=?').get(review);
  assert.deepEqual({...r}, {status: 'approved', decided_by: ADMIN, note: 'skippers view'}, 'the registration review is closed by the same decision');
  assert.deepEqual(ch.sent.map(m => [m.to, m.text]), [['ENC-c1', 'Sea Example is verified. Your page: skippercast.com/boats/sea-example']]);
  assert.equal(sql.prepare("SELECT id FROM advisor_messages WHERE direction='out'").get().id, await outboundId(review, 'admin.skipper'), 'the queue’s outbound id: never texted twice across views');
  const repeat = await call(worker, env, 'POST', '/api/admin/boats/b1', {status: 'verified'});
  assert.deepEqual([repeat.status, JSON.parse(repeat.text).sends, ch.sent.length], [200, 0, 1], 'verifying a verified boat (the review closed) texts nothing more');

  // No open review: the boat is rejected directly, then the same request again texts nothing more.
  for (let i = 0; i < 2; i++) assert.equal((await call(worker, env, 'POST', '/api/admin/boats/b2', {status: 'rejected'})).status, 200);
  assert.equal(boatOf(sql, 'b2').status, 'rejected');
  assert.equal(ch.sent.length, 2);
  assert.equal(ch.sent[1].text, t('es', 'boat_rejected', {name: 'Example Two', slug: 'example-two'}));
  const rejected = await outboundId(await reviewId('skipper', 'b2', 'new_skipper'), 'admin.skipper.rejected');
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM advisor_messages WHERE direction='out' AND id=?").get(rejected).n, 1);
  // Replies off: the boat still changes, nothing is texted.
  const off = {...env, ADVISOR_REPLIES_ENABLED: 'false'};
  const held = await call(worker, off, 'POST', '/api/admin/boats/b2', {status: 'verified'});
  assert.deepEqual([JSON.parse(held.text).held, boatOf(sql, 'b2').status, ch.sent.length], ['replies-off', 'verified', 2]);
});

dbTest('crew removal ends the link (kept for audit) and makes the contact an angler again; unknown pairs are 404', async () => {
  const {sql, env, worker} = setup();
  addContact(sql, {id: 'c1', role: 'skipper', boat_id: 'b1'});
  addContact(sql, {id: 'c2', role: 'crew', boat_id: 'b1'});
  addBoat(sql, {id: 'b1', slug: 'sea-example', name: 'Sea Example', owner: 'c1'});
  sql.prepare("INSERT INTO advisor_crew(boat_id,contact_id,added_by,added_at) VALUES('b1','c2','c1',?)").run(iso(T0));
  const removed = await call(worker, env, 'POST', '/api/admin/boats/b1/crew/c2/remove', {});
  assert.equal(removed.status, 200);
  assert.deepEqual(JSON.parse(removed.text).boat.crew, []);
  assert.equal(sql.prepare("SELECT removed_at FROM advisor_crew WHERE contact_id='c2'").get().removed_at, iso(T0));
  assert.deepEqual({...sql.prepare("SELECT role,boat_id FROM advisor_contacts WHERE id='c2'").get()}, {role: 'angler', boat_id: null});
  assert.equal((await call(worker, env, 'POST', '/api/admin/boats/b1/crew/c2/remove', {})).status, 200, 'a repeat is harmless');
  assert.equal((await call(worker, env, 'POST', '/api/admin/boats/b1/crew/c9/remove', {})).status, 404);
});

// ---- invites -----------------------------------------------------------------------------

dbTest('invite: the number is hashed on receipt and never echoed or logged; the contact is created and the registration starts with the invite text', async () => {
  const {sql, env, worker, ch} = setup();
  const res = await call(worker, env, 'POST', '/api/admin/boats/invite', {phone: TYPED, boat_name: 'Gray Example'});
  assert.equal(res.status, 200, res.text);
  const body = JSON.parse(res.text);
  assert.deepEqual([body.sends, body.created], [1, true]);
  for (const text of [res.text, res.lines.join('\n')]) assert.doesNotMatch(text.replace(/\D/g, ''), /8055550142/, 'the number is neither returned nor logged');
  const keys = await deriveKeys(KEY);
  const contact = sql.prepare('SELECT * FROM advisor_contacts WHERE id=?').get(body.contact_id);
  assert.deepEqual([contact.phone_hash, contact.source, contact.channel, contact.role, contact.status], [await phoneHash(keys, PHONE), 'skipper-invite', 'sms', 'angler', 'active']);
  assert.equal(await decryptPhone(keys, ch.sent[0].to), PHONE, 'sent to the typed number, which the channel decrypts');
  assert.equal(ch.sent[0].text, `${t('en', 'skipper_invite_boat', {boat: 'Gray Example'})} ${t('en', 'register_intro')} ${t('en', 'register_ask_port')}`, 'the name is known, so the port is asked');
  const flow = await readFlow(env.DB, body.contact_id);
  assert.deepEqual([flow.flow, flow.step, flow.draft.name], ['register', 'port', 'Gray Example'], 'the reply answers the registration (TA-I1)');
  const out = sql.prepare("SELECT id,created_by FROM advisor_messages WHERE direction='out'").get();
  assert.deepEqual([out.id, out.created_by], [await inviteOutboundId(body.contact_id, T0), ADMIN]);
  // The same day again: the same contact, no second text.
  const again = JSON.parse((await call(worker, env, 'POST', '/api/admin/boats/invite', {phone: PHONE})).text);
  assert.deepEqual([again.contact_id, again.created, again.sends, ch.sent.length], [body.contact_id, false, 0, 1]);
  // Spanish, with no boat name: the name is asked first.
  const es = JSON.parse((await call(worker, env, 'POST', '/api/admin/boats/invite', {phone: '+18055550143', language: 'es'})).text);
  assert.equal(ch.sent.at(-1).text, `${t('es', 'skipper_invite')} ${t('es', 'register_intro')} ${t('es', 'register_ask_name')}`);
  assert.equal((await readFlow(env.DB, es.contact_id)).step, 'name');
});

dbTest('invite is refused for a bad number, a stopped or blocked contact, an owner, while replies are off, without the key, and past 20 a day', async () => {
  const {sql, env, worker, ch} = setup();
  const keys = await deriveKeys(KEY);
  addContact(sql, {id: 'stopped', status: 'stopped', phone_hash: await phoneHash(keys, '+18055550150')});
  addContact(sql, {id: 'blocked', status: 'blocked', phone_hash: await phoneHash(keys, '+18055550151')});
  addContact(sql, {id: 'owner', role: 'skipper', boat_id: 'b1', phone_hash: await phoneHash(keys, '+18055550152')});
  addBoat(sql, {id: 'b1', slug: 'sea-example', name: 'Sea Example', owner: 'owner'});
  const invite = async (body, e = env) => call(worker, e, 'POST', '/api/admin/boats/invite', body);
  assert.equal((await invite({phone: '555'})).status, 400);
  assert.equal((await invite({phone: TYPED, boat_name: 'x'.repeat(61)})).status, 400);
  for (const n of ['+18055550150', '+18055550151', '+18055550152']) assert.equal((await invite({phone: n})).status, 409, n);
  assert.equal((await invite({phone: TYPED}, {...env, ADVISOR_REPLIES_ENABLED: 'false'})).status, 409);
  const {ADVISOR_PHONE_KEY: _k, ...keyless} = env;
  assert.equal((await invite({phone: TYPED}, keyless)).status, 503);
  assert.equal(ch.sent.length, 0, 'none of these texted anyone');
  assert.equal(sql.prepare("SELECT status FROM advisor_contacts WHERE id='stopped'").get().status, 'stopped', 'STOP stands');
  const used = sql.prepare("SELECT count FROM request_limits WHERE id LIKE 'admin:skipper-invite:%'").get()?.count ?? 0;
  for (let i = used; i < INVITES_PER_DAY; i++) assert.equal((await invite({phone: `+1805555${String(1000 + i).padStart(4, '0')}`})).status, 200, `invite ${i + 1}`);
  const over = await invite({phone: '+18055559999'});
  assert.equal(over.status, 409);
  assert.match(JSON.parse(over.text).error, /20 invites a day/);
});

dbTest('invite passes the outbound guard: ADVISOR_GLOBAL_DAILY_COLD caps invites to new numbers, nothing is stored for a refused one, and the admin sees why', async () => {
  const {sql, env, worker, ch} = setup({env: {ADVISOR_GLOBAL_DAILY_COLD: '1'}});
  const keys = await deriveKeys(KEY);
  const invite = body => call(worker, env, 'POST', '/api/admin/boats/invite', body);
  assert.equal((await invite({phone: PHONE})).status, 200);
  const over = await invite({phone: '+18055550143'});
  assert.equal(over.status, 409);
  assert.match(JSON.parse(over.text).error, /ADVISOR_GLOBAL_DAILY_COLD/);
  assert.equal(ch.sent.length, 1, 'the refused invite texted no one');
  assert.equal(sql.prepare('SELECT COUNT(*) AS n FROM advisor_contacts WHERE phone_hash=?').get(await phoneHash(keys, '+18055550143')).n, 0, 'and stored no contact');
  // The first number's same-day repeat is still the no-op it was (one outbound row per contact and day), not a refusal.
  assert.equal((await invite({phone: PHONE})).status, 200);
  assert.equal(ch.sent.length, 1);
});

// ---- contacts ----------------------------------------------------------------------------

dbTest('GET /api/admin/contacts/<id>: by id only, no number or hash, boats, the last 50 messages oldest first, and the export link', async () => {
  const {sql, env, worker} = setup();
  addContact(sql, {id: 'c1', role: 'skipper', boat_id: 'b1', display_name: 'Dana', source: 'skipper-invite', phone_hash: 'HASH-SECRET', phone_enc: 'ENC-SECRET'});
  addBoat(sql, {id: 'b1', slug: 'sea-example', name: 'Sea Example', owner: 'c1'});
  for (let i = 1; i <= 55; i++) sql.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,body,intent,status,media_json,created_at,created_by) VALUES(?,?,?,?,?,?,?,?,?,?)`)
    .run(`m${i}`, 'c1', i % 2 ? 'in' : 'out', 'imessage', `message ${i}`, i % 2 ? 'advice' : null, i % 2 ? 'done' : 'sent', i === 55 ? '["p1","p2"]' : null, iso(T0 + i * 1000), i === 54 ? ADMIN : null);
  const {status, text} = await call(worker, env, 'GET', '/api/admin/contacts/c1');
  assert.equal(status, 200);
  assert.doesNotMatch(text, /SECRET/);
  const d = JSON.parse(text);
  assert.deepEqual([d.contact.display_name, d.contact.source, d.contact.status, d.contact.role], ['Dana', 'skipper-invite', 'active', 'skipper']);
  assert.deepEqual(d.boats, [{id: 'b1', name: 'Sea Example', slug: 'sea-example', status: 'pending', relation: 'owner'}]);
  assert.equal(d.messages.length, 50);
  assert.deepEqual([d.messages[0].body, d.messages.at(-1).body, d.messages.at(-1).media, d.messages.at(-2).team], ['message 6', 'message 55', 2, true]);
  assert.equal(d.export, '/api/admin/contacts/c1/export');
  assert.equal((await call(worker, env, 'GET', '/api/admin/contacts/nobody')).status, 404);
  assert.equal((await call(worker, env, 'GET', '/api/admin/contacts')).status, 404, 'there is no list or search');
  assert.equal((await call(worker, env, 'GET', `/api/admin/contacts?phone=${encodeURIComponent(PHONE)}`)).status, 404);

  const exported = await call(worker, env, 'GET', '/api/admin/contacts/c1/export');
  assert.equal(exported.status, 200);
  assert.match(exported.headers.get('Content-Disposition'), /^attachment; filename="skippercast-contact-c1\.json"$/);
  assert.equal(exported.headers.get('Cache-Control'), 'private, no-store');
  assert.doesNotMatch(exported.text, /ENC-SECRET/, 'the export never carries the encrypted number');
  assert.equal(JSON.parse(exported.text).messages.length, 55);
});

dbTest('block and unblock: unblocking restores the status the contact had, so STOP stands', async () => {
  const {sql, env, worker} = setup();
  addContact(sql, {id: 'a', status: 'active'});
  addContact(sql, {id: 's', status: 'stopped'});
  const status = id => sql.prepare('SELECT status FROM advisor_contacts WHERE id=?').get(id).status;
  const block = (id, blocked) => call(worker, env, 'POST', `/api/admin/contacts/${id}/block`, {blocked});
  for (const id of ['a', 's']) { assert.equal(JSON.parse((await block(id, true)).text).status, 'blocked'); assert.equal(status(id), 'blocked'); }
  assert.equal((await block('a', true)).status, 200, 'a repeat is harmless');
  assert.deepEqual([JSON.parse((await block('a', false)).text).status, JSON.parse((await block('s', false)).text).status], ['active', 'stopped']);
  assert.equal(JSON.parse((await call(worker, env, 'GET', '/api/admin/contacts/s')).text).contact.blocked_from, null);
  assert.equal((await call(worker, env, 'POST', '/api/admin/contacts/a/block', {blocked: 'yes'})).status, 400);
  assert.equal((await block('nobody', true)).status, 404);
});

test('the admin app routes #contact/<id> by id, and anything else to a view or the queue', () => {
  assert.deepEqual(routeOf('#contact/abc-123'), {view: 'contact', arg: 'abc-123'});
  assert.deepEqual(routeOf('#skippers'), {view: 'skippers', arg: ''});
  for (const hash of ['#contact/', '#contact/a/b', '#contact/%E0%A4%A', '#contact/has space', '#nowhere', '']) assert.equal(routeOf(hash).view, 'queue', hash);
});
