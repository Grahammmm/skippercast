// F02-02 / SCA-525: the weekly retention prune must stay inside D1's 100-bind budget per statement. The media rule's
// shared-original check binds distinct keys + ids (51 rows = 102 binds) and the graphic-key delete binds one per key
// (101 orphans = 101 binds), so a failing statement leaves the same expired backlog to every later week. Offline:
// real migrations in node:sqlite, an in-memory R2, synthetic rows only; a bind-counting wrapper enforces the cap.
//
// Controls (all pass; this file never asserts the defect is desired):
//   valid control     the real prune with a chunk of 40 (40 ids + 40 keys = 80 binds) clears 51 and 500 distinct expired
//                     originals and 101 orphan graphic requests, keeps an original a non-expired row still uses, and
//                     never exceeds 100 binds.
//   affected control  `contractGaps` reports each gap of a synthetic observation shaped like the failure (statement over
//                     the cap, backlog left, shared original deleted, graphic files dropped before their keys).
//   weekly regression the real prune at the shipped chunk must meet the same contract without a caller override.
import test from 'node:test';
import assert from 'node:assert/strict';
import {advisorDatabase, fakeBucket, sqliteUnavailable} from './_advisor_d1.mjs';
import {runRetention} from '../server/advisor/retention.ts';

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const BIND_CAP = 100, DAY = 86400000;
const NOW = Date.parse('2026-10-11T09:00:00Z');
const ago = days => new Date(NOW - days * DAY).toISOString();
const quiet = async fn => { const s = {log: console.log, warn: console.warn, error: console.error}; console.log = console.warn = console.error = () => {}; try { return await fn(); } finally { Object.assign(console, s); } };

/** The D1 adapter with the project's per-statement bind budget: over the cap fails like D1's "too many SQL variables". */
function guard(db, stats, bucket) {
  return {
    prepare(query) {
      const st = db.prepare(query);
      let args = [];
      return {
        bind(...a) { args = a; stats.maxBinds = Math.max(stats.maxBinds, a.length); if (a.length > BIND_CAP) throw Error('too many SQL variables'); st.bind(...a); return this; },
        first: () => st.first(), all: () => st.all(),
        run() {
          // Ordering probe: a graphic-key delete that executes while any of its files is still in the bucket.
          if (bucket && /^\s*DELETE FROM job_state/i.test(query)) {
            for (const key of args) { const id = String(key).slice('advisor.graphic.'.length); if ([...bucket.store].some(k => k.startsWith(`advisor/posts/${id}/`))) { stats.keyBeforeFiles++; break; } }
          }
          return st.run();
        },
      };
    },
    batch: qs => db.batch(qs),
  };
}

/** n distinct expired originals, one shared original (expired row + a recent row on the same key), n_graphic orphans. */
function seed(expired, graphics) {
  const {sql, db} = advisorDatabase();
  const media = sql.prepare("INSERT INTO advisor_media(id,contact_id,kind,mime,bytes,r2_key,sha256,publish_state,created_at) VALUES(?,'c','image','image/jpeg',1,?,?,'private',?)");
  const state = sql.prepare("INSERT INTO job_state(key,value,updated_at) VALUES(?,'{}',?)");
  const objects = [];
  for (let i = 0; i < expired; i++) { const key = `advisor/media/c/e${i}.jpg`; media.run(`e${i}`, key, `s${i}`, ago(100)); objects.push(key); }
  const shared = 'advisor/media/c/shared.jpg';
  media.run('shared-old', shared, 'sh', ago(100)); media.run('shared-new', shared, 'sh', ago(1)); objects.push(shared);
  for (let i = 0; i < graphics; i++) { state.run(`advisor.graphic.g${i}`, ago(40)); objects.push(`advisor/posts/g${i}/daily.jpg`); }
  return {sql, db, bucket: fakeBucket(objects)};
}

/** Run the real prune and describe what happened (never throws). */
async function observe(expired, graphics, deps, run = runRetention) {
  const s = seed(expired, graphics), stats = {maxBinds: 0, overCap: 0, keyBeforeFiles: 0};
  const env = {DB: guard(s.db, stats, s.bucket), ADVISOR_MEDIA: s.bucket};
  const outcome = await quiet(() => run(env, NOW, deps).then(() => 'ok', e => e.message));
  const n = q => Number(s.sql.prepare(q).get()['COUNT(*)']);
  return {
    outcome, maxBinds: stats.maxBinds, keyBeforeFiles: stats.keyBeforeFiles,
    expiredLeft: n("SELECT COUNT(*) FROM advisor_media WHERE id LIKE 'e%' AND r2_key<>''"),
    originalsLeft: [...s.bucket.store].filter(k => k.startsWith('advisor/media/c/e')).length,
    sharedKept: s.bucket.store.has('advisor/media/c/shared.jpg') && n("SELECT COUNT(*) FROM advisor_media WHERE id='shared-new' AND r2_key='advisor/media/c/shared.jpg'") === 1,
    sharedExpiredLeft: n("SELECT COUNT(*) FROM advisor_media WHERE id='shared-old' AND r2_key<>''"),
    graphicKeysLeft: n("SELECT COUNT(*) FROM job_state WHERE key LIKE 'advisor.graphic.%'"),
    graphicFilesLeft: [...s.bucket.store].filter(k => k.startsWith('advisor/posts/')).length,
  };
}

