// SC2037-13: real routes, synthetic in-memory D1 and generated keys; every push is intercepted.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {mkdtemp, readFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {hkdfSync} from 'node:crypto';
import {DatabaseSync} from 'node:sqlite';
import vm from 'node:vm';
import {build} from 'esbuild';
import {withSessions} from './fixtures/test-sessions.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {};
globalThis.BUILD_ID = 'build-test';
const {default: deployed} = await import('../server/index.ts');
const worker = withSessions(deployed);
const {budget, hash} = await import('../server/http.ts');
const {sendTestNotification, deviceStatus} = await import('../web/alerts.ts');
const ORIGIN = 'https://skippercast.com', ENDPOINT = 'https://fcm.googleapis.com/fcm/send/fixture';
const MESSAGE = 'SkipperCast test notification. Trip alerts will arrive like this.';
const b64 = bytes => Buffer.from(bytes).toString('base64url');
const hkdf = (key, salt, info, length) => new Uint8Array(hkdfSync('sha256', key, salt, info, length));

async function scenario(run) {
  const sql = new DatabaseSync(':memory:');
  for (const {tag} of read('../drizzle/meta/_journal.json').entries) sql.exec(readFileSync(new URL(`../drizzle/${tag}.sql`, import.meta.url), 'utf8'));
  const writes = [];
  const DB = {prepare(query) {
    const st = sql.prepare(query); let args = [];
    if (/^\s*(INSERT|UPDATE|DELETE)/i.test(query)) writes.push(query);
    return {bind(...a) { args = a; return this; }, async first() { return st.get(...args) ?? null; }, async all() { return {results: st.all(...args)}; }, async run() { return {meta: {changes: Number(st.run(...args).changes)}}; }};
  }};
  const client = await crypto.subtle.generateKey({name: 'ECDH', namedCurve: 'P-256'}, true, ['deriveBits']);
  const publicBytes = new Uint8Array(await crypto.subtle.exportKey('raw', client.publicKey)), auth = crypto.getRandomValues(new Uint8Array(16));
  const vapid = await crypto.subtle.generateKey({name: 'ECDSA', namedCurve: 'P-256'}, true, ['sign', 'verify']);
  const env = {DB, VAPID_PUBLIC_KEY: b64(await crypto.subtle.exportKey('raw', vapid.publicKey)), VAPID_PRIVATE_KEY: (await crypto.subtle.exportKey('jwk', vapid.privateKey)).d};
  const add = async (owner, endpoint) => sql.prepare('INSERT INTO subscriptions(id,owner,endpoint,p256dh,auth,created_at) VALUES(?,?,?,?,?,?)').run(await hash(endpoint), owner, endpoint, b64(publicBytes), b64(auth), '2026-11-01T00:00:00Z');
  await add('alice', ENDPOINT);
  await add('alice', ENDPOINT + '-phone');
  await add('bob', ENDPOINT + '-bob');
  const call = (endpoint = ENDPOINT, owner = 'alice', value = {endpoint}) => worker.fetch(new Request(ORIGIN + '/api/subscription/test', {method: 'POST', headers: {'Content-Type': 'application/json', Origin: ORIGIN, ...(owner ? {'x-test-owner': owner} : {})}, body: JSON.stringify(value)}), env);
  const pushes = [], original = globalThis.fetch;
  let reply = 201;
  globalThis.fetch = async (url, init) => {
    pushes.push({url, init});
    if (reply === 'timeout') throw new DOMException('timed out', 'TimeoutError');
    return new Response(null, {status: reply});
  };
  // Independently decrypt the actual sender's RFC8291 payload using this device's private key.
  async function payload(push) {
    const bytes = new Uint8Array(push.init.body), salt = bytes.slice(0, 16), keyEnd = 21 + bytes[20], serverBytes = bytes.slice(21, keyEnd);
    const server = await crypto.subtle.importKey('raw', serverBytes, {name: 'ECDH', namedCurve: 'P-256'}, false, []);
    const secret = new Uint8Array(await crypto.subtle.deriveBits({name: 'ECDH', public: server}, client.privateKey, 256));
    const info = Buffer.concat([Buffer.from('WebPush: info\0'), publicBytes, serverBytes]);
    const ikm = hkdf(secret, auth, info, 32), cek = hkdf(ikm, salt, Buffer.from('Content-Encoding: aes128gcm\0'), 16), iv = hkdf(ikm, salt, Buffer.from('Content-Encoding: nonce\0'), 12);
    const key = await crypto.subtle.importKey('raw', cek, 'AES-GCM', false, ['decrypt']);
    const padded = new Uint8Array(await crypto.subtle.decrypt({name: 'AES-GCM', iv}, key, bytes.slice(keyEnd)));
    let end = padded.length - 1; while (padded[end] === 0) end--;
    assert.equal(padded[end], 2);
    return JSON.parse(new TextDecoder().decode(padded.slice(0, end)));
  }
  try { await run({sql, env, call, pushes, payload, reply: value => { reply = value; }}); }
  finally {
    globalThis.fetch = original;
    assert.ok(!writes.some(q => /(?:INSERT(?: OR IGNORE)? INTO|UPDATE|DELETE FROM) (?:alert_events|delivery_receipts)\b/i.test(q)), 'no event or receipt writes, even temporary ones');
    for (const table of ['alert_events', 'delivery_receipts']) assert.equal(sql.prepare(`SELECT COUNT(*) AS n FROM ${table}`).get().n, 0, table);
    sql.close();
  }
}

