// SkipperCast accounts end to end through worker.fetch: passkey registration and
// sign-in with a software authenticator (real WebAuthn bytes, real verifier),
// session cookies, passkey management and account deletion.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {DatabaseSync} from 'node:sqlite';
import {SoftwareAuthenticator} from './fixtures/software-authenticator.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.BUILD_ID = 'build-test';
const {default: worker} = await import('../server/worker.js');
const {SESSION_SECONDS, COOKIE} = await import('../server/auth.js');

function database() {
  const sql = new DatabaseSync(':memory:'), journal = read('../drizzle/meta/_journal.json');
  for (const {tag} of [...journal.entries].sort((a, b) => a.idx - b.idx)) sql.exec(readFileSync(new URL(`../drizzle/${tag}.sql`, import.meta.url), 'utf8'));
  const adapter = {prepare(query) { let args = []; const statement = sql.prepare(query); return {bind(...a) { args = a; return this; }, async first() { return statement.get(...args) || null; }, async all() { return {results: statement.all(...args)}; }, async run() { const info = statement.run(...args); return {meta: {changes: Number(info.changes)}}; }}; },
    async batch(queries) { sql.exec('BEGIN'); try { const out = []; for (const q of queries) out.push(await q.run()); sql.exec('COMMIT'); return out; } catch (e) { sql.exec('ROLLBACK'); throw e; } }};
  return {sql, adapter};
}

const ORIGIN = 'https://skippercast.com';
const now = () => Math.floor(Date.now() / 1000);
let ipCounter = 0;
function client(adapter, {host = ORIGIN, provider = 'skippercast', extra} = {}) {
  const ip = '203.0.113.' + (++ipCounter);   // a fresh auth budget per client
  const env = {DB: adapter, ...(provider === null ? {} : {IDENTITY_PROVIDER: provider}), ...(extra ? {EXTRA_ORIGINS: extra} : {})};
  const jar = {cookie: null};
  async function call(path, {method = 'GET', body, origin = host, headers = {}} = {}) {
    const h = {'Content-Type': 'application/json', 'CF-Connecting-IP': ip, 'User-Agent': 'Mozilla/5.0 (test) Safari', ...headers};
    if (method !== 'GET') h.Origin = origin;
    if (jar.cookie) h.Cookie = `${COOKIE}=${jar.cookie}`;
    const response = await worker.fetch(new Request(host + path, {method, headers: h, body: body === undefined ? undefined : JSON.stringify(body)}), env);
    const set = response.headers.get('Set-Cookie');
    if (set) { const m = set.match(new RegExp(`^${COOKIE}=([^;]*)`)); jar.cookie = m[1] || null; }
    const data = await response.json().catch(() => null);
    return {status: response.status, data, setCookie: set, headers: response.headers};
  }
  return {call, jar, env};
}
async function register(c, auth, name = 'Skipper', origin = ORIGIN) {
  const options = await c.call('/api/auth/register/options', {method: 'POST', body: {display_name: name}});
  assert.equal(options.status, 200, JSON.stringify(options.data));
  const response = await auth.create(options.data, origin);
  return {options: options.data, response, result: await c.call('/api/auth/register/verify', {method: 'POST', body: {response, display_name: name}})};
}
async function login(c, auth, opts = {}) {
  const options = await c.call('/api/auth/login/options', {method: 'POST', body: {}});
  assert.equal(options.status, 200);
  const response = await auth.get(options.data, opts.origin || ORIGIN, opts);
  return {response, result: await c.call('/api/auth/login/verify', {method: 'POST', body: {response}})};
}
const trip = () => ({region: 'morro-bay', point: 'north', species: 'reef', date: new Intl.DateTimeFormat('en-CA', {timeZone: 'America/Los_Angeles'}).format(new Date(Date.now() + 86400000)), start_hour: 7, end_hour: 13, wind_limit: 8, gust_limit: 12, sea_limit: 3});
const count = (sql, table) => sql.prepare(`SELECT COUNT(*) AS n FROM ${table}`).get().n;

