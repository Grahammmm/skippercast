// Skipper registration, consent and crew (server/advisor/intake/skippers.ts, the
// register_boat/add_crew/remove_crew tools and their consumer appliers;
// docs/plans/text-advisor/05-skipper-intake.md § Becoming a skipper, § Consent,
// § Crew, § Verification). The scripted golden conversations 2 (en, es) and 3
// run in tests/test_advisor_engine.mjs; this file covers the parsers, port
// aliases and the nearest-three fallback, slug collisions, the invalid-answer
// and abandoned-flow paths, the 7-day consent re-ask, revoke, crew rules (owner
// only, credited on reply), the text admin verification text, the
// verified/unverified contract and the strings. Offline: real migrations in
// node:sqlite, a recording channel, no model.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
const sk = await import('../server/advisor/intake/skippers.ts');
const {runTurn, engineHandler} = await import('../server/advisor/engine.ts');
const {consumeAdvisor, ADVISOR_QUEUE_NAME} = await import('../server/advisor/consumer.ts');
const {TOOL_BY_NAME} = await import('../server/advisor/tools/index.ts');
const {advisorSettings} = await import('../server/advisor/settings.ts');
const {STRINGS, t} = await import('../server/advisor/strings.ts');
const {deriveKeys, phoneHash, encryptPhone, reviewId} = await import('../server/advisor/contacts.ts');
const {storeInbound} = await import('../server/advisor/inbound.ts');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const T0 = Date.parse('2026-10-03T17:00:00Z');
const HOUR = 3600000, DAY = 24 * HOUR;
const KEY = Buffer.alloc(32, 7).toString('base64');
const ADMIN_ID = 'admin-contact-1';
const iso = ms => new Date(ms).toISOString();
const settings = advisorSettings({});
const quiet = async fn => { const saved = {log: console.log, warn: console.warn, error: console.error}, lines = []; console.log = console.warn = console.error = (...a) => lines.push(a.join(' ')); try { return {value: await fn(), lines}; } finally { Object.assign(console, saved); } };

function setup({contact = {}, env = {}} = {}) {
  const {sql, db} = advisorDatabase();
  const c = {id: 'c1', phone_hash: 'h1', phone_enc: 'ENC', channel: 'imessage', role: 'angler', language: 'en', boat_id: null, display_name: null, home_port: null, ...contact};
  addContact(sql, c);
  sql.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,body,status,created_at) VALUES('seen','c1','in','imessage','earlier','done',?)`).run(iso(T0 - 30 * DAY));
  return {sql, db, env: {TEXT_ADVISOR_ENABLED: 'true', DB: db, ADVISOR_NUMBER: '+15555550199', ADVISOR_PHONE_KEY: KEY, ...env}};
}
function addContact(sql, c) {
  sql.prepare(`INSERT INTO advisor_contacts(id,phone_hash,phone_enc,channel,role,language,boat_id,display_name,home_port,status,last_seen_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,'active',?,?,?)`)
    .run(c.id, c.phone_hash, c.phone_enc, c.channel ?? 'imessage', c.role ?? 'angler', c.language ?? 'en', c.boat_id ?? null, c.display_name ?? null, c.home_port ?? null, iso(T0), iso(T0), iso(T0));
}
function addBoat(sql, b) {
  sql.prepare(`INSERT INTO advisor_boats(id,slug,name,port,region,owner_contact_id,status,consent_photos_at,consent_revoked_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)`)
    .run(b.id, b.slug, b.name, b.port ?? 'morro-bay', 'morro-bay', b.owner ?? null, b.status ?? 'pending', b.consent ?? null, b.revoked ?? null, b.created ?? iso(T0 - 30 * DAY), iso(T0));
}
let seq = 0;
function inbound(sql, body, {contact = 'c1', media = null, at = T0, status = 'processing'} = {}) {
  const id = `in${++seq}`;
  sql.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,body,media_json,status,created_at) VALUES(?,?,'in','imessage',?,?,?,?)`).run(id, contact, body, media ? JSON.stringify(media) : null, status, iso(at));
  return sql.prepare('SELECT * FROM advisor_messages WHERE id=?').get(id);
}
const contactRow = (sql, id = 'c1') => sql.prepare('SELECT * FROM advisor_contacts WHERE id=?').get(id);
const texts = r => r.actions.filter(a => a.type === 'send_text').map(a => a.text);
const run = (env, contact, message, now = T0) => runTurn({env, contact, message, now, deps: {clock: () => now, sleep: async () => {}}});
const setFlow = (sql, contact, state) => sql.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value').run(sk.flowKey(contact), JSON.stringify(state), iso(T0));
const flowOf = (sql, contact = 'c1') => { const r = sql.prepare('SELECT value FROM job_state WHERE key=?').get(sk.flowKey(contact)); return r ? JSON.parse(r.value) : null; };
function recorder(name = 'bluebubbles') { const sent = []; return {sent, name, async send(m) { sent.push(structuredClone(m)); return {providerId: `${name}-${sent.length}`, status: 'sent'}; }}; }
function batchOf(id) { return {queue: ADVISOR_QUEUE_NAME, messages: [{id: 'm', body: {message_id: id}, attempts: 1, ack() {}, retry() {}}], ackAll() {}, retryAll() {}}; }
/** One message through the consumer and the engine, every contact on the recording channel. */
async function consume(env, sql, body, {contact = 'c1', media = null, at = T0, ch = recorder()} = {}) {
  const m = inbound(sql, body, {contact, media, at, status: 'queued'});
  await quiet(() => consumeAdvisor(batchOf(m.id), env, {channelFor: () => ch, handler: engineHandler, now: () => at, engine: {clock: () => at, sleep: async () => {}}}));
  return {m, ch};
}
const toolCtx = (env, db, contact, message = {id: 'in-tool'}) => ({env, contact, message, deps: {}, db, language: contact.language ?? 'en', settings: advisorSettings(env), now: T0});