test('own endpoint: exactly one encrypted push, fixed words, VAPID key and test id; no fan-out or ledger writes', () => scenario(async ({env, call, pushes, payload}) => {
  const response = await call();
  assert.equal(response.status, 200);
  assert.equal((await response.json()).sent, true);
  assert.equal(pushes.length, 1); assert.equal(pushes[0].url, ENDPOINT);
  assert.equal(pushes[0].init.redirect, 'manual');
  assert.ok(pushes[0].init.headers.authorization.includes(env.VAPID_PUBLIC_KEY), 'same VAPID public key');
  const data = await payload(pushes[0]);
  assert.equal(data.title, 'SkipperCast'); assert.equal(data.body, MESSAGE);
  assert.match(data.eventId, /^test:[0-9a-f-]{36}$/); assert.equal(data.url, '/map#alerts');
}));

test('another owner and unknown endpoint: indistinguishable 404, even without VAPID; signed-out refused', () => scenario(async ({env, call, pushes}) => {
  delete env.VAPID_PRIVATE_KEY;
  const responses = [await call(ENDPOINT + '-bob'), await call(ENDPOINT + '-unknown')];
  for (const response of responses) { assert.equal(response.status, 404); assert.equal((await response.json()).error, 'Not found'); }
  assert.equal((await call(ENDPOINT, '')).status, 401);
  assert.equal(pushes.length, 0);
}));

test('invalid bodies: refused before a push', () => scenario(async ({call, pushes}) => {
  for (const value of [{}, {endpoint: ''}, {endpoint: 3}, {endpoint: 'x'.repeat(2001)}, {endpoint: ENDPOINT, all: true}, []]) assert.equal((await call(ENDPOINT, 'alice', value)).status, 400);
  assert.equal(pushes.length, 0);
}));

test('daily owner budget: duplicate taps and multiple devices share three attempts; another owner and next UTC day retain their own budgets', async t => {
  const start = Date.parse('2026-11-17T12:00:00Z');
  t.mock.method(Date, 'now', () => start);
  await scenario(async ({call, pushes}) => {
    const responses = await Promise.all([call(), call(), call(ENDPOINT + '-phone'), call()]);
    assert.equal(responses.filter(r => r.status === 200).length, 3);
    const limited = responses.find(r => r.status === 429);
    assert.ok(limited); assert.equal((await limited.json()).error, 'Please try again shortly');
    assert.equal(pushes.length, 3);
    assert.equal((await call(ENDPOINT + '-bob', 'bob')).status, 200);
    t.mock.method(Date, 'now', () => start + 60_000);
    assert.equal((await call()).status, 429, 'minute rollover does not reset test budget');
    t.mock.method(Date, 'now', () => start + 86_400_000);
    assert.equal((await call()).status, 200, 'new day resets test budget');
  });
});

