// F02-08 / SCA-576: unavailable Facebook engagement must not become a measured zero. Contract:
//   - availability is kept per metric;
//   - a count failure after a good reading keeps the last measured value (and its time), flagged stale;
//   - a first failure shows "unavailable" (null), never numeric 0;
//   - a genuine later measured zero replaces an earlier positive value.
// Offline: real migrations in node:sqlite and the real readFacebook/saveReading/postStats with a recorded Graph API.
//
// Controls (all pass; this file never asserts the defect is desired):
//   valid control     a synthetic store that keeps per-metric availability meets the contract (no gaps).
//   affected control  a synthetic store that writes zeros for a failed count call is reported with each gap.
//   baseline receipt  the real code's observation is printed as a diagnostic (gaps listed, not asserted), so this file
//                     stays green before and after the product fix. The real measured-zero case is asserted.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
const I = await import('../server/advisor/social/insights.ts');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const fixture = name => read(`./fixtures/advisor/meta/${name}.json`);
const jsonResponse = (body, status = 200) => new Response(JSON.stringify(body), {status, headers: {'content-type': 'application/json'}});
const quiet = async fn => { const saved = {log: console.log, warn: console.warn, error: console.error}; console.log = console.warn = console.error = () => {}; try { return await fn(); } finally { Object.assign(console, saved); } };
const iso = ms => new Date(ms).toISOString();
const T0 = Date.parse('2026-10-05T18:00:00Z'), HOUR = 3600000, DAY = 86400000;
const PAGE = '100000000000001', FB_POST = '100000000000001_200000000000001';
const POSITIVE = {likes: 57, comments: 6, shares: 4};

/** Recorded Graph API for one Page post: reach always answers; the count call answers `counts`, or fails when 'fail'. */
function graph(counts) {
  return async url => {
    const u = new URL(url), edge = u.pathname.split('/')[3];
    if (edge === 'insights') return jsonResponse(fixture('fb-post-insights'));
    if (counts === 'fail') return jsonResponse({error: {code: 190, message: 'synthetic count failure'}}, 400);
    return jsonResponse({shares: {count: counts.shares}, reactions: {summary: {total_count: counts.likes}}, comments: {summary: {total_count: counts.comments}}, id: FB_POST});
  };
}

/** A store is {record(at, counts), latest()}; latest() is {likes: {value, stale, measuredAt}} with value null when unavailable. */
function realStore() {
  const {sql, db} = advisorDatabase();
  sql.prepare(`INSERT INTO advisor_posts(id,kind,region,media_json,caption,targets_json,status,fb_post_id,created_by,posted_at,created_at,updated_at)
    VALUES('p1','photo','morro-bay','[]','c','["facebook"]','posted',?,'engine',?,?,?)`).run(FB_POST, iso(T0 - DAY), iso(T0 - DAY), iso(T0 - DAY));
  return {
    async record(at, counts) {
      const cfg = {token: 'EAAB-PLACEHOLDER-TOKEN', appSecret: 'app-secret-PLACEHOLDER', fetcher: graph(counts), sleep: async () => {}};
      const reading = await quiet(() => I.readFacebook(cfg, FB_POST));
      if (reading) await I.saveReading(db, 'p1', 'facebook', reading, at);
    },
    async latest() {
      const fb = (await I.postStats(db, {id: 'p1', ig_media_id: null})).facebook;
      // The real reader exposes only numbers and notes: a count-failure note is the only hint it offers.
      return {likes: {value: fb.likes, stale: fb.notes.some(n => n.startsWith('counts:')), measuredAt: fb.fetched_at}};
    },
  };
}

/** The contract's valid behaviour, as a synthetic store with per-metric availability. */
function compliantStore() {
  let likes = {value: null, stale: false, measuredAt: null};
  return {
    async record(at, counts) { likes = counts === 'fail' ? {...likes, stale: likes.value !== null} : {value: counts.likes, stale: false, measuredAt: iso(at)}; },
    async latest() { return {likes: {...likes}}; },
  };
}
/** The defect: a failed count call is written as measured zeros over whatever was stored. */
function zeroingStore() {
  let likes = {value: null, stale: false, measuredAt: null};
  return {
    async record(at, counts) { likes = {value: counts === 'fail' ? 0 : counts.likes, stale: false, measuredAt: iso(at)}; },
    async latest() { return {likes: {...likes}}; },
  };
}

const GAP = {
  stale: 'a count failure after a good reading did not keep the last measured likes, flagged stale',
  first: 'a first count failure is not shown as unavailable (null)',
  zero: 'a genuine measured zero did not replace the earlier positive value',
};
/** The contract over a store: three scenarios, each on its own store from `make`. */
async function contractGaps(make) {
  const gaps = [];
  const a = make(); await a.record(T0, POSITIVE); await a.record(T0 + HOUR, 'fail');   // a same-day repeat, as the issue describes
  const stale = (await a.latest()).likes;
  if (stale.value !== POSITIVE.likes || !stale.stale || stale.measuredAt !== iso(T0)) gaps.push(GAP.stale);
  const b = make(); await b.record(T0, 'fail');
  if ((await b.latest()).likes.value !== null) gaps.push(GAP.first);
  const c = make(); await c.record(T0, POSITIVE); await c.record(T0 + DAY, {likes: 0, comments: 0, shares: 0});
  if ((await c.latest()).likes.value !== 0) gaps.push(GAP.zero);
  return gaps;
}

test('valid control: a store with per-metric availability has no gaps', async () => {
  assert.deepEqual(await contractGaps(compliantStore), []);
});

test('affected control: a store that writes zeros for a failed count call is reported with the stale and unavailable gaps', async () => {
  assert.deepEqual(await contractGaps(zeroingStore), [GAP.stale, GAP.first]);
});

dbTest('real code: a measured zero on a later day replaces the earlier positive value (a true zero is meaningful)', async () => {
  const s = realStore();
  await s.record(T0, POSITIVE);
  assert.equal((await s.latest()).likes.value, 57);
  await s.record(T0 + DAY, {likes: 0, comments: 0, shares: 0});
  assert.equal((await s.latest()).likes.value, 0);
});

dbTest('baseline receipt: the real reading/stat read-back observed against the contract (diagnostic; not asserted)', async t => {
  const gaps = await contractGaps(realStore);
  const s = realStore(); await s.record(T0, POSITIVE); await s.record(T0 + HOUR, 'fail');
  const f = realStore(); await f.record(T0, 'fail');
  t.diagnostic(`after good then failed count (same day): ${JSON.stringify(await s.latest())}; first failure: ${JSON.stringify(await f.latest())}; gaps=${JSON.stringify(gaps)}`);
  for (const gap of gaps) assert.ok(Object.values(GAP).includes(gap));
});
