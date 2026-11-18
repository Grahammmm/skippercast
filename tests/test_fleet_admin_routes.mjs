// The admin app's fleet routes (CF-31, web/admin/route.ts): parsing, the nav entry a route marks, and the flag gating.
import test from 'node:test';
import assert from 'node:assert/strict';

const {routeOf, navOf, visibleViews, shownRoute, VIEWS, FLEET_VIEWS} = await import('../web/admin/route.ts');
const ID = 'a'.repeat(32);

test('routeOf: fleet views with a valid region, vessel details by 32-hex id, anything else the queue', () => {
  assert.deepEqual(routeOf('#fleet-review'), {view: 'fleet-review', arg: ''});
  assert.deepEqual(routeOf('#fleet-vessels?region=CA'), {view: 'fleet-vessels', arg: 'CA'});
  assert.deepEqual(routeOf('#fleet-review?region=%3Cx%3E'), {view: 'fleet-review', arg: ''});
  assert.deepEqual(routeOf(`#fleet-vessel/${ID}`), {view: 'fleet-vessel', arg: ID});
  for (const hash of ['#fleet-vessel/abc', `#fleet-vessel/${ID}/x`, '#fleet-vessel/', '#fleet-review/x', '#constructor/x'])
    assert.equal(routeOf(hash).view, 'queue', hash);
});

test('navOf marks a contact as Skippers and a vessel as Vessels', () => {
  assert.equal(navOf('contact'), 'skippers');
  assert.equal(navOf('fleet-vessel'), 'fleet-vessels');
  assert.equal(navOf('fleet-review'), 'fleet-review');
});

test('visibleViews and shownRoute hide the fleet while its flag is off', () => {
  assert.deepEqual(visibleViews({advisor: true, fleet: false}), [...VIEWS]);
  assert.deepEqual(visibleViews({advisor: false, fleet: true}), [...FLEET_VIEWS]);
  assert.deepEqual(shownRoute(routeOf(`#fleet-vessel/${ID}`), {advisor: true, fleet: false}), {view: 'queue', arg: ''});
  assert.deepEqual(shownRoute(routeOf('#health'), {advisor: false, fleet: true}), {view: 'fleet-review', arg: ''});
  assert.equal(shownRoute(routeOf('#queue'), {advisor: false, fleet: false}), null);
});