test('default auth budget remains per minute with its original expiry', async t => {
  const start = Date.parse('2026-11-17T12:00:00Z');
  t.mock.method(Date, 'now', () => start);
  await scenario(async ({env, sql}) => {
    await budget(env, 'auth:fixture', 1);
    await assert.rejects(budget(env, 'auth:fixture', 1), /rate limited/);
    assert.equal(sql.prepare('SELECT expires_at FROM request_limits').get().expires_at, start / 1000 + 120);
    t.mock.method(Date, 'now', () => start + 60_000);
    await budget(env, 'auth:fixture', 1);
  });
});

for (const key of ['VAPID_PUBLIC_KEY', 'VAPID_PRIVATE_KEY']) test(`missing ${key}: 503 words, no send`, () => scenario(async ({env, call, pushes}) => {
  delete env[key]; const r = await call();
  assert.equal(r.status, 503); assert.equal((await r.json()).error, 'Notifications are not configured on this site.');
  assert.equal(pushes.length, 0);
}));

for (const code of [404, 410, 500, 429, 'timeout']) test(`push ${code}: honest error, no receipt; expiry removes only this row`, () => scenario(async ({sql, call, pushes, reply}) => {
  reply(code); const r = await call(), expired = code === 404 || code === 410;
  assert.equal(r.status, expired ? 410 : 502);
  assert.equal((await r.json()).error, expired ? 'This device is no longer subscribed. Press Enable to set it up again.' : 'The push service did not accept the test notification. Try again later.');
  assert.equal(pushes.length, 1);
  assert.equal(sql.prepare('SELECT COUNT(*) AS n FROM subscriptions').get().n, expired ? 2 : 3);
  if (expired) { assert.equal((await call()).status, 404); assert.equal(pushes.length, 1, 'stale row cannot send again'); }
}));

test('client sends only the named endpoint and propagates refusal words', async () => {
  const seen = [];
  await sendTestNotification(ENDPOINT, async (url, init) => { seen.push({url, init}); return Response.json({sent: true}); });
  assert.equal(seen.length, 1); assert.equal(seen[0].url, '/api/subscription/test');
  assert.equal(seen[0].init.method, 'POST'); assert.equal(seen[0].init.body, JSON.stringify({endpoint: ENDPOINT}));
  await assert.rejects(sendTestNotification(ENDPOINT, async () => Response.json({error: 'Not found'}, {status: 404})), /Not found/);
});

