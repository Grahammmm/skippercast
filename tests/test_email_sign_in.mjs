// Email sign-in links end to end through worker.fetch, with the mail provider
// (Resend) answered by a stub: link issue and single use, account creation and
// return, adding an address to a passkey account, limits, failures and deletion.
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
const {default: worker} = await import('../server/index.ts');
const {COOKIE} = await import('../server/auth.ts');
const {normalizeEmail, linkMessage, LINKS_PER_HOUR, LINK_SECONDS} = await import('../server/email-auth.ts');

function database() {
  const sql = new DatabaseSync(':memory:'), journal = read('../drizzle/meta/_journal.json');
  for (const {tag} of [...journal.entries].sort((a, b) => a.idx - b.idx)) sql.exec(readFileSync(new URL(`../drizzle/${tag}.sql`, import.meta.url), 'utf8'));
  const adapter = {prepare(query) { let args = []; const statement = sql.prepare(query); return {bind(...a) { args = a; return this; }, async first() { return statement.get(...args) || null; }, async all() { return {results: statement.all(...args)}; }, async run() { const info = statement.run(...args); return {meta: {changes: Number(info.changes)}}; }}; },
    async batch(queries) { sql.exec('BEGIN'); try { const out = []; for (const q of queries) out.push(await q.run()); sql.exec('COMMIT'); return out; } catch (e) { sql.exec('ROLLBACK'); throw e; } }};
  return {sql, adapter};
}

