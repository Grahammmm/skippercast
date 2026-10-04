// Text Advisor admin Rules and the CDFW change-watch (TA-A4; docs/plans/text-advisor/
// 08-website.md § Admin, Rules; 02 § advisor_rules; OP-6): the gate, the list with
// its filters and due flags, create / edit / retire with their validation, the
// review stamp (reviewed_at now, review_due = the sooner of 90 days and the
// season's end, status active, updated_by the admin), the pages version, what
// lookupRules then quotes, the daily rules-watch slot on the daily feed's
// regulation checks (rows to review, one deterministic review per jurisdiction
// and change, an admin's re-confirmation standing until the pages change again),
// and the queue's rule-change card. Offline: the importer's rows in node:sqlite,
// tests/fixtures/feeds/daily-latest.json as the feed.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
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
const {reviewDue, validSeason, ruleId, watchRuleSources, changedSources, changeRef, CHANGE_PREFIX, LAST_WATCH_KEY, JURISDICTIONS} = await import('../server/advisor/admin/rules.ts');
const {lookupRules} = await import('../server/advisor/answers/rules.ts');
const {reviewId} = await import('../server/advisor/contacts.ts');
const {PAGES_VERSION_KEY} = await import('../server/advisor/intake/reports.ts');
const {advisorCron, SLOT_PREFIX} = await import('../server/advisor/cron.ts');
const {routeOf, rulesHref} = await import('../web/admin/route.ts');
const importer = await import('../scripts/advisor/import-rules.mjs');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const ORIGIN = 'https://skippercast.com';
const ADMIN = 'admin-user-1', OTHER = 'plain-user-1';
const T0 = Date.parse('2026-10-04T18:00:00Z'), DAY = 86400000;
const iso = ms => new Date(ms).toISOString();
const CDFW = 'https://wildlife.ca.gov/Fishing/Ocean/Regulations/Fishing-Map/Central';
const quiet = async fn => { const saved = {log: console.log, warn: console.warn, error: console.error}, lines = []; console.log = console.warn = console.error = (...a) => lines.push(a.join(' ')); try { return {value: await fn(), lines}; } finally { Object.assign(console, saved); } };

function setup({now = T0} = {}) {
  const {sql, db} = advisorDatabase();
  sql.prepare("INSERT INTO users(id,created_at,role) VALUES(?,?,'admin')").run(ADMIN, iso(T0));
  sql.prepare('INSERT INTO users(id,created_at) VALUES(?,?)').run(OTHER, iso(T0));
  sql.exec(importer.rulesSql(importer.importRows(T0 - 100 * DAY)));   // imported 100 days ago: every row in review and past due
  const clock = {now};
  const app = new Hono({getPath: request => new URL(request.url).pathname});
  app.use('*', context);
  app.use('/api/*', requireUser);
  app.route('/', adminRoutes({now: () => clock.now}));
  app.onError(onError);
  return {sql, db, clock, real: withSessions(deployed), worker: withSessions({fetch: (request, e, ctx) => app.fetch(request, e, ctx)}), env: {TEXT_ADVISOR_ENABLED: 'true', DB: db}};
}
const get = (worker, env, path, owner = ADMIN) => worker.fetch(new Request(ORIGIN + path, {headers: owner ? {'x-test-owner': owner} : {}}), env);
const post = (worker, env, path, body, owner = ADMIN) => worker.fetch(new Request(ORIGIN + path, {method: 'POST',
  headers: {'Content-Type': 'application/json', Origin: ORIGIN, ...(owner ? {'x-test-owner': owner} : {})}, body: JSON.stringify(body)}), env);