// SCA-017: the fleet job route/role matrix through the Worker, offline, with the
// OIDC verifier stubbed to synthetic claims shaped as validJobClaims accepts them.
// The monitor (fleet-health.yml) may only read GET /api/fleet/jobs/health and run
// the data-free identity ping; every other job route answers 403 before any
// storage work (no D1 statement, not even the request budget). The registry,
// OSINT and AIS processor identities keep every job route; no token stays 401.
import {readFileSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

const readJSON = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS ??= {'morro-bay': readJSON('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT ??= readJSON('../deployments/production.json');
globalThis.SHELLS ??= {'/': '/index.0123456789.html', '/admin.html': '/admin.0123456789.html'};
globalThis.BUILD_ID ??= 'build-test';
const {default: worker} = await import('../server/index.ts');
const {fleetJobs, fleetRouter, FLEET_JOB_SCOPE, FLEET_JOB_LIMITS} = await import('../server/routes/fleet.ts');

const S = globalThis.DEPLOYMENT.scheduler, ORIGIN = 'https://skippercast.com';
const MONITOR = 'fleet-health.yml', PROCESSORS = ['fleet-registry.yml', 'fleet-osint.yml', 'fleet-ais.yml'];
const HEALTH = 'GET /api/fleet/jobs/health', PING = 'GET /api/fleet/jobs/ping';
const claimsOf = workflow => ({jti: `run-${workflow}`, workflow_ref: `${S.repository}/.github/workflows/${workflow}@${S.ref}`});
/** Every registered job route as 'METHOD /path' (middleware rows are method ALL). */
const ROUTES = [...new Set(fleetRouter.routes.filter(r => r.method !== 'ALL' && r.path.startsWith('/api/fleet/jobs/')).map(r => `${r.method} ${r.path}`))];

/** The migrated D1 fake, counting every statement the Worker prepares or batches. */
function countingDatabase() {
  const {db} = advisorDatabase(), seen = {statements: 0};
  return {seen, db: {prepare(q) { seen.statements++; return db.prepare(q); }, async batch(qs) { seen.statements += qs.length; return db.batch(qs); }}};
}
async function call(route, token) {
  const [method, path] = route.split(' '), {db, seen} = countingDatabase();
  const init = {method, headers: token ? {Authorization: `Bearer ${token}`} : {}};
  if (method === 'POST') { init.headers['Content-Type'] = 'application/json'; init.body = '{}'; }
  const response = await worker.fetch(new Request(`${ORIGIN}${path}?region=CA`, init), {ASSETS: {fetch: async () => new Response('', {status: 299})}, DB: db, FLEET_ENABLED: 'true'});
  return {status: response.status, body: await response.json().catch(() => null), statements: seen.statements};
}

const skip = sqliteUnavailable ?? false;
let verifySaved;
test.before(() => { verifySaved = fleetJobs.verify; fleetJobs.verify = async token => [MONITOR, ...PROCESSORS].includes(token) ? claimsOf(token) : false; });
test.after(() => { fleetJobs.verify = verifySaved; });

test('SCA-017: the limits name only fleet job workflows, and the matrix covers the private reads and mutations', () => {
  for (const workflow of Object.keys(FLEET_JOB_LIMITS)) assert.ok(FLEET_JOB_SCOPE.workflows.includes(workflow), workflow);
  assert.deepEqual([...FLEET_JOB_LIMITS[MONITOR]].sort(), [HEALTH, PING]);
  for (const workflow of PROCESSORS) assert.equal(FLEET_JOB_LIMITS[workflow], undefined, workflow);
  for (const route of [HEALTH, 'GET /api/fleet/jobs/snapshot', 'GET /api/fleet/jobs/watch', 'GET /api/fleet/jobs/labels', 'POST /api/fleet/jobs/registry',
    'POST /api/fleet/jobs/activity', 'POST /api/fleet/jobs/heartbeat', 'POST /api/fleet/jobs/watch', 'POST /api/fleet/jobs/labels']) assert.ok(ROUTES.includes(route), route);
});

test('SCA-017: the monitor identity reads the health contract and nothing else, refused before any storage work', {skip}, async () => {
  const ok = await call(HEALTH, MONITOR);
  assert.equal(ok.status, 200);
  assert.deepEqual(Object.keys(ok.body.checks).sort(), ['heartbeat', 'last_message', 'processed']);
  assert.equal(typeof ok.body.stale, 'boolean');
  assert.ok(ok.statements > 0, 'the permitted health read reaches D1');
  const ping = await call(PING, MONITOR);
  assert.equal(ping.status, 200);
  assert.deepEqual(ping.body, {ok: true, region: 'CA'});
  const denied = [...ROUTES.filter(r => r !== HEALTH && r !== PING), 'POST /api/fleet/jobs/health', 'GET /api/fleet/jobs/health/', 'GET /api/fleet/jobs/nope', 'POST /api/fleet/jobs/nope'];
  for (const route of denied) {
    const result = await call(route, MONITOR);
    assert.equal(result.status, 403, route);
    assert.equal(result.body?.error, 'Forbidden', route);
    assert.equal(result.statements, 0, `${route}: no D1 work before the refusal`);
  }
});

test('SCA-017: the processor and registry identities keep every job route; no identity stays 401', {skip}, async () => {
  for (const workflow of PROCESSORS) for (const route of ROUTES) {
    const result = await call(route, workflow);
    assert.ok(![401, 403].includes(result.status), `${workflow} ${route}: ${result.status}`);
    assert.ok(result.statements > 0, `${workflow} ${route} reaches D1`);
  }
  for (const route of ROUTES) for (const token of [undefined, 'not-a-job']) {
    const result = await call(route, token);
    assert.equal(result.status, 401, `${token} ${route}`);
    assert.equal(result.statements, 0, `${token} ${route}`);
  }
});
