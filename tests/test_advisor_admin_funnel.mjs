// Text Advisor admin Funnel (TA-W4; docs/plans/text-advisor/08-website.md § Admin,
// Funnel; OP-5): the gate and the days allowlist, every D1 count on a seeded
// database, the Analytics Engine part through a fake SQL API (queries, label
// cleaning, the not-configured / no-data / error states), the real fetcher's URL,
// headers and error handling against a fake fetch, numbers only (no ids) in the
// answer, and the deploy wiring that uploads CF_ANALYTICS_TOKEN with the account id.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, mkdtempSync, rmSync, writeFileSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';
import {withSessions} from './fixtures/test-sessions.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html', '/admin.html': '/admin.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
const {default: deployed} = await import('../server/index.ts');
const {Hono} = await import('hono');
const {context} = await import('../server/middleware/context.ts');
const {requireUser} = await import('../server/middleware/auth.ts');
const {onError} = await import('../server/middleware/error.ts');
const {adminRoutes} = await import('../server/routes/admin.ts');
const {adminFunnel, analyticsSql, funnelQueries, daysBetween, SQL_API} = await import('../server/advisor/admin/funnel.ts');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const ORIGIN = 'https://skippercast.com';
const ADMIN = 'admin-user-1', OTHER = 'plain-user-1';
const T0 = Date.parse('2026-10-04T18:00:00Z'), DAY = 86400000;
const iso = ms => new Date(ms).toISOString();
const ACCOUNT = '0123456789abcdef0123456789abcdef';
const quiet = async fn => { const saved = {log: console.log, warn: console.warn, error: console.error}, lines = []; console.log = console.warn = console.error = (...a) => lines.push(a.join(' ')); try { return {value: await fn(), lines}; } finally { Object.assign(console, saved); } };

function setup({sql: analytics} = {}) {
  const {sql, db} = advisorDatabase();
  sql.prepare("INSERT INTO users(id,created_at,role) VALUES(?,?,'admin')").run(ADMIN, iso(T0));
  sql.prepare('INSERT INTO users(id,created_at) VALUES(?,?)').run(OTHER, iso(T0));
  const app = new Hono({getPath: request => new URL(request.url).pathname});
  app.use('*', context);
  app.use('/api/*', requireUser);
  app.route('/', adminRoutes({now: () => T0, ...(analytics !== undefined ? {analyticsSql: analytics} : {})}));
  app.onError(onError);
  return {sql, db, real: withSessions(deployed), worker: withSessions({fetch: (request, e, ctx) => app.fetch(request, e, ctx)}), env: {TEXT_ADVISOR_ENABLED: 'true', DB: db}};
}
const get = (worker, env, path, owner = ADMIN) => worker.fetch(new Request(ORIGIN + path, {headers: owner ? {'x-test-owner': owner} : {}}), env);

