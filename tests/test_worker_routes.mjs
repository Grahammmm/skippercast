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
globalThis.SHELLS = {'/': '/index.0123456789.html', '/index.html': '/index.0123456789.html', '/landing.html': '/landing.0123456789.html', '/app.html': '/app.0123456789.html', '/coast.html': '/coast.0123456789.html'};
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
      // CF-01: the charter fleet is dark (404) without FLEET_ENABLED, signed in or not.
      ['GET', '/api/fleet/jobs/ping', null, false, 404], ['POST', '/api/fleet/jobs/registry', null, false, 404],
      ['GET', '/api/fleet/map/filters', 'alice', false, 404], ['GET', '/api/admin/fleet/reviews', 'alice', false, 404],
    ];
    for (const [method, path, owner, origin, status] of cases) {
      const response = await call(path, {method, owner, origin: origin ? ORIGIN : undefined, env});
      assert.equal(response.status, status, `${method} ${path}${owner ? ' signed in' : ''}`);
      for (const [name, value] of Object.entries(SECURITY_HEADERS)) assert.equal(response.headers.get(name), value, `${method} ${path}: ${name}`);
    }
  } finally { sql.close(); }
});

// FE-01 (docs/plans/front-end/design.md § 14): the v2 shells behind UI_V2 and the ?ui= switch.
// ASSETS answers 299 with the fetched path, so the chosen shell is visible in the body.
test('UI_V2 off: / is the v1 shell as before and /map is 404; ?ui=v2 previews; UI_V2=true serves v2 and ?ui=v1 forces v1', async () => {
  const shell = async (path, env) => { const r = await call(path, {env}); return r.status === 299 ? [r.status, await r.text(), r.headers.get('Cache-Control')] : [r.status]; };
  const v1 = [299, '/index.0123456789', 'no-store'], landing = [299, '/landing.0123456789', 'no-store'], app = [299, '/app.0123456789', 'no-store'];
  // 1. Flag unset, no switch: byte-identical v1 (the same fingerprinted file, no-store, query stripped); the v2 paths are dark.
  for (const env of [{}, {UI_V2: ''}, {UI_V2: 'false'}, {UI_V2: 'yes'}, {UI_V2: '1'}]) {
    assert.deepEqual(await shell('/', env), v1, JSON.stringify(env));
    assert.deepEqual(await shell('/?region=morro-bay&view=tomorrow', env), v1);
    assert.deepEqual(await shell('/index.html', env), v1);
    for (const path of ['/map', '/map?region=morro-bay', '/landing.html', '/app.html']) assert.deepEqual(await shell(path, env), [404], `${path} ${JSON.stringify(env)}`);
  }
  // 2. ?ui=v2 on a request: the landing without an area parameter, the app with one (shared v1 links keep working), /map the app.
  assert.deepEqual(await shell('/?ui=v2', {}), landing);
  for (const query of ['region=morro-bay', 'coast=central', 'view=tomorrow', 'spot=x', 'target=lingcod', 'focus=y']) assert.deepEqual(await shell(`/?${query}&ui=v2`, {}), app, query);
  assert.deepEqual(await shell('/map?ui=v2', {}), app);
  assert.deepEqual(await shell('/landing.html?ui=v2', {}), landing); assert.deepEqual(await shell('/app.html?ui=v2', {}), app);
  // 3. UI_V2=true: v2 by default (any case, trimmed); ?ui=v1 forces the v1 shell and darkens /map.
  for (const env of [{UI_V2: 'true'}, {UI_V2: ' TRUE '}]) {
    assert.deepEqual(await shell('/', env), landing); assert.deepEqual(await shell('/?region=morro-bay', env), app); assert.deepEqual(await shell('/map', env), app);
    assert.deepEqual(await shell('/?ui=v1', env), v1); assert.deepEqual(await shell('/?region=morro-bay&ui=v1', env), v1);
    assert.deepEqual(await shell('/map?ui=v1', env), [404]); assert.deepEqual(await shell('/index.html', env), v1);
  }
  // An unknown switch value is no switch; other pages and assets are untouched by the flag.
  assert.deepEqual(await shell('/?ui=v3', {UI_V2: 'true'}), landing); assert.deepEqual(await shell('/?ui=v3', {}), v1);
  assert.deepEqual(await shell('/sources.html?ui=v2', {}), [299, '/sources.html', null]);
  const dark = await call('/map', {});
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) assert.equal(dark.headers.get(name), value, `404 /map: ${name}`);
});

