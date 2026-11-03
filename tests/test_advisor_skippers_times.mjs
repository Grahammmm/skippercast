// RF1230-24: stored times in server/advisor/intake/skippers.ts fail safe. A
// register step whose asked_at is unreadable or in the future is abandoned; a
// future or unreadable consent/boat time allows the photo re-ask; a crew NO
// whose time is unreadable or in the future still silences invitations. Every
// in-range time behaves as before. Builders copied from
// tests/test_advisor_skippers.mjs (not exported there). Offline: real
// migrations in node:sqlite, no model.
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
const {runTurn} = await import('../server/advisor/engine.ts');
const {t} = await import('../server/advisor/strings.ts');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const T0 = Date.parse('2026-10-03T17:00:00Z');
const HOUR = 3600000, DAY = 24 * HOUR;
const KEY = Buffer.alloc(32, 7).toString('base64');
const iso = ms => new Date(ms).toISOString();
const quiet = async fn => { const saved = {log: console.log, warn: console.warn, error: console.error}; console.log = console.warn = console.error = () => {}; try { return await fn(); } finally { Object.assign(console, saved); } };

function setup({contact = {}} = {}) {
  const {sql, db} = advisorDatabase();
  const c = {id: 'c1', phone_hash: 'h1', phone_enc: 'ENC', role: 'angler', boat_id: null, ...contact};
  sql.prepare(`INSERT INTO advisor_contacts(id,phone_hash,phone_enc,channel,role,language,boat_id,display_name,home_port,status,last_seen_at,created_at,updated_at) VALUES(?,?,?,'imessage',?,'en',?,NULL,NULL,'active',?,?,?)`)
    .run(c.id, c.phone_hash, c.phone_enc, c.role, c.boat_id, iso(T0), iso(T0), iso(T0));
  sql.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,body,status,created_at) VALUES('seen','c1','in','imessage','earlier','done',?)`).run(iso(T0 - 30 * DAY));
  return {sql, db, env: {TEXT_ADVISOR_ENABLED: 'true', DB: db, ADVISOR_NUMBER: '+155****0199', ADVISOR_PHONE_KEY: KEY}};
}
function addBoat(sql, b) {
  sql.prepare(`INSERT INTO advisor_boats(id,slug,name,port,region,owner_contact_id,status,consent_photos_at,consent_revoked_at,created_at,updated_at) VALUES(?,?,?,'morro-bay','morro-bay',?,'pending',NULL,NULL,?,?)`)
    .run(b.id, b.slug, b.name, b.owner ?? null, b.created ?? iso(T0 - 30 * DAY), iso(T0));
}
let seq = 0;
function inbound(sql, body, {media = null} = {}) {
  const id = `in${++seq}`;
  sql.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,body,media_json,status,created_at) VALUES(?,'c1','in','imessage',?,?,'processing',?)`).run(id, body, media ? JSON.stringify(media) : null, iso(T0));
  return sql.prepare('SELECT * FROM advisor_messages WHERE id=?').get(id);
}
const contactRow = sql => sql.prepare("SELECT * FROM advisor_contacts WHERE id='c1'").get();
const texts = r => r.actions.filter(a => a.type === 'send_text').map(a => a.text);
const run = (env, sql, body, opts) => quiet(() => runTurn({env, contact: contactRow(sql), message: inbound(sql, body, opts), now: T0, deps: {clock: () => T0, sleep: async () => {}}}));
const setFlow = (sql, state) => sql.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value').run(sk.flowKey('c1'), JSON.stringify(state), iso(T0));
const landingStep = askedAt => ({flow: 'register', step: 'landing', draft: {name: 'Sea Example', port: 'morro-bay', lang: 'en'}, asked_at: askedAt});

// ---- register step freshness ---------------------------------------------------------------

async function registerReply(askedAt) {
  const {sql, env} = setup();
  setFlow(sql, landingStep(askedAt));
  return run(env, sql, 'Morro Bay Landing');
}
const abandoned = (r, label) => {
  assert.notEqual(r.intent, 'skipper.register.landing', `${label}: not read as a register answer`);
  assert.deepEqual(r.actions[0], {type: 'flow_set', state: null}, `${label}: the flow is deleted`);
  assert.ok(!texts(r).some(x => /Instagram/i.test(x)), `${label}: no next registration question`);
};

