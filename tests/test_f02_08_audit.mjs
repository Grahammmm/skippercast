// F02-08 / SCA-576: unavailable Facebook engagement must not become a measured zero. Contract (for each of likes, comments, shares):
//   - availability is kept per metric;
//   - a count failure after a good reading keeps the last measured value (and its time), flagged stale;
//   - a first failure shows "unavailable" (null), never numeric 0;
//   - a genuine later measured zero replaces an earlier positive value;
//   - in a mixed reading (one metric fails, others measured) each metric is kept/flagged/replaced on its own.
// Offline: real migrations in node:sqlite and the real readFacebook/saveReading/postStats with a recorded Graph API.
//
// Controls (all pass; this file never asserts the defect is desired):
//   valid control     a synthetic store that keeps per-metric availability meets the contract (no gaps).
//   affected control  a synthetic store that writes zeros for a failed count is reported with each gap
//                     (and a store wrong only for comments/shares is still detected).
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
const FB_POST = '100000000000001_200000000000001';
const METRICS = ['likes', 'comments', 'shares'];
const NOTE_NAME = {likes: 'reactions', comments: 'comments', shares: 'shares'};
const POS = {likes: 57, comments: 6, shares: 4};
const ZERO = {likes: 0, comments: 0, shares: 0};
/** A counts argument is 'fail' (the whole count call fails) or {likes, comments, shares}, each a number or 'fail' (that metric not returned). */
const metricOf = (counts, m) => counts === 'fail' ? 'fail' : counts[m];

/** Recorded Graph API for one Page post: reach always answers; the count call answers `counts`; a 'fail' metric is omitted. */
function graph(counts) {
  return async url => {
    const u = new URL(url), edge = u.pathname.split('/')[3];
    if (edge === 'insights') return jsonResponse(fixture('fb-post-insights'));
    if (counts === 'fail') return jsonResponse({error: {code: 190, message: 'synthetic count failure'}}, 400);
    const body = {id: FB_POST};
    if (counts.shares !== 'fail') body.shares = {count: counts.shares};
    if (counts.likes !== 'fail') body.reactions = {summary: {total_count: counts.likes}};
    if (counts.comments !== 'fail') body.comments = {summary: {total_count: counts.comments}};
    return jsonResponse(body);
  };
}

/** A store is {record(at, counts), latest()}; latest() is {likes|comments|shares: {value, stale, measuredAt}} with value null when unavailable. */
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
      // The real reader exposes only numbers and notes: a note is the only hint it offers for a failed count.
      return Object.fromEntries(METRICS.map(m => [m, {value: fb[m], stale: fb.notes.some(n => n.startsWith('counts:') || n.startsWith(`${NOTE_NAME[m]}:`)), measuredAt: fb.fetched_at}]));
    },
  };
}

const blank = () => Object.fromEntries(METRICS.map(m => [m, {value: null, stale: false, measuredAt: null}]));
/** The contract's valid behaviour, as a synthetic store with per-metric availability and measured times. */
function compliantStore() {
  const st = blank();
  return {
    async record(at, counts) {
      for (const m of METRICS) {
        const v = metricOf(counts, m);
        st[m] = v === 'fail' ? {...st[m], stale: st[m].value !== null} : {value: v, stale: false, measuredAt: iso(at)};
      }
    },
    async latest() { return Object.fromEntries(METRICS.map(m => [m, {...st[m]}])); },
  };
}
/** The defect: a failed count is written as a measured zero over whatever was stored. */
function zeroingStore() {
  const st = blank();
  return {
    async record(at, counts) {
      for (const m of METRICS) { const v = metricOf(counts, m); st[m] = {value: v === 'fail' ? 0 : v, stale: false, measuredAt: iso(at)}; }
    },
    async latest() { return Object.fromEntries(METRICS.map(m => [m, {...st[m]}])); },
  };
}
/** Correct for likes only: comments and shares are overwritten with zeros on failure. */
function likesOnlyStore() {
  const good = compliantStore(), bad = zeroingStore();
  return {
    async record(at, counts) { await good.record(at, counts); await bad.record(at, counts); },
    async latest() { const g = await good.latest(), b = await bad.latest(); return {likes: g.likes, comments: b.comments, shares: b.shares}; },
  };
}