// ---- parsers -------------------------------------------------------------------------------

test('parsers: name, landing, instagram, booking, skip and start phrases (02 column notes)', () => {
  assert.equal(sk.parseName('  "Rita G"  '), 'Rita G');
  assert.equal(sk.parseName('the NEW Lucero!'), 'the NEW Lucero', 'case kept, trailing ! dropped');
  assert.equal(sk.parseName('x'.repeat(61)), null);
  assert.equal(sk.parseName('skip'), null, 'the name is required');
  assert.equal(sk.parseLanding('Virg\u0007\'s Landing'), "Virg 's Landing");
  assert.equal(sk.parseLanding('y'.repeat(61)), null);
  assert.equal(sk.parseInstagram('@RitaG_Sportfishing'), 'ritag_sportfishing', 'stored lower-case, without @');
  assert.equal(sk.parseInstagram('lucero.psl'), 'lucero.psl');
  for (const bad of ['rita g', '@' + 'a'.repeat(31), 'rita-g', 'https://instagram.com/ritag']) assert.equal(sk.parseInstagram(bad), null, bad);
  assert.deepEqual(sk.parseBooking('https://example.com/book?trip=1'), {booking_url: 'https://example.com/book?trip=1', phone_public: null});
  assert.deepEqual(sk.parseBooking('(805) 555-0100'), {booking_url: null, phone_public: '+18055550100'}, 'a phone is phone_public, never a contact');
  for (const bad of ['http://example.com', 'example.com', 'call me', 'https://user:pw@example.com']) assert.equal(sk.parseBooking(bad), null, bad);
  for (const w of ['skip', 'SKIP.', 'none', 'saltar', 'ninguno', 'n/a']) assert.ok(sk.isSkip(w), w);
  for (const w of ['yes', 'YES', 'ok', 'Sí', 'si', 'y']) assert.ok(sk.isYes(w), w);
  assert.ok(!sk.isYes('yes but not on facebook'));
  assert.deepEqual(sk.startPhrase("I'm the captain of the Rita G"), {language: null, name: 'Rita G'});
  assert.deepEqual(sk.startPhrase('register my boat'), {language: null, name: null});
  assert.deepEqual(sk.startPhrase('Quiero registrar mi barco'), {language: 'es', name: null});
  assert.deepEqual(sk.startPhrase('soy el capitán del Lucero'), {language: 'es', name: 'Lucero'});
  for (const no of ['the captain said lings were good', 'what boat should I register for?', 'is the Rita G running?']) assert.equal(sk.startPhrase(no), null, no);
});

test('ports: catalog names and the 05 aliases match; anything else gets the three nearest ports, numbered', () => {
  const table = {'MB': 'morro-bay', 'Morro': 'morro-bay', 'morro bay': 'morro-bay', 'Cayucos': 'morro-bay', 'Avila': 'port-san-luis', 'Avila Beach': 'port-san-luis',
    'Port San Luis': 'port-san-luis', 'PSL': 'port-san-luis', 'port-san-luis': 'port-san-luis', 'Santa Barbara': 'santa-barbara', 'Fort Bragg': 'noyo-harbor'};
  for (const [answer, port] of Object.entries(table)) assert.equal(sk.parsePort(answer), port, answer);
  assert.equal(sk.parsePort('Atlantis'), null);
  const nearest = sk.nearestPorts({home_port: null}, settings);
  assert.deepEqual(nearest, ['morro-bay', 'port-san-luis', 'santa-barbara'], 'from the default region\'s first port');
  assert.deepEqual(sk.nearestPorts({home_port: 'monterey'}, settings), ['monterey', 'santa-cruz', 'pillar-point'], 'from the home port');
  assert.equal(sk.parsePort('2', nearest), 'port-san-luis', 'a number picks from the list');
  assert.equal(sk.parsePort('#3', nearest), 'santa-barbara');
  assert.equal(sk.parsePort('4', nearest), null);
});