dbTest('register: an hour-old step and one exactly 24 h old are still pending', async () => {
  for (const askedAt of [iso(T0 - HOUR), iso(T0 - sk.FLOW_MAX_AGE_MS)]) {
    const r = await registerReply(askedAt);
    assert.equal(r.intent, 'skipper.register.landing', askedAt);
    assert.notDeepEqual(r.actions[0], {type: 'flow_set', state: null}, askedAt);
  }
});

dbTest('register: a step 25 h old, one asked 2 h in the future, and an unreadable one are abandoned', async () => {
  abandoned(await registerReply(iso(T0 - 25 * HOUR)), '25 h old');
  abandoned(await registerReply(iso(T0 + 2 * HOUR)), 'future');
  abandoned(await registerReply('garbage'), 'garbage');
  abandoned(await registerReply(iso(T0 - sk.FLOW_MAX_AGE_MS - 1)), 'one ms past 24 h');
});

// ---- the 7-day consent re-ask --------------------------------------------------------------

async function photoReply({askedAt = null, created} = {}) {
  const {sql, env} = setup({contact: {role: 'skipper', boat_id: 'b1'}});
  addBoat(sql, {id: 'b1', slug: 'sea-example', name: 'Sea Example', owner: 'c1', created});
  if (askedAt !== null) setFlow(sql, {flow: 'consent', step: 'declined', draft: {boat_id: 'b1'}, asked_at: askedAt});
  return run(env, sql, null, {media: ['m1']});
}
const ACK = [t('en', 'media_ack')];
const REASK = [t('en', 'media_ack'), t('en', 'consent_ask', {name: 'Sea Example'})];

dbTest('consent re-ask: 3 days after the last ask nothing, 8 days and a future ask time re-ask', async () => {
  assert.deepEqual(texts(await photoReply({askedAt: iso(T0 - 3 * DAY)})), ACK, '3 days: no re-ask');
  assert.deepEqual(texts(await photoReply({askedAt: iso(T0 - sk.CONSENT_REASK_MS + 1)})), ACK, 'just under 7 days: no re-ask');
  assert.deepEqual(texts(await photoReply({askedAt: iso(T0 - 8 * DAY)})), REASK, '8 days: re-ask');
  const future = await photoReply({askedAt: iso(T0 + 30 * DAY)});
  assert.deepEqual(texts(future), REASK, 'an ask time 30 days ahead does not mute the re-ask');
  assert.equal(future.actions.at(-1).state.asked_at, iso(T0), 'the ask time is reset to now');
  assert.deepEqual(texts(await photoReply({askedAt: 'garbage'})), REASK, 'an unreadable ask time re-asks');
});

dbTest('consent re-ask with no consent state goes by the boat age: young none, old/unreadable/future re-ask', async () => {
  assert.deepEqual(texts(await photoReply({created: iso(T0 - 2 * DAY)})), ACK, 'a 2-day-old boat: no ask yet');
  assert.deepEqual(texts(await photoReply({created: iso(T0 - 30 * DAY)})), REASK, 'a 30-day-old boat');
  assert.deepEqual(texts(await photoReply({created: 'not a date'})), REASK, 'an unreadable created_at');
  assert.deepEqual(texts(await photoReply({created: iso(T0 + 30 * DAY)})), REASK, 'a future created_at');
});

// ---- crew NO -------------------------------------------------------------------------------

async function declinedAt(updatedAt) {
  const {sql, db} = setup();
  if (updatedAt !== null) sql.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?)').run(sk.crewDeclineKey('b1', 'c1'), '1', updatedAt);
  return sk.crewDeclined(db, 'b1', 'c1', T0);
}

dbTest('crewDeclined: a NO under 30 days, unreadable or future-dated silences; 30+ days or none does not', async () => {
  assert.equal(await declinedAt(iso(T0 - 10 * DAY)), true, '10 days old');
  assert.equal(await declinedAt(iso(T0 - 31 * DAY)), false, '31 days old');
  assert.equal(await declinedAt(iso(T0 - sk.CREW_DECLINE_MS)), false, 'exactly 30 days: expired (<)');
  assert.equal(await declinedAt(iso(T0 - sk.CREW_DECLINE_MS + 1)), true, 'one ms under 30 days');
  assert.equal(await declinedAt('not a date'), true, 'an undatable NO stays a NO');
  assert.equal(await declinedAt(''), true, 'an empty time stays a NO');
  assert.equal(await declinedAt(iso(T0 + DAY)), true, 'a NO dated a day ahead stays a NO');
  assert.equal(await declinedAt(null), false, 'no row: no NO');
});
