// HTTP-level coverage for Worker routes that were only unit-tested before:
// the model API through worker.fetch, the per-owner request budget,
// push subscriptions, delivery pruning, page shells, typed errors and health.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html', '/index.html': '/index.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
const {default: deployed, handle, checkTrips, ClientError} = await import('../server/worker.js');
// A test-only identity resolver, passed through handle(); the deployed fetch never reads it.
const worker = {fetch: (request, env, ctx) => handle(request, env, ctx, async r => r.headers.get('x-test-owner')), scheduled: deployed.scheduled};

function database() {
  const sql = new DatabaseSync(':memory:'), journal = read('../drizzle/meta/_journal.json');
  for (const {tag} of [...journal.entries].sort((a, b) => a.idx - b.idx)) sql.exec(readFileSync(new URL(`../drizzle/${tag}.sql`, import.meta.url), 'utf8'));
  const adapter = {prepare(query) { let args = []; const statement = sql.prepare(query); return {bind(...a) { args = a; return this; }, async first() { return statement.get(...args) || null; }, async all() { return {results: statement.all(...args)}; }, async run() { const info = statement.run(...args); return {meta: {changes: Number(info.changes)}}; }}; },
    async batch(queries) { sql.exec('BEGIN'); try { const out = []; for (const q of queries) out.push(await q.run()); sql.exec('COMMIT'); return out; } catch (e) { sql.exec('ROLLBACK'); throw e; } }};
  return {sql, adapter};
}
const origin = 'https://skippercast.com';
function request(path, {owner, method = 'GET', body} = {}) {
  const headers = {'Content-Type': 'application/json'};
  if (owner) headers['x-test-owner'] = owner;
  if (method !== 'GET') headers.Origin = origin;
  return new Request(origin + path, {method, headers, body: body === undefined ? undefined : typeof body === 'string' ? body : JSON.stringify(body)});
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

// A 2x2 wind tile at (35, -121) whose first step is "now", so the answer has values.
function windTile(start) {
  const q16 = values => Buffer.from(new Int16Array(values.map(v => Math.round(v / 0.01))).buffer).toString('base64');
  const field = value => ({scale: 0.01, data: q16(Array(2 * 4).fill(value))});
  return {schema_version: 1, model: 'gfs_global', key: '35_-121', times: [start, start + 3600], lat0: 35, lon0: -121, dlat: 0.25, dlon: 0.25, nlat: 2, nlon: 2,
    sea: Buffer.from([0xf0]).toString('base64'), fields: {u10: field(0), v10: field(-5), gust: field(8)}};
}

test('/api/om answers an Open-Meteo-style query through worker.fetch from the published tiles', async () => {
  const original = globalThis.fetch, requested = [];
  const start = Math.floor(Date.now() / 3600000) * 3600;
  globalThis.fetch = async (url, options) => {
    requested.push(url.replace(DEPLOYMENT.forecast_feed, ''));
    assert.equal(options.redirect, 'manual');
    if (url.endsWith('/manifest.json')) return Response.json({model: 'gfs_global', tiles: ['35_-121'], meta: {last_run_initialisation_time: start, data_end_time: start + 3600}});
    if (url.endsWith('/tiles/35_-121.json')) return Response.json(windTile(start));
    return new Response('missing', {status: 404});
  };
  try {
    const response = await worker.fetch(request('/api/om/v1/forecast?latitude=35.1&longitude=-120.9&models=gfs_global&hourly=wind_speed_10m,wind_gusts_10m&wind_speed_unit=kn&timezone=UTC&timeformat=unixtime&forecast_days=1'), {});
    assert.equal(response.status, 200);
    assert.equal(response.headers.get('Cache-Control'), 'public, max-age=300, s-maxage=300');
    const data = await response.json();
    assert.equal(data.hourly_units.wind_speed_10m, 'kn');
    const now = data.hourly.time.indexOf(start);
    assert.ok(now >= 0);assert.equal(data.hourly.wind_speed_10m[now], 9.7);assert.equal(data.hourly.wind_gusts_10m[now], 15.6);
    assert.deepEqual(requested, ['/gfs_global/manifest.json', '/gfs_global/tiles/35_-121.json']);
    const bad = await worker.fetch(request('/api/om/v1/forecast?latitude=north&longitude=-120.9'), {});
    assert.equal(bad.status, 400);assert.equal((await bad.json()).error, true);
    assert.equal((await worker.fetch(request('/api/om/data/not_a_model/static/meta.json'), {})).status, 400);
    assert.equal((await worker.fetch(request('/api/om/v1/other'), {})).status, 401, 'unknown om paths fall through to the private routes');
  } finally { globalThis.fetch = original; }
});

test('the per-owner budget allows 30 writes a minute, then answers 429', async () => {
  const {sql, adapter} = database(), realNow = Date.now, fixed = Date.now();
  Date.now = () => fixed;  // keep all requests inside one budget minute
  try {
    const body = {region: 'morro-bay', rating: 7, phase: 'fishing'};
    for (let i = 0; i < 30; i++) assert.equal((await worker.fetch(request('/api/comfort', {owner: 'alice', method: 'POST', body}), {DB: adapter})).status, 201);
    const limited = await worker.fetch(request('/api/comfort', {owner: 'alice', method: 'POST', body}), {DB: adapter});
    assert.equal(limited.status, 429);assert.deepEqual(await limited.json(), {error: 'Please try again shortly'});
    assert.equal((await worker.fetch(request('/api/comfort', {owner: 'bob', method: 'POST', body}), {DB: adapter})).status, 201, 'budgets are per owner');
    assert.equal(sql.prepare('SELECT COUNT(*) AS n FROM comfort_feedback').get().n, 31);
  } finally { Date.now = realNow; sql.close(); }
});

test('push subscriptions: create, ownership, device cap, bad endpoints and delete over HTTP', async () => {
  const {sql, adapter} = database(), env = {DB: adapter};
  try {
    const keys = await pushKeys(), sub = n => ({endpoint: `https://fcm.googleapis.com/fcm/send/device-${n}`, keys});
    const created = await worker.fetch(request('/api/subscription', {owner: 'alice', method: 'POST', body: sub(1)}), env);
    assert.equal(created.status, 200);assert.deepEqual(await created.json(), {enabled: true});
    assert.equal((await worker.fetch(request('/api/subscription', {owner: 'alice', method: 'POST', body: sub(1)}), env)).status, 200, 're-subscribing is idempotent');
    assert.equal((await worker.fetch(request('/api/subscription', {owner: 'bob', method: 'POST', body: sub(1)}), env)).status, 409);
    for (let n = 2; n <= 5; n++) assert.equal((await worker.fetch(request('/api/subscription', {owner: 'alice', method: 'POST', body: sub(n)}), env)).status, 200);
    assert.equal((await worker.fetch(request('/api/subscription', {owner: 'alice', method: 'POST', body: sub(6)}), env)).status, 409, 'five devices at most');
    for (const endpoint of ['not a url', 'https://attacker.test/push', 42]) {
      const rejected = await worker.fetch(request('/api/subscription', {owner: 'alice', method: 'POST', body: {endpoint, keys}}), env);
      assert.equal(rejected.status, 400, String(endpoint));assert.match((await rejected.json()).error, /push endpoint rejected|subscription missing/);
    }
    assert.equal((await worker.fetch(request('/api/subscription', {owner: 'bob', method: 'POST', body: sub(9)}), env)).status, 200);
    const removed = await worker.fetch(request('/api/subscription', {owner: 'alice', method: 'DELETE', body: {}}), env);
    assert.deepEqual(await removed.json(), {enabled: false});
    assert.deepEqual(sql.prepare('SELECT owner FROM subscriptions').all().map(r => r.owner), ['bob'], 'delete removes only the caller\'s devices');
  } finally { sql.close(); }
});

test('delivery to an expired push endpoint (410) prunes the subscription and holds the event in-app', async () => {
  const {sql, adapter} = database(), original = globalThis.fetch, keys = await pushKeys(), env = {DB: adapter, ...await vapid()};
  const date = new Intl.DateTimeFormat('en-CA', {timeZone: 'America/Los_Angeles'}).format(new Date(Date.now() + 2 * 86400000));
  sql.prepare('INSERT INTO trips(id,owner,region,point,species,date,start_hour,end_hour,wind_limit,gust_limit,sea_limit,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)').run('trip-1', 'alice', 'morro-bay', 'north', 'reef', date, 7, 13, 8, 12, 3, new Date().toISOString());
  sql.prepare('INSERT INTO subscriptions(id,owner,endpoint,p256dh,auth,created_at) VALUES(?,?,?,?,?,?)').run('s1', 'alice', 'https://fcm.googleapis.com/fcm/send/gone', keys.p256dh, keys.auth, new Date().toISOString());
  const pushes = [];
  globalThis.fetch = async (url, init = {}) => {
    if (String(url).startsWith('https://fcm.googleapis.com/')) { pushes.push({url, init}); return new Response(null, {status: 410}); }
    return new Response('{}', {status: 503});  // feeds unavailable: the assessment is "unverified"
  };
  try {
    const result = await checkTrips(env);
    assert.equal(result.changes, 1);assert.equal(pushes.length, 1);
    assert.equal(pushes[0].init.redirect, 'manual');assert.match(pushes[0].init.headers.authorization || pushes[0].init.headers.Authorization, /^vapid /);
    assert.equal(sql.prepare('SELECT COUNT(*) AS n FROM subscriptions').get().n, 0, 'the 410 endpoint was pruned');
    assert.equal(sql.prepare('SELECT status FROM delivery_receipts').get().status, 'expired');
    assert.equal(sql.prepare('SELECT status FROM alert_events').get().status, 'held');
  } finally { globalThis.fetch = original; sql.close(); }
});

test('page shells are served from their fingerprinted file with no-store; other assets pass through', async () => {
  const requested = [];
  const ASSETS = {fetch: async req => { const path = new URL(req.url).pathname; requested.push([path, new URL(req.url).search]);
    return new Response('page', {headers: {'Content-Type': path.includes('.') ? 'text/javascript' : 'text/html', 'Cache-Control': 'public, max-age=31536000'}}); }};
  const shell = await worker.fetch(new Request(origin + '/?region=morro-bay'), {ASSETS});
  assert.equal(shell.status, 200);assert.equal(shell.headers.get('Cache-Control'), 'no-store');
  assert.deepEqual(requested[0], ['/index.0123456789', ''], 'hashed file, without .html or the visitor query');
  const asset = await worker.fetch(new Request(origin + '/app.0123456789.js'), {ASSETS});
  assert.equal(asset.headers.get('Cache-Control'), 'public, max-age=31536000', 'hashed assets keep their long cache');
  assert.equal((await worker.fetch(new Request(origin + '/'), {})).status, 404, 'no asset binding, no page');
});

test('only typed client errors answer 400 with their message; dependency errors stay generic', async () => {
  const failing = {prepare() { throw Error('D1_ERROR: invalid column owner_x: SQLITE_ERROR'); }, async batch() { throw Error('invalid'); }};
  const response = await worker.fetch(request('/api/trips', {owner: 'alice'}), {DB: failing});
  assert.equal(response.status, 503, 'a storage error mentioning "invalid" is not a client error');
  assert.doesNotMatch((await response.json()).error, /D1|SQLITE|column/);
  const {sql, adapter} = database();
  try {
    const bad = await worker.fetch(request('/api/trips', {owner: 'alice', method: 'POST', body: '{"region":'}), {DB: adapter});
    assert.equal(bad.status, 400);assert.deepEqual(await bad.json(), {error: 'invalid JSON body'});
    const proto = await worker.fetch(request('/api/trips', {owner: 'alice', method: 'POST', body: {region: '__proto__', point: 'x', species: 'y'}}), {DB: adapter});
    assert.equal(proto.status, 400);assert.deepEqual(await proto.json(), {error: 'unknown area or species'});
    assert.equal((await worker.fetch(request('/api/intelligence?region=constructor'), {})).status, 404);
    assert.ok(new ClientError('x') instanceof Error);
  } finally { sql.close(); }
});

test('alert acknowledgement binds only a well-formed event id and only the caller\'s event', async () => {
  const {sql, adapter} = database(), env = {DB: adapter}, id = 'a'.repeat(64);
  sql.prepare('INSERT INTO alert_events(id,trip_id,owner,kind,message,created_at) VALUES(?,?,?,?,?,?)').run(id, 't', 'alice', 'final', 'm', new Date().toISOString());
  sql.prepare('INSERT INTO trips(id,owner,region,point,species,date,start_hour,end_hour,wind_limit,gust_limit,sea_limit,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)').run('t', 'alice', 'morro-bay', 'north', 'reef', '2026-10-01', 7, 13, 8, 12, 3, new Date().toISOString());
  try {
    for (const bad of [{id: {}}, {id: ['x']}, {id: 7}, {}, {id: 'short'}, {id: 'A'.repeat(64)}]) {
      const response = await worker.fetch(request('/api/events/ack', {owner: 'alice', method: 'POST', body: bad}), env);
      assert.equal(response.status, 400, JSON.stringify(bad));assert.deepEqual(await response.json(), {error: 'event id required'});
    }
    assert.equal((await worker.fetch(request('/api/events/ack', {owner: 'bob', method: 'POST', body: {id}}), env)).status, 404);
    assert.deepEqual(await (await worker.fetch(request('/api/events/ack', {owner: 'alice', method: 'POST', body: {id}}), env)).json(), {read: true});
    assert.equal(sql.prepare('SELECT status FROM alert_events').get().status, 'read');
    assert.ok(sql.prepare('SELECT final_delivered_at FROM trips').get().final_delivered_at, 'a final alert closes the trip');
  } finally { sql.close(); }
});

test('public health is minimal: no binding or secret presence is disclosed', async () => {
  const response = await worker.fetch(request('/api/health'), {DB: {}, FEEDS: {}, VAPID_PUBLIC_KEY: 'k', VAPID_PRIVATE_KEY: 'k', ANTHROPIC_API_KEY: 'k'});
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), {service: 'SkipperCast', version: '0.3.0', build: 'build-test'});
  assert.equal(response.headers.get('Cache-Control'), 'no-store');
});