/** A week of advisor activity; every id carries ID-SECRET so a leak would show. */
function seed(sql) {
  const contact = (id, source, at) => sql.prepare(`INSERT INTO advisor_contacts(id,phone_hash,channel,source,status,last_seen_at,created_at,updated_at) VALUES(?,?,'imessage',?,'active',?,?,?)`)
    .run(id, `HASH-${id}`, source, iso(at), iso(at), iso(at));
  contact('ID-SECRET-c1', 'instagram', T0 - 1 * DAY);
  contact('ID-SECRET-c2', 'instagram', T0 - 1 * DAY);
  contact('ID-SECRET-c3', 'skipper-invite', T0 - 3 * DAY);
  contact('ID-SECRET-c4', null, T0);
  contact('ID-SECRET-old', 'qr', T0 - 20 * DAY);
  let n = 0;
  const message = (c, direction, at, intent = null, status = direction === 'in' ? 'done' : 'sent') => sql.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,body,intent,status,created_at) VALUES(?,?,?,'imessage','x',?,?,?)`)
    .run(`ID-SECRET-m${++n}`, c, direction, intent, status, iso(at));
  message('ID-SECRET-c1', 'in', T0 - 1 * DAY, 'report.daily'); message('ID-SECRET-c1', 'out', T0 - 1 * DAY);
  message('ID-SECRET-c1', 'in', T0 - 2 * DAY, 'report.daily'); message('ID-SECRET-c1', 'out', T0 - 2 * DAY);
  message('ID-SECRET-c2', 'in', T0 - 1 * DAY, 'fishid'); message('ID-SECRET-c2', 'out', T0 - 1 * DAY); message('ID-SECRET-c2', 'out', T0 - 1 * DAY + 1000);
  message('ID-SECRET-c3', 'in', T0 - 3 * DAY); message('ID-SECRET-c3', 'out', T0 - 3 * DAY, null, 'failed');
  message('ID-SECRET-old', 'in', T0 - 20 * DAY, 'fishid'); message('ID-SECRET-old', 'out', T0 - 20 * DAY);
  const boat = (id, status, verifiedAt, consent = null) => sql.prepare(`INSERT INTO advisor_boats(id,slug,name,port,region,status,verified_at,consent_photos_at,created_at,updated_at) VALUES(?,?,?,'morro-bay','morro-bay',?,?,?,?,?)`)
    .run(id, id.toLowerCase(), `Boat ${id}`, status, verifiedAt, consent, iso(T0 - 30 * DAY), iso(T0));
  boat('ID-SECRET-b1', 'verified', iso(T0 - 2 * DAY), iso(T0 - 2 * DAY));
  boat('ID-SECRET-b2', 'verified', iso(T0 - 25 * DAY));
  boat('ID-SECRET-b3', 'pending', null, iso(T0 - DAY));
  boat('ID-SECRET-b4', 'rejected', null, iso(T0 - DAY));
  const report = (id, b, at, status = 'published') => sql.prepare(`INSERT INTO advisor_reports(id,boat_id,region,port,report_date,counts_json,source,status,verified,version,published_at,created_at,updated_at) VALUES(?,?,'morro-bay','morro-bay',?,'[]','text',?,1,1,?,?,?)`)
    .run(id, b, iso(at).slice(0, 10), status, status === 'published' ? iso(at) : null, iso(at), iso(at));
  report('ID-SECRET-r1', 'ID-SECRET-b1', T0 - DAY); report('ID-SECRET-r2', 'ID-SECRET-b1', T0 - 2 * DAY); report('ID-SECRET-r3', 'ID-SECRET-b2', T0 - 3 * DAY);
  report('ID-SECRET-r4', 'ID-SECRET-b2', T0 - 4 * DAY, 'pending_confirm'); report('ID-SECRET-r5', 'ID-SECRET-b2', T0 - 15 * DAY);
  const media = (id, state, at, kind = 'image') => sql.prepare(`INSERT INTO advisor_media(id,contact_id,kind,mime,bytes,r2_key,sha256,exif_stripped,publish_state,created_at) VALUES(?,'ID-SECRET-c1',?,'image/jpeg',1,'k','s',1,?,?)`)
    .run(id, kind, state, iso(at));
  media('ID-SECRET-p1', 'approved', T0 - DAY); media('ID-SECRET-p2', 'private', T0 - DAY); media('ID-SECRET-p3', 'approved', T0 - 12 * DAY); media('ID-SECRET-v1', 'private', T0, 'video');
}

dbTest('GET /api/admin/funnel is admin-only, takes days=7 or 30 and nothing else', async () => {
  const {env, real} = setup();
  assert.equal((await get(real, env, '/api/admin/funnel', OTHER)).status, 404);
  assert.equal((await get(real, env, '/api/admin/funnel', null)).status, 401);
  assert.equal((await get(real, env, '/api/admin/funnel', ADMIN, )).status, 200);
  assert.equal((await get(real, {...env, TEXT_ADVISOR_ENABLED: 'false'}, '/api/admin/funnel')).status, 404);
  for (const bad of ['14', 'abc', '7.5', '-7', '7%20OR%201']) assert.equal((await get(real, env, `/api/admin/funnel?days=${bad}`)).status, 400, bad);
  assert.equal((await (await get(real, env, '/api/admin/funnel?days=30')).json()).days, 30);
});

dbTest('the D1 counts: contacts by UTC day and source, intents, replies per contact, return rate, boats, reports per boat, photos, consent; no id anywhere', async () => {
  const queries = [];
  const fake = async sql => { queries.push(sql); return []; };
  const {sql, env, worker} = setup({sql: fake});
  seed(sql);
  const response = await get(worker, env, '/api/admin/funnel?days=7');
  const text = await response.text();
  assert.equal(response.status, 200);
  assert.doesNotMatch(text, /ID-SECRET|HASH-/, 'numbers and labels only');
  const f = JSON.parse(text);
  assert.deepEqual([f.days, f.since, f.generated_at], [7, iso(T0 - 7 * DAY), iso(T0)]);
  assert.equal(f.contacts.by_day.length, 8, 'every UTC day from the window start through today');
  assert.equal(f.contacts.new, 4, 'the 20-day-old contact is outside the window');
  assert.deepEqual(f.contacts.sources, ['instagram', 'skipper-invite', 'unknown']);
  assert.deepEqual(f.contacts.by_day.find(d => d.day === '2026-10-03'), {day: '2026-10-03', total: 2, by_source: {instagram: 2}});
  assert.deepEqual(f.contacts.by_day.at(-1), {day: '2026-10-04', total: 1, by_source: {unknown: 1}});
  assert.equal(f.contacts.by_day[0].total, 0);
  assert.deepEqual(f.messages, {inbound: 4, by_intent: [{intent: 'report.daily', count: 2}, {intent: 'fishid', count: 1}, {intent: 'none', count: 1}]});
  assert.deepEqual(f.replies, {outbound: 4, contacts: 2, per_contact: 2}, 'a failed send is not a reply');
  assert.deepEqual(f.return_rate, {active: 3, returning: 1, rate: 0.333});
  assert.deepEqual(f.boats, {verified: 1, verified_total: 2, pending: 1, reports_published: 3, boats_reporting: 2, reports_per_boat: 1.5});
  assert.deepEqual(f.photos, {submitted: 2, approved: 1}, 'images only, created in the window');
  assert.deepEqual(f.consent, {boats: 3, given: 2, rate: 0.667}, 'rejected boats are not counted');
  assert.equal(queries.length, 3);
  const month = await (await get(worker, env, '/api/admin/funnel?days=30')).json();
  assert.deepEqual([month.contacts.new, month.boats.reports_published, month.photos.submitted], [5, 4, 3]);
  assert.ok(queries.slice(3).every(q => q.includes("INTERVAL '30' DAY")));
});

test('the Analytics Engine part: three statements on skippercast_events, rows mapped to numbers and cleaned labels', async () => {
  const q = funnelQueries(7);
  assert.match(q.llm, /index1 = 'llm' AND timestamp > NOW\(\) - INTERVAL '7' DAY/);
  assert.match(q.turns, /quantileExactWeighted\(0\.5\)\(double1, _sample_interval\)[\s\S]*quantileExactWeighted\(0\.95\)/);
  assert.match(q.pages, /blob2 IN \('advisor_port_view', 'advisor_species_view', 'advisor_boat_view', 'advisor_cta'\)/);
  assert.throws(() => funnelQueries(14));
  const rows = {
    llm: [{feature: 'advisor:report.daily', calls: '12', input_tokens: '3400', output_tokens: 900}, {feature: '<script>', calls: 1, input_tokens: 1, output_tokens: 1}],
    turns: [{turns: '40', p50_ms: '2310.4', p95_ms: 9020}],
    pages: [{event: 'advisor_port_view', source: 'txt', events: '30'}, {event: 'advisor_cta', source: '', events: 4}, {event: 'advisor_port_view', source: 'zz', events: 2}, {event: 'map_viewed', source: '', events: 99}],
  };
  const fake = async sql => (sql.includes("'llm'") ? rows.llm : sql.includes("'advisor_turn'") ? rows.turns : rows.pages);
  const {db} = sqliteUnavailable ? {db: null} : advisorDatabase();
  if (!db) return;
  const f = await adminFunnel({DB: db}, 7, {now: T0, sql: fake});
  assert.deepEqual(f.analytics, {available: true, reason: null,
    llm: [{feature: 'advisor:report.daily', calls: 12, input_tokens: 3400, output_tokens: 900}, {feature: 'other', calls: 1, input_tokens: 1, output_tokens: 1}],
    turns: {count: 40, p50_ms: 2310, p95_ms: 9020},
    pages: [{event: 'advisor_port_view', source: 'txt', count: 30}, {event: 'advisor_cta', source: '', count: 4}, {event: 'advisor_port_view', source: 'other', count: 2}]});
  const none = await adminFunnel({DB: db}, 7, {now: T0, sql: null});
  assert.deepEqual([none.analytics.available, none.analytics.reason, none.analytics.turns], [false, 'not-configured', {count: 0, p50_ms: null, p95_ms: null}]);
  const {value: failed, lines} = await quiet(() => adminFunnel({DB: db}, 7, {now: T0, sql: async () => { throw new Error('boom'); }}));
  assert.deepEqual([failed.analytics.available, failed.analytics.reason, failed.contacts.new], [false, 'error', 0], 'the D1 part still answers');
  assert.match(lines.join('\n'), /advisor_funnel_analytics_failed/);
});

test('analyticsSql: null without the token or a 32-hex account; POSTs the statement with the bearer token; a never-written dataset is no-data', async () => {
  assert.equal(analyticsSql({}), null);
  assert.equal(analyticsSql({CF_ANALYTICS_TOKEN: 'tok'}), null);
  assert.equal(analyticsSql({CF_ANALYTICS_TOKEN: 'tok', CLOUDFLARE_ACCOUNT_ID: 'not-an-account'}), null);
  const calls = [];
  const ok = analyticsSql({CF_ANALYTICS_TOKEN: 'tok-secret', CLOUDFLARE_ACCOUNT_ID: ACCOUNT}, async (url, init) => { calls.push({url, init}); return Response.json({data: [{calls: 1}], meta: []}); });
  assert.deepEqual(await ok('SELECT 1'), [{calls: 1}]);
  assert.equal(calls[0].url, SQL_API.replace('{account}', ACCOUNT));
  assert.deepEqual([calls[0].init.method, calls[0].init.body, calls[0].init.headers.Authorization, calls[0].init.headers['Content-Type']], ['POST', 'SELECT 1', 'Bearer tok-secret', 'text/plain']);
  const missing = analyticsSql({CF_ANALYTICS_TOKEN: 'tok-secret', CLOUDFLARE_ACCOUNT_ID: ACCOUNT}, async () => new Response('unknown table skippercast_events: does not exist', {status: 400}));
  await assert.rejects(missing('SELECT 1'), e => e.noData === true && e.status === 400);
  const denied = analyticsSql({CF_ANALYTICS_TOKEN: 'tok-secret', CLOUDFLARE_ACCOUNT_ID: ACCOUNT}, async () => new Response('Authentication error', {status: 403}));
  await assert.rejects(denied('SELECT 1'), e => e.noData === false && e.status === 403);
  if (sqliteUnavailable) return;
  const {db} = advisorDatabase();
  const {value: f, lines} = await quiet(() => adminFunnel({DB: db, CF_ANALYTICS_TOKEN: 'tok-secret', CLOUDFLARE_ACCOUNT_ID: ACCOUNT}, 7, {now: T0,
    sql: analyticsSql({CF_ANALYTICS_TOKEN: 'tok-secret', CLOUDFLARE_ACCOUNT_ID: ACCOUNT}, async () => new Response('unknown table skippercast_events', {status: 404}))}));
  assert.equal(f.analytics.reason, 'no-data');
  assert.doesNotMatch(lines.join('\n'), /tok-secret/, 'the token is never logged');
  assert.deepEqual(daysBetween(T0 - DAY, T0), ['2026-10-03', '2026-10-04']);
});

test('deploy wiring: the workflow passes CF_ANALYTICS_TOKEN from secrets, and the deploy uploads it with the account id only when the token is set', () => {
  const workflow = readFileSync(new URL('../.github/workflows/deploy-cloudflare.yml', import.meta.url), 'utf8');
  assert.match(workflow, /^ {10}CF_ANALYTICS_TOKEN: \$\{\{ secrets\.CF_ANALYTICS_TOKEN \}\}$/m);
  assert.match(workflow, /^ {6}CLOUDFLARE_ACCOUNT_ID: \$\{\{ secrets\.CLOUDFLARE_ACCOUNT_ID \}\}$/m, 'the account id is already in the job env');
  const script = readFileSync(new URL('../scripts/cloudflare_deploy.sh', import.meta.url), 'utf8');
  const python = script.slice(script.indexOf("python3 - <<'PY' > var/cloudflare-secrets.json") + "python3 - <<'PY' > var/cloudflare-secrets.json".length, script.indexOf('\nPY\n')).trim();
  const dir = mkdtempSync(join(tmpdir(), 'secrets-'));
  try {
    const file = join(dir, 'secrets.py');
    writeFileSync(file, python);
    const run = env => JSON.parse(spawnSync('python3', [file], {encoding: 'utf8', env: {PATH: process.env.PATH, ...env}}).stdout);
    assert.deepEqual(run({CF_ANALYTICS_TOKEN: 'tok', CLOUDFLARE_ACCOUNT_ID: ACCOUNT}), {CF_ANALYTICS_TOKEN: 'tok', CLOUDFLARE_ACCOUNT_ID: ACCOUNT});
    assert.deepEqual(run({CLOUDFLARE_ACCOUNT_ID: ACCOUNT}), {}, 'no token: the account id stays out of the Worker too');
  } finally { rmSync(dir, {recursive: true, force: true}); }
});
