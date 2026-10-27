import test, {after} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import {installOffline} from './fixtures/sp1601_generated_settle/offline.mjs';

const guard = installOffline();
const savedGlobals = new Map(['REGIONS', 'DEPLOYMENT', 'SHELLS', 'BUILD_ID'].map(key => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
const read = relative => JSON.parse(readFileSync(new URL(relative, import.meta.url), 'utf8'));
const fixtures = read('./fixtures/sp1601_generated_settle/feeds.json');
globalThis.REGIONS = {};
globalThis.DEPLOYMENT = {allowed_origins: [], public_origin: 'https://example.invalid'};
globalThis.SHELLS = {};
globalThis.BUILD_ID = 'synthetic-sp1601';
// Full real module and dependencies, using native supported TypeScript stripping.
// No dependency replacement, extracted implementation or operational bindings.
const product = await import('../server/trip-queue.ts');
const {useBucket} = await import('../server/feeds.ts');
useBucket(null);
const NOW = Date.parse(fixtures.now);
after(() => {
  useBucket(null);
  guard.restore();
  for (const [key, descriptor] of savedGlobals) {
    if (descriptor) Object.defineProperty(globalThis, key, descriptor);
    else delete globalThis[key];
  }
  assert.deepEqual(guard.attempts, [], 'no attempted external I/O');
});

function scenario(t, {previous = null, failSend = false} = {}) {
  const sql = new DatabaseSync(':memory:');
  t.after(() => sql.close());
  for (const {tag} of [...read('../drizzle/meta/_journal.json').entries].sort((a, b) => a.idx - b.idx)) {
    sql.exec(readFileSync(new URL(`../drizzle/${tag}.sql`, import.meta.url), 'utf8'));
  }
  // DUE uses SQLite's current date. A far-future synthetic date keeps this
  // producer-only fixture deterministic without replacing the SQL or clock.
  sql.prepare('INSERT INTO trips(id,owner,region,point,species,date,start_hour,end_hour,wind_limit,gust_limit,sea_limit,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)')
    .run('synthetic-trip', 'synthetic-owner', 'synthetic-region', 'north', 'reef', '9999-12-31', 7, 13, 8, 12, 3, fixtures.now);
  if (previous !== null) sql.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?)').run(product.STATE_KEY, previous, fixtures.now);
  const queries = [], messages = [];
  const DB = {prepare(query) {
    queries.push(query);
    const statement = sql.prepare(query); let args = [];
    return {bind(...values) { args = values; return this; },
      async first() { return statement.get(...args) || null; },
      async all() { return {results: statement.all(...args)}; },
      async run() { return {meta: {changes: Number(statement.run(...args).changes)}}; }};
  }};
  const TRIP_QUEUE = {async sendBatch(batch) {
    if (failSend) throw Error('synthetic send failure');
    messages.push(...structuredClone(batch));
  }};
  return {sql, queries, messages, env: {DB, TRIP_QUEUE},
    run(feed, now = NOW) { return product.scheduleTripChecks(this.env, now, Promise.resolve(feed)); },
    state() { return sql.prepare('SELECT value FROM job_state WHERE key=?').get(product.STATE_KEY)?.value ?? null; }};
}

// These two cases and their dependencies are frozen before product modification.
test('primary regression', async t => {
  const s = scenario(t);
  const result = await s.run(fixtures.recent);
  assert.equal(result.action, 'settling', 'A1_GENERATED_RECENT_MUST_SETTLE');
  assert.equal(result.publication, `synthetic-generated@${fixtures.recent.generated_at}`);
  assert.deepEqual(s.queries, [], 'settle before any DB prepare/read/write');
  assert.deepEqual(s.messages, [], 'settle before any send');
  assert.equal(s.state(), null);
});

test('healthy control', async t => {
  const s = scenario(t);
  const result = await s.run(fixtures.old);
  const publication = `synthetic-generated@${fixtures.old.generated_at}`;
  assert.deepEqual(result, {action: 'enqueued', publication, owners: 1, batches: 1});
  assert.deepEqual(s.messages, [{body: {owner: 'synthetic-owner', publication}, contentType: 'json'}]);
  assert.equal(s.state(), publication);
  assert.equal(s.queries.filter(query => query.includes('DISTINCT owner')).length, 1);
});

if (!process.argv.includes('--baseline')) {
  const {registerFocused} = await import('./fixtures/sp1601_generated_settle/focused.mjs');
  registerFocused({test, assert, product, scenario, fixtures, NOW, guard});
}