test('register → session → private trip → sign out → 401 → sign in again', async () => {
  const {sql, adapter} = database(), c = client(adapter), auth = new SoftwareAuthenticator();
  assert.deepEqual((await c.call('/api/session')).data, {signedIn: false, publicKey: null, signIn: '/#account', user: null});
  assert.equal((await c.call('/api/trips')).status, 401);

  const {options, result} = await register(c, auth, 'Graham');
  assert.equal(options.rp.id, 'skippercast.com');
  assert.equal(options.authenticatorSelection.residentKey, 'required');
  assert.equal(options.authenticatorSelection.userVerification, 'required');
  assert.equal(options.attestation, 'none');
  assert.equal(result.status, 201, JSON.stringify(result.data));
  const userId = result.data.user.id;
  assert.equal(result.data.user.display_name, 'Graham');
  assert.equal(options.user.id, userId, 'the passkey user handle is the account id');

  const session = (await c.call('/api/session')).data;
  assert.deepEqual([session.signedIn, session.signIn, session.user], [true, '/#account', {id: userId, display_name: 'Graham'}]);
  const created = await c.call('/api/trips', {method: 'POST', body: trip()});
  assert.equal(created.status, 201);
  assert.equal(sql.prepare('SELECT owner FROM trips').get().owner, userId, 'owner is users.id');

  // Only sha256(token) is stored.
  const token = c.jar.cookie;
  assert.match(token, /^[\w-]{43}$/);
  const stored = sql.prepare('SELECT id,user_agent,expires_at FROM sessions').get();
  assert.equal(stored.id, createHash('sha256').update(token).digest('hex'));
  assert.ok(!JSON.stringify(sql.prepare('SELECT * FROM sessions').all()).includes(token));
  assert.equal(stored.user_agent, 'Mozilla/5.0 (test) Safari');
  assert.ok(Math.abs(stored.expires_at - (now() + SESSION_SECONDS)) < 5);

  const out = await c.call('/api/auth/logout', {method: 'POST', body: {}});
  assert.equal(out.status, 200);
  assert.match(out.setCookie, /Max-Age=0/);
  assert.equal(count(sql, 'sessions'), 0);
  assert.equal((await c.call('/api/trips')).status, 401);
  // The old token no longer works even if a client kept it.
  c.jar.cookie = token;
  assert.equal((await c.call('/api/trips')).status, 401);
  c.jar.cookie = null;

  const again = await login(c, auth);
  assert.equal(again.result.status, 200, JSON.stringify(again.result.data));
  assert.equal(again.result.data.user.id, userId);
  const trips = await c.call('/api/trips');
  assert.equal(trips.status, 200);
  assert.equal(trips.data.trips.length, 1);
  assert.ok(sql.prepare('SELECT last_used_at FROM passkeys').get().last_used_at);
  assert.equal(sql.prepare('SELECT counter FROM passkeys').get().counter, 1);
  sql.close();
});

test('signing in again from a signed-in browser replaces its session', async () => {
  const {sql, adapter} = database(), c = client(adapter), auth = new SoftwareAuthenticator();
  await register(c, auth);
  const before = c.jar.cookie;
  assert.equal((await login(c, auth)).result.status, 200);
  assert.notEqual(c.jar.cookie, before);
  assert.deepEqual(sql.prepare('SELECT id FROM sessions').all().map(r => r.id), [createHash('sha256').update(c.jar.cookie).digest('hex')]);
  sql.close();
});

test('the session cookie is __Host-, HttpOnly, Secure, SameSite=Lax, Path=/ and 30 days', async () => {
  const {sql, adapter} = database(), c = client(adapter);
  const {result} = await register(c, new SoftwareAuthenticator());
  const parts = result.setCookie.split(';').map(s => s.trim());
  assert.match(parts[0], /^__Host-sc_session=[\w-]{43}$/);
  for (const flag of ['HttpOnly', 'Secure', 'SameSite=Lax', 'Path=/', `Max-Age=${30 * 86400}`]) assert.ok(parts.includes(flag), flag);
  assert.ok(!parts.some(p => /^domain=/i.test(p)), '__Host- cookies carry no Domain');
  assert.equal(result.headers.get('Cache-Control'), 'no-store');
  sql.close();
});

