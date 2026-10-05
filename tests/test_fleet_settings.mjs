// Charter fleet switches and job routes (CF-01; docs/plans/charter-fleet/design.md
// § 12, § 16): fleetSettings defaults, the per-request gate on /api/fleet/*,
// the fleet job identity (a real RS256 token against a stubbed JWKS) and the
// admin page opening with either feature. Offline, against the real migrations.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html', '/admin.html': '/admin.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
import {withSessions} from './fixtures/test-sessions.mjs';
const {default: deployed} = await import('../server/index.ts');
const {fleetSettings, FLEET_DEFAULTS} = await import('../server/fleet/settings.ts');
const {FLEET_JOB_SCOPE, fleetJobs} = await import('../server/routes/fleet.ts');
const worker = withSessions(deployed);

const ORIGIN = 'https://skippercast.com';
const ASSETS = {fetch: async request => new Response(new URL(request.url).pathname, {status: 299})};
const ON = {FLEET_ENABLED: 'true'};
const MAP = {FLEET_ENABLED: 'true', FLEET_MAP_ENABLED: 'true'};

function database() {
  const sql = new DatabaseSync(':memory:'), journal = read('../drizzle/meta/_journal.json');
  for (const {tag} of [...journal.entries].sort((a, b) => a.idx - b.idx)) sql.exec(readFileSync(new URL(`../drizzle/${tag}.sql`, import.meta.url), 'utf8'));
  const adapter = {prepare(query) { let args = []; const statement = sql.prepare(query); return {bind(...a) { args = a; return this; }, async first() { return statement.get(...args) || null; }, async all() { return {results: statement.all(...args)}; }, async run() { const info = statement.run(...args); return {meta: {changes: Number(info.changes)}}; }}; },
    async batch(queries) { sql.exec('BEGIN'); try { const out = []; for (const q of queries) out.push(await q.run()); sql.exec('COMMIT'); return out; } catch (e) { sql.exec('ROLLBACK'); throw e; } }};
  return {sql, adapter};
}
const call = (path, env, {headers = {}, method = 'GET'} = {}) => worker.fetch(new Request(ORIGIN + path, {method, headers}), {ASSETS, ...env});
const withVerifier = async (verify, fn) => { const saved = fleetJobs.verify; fleetJobs.verify = verify; try { return await fn(); } finally { fleetJobs.verify = saved; } };
const accept = async token => token === 'good' ? {jti: 'run-1'} : false;
const bearer = token => ({Authorization: `Bearer ${token}`});

test('fleetSettings: both flags default off; only "true"/"false" (any case, trimmed) change them', () => {
  assert.deepEqual(fleetSettings(), {enabled: false, mapEnabled: false});
  assert.deepEqual(fleetSettings({}), FLEET_DEFAULTS);
  assert.deepEqual(fleetSettings({FLEET_ENABLED: ' TRUE ', FLEET_MAP_ENABLED: 'true'}), {enabled: true, mapEnabled: true});
  for (const value of ['', '1', 'yes', 'on', 'tru', undefined]) assert.equal(fleetSettings({FLEET_ENABLED: value}).enabled, false, String(value));
  assert.equal(fleetSettings({FLEET_ENABLED: 'false'}).enabled, false);
  assert.ok(Object.isFrozen(FLEET_DEFAULTS));
});

test('with both flags unset every /api/fleet/* and /api/admin/fleet/* path answers 404, with or without a job identity', async () => {
  const {sql, adapter} = database();
  try {
    await withVerifier(accept, async () => {
      for (const env of [{DB: adapter}, {DB: adapter, FLEET_ENABLED: 'false', FLEET_MAP_ENABLED: 'true'}, {DB: adapter, FLEET_ENABLED: 'yes'}])
        for (const path of ['/api/fleet/jobs/ping', '/api/fleet/jobs/ping?region=CA', '/api/fleet/jobs/snapshot', '/api/fleet/map/filters', '/api/fleet/', '/api/fleet/nope', '/api/admin/fleet/reviews']) {
          const response = await call(path, env, {headers: bearer('good')});
          assert.equal(response.status, 404, `${path} ${JSON.stringify({...env, DB: undefined})}`);
          assert.equal((await response.json()).error, 'Not found');
        }
    });
  } finally { sql.close(); }
});

test('with FLEET_ENABLED the ping needs a fleet job identity, and answers {ok, region}', async () => {
  const {sql, adapter} = database(), env = {DB: adapter, ...ON};
  try {
    await withVerifier(accept, async () => {
      assert.equal((await call('/api/fleet/jobs/ping', env)).status, 401);
      assert.equal((await call('/api/fleet/jobs/ping', env, {headers: bearer('bad')})).status, 401);
      const ok = await call('/api/fleet/jobs/ping?region=CA', env, {headers: bearer('good')});
      assert.equal(ok.status, 200);
      assert.equal(ok.headers.get('Cache-Control'), 'no-store');
      assert.deepEqual(await ok.json(), {ok: true, region: 'CA'});
      assert.deepEqual(await (await call('/api/fleet/jobs/ping', env, {headers: bearer('good')})).json(), {ok: true, region: null});
      assert.equal((await call('/api/fleet/jobs/ping?region=../x', env, {headers: bearer('good')})).status, 400);
      // An unknown job path needs the identity, then falls through to the private gate like any unknown /api/ path.
      assert.equal((await call('/api/fleet/jobs/nope', env)).status, 401);
      assert.equal((await call('/api/fleet/jobs/nope', env, {headers: bearer('good')})).status, 401);
      // Map routes need FLEET_MAP_ENABLED as well; none exist yet, so on they fall through to the /api/ 404.
      assert.equal((await call('/api/fleet/map/filters', env)).status, 404);
      assert.equal((await call('/api/fleet/map/filters', {DB: adapter, FLEET_MAP_ENABLED: 'true'})).status, 404, 'the map flag alone opens nothing');
    });
    // The default verifier is the real one: an unsigned token never passes.
    assert.equal((await call('/api/fleet/jobs/ping', env, {headers: bearer('a.b.c')})).status, 401);
  } finally { sql.close(); }
});