const call = async (worker, env, method, path, body) => {
  const response = (await quiet(() => (method === 'GET' ? get(worker, env, path) : post(worker, env, path, body)))).value;
  const text = await response.text();
  return {status: response.status, body: (() => { try { return JSON.parse(text); } catch { return text; } })()};
};
const version = sql => Number(sql.prepare('SELECT value FROM job_state WHERE key=?').get(PAGES_VERSION_KEY)?.value ?? 0);
const lingcodId = () => importer.importRows(T0).find(r => r.jurisdiction === 'california-central' && r.species_key === 'lingcod').id;
const rowOf = (sql, id) => ({...sql.prepare('SELECT * FROM advisor_rules WHERE id=?').get(id)});

/** The daily feed fixture with some of its regulation checks changed. */
function feedWith(changes = {}, extra = {}) {
  const feed = structuredClone(read('./fixtures/feeds/daily-latest.json'));
  for (const [id, sha] of Object.entries(changes)) feed.regulations.checks[id] = {...feed.regulations.checks[id], status: 'changed', content_sha256: sha};
  Object.assign(feed.regulations, extra);
  return async url => { if (/latest\.json$/.test(url)) return feed; throw Error(`no fixture for ${url}`); };
}

// ---- the gate ----------------------------------------------------------------------------

dbTest('every rules route is a 404 for a non-admin and while the advisor is off, 401 signed out', async () => {
  const {sql, env, real} = setup();
  const id = lingcodId();
  const routes = [['GET', '/api/admin/rules'], ['POST', '/api/admin/rules'], ['POST', `/api/admin/rules/${id}`], ['POST', `/api/admin/rules/${id}/retire`]];
  for (const [method, path] of routes) {
    assert.equal((await quiet(() => (method === 'GET' ? get(real, env, path, OTHER) : post(real, env, path, {}, OTHER)))).value.status, 404, `${method} ${path}`);
    assert.equal((await quiet(() => (method === 'GET' ? get(real, env, path, null) : post(real, env, path, {}, null)))).value.status, 401);
    assert.equal((await quiet(() => (method === 'GET' ? get(real, {...env, TEXT_ADVISOR_ENABLED: 'false'}, path) : post(real, {...env, TEXT_ADVISOR_ENABLED: 'false'}, path, {})))).value.status, 404);
  }
  assert.deepEqual([rowOf(sql, id).status, rowOf(sql, id).updated_by], ['review', 'import-rules'], 'nothing changed');
});

// ---- list --------------------------------------------------------------------------------

dbTest('GET /api/admin/rules filters by jurisdiction and status, flags due rows and carries the editor’s choices', async () => {
  const {sql, env, worker} = setup();
  const all = await call(worker, env, 'GET', '/api/admin/rules');
  assert.equal(all.status, 200);
  assert.equal(all.body.rules.length, sql.prepare('SELECT COUNT(*) AS n FROM advisor_rules').get().n);
  assert.ok(all.body.rules.every(r => r.due), 'imported rows are in review, so due');
  assert.deepEqual(all.body.jurisdictions, [...JURISDICTIONS.keys()]);
  assert.deepEqual(all.body.regions, [{id: 'morro-bay', jurisdiction: 'california-central'}]);
  assert.ok(all.body.species.some(s => s.key === 'vermilion') && all.body.species.some(s => s.key === 'other'));
  assert.ok(!all.body.species.some(s => s.key === 'california-halibut'), 'synonyms are not rule keys');
  const central = await call(worker, env, 'GET', '/api/admin/rules?jurisdiction=california-central');
  assert.ok(central.body.rules.length > 5 && central.body.rules.every(r => r.jurisdiction === 'california-central'));
  sql.prepare("UPDATE advisor_rules SET status='active', review_due='2027-01-01' WHERE id=?").run(lingcodId());
  sql.prepare("UPDATE advisor_rules SET status='active', review_due='2026-10-01' WHERE jurisdiction='california-central' AND species_key='rockfish'").run();
  const due = await call(worker, env, 'GET', '/api/admin/rules?jurisdiction=california-central&status=due');
  assert.ok(!due.body.rules.some(r => r.id === lingcodId()), 'an active row before its due date is not due');
  assert.ok(due.body.rules.some(r => r.species_key === 'rockfish' && r.status === 'active' && r.due), 'an active row past its due date is');
  assert.deepEqual((await call(worker, env, 'GET', '/api/admin/rules?status=active')).body.rules.map(r => r.status).filter(s => s !== 'active'), []);
  for (const bad of ['jurisdiction=oregon', 'status=open', "jurisdiction=california-central'"]) assert.equal((await call(worker, env, 'GET', `/api/admin/rules?${bad}`)).status, 400, bad);
});

