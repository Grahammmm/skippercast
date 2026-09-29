// The Worker's routing table and middleware (server/app.ts): which handler
// answers each method and path, request ids, the error boundary, and the typed
// Env interface against wrangler.jsonc.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, readdirSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import {stripJsonComments} from '../scripts/wrangler_config.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
import {withSessions} from './fixtures/test-sessions.mjs';
const {default: deployed} = await import('../server/index.ts');
const {SECURITY_HEADERS} = await import('../server/security-headers.ts');
const worker = withSessions(deployed);

function database() {
  const sql = new DatabaseSync(':memory:'), journal = read('../drizzle/meta/_journal.json');
  for (const {tag} of [...journal.entries].sort((a, b) => a.idx - b.idx)) sql.exec(readFileSync(new URL(`../drizzle/${tag}.sql`, import.meta.url), 'utf8'));
  const adapter = {prepare(query) { let args = []; const statement = sql.prepare(query); return {bind(...a) { args = a; return this; }, async first() { return statement.get(...args) || null; }, async all() { return {results: statement.all(...args)}; }, async run() { const info = statement.run(...args); return {meta: {changes: Number(info.changes)}}; }}; },
    async batch(queries) { sql.exec('BEGIN'); try { const out = []; for (const q of queries) out.push(await q.run()); sql.exec('COMMIT'); return out; } catch (e) { sql.exec('ROLLBACK'); throw e; } }};
  return {sql, adapter};
}
// Static assets answer 299 with the path they were asked for, so a route that
// falls through to the site is visible in the status.
const ASSETS = {fetch: async request => new Response(new URL(request.url).pathname, {status: 299})};
const ORIGIN = 'https://skippercast.com';
const call = (path, {method = 'GET', owner, origin, env = {}} = {}) => {
  const headers = {};
  if (owner) headers['x-test-owner'] = owner;
  if (origin) headers.Origin = origin;
  const body = ['GET', 'HEAD'].includes(method) ? undefined : '{}';
  return worker.fetch(new Request(ORIGIN + path, {method, headers, body}), {ASSETS, ...env});
};

test('every method and path reaches the same handler as before the Hono router', async () => {
  const {sql, adapter} = database(), env = {DB: adapter};
  try {
    const cases = [
      // [method, path, owner, origin, expected status]
      ['GET', '/', null, false, 299], ['GET', '/feeds', null, false, 299], ['GET', '/api', null, false, 299],
      ['POST', '/feeds/data/x.json', null, false, 299],           // only GET reads feeds; anything else is the site
      ['GET', '/feeds/', null, false, 404], ['GET', '/feeds/nope/x.json', null, false, 404],
      ['POST', '/api/health', null, false, 200], ['DELETE', '/api/health', null, false, 200],
      ['GET', '/api/habitat?region=nowhere', null, false, 404], ['GET', '/api/forecast?region=nowhere', null, false, 404],
      ['GET', '/api/intelligence', null, false, 404],
      ['GET', '/api/jobs/check', null, false, 401],               // GET is not the job route: a private path
      ['POST', '/api/jobs/check', null, false, 401],              // no scheduler token
      ['POST', '/api/om/v1/forecast', null, false, 401],          // only GET reads the model API
      ['GET', '/api/om/v1/forecastx', null, false, 401], ['GET', '/api/om/data/GFS/static/meta.json', null, false, 401],
      ['GET', '/api/om/v1/xforecast', null, false, 401], ['GET', '/api/om/v1/forecast/x', null, false, 401],
      ['GET', '/api/om/data/gfs-global/static/meta.json', null, false, 401], ['GET', '/api/om/data/a/b/static/meta.json', null, false, 401],
      ['GET', '/api/om/data/gfs_global/static/metaxjson', null, false, 401], ['GET', '/api/xforecast?region=morro-bay', null, false, 401],
      ['GET', '/api/forecast/x?region=morro-bay', null, false, 401], ['GET', '/api/om/data/nope/static/meta.json', null, false, 400],
      ['GET', '/api/auth', null, false, 401],                     // '/api/auth' is not '/api/auth/'
      ['GET', '/api/auth/passkeys', null, false, 401], ['GET', '/api/auth/nope', null, false, 404],
      ['GET', '/api/session', null, false, 200], ['POST', '/api/session', null, false, 401],
      ['GET', '/api/nope', null, false, 401], ['GET', '/api/', null, false, 401],
      ['GET', '/api/%74rips', 'alice', false, 404],               // routes see the raw path, as URL.pathname gives it
      ['GET', '/api/nope', 'alice', false, 404], ['GET', '/api/trips/', 'alice', false, 404],
      ['POST', '/api/nope', 'alice', false, 400],                 // mutations need an allowed Origin first
      ['POST', '/api/nope', 'alice', true, 404],
      ['PUT', '/api/trips', 'alice', true, 404], ['GET', '/api/trips', 'alice', false, 200],
      ['GET', '/api/comfort', 'alice', false, 200], ['GET', '/api/privacy', 'alice', false, 200],
    ];
    for (const [method, path, owner, origin, status] of cases) {
      const response = await call(path, {method, owner, origin: origin ? ORIGIN : undefined, env});
      assert.equal(response.status, status, `${method} ${path}${owner ? ' signed in' : ''}`);
      for (const [name, value] of Object.entries(SECURITY_HEADERS)) assert.equal(response.headers.get(name), value, `${method} ${path}: ${name}`);
    }
  } finally { sql.close(); }
});