test('challenges are single use and expire after five minutes', async () => {
  const {sql, adapter} = database(), c = client(adapter), auth = new SoftwareAuthenticator();
  const first = await register(c, auth);
  assert.equal(first.result.status, 201);
  // Replaying the same registration response: the challenge is gone.
  const replay = await c.call('/api/auth/register/verify', {method: 'POST', body: {response: first.response}});
  assert.equal(replay.status, 400);
  assert.equal(count(sql, 'users'), 1);

  await c.call('/api/auth/logout', {method: 'POST', body: {}});
  const signIn = await login(c, auth);
  assert.equal(signIn.result.status, 200);
  await c.call('/api/auth/logout', {method: 'POST', body: {}});
  const replayed = await c.call('/api/auth/login/verify', {method: 'POST', body: {response: signIn.response}});
  assert.equal(replayed.status, 400, 'an assertion cannot be replayed');
  assert.equal(c.jar.cookie, null);

  // A challenge older than five minutes is refused (and removed).
  const options = await c.call('/api/auth/login/options', {method: 'POST', body: {}});
  const row = sql.prepare('SELECT expires_at FROM auth_challenges WHERE challenge=?').get(options.data.challenge);
  assert.ok(Math.abs(row.expires_at - (now() + 300)) < 5);
  sql.prepare('UPDATE auth_challenges SET expires_at=? WHERE challenge=?').run(now() - 1, options.data.challenge);
  const late = await c.call('/api/auth/login/verify', {method: 'POST', body: {response: await auth.get(options.data, ORIGIN)}});
  assert.equal(late.status, 400);
  assert.match(late.data.error, /expired/);
  assert.equal(count(sql, 'auth_challenges'), 0);

  // A login challenge cannot be used to register, and vice versa.
  const loginOptions = await c.call('/api/auth/login/options', {method: 'POST', body: {}});
  const forged = await auth.create({...loginOptions.data, rp: {id: 'skippercast.com'}, user: {id: 'AAAA'}}, ORIGIN);
  assert.equal((await c.call('/api/auth/register/verify', {method: 'POST', body: {response: forged}})).status, 400);
  // An invented challenge is refused.
  const made = await auth.create({challenge: 'aW52ZW50ZWQ', rp: {id: 'skippercast.com'}, user: {id: 'AAAA'}}, ORIGIN);
  assert.equal((await c.call('/api/auth/register/verify', {method: 'POST', body: {response: made}})).status, 400);
  assert.equal(count(sql, 'users'), 1);
  sql.close();
});

test('wrong origin, wrong RP ID, unlisted host and missing user verification are rejected', async () => {
  const {sql, adapter} = database(), c = client(adapter);
  // clientDataJSON from another site.
  assert.equal((await register(c, new SoftwareAuthenticator(), 'x', 'https://evil.example')).result.status, 400);
  // Authenticator scoped to another RP ID.
  const options = await c.call('/api/auth/register/options', {method: 'POST', body: {}});
  const wrongRp = await new SoftwareAuthenticator().create(options.data, ORIGIN, {rpId: 'evil.example'});
  assert.equal((await c.call('/api/auth/register/verify', {method: 'POST', body: {response: wrongRp}})).status, 400);
  // No user verification (no Face ID / PIN).
  assert.equal((await register(c, new SoftwareAuthenticator({userVerified: false}))).result.status, 400);
  // The request itself from another Origin.
  const cross = await c.call('/api/auth/register/options', {method: 'POST', body: {}, origin: 'https://attacker.example'});
  assert.equal(cross.status, 400);
  assert.equal(cross.data.error, 'origin rejected');
  // A host this deployment does not list cannot mint passkeys for itself.
  const other = client(adapter, {host: 'https://skippercast.example'});
  const refused = await other.call('/api/auth/register/options', {method: 'POST', body: {}, origin: ORIGIN});
  assert.equal(refused.status, 400);
  assert.equal(count(sql, 'users'), 0);

  // A listed staging host uses its own RP ID; a passkey made there does not sign in on the apex.
  const staging = client(adapter, {host: 'https://skippercast.g4651.workers.dev', extra: 'https://skippercast.g4651.workers.dev'});
  const stagingAuth = new SoftwareAuthenticator();
  const made = await register(staging, stagingAuth, 's', 'https://skippercast.g4651.workers.dev');
  assert.equal(made.options.rp.id, 'skippercast.g4651.workers.dev');
  assert.equal(made.result.status, 201);
  const apex = client(adapter);
  const opts = await apex.call('/api/auth/login/options', {method: 'POST', body: {}});
  const crossRp = await stagingAuth.get(opts.data, ORIGIN, {rpId: 'skippercast.g4651.workers.dev'});
  assert.equal((await apex.call('/api/auth/login/verify', {method: 'POST', body: {response: crossRp}})).status, 400);
  sql.close();
});