// ---- create, edit, retire ----------------------------------------------------------------

test('review_due: 90 days on, or the season close when sooner and not past; MM-DD is its next occurrence', () => {
  assert.equal(reviewDue(T0, null), '2027-01-02');
  assert.equal(reviewDue(T0, '10-31'), '2026-10-31');
  assert.equal(reviewDue(T0, '2026-11-15'), '2026-11-15');
  assert.equal(reviewDue(T0, '2026-09-30'), '2027-01-02', 'a past ISO close');
  assert.equal(reviewDue(T0, '09-30'), '2027-01-02', 'MM-DD past this year: next year’s, beyond 90 days');
  assert.equal(reviewDue(T0, '12-31'), '2026-12-31');
  assert.equal(reviewDue(T0, '10-04'), '2026-10-04', 'today counts');
  for (const ok of ['01-01', '02-29', '2026-12-31']) assert.ok(validSeason(ok), ok);
  for (const bad of ['13-01', '02-30', '2026-02-29', '1-1', '2026/01/01', 'spring']) assert.ok(!validSeason(bad), bad);
});

dbTest('create: validated, active with the review stamp, the importer’s id, refused when the row exists; then quotable and the pages re-render', async () => {
  const {sql, env, worker} = setup();
  const base = {jurisdiction: 'california-central', region: '*', species_key: 'other', species_label: 'Pacific sanddab', bag_limit: 10, source_name: 'CDFW Central Region', source_url: CDFW};
  const bad = [
    [{...base, jurisdiction: 'oregon'}, /jurisdiction/], [{...base, region: 'southern-california'}, /region/], [{...base, species_key: 'unicorn'}, /species_key/],
    [{...base, source_url: 'http://wildlife.ca.gov/x'}, /https/], [{...base, source_url: 'https://example.com/rules'}, /authority hosts/],
    [{...base, season_open: '04-01'}, /together/], [{...base, season_open: '04-01', season_close: '13-01'}, /MM-DD/], [{...base, bag_limit: 2.5}, /whole number/],
    [{...base, size_min_in: -1}, /number/], [{...base, species_label: ''}, /species_label/], [{...base, source_name: undefined}, /source_name/], [{...base, phone: '1'}, /unknown field/],
  ];
  for (const [body, error] of bad) {
    const r = await call(worker, env, 'POST', '/api/admin/rules', body);
    assert.equal(r.status, 400, JSON.stringify(body));
    assert.match(r.body.error, error);
  }
  const v0 = version(sql);
  const made = await call(worker, env, 'POST', '/api/admin/rules', {...base, season_open: '04-01', season_close: '10-31', bag_notes: '  10 per person  '});
  assert.equal(made.status, 200, JSON.stringify(made.body));
  const rule = made.body.rule;
  assert.equal(rule.id, await ruleId(base));
  assert.deepEqual([rule.status, rule.reviewed_at, rule.review_due, rule.updated_by, rule.bag_notes, rule.due], ['active', iso(T0), '2026-10-31', ADMIN, '10 per person', false]);
  assert.ok(version(sql) > v0);
  assert.equal((await call(worker, env, 'POST', '/api/admin/rules', base)).status, 409);
  // The importer's id formula is the same one.
  const imported = importer.importRows(T0).find(r => r.species_key === 'lingcod' && r.jurisdiction === 'california-central');
  assert.equal(await ruleId(imported), imported.id);
  const quoted = await lookupRules(env.DB, {region: 'morro-bay', speciesKey: 'other', now: T0});
  assert.ok(quoted.some(r => r.species_label === 'Pacific sanddab' && !r.stale));
});