test('without an identity provider /api/auth/ is unavailable and private routes fail closed', async () => {
  const env = {IDENTITY_PROVIDER: 'none'};
  const auth = await deployed.fetch(new Request(ORIGIN + '/api/auth/login/options', {method: 'POST', headers: {Origin: ORIGIN}, body: '{}'}), env);
  assert.equal(auth.status, 404);
  const {request_id, ...rest} = await auth.json();
  assert.deepEqual(rest, {error: 'Accounts are not available on this site', signIn: null});
  assert.equal(request_id, auth.headers.get('X-Request-Id'));
  const trips = await deployed.fetch(new Request(ORIGIN + '/api/trips'), env);
  assert.equal(trips.status, 401);
});

test('HEAD is answered as GET without a body (Hono), including for the site', async () => {
  const health = await deployed.fetch(new Request(ORIGIN + '/api/health', {method: 'HEAD'}), {});
  assert.equal(health.status, 200);assert.equal(await health.text(), '');
  const page = await deployed.fetch(new Request(ORIGIN + '/', {method: 'HEAD'}), {ASSETS});
  assert.equal(page.status, 299);assert.equal(page.headers.get('Cache-Control'), 'no-store');
});

test('every response carries a request id; JSON errors repeat it; a well-formed incoming id is kept', async () => {
  const ok = await deployed.fetch(new Request(ORIGIN + '/api/health'), {});
  assert.match(ok.headers.get('X-Request-Id'), /^[0-9a-f-]{36}$/);
  assert.equal((await ok.json()).request_id, undefined, 'successful bodies are unchanged');
  const page = await deployed.fetch(new Request(ORIGIN + '/'), {ASSETS});
  assert.match(page.headers.get('X-Request-Id'), /^[0-9a-f-]{36}$/);
  const kept = await deployed.fetch(new Request(ORIGIN + '/api/nope', {headers: {'X-Request-Id': 'edge-1234abcd'}}), {});
  assert.equal(kept.headers.get('X-Request-Id'), 'edge-1234abcd');
  assert.equal((await kept.json()).request_id, 'edge-1234abcd');
  for (const bad of ['short', 'x'.repeat(65), 'has space 1234', 'aébcdefgh']) {
    const replaced = await deployed.fetch(new Request(ORIGIN + '/api/health', {headers: {'X-Request-Id': encodeURIComponent(bad) === bad ? bad : 'has%20space'}}), {});
    assert.notEqual(replaced.headers.get('X-Request-Id'), bad);
    assert.match(replaced.headers.get('X-Request-Id'), /^[0-9a-f-]{36}$/);
  }
  // A dependency failure: the generic 503 message plus the id to quote.
  const broken = {prepare() { throw Error('D1 down'); }};
  const failed = await worker.fetch(new Request(ORIGIN + '/api/trips', {headers: {'x-test-owner': 'alice'}}), {DB: broken});
  assert.equal(failed.status, 503);
  const body = await failed.json();
  assert.equal(body.error, 'This service is temporarily unavailable. Your existing records are preserved.');
  assert.equal(body.request_id, failed.headers.get('X-Request-Id'));
  // Rate limits outside the D1 budget (Rate Limiting binding) are JSON errors too.
  const limited = await deployed.fetch(new Request(ORIGIN + '/feeds/data/x.json'), {FEED_LIMITER: {limit: async () => ({success: false})}});
  assert.equal(limited.status, 429);assert.equal(limited.headers.get('Retry-After'), '60');
  assert.equal((await limited.json()).request_id, limited.headers.get('X-Request-Id'));
});

test('errors outside /api/ are not mapped to JSON: the Worker fails as it did before', async () => {
  const failing = {fetch: async () => { throw Error('assets down'); }};
  await assert.rejects(deployed.fetch(new Request(ORIGIN + '/'), {ASSETS: failing}), /assets down/);
});

test('the typed Env lists every binding and variable in wrangler.jsonc', () => {
  const config = JSON.parse(stripJsonComments(readFileSync(new URL('../wrangler.jsonc', import.meta.url), 'utf8')));
  const source = readFileSync(new URL('../server/env.ts', import.meta.url), 'utf8');
  const declared = new Set([...source.matchAll(/^\s+([A-Z][A-Z0-9_]*)\?:/gm)].map(m => m[1]));
  const names = [config.assets.binding, ...config.d1_databases.map(d => d.binding), ...config.r2_buckets.map(b => b.binding),
    ...config.ratelimits.map(r => r.name), ...Object.keys(config.vars)];
  for (const name of names) assert.ok(declared.has(name), `server/env.ts is missing ${name}`);
  // Every env.X the Worker reads is declared.
  const used = new Set();
  const walk = dir => { for (const entry of readdirSync(new URL(dir, import.meta.url), {withFileTypes: true})) {
    if (entry.isDirectory()) walk(dir + entry.name + '/');
    else if (entry.name.endsWith('.ts')) for (const m of readFileSync(new URL(dir + entry.name, import.meta.url), 'utf8').matchAll(/\benv\??\.([A-Z][A-Z0-9_]+)/g)) used.add(m[1]);
  } };
  walk('../server/');
  for (const name of used) assert.ok(declared.has(name), `server/env.ts is missing ${name}`);
});