test('a cloned authenticator (counter going backwards) is refused', async () => {
  const {sql, adapter} = database(), c = client(adapter), auth = new SoftwareAuthenticator();
  await register(c, auth);
  await c.call('/api/auth/logout', {method: 'POST', body: {}});
  assert.equal((await login(c, auth, {counter: 5})).result.status, 200);
  await c.call('/api/auth/logout', {method: 'POST', body: {}});
  assert.equal((await login(c, auth, {counter: 3})).result.status, 400);
  sql.close();
});

test('sessions expire after 30 days and renew when fewer than 15 days remain', async () => {
  const {sql, adapter} = database(), c = client(adapter);
  await register(c, new SoftwareAuthenticator());
  const token = c.jar.cookie;
  // 20 days left: no renewal.
  sql.prepare('UPDATE sessions SET expires_at=?').run(now() + 20 * 86400);
  const fresh = await c.call('/api/session');
  assert.equal(fresh.data.signedIn, true);
  assert.equal(fresh.setCookie, null);
  // 10 days left: renewed to 30 days, same token.
  sql.prepare('UPDATE sessions SET expires_at=?').run(now() + 10 * 86400);
  const renewed = await c.call('/api/trips');
  assert.equal(renewed.status, 200);
  assert.match(renewed.setCookie, new RegExp(`^${COOKIE}=${token}; Max-Age=${30 * 86400}; Path=/; Secure; HttpOnly; SameSite=Lax$`));
  assert.ok(Math.abs(sql.prepare('SELECT expires_at FROM sessions').get().expires_at - (now() + SESSION_SECONDS)) < 5);
  // Expired: signed out, and the row is removed.
  sql.prepare('UPDATE sessions SET expires_at=?').run(now() - 1);
  assert.equal((await c.call('/api/trips')).status, 401);
  assert.equal((await c.call('/api/session')).data.signedIn, false);
  assert.equal(count(sql, 'sessions'), 0);
  // Garbage cookies are ignored.
  c.jar.cookie = 'not-a-token';
  assert.equal((await c.call('/api/session')).data.signedIn, false);
  sql.close();
});

test('passkeys: add a second, list, remove; the last one cannot be removed', async () => {
  const {sql, adapter} = database(), c = client(adapter), phone = new SoftwareAuthenticator(), laptop = new SoftwareAuthenticator();
  const {result} = await register(c, phone, 'Graham');
  const userId = result.data.user.id;
  const list = async () => (await c.call('/api/auth/passkeys')).data.passkeys;
  const [only] = await list();
  assert.deepEqual(Object.keys(only).sort(), ['created_at', 'id', 'last_used_at', 'transports']);
  const last = await c.call('/api/auth/passkeys', {method: 'DELETE', body: {id: only.id}});
  assert.equal(last.status, 409);
  assert.match(last.data.error, /only passkey/);

  const options = await c.call('/api/auth/passkeys/options', {method: 'POST', body: {}});
  assert.equal(options.status, 200);
  assert.equal(options.data.user.id, userId);
  assert.deepEqual(options.data.excludeCredentials.map(x => x.id), [only.id], 'the same authenticator is not registered twice');
  const added = await c.call('/api/auth/passkeys', {method: 'POST', body: {response: await laptop.create(options.data, ORIGIN)}});
  assert.equal(added.status, 201, JSON.stringify(added.data));
  assert.equal((await list()).length, 2);

  // Another account cannot remove or see these passkeys.
  const stranger = client(adapter);
  await register(stranger, new SoftwareAuthenticator());
  assert.equal((await stranger.call('/api/auth/passkeys', {method: 'DELETE', body: {id: only.id}})).status, 404);
  assert.equal((await stranger.call('/api/auth/passkeys')).data.passkeys.length, 1);

  assert.equal((await c.call('/api/auth/passkeys', {method: 'DELETE', body: {id: only.id}})).status, 200);
  assert.equal((await list()).length, 1);
  // The removed passkey no longer signs in; the remaining one does.
  await c.call('/api/auth/logout', {method: 'POST', body: {}});
  assert.equal((await login(c, phone)).result.status, 400);
  assert.equal((await login(c, laptop)).result.data.user.id, userId);
  // Signed out: managing passkeys needs a session.
  await c.call('/api/auth/logout', {method: 'POST', body: {}});
  assert.equal((await c.call('/api/auth/passkeys')).status, 401);
  assert.equal((await c.call('/api/auth/passkeys/options', {method: 'POST', body: {}})).status, 401);
  sql.close();
});