dbTest('slugs: ASCII from the name, 40 characters at most, a numeric suffix on collision', async () => {
  const {sql, db} = setup();
  assert.equal(sk.slugify('Rita G'), 'rita-g');
  assert.equal(sk.slugify('Señorita Pescadora II'), 'senorita-pescadora-ii');
  assert.equal(sk.slugify('***'), 'boat');
  const long = sk.slugify('The Very Long Name Of A Sportfishing Boat Out Of Morro Bay');
  assert.ok(long.length <= 40 && !long.endsWith('-'), long);
  assert.equal(await sk.uniqueSlug(db, 'Rita G'), 'rita-g');
  addBoat(sql, {id: 'b1', slug: 'rita-g', name: 'Rita G'});
  assert.equal(await sk.uniqueSlug(db, 'Rita  G!'), 'rita-g-2');
  addBoat(sql, {id: 'b2', slug: 'rita-g-2', name: 'Rita G'});
  assert.equal(await sk.uniqueSlug(db, 'rita g'), 'rita-g-3');
  const longName = 'The Very Long Name Of A Sportfishing Boat Out Of Morro Bay';
  addBoat(sql, {id: 'b3', slug: sk.slugify(longName), name: longName});
  const suffixed = await sk.uniqueSlug(db, longName);
  assert.ok(suffixed.endsWith('-2') && suffixed.length <= 40, suffixed);
});

// ---- the state machine --------------------------------------------------------------------

