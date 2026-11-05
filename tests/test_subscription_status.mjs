// SC2037-12: POST /api/subscription/status and the saved-trip sheet's device state. Browser and fetch are mocked; no push is sent.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html', '/index.html': '/index.0123456789.html', '/landing.html': '/landing.0123456789.html', '/app.html': '/app.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
import {withSessions} from './fixtures/test-sessions.mjs';
const {default: deployed} = await import('../server/index.ts');
const worker = withSessions(deployed);
const alerts = await import('../web/alerts.ts');

function database() {
  const sql = new DatabaseSync(':memory:'), journal = read('../drizzle/meta/_journal.json');
  for (const {tag} of [...journal.entries].sort((a, b) => a.idx - b.idx)) sql.exec(readFileSync(new URL(`../drizzle/${tag}.sql`, import.meta.url), 'utf8'));
  const adapter = {prepare(query) { let args = []; const st = sql.prepare(query); return {bind(...a) { args = a; return this; }, async first() { return st.get(...args) || null; }, async all() { return {results: st.all(...args)}; }, async run() { const i = st.run(...args); return {meta: {changes: Number(i.changes)}}; }}; }};
  return {sql, adapter};
}
const origin = 'https://skippercast.com';
const request = (path, {owner, method = 'POST', body} = {}) => {
  const headers = {'Content-Type': 'application/json', Origin: origin};
  if (owner) headers['x-test-owner'] = owner;
  return new Request(origin + path, {method, headers, body: typeof body === 'string' ? body : JSON.stringify(body)});
};
async function pushKeys() {
  const b64url = bytes => Buffer.from(bytes).toString('base64url');
  const client = await crypto.subtle.generateKey({name: 'ECDH', namedCurve: 'P-256'}, true, ['deriveBits']);
  return {p256dh: b64url(await crypto.subtle.exportKey('raw', client.publicKey)), auth: b64url(crypto.getRandomValues(new Uint8Array(16)))};
}
const ENDPOINT = 'https://fcm.googleapis.com/fcm/send/device-1';

test('status route: own endpoint true; absent and another owner\'s both false and identical; nothing written; signed out refused', async () => {
  const {sql, adapter} = database(), env = {DB: adapter}, keys = await pushKeys();
  const call = (owner, endpoint) => worker.fetch(request('/api/subscription/status', {owner, body: {endpoint}}), env);
  assert.equal((await worker.fetch(request('/api/subscription', {owner: 'alice', body: {endpoint: ENDPOINT, keys}}), env)).status, 200);
  const before = sql.prepare('SELECT * FROM subscriptions').all();
  const own = await call('alice', ENDPOINT);
  assert.equal(own.status, 200);
  assert.deepEqual(await own.json(), {registered: true});
  const other = await call('bob', ENDPOINT), absent = await call('alice', 'https://fcm.googleapis.com/fcm/send/never');
  assert.equal(other.status, 200); assert.equal(absent.status, 200);
  const [o, a] = [await other.text(), await absent.text()];
  assert.equal(o, a, 'another owner\'s endpoint and an absent one answer alike');
  assert.deepEqual(JSON.parse(o), {registered: false});
  const after = sql.prepare('SELECT * FROM subscriptions').all();
  assert.ok(JSON.stringify(after) === JSON.stringify(before), 'status writes nothing');
  assert.equal(sql.prepare('SELECT COUNT(*) AS n FROM subscriptions').get().n, 1);
  const signedOut = await call(undefined, ENDPOINT);
  assert.ok(signedOut.status === 401 || signedOut.status === 403, `signed out refused (${signedOut.status})`);
  assert.notEqual(await signedOut.text().then(t => t.includes('registered')), true);
});

test('status route: bad bodies are 400', async () => {
  const {adapter} = database(), env = {DB: adapter};
  for (const body of [{}, {endpoint: ''}, {endpoint: 5}, {endpoint: 'x'.repeat(2001)}, {endpoint: ENDPOINT, all: true}]) {
    const r = await worker.fetch(request('/api/subscription/status', {owner: 'alice', body}), env);
    assert.equal(r.status, 400, JSON.stringify(body).slice(0, 60));
  }
});

/** A mock browser; `server` answers the status call. */
function world({permission = 'granted', subscribed = true, worker = true, server = () => new Response(JSON.stringify({registered: true}), {status: 200})} = {}) {
  const log = [];
  const sub = subscribed ? {endpoint: ENDPOINT, async unsubscribe() { return true; }} : null;
  const nav = worker ? {serviceWorker: {async getRegistration() { return {pushManager: {async getSubscription() { return sub; }, async subscribe() { log.push('SUBSCRIBE'); }}}; }, async register() { log.push('REGISTER'); }}} : {};
  const notif = {permission, requestPermission() { log.push('requestPermission'); }};
  const fetchFn = async (url, init) => { log.push(`${init.method} ${url} ${init.body ?? ''}`); return server(); };
  return {log, nav, notif, fetchFn, status: () => alerts.deviceStatus(fetchFn, nav, notif)};
}
globalThis.PushManager = class {};

