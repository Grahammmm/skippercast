import test, {beforeEach, afterEach, after} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {installOffline, restorePreload} from './fixtures/sp1407_daily_window/bootstrap.mjs';
// Bootstrap has already installed sentinels, before any complete product module.
const {advisorDatabase, sqliteUnavailable} = await import('./_advisor_d1.mjs');
if (sqliteUnavailable) throw new Error(sqliteUnavailable); // no skip fallback
const daily = await import('../server/advisor/answers/reports.ts');
const {localDate} = await import('../server/advisor/answers/time.ts');
const {planningBrief} = await import('../server/advisor/answers/planning.ts');
const F = JSON.parse(readFileSync(new URL('./fixtures/sp1407_daily_window/cases.json', import.meta.url), 'utf8'));
const NOW = Date.parse('2026-10-25T19:00:00Z');
const noModel = () => { throw new Error('SP1407_MODEL_FORBIDDEN'); };
const feeds = async url => {
  if (/intelligence\.json$/.test(url)) return structuredClone(F.intelligence);
  if (/latest\.json$/.test(url)) return structuredClone(F.daily);
  throw new Error('SP1407_UNKNOWN_FEED');
};
const deps = {feeds, fetcher: noModel, clock: () => NOW};
let restore, databases;
beforeEach(() => { restore = installOffline(); databases = []; });
afterEach(() => { for (const sql of databases) sql.close(); restore(); });
after(() => restorePreload());
function setup() {
  const {sql, db} = advisorDatabase();
  databases.push(sql);
  const at = '2026-10-01T00:00:00Z';
  sql.prepare(`INSERT INTO advisor_contacts(id,phone_hash,phone_enc,channel,role,language,status,last_seen_at,created_at,updated_at)
    VALUES('synthetic-owner','synthetic-hash','ENC','imessage','skipper','en','active',?,?,?)`).run(at, at, at);
  sql.prepare(`INSERT INTO advisor_boats(id,slug,name,landing,port,region,owner_contact_id,status,created_at,updated_at)
    VALUES('synthetic-boat','synthetic-boat','Synthetic Boat','Example Landing','morro-bay','morro-bay','synthetic-owner','verified',?,?)`).run(at, at);
  return {sql, env: {DB: db}}; // no model key, R2, live DB or storage binding
}
function report(sql, id, date, {status = 'published', port = 'morro-bay', verified = 1} = {}) {
  sql.prepare(`INSERT INTO advisor_reports(id,boat_id,region,port,report_date,trip_type,anglers,counts_json,source,status,verified,published_at,created_at,updated_at)
    VALUES(?,'synthetic-boat','morro-bay',?,?,'full-day',2,?,?,?,?,?,?,?)`)
    .run(id, port, date, JSON.stringify(F.counts), `synthetic-${id}`, status, verified,
      status === 'published' ? `${date}T19:00:00Z` : null, '2026-10-01T00:00:00Z', '2026-10-01T00:00:00Z');
}
const inputs = (env, date = F.answer_date, now = NOW) => daily.dailyInputs(env, 'morro-bay', date, deps, now);
// Baseline registers exactly this pair; no --test-name-pattern and no skips.
test('primary regression', async () => {
  const {sql, env} = setup();
  for (const date of F.dates) report(sql, date, date);
  const actual = await inputs(env);
  assert.deepEqual(actual.skipper_reports.map(r => r.date), F.expected, 'SP1407_THREE_CALENDAR_DATES');
  assert.deepEqual(actual.skipper_reports.map(r => r.id), F.expected);
});
test('healthy control', async () => {
  const {sql, env} = setup();
  report(sql, 'boundary', '2026-10-23');
  report(sql, 'draft', '2026-10-23', {status: 'draft'});
  report(sql, 'pending', '2026-10-23', {status: 'pending_confirm'});
  report(sql, 'other', '2026-10-23', {port: 'port-san-luis'});
  assert.deepEqual((await inputs(env)).skipper_reports.map(r => r.id), ['boundary']);
});
if (process.env.SP1407_SUITE !== 'baseline') {
  test('A2 today, boundary, anonymity, filters and empty fallback', async () => {
    const {sql, env} = setup();
    report(sql, 'today', F.answer_date);
    report(sql, 'anonymous', '2026-10-23', {verified: 0});
    report(sql, 'draft', F.answer_date, {status: 'draft'});
    report(sql, 'other', F.answer_date, {port: 'port-san-luis'});
    const actual = await inputs(env);
    assert.deepEqual(actual.skipper_reports.map(r => [r.id, r.boat, r.verified]), [['today', 'Synthetic Boat', true], ['anonymous', 'a boat', false]]);
    const empty = setup();
    report(empty.sql, 'old', '2026-10-22');
    assert.equal(daily.composeDaily(await inputs(empty.env), 'en'), "No reports from the last three days for Morro Bay yet. Today's forecast isn't in yet.");
    const answer = await daily.dailyAnswer(empty.env, 'morro-bay', F.answer_date, 'en', deps, {generate: false});
    assert.equal(answer.source, 'composed');
    assert.equal(answer.text, daily.composeDaily(await inputs(empty.env), 'en'));
    assert.equal(empty.sql.prepare('SELECT count(*) n FROM advisor_daily_answers').get().n, 0);
  });
  for (const c of F.boundaries) test(`A3 calendar boundary: ${c.name}`, async () => {
    const {sql, env} = setup();
    const now = Date.parse(c.now);
    assert.equal(localDate(now, 'America/Los_Angeles'), c.today);
    for (const date of c.dates) report(sql, date, date);
    assert.deepEqual((await inputs(env, localDate(now, 'America/Los_Angeles'), now)).skipper_reports.map(r => r.date), c.expected);
  });
  test('A3 hash identity/version recompute and unchanged eight-row ordering cap', async () => {
    const {sql, env} = setup();
    for (const id of ['j','i','h','g','f','e','d','c','b','a']) report(sql, id, F.answer_date);
    report(sql, 'older', '2026-10-24');
    const actual = await inputs(env);
    assert.deepEqual(actual.skipper_reports.map(r => r.id), ['a','b','c','d','e','f','g','h']);
    const h1 = await daily.currentInputsHash(env, 'morro-bay', F.answer_date, deps, NOW);
    assert.equal(h1, createHash('sha256').update(JSON.stringify(actual)).digest('hex'));
    assert.equal(await daily.currentInputsHash(env, 'morro-bay', F.answer_date, deps, NOW), h1);
    report(sql, 'old', '2026-10-22');
    report(sql, 'future', '2026-10-26');
    report(sql, 'draft', F.answer_date, {status: 'draft'});
    assert.equal(await daily.currentInputsHash(env, 'morro-bay', F.answer_date, deps, NOW), h1);
    sql.prepare("UPDATE advisor_reports SET version=2 WHERE id='a'").run();
    assert.equal((await inputs(env)).skipper_reports[0].version, 2);
    const h2 = await daily.currentInputsHash(env, 'morro-bay', F.answer_date, deps, NOW);
    assert.notEqual(h2, h1);
    const a = await daily.dailyAnswer(env, 'morro-bay', F.answer_date, 'en', deps, {generate: false});
    assert.equal(a.inputs_hash, h2);
    // Stored synthetic stale identity forces a fresh composition, never a model.
    sql.prepare('INSERT INTO advisor_daily_answers(key,text_en,text_es,inputs_hash,generated_at) VALUES(?,?,?,?,?)')
      .run(`morro-bay:${F.answer_date}`, 'old', 'old-es', h1, '2026-10-25T00:00:00Z');
    assert.equal((await daily.dailyAnswer(env, 'morro-bay', F.answer_date, 'en', deps, {generate: false})).source, 'composed');
    sql.prepare('UPDATE advisor_daily_answers SET inputs_hash=?').run(h2);
    assert.equal((await daily.dailyAnswer(env, 'morro-bay', F.answer_date, 'en', deps, {generate: false})).source, 'cache');
  });
  test('A3 downstream planning uses corrected daily inputs, not the future or fourth date', async () => {
    const {sql, env} = setup();
    for (const date of F.dates) report(sql, date, date);
    const out = await planningBrief(env, {port: 'morro-bay', date: 'today', species: 'rockfish'}, {now: NOW, language: 'en', deps: {feeds}});
    assert.equal(out.error, undefined);
    assert.deepEqual(out.planning.recent_activity.skipper_reports.map(r => r.date), F.expected);
    assert.deepEqual(out.planning.recent_activity.skipper_reports.map(r => r.boat), ['Synthetic Boat', 'Synthetic Boat', 'Synthetic Boat']);
  });
  test('offline network, model and storage controls are active', () => {
    assert.throws(() => fetch('https://synthetic.invalid'), /SP1407_OFFLINE_SIDE_EFFECT/);
    assert.throws(() => caches.open('synthetic'), /SP1407_OFFLINE_SIDE_EFFECT/);
    assert.throws(() => localStorage.setItem('synthetic', 'x'), /SP1407_OFFLINE_SIDE_EFFECT/);
    assert.throws(noModel, /SP1407_MODEL_FORBIDDEN/);
  });
}