dbTest('edit: content fields only; reviewed_at now, review_due, status active, updated_by; an empty edit confirms; retire stops quoting; each bumps the pages version', async () => {
  const {sql, env, worker} = setup();
  const id = lingcodId();
  assert.equal((await lookupRules(env.DB, {region: 'morro-bay', speciesKey: 'lingcod', now: T0}))[0].stale, true, 'imported rows are stale until reviewed');
  for (const body of [{status: 'active'}, {jurisdiction: 'california-southern'}, {species_key: 'halibut'}, {review_due: '2030-01-01'}])
    assert.equal((await call(worker, env, 'POST', `/api/admin/rules/${id}`, body)).status, 400, JSON.stringify(body));
  assert.equal((await call(worker, env, 'POST', `/api/admin/rules/${id}`, {season_open: null})).status, 400, 'one season end alone (lingcod has both)');
  const v0 = version(sql);
  const edited = await call(worker, env, 'POST', `/api/admin/rules/${id}`, {bag_limit: 3, size_min_in: '24'});
  assert.equal(edited.status, 200, JSON.stringify(edited.body));
  const row = rowOf(sql, id);
  assert.deepEqual([row.bag_limit, row.size_min_in, row.status, row.reviewed_at, row.review_due, row.updated_by], [3, 24, 'active', iso(T0), '2026-12-31', ADMIN], 'due at the season end (31 Dec), sooner than 90 days');
  assert.ok(version(sql) > v0);
  const quoted = (await lookupRules(env.DB, {region: 'morro-bay', speciesKey: 'lingcod', now: T0}))[0];
  assert.deepEqual([quoted.stale, quoted.bag_limit], [false, 3], 'quotable without "double-check" now');

  // An empty edit is "checked, no change" on another row.
  const rockfish = importer.importRows(T0).find(r => r.jurisdiction === 'california-central' && r.species_key === 'rockfish').id;
  const before = rowOf(sql, rockfish);
  const confirmed = await call(worker, env, 'POST', `/api/admin/rules/${rockfish}`, {});
  assert.equal(confirmed.status, 200);
  const after = rowOf(sql, rockfish);
  assert.deepEqual([after.bag_limit, after.bag_notes, after.status, after.reviewed_at], [before.bag_limit, before.bag_notes, 'active', iso(T0)]);

  const v1 = version(sql);
  const retired = await call(worker, env, 'POST', `/api/admin/rules/${id}/retire`, {});
  assert.deepEqual([retired.status, retired.body.rule.status, rowOf(sql, id).updated_by], [200, 'retired', ADMIN]);
  assert.ok(version(sql) > v1);
  assert.ok(!(await lookupRules(env.DB, {region: 'morro-bay', speciesKey: 'lingcod', now: T0})).some(r => r.bag_limit === 3), 'never quoted again');
  const v2 = version(sql);
  assert.equal((await call(worker, env, 'POST', `/api/admin/rules/${id}/retire`, {})).status, 200);
  assert.equal(version(sql), v2, 'retiring twice changes nothing');
  for (const path of [`/api/admin/rules/${'f'.repeat(32)}`, '/api/admin/rules/not-an-id/retire']) assert.equal((await call(worker, env, 'POST', path, {})).status, 404, path);
});

// ---- the change-watch --------------------------------------------------------------------

