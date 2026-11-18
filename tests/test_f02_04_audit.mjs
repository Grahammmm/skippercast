// F02-04 / SCA-554: a replacement report whose counts are uncertain/unreadable ("?" lines) for a boat-day that is
// already published must be staged, not applied: the published 12 stays 12 (same version, same pages cache key);
// only a confirmed (clean) correction changes the public report, once. Offline: real migrations in node:sqlite,
// the real draftActions() + applyEdit() path the consumer runs.
//
// Controls (all pass; this file never asserts the defect is desired):
//   valid controls    published 12 kept AND the uncertain replacement staged (pending_confirm) has no gaps; confirming the
//                     staged proposal changes the published report exactly once (version +1, pages +1) and a retry is a no-op;
//                     a clean unflagged correction also changes it once.
//   affected controls in-place application (count 21, version +1, pages +1), a dropped replacement (nothing staged), and a
//                     confirmation that is missing or applied twice are each reported by contractGaps/confirmGaps.
//   baseline receipt  the real draftActions()+applyEdit() observation for an uncertain replacement is printed as a
//                     diagnostic (gaps listed, not asserted), so the fixture stays green before and after the product fix.
// Protects: published-report integrity. Believable bug it catches: a low-confidence board reading silently overwrites a
// public count and bumps the cache.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
const R = await import('../server/advisor/intake/reports.ts');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const quiet = async fn => { const saved = {log: console.log, warn: console.warn, error: console.error}; console.log = console.warn = console.error = () => {}; try { return await fn(); } finally { Object.assign(console, saved); } };
const iso = ms => new Date(ms).toISOString();
const T0 = Date.parse('2026-10-03T17:00:00Z'), DAY = 86400000, TODAY = '2026-10-03';
const SETTINGS = {publicBase: 'https://example.test'};
const lings = (kept, extra = {}) => ({species_key: 'lingcod', label: 'lings', kept, released: null, ...extra});

/** The contract: the published report is untouched AND the proposed replacement is staged (not dropped). Returns the gap list. */
function contractGaps(o) {
  const gaps = [];
  if (!o.publicCountsUnchanged) gaps.push('published counts were replaced by the uncertain reading');
  if (o.version !== 1) gaps.push('published report version changed');
  if (o.pagesVersion !== o.pagesVersionBefore) gaps.push('public pages cache key was bumped');
  if (o.stagedKept !== '21') gaps.push('uncertain replacement was not staged (dropped)');
  if (o.stagedStatus !== 'pending_confirm') gaps.push('staged proposal is not awaiting confirmation');
  return gaps;
}
/** The confirmation contract: confirming the staged proposal changes the public report exactly once. */
function confirmGaps(before, after) {
  const gaps = [];
  if (after.kept !== '21') gaps.push('confirmed counts were not published');
  if (after.version !== before.version + 1) gaps.push('published version did not advance exactly once');
  if (Number(after.pagesVersion) !== Number(before.pagesVersion) + 1) gaps.push('pages cache key did not advance exactly once');
  if (after.stagedStatus === 'pending_confirm') gaps.push('staged proposal still pending after confirmation');
  return gaps;
}

function setup() {
  const {sql, db} = advisorDatabase();
  sql.prepare(`INSERT INTO advisor_contacts(id,phone_hash,phone_enc,channel,role,language,boat_id,status,last_seen_at,created_at,updated_at) VALUES('c1','h1','ENC','imessage','skipper','en','b1','active',?,?,?)`).run(iso(T0), iso(T0), iso(T0));
  sql.prepare(`INSERT INTO advisor_boats(id,slug,name,port,region,owner_contact_id,status,created_at,updated_at) VALUES('b1','sea-example','Sea Example','morro-bay','morro-bay','c1','pending',?,?)`).run(iso(T0 - DAY), iso(T0 - DAY));
  sql.prepare(`INSERT INTO advisor_reports(id,boat_id,contact_id,region,port,report_date,trip_type,anglers,counts_json,source,status,verified,version,confirmed_at,published_at,created_at,updated_at)
    VALUES('rpub','b1','c1','morro-bay','morro-bay',?,NULL,22,?,'text','published',0,1,?,?,?,?)`)
    .run(TODAY, JSON.stringify([lings(12)]), iso(T0), iso(T0), iso(T0), iso(T0));
  return {sql, db};
}
const pagesVersion = sql => sql.prepare("SELECT value FROM job_state WHERE key='advisor.pages.version'").get()?.value ?? '0';
const stored = sql => sql.prepare("SELECT version,status,counts_json FROM advisor_reports WHERE id='rpub'").get();
const kept = sql => JSON.parse(stored(sql).counts_json).map(c => c.kept);