test('deviceStatus: each of the six states', async () => {
  assert.equal(await world().status(), 'confirmed');
  assert.equal(await world({server: () => new Response(JSON.stringify({registered: false}), {status: 200})}).status(), 'not-sending');
  assert.equal(await world({server: () => new Response('{}', {status: 503})}).status(), 'unchecked');
  assert.equal(await world({permission: 'denied'}).status(), 'blocked');
  assert.equal(await world({subscribed: false, permission: 'default'}).status(), 'off');
  assert.equal(await world({worker: false}).status(), 'unavailable');
  assert.equal(alerts.DEVICE_LINE.unavailable, 'Notifications are not available here. On iPad/iPhone, add SkipperCast to the Home Screen and open it there.');
  assert.match(alerts.DEVICE_LINE.blocked, /settings/);
});

test('deviceStatus: opening asks no permission, subscribes nothing, and asks the server only with a local subscription', async () => {
  for (const o of [{}, {subscribed: false}, {permission: 'denied'}, {permission: 'default'}]) {
    const w = world(o); await w.status();
    assert.ok(!w.log.some(l => l === 'requestPermission' || l === 'REGISTER' || l === 'SUBSCRIBE'), JSON.stringify(o));
    if (o.subscribed === false || o.permission === 'denied') assert.deepEqual(w.log, [], 'no server call');
  }
  const w = world(); await w.status();
  assert.deepEqual(w.log, [`POST /api/subscription/status {"endpoint":"${ENDPOINT}"}`]);
});

test('deviceStatus: a failed check never shows on', async () => {
  for (const server of [() => { throw new TypeError('Failed to fetch'); }, () => new Response('{}', {status: 500}), () => new Response('not json', {status: 200}), () => new Response('{}', {status: 200}), () => new Response(JSON.stringify({registered: 'yes'}), {status: 200})]) {
    assert.equal(await world({server}).status(), 'unchecked');
  }
});

test('other phone stopped all devices: granted + local subscription + no row shows not sending, Enable offered, Stop on this device kept', async () => {
  const {adapter} = database(), env = {DB: adapter}, keys = await pushKeys();
  await worker.fetch(request('/api/subscription', {owner: 'alice', body: {endpoint: ENDPOINT, keys}}), env);
  await worker.fetch(request('/api/subscription', {owner: 'alice', method: 'DELETE', body: {all: true}}), env);
  const w = world({server: (u, i) => undefined});
  w.fetchFn = async (url, init) => worker.fetch(request(url, {owner: 'alice', method: init.method, body: init.body}), env);
  const s = await alerts.deviceStatus(w.fetchFn, w.nav, w.notif);
  assert.equal(s, 'not-sending');
  assert.deepEqual(alerts.deviceButtons(s), {enable: true, stopDevice: true});
});

test('account switch: the earlier owner\'s local subscription shows not sending; Enable (POST) answers 409 with the existing words', async () => {
  const {adapter} = database(), env = {DB: adapter}, keys = await pushKeys();
  await worker.fetch(request('/api/subscription', {owner: 'alice', body: {endpoint: ENDPOINT, keys}}), env);
  const asBob = async (url, init) => worker.fetch(request(url, {owner: 'bob', method: init.method, body: init.body}), env);
  const w = world();
  const s = await alerts.deviceStatus(asBob, w.nav, w.notif);
  assert.equal(s, 'not-sending');
  assert.equal(alerts.deviceButtons(s).enable, true);
  await assert.rejects(alerts.api('subscription', {method: 'POST', body: JSON.stringify({endpoint: ENDPOINT, keys})}, asBob), {message: 'Subscription belongs to another signed-in user'});
});

test('buttons: Enable hidden only when confirmed; Stop on this device only with a local subscription', () => {
  const b = alerts.deviceButtons;
  assert.deepEqual(b('confirmed'), {enable: false, stopDevice: true});
  assert.deepEqual(b('not-sending'), {enable: true, stopDevice: true});
  assert.deepEqual(b('unchecked'), {enable: true, stopDevice: true});
  for (const s of ['blocked', 'off', 'unavailable', null]) assert.deepEqual(b(s), {enable: true, stopDevice: false}, String(s));
});

test('latestCheck: a slow opening check answering after the post-stop refresh is dropped', async () => {
  const pending = [], seen = [];
  const run = alerts.latestCheck(() => new Promise(resolve => pending.push(resolve)), v => seen.push(v), () => 'unchecked');
  run(); run(); // opening check, then the refresh after Stop on all devices
  pending[1]('off');
  await new Promise(r => setImmediate(r));
  pending[0]('confirmed'); // the delayed opening answer
  await new Promise(r => setImmediate(r));
  assert.deepEqual(seen, ['off']);
});

test('latestCheck: a failed latest check reports unchecked; an older failure is dropped', async () => {
  const pending = [], seen = [];
  const run = alerts.latestCheck(() => new Promise((resolve, reject) => pending.push({resolve, reject})), v => seen.push(v), () => 'unchecked');
  run(); run();
  pending[0].reject(new Error('x')); pending[1].reject(new Error('y'));
  await new Promise(r => setImmediate(r));
  assert.deepEqual(seen, ['unchecked']);
});