test('changedSources reads only "changed" checks for the jurisdiction, with the link on an authority host and both fingerprints', () => {
  const regs = {jurisdiction_id: 'california-central', checks: {
    'rules-central': {status: 'changed', url: CDFW, content_sha256: 'a'.repeat(64)},
    'rules-gear': {status: 'unchanged', url: CDFW, content_sha256: 'b'.repeat(64)},
    'rules-ocean': {status: 'unavailable', url: CDFW},
    'rules-evil': {status: 'changed', url: 'https://evil.example/x', content_sha256: 'not a hash'},
  }, sources: {'rules-central': {name: 'CDFW Central Region rules', approved_content_sha256: 'c'.repeat(64)}}};
  assert.deepEqual(changedSources(regs, 'california-central'), [
    {id: 'rules-central', name: 'CDFW Central Region rules', url: CDFW, content_sha256: 'a'.repeat(64), approved_sha256: 'c'.repeat(64)},
    {id: 'rules-evil', name: null, url: null, content_sha256: null, approved_sha256: null},
  ]);
  assert.deepEqual(changedSources(regs, 'california-southern'), [], 'another jurisdiction’s feed');
  for (const nothing of [null, {}, {checks: 'x'}]) assert.deepEqual(changedSources(nothing, 'california-central'), []);
});

dbTest('rules-watch: a changed CDFW page puts the jurisdiction’s active rows into review and opens one review; repeats change nothing; a re-confirmation stands until the page changes again', async () => {
  const {sql, env} = setup();
  sql.prepare("UPDATE advisor_rules SET status='active', review_due='2027-01-01'").run();
  const active = () => sql.prepare("SELECT COUNT(*) AS n FROM advisor_rules WHERE jurisdiction='california-central' AND status='active'").get().n;
  const southern = sql.prepare("SELECT COUNT(*) AS n FROM advisor_rules WHERE jurisdiction='california-southern' AND status='active'").get().n;
  const central = active();
  assert.ok(central > 0 && southern > 0);

  // Nothing changed: nothing happens.
  let r = (await quiet(() => watchRuleSources(env, T0, {feeds: feedWith()}))).value;
  assert.deepEqual(r, {regions: 1, unread: 0, changed: 0, opened: 0, rows_marked: 0});
  assert.equal(active(), central);

  const v0 = version(sql);
  r = (await quiet(() => watchRuleSources(env, T0, {feeds: feedWith({'rules-central': 'a'.repeat(64)})}))).value;
  assert.deepEqual(r, {regions: 1, unread: 0, changed: 1, opened: 1, rows_marked: central});
  assert.equal(active(), 0, 'every active Central row is in review');
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM advisor_rules WHERE jurisdiction='california-southern' AND status='active'").get().n, southern, 'other jurisdictions untouched');
  assert.equal(sql.prepare("SELECT DISTINCT updated_by FROM advisor_rules WHERE jurisdiction='california-central'").get().updated_by, 'rule-watch');
  assert.ok(version(sql) > v0, 'the species pages show "under review"');
  const ref = await changeRef('california-central', [{id: 'rules-central', content_sha256: 'a'.repeat(64)}]);
  const review = sql.prepare("SELECT * FROM advisor_reviews WHERE kind='rule'").all();
  assert.equal(review.length, 1);
  assert.deepEqual([review[0].id, review[0].ref_id, review[0].reason, review[0].status], [await reviewId('rule', ref, 'rule_source_changed'), ref, 'rule_source_changed', 'open']);
  const finding = JSON.parse(sql.prepare('SELECT value FROM job_state WHERE key=?').get(CHANGE_PREFIX + ref).value);
  assert.deepEqual([finding.jurisdiction, finding.regions, finding.sources[0].url, finding.sources[0].content_sha256, finding.rows_marked], ['california-central', ['morro-bay'], CDFW, 'a'.repeat(64), central]);
  assert.match(finding.sources[0].approved_sha256, /^[0-9a-f]{64}$/);
  assert.equal(JSON.parse(sql.prepare('SELECT value FROM job_state WHERE key=?').get(LAST_WATCH_KEY).value).changed, 1);

  // The admin re-confirms a row; the same finding the next day neither re-marks it nor opens a second review.
  const lingcod = lingcodId();
  sql.prepare("UPDATE advisor_rules SET status='active' WHERE id=?").run(lingcod);
  r = (await quiet(() => watchRuleSources(env, T0 + DAY, {feeds: feedWith({'rules-central': 'a'.repeat(64)})}))).value;
  assert.deepEqual([r.opened, r.rows_marked, rowOf(sql, lingcod).status], [0, 0, 'active']);
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM advisor_reviews WHERE kind='rule'").get().n, 1);

  // The page changes again: a new finding, a new review, the row back in review.
  r = (await quiet(() => watchRuleSources(env, T0 + 2 * DAY, {feeds: feedWith({'rules-central': 'd'.repeat(64)})}))).value;
  assert.deepEqual([r.opened, r.rows_marked, rowOf(sql, lingcod).status], [1, 1, 'review']);
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM advisor_reviews WHERE kind='rule'").get().n, 2);

  // A feed for another jurisdiction, or none at all, changes nothing.
  r = (await quiet(() => watchRuleSources(env, T0, {feeds: feedWith({'rules-central': 'e'.repeat(64)}, {jurisdiction_id: 'california-southern'})}))).value;
  assert.equal(r.changed, 0);
  r = (await quiet(() => watchRuleSources(env, T0, {feeds: async () => { throw Error('down'); }}))).value;
  assert.deepEqual([r.unread, r.changed], [1, 0]);
});

