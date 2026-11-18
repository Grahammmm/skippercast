// F02-04 / SCA-554: a replacement report whose counts are uncertain/unreadable ("?" lines) for a boat-day that is
// already published must be staged, not applied: the published 12 stays 12 (same version, same pages cache key);
// only a confirmed (clean) correction changes the public report, once. Offline: real migrations in node:sqlite,
// the real draftActions() + applyEdit() path the consumer runs.
//
// Controls (all pass; this file never asserts the defect is desired):
//   valid control     an observation that kept the published 12 (version, pages version unchanged) has no gaps; a clean
//                     confirmed correction really changes the published report exactly once (version +1, pages +1).
//   affected control  a synthetic observation where the uncertain replacement was applied in place (count 21, version +1,
//                     pages version +1) is reported by `contractGaps`.
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

/** The contract: the published report after an uncertain replacement is untouched. Returns the gap list. */
function contractGaps(o) {
  const gaps = [];
  if (!o.publicCountsUnchanged) gaps.push('published counts were replaced by the uncertain reading');
  if (o.version !== 1) gaps.push('published report version changed');
  if (o.pagesVersion !== o.pagesVersionBefore) gaps.push('public pages cache key was bumped');
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
const observe = (sql, before) => ({publicCountsUnchanged: kept(sql).join() === '12', version: stored(sql).version, pagesVersionBefore: before, pagesVersion: pagesVersion(sql)});

test('contractGaps: compliant observation has none; each violated clause is named', () => {
  const ok = {publicCountsUnchanged: true, version: 1, pagesVersionBefore: '0', pagesVersion: '0'};
  assert.deepEqual(contractGaps(ok), []);
  assert.deepEqual(contractGaps({...ok, publicCountsUnchanged: false}), ['published counts were replaced by the uncertain reading']);
  assert.deepEqual(contractGaps({...ok, version: 2}), ['published report version changed']);
  assert.deepEqual(contractGaps({...ok, pagesVersion: '1'}), ['public pages cache key was bumped']);
});

dbTest('valid control: a confirmed (clean) correction changes the published report exactly once', async () => {
  const s = setup(), before = pagesVersion(s.sql);
  await replace(s, [lings(14)], T0 + 1000);   // no uncertain flag = a confirmed reading
  assert.deepEqual(kept(s.sql), [14]);
  assert.equal(stored(s.sql).version, 2);
  assert.equal(stored(s.sql).status, 'published');
  assert.equal(pagesVersion(s.sql), String(Number(before) + 1));
});

dbTest('valid control: an observation that kept the published 12 has no gaps', () => {
  const s = setup();
  assert.deepEqual(contractGaps(observe(s.sql, pagesVersion(s.sql))), []);
});

dbTest('affected control: a synthetic in-place application of an uncertain replacement is detected', () => {
  const s = setup(), before = pagesVersion(s.sql);
  s.sql.prepare("UPDATE advisor_reports SET counts_json=?,version=2 WHERE id='rpub'").run(JSON.stringify([lings(21)]));
  s.sql.prepare("INSERT INTO job_state(key,value,updated_at) VALUES('advisor.pages.version','1',?)").run(iso(T0));
  assert.deepEqual(contractGaps(observe(s.sql, before)),
    ['published counts were replaced by the uncertain reading', 'published report version changed', 'public pages cache key was bumped']);
});

dbTest('baseline receipt: the real uncertain-replacement observation against the contract (diagnostic; not asserted)', async t => {
  const s = setup(), before = pagesVersion(s.sql);
  const out = await replace(s, [lings(21, {uncertain: true})], T0 + 2000);
  const obs = observe(s.sql, before);
  t.diagnostic(`actions=${out.actions.map(a => a.type).join(',')}; counts=${kept(s.sql).join()}; observation=${JSON.stringify(obs)}; gaps=${JSON.stringify(contractGaps(obs))}`);
  assert.equal(stored(s.sql).status, 'published', 'the report stays published (never removed while awaiting confirmation)');
});