/** The contract over one observation: bounded statements, backlog cleared, shared original kept, keys follow their files. */
function contractGaps(o) {
  const gaps = [];
  if (o.outcome !== 'ok') gaps.push(`prune failed: ${o.outcome}`);
  if (o.maxBinds > BIND_CAP) gaps.push(`a statement bound ${o.maxBinds} values (cap ${BIND_CAP})`);
  if (o.expiredLeft || o.originalsLeft) gaps.push(`expired media backlog left (${o.expiredLeft} rows, ${o.originalsLeft} originals)`);
  if (!o.sharedKept) gaps.push('an original still referenced by a non-expired row was deleted');
  if (o.graphicKeysLeft || o.graphicFilesLeft) gaps.push(`orphan graphic requests left (${o.graphicKeysLeft} keys, ${o.graphicFilesLeft} files)`);
  if (o.graphicKeysLeft === 0 && o.graphicFilesLeft) gaps.push('graphic keys dropped before their files');
  if (o.keyBeforeFiles) gaps.push(`graphic keys deleted while their files still existed (${o.keyBeforeFiles} statements)`);
  return gaps;
}

const compliant = {outcome: 'ok', maxBinds: 82, expiredLeft: 0, originalsLeft: 0, sharedKept: true, graphicKeysLeft: 0, graphicFilesLeft: 0, keyBeforeFiles: 0};
const defective = {outcome: 'too many SQL variables', maxBinds: 102, expiredLeft: 51, originalsLeft: 51, sharedKept: true, graphicKeysLeft: 101, graphicFilesLeft: 0, keyBeforeFiles: 0};

test('F02-02 contract: the compliant model has no gaps; the defective model reports each one', () => {
  assert.deepEqual(contractGaps(compliant), []);
  assert.deepEqual(contractGaps(defective), [
    'prune failed: too many SQL variables', 'a statement bound 102 values (cap 100)',
    'expired media backlog left (51 rows, 51 originals)', 'orphan graphic requests left (101 keys, 0 files)']);
  assert.deepEqual(contractGaps({...compliant, keyBeforeFiles: 2}), ['graphic keys deleted while their files still existed (2 statements)']);
  assert.deepEqual(contractGaps({...compliant, sharedKept: false}), ['an original still referenced by a non-expired row was deleted']);
  assert.deepEqual(contractGaps({...compliant, graphicFilesLeft: 3}), ['orphan graphic requests left (0 keys, 3 files)', 'graphic keys dropped before their files']);
});

for (const [expired, graphics] of [[51, 101], [500, 101]]) {
  dbTest(`valid control: ${expired} distinct expired originals and ${graphics} orphan graphic requests clear under the ${BIND_CAP}-bind cap (chunk 40)`, async () => {
    const o = await observe(expired, graphics, {chunk: 40});
    assert.deepEqual(contractGaps(o), []);
    assert.equal(o.keyBeforeFiles, 0);
    assert.ok(o.maxBinds <= BIND_CAP && o.maxBinds > 0, `max binds ${o.maxBinds}`);
  });
}

dbTest('affected control: a statement past the cap is what the bind-counting adapter rejects (the gap is detectable)', async () => {
  const stats = {maxBinds: 0, overCap: 0}, {db} = seed(0, 0);
  assert.throws(() => guard(db, stats).prepare('SELECT 1').bind(...Array(BIND_CAP + 2).fill('x')), /too many SQL variables/);
});

dbTest('affected control: a key-first prune that ends with keys and files both gone is still detected (ordering, not just end state)', async () => {
  const keyFirst = async env => {
    const keys = (await env.DB.prepare("SELECT key FROM job_state WHERE key LIKE 'advisor.graphic.%' ORDER BY key LIMIT ?").bind(40).all()).results.map(r => r.key);
    await env.DB.prepare(`DELETE FROM job_state WHERE key IN (${keys.map(() => '?').join(',')})`).bind(...keys).run();
    for (const k of keys) await env.ADVISOR_MEDIA.delete([...env.ADVISOR_MEDIA.store].filter(f => f.startsWith(`advisor/posts/${k.slice('advisor.graphic.'.length)}/`)));
  };
  const o = await observe(0, 30, {}, keyFirst);
  assert.equal(o.graphicKeysLeft, 0); assert.equal(o.graphicFilesLeft, 0);
  assert.deepEqual(contractGaps(o), ['graphic keys deleted while their files still existed (1 statements)']);
});

for (const expired of [51, 500]) {
  dbTest(`weekly regression: ${expired} distinct expired originals and 101 orphan graphic requests clear at the default chunk`, async t => {
    const o = await observe(expired, 101, {});
    t.diagnostic(`maximum binds: ${o.maxBinds}`);
    assert.deepEqual(contractGaps(o), []);
    // At 500 distinct originals the extra shared row is beyond the unchanged weekly limit.
    if (expired === 51) assert.equal(o.sharedExpiredLeft, 0, 'expire the old reference without deleting the shared object');
  });
}
