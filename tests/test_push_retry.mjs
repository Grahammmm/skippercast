// Push delivery retries (server/trips.ts deliver/retryable): a receipt that failed with 429 or 5xx
// is sent again on later checks, at most 3 attempts in all, while the event stays 'pending'.
// 'uncertain' (network error/timeout), 'sending' (crash), 'accepted', 'expired' and other failures are final.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
const {checkOwnerTrips, retryable} = await import('../server/trips.ts');
const {hash} = await import('../server/http.ts');

function database() {
  const sql = new DatabaseSync(':memory:'), journal = read('../drizzle/meta/_journal.json');
  for (const {tag} of [...journal.entries].sort((a, b) => a.idx - b.idx)) sql.exec(readFileSync(new URL(`../drizzle/${tag}.sql`, import.meta.url), 'utf8'));
  const adapter = {prepare(query) { let args = []; const statement = sql.prepare(query); return {bind(...a) { args = a; return this; }, async first() { return statement.get(...args) || null; }, async all() { return {results: statement.all(...args)}; }, async run() { const info = statement.run(...args); return {meta: {changes: Number(info.changes)}}; }}; },
    async batch(queries) { sql.exec('BEGIN'); try { const out = []; for (const q of queries) out.push(await q.run()); sql.exec('COMMIT'); return out; } catch (e) { sql.exec('ROLLBACK'); throw e; } }};
  return {sql, adapter};
}
const b64url = bytes => Buffer.from(bytes).toString('base64url');
async function pushKeys() {
  const client = await crypto.subtle.generateKey({name: 'ECDH', namedCurve: 'P-256'}, true, ['deriveBits']);
  return {p256dh: b64url(new Uint8Array(await crypto.subtle.exportKey('raw', client.publicKey))), auth: b64url(crypto.getRandomValues(new Uint8Array(16)))};
}
async function vapid() {
  const pair = await crypto.subtle.generateKey({name: 'ECDSA', namedCurve: 'P-256'}, true, ['sign', 'verify']);
  return {VAPID_PUBLIC_KEY: b64url(new Uint8Array(await crypto.subtle.exportKey('raw', pair.publicKey))), VAPID_PRIVATE_KEY: (await crypto.subtle.exportKey('jwk', pair.privateKey)).d};
}

// Trip on 2026-11-12, saved two days before; 03:00Z is 19:00 PST the evening before, so each check is the day-before final.
const DAY = '2026-11-12', SAVED = '2026-11-10T20:00:00.000Z', EVENING = Date.parse('2026-11-12T03:00:00Z');
const PUSH = 'https://fcm.googleapis.com/fcm/send/';

// `replies[sub]` lists what the push service answers to each send to that subscription:
// a status number, or 'timeout' for a network error. Feeds are unavailable (503).
async function scenario(replies, run) {
  const {sql, adapter} = database(), original = globalThis.fetch, env = {DB: adapter, ...await vapid()}, pushes = [];
  sql.prepare('INSERT INTO trips(id,owner,region,point,species,date,start_hour,end_hour,wind_limit,gust_limit,sea_limit,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)').run('trip-1', 'alice', 'morro-bay', 'north', 'reef', DAY, 7, 13, 8, 12, 3, SAVED);
  for (const sub of Object.keys(replies)) {
    const keys = await pushKeys();
    sql.prepare('INSERT INTO subscriptions(id,owner,endpoint,p256dh,auth,created_at) VALUES(?,?,?,?,?,?)').run(sub, 'alice', PUSH + sub, keys.p256dh, keys.auth, SAVED);
  }
  globalThis.fetch = async url => {
    if (!String(url).startsWith(PUSH)) return new Response('{}', {status: 503});
    const sub = String(url).slice(PUSH.length), reply = replies[sub][pushes.filter(p => p === sub).length];
    pushes.push(sub);
    if (reply === 'timeout' || reply === undefined) throw new DOMException('timed out', 'TimeoutError');
    return new Response(null, {status: reply});
  };
  const eventId = await hash('trip-1:final');
  const receipt = async (sub, n) => sql.prepare('SELECT status,http_status FROM delivery_receipts WHERE id=?').get(await hash(eventId + ':' + sub + (n > 1 ? ':' + n : ''))) || null;
  const ctx = {sql, eventId, pushes, receipt,
    check: () => checkOwnerTrips(env, 'alice', EVENING, new Map()),
    event: () => sql.prepare('SELECT status FROM alert_events WHERE id=?').get(eventId)?.status,
    receipts: () => sql.prepare('SELECT COUNT(*) AS n FROM delivery_receipts').get().n,
    finalAt: () => sql.prepare('SELECT final_delivered_at FROM trips WHERE id=?').get('trip-1').final_delivered_at};
  try { await run(ctx); } finally { globalThis.fetch = original; sql.close(); }
}

test('retryable: only failed 429/5xx with fewer than 3 attempts', () => {
  assert.equal(retryable('failed', 429, 1), true);
  assert.equal(retryable('failed', 503, 2), true);
  assert.equal(retryable('failed', 500, 1), true);
  assert.equal(retryable('failed', 599, 2), true);
  assert.equal(retryable('failed', 503, 3), false, 'three attempts used');
  assert.equal(retryable('failed', 429, 3), false, 'three attempts used');
  for (const code of [400, 401, 403, 404, 413, 600, null]) assert.equal(retryable('failed', code, 1), false, String(code));
  assert.equal(retryable('uncertain', null, 1), false);
  assert.equal(retryable('accepted', 201, 1), false);
  for (const status of ['sending', 'expired']) assert.equal(retryable(status, 503, 1), false, status);
});