test('two parallel removals cannot delete the last passkey', async () => {
  const {sql, adapter} = database(), c = client(adapter);
  await register(c, new SoftwareAuthenticator());
  const options = await c.call('/api/auth/passkeys/options', {method: 'POST', body: {}});
  assert.equal((await c.call('/api/auth/passkeys', {method: 'POST', body: {response: await new SoftwareAuthenticator().create(options.data, ORIGIN)}})).status, 201);
  const ids = sql.prepare('SELECT id FROM passkeys').all().map(r => r.id);
  const results = await Promise.all(ids.map(id => c.call('/api/auth/passkeys', {method: 'DELETE', body: {id}})));
  assert.deepEqual(results.map(r => r.status).sort(), [200, 409]);
  assert.equal(count(sql, 'passkeys'), 1);
  sql.close();
});

test('export includes the account; deleting records deletes the account, passkeys and sessions', async () => {
  const {sql, adapter} = database(), c = client(adapter), other = client(adapter);
  const {result} = await register(c, new SoftwareAuthenticator(), 'Graham');
  await register(other, new SoftwareAuthenticator(), 'Other');
  const userId = result.data.user.id;
  await c.call('/api/trips', {method: 'POST', body: trip()});
  assert.equal((await c.call('/api/comfort', {method: 'POST', body: {region: 'morro-bay', rating: 7, phase: 'fishing'}})).status, 201);
  sql.prepare('INSERT INTO subscriptions(id,owner,endpoint,p256dh,auth,created_at) VALUES(?,?,?,?,?,?)').run('s1', userId, 'https://fcm.googleapis.com/x', 'k', 'a', 'x');
  sql.prepare('INSERT INTO alert_events(id,trip_id,owner,kind,message,created_at) VALUES(?,?,?,?,?,?)').run('e1', 't', userId, 'change', 'm', new Date().toISOString());
  sql.prepare('INSERT INTO delivery_receipts(id,event_id,subscription_id,status,attempt_at) VALUES(?,?,?,?,?)').run('r1', 'e1', 's1', 'sent', 'x');
  assert.equal((await c.call('/api/auth/passkeys/options', {method: 'POST', body: {}})).status, 200);   // a pending challenge tied to the account
  const exported = (await c.call('/api/privacy')).data;
  assert.equal(exported.account.user.id, userId);
  assert.equal(exported.account.user.display_name, 'Graham');
  assert.equal(exported.account.passkeys.length, 1);
  assert.ok(!('public_key' in exported.account.passkeys[0]));
  assert.equal(exported.account.sessions.length, 1);
  assert.equal(exported.trips.length, 1);

  const deleted = await c.call('/api/privacy', {method: 'DELETE', body: {}});
  assert.equal(deleted.status, 200);
  assert.match(deleted.setCookie, /Max-Age=0/);
  for (const [table, column] of [['users', 'id'], ['passkeys', 'user_id'], ['sessions', 'user_id'], ['auth_challenges', 'user_id'], ['trips', 'owner'], ['comfort_feedback', 'owner'], ['subscriptions', 'owner'], ['alert_events', 'owner']])
    assert.equal(sql.prepare(`SELECT COUNT(*) AS n FROM ${table} WHERE ${column}=?`).get(userId).n, 0, table);
  assert.equal(count(sql, 'delivery_receipts'), 0);
  assert.equal((await c.call('/api/session')).data.signedIn, false);
  assert.equal(count(sql, 'users'), 1, 'the other account is untouched');
  assert.equal((await other.call('/api/session')).data.user.display_name, 'Other');
  sql.close();
});