// Render the actual button and call its actual handler; the test-only export changes no production source.
const dir = await mkdtemp(join(tmpdir(), 'test-push-ui-')), out = join(dir, 'ui.mjs');
await build({stdin: {resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts', contents: `export {TestNotification, Said} from './web/app/TripAlerts.tsx'; export {language} from './web/i18n.ts'; export {h, options} from 'preact'; export {render} from 'preact-render-to-string';`}, bundle: true, platform: 'node', format: 'esm', outfile: out, jsx: 'automatic', jsxImportSource: 'preact', logLevel: 'silent', plugins: [{name: 'test-button', setup(b) { b.onLoad({filter: /\/TripAlerts\.tsx$/}, async ({path}) => ({contents: await readFile(path, 'utf8') + '\nexport {TestNotification, Said};', loader: 'tsx'})); }}]});
const ui = await import(pathToFileURL(out).href);
test.after(() => rm(dir, {recursive: true, force: true}));
function button(device, extra = {}) {
  let press; const prior = ui.options.vnode;
  ui.options.vnode = v => { prior?.(v); if (v.type === 'button') press = v.props.onClick; };
  try { return {html: ui.render(ui.h(ui.TestNotification, {device, stopping: false, say() {}, refresh() {}, ...extra})), press: () => press?.()}; }
  finally { ui.options.vnode = prior; }
}

test('rendered sheet button: shown only for server-confirmed, not browser-only, unconfirmed or failed-check states', async () => {
  assert.match(button('confirmed').html, />Send a test notification</);
  for (const state of ['not-sending', 'unchecked', 'blocked', 'off', 'unavailable', null]) assert.equal(button(state).html, '', String(state));
  globalThis.PushManager = class {};
  const nav = {serviceWorker: {async getRegistration() { return {pushManager: {async getSubscription() { return {endpoint: ENDPOINT}; }}}; }}};
  for (const registered of [false, undefined]) {
    const state = await deviceStatus(async () => Response.json({registered}), nav, {permission: 'granted'});
    assert.equal(button(state).html, '', 'browser permission and subscription are insufficient (stopped elsewhere or switched account)');
  }
  const state = await deviceStatus(async () => { throw Error('offline'); }, nav, {permission: 'granted'});
  assert.equal(button(state).html, '');
});

test('test notification copy follows the page language', () => {
  try {
    for (const [lang, label, message] of [
      ['en', 'Send a test notification', 'Test notification accepted by the push service. Check this device for it.'],
      ['es', 'Enviar una notificación de prueba', 'El servicio de notificaciones aceptó la prueba. Búscala en este dispositivo.'],
    ]) {
      ui.language.value = lang;
      assert.ok(button('confirmed').html.includes(label));
      assert.ok(ui.render(ui.h(ui.Said, {say: {id: 'alerts.test.sent'}, lang})).includes(message));
    }
  } finally { ui.language.value = 'en'; }
});

test('button handler: double tap sends once, reports result/refusal, refreshes status; missing local subscription never sends', async t => {
  const originalFetch = globalThis.fetch, originalNav = Object.getOwnPropertyDescriptor(globalThis, 'navigator');
  let sub = {endpoint: ENDPOINT}, resolve, calls = 0, refreshes = 0;
  Object.defineProperty(globalThis, 'navigator', {configurable: true, value: {serviceWorker: {async getRegistration() { return {pushManager: {async getSubscription() { return sub; }}}; }}}});
  t.after(() => { globalThis.fetch = originalFetch; if (originalNav) Object.defineProperty(globalThis, 'navigator', originalNav); else delete globalThis.navigator; });
  const said = [], props = {say: s => said.push(s), refresh: () => refreshes++};
  globalThis.fetch = async () => { calls++; return new Promise(r => { resolve = r; }); };
  const b = button('confirmed', props); b.press(); b.press();
  await new Promise(r => setImmediate(r)); assert.equal(calls, 1);
  resolve(Response.json({sent: true})); await new Promise(r => setImmediate(r));
  assert.equal(said.at(-1).id, 'alerts.test.sent'); assert.equal(refreshes, 1);
  globalThis.fetch = async () => { calls++; return Response.json({error: 'Not found'}, {status: 404}); };
  button('confirmed', props).press(); await new Promise(r => setImmediate(r));
  assert.equal(said.at(-1).literal, 'Not found'); assert.equal(refreshes, 2);
  sub = null; button('confirmed', props).press(); await new Promise(r => setImmediate(r));
  assert.equal(calls, 2); assert.equal(said.at(-1).id, 'alerts.device.notSending'); assert.equal(refreshes, 3);
  button('confirmed', {...props, stopping: true}).press(); await new Promise(r => setImmediate(r));
  assert.equal(calls, 2, 'stop in progress cannot send');
});

test('unchanged service worker displays test payload and opens saved-trip sheet on tap', async () => {
  const listeners = {}, shown = [], opened = [];
  const self = {location: {origin: ORIGIN}, addEventListener(name, fn) { listeners[name] = fn; }, registration: {async showNotification(title, options) { shown.push({title, options}); }}};
  vm.runInNewContext(readFileSync(new URL('../dist/sw.js', import.meta.url), 'utf8'), {self, URL, clients: {async matchAll() { return []; }, async openWindow(url) { opened.push(url); }}});
  let pending;
  listeners.push({data: {json: () => ({title: 'SkipperCast', body: MESSAGE, eventId: 'test:fixture', url: '/map#alerts'})}, waitUntil(p) { pending = p; }});
  await pending; assert.equal(shown.length, 1); assert.equal(shown[0].options.body, MESSAGE);
  let closed = false;
  listeners.notificationclick({notification: {close() { closed = true; }}, waitUntil(p) { pending = p; }});
  await pending; assert.ok(closed); assert.equal(opened[0], '/map#alerts');
});