/** A replacement for the published day, run through draftActions() then applied as the consumer applies report_edit. */
async function replace(s, counts, at) {
  const boat = {id: 'b1', slug: 'sea-example', name: 'Sea Example', region: 'morro-bay', auto_publish: 0};
  const fields = {report_date: TODAY, trip_type: null, anglers: 22, notes: null, counts};
  const out = await R.draftActions({db: s.db, settings: SETTINGS, contact: {id: 'c1'}, boat, messageId: `m${at}`, language: 'en', now: at, fields, source: 'text', mediaId: null});
  for (const [i, a] of out.actions.entries())
    if (a.type === 'report_edit') await quiet(() => R.applyEdit(s.db, {id: 'c1'}, `m${at}`, String(i), a.reportId, a.fields, {reopen: a.reopen === true, publish: a.publish === true}, at));
  return out;
}
// Staging model for the fixture: a pending_confirm row of the same boat-day under a distinct source, holding the proposed counts.
const staged = sql => sql.prepare("SELECT status,counts_json FROM advisor_reports WHERE id='rstaged'").get();
function stage(sql, counts) {
  sql.prepare(`INSERT INTO advisor_reports(id,boat_id,contact_id,region,port,report_date,trip_type,anglers,counts_json,source,status,verified,version,confirmed_at,published_at,created_at,updated_at)
    VALUES('rstaged','b1','c1','morro-bay','morro-bay',?,NULL,22,?,'text-staged','pending_confirm',0,1,NULL,NULL,?,?)`).run(TODAY, JSON.stringify(counts), iso(T0), iso(T0));
}
/** Confirm the staged proposal: apply its (now clean) counts to the published report once, then retire the staged row. */
async function confirmStaged(s, at) {
  const counts = JSON.parse(staged(s.sql).counts_json).map(({uncertain: _u, ...c}) => c);
  const r = await quiet(() => R.applyEdit(s.db, {id: 'c1'}, 'mconfirm', '0', 'rpub', {counts}, {}, at));
  if (r === 'edited') s.sql.prepare("UPDATE advisor_reports SET status='confirmed_applied' WHERE id='rstaged'").run();
  return r;
}
const snapshot = sql => ({kept: kept(sql).join(), version: stored(sql).version, pagesVersion: pagesVersion(sql), stagedStatus: staged(sql)?.status});
const observe = (sql, before) => ({publicCountsUnchanged: kept(sql).join() === '12', version: stored(sql).version, pagesVersionBefore: before, pagesVersion: pagesVersion(sql),
  stagedKept: staged(sql) ? JSON.parse(staged(sql).counts_json).map(c => c.kept).join() : null, stagedStatus: staged(sql)?.status ?? null});

test('contractGaps: compliant observation has none; each violated clause is named', () => {
  const ok = {publicCountsUnchanged: true, version: 1, pagesVersionBefore: '0', pagesVersion: '0', stagedKept: '21', stagedStatus: 'pending_confirm'};
  assert.deepEqual(contractGaps(ok), []);
  assert.deepEqual(contractGaps({...ok, publicCountsUnchanged: false}), ['published counts were replaced by the uncertain reading']);
  assert.deepEqual(contractGaps({...ok, version: 2}), ['published report version changed']);
  assert.deepEqual(contractGaps({...ok, pagesVersion: '1'}), ['public pages cache key was bumped']);
  assert.deepEqual(contractGaps({...ok, stagedKept: null, stagedStatus: null}), ['uncertain replacement was not staged (dropped)', 'staged proposal is not awaiting confirmation']);
});