// A real token, signed with a test key and verified by server/job-auth.ts through the route.
const policy = DEPLOYMENT, s = policy.scheduler;
const jobClaims = (workflow, audiencePath = '/api/fleet/jobs') => {
  const now = Math.floor(Date.now() / 1000);
  return {iss: 'https://token.actions.githubusercontent.com', aud: policy.public_origin + audiencePath, sub: `repo:${s.repository}:ref:${s.ref}`,
    repository: s.repository, repository_id: s.repository_id, repository_owner_id: s.owner_id, ref: s.ref,
    workflow_ref: `${s.repository}/.github/workflows/${workflow}@${s.ref}`, event_name: 'schedule', iat: now, nbf: now, exp: now + 300, jti: `run-${workflow}`};
};

test('FLEET_JOB_SCOPE: the fleet audience and the four fleet workflows, all listed in scheduler.workflows', () => {
  assert.deepEqual(FLEET_JOB_SCOPE, {audiencePath: '/api/fleet/jobs', workflows: ['fleet-registry.yml', 'fleet-osint.yml', 'fleet-ais.yml', 'fleet-health.yml']});
  for (const workflow of FLEET_JOB_SCOPE.workflows) assert.ok(s.workflows.includes(workflow), workflow);
});

test('a signed fleet-ais.yml token reaches ping; advisor-media.yml, trip-check and wrong-audience tokens get 401', async () => {
  const pair = await crypto.subtle.generateKey({name: 'RSASSA-PKCS1-v1_5', modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256'}, true, ['sign', 'verify']);
  const jwk = {...await crypto.subtle.exportKey('jwk', pair.publicKey), kid: 'test', alg: 'RS256', use: 'sig'};
  const b64 = x => Buffer.from(JSON.stringify(x)).toString('base64url');
  const sign = async c => { const body = b64({alg: 'RS256', typ: 'JWT', kid: 'test'}) + '.' + b64(c); return body + '.' + Buffer.from(await crypto.subtle.sign('RSASSA-PKCS1-v1_5', pair.privateKey, new TextEncoder().encode(body))).toString('base64url'); };
  const {sql, adapter} = database(), env = {DB: adapter, ...ON}, saved = globalThis.fetch, warn = console.warn;
  globalThis.fetch = async url => { assert.equal(url, 'https://token.actions.githubusercontent.com/.well-known/jwks'); return Response.json({keys: [jwk]}); };
  console.warn = () => {};
  try {
    for (const workflow of FLEET_JOB_SCOPE.workflows) {
      const response = await call('/api/fleet/jobs/ping?region=CA', env, {headers: bearer(await sign(jobClaims(workflow)))});
      assert.equal(response.status, 200, workflow);
    }
    const refused = [['advisor-media.yml', '/api/fleet/jobs'], ['advisor-media.yml', '/api/advisor/jobs'], ['live-conditions.yml', '/api/fleet/jobs'],
      ['fleet-ais.yml', '/api/advisor/jobs'], ['fleet-ais.yml', '/api/jobs/check'], ['deploy-cloudflare.yml', '/api/fleet/jobs']];
    for (const [workflow, aud] of refused)
      assert.equal((await call('/api/fleet/jobs/ping', env, {headers: bearer(await sign(jobClaims(workflow, aud)))})).status, 401, `${workflow} ${aud}`);
    const token = await sign(jobClaims('fleet-ais.yml'));
    assert.equal((await call('/api/fleet/jobs/ping', {DB: adapter}, {headers: bearer(token)})).status, 404, 'a valid token is still dark while FLEET_ENABLED is off');
    // The fleet token is no advisor job either.
    assert.equal((await call('/api/advisor/jobs/media', {DB: adapter, TEXT_ADVISOR_ENABLED: 'true'}, {headers: bearer(token)})).status, 401);
  } finally { globalThis.fetch = saved; console.warn = warn; sql.close(); }
});

test('admin: /admin opens with only FLEET_ENABLED; the advisor admin API stays dark; with both off everything is 404', async () => {
  const {sql, adapter} = database();
  sql.prepare("INSERT INTO users(id,created_at,role) VALUES('admin-1',?,'admin')").run(new Date().toISOString());
  const as = (path, env, owner = 'admin-1') => worker.fetch(new Request(ORIGIN + path, {headers: {'x-test-owner': owner}}), {ASSETS, DB: adapter, ...env});
  try {
    const fleetOnly = await as('/admin', ON);
    assert.equal(fleetOnly.status, 302);
    assert.equal(fleetOnly.headers.get('Location'), '/admin.html');
    assert.equal((await as('/admin.html', ON)).status, 299, 'the shell is served');
    assert.equal((await as('/api/admin/reviews', ON)).status, 404, 'the advisor admin API keeps its own switch');
    assert.equal((await as('/api/admin/health', ON)).status, 404);
    assert.equal((await as('/admin', ON, 'someone')).status, 404, 'a non-admin sees nothing');
    for (const path of ['/admin', '/admin.html', '/api/admin/reviews', '/api/admin/fleet/reviews']) assert.equal((await as(path, {})).status, 404, `both off: ${path}`);
    assert.equal((await as('/admin', {TEXT_ADVISOR_ENABLED: 'true'})).status, 302, 'the advisor alone still opens it');
    assert.equal((await as('/api/admin/reviews', {TEXT_ADVISOR_ENABLED: 'true'})).status, 200);
  } finally { sql.close(); }
});
