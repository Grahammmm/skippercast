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
//   regression        the real reader/writer must satisfy all of the same cases, including the original same-day overwrite.
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
    // An omitted shares field is a real zero in the Graph adapter, so simulate
    // an unreadable shares count with a present field and a missing count.
    body.shares = counts.shares === 'fail' ? {} : {count: counts.shares};
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
      for (const m of METRICS) {
        if (fb[m] === null) assert.ok(fb.notes.includes(`${m}: unavailable`));
        else if (fb.engagement?.[m].stale) assert.ok(fb.notes.includes(`${m}: stale (last measured ${fb.engagement[m].measuredAt})`));
      }
      return Object.fromEntries(METRICS.map(m => [m, {value: fb[m], ...fb.engagement?.[m]}]));
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

dbTest('real code: failed counts retain per-metric measurements or report unavailable; zero still replaces a positive count', async () => {
  assert.deepEqual(await contractGaps(realStore), []);
  const s = realStore();
  await s.record(T0, POS);
  await s.record(T0 + HOUR, 'fail');
  await s.record(T0 + DAY, 'fail');
  const afterFailures = await s.latest();
  for (const m of METRICS) assert.deepEqual(afterFailures[m], {value: POS[m], stale: true, measuredAt: iso(T0)});
  await s.record(T0 + DAY + HOUR, ZERO);
  const recovered = await s.latest();
  for (const m of METRICS) assert.deepEqual(recovered[m], {value: 0, stale: false, measuredAt: iso(T0 + DAY + HOUR)});
});

// ---- H8 #6 / #7: legacy history and overlapping writers ---------------------------------------------------------

function postDb() {
  const {sql, db} = advisorDatabase();
  sql.prepare(`INSERT INTO advisor_posts(id,kind,region,media_json,caption,targets_json,status,fb_post_id,created_by,posted_at,created_at,updated_at)
    VALUES('p1','photo','morro-bay','[]','c','["facebook"]','posted',?,'engine',?,?,?)`).run(FB_POST, iso(T0 - 3 * DAY), iso(T0 - 3 * DAY), iso(T0 - 3 * DAY));
  return {sql, db};
}
const engagementOf = async db => {
  const fb = (await I.postStats(db, {id: 'p1', ig_media_id: null})).facebook;
  return {reach: fb.reach, ...Object.fromEntries(METRICS.map(m => [m, {value: fb[m], ...fb.engagement[m]}]))};
};

// H8 #6 contract: a latest legacy row missing a metric shows the latest EARLIER measured value (a measured zero stays 0) with its
// measurement time; a metric the latest row measured is left alone. Bug caught: only the latest row is consulted, so the metric reads unavailable.
dbTest('legacy rows: an absent metric resolves to the latest earlier measured value with its time; a measured zero is not missing; newer values stay', async () => {
  const {sql, db} = postDb();
  const legacy = sql.prepare('INSERT INTO advisor_post_stats(post_id,platform,day,reach,likes,comments,shares,raw_json,fetched_at) VALUES(?,?,?,?,?,?,?,?,?)');
  legacy.run('p1', 'facebook', '2026-10-02', 700, 40, 3, 2, JSON.stringify({metrics: {post_impressions_unique: 700, reactions: 40, comments: 3, shares: 2}}), iso(T0 - 3 * DAY));
  legacy.run('p1', 'facebook', '2026-10-03', 760, 57, 0, 2, JSON.stringify({metrics: {post_impressions_unique: 760, reactions: 57, comments: 0}}), iso(T0 - 2 * DAY));
  legacy.run('p1', 'facebook', '2026-10-04', 812, 0, 0, 9, JSON.stringify({metrics: {post_impressions_unique: 812, shares: 9}, notes: ['reactions: not returned', 'comments: not returned']}), iso(T0 - DAY));
  assert.deepEqual(await engagementOf(db), {
    reach: 812,
    likes: {value: 57, stale: true, measuredAt: iso(T0 - 2 * DAY)},       // the latest earlier measurement, not the oldest
    comments: {value: 0, stale: true, measuredAt: iso(T0 - 2 * DAY)},     // a measured zero, not unavailable and not the older 3
    shares: {value: 9, stale: false, measuredAt: iso(T0 - DAY)},          // measured in the latest row: left alone
  });
});

/** Facebook readings as readFacebook returns them; an omitted metric was not returned. */
const fbReading = ({reach, likes, comments, shares}) => {
  const metrics = {post_impressions_unique: reach, ...(likes === undefined ? {} : {reactions: likes}), ...(comments === undefined ? {} : {comments}), ...(shares === undefined ? {} : {shares})};
  return {columns: {views: 0, reach, likes: likes ?? 0, comments: comments ?? 0, saved: 0, shares: shares ?? 0, follows: 0, profile_visits: 0, link_taps: 0}, metrics, notes: []};
};
/** A D1 where `between` runs once, just before the first advisor_post_stats write: another run's write landing between our lookup and our write. */
function interleaved(db, between) {
  let fired = false;
  return {
    prepare(q) {
      const st = db.prepare(q);
      if (fired || !/^\s*(INSERT INTO|UPDATE) advisor_post_stats/.test(q)) return st;
      return {bind(...a) { st.bind(...a); return this; }, first: () => st.first(), all: () => st.all(),
        async run() { if (!fired) { fired = true; await between(); } return st.run(); }};
    },
    batch: queries => db.batch(queries),
  };
}

// H8 #7 contract: per-metric measured state survives overlapping sparse and complete reads in either landing order, and a reading
// older than everything stored changes nothing. Bug caught: lookup and upsert outside one atomic step, so the later write drops
// (or the stale-row guard discards) the measurement the other run wrote in between.
dbTest('overlapping sparse and complete reads keep every metric\'s newest measurement in both orders; a genuinely stale reading is rejected', async () => {
  const complete = fbReading({reach: 800, likes: 58, comments: 7, shares: 4}), sparse = fbReading({reach: 820, likes: 60, shares: 5});
  const t1 = T0 + HOUR, t2 = T0 + 2 * HOUR;
  const expected = {reach: 820, likes: {value: 60, stale: false, measuredAt: iso(t2)}, comments: {value: 7, stale: true, measuredAt: iso(t1)},
    shares: {value: 5, stale: false, measuredAt: iso(t2)}};
  // The newer sparse run looked up first; the older complete run's write lands before the sparse write.
  const a = postDb();
  await I.saveReading(interleaved(a.db, () => I.saveReading(a.db, 'p1', 'facebook', complete, t1)), 'p1', 'facebook', sparse, t2);
  assert.deepEqual(await engagementOf(a.db), expected, 'sparse write after an interleaved complete write');
  // The reverse: the older complete run looked up first; the newer sparse write lands before it.
  const b = postDb();
  await I.saveReading(interleaved(b.db, () => I.saveReading(b.db, 'p1', 'facebook', sparse, t2)), 'p1', 'facebook', complete, t1);
  assert.deepEqual(await engagementOf(b.db), expected, 'complete write after an interleaved sparse write: the same result');
  assert.equal(a.sql.prepare('SELECT COUNT(*) AS n FROM advisor_post_stats').get().n, 1);
  // Genuinely stale: a reading older than every stored measurement leaves the row byte-for-byte unchanged.
  const before = {...b.sql.prepare('SELECT * FROM advisor_post_stats').get()};
  await I.saveReading(b.db, 'p1', 'facebook', fbReading({reach: 1, likes: 1, comments: 1, shares: 1}), T0);
  assert.deepEqual({...b.sql.prepare('SELECT * FROM advisor_post_stats').get()}, before);
});