// FE-78 (design § 3A.3): Fish and coast keys open the app at / and, with v2 on, /coast is the app at presentation=3d.
test('FE-78: coast and Fish keys open the v2 app; /coast is the app at presentation=3d; with v2 off every path is unchanged', async () => {
  const shell = async (path, env) => { const r = await call(path, {env}); return r.status === 299 ? [r.status, await r.text(), r.headers.get('Cache-Control')] : [r.status, r.headers.get('Location'), r.headers.get('Cache-Control')]; };
  const v1 = [299, '/index.0123456789', 'no-store'], app = [299, '/app.0123456789', 'no-store'], coastPage = [299, '/coast.0123456789', 'no-store'];
  const keys = ['place=morro', 'mode=shore', 'species=lingcod', 'presentation=3d', 'habitat=reef:1', 'current=wcofs'];
  // 1. v2 off: /coast still serves coast.html, / and every Fish or coast link is the v1 shell byte for byte.
  for (const env of [{}, {UI_V2: 'false'}, {UI_V2: 'true', ui: 'v1'}]) {
    const off = env.ui ? '&ui=v1' : '', e = {UI_V2: env.UI_V2};
    assert.deepEqual(await shell(`/coast?${off.slice(1)}`, e), coastPage, JSON.stringify(env));
    assert.deepEqual(await shell(`/coast?place=morro&mode=shore${off}`, e), coastPage);
    for (const query of ['', ...keys, 'place=morro&mode=shore']) assert.deepEqual(await shell(`/?${query}${off}`, e), v1, `${query} ${JSON.stringify(env)}`);
  }
  assert.equal(await (await call('/', {})).text(), await (await call('/?place=morro&mode=shore', {})).text(), '/ is byte-identical with v2 off');
  // 2. v2 on (the flag or ?ui=v2): each key opens the app at /; /coast moves to the app at presentation=3d, query kept.
  for (const query of keys) {
    assert.deepEqual(await shell(`/?${query}`, {UI_V2: 'true'}), app, query);
    assert.deepEqual(await shell(`/?${query}&ui=v2`, {}), app, `${query} ?ui=v2`);
  }
  assert.deepEqual(await shell('/?place=morro&mode=shore', {UI_V2: 'true'}), app);
  assert.deepEqual(await shell('/coast', {UI_V2: 'true'}), [302, '/map?presentation=3d', 'no-store']);
  assert.deepEqual(await shell('/coast?place=morro&mode=shore', {UI_V2: 'true'}), [302, '/map?place=morro&mode=shore&presentation=3d', 'no-store']);
  assert.deepEqual(await shell('/coast?ui=v2', {}), [302, '/map?ui=v2&presentation=3d', 'no-store']);
  assert.deepEqual(await shell('/coast?presentation=2d', {UI_V2: 'true'}), [302, '/map?presentation=2d', 'no-store'], 'a link that names a presentation keeps it');
  const moved = await call('/coast', {env: {UI_V2: 'true'}});
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) assert.equal(moved.headers.get(name), value, `302 /coast: ${name}`);
  // The redirect target is the app.
  assert.deepEqual(await shell('/map?presentation=3d', {UI_V2: 'true'}), app); assert.deepEqual(await shell('/map?ui=v2&presentation=3d', {}), app);
  // 3. The readable pages answer the same with v2 on and off (offline: the upstream report is unavailable).
  const real = globalThis.fetch;
  globalThis.fetch = async () => { throw Error('offline'); };
  try {
    for (const path of ['/report', '/feed.xml', '/methodology', '/about']) {
      const read = async (p, env) => { const r = await call(p, {env}); return [r.status, r.headers.get('Content-Type'), r.headers.get('Location'), await r.text()]; };
      const before = await read(path, {});
      assert.notEqual(before[0], 302, path);
      assert.deepEqual(await read(path, {UI_V2: 'true'}), before, `${path} UI_V2=true`);
      assert.deepEqual(await read(`${path}?ui=v2`, {}), await read(`${path}?ui=v1`, {}), `${path} ?ui=`);
    }
  } finally { globalThis.fetch = real; }
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
