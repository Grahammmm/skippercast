// SC1537-08: the privacy export lists the account's notification devices as push service host and
// created date only; the endpoint path, the endpoint hash id, p256dh and auth never appear.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
import {withSessions} from './fixtures/test-sessions.mjs';
const {default: deployed} = await import('../server/index.ts');
const {deviceRow} = await import('../server/routes/account.ts');
const worker = withSessions(deployed);

function database() {
  // Every migration in journal order, as `wrangler d1 migrations apply` does (pattern of test_private_api.mjs).
  const sql = new DatabaseSync(':memory:'), journal = read('../drizzle/meta/_journal.json');
  for (const {tag} of [...journal.entries].sort((a, b) => a.idx - b.idx)) sql.exec(readFileSync(new URL(`../drizzle/${tag}.sql`, import.meta.url), 'utf8'));
  const adapter = {prepare(query) { let args = []; const statement = sql.prepare(query); return {bind(...a) { args = a; return this; }, async first() { return statement.get(...args) || null; }, async all() { return {results: statement.all(...args)}; }, async run() { const info = statement.run(...args); return {meta: {changes: Number(info.changes)}}; }}; }, async batch(queries) { sql.exec('BEGIN'); try { const result = []; for (const q of queries) result.push(await q.run()); sql.exec('COMMIT'); return result; } catch (e) { sql.exec('ROLLBACK'); throw e; } }};
  return {sql, adapter};
}
const subscribe = (sql, id, owner, endpoint, p256dh, auth, created_at) =>
  sql.prepare('INSERT INTO subscriptions(id,owner,endpoint,p256dh,auth,created_at) VALUES(?,?,?,?,?,?)').run(id, owner, endpoint, p256dh, auth, created_at);
async function exportFor(adapter, owner) {
  const response = await worker.fetch(new Request('https://skippercast.com/api/privacy', {headers: {'x-test-owner': owner}}), {DB: adapter});
  const text = await response.text();
  return {status: response.status, text, data: JSON.parse(text)};
}

test('two devices are listed newest first as host and date only; no path, id, p256dh or auth', async () => {
  const {sql, adapter} = database();
  const fcm = {id: 'sub-hash-fcm-7f3a', path: 'fcm-path-SECRETSEG-1', p256dh: 'P256DH-VALUE-FCM-' + 'x'.repeat(70), auth: 'AUTH-VALUE-FCM-zz'};
  const apple = {id: 'sub-hash-apple-9c1d', path: 'apple-path-SECRETSEG-2', p256dh: 'P256DH-VALUE-APPLE-' + 'y'.repeat(68), auth: 'AUTH-VALUE-APPLE-q'};
  subscribe(sql, fcm.id, 'alice', `https://fcm.googleapis.com/fcm/send/${fcm.path}`, fcm.p256dh, fcm.auth, '2026-10-01T08:00:00.000Z');
  subscribe(sql, apple.id, 'alice', `https://web.push.apple.com/${apple.path}`, apple.p256dh, apple.auth, '2026-10-20T08:00:00.000Z');
  const {status, text, data} = await exportFor(adapter, 'alice');
  assert.equal(status, 200);
  assert.deepEqual(data.devices, [
    {push_service: 'web.push.apple.com', created_at: '2026-10-20T08:00:00.000Z'},
    {push_service: 'fcm.googleapis.com', created_at: '2026-10-01T08:00:00.000Z'},
  ]);
  for (const s of [fcm, apple]) for (const secret of [s.id, s.path, s.p256dh, s.auth]) assert.ok(!text.includes(secret), `export leaks ${secret.slice(0, 12)}`);
  assert.ok(!text.includes('/fcm/send'), 'endpoint path prefix must not appear');
  assert.ok(!/"(endpoint|p256dh|auth|id)"\s*:/.test(JSON.stringify(data.devices)), 'device rows carry only push_service and created_at');
  assert.deepEqual(Object.keys(data), ['account', 'trips', 'feedback', 'events', 'devices'], 'devices follows events; no other key changes');
  sql.close();
});