test('forged identity headers and cookies never authenticate; provider none disables accounts', async () => {
  const {sql, adapter} = database(), c = client(adapter);
  const {result} = await register(c, new SoftwareAuthenticator());
  const userId = result.data.user.id;
  const forged = {'oai-authenticated-user-id': userId, 'oai-authenticated-user-email': 'a@example.test', 'x-test-owner': userId};
  const anon = client(adapter);
  assert.equal((await anon.call('/api/trips', {headers: forged})).status, 401);
  assert.equal((await anon.call('/api/session', {headers: forged})).data.signedIn, false);
  anon.jar.cookie = userId.padEnd(43, 'A');
  assert.equal((await anon.call('/api/trips')).status, 401, 'a cookie that is not a session token');

  // With IDENTITY_PROVIDER absent or none, even a valid session is ignored.
  for (const provider of [null, 'none', '', 'chatgpt-sites', 'constructor']) {
    const off = client(adapter, {provider});
    off.jar.cookie = c.jar.cookie;
    assert.equal((await off.call('/api/trips')).status, 401);
    const session = (await off.call('/api/session')).data;
    assert.equal(session.signedIn, false);
    assert.equal(session.signIn, null);
    assert.equal((await off.call('/api/auth/login/options', {method: 'POST', body: {}})).status, 404);
  }
  sql.close();
});

test('auth endpoints are rate-limited per IP', async () => {
  const {sql, adapter} = database(), c = client(adapter);
  for (let i = 0; i < 20; i++) assert.equal((await c.call('/api/auth/login/options', {method: 'POST', body: {}})).status, 200);
  const limited = await c.call('/api/auth/login/options', {method: 'POST', body: {}});
  assert.equal(limited.status, 429);
  assert.equal((await client(adapter).call('/api/auth/login/options', {method: 'POST', body: {}})).status, 200, 'another IP is unaffected');
  sql.close();
});

test('the cron prunes expired sessions and challenges', async () => {
  const {sql, adapter} = database();
  sql.prepare('INSERT INTO sessions(id,user_id,created_at,expires_at) VALUES(?,?,?,?),(?,?,?,?)').run('old', 'u', 'x', now() - 10, 'live', 'u', 'x', now() + 600);
  sql.prepare('INSERT INTO auth_challenges(id,challenge,kind,expires_at) VALUES(?,?,?,?),(?,?,?,?)').run('c1', 'a', 'login', now() - 10, 'c2', 'b', 'login', now() + 60);
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => Response.json({completed_at: new Date().toISOString()});
  try {
    const pending = [];
    await worker.scheduled({}, {DB: adapter}, {waitUntil: p => pending.push(p)});
    await Promise.all(pending);
  } finally { globalThis.fetch = originalFetch; }
  assert.deepEqual(sql.prepare('SELECT id FROM sessions').all().map(r => r.id), ['live']);
  assert.deepEqual(sql.prepare('SELECT id FROM auth_challenges').all().map(r => r.id), ['c2']);
  sql.close();
});

test('client: #account opens over the Guide, and passkey errors read plainly', async () => {
  const {viewFromHash} = await import('../dist/navigation.js');
  assert.equal(viewFromHash('#account'), 'guide');
  const {passkeyMessage, signInHref} = await import('../dist/account.js');
  // Sign-in links stay in the page (a full load of "/" would drop the region and view).
  assert.equal(signInHref('/#account'), '#account');
  for (const bad of [null, '', 'https://evil.example/#account', '//evil.example', 'javascript:alert(1)']) assert.equal(signInHref(bad), '', String(bad));
  const {hasAreaLink} = await import('../dist/home-port.js');
  assert.equal(hasAreaLink('https://skippercast.com/#account'), true, 'a direct #account link is not replaced by the port chooser');
  assert.match(passkeyMessage({name: 'NotAllowedError'}), /cancelled or timed out/);
  assert.match(passkeyMessage({name: 'InvalidStateError'}), /already has a passkey/);
  assert.match(passkeyMessage({status: 429, message: 'please try again shortly'}), /Too many attempts/);
  assert.equal(passkeyMessage({message: 'that passkey is not recognised here'}), 'That passkey is not recognised here.');
  const html = readFileSync(new URL('../dist/index.html', import.meta.url), 'utf8');
  assert.match(html, /<script src="vendor\/simplewebauthn-browser-14\.0\.0\/index\.umd\.min\.js" integrity="sha256-[^"]+" defer><\/script>/);
  assert.match(html, /id="account-entry"/);
  // Destructive actions confirm in the page; window.confirm blocks the page and automation.
  for (const file of ['../dist/account.js', '../dist/trip-alerts.js']) assert.doesNotMatch(readFileSync(new URL(file, import.meta.url), 'utf8'), /(^|[^.\w])confirm\(/, file);
  for (const file of ['../dist/trip-alerts.js', '../dist/boat-profile.js']) assert.doesNotMatch(readFileSync(new URL(file, import.meta.url), 'utf8'), /coming soon|chatgpt/i, file);
});