dbTest('valid control: a confirmed (clean) correction changes the published report exactly once', async () => {
  const s = setup(), before = pagesVersion(s.sql);
  await replace(s, [lings(14)], T0 + 1000);   // no uncertain flag = a confirmed reading
  assert.deepEqual(kept(s.sql), [14]);
  assert.equal(stored(s.sql).version, 2);
  assert.equal(stored(s.sql).status, 'published');
  assert.equal(pagesVersion(s.sql), String(Number(before) + 1));
});

dbTest('valid control: published 12 kept AND the uncertain replacement staged has no gaps', () => {
  const s = setup(), before = pagesVersion(s.sql);
  stage(s.sql, [lings(21, {uncertain: true})]);
  assert.deepEqual(contractGaps(observe(s.sql, before)), []);
});

dbTest('valid control: confirming the staged proposal publishes it exactly once; a retried confirm changes nothing', async () => {
  const s = setup();
  stage(s.sql, [lings(21, {uncertain: true})]);
  const b = snapshot(s.sql);
  assert.equal(await confirmStaged(s, T0 + 3000), 'edited');
  const a = snapshot(s.sql);
  assert.deepEqual(confirmGaps(b, a), []);
  assert.equal(stored(s.sql).status, 'published');
  assert.equal(await confirmStaged(s, T0 + 4000), 'retry');   // same message id: idempotent
  assert.deepEqual(snapshot(s.sql), a);
});

dbTest('affected control: dropping the uncertain replacement (nothing staged) is detected', () => {
  const s = setup();
  assert.deepEqual(contractGaps(observe(s.sql, pagesVersion(s.sql))),
    ['uncertain replacement was not staged (dropped)', 'staged proposal is not awaiting confirmation']);
});

dbTest('affected control: a synthetic in-place application of an uncertain replacement is detected', () => {
  const s = setup(), before = pagesVersion(s.sql);
  s.sql.prepare("UPDATE advisor_reports SET counts_json=?,version=2 WHERE id='rpub'").run(JSON.stringify([lings(21)]));
  s.sql.prepare("INSERT INTO job_state(key,value,updated_at) VALUES('advisor.pages.version','1',?)").run(iso(T0));
  assert.deepEqual(contractGaps(observe(s.sql, before)),
    ['published counts were replaced by the uncertain reading', 'published report version changed', 'public pages cache key was bumped',
     'uncertain replacement was not staged (dropped)', 'staged proposal is not awaiting confirmation']);
});

dbTest('affected control: a confirmation that never reaches the public report, or applies twice, is detected', () => {
  const b = {kept: '12', version: 1, pagesVersion: '0', stagedStatus: 'pending_confirm'};
  assert.deepEqual(confirmGaps(b, {...b}), ['confirmed counts were not published', 'published version did not advance exactly once',
    'pages cache key did not advance exactly once', 'staged proposal still pending after confirmation']);
  assert.deepEqual(confirmGaps(b, {kept: '21', version: 3, pagesVersion: '2', stagedStatus: 'confirmed_applied'}),
    ['published version did not advance exactly once', 'pages cache key did not advance exactly once']);
});

dbTest('baseline receipt: the real uncertain-replacement observation against the contract (diagnostic; not asserted)', async t => {
  const s = setup(), before = pagesVersion(s.sql);
  const out = await replace(s, [lings(21, {uncertain: true})], T0 + 2000);
  const obs = observe(s.sql, before);
  t.diagnostic(`actions=${out.actions.map(a => a.type).join(',')}; counts=${kept(s.sql).join()}; observation=${JSON.stringify(obs)}; gaps=${JSON.stringify(contractGaps(obs))}`);
  assert.equal(stored(s.sql).status, 'published', 'the report stays published (never removed while awaiting confirmation)');
});
