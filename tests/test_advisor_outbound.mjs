// The guard on texts the advisor starts (server/advisor/outbound-guard.ts;
// docs/legal/threat-model.md § 9.3): web phone-link codes, crew invitations
// and admin skipper invites to a number the requester typed. Covers the
// limits (per number per day and per 7 days, per requester, per client
// address, the global ADVISOR_GLOBAL_DAILY_COLD for numbers that never texted
// us), stopped numbers, that nothing is counted when a text does not go out,
// and that the web visitor's answer never depends on the number. Offline:
// real migrations in node:sqlite, a recording channel, no model.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
const guard = await import('../server/advisor/outbound-guard.ts');
const {advisorSettings} = await import('../server/advisor/settings.ts');
const {consumeAdvisor, ADVISOR_QUEUE_NAME} = await import('../server/advisor/consumer.ts');
const {TOOL_BY_NAME} = await import('../server/advisor/tools/index.ts');
const {deriveKeys, phoneHash, encryptPhone} = await import('../server/advisor/contacts.ts');
const {linkKey} = await import('../server/advisor/tools/offer_text_link.ts');
const {readCrewInvite} = await import('../server/advisor/intake/skippers.ts');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const T0 = Date.parse('2026-10-05T17:00:00Z');
const HOUR = 3600000, DAY = 24 * HOUR;
const KEY = Buffer.alloc(32, 7).toString('base64');
const iso = ms => new Date(ms).toISOString();
const settings = advisorSettings({});
const quiet = async fn => { const saved = {log: console.log, warn: console.warn, error: console.error}, lines = []; console.log = console.warn = console.error = (...a) => lines.push(a.join(' ')); try { return {value: await fn(), lines}; } finally { Object.assign(console, saved); } };
let uniq = 0;
function recorder() { const sent = []; return {sent, name: 'bluebubbles', async send(m) { sent.push(structuredClone(m)); return {providerId: `rec-${++uniq}`, status: 'sent'}; }}; }
const batchOf = id => ({queue: ADVISOR_QUEUE_NAME, messages: [{id: 'm', body: {message_id: id}, attempts: 1, ack() {}, retry() {}}], ackAll() {}, retryAll() {}});
const keys = await deriveKeys(KEY);
const number = n => `+1805555${String(n).padStart(4, '0')}`;
const hashOf = n => phoneHash(keys, number(n));