// The stub mail provider: records what the Worker sends to Resend.
const outbox = [];
let providerStatus = 200;
const realFetch = globalThis.fetch;
globalThis.fetch = async (input, init) => {
  const url = String(input instanceof Request ? input.url : input);
  if (url !== 'https://api.resend.com/emails') return realFetch(input, init);
  outbox.push({headers: new Headers(init.headers), body: JSON.parse(init.body)});
  return new Response(JSON.stringify(providerStatus === 200 ? {id: 'msg_' + outbox.length} : {message: 'provider down'}), {status: providerStatus});
};
const MAIL = {RESEND_API_KEY: 're_test_key', MAIL_FROM: 'SkipperCast <sign-in@skippercast.com>'};
const tokenIn = mail => mail.body.text.match(/#email-sign-in=([\w-]{43})/)[1];

const ORIGIN = 'https://skippercast.com';
let ipCounter = 0;
function client(adapter, {host = ORIGIN, env: extra = MAIL} = {}) {
  const ip = '198.51.100.' + (++ipCounter);
  const env = {DB: adapter, IDENTITY_PROVIDER: 'skippercast', ...extra};
  const jar = {cookie: null};
  async function call(path, {method = 'GET', body, origin = host} = {}) {
    const h = {'Content-Type': 'application/json', 'CF-Connecting-IP': ip, 'User-Agent': 'Mozilla/5.0 (test) Safari'};
    if (method !== 'GET') h.Origin = origin;
    if (jar.cookie) h.Cookie = `${COOKIE}=${jar.cookie}`;
    const response = await worker.fetch(new Request(host + path, {method, headers: h, body: body === undefined ? undefined : JSON.stringify(body)}), env);
    const set = response.headers.get('Set-Cookie');
    if (set) { const m = set.match(new RegExp(`^${COOKIE}=([^;]*)`)); jar.cookie = m[1] || null; }
    return {status: response.status, data: await response.json().catch(() => null), setCookie: set};
  }
  return {call, jar};
}
async function emailSignIn(c, email) {
  const before = outbox.length;
  const sent = await c.call('/api/auth/email/start', {method: 'POST', body: {email}});
  assert.equal(sent.status, 200, JSON.stringify(sent.data));
  assert.equal(outbox.length, before + 1);
  return c.call('/api/auth/email/verify', {method: 'POST', body: {token: tokenIn(outbox.at(-1))}});
}
const count = (sql, table) => sql.prepare(`SELECT COUNT(*) AS n FROM ${table}`).get().n;
const trip = () => ({region: 'morro-bay', point: 'north', species: 'reef', date: new Intl.DateTimeFormat('en-CA', {timeZone: 'America/Los_Angeles'}).format(new Date(Date.now() + 86400000)), start_hour: 7, end_hour: 13, wind_limit: 8, gust_limit: 12, sea_limit: 3});

test('addresses are trimmed and lower-cased; anything unlike an address is refused', () => {
  assert.equal(normalizeEmail('  Graham@Example.COM '), 'graham@example.com');
  for (const bad of ['', 'graham', 'graham@', '@example.com', 'a b@example.com', 'a@b', 'x@exa mple.com', 'a<b>@example.com', 'a\n@example.com', 'a'.repeat(250) + '@example.com', 42, null])
    assert.throws(() => normalizeEmail(bad), /email address/, String(bad));
  const message = linkMessage('a@example.com', 'https://skippercast.com/#email-sign-in=abc', false);
  assert.match(message.text, /within 15 minutes/);
  assert.match(message.html, /href="https:\/\/skippercast\.com\/#email-sign-in=abc"/);
  assert.match(linkMessage('a@example.com', 'https://x/#y', true).subject, /Confirm your email/);
});

test('without a mail provider email sign-in is off and says so', async () => {
  const {sql, adapter} = database(), c = client(adapter, {env: {}});
  assert.equal((await c.call('/api/session')).data.emailSignIn, false);
  const start = await c.call('/api/auth/email/start', {method: 'POST', body: {email: 'a@example.com'}});
  assert.equal(start.status, 503);
  assert.match(start.data.error, /not available/);
  assert.equal(count(sql, 'email_links'), 0);
  // An unusable sender is the same as none.
  assert.equal((await client(adapter, {env: {...MAIL, MAIL_FROM: 'not an address'}}).call('/api/session')).data.emailSignIn, false);
  // The log transport is for wrangler dev on localhost only, never a public host.
  assert.equal((await client(adapter, {env: {MAIL_TRANSPORT: 'log'}}).call('/api/session')).data.emailSignIn, false);
  sql.close();
});

test('a link creates the account, signs in once and cannot be used again', async () => {
  const {sql, adapter} = database(), c = client(adapter);
  assert.equal((await c.call('/api/session')).data.emailSignIn, true);
  const sent = await c.call('/api/auth/email/start', {method: 'POST', body: {email: ' Skipper@Example.com '}});
  assert.deepEqual(sent.data, {sent: true, expires_in: LINK_SECONDS});
  const mail = outbox.at(-1);
  assert.equal(mail.headers.get('Authorization'), 'Bearer re_test_key');
  assert.deepEqual([mail.body.from, mail.body.to], ['SkipperCast <sign-in@skippercast.com>', ['skipper@example.com']]);
  assert.match(mail.body.text, /^Open this link within 15 minutes to sign in to SkipperCast:\n\nhttps:\/\/skippercast\.com\/#email-sign-in=[\w-]{43}\n/);
  const token = tokenIn(mail);
  // Only the hash is stored, never the token; no account exists until the link is opened.
  const row = sql.prepare('SELECT * FROM email_links').get();
  assert.equal(row.id, createHash('sha256').update(token).digest('hex'));
  assert.ok(!JSON.stringify(row).includes(token));
  assert.equal(row.expires_at - row.created_at, LINK_SECONDS);
  assert.equal(count(sql, 'users'), 0);
  assert.equal((await c.call('/api/trips')).status, 401);

  const opened = await c.call('/api/auth/email/verify', {method: 'POST', body: {token}});
  assert.equal(opened.status, 201, JSON.stringify(opened.data));
  assert.equal(opened.data.created, true);
  assert.equal(opened.data.email, 'skipper@example.com');
  assert.match(opened.setCookie, /HttpOnly; SameSite=Lax/);
  const userId = opened.data.user.id;
  assert.deepEqual({...sql.prepare('SELECT email,user_id FROM user_emails').get()}, {email: 'skipper@example.com', user_id: userId});
  assert.equal(count(sql, 'email_links'), 0, 'the link is used up');
  assert.equal((await c.call('/api/trips', {method: 'POST', body: trip()})).status, 201);
  assert.equal(sql.prepare('SELECT owner FROM trips').get().owner, userId);
  assert.equal((await c.call('/api/auth/email')).data.email, 'skipper@example.com');

  // The same link again, from anywhere, does nothing.
  const other = client(adapter);
  const again = await other.call('/api/auth/email/verify', {method: 'POST', body: {token}});
  assert.equal(again.status, 400);
  assert.match(again.data.error, /expired or was already used/);
  assert.equal(other.jar.cookie, null);

  // A later link to the same address returns to the same account, case-insensitively.
  const back = await emailSignIn(other, 'SKIPPER@example.com');
  assert.equal(back.status, 200);
  assert.deepEqual([back.data.created, back.data.user.id], [false, userId]);
  assert.equal(count(sql, 'users'), 1);
  sql.close();
});

test('the answer does not reveal whether an address has an account', async () => {
  const {sql, adapter} = database(), c = client(adapter);
  await emailSignIn(c, 'known@example.com');
  const known = await client(adapter).call('/api/auth/email/start', {method: 'POST', body: {email: 'known@example.com'}});
  const unknown = await client(adapter).call('/api/auth/email/start', {method: 'POST', body: {email: 'nobody@example.com'}});
  assert.deepEqual([known.status, known.data], [unknown.status, unknown.data]);
  assert.equal(outbox.at(-1).body.subject, outbox.at(-2).body.subject);
  sql.close();
});

test('bad, expired and cross-origin requests are refused', async () => {
  const {sql, adapter} = database(), c = client(adapter);
  for (const token of [undefined, '', 'short', 'x'.repeat(43) + '!', 'y'.repeat(44)])
    assert.equal((await c.call('/api/auth/email/verify', {method: 'POST', body: {token}})).status, 400);
  assert.equal((await c.call('/api/auth/email/verify', {method: 'POST', body: {token: 'z'.repeat(43)}})).status, 400);
  assert.equal((await c.call('/api/auth/email/start', {method: 'POST', body: {email: 'not-an-address'}})).status, 400);

  await c.call('/api/auth/email/start', {method: 'POST', body: {email: 'late@example.com'}});
  sql.prepare('UPDATE email_links SET expires_at=expires_at-?').run(LINK_SECONDS + 1);
  const late = await c.call('/api/auth/email/verify', {method: 'POST', body: {token: tokenIn(outbox.at(-1))}});
  assert.equal(late.status, 400);
  assert.match(late.data.error, /expired/);
  assert.equal(count(sql, 'users'), 0);

  const cross = await c.call('/api/auth/email/start', {method: 'POST', body: {email: 'a@example.com'}, origin: 'https://attacker.example'});
  assert.equal(cross.status, 400);
  assert.equal(cross.data.error, 'origin rejected');
  // A host this deployment does not list cannot send links that point at itself.
  const before = outbox.length;
  assert.equal((await client(adapter, {host: 'https://skippercast.example'}).call('/api/auth/email/start', {method: 'POST', body: {email: 'a@example.com'}, origin: ORIGIN})).status, 400);
  assert.equal(outbox.length, before);
  sql.close();
});

test('an address gets at most five links an hour, and a provider failure leaves no link', async () => {
  const {sql, adapter} = database();
  for (let i = 0; i < LINKS_PER_HOUR; i++)
    assert.equal((await client(adapter).call('/api/auth/email/start', {method: 'POST', body: {email: 'busy@example.com'}})).status, 200);
  const sent = outbox.length;
  const limited = await client(adapter).call('/api/auth/email/start', {method: 'POST', body: {email: 'busy@example.com'}});
  assert.equal(limited.status, 429);
  assert.equal(outbox.length, sent, 'no sixth email');
  // An hour later the address can be sent links again.
  sql.prepare('UPDATE email_links SET created_at=created_at-3601, expires_at=expires_at-3601').run();
  assert.equal((await client(adapter).call('/api/auth/email/start', {method: 'POST', body: {email: 'busy@example.com'}})).status, 200);

  providerStatus = 500;
  try {
    const failed = await client(adapter).call('/api/auth/email/start', {method: 'POST', body: {email: 'down@example.com'}});
    assert.equal(failed.status, 503);
    assert.match(failed.data.error, /could not be sent/);
    assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM email_links WHERE email='down@example.com'").get().n, 0);
  } finally { providerStatus = 200; }
  sql.close();
});

test('a passkey account adds an address, can then drop its last passkey, and keeps one way in', async () => {
  const {sql, adapter} = database(), c = client(adapter), auth = new SoftwareAuthenticator();
  assert.equal((await c.call('/api/auth/email')).status, 401);
  const options = await c.call('/api/auth/register/options', {method: 'POST', body: {display_name: 'Graham'}});
  const made = await c.call('/api/auth/register/verify', {method: 'POST', body: {response: await auth.create(options.data, ORIGIN), display_name: 'Graham'}});
  const userId = made.data.user.id;
  assert.deepEqual((await c.call('/api/auth/email')).data, {email: null, verified_at: null, available: true});

  assert.equal((await c.call('/api/auth/email', {method: 'POST', body: {email: 'graham@example.com'}})).status, 200);
  assert.match(outbox.at(-1).body.subject, /Confirm your email/);
  assert.equal(count(sql, 'user_emails'), 0, 'not added until the link is opened');
  const confirmed = await c.call('/api/auth/email/verify', {method: 'POST', body: {token: tokenIn(outbox.at(-1))}});
  assert.equal(confirmed.status, 200);
  assert.deepEqual([confirmed.data.user.id, confirmed.data.email, confirmed.setCookie], [userId, 'graham@example.com', null]);

  // With a confirmed address, the last passkey can go; then the address cannot.
  const passkeyId = (await c.call('/api/auth/passkeys')).data.passkeys[0].id;
  assert.equal((await c.call('/api/auth/passkeys', {method: 'DELETE', body: {id: passkeyId}})).status, 200);
  const keep = await c.call('/api/auth/email', {method: 'DELETE', body: {}});
  assert.equal(keep.status, 409);
  assert.match(keep.data.error, /only way to sign in/);

  // Signed out, the address still signs in to the same account.
  await c.call('/api/auth/logout', {method: 'POST', body: {}});
  const back = await emailSignIn(c, 'graham@example.com');
  assert.deepEqual([back.status, back.data.user], [200, {id: userId, display_name: 'Graham'}]);

  // Another account cannot take the address over.
  const b = client(adapter);
  await emailSignIn(b, 'someone@example.com');
  await b.call('/api/auth/email', {method: 'POST', body: {email: 'graham@example.com'}});
  const taken = await b.call('/api/auth/email/verify', {method: 'POST', body: {token: tokenIn(outbox.at(-1))}});
  assert.equal(taken.status, 400);
  assert.match(taken.data.error, /another SkipperCast account/);
  assert.equal(sql.prepare("SELECT user_id FROM user_emails WHERE email='graham@example.com'").get().user_id, userId);

  // Export includes the address; deletion removes it and any pending link.
  assert.equal((await c.call('/api/privacy')).data.account.email.email, 'graham@example.com');
  await c.call('/api/auth/email', {method: 'POST', body: {email: 'graham@example.com'}});
  assert.equal((await c.call('/api/privacy', {method: 'DELETE', body: {}})).status, 200);
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM user_emails WHERE user_id=?").get(userId).n, 0);
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM email_links WHERE email='graham@example.com'").get().n, 0);
  assert.equal(sql.prepare('SELECT COUNT(*) AS n FROM users WHERE id=?').get(userId).n, 0);
  sql.close();
});

test('an address can be removed while a passkey remains', async () => {
  const {sql, adapter} = database(), c = client(adapter), auth = new SoftwareAuthenticator();
  const options = await c.call('/api/auth/register/options', {method: 'POST', body: {}});
  await c.call('/api/auth/register/verify', {method: 'POST', body: {response: await auth.create(options.data, ORIGIN)}});
  await c.call('/api/auth/email', {method: 'POST', body: {email: 'temp@example.com'}});
  await c.call('/api/auth/email/verify', {method: 'POST', body: {token: tokenIn(outbox.at(-1))}});
  assert.equal((await c.call('/api/auth/email', {method: 'DELETE', body: {}})).status, 200);
  assert.equal(count(sql, 'user_emails'), 0);
  assert.equal((await c.call('/api/auth/email', {method: 'DELETE', body: {}})).status, 404);
  sql.close();
});