dbTest('the queue shows a rule-change item with the changed page, its fingerprints and the rows in review; Done closes it', async () => {
  const {sql, env, worker} = setup();
  sql.prepare("UPDATE advisor_rules SET status='active'").run();
  await quiet(() => watchRuleSources(env, T0, {feeds: feedWith({'rules-central': 'a'.repeat(64)})}));
  const {body} = await call(worker, env, 'GET', '/api/admin/reviews?kind=rule');
  assert.equal(body.items.length, 1);
  const s = body.items[0].detail.summary;
  assert.equal(body.items[0].detail.rule, null);
  assert.deepEqual([s.jurisdiction, s.sources.map(x => [x.id, x.url]), s.rules.active], ['california-central', [['rules-central', CDFW]], 0]);
  assert.ok(s.rules.review > 0);
  assert.equal((await call(worker, env, 'POST', `/api/admin/reviews/${body.items[0].id}`, {decision: 'edit'})).status, 400, 'rules are edited in the Rules view');
  const done = await call(worker, env, 'POST', `/api/admin/reviews/${body.items[0].id}`, {decision: 'approve'});
  assert.equal(done.body.review.status, 'approved');
});

dbTest('the rules-watch slot runs once a local day at 06:15 from advisorCron, with the daily feeds', async () => {
  const {sql, env} = setup();
  sql.prepare("UPDATE advisor_rules SET status='active'").run();
  const deps = {slots: undefined, daily: {feeds: feedWith({'rules-central': 'a'.repeat(64)}), fetcher: async () => { throw Error('no model in this test'); }}};
  const day = '2026-10-05', ran = [];
  for (let tick = Date.parse(`${day}T12:00:00Z`); tick < Date.parse(`${day}T15:00:00Z`); tick += 15 * 60000) {
    await quiet(() => advisorCron({...env}, tick, deps));
    if (sql.prepare("SELECT COUNT(*) AS n FROM advisor_reviews WHERE kind='rule'").get().n && !ran.length) ran.push(iso(tick));
  }
  assert.deepEqual(ran, ['2026-10-05T13:15:00.000Z'], '06:15 PDT');
  assert.equal(sql.prepare('SELECT value FROM job_state WHERE key=?').get(SLOT_PREFIX + 'rules-watch').value, day);
});

test('the admin app routes #rules?jurisdiction=<id> to the Rules view on that jurisdiction', () => {
  assert.deepEqual(routeOf('#rules?jurisdiction=california-central'), {view: 'rules', arg: 'california-central'});
  assert.deepEqual(routeOf('#rules'), {view: 'rules', arg: ''});
  assert.deepEqual(routeOf('#rules?jurisdiction=%3Cscript%3E'), {view: 'rules', arg: ''});
  assert.equal(rulesHref('california-central'), '#rules?jurisdiction=california-central');
});