test('no subscriptions gives devices: [] with the key present', async () => {
  const {sql, adapter} = database();
  const {status, data} = await exportFor(adapter, 'alice');
  assert.equal(status, 200);
  assert.ok('devices' in data);
  assert.deepEqual(data.devices, []);
  sql.close();
});

test("another owner's subscription is not listed", async () => {
  const {sql, adapter} = database();
  subscribe(sql, 'sub-bob', 'bob', 'https://updates.push.services.mozilla.com/wpush/v2/BOBSEG', 'kb', 'ab', '2026-10-21T00:00:00.000Z');
  subscribe(sql, 'sub-alice', 'alice', 'https://fcm.googleapis.com/fcm/send/ALICESEG', 'ka', 'aa', '2026-10-02T00:00:00.000Z');
  const alice = await exportFor(adapter, 'alice');
  assert.deepEqual(alice.data.devices, [{push_service: 'fcm.googleapis.com', created_at: '2026-10-02T00:00:00.000Z'}]);
  assert.ok(!alice.text.includes('mozilla'));
  const carol = await exportFor(adapter, 'carol');
  assert.deepEqual(carol.data.devices, []);
  sql.close();
});

test('legacy garbage endpoint, uppercase host and NULL created_at still export 200', async () => {
  const {sql, adapter} = database();
  // The migration column is NOT NULL; a legacy table without it is how a NULL date could exist.
  sql.exec('ALTER TABLE subscriptions RENAME TO subscriptions_old');
  sql.exec('CREATE TABLE subscriptions (id text PRIMARY KEY NOT NULL, owner text NOT NULL, endpoint text, p256dh text NOT NULL, auth text NOT NULL, created_at text)');
  subscribe(sql, 's-garbage', 'alice', 'not a url', 'k1', 'a1', '2026-10-03T00:00:00.000Z');
  subscribe(sql, 's-upper', 'alice', 'https://WEB.PUSH.APPLE.COM/UPPERSEG', 'k2', 'a2', '2026-10-04T00:00:00.000Z');
  subscribe(sql, 's-null', 'alice', 'https://fcm.googleapis.com/fcm/send/NULLSEG', 'k3', 'a3', null);
  const {status, text, data} = await exportFor(adapter, 'alice');
  assert.equal(status, 200);
  assert.deepEqual(data.devices, [
    {push_service: 'web.push.apple.com', created_at: '2026-10-04T00:00:00.000Z'},
    {push_service: 'unknown', created_at: '2026-10-03T00:00:00.000Z'},
    {push_service: 'fcm.googleapis.com', created_at: null},
  ]);
  for (const leak of ['not a url', 'UPPERSEG', 'NULLSEG', 'WEB.PUSH']) assert.ok(!text.includes(leak), `export leaks ${leak}`);
  sql.close();
});

test('deviceRow maps garbage to unknown, lowercases the host and nulls a non-string date', () => {
  assert.deepEqual(deviceRow({endpoint: 'not a url', created_at: 'd'}), {push_service: 'unknown', created_at: 'd'});
  for (const endpoint of [null, undefined, 42, {}, '', 'mailto:'])
    assert.equal(deviceRow({endpoint, created_at: 'd'}).push_service, 'unknown', `endpoint ${String(endpoint)}`);
  assert.deepEqual(deviceRow({endpoint: 'https://Fcm.GoogleAPIs.COM/fcm/send/AbC', created_at: '2026-10-05'}), {push_service: 'fcm.googleapis.com', created_at: '2026-10-05'});
  assert.equal(deviceRow({endpoint: 'https://wns2-par02p.NOTIFY.windows.com/w/?token=T', created_at: null}).push_service, 'wns2-par02p.notify.windows.com');
  for (const created_at of [null, undefined, 1730000000, {}]) assert.equal(deviceRow({endpoint: 'https://web.push.apple.com/x', created_at}).created_at, null);
  assert.deepEqual(Object.keys(deviceRow({endpoint: 'https://web.push.apple.com/x', created_at: 'd'})), ['push_service', 'created_at']);
});