dbTest('registration: one question per text, an unknown port gets the nearest three, a number picks one, three bad answers cancel', async () => {
  const {sql, env} = setup();
  const start = await run(env, contactRow(sql), inbound(sql, 'register my boat'));
  assert.equal(start.intent, 'skipper.register.start');
  assert.deepEqual(texts(start), ["Let's set up your boat page. What's the boat's name?"]);
  assert.equal(start.actions.at(-1).type, 'flow_set');
  setFlow(sql, 'c1', start.actions.at(-1).state);
  const name = await run(env, contactRow(sql), inbound(sql, '"Rita G"'));
  assert.deepEqual([name.intent, texts(name)], ['skipper.register.name', ['Which port does she run out of?']]);
  setFlow(sql, 'c1', name.actions.at(-1).state);
  const bad = await run(env, contactRow(sql), inbound(sql, 'the harbor'));
  assert.equal(bad.intent, 'skipper.register.port.invalid');
  assert.deepEqual(texts(bad), ["I don't know that port. Reply with a number: 1) Morro Bay, 2) Port San Luis · Avila Beach, 3) Santa Barbara. Or type the port's name."]);
  setFlow(sql, 'c1', bad.actions.at(-1).state);
  const pick = await run(env, contactRow(sql), inbound(sql, '2'));
  assert.equal(pick.intent, 'skipper.register.port');
  assert.equal(pick.actions.at(-1).state.draft.port, 'port-san-luis');
  assert.equal(pick.actions.at(-1).state.tries, undefined, 'a valid answer resets the count');
  setFlow(sql, 'c1', pick.actions.at(-1).state);
  // The landing is free text; the Instagram handle three times wrong cancels.
  const landing = await run(env, contactRow(sql), inbound(sql, 'Port San Luis Harbor'));
  setFlow(sql, 'c1', landing.actions.at(-1).state);
  let r;
  for (let i = 0; i < 3; i++) { r = await run(env, contactRow(sql), inbound(sql, 'not a handle!')); if (r.actions.at(-1).type === 'flow_set' && r.actions.at(-1).state) setFlow(sql, 'c1', r.actions.at(-1).state); }
  assert.equal(r.intent, 'skipper.register.cancelled');
  assert.deepEqual(r.actions[0], {type: 'flow_set', state: null});
  assert.match(texts(r)[0], /^OK, I've stopped setting up the boat\./);
});

dbTest('registration: "never mind" cancels; a start phrase from a boat owner says they are set up', async () => {
  const {sql, env} = setup();
  setFlow(sql, 'c1', {flow: 'register', step: 'port', draft: {name: 'Rita G', lang: 'en'}, asked_at: iso(T0 - HOUR)});
  const cancel = await run(env, contactRow(sql), inbound(sql, 'never mind'));
  assert.deepEqual([cancel.intent, cancel.actions[0]], ['skipper.register.cancelled', {type: 'flow_set', state: null}]);
  const owner = setup({contact: {role: 'skipper', boat_id: 'b1'}});
  addBoat(owner.sql, {id: 'b1', slug: 'rita-g', name: 'Rita G', owner: 'c1'});
  const again = await run(owner.env, contactRow(owner.sql), inbound(owner.sql, "I'm the captain of the Rita G"));
  assert.deepEqual([again.intent, texts(again)], ['skipper.register.exists', ["You're already set up with Rita G. Text me today's count board whenever you're in."]]);
});

dbTest('a register flow older than 24 h is abandoned silently: deleted, and the message goes on to the model', async () => {
  const {sql, env} = setup();
  setFlow(sql, 'c1', {flow: 'register', step: 'landing', draft: {name: 'Rita G', port: 'morro-bay', lang: 'en'}, asked_at: iso(T0 - 25 * HOUR)});
  const {value: r} = await quiet(() => run(env, contactRow(sql), inbound(sql, 'Morro Bay Landing')));
  assert.equal(r.intent, 'unconfigured', 'no API key here: the model path answered');
  assert.deepEqual(r.actions[0], {type: 'flow_set', state: null}, 'the stale flow is deleted');
  assert.ok(!texts(r).some(x => /landing|Instagram/i.test(x)), 'no registration question');
  // 23 hours is still live.
  setFlow(sql, 'c1', {flow: 'register', step: 'landing', draft: {name: 'Rita G', port: 'morro-bay', lang: 'en'}, asked_at: iso(T0 - 23 * HOUR)});
  assert.equal((await run(env, contactRow(sql), inbound(sql, 'Morro Bay Landing'))).intent, 'skipper.register.landing');
});

dbTest('consumer: completion creates the pending boat, makes the contact its skipper, opens new_skipper and texts the admin; a retry creates nothing twice', async () => {
  const {sql, env} = setup({env: {ADVISOR_ADMIN_CONTACT_ID: ADMIN_ID}});
  addContact(sql, {id: ADMIN_ID, phone_hash: 'ha', phone_enc: 'ENC-ADMIN', role: 'admin-test'});
  addBoat(sql, {id: 'other', slug: 'rita-g', name: 'Rita G'});   // the slug is taken
  setFlow(sql, 'c1', {flow: 'register', step: 'booking', draft: {name: 'Rita G', port: 'morro-bay', landing: null, instagram: 'ritag', lang: 'en'}, asked_at: iso(T0 - HOUR)});
  const ch = recorder();
  const {m} = await consume(env, sql, 'https://example.com/rita', {ch});
  const boat = sql.prepare("SELECT * FROM advisor_boats WHERE owner_contact_id='c1'").get();
  assert.deepEqual([boat.slug, boat.status, boat.booking_url, boat.verified_at], ['rita-g-2', 'pending', 'https://example.com/rita', null]);
  assert.deepEqual([contactRow(sql).role, contactRow(sql).boat_id, contactRow(sql).home_port], ['skipper', boat.id, 'morro-bay']);
  const code = (await reviewId('skipper', boat.id, 'new_skipper')).slice(0, 6);
  const toAdmin = ch.sent.filter(x => x.to === 'ENC-ADMIN').map(x => x.text);
  assert.deepEqual(toAdmin, [`New skipper review (new_skipper). Reply OK ${code} to approve or NO ${code} to reject.`]);
  const toSkipper = ch.sent.filter(x => x.to === 'ENC').map(x => x.text);
  assert.match(toSkipper[0], /skippercast\.com\/boats\/rita-g-2 once the team confirms/);
  assert.match(toSkipper[1], /^One more thing: OK for SkipperCast to post your photos/);
  // The same message again (a redelivery): no second boat, no second text.
  sql.prepare("UPDATE advisor_messages SET status='queued' WHERE id=?").run(m.id);
  setFlow(sql, 'c1', {flow: 'register', step: 'booking', draft: {name: 'Rita G', port: 'morro-bay', landing: null, instagram: 'ritag', lang: 'en'}, asked_at: iso(T0 - HOUR)});
  const before = ch.sent.length;
  await quiet(() => consumeAdvisor(batchOf(m.id), env, {channelFor: () => ch, handler: engineHandler, now: () => T0, engine: {clock: () => T0}}));
  assert.equal(sql.prepare("SELECT COUNT(*) n FROM advisor_boats WHERE owner_contact_id='c1'").get().n, 1);
  assert.equal(sql.prepare("SELECT slug FROM advisor_boats WHERE owner_contact_id='c1'").get().slug, 'rita-g-2', 'the retry keeps the slug');
  assert.equal(ch.sent.length, before);
});

// ---- consent ---------------------------------------------------------------------------------

dbTest('consent: YES records the time and message id; any other reply declines once and goes on; revoke sets consent_revoked_at', async () => {
  const {sql, env} = setup({contact: {role: 'skipper', boat_id: 'b1'}});
  addBoat(sql, {id: 'b1', slug: 'rita-g', name: 'Rita G', owner: 'c1'});
  setFlow(sql, 'c1', {flow: 'consent', step: 'asked', draft: {boat_id: 'b1', lang: 'en'}, asked_at: iso(T0 - HOUR)});
  // A question instead of an answer: the decline note, then the question goes on to the model.
  const {value: q} = await quiet(() => run(env, contactRow(sql), inbound(sql, "what's the swell tomorrow?")));
  assert.equal(q.intent, 'unconfigured');
  assert.deepEqual(q.actions.map(a => a.type), ['flow_set', 'send_text', 'send_text']);
  assert.equal(q.actions[0].state.step, 'declined');
  assert.match(texts(q)[0], /^No problem\. Your photos will still go on your boat page/);
  // A plain "no" is answered by the note alone.
  const no = await run(env, contactRow(sql), inbound(sql, 'no'));
  assert.deepEqual([no.intent, texts(no).length], ['consent.declined', 1]);
  // "post my photos" grants it later, with this message's id.
  const ch = recorder();
  const {m} = await consume(env, sql, 'post my photos', {ch});
  const b = sql.prepare("SELECT * FROM advisor_boats WHERE id='b1'").get();
  assert.deepEqual([b.consent_photos_at, b.consent_message_id, b.consent_revoked_at], [iso(T0), m.id, null]);
  assert.match(ch.sent.at(-1).text, /^Thanks\. Your photos can go on the SkipperCast feed, tagged to Rita G\./);
  // Revoke: the column, the post_revoke placeholder (logged), the confirmation.
  const later = T0 + DAY;
  const {lines} = await quiet(async () => {
    const msg = inbound(sql, 'Stop posting my photos', {at: later, status: 'queued'});
    await consumeAdvisor(batchOf(msg.id), env, {channelFor: () => ch, handler: engineHandler, now: () => later, engine: {clock: () => later}});
  });
  const r = sql.prepare("SELECT * FROM advisor_boats WHERE id='b1'").get();
  assert.equal(r.consent_revoked_at, iso(later));
  assert.equal(r.consent_photos_at, iso(T0), 'the original consent stays on record');
  assert.equal(sk.consentActive(r), false);
  assert.ok(lines.some(l => /advisor_post_revoke/.test(l)), 'post_revoke is logged until TA-S1');
  assert.match(ch.sent.at(-1).text, /^Done\. I won't post your photos on social anymore\./);
  const es = await run(env, contactRow(sql), inbound(sql, 'No publiques'));
  assert.equal(es.intent, 'consent.revoke');
});

dbTest('consent: only the owner; a crew member asking to revoke is told so and nothing changes', async () => {
  const {sql, env} = setup({contact: {role: 'crew', boat_id: 'b1'}});
  addBoat(sql, {id: 'b1', slug: 'rita-g', name: 'Rita G', owner: 'owner', consent: iso(T0 - DAY)});
  const r = await run(env, contactRow(sql), inbound(sql, 'revoke'));
  assert.deepEqual([r.intent, texts(r)], ['consent.not_owner', ["Only the boat's owner can change that."]]);
});

dbTest('consent: a photo from the owner without consent re-asks, at most once per 7 days', async () => {
  const {sql, env} = setup({contact: {role: 'skipper', boat_id: 'b1'}});
  addBoat(sql, {id: 'b1', slug: 'rita-g', name: 'Rita G', owner: 'c1', created: iso(T0 - 30 * DAY)});
  setFlow(sql, 'c1', {flow: 'consent', step: 'declined', draft: {boat_id: 'b1'}, asked_at: iso(T0 - 3 * DAY)});
  const soon = await run(env, contactRow(sql), inbound(sql, null, {media: ['m1']}));
  assert.deepEqual([soon.intent, texts(soon)], ['media', [t('en', 'media_ack')]], '3 days after the last ask: no re-ask');
  setFlow(sql, 'c1', {flow: 'consent', step: 'declined', draft: {boat_id: 'b1'}, asked_at: iso(T0 - 8 * DAY)});
  const later = await run(env, contactRow(sql), inbound(sql, null, {media: ['m2']}));
  assert.equal(later.intent, 'media');
  assert.deepEqual(texts(later), [t('en', 'media_ack'), t('en', 'consent_ask', {name: 'Rita G'})]);
  assert.deepEqual({...later.actions.at(-1).state, asked_at: 'x'}, {flow: 'consent', step: 'asked', draft: {boat_id: 'b1', lang: 'en'}, asked_at: 'x'});
  setFlow(sql, 'c1', later.actions.at(-1).state);
  const yes = await run(env, contactRow(sql), inbound(sql, 'ok'));
  assert.equal(yes.intent, 'consent.yes', 'the re-asked question takes a YES');
  // With consent active, a photo asks nothing.
  sql.prepare("UPDATE advisor_boats SET consent_photos_at=?").run(iso(T0));
  sql.prepare('DELETE FROM job_state').run();
  assert.deepEqual(texts(await run(env, contactRow(sql), inbound(sql, null, {media: ['m3']}))), [t('en', 'media_ack')]);
  // A revoked boat with no flow row: re-asked by the boat's age.
  sql.prepare("UPDATE advisor_boats SET consent_revoked_at=?").run(iso(T0 + 1));
  assert.equal(texts(await run(env, contactRow(sql), inbound(sql, null, {media: ['m4']}))).length, 2);
});

// ---- crew --------------------------------------------------------------------------------------

dbTest('crew: the owner adds by number (hashed, never echoed), the invite goes to that number, the reply is credited to the boat', async () => {
  const {sql, db, env} = setup({contact: {role: 'skipper', boat_id: 'b1', display_name: 'Captain Dave'}});
  addBoat(sql, {id: 'b1', slug: 'rita-g', name: 'Rita G', owner: 'c1', status: 'verified'});
  const out = await TOOL_BY_NAME.get('add_crew').run({phone: '805.555.0142'}, toolCtx(env, db, contactRow(sql)));
  assert.deepEqual(out.result, {added: true});
  assert.ok(!JSON.stringify(out.result).includes('555'), 'the number is never echoed');
  const keys = await deriveKeys(KEY), hash = await phoneHash(keys, '+18055550142');
  assert.deepEqual([out.actions[0].type, out.actions[0].boatId, out.actions[0].phoneHash], ['crew_add', 'b1', hash]);
  // Applied through the consumer: the invite goes to the crew contact's own address.
  const ch = recorder();
  const msg = inbound(sql, 'add my deckhand', {status: 'queued'});
  await quiet(() => consumeAdvisor(batchOf(msg.id), env, {channelFor: () => ch, handler: async () => ({actions: out.actions, intent: 'skipper.crew'}), now: () => T0}));
  const crew = sql.prepare('SELECT * FROM advisor_contacts WHERE phone_hash=?').get(hash);
  assert.deepEqual([crew.role, crew.boat_id, crew.channel, crew.source], ['crew', 'b1', 'sms', 'skipper-invite']);
  assert.deepEqual(ch.sent.map(x => [x.to, x.text]), [[crew.phone_enc, "Captain Dave added you as crew on Rita G. Text me the day's count board or catch photos and they'll post under the boat. Reply STOP to opt out."]]);
  assert.deepEqual({...sql.prepare('SELECT boat_id,contact_id,added_by,removed_at FROM advisor_crew').get()}, {boat_id: 'b1', contact_id: crew.id, added_by: 'c1', removed_at: null});
  assert.ok(!sql.prepare("SELECT body FROM advisor_messages WHERE direction='out'").all().some(r => /555/.test(r.body ?? '')), 'no number in a stored text');
  // The crew member replies with a photo: a normal turn, and the media is the boat's.
  const id = await storeInbound(env, {channel: 'sms', providerId: 'p-crew-1', from: '+18055550142', to: '+15555550199', text: '', receivedAt: iso(T0),
    media: [{providerRef: 'att-1', mime: 'image/jpeg', bytes: 1000, name: 'board.jpg', fetch: async () => new Response('')}], isGroup: false}, new Date(T0));
  assert.ok(id);
  assert.equal(sql.prepare('SELECT boat_id FROM advisor_media WHERE message_id=?').get(id).boat_id, 'b1', 'crew media carry the boat');
  assert.equal(sql.prepare('SELECT contact_id FROM advisor_messages WHERE id=?').get(id).contact_id, crew.id, 'the existing crew contact, not a new one');
  // Adding the same number again re-links and texts again; adding the skipper's own number or a bad one does nothing.
  assert.deepEqual((await TOOL_BY_NAME.get('add_crew').run({phone: 'call me'}, toolCtx(env, db, contactRow(sql)))).result, {added: false, reason: 'not a US mobile number'});
  const selfHash = await phoneHash(keys, '+18055550111');
  sql.prepare("UPDATE advisor_contacts SET phone_hash=? WHERE id='c1'").run(selfHash);
  assert.equal((await TOOL_BY_NAME.get('add_crew').run({phone: '8055550111'}, toolCtx(env, db, contactRow(sql)))).result.added, false);
  void encryptPhone;
});

dbTest('crew: only the boat owner can add or remove; removal keeps the row, clears the boat, and later photos are an angler\'s', async () => {
  const {sql, db, env} = setup({contact: {role: 'skipper', boat_id: 'b1'}});
  const keys = await deriveKeys(KEY), hash = await phoneHash(keys, '+18055550142');
  addBoat(sql, {id: 'b1', slug: 'rita-g', name: 'Rita G', owner: 'c1'});
  addBoat(sql, {id: 'b2', slug: 'lucero', name: 'Lucero', owner: 'c3'});
  addContact(sql, {id: 'c2', phone_hash: hash, phone_enc: 'ENC-CREW', role: 'crew', boat_id: 'b1'});
  addContact(sql, {id: 'c3', phone_hash: 'h3', phone_enc: 'ENC-3', role: 'skipper', boat_id: 'b2'});
  sql.prepare(`INSERT INTO advisor_crew(boat_id,contact_id,added_by,added_at) VALUES('b1','c2','c1',?)`).run(iso(T0));
  // The crew member, and another boat's owner, cannot remove or add.
  for (const who of ['c2', 'c3']) {
    const r = await TOOL_BY_NAME.get('remove_crew').run({phone: '(805) 555-0142'}, toolCtx(env, db, contactRow(sql, who)));
    assert.equal(r.result.removed, false, who); assert.equal(r.actions, undefined, who);
  }
  assert.deepEqual((await TOOL_BY_NAME.get('add_crew').run({phone: '(805) 555-0177'}, toolCtx(env, db, contactRow(sql, 'c2')))).result, {added: false, reason: "only the boat's owner can add crew"});
  // A forged action from someone else is refused by the consumer too.
  const ch = recorder();
  const forged = inbound(sql, 'x', {contact: 'c3', status: 'queued'});
  await quiet(() => consumeAdvisor(batchOf(forged.id), env, {channelFor: () => ch, handler: async () => ({actions: [{type: 'crew_remove', boatId: 'b1', contactId: 'c2'}], intent: 'skipper.crew'}), now: () => T0}));
  assert.equal(contactRow(sql, 'c2').boat_id, 'b1');
  // The owner removes.
  const r = await TOOL_BY_NAME.get('remove_crew').run({phone: '805-555-0142'}, toolCtx(env, db, contactRow(sql)));
  assert.deepEqual(r.result, {removed: true});
  const msg = inbound(sql, 'remove him', {status: 'queued'});
  await quiet(() => consumeAdvisor(batchOf(msg.id), env, {channelFor: () => ch, handler: async () => ({actions: r.actions, intent: 'skipper.crew'}), now: () => T0}));
  assert.equal(sql.prepare("SELECT removed_at FROM advisor_crew WHERE contact_id='c2'").get().removed_at, iso(T0), 'the row is kept with removed_at');
  assert.deepEqual([contactRow(sql, 'c2').boat_id, contactRow(sql, 'c2').role], [null, 'angler']);
  assert.deepEqual((await TOOL_BY_NAME.get('remove_crew').run({phone: '805-555-0142'}, toolCtx(env, db, contactRow(sql)))).result, {removed: false, reason: 'that number is not crew on this boat'});
  assert.deepEqual(await sk.boatsForContact(db, 'c2'), [], 'no boat for the removed crew member');
  assert.deepEqual((await sk.boatsForContact(db, 'c1')).map(b => [b.id, b.relation]), [['b1', 'owner']]);
});

// ---- register_boat tool ----------------------------------------------------------------------

dbTest('register_boat: starts the flow with what the model heard, completes at once with every field, refuses the web and existing owners', async () => {
  const {sql, db, env} = setup();
  const partial = await TOOL_BY_NAME.get('register_boat').run({name: 'Rita G', port: 'morro-bay', instagram: 'not a handle'}, toolCtx(env, db, contactRow(sql)));
  assert.deepEqual([partial.result.started, partial.result.registered, partial.result.ignored], [true, false, ['instagram']]);
  assert.deepEqual(partial.actions.map(a => a.type), ['send_text', 'flow_set']);
  assert.equal(partial.actions[0].text, 'Which landing? (skip if none)', 'no intro: the model already spoke');
  assert.deepEqual(partial.actions[1].state.draft, {lang: 'en', name: 'Rita G', port: 'morro-bay'});
  const full = await TOOL_BY_NAME.get('register_boat').run({name: 'Rita G', port: 'morro-bay', landing: 'Virg\'s', instagram: '@ritag', booking_url: 'https://example.com/rita'},
    toolCtx(env, db, contactRow(sql), {id: 'in-full'}));
  assert.equal(full.result.registered, true);
  assert.deepEqual(full.actions.map(a => a.type), ['boat_create', 'review_open', 'send_text', 'send_text', 'flow_set']);
  assert.deepEqual(full.actions[1], {type: 'review_open', kind: 'skipper', refId: full.actions[0].boat.id, reason: 'new_skipper'});
  const web = await TOOL_BY_NAME.get('register_boat').run({name: 'Rita G'}, toolCtx(env, db, {...contactRow(sql), phone_enc: null, web_session: 'w'.repeat(64)}));
  assert.equal(web.result.started, false);
  addBoat(sql, {id: 'b1', slug: 'rita-g', name: 'Rita G', owner: 'c1'});
  sql.prepare("UPDATE advisor_contacts SET boat_id='b1', role='skipper'").run();
  assert.equal((await TOOL_BY_NAME.get('register_boat').run({name: 'Other'}, toolCtx(env, db, contactRow(sql)))).result.started, false);
});

// ---- verification (05 § Verification) ------------------------------------------------------------

dbTest('ok <code> from the admin-test contact verifies the boat and texts the skipper; no <code> rejects and says the team will reach out', async () => {
  for (const [word, status, reply] of [['ok', 'verified', 'Rita G is verified. Your page: skippercast.com/boats/rita-g'], ['no', 'rejected', "We couldn't confirm Rita G yet. Someone from the SkipperCast team will reach out."]]) {
    const {sql, env} = setup({contact: {role: 'skipper', boat_id: 'b1'}, env: {ADVISOR_ADMIN_CONTACT_ID: ADMIN_ID}});
    addContact(sql, {id: ADMIN_ID, phone_hash: 'ha', phone_enc: 'ENC-ADMIN', role: 'admin-test'});
    addBoat(sql, {id: 'b1', slug: 'rita-g', name: 'Rita G', owner: 'c1'});
    const review = await reviewId('skipper', 'b1', 'new_skipper');
    sql.prepare(`INSERT INTO advisor_reviews(id,kind,ref_id,reason,status,opened_at) VALUES(?,'skipper','b1','new_skipper','open',?)`).run(review, iso(T0));
    const {ch} = await consume(env, sql, `${word} ${review.slice(0, 6)}`, {contact: ADMIN_ID});
    assert.equal(sql.prepare("SELECT status FROM advisor_boats WHERE id='b1'").get().status, status);
    assert.deepEqual(ch.sent.filter(x => x.to === 'ENC').map(x => x.text), [reply], word);
    assert.equal(ch.sent.filter(x => x.to === 'ENC-ADMIN').length, 1, 'the admin gets the Done line');
  }
});

dbTest('the unverified contract: publicBoat names only verified boats; get_trips lists only verified ones', async () => {
  assert.deepEqual(sk.publicBoat({name: 'Rita G', slug: 'rita-g', verified: true}), {boat: 'Rita G', verified: true, boat_link: '{{link:boat:rita-g}}'});
  assert.deepEqual(sk.publicBoat({name: 'Rita G', slug: 'rita-g', verified: false}), {boat: 'a boat', verified: false});
  assert.ok(sk.isVerified('verified') && !sk.isVerified('pending') && !sk.isVerified('rejected'));
  const {sql, db, env} = setup();
  addBoat(sql, {id: 'b1', slug: 'rita-g', name: 'Rita G', status: 'verified'});
  addBoat(sql, {id: 'b2', slug: 'lucero', name: 'Lucero', status: 'pending'});
  addBoat(sql, {id: 'b3', slug: 'nope', name: 'Nope', status: 'rejected'});
  const trips = (await TOOL_BY_NAME.get('get_trips').run({port: 'morro-bay'}, toolCtx(env, db, contactRow(sql)))).result;
  assert.deepEqual(trips.boats.map(b => b.name), ['Rita G']);
  assert.deepEqual(sk.consentState({consent_photos_at: null, consent_revoked_at: null}), 'not given');
  assert.deepEqual(sk.consentState({consent_photos_at: iso(T0), consent_revoked_at: null}), 'given');
  assert.deepEqual(sk.consentState({consent_photos_at: iso(T0), consent_revoked_at: iso(T0 + 1)}), 'revoked');
  assert.deepEqual(sk.consentState({consent_photos_at: iso(T0 + 2), consent_revoked_at: iso(T0 + 1)}), 'given', 'granted again after revoking');
});

// ---- strings ------------------------------------------------------------------------------------

test('every TA-I1 string has English and Spanish, and the 05 wording is exact', () => {
  const keys = ['register_intro', 'register_ask_name', 'register_ask_port', 'register_ask_landing', 'register_ask_instagram', 'register_ask_booking', 'register_bad_name', 'register_bad_port',
    'register_bad_landing', 'register_bad_instagram', 'register_bad_booking', 'register_cancelled', 'register_already', 'register_done', 'consent_ask', 'consent_yes', 'consent_declined',
    'consent_revoked', 'owner_only', 'crew_invite', 'crew_invite_skipper', 'boat_verified', 'boat_rejected'];
  for (const key of keys) {
    assert.ok(STRINGS[key], key);
    assert.ok(STRINGS[key].en.trim() && STRINGS[key].es.trim() && STRINGS[key].en !== STRINGS[key].es, key);
  }
  assert.equal(t('en', 'register_ask_name'), "What's the boat's name?");
  assert.equal(t('en', 'register_ask_port'), 'Which port does she run out of?');
  assert.equal(t('en', 'register_ask_landing'), 'Which landing? (skip if none)');
  assert.equal(t('en', 'register_ask_instagram'), "Your boat's Instagram handle, so we can tag you? (skip if none)");
  assert.equal(t('en', 'register_ask_booking'), 'A booking link or phone for the boat page? (skip)');
  assert.equal(t('en', 'register_done', {name: 'Rita G', slug: 'rita-g'}), "Got it. Rita G is set up. Your reports will show on skippercast.com/boats/rita-g once the team confirms the boat, usually same day. Text me a photo of today's count board whenever you're in.");
  assert.equal(t('en', 'consent_ask', {name: 'Rita G'}), 'One more thing: OK for SkipperCast to post your photos and videos on our Instagram and Facebook, always credited and tagged to Rita G? Reply YES.');
  assert.equal(t('en', 'crew_invite', {skipper: 'Dave', boat: 'Rita G'}), "Dave added you as crew on Rita G. Text me the day's count board or catch photos and they'll post under the boat. Reply STOP to opt out.");
  assert.match(t('es', 'crew_invite', {skipper: 'Dave', boat: 'Rita G'}), /Responde STOP para salir\.$/, 'the Spanish invite keeps the STOP line');
  assert.equal(t('en', 'boat_verified', {name: 'Rita G', slug: 'rita-g'}), 'Rita G is verified. Your page: skippercast.com/boats/rita-g');
});