test('503, 503, then 201 on three checks: receipts failed, failed, accepted; event delivered; final recorded', () => scenario({'sub-1': [503, 503, 201]}, async ({pushes, receipt, check, event, receipts, finalAt}) => {
  const first = await check();
  assert.equal(first.held, 1);assert.equal(event(), 'pending', 'still retryable');assert.equal(finalAt(), null);
  await check();
  assert.equal(event(), 'pending');
  const third = await check();
  assert.equal(third.delivered, 1);assert.equal(event(), 'delivered');assert.ok(finalAt(), 'final_delivered_at set');
  assert.deepEqual([await receipt('sub-1', 1), await receipt('sub-1', 2), await receipt('sub-1', 3)].map(r => ({...r})),
    [{status: 'failed', http_status: 503}, {status: 'failed', http_status: 503}, {status: 'accepted', http_status: 201}]);
  assert.equal(receipts(), 3);assert.equal(pushes.length, 3);
  await check();assert.equal(pushes.length, 3, 'a delivered final is never resent');
}));

test('429 three times: exactly 3 pushes, then held; a 4th check sends nothing', () => scenario({'sub-1': [429, 429, 429, 201]}, async ({pushes, check, event, receipts, finalAt}) => {
  await check();await check();
  assert.equal(event(), 'pending');assert.equal(pushes.length, 2);
  const third = await check();
  assert.equal(third.held, 1);assert.equal(event(), 'held');assert.equal(pushes.length, 3);
  await check();await check();
  assert.equal(pushes.length, 3, 'no fourth attempt');assert.equal(receipts(), 3);assert.equal(finalAt(), null);
}));

for (const code of [400, 401, 403, 413, 418]) {
  test(`a ${code} is final: one push ever, event held`, () => scenario({'sub-1': [code, 201]}, async ({pushes, receipt, check, event, receipts}) => {
    await check();await check();await check();
    assert.equal(pushes.length, 1);assert.equal(event(), 'held');assert.equal(receipts(), 1);
    assert.equal((await receipt('sub-1', 1)).status, 'failed');
  }));
}

test('a network error or timeout (uncertain) is never resent; event held', () => scenario({'sub-1': ['timeout', 201]}, async ({pushes, receipt, check, event, receipts}) => {
  await check();await check();
  assert.equal(pushes.length, 1);assert.equal(event(), 'held');assert.equal(receipts(), 1);
  assert.equal((await receipt('sub-1', 1)).status, 'uncertain');
}));

test('a timeout on the retry ends the retries: 503 then timeout, then nothing', () => scenario({'sub-1': [503, 'timeout', 201]}, async ({pushes, receipt, check, event}) => {
  await check();await check();await check();
  assert.equal(pushes.length, 2);assert.equal(event(), 'held');
  assert.equal((await receipt('sub-1', 2)).status, 'uncertain');assert.equal(await receipt('sub-1', 3), null);
}));

test('a receipt left sending by a crash is never resent', () => scenario({'sub-1': [201]}, async ({sql, eventId, pushes, check, event}) => {
  sql.prepare('INSERT INTO alert_events(id,trip_id,owner,kind,message,created_at) VALUES(?,?,?,?,?,?)').run(eventId, 'trip-1', 'alice', 'final', 'x', SAVED);
  sql.prepare('INSERT INTO delivery_receipts(id,event_id,subscription_id,status,attempt_at) VALUES(?,?,?,?,?)').run(await hash(eventId + ':sub-1'), eventId, 'sub-1', 'sending', SAVED);
  await check();await check();
  assert.equal(pushes.length, 0);assert.equal(event(), 'held');
}));

test('a retry left sending by a crash (attempt 2) is never resent', () => scenario({'sub-1': [503, 201]}, async ({sql, eventId, pushes, check, event}) => {
  await check();assert.equal(pushes.length, 1);
  sql.prepare('INSERT INTO delivery_receipts(id,event_id,subscription_id,status,attempt_at) VALUES(?,?,?,?,?)').run(await hash(eventId + ':sub-1:2'), eventId, 'sub-1', 'sending', SAVED);
  await check();await check();
  assert.equal(pushes.length, 1);assert.equal(event(), 'held');
}));

test('two subscriptions, one 201 and one 503: delivered on the first check, the failed one is not retried', () => scenario({'sub-a': [201, 201], 'sub-b': [503, 201]}, async ({pushes, receipt, check, event, receipts}) => {
  const first = await check();
  assert.equal(first.delivered, 1);assert.equal(event(), 'delivered');assert.equal(pushes.length, 2);
  await check();await check();
  assert.equal(pushes.length, 2);assert.equal(receipts(), 2);assert.equal(await receipt('sub-b', 2), null);
}));

test('two subscriptions, one 400 and one 503: pending while one can retry, held once both are final', () => scenario({'sub-a': [400, 201], 'sub-b': [503, 503, 503, 201]}, async ({pushes, check, event}) => {
  await check();assert.equal(event(), 'pending');assert.equal(pushes.length, 2);
  await check();assert.equal(event(), 'pending');assert.deepEqual(pushes.slice(2), ['sub-b'], 'only the retryable subscription is resent');
  await check();assert.equal(event(), 'held');assert.equal(pushes.length, 4);
  await check();assert.equal(pushes.length, 4);
}));
