import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import test from 'node:test';
import {setImmediate} from 'node:timers/promises';

Object.assign(globalThis, {REGIONS: {}, DEPLOYMENT: {allowed_origins: []}, SHELLS: {}});
const {default: worker} = await import('../server/index.ts');

const now = Date.parse('2026-10-05T19:00:00Z'); // Monday noon in the advisor's zone; a daily slot is due.
const completed = new Date(now - 5 * 60_000).toISOString();
const marker = `fixture@${completed}`;
const cron = '*/15 * * * *';

function fixture(t) {
  t.mock.method(Date, 'now', () => now);
  t.mock.method(globalThis, 'fetch', async url => {
    assert.ok(String(url).endsWith('/conditions/latest.json'), 'only the synthetic feed is served');
    return Response.json({completed_at: completed, published_at: completed, run_id: 'fixture'});
  });
  for (const method of ['log', 'warn', 'error']) t.mock.method(console, method, () => {});
  const points = [], pending = [];
  const ANALYTICS = {writeDataPoint: point => points.push(point)};
  return {
    points,
    run: env => worker.scheduled({cron}, {...env, ANALYTICS}, {waitUntil: p => pending.push(p)}),
    drain: () => Promise.all(pending),
  };
}

function outcomes(points) {
  return points.map(point => point.blobs);
}

test('prune failure rejects even when trips and advisor are inactive', async t => {
  const {run, drain, points} = fixture(t);
  const DB = {prepare: () => ({bind() { return this; }}), async batch() { throw Error('synthetic prune failure'); }};
  await assert.rejects(run({DB}), /cron run failed/);
  await drain();
  assert.deepEqual(outcomes(points), [['cron', cron, 'none', 'no-queue', 'failed', 'disabled']]);
});

test('advisor error rejects even when pruning succeeded and trips are inactive', async t => {
  const {run, drain, points} = fixture(t);
  const DB = {
    prepare(query) {
      if (query === 'SELECT value FROM job_state WHERE key=?') throw Error('synthetic advisor state failure');
      return {bind() { return this; }};
    },
    async batch() {},
  };
  await assert.rejects(run({DB, TEXT_ADVISOR_ENABLED: 'true'}), /cron run failed/);
  await drain();
  assert.deepEqual(outcomes(points), [['cron', cron, 'none', 'no-queue', 'ok', 'error']]);
});

test('enqueue failure waits for pruning, releases its claim and retries only on a later tick', async t => {
  const {run, drain, points} = fixture(t);
  const sql = new DatabaseSync(':memory:');
  t.after(() => sql.close());
  const read = path => readFileSync(new URL(path, import.meta.url), 'utf8');
  for (const {tag} of JSON.parse(read('../drizzle/meta/_journal.json')).entries) sql.exec(read(`../drizzle/${tag}.sql`));
  sql.exec(`INSERT INTO trips(id,owner,region,point,species,date,start_hour,end_hour,wind_limit,gust_limit,sea_limit,created_at)
            VALUES ('synthetic-trip','synthetic-owner','fixture','point','reef','2026-10-06',7,13,8,12,3,'2026-10-05T19:00:00Z');`);
  const prune = Promise.withResolvers();
  const attempted = Promise.withResolvers();
  const DB = {
    prepare(query) {
      if (!/^(SELECT|INSERT INTO job_state|DELETE FROM job_state)/.test(query)) return {bind() { return this; }};
      const stmt = sql.prepare(query);
      return {bind(...args) { return {
        async first() { return stmt.get(...args); },
        async all() { return {results: stmt.all(...args)}; },
        async run() { return {meta: stmt.run(...args)}; },
      }; }};
    },
    batch: () => prune.promise,
  };
  const attempts = [];
  const TRIP_QUEUE = {async sendBatch(messages) {
    attempts.push(messages.map(message => message.body));
    if (attempts.length === 1) {
      attempted.resolve();
      throw Error('synthetic enqueue failure');
    }
  }};
  const env = {DB, TRIP_QUEUE};
  const first = run(env);
  let settled = false;
  void first.then(() => { settled = true; }, () => { settled = true; });
  try {
    await Promise.race([attempted.promise, first]);
    await setImmediate(); // Let the failed send and claim release finish while pruning is held.
    assert.equal(settled, false);
    assert.deepEqual(points, []);
    assert.equal(attempts.length, 1, 'no retry inside this invocation');
  } finally {
    prune.resolve();
  }
  await assert.rejects(first, /cron run failed/);
  assert.equal(sql.prepare('SELECT COUNT(*) AS n FROM job_state').get().n, 0);
  await run(env);
  await run(env);
  await drain();
  assert.deepEqual(attempts, Array.from({length: 2}, () => [{owner: 'synthetic-owner', publication: marker}]));
  assert.deepEqual(outcomes(points), [
    ['cron', cron, 'none', 'enqueue-failed', 'ok', 'disabled'],
    ['cron', cron, 'none', 'enqueued', 'ok', 'disabled'],
    ['cron', cron, 'none', 'unchanged', 'ok', 'disabled'],
  ]);
});

test('missing queue and disabled advisor are normal outcomes', async t => {
  const {run, drain, points} = fixture(t);
  await run({});
  await drain();
  assert.deepEqual(outcomes(points), [['cron', cron, 'none', 'no-queue', 'no-db', 'disabled']]);
});