const GAP = {
  stale: m => `a count failure after a good reading did not keep the last measured ${m}, flagged stale`,
  first: m => `a first count failure is not shown as unavailable (null) for ${m}`,
  zero: m => `a genuine measured zero did not replace the earlier positive ${m}`,
  mixed: m => `in a mixed-availability reading, ${m} was not kept, flagged or replaced independently of the other metrics`,
};
const ALL_GAPS = new Set(METRICS.flatMap(m => Object.values(GAP).map(g => g(m))));
/** The contract over a store, per metric: four scenarios, each on its own store from `make`. */
async function contractGaps(make) {
  const gaps = [];
  const a = make(); await a.record(T0, POS); await a.record(T0 + HOUR, 'fail');   // a same-day repeat, as the issue describes
  const sa = await a.latest();
  for (const m of METRICS) if (sa[m].value !== POS[m] || !sa[m].stale || sa[m].measuredAt !== iso(T0)) gaps.push(GAP.stale(m));
  const b = make(); await b.record(T0, 'fail');
  const sb = await b.latest();
  for (const m of METRICS) if (sb[m].value !== null) gaps.push(GAP.first(m));
  const c = make(); await c.record(T0, POS); await c.record(T0 + DAY, ZERO);
  const sc = await c.latest();
  for (const m of METRICS) if (sc[m].value !== 0) gaps.push(GAP.zero(m));
  // Mixed: likes is a true zero, comments fails (keep 6, stale, time T0), shares is measured anew (9).
  const d = make(); await d.record(T0, POS); await d.record(T0 + DAY, {likes: 0, comments: 'fail', shares: 9});
  const sd = await d.latest();
  if (sd.likes.value !== 0 || sd.likes.stale || sd.likes.measuredAt !== iso(T0 + DAY)) gaps.push(GAP.mixed('likes'));
  if (sd.comments.value !== 6 || !sd.comments.stale || sd.comments.measuredAt !== iso(T0)) gaps.push(GAP.mixed('comments'));
  if (sd.shares.value !== 9 || sd.shares.stale || sd.shares.measuredAt !== iso(T0 + DAY)) gaps.push(GAP.mixed('shares'));
  return gaps;
}

test('valid control: a store with per-metric availability has no gaps for likes, comments or shares', async () => {
  assert.deepEqual(await contractGaps(compliantStore), []);
});

test('affected control: a store that writes zeros for a failed count is reported with the stale, unavailable and mixed gaps', async () => {
  assert.deepEqual(await contractGaps(zeroingStore), [
    ...METRICS.map(GAP.stale), ...METRICS.map(GAP.first), GAP.mixed('comments'),
  ]);
});

test('affected control: a store wrong only for comments and shares is still detected, with no likes gap', async () => {
  const gaps = await contractGaps(likesOnlyStore);
  assert.deepEqual(gaps, [
    GAP.stale('comments'), GAP.stale('shares'), GAP.first('comments'), GAP.first('shares'), GAP.mixed('comments'),
  ]);
});

dbTest('real code: a measured zero on a later day replaces the earlier positive value for every metric (a true zero is meaningful)', async () => {
  const s = realStore();
  await s.record(T0, POS);
  const before = await s.latest();
  for (const m of METRICS) assert.equal(before[m].value, POS[m]);
  await s.record(T0 + DAY, ZERO);
  const after = await s.latest();
  for (const m of METRICS) assert.equal(after[m].value, 0);
});

dbTest('baseline receipt: the real reading/stat read-back observed against the contract (diagnostic; not asserted)', async t => {
  const gaps = await contractGaps(realStore);
  const s = realStore(); await s.record(T0, POS); await s.record(T0 + HOUR, 'fail');
  const f = realStore(); await f.record(T0, 'fail');
  const x = realStore(); await x.record(T0, POS); await x.record(T0 + DAY, {likes: 0, comments: 'fail', shares: 9});
  t.diagnostic(`after good then failed count (same day): ${JSON.stringify(await s.latest())}; first failure: ${JSON.stringify(await f.latest())}; mixed availability: ${JSON.stringify(await x.latest())}; gaps=${JSON.stringify(gaps)}`);
  for (const gap of gaps) assert.ok(ALL_GAPS.has(gap));
});