function setup(env = {}) {
  const {sql, db} = advisorDatabase();
  return {sql, db, env: {TEXT_ADVISOR_ENABLED: 'true', DB: db, ADVISOR_NUMBER: '+15555550199', ADVISOR_PHONE_KEY: KEY, ...env}};
}
function addContact(sql, c) {
  sql.prepare(`INSERT INTO advisor_contacts(id,phone_hash,phone_enc,web_session,channel,role,language,boat_id,status,last_seen_at,created_at,updated_at) VALUES(?,?,?,?,?,?,'en',?,?,?,?,?)`)
    .run(c.id, c.phone_hash ?? null, c.phone_enc ?? null, c.web_session ?? null, c.channel ?? 'imessage', c.role ?? 'angler', c.boat_id ?? null, c.status ?? 'active', iso(T0), iso(T0), iso(T0));
}
let seq = 0;
function inbound(sql, contact, at = T0, body = 'x') {
  const id = `in${++seq}`;
  sql.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,body,status,created_at) VALUES(?,?,'in','imessage',?,'queued',?)`).run(id, contact, body, iso(at));
  return id;
}
/** One message from `contact` whose turn returns `actions`, applied by the consumer; the texts the channel got. */
async function apply(env, sql, contact, actions, {at = T0, ipHash} = {}) {
  const ch = recorder(), id = inbound(sql, contact, at);
  await quiet(() => consumeAdvisor(batchOf(id), env, {channelFor: () => ch, channel: undefined, handler: async () => ({actions, intent: 'test'}), now: () => at, ...(ipHash ? {ipHash} : {})}));
  return ch.sent;
}
/** A web visitor (a fresh cookie each time) asking for a code to `n` through the real tool. */
async function webCode(env, sql, db, n, {at = T0, ipHash = 'ip-a', visitor} = {}) {
  const id = visitor ?? `web${++seq}`;
  if (!sql.prepare('SELECT 1 FROM advisor_contacts WHERE id=?').get(id)) addContact(sql, {id, web_session: `s-${id}`, channel: 'web'});
  const contact = sql.prepare('SELECT * FROM advisor_contacts WHERE id=?').get(id);
  const out = await TOOL_BY_NAME.get('offer_text_link').run({phone: number(n)}, {env, contact, message: {id: 'tool'}, deps: {random: () => 0.5}, db, language: 'en', settings: advisorSettings(env), now: at});
  const sent = out.actions ? await apply(env, sql, id, out.actions, {at, ipHash}) : [];
  return {result: out.result, sent, visitor: id};
}
const codes = sent => sent.filter(m => /^Your SkipperCast code is \d{6}/.test(m.text ?? '')).length;

// ---- the guard itself ---------------------------------------------------------------------------

dbTest('guard: 2 a day and 5 in any 7 days to one number, whoever asks; nothing is counted until commit', async () => {
  const {db} = setup();
  const h = await hashOf(100);
  const ask = (origin, now) => guard.checkOutbound(db, settings, {kind: 'link_code', recipientHash: h, origin, now});
  const first = await ask('a', T0);
  assert.equal(first.ok, true);
  assert.equal((await ask('b', T0)).ok, true, 'a check without commit counts nothing');
  await first.commit(); await (await ask('b', T0)).commit();
  assert.deepEqual(await ask('c', T0), {ok: false, reason: 'recipient'}, 'third the same day, from a third requester');
  // Days 2-4: one more each (5 in 7 days), then the 7-day limit holds on day 5 and lifts once day 1 leaves the window.
  for (const d of [1, 2, 3]) { const v = await ask(`d${d}`, T0 + d * DAY); assert.equal(v.ok, true, `day ${d}`); await v.commit(); }
  assert.deepEqual(await ask('e', T0 + 4 * DAY), {ok: false, reason: 'recipient'}, '5 in 7 days');
  assert.equal((await ask('f', T0 + 7 * DAY)).ok, true, 'the first day left the 7-day window');
});

dbTest('guard: stopped and blocked numbers are refused; the global cold cap counts only numbers that never texted us', async () => {
  const {sql, db} = setup();
  addContact(sql, {id: 's', phone_hash: await hashOf(1), status: 'stopped'});
  addContact(sql, {id: 'b', phone_hash: await hashOf(2), status: 'blocked'});
  addContact(sql, {id: 'warm', phone_hash: await hashOf(3)});
  inbound(sql, 'warm', T0 - DAY);
  for (const n of [1, 2]) assert.deepEqual(await guard.checkOutbound(db, settings, {kind: 'crew_invite', recipientHash: await hashOf(n), origin: 'x', now: T0}), {ok: false, reason: 'stopped'});
  const tight = {globalDailyCold: 1};
  const cold = await guard.checkOutbound(db, tight, {kind: 'admin_invite', recipientHash: await hashOf(4), origin: 'admin', now: T0});
  assert.equal(cold.cold, true); await cold.commit();
  assert.deepEqual(await guard.checkOutbound(db, tight, {kind: 'admin_invite', recipientHash: await hashOf(5), origin: 'admin', now: T0}), {ok: false, reason: 'global'});
  const warm = await guard.checkOutbound(db, tight, {kind: 'admin_invite', recipientHash: await hashOf(3), origin: 'admin', now: T0});
  assert.equal(warm.ok, true, 'a number that texted us is not cold'); assert.equal(warm.cold, false);
  await warm.commit();
  assert.equal(sql.prepare('SELECT count FROM request_limits WHERE id=?').get(guard.coldKey(Math.floor(T0 / DAY))).count, 1, 'only the cold text counts toward the cap');
  assert.equal(advisorSettings({}).globalDailyCold, 50);
  assert.equal(advisorSettings({ADVISOR_GLOBAL_DAILY_COLD: '7'}).globalDailyCold, 7);
});

dbTest('guard: per requester and per client address a day', async () => {
  const {db} = setup();
  let n = 200;
  for (let i = 0; i < guard.ORIGIN_PER_DAY.crew_invite; i++) await (await guard.checkOutbound(db, settings, {kind: 'crew_invite', recipientHash: await hashOf(n++), origin: 'skipper', now: T0})).commit();
  assert.deepEqual(await guard.checkOutbound(db, settings, {kind: 'crew_invite', recipientHash: await hashOf(n++), origin: 'skipper', now: T0}), {ok: false, reason: 'origin'});
  assert.equal((await guard.checkOutbound(db, settings, {kind: 'crew_invite', recipientHash: await hashOf(n++), origin: 'skipper', now: T0 + DAY})).ok, true, 'a new day');
  for (let i = 0; i < guard.IP_PER_DAY; i++) await (await guard.checkOutbound(db, settings, {kind: 'link_code', recipientHash: await hashOf(n++), origin: `visitor${i}`, ipHash: 'ip-1', now: T0})).commit();
  assert.deepEqual(await guard.checkOutbound(db, settings, {kind: 'link_code', recipientHash: await hashOf(n++), origin: 'visitor-new', ipHash: 'ip-1', now: T0}), {ok: false, reason: 'ip'});
  assert.equal((await guard.checkOutbound(db, settings, {kind: 'link_code', recipientHash: await hashOf(n++), origin: 'visitor-new', ipHash: 'ip-2', now: T0})).ok, true);
});

test('ipHash: keyed, 32 hex characters, never the address', async () => {
  const a = await guard.ipHash(KEY, '203.0.113.7');
  assert.match(a, /^[0-9a-f]{32}$/);
  assert.notEqual(a, await guard.ipHash(Buffer.alloc(32, 8).toString('base64'), '203.0.113.7'), 'depends on the key');
  assert.notEqual(a, await guard.ipHash(KEY, '203.0.113.8'));
  assert.ok(!a.includes('203'));
});

// ---- web phone-link codes ------------------------------------------------------------------------

dbTest('web link codes: fresh cookies from one address stop after 5 codes; one number gets at most 2 a day; the visitor hears the same either way', async () => {
  const {sql, db, env} = setup();
  // One number, many fresh cookies on many addresses: two codes, then silence.
  const results = [];
  for (let i = 0; i < 4; i++) results.push(await webCode(env, sql, db, 300, {ipHash: `ip-${i}`}));
  assert.deepEqual(results.map(r => codes(r.sent)), [1, 1, 0, 0], 'at most 2 codes a day to one number');
  assert.ok(results.every(r => JSON.stringify(r.result) === JSON.stringify(results[0].result)), 'the answer never shows the refusal');
  assert.ok(results.every(r => r.sent.every(m => !/couldn't text/.test(m.text ?? ''))), 'no "couldn\'t text" either');
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM job_state WHERE key LIKE 'advisor.link.%'").get().n, 2, 'a refused code leaves no pending link');
  // One address, fresh cookies, many numbers: five codes, then silence.
  const many = [];
  for (let i = 0; i < 7; i++) many.push(await webCode(env, sql, db, 400 + i, {ipHash: 'ip-busy'}));
  assert.deepEqual(many.map(r => codes(r.sent)), [1, 1, 1, 1, 1, 0, 0]);
  assert.equal(sql.prepare('SELECT COUNT(*) AS n FROM advisor_contacts WHERE phone_hash=?').get(await hashOf(406)).n, 0, 'a refused number is not stored');
});

dbTest('web link codes: a stopped number gets nothing, the visitor hears what anyone hears, and no "couldn\'t text" reveals it', async () => {
  const {sql, db, env} = setup();
  addContact(sql, {id: 'stopped', phone_hash: await hashOf(500), phone_enc: await encryptPhone(keys, number(500)), status: 'stopped'});
  const stopped = await webCode(env, sql, db, 500);
  const fresh = await webCode(env, sql, db, 501);
  assert.deepEqual(stopped.result, fresh.result);
  assert.deepEqual(stopped.sent, [], 'nothing to the number and nothing to the visitor');
  assert.equal(codes(fresh.sent), 1);
  assert.equal(sql.prepare('SELECT COUNT(*) AS n FROM job_state WHERE key=?').get(linkKey(stopped.visitor)).n, 0);
});

dbTest('web link codes: ADVISOR_GLOBAL_DAILY_COLD caps codes to new numbers across every visitor', async () => {
  const {sql, db, env} = setup({ADVISOR_GLOBAL_DAILY_COLD: '2'});
  const sent = [];
  for (let i = 0; i < 4; i++) sent.push(codes((await webCode(env, sql, db, 600 + i, {ipHash: `ip-${i}`})).sent));
  assert.deepEqual(sent, [1, 1, 0, 0]);
  assert.equal(codes((await webCode(env, sql, db, 610, {ipHash: 'ip-x', at: T0 + DAY})).sent), 1, 'a new day');
});

// ---- crew invitations ----------------------------------------------------------------------------

dbTest('crew invitations: one number gets at most 2 a day from all boats; a skipper sends at most 10 a day', async () => {
  const {sql, db, env} = setup();
  for (const [boat, owner] of [['b1', 'o1'], ['b2', 'o2'], ['b3', 'o3']]) {
    addContact(sql, {id: owner, phone_hash: `h-${owner}`, phone_enc: `E-${owner}`, role: 'skipper', boat_id: boat});
    sql.prepare(`INSERT INTO advisor_boats(id,slug,name,port,region,owner_contact_id,status,created_at,updated_at) VALUES(?,?,?,'morro-bay','morro-bay',?,'verified',?,?)`).run(boat, `boat-${boat}`, `Test Boat ${boat}`, owner, iso(T0), iso(T0));
  }
  const crewAdd = async n => ({type: 'crew_add', boatId: 'b1', phoneHash: await hashOf(n), phoneEnc: await encryptPhone(keys, number(n))});
  const target = await hashOf(700), enc = await encryptPhone(keys, number(700));
  const fromBoat = (boat, owner) => apply(env, sql, owner, [{type: 'crew_add', boatId: boat, phoneHash: target, phoneEnc: enc}]);
  assert.equal((await fromBoat('b1', 'o1')).length, 1);
  assert.equal((await fromBoat('b2', 'o2')).length, 1);
  assert.deepEqual(await fromBoat('b3', 'o3'), [], 'a third invitation the same day is dropped');
  const contact = sql.prepare('SELECT id FROM advisor_contacts WHERE phone_hash=?').get(target);
  assert.equal((await readCrewInvite(db, contact.id)).boat_id, 'b2', 'the dropped one did not replace the pending invitation');
  let sent = 0;
  for (let n = 800; n < 812; n++) sent += (await apply(env, sql, 'o1', [await crewAdd(n)])).length;
  assert.equal(sent, guard.ORIGIN_PER_DAY.crew_invite - 1, 'ten a day per skipper (one went to the first number)');
});
