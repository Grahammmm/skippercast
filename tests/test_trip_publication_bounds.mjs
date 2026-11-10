import test, {after} from 'node:test';
import assert from 'node:assert/strict';
import {isDeepStrictEqual} from 'node:util';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';

const savedFetch = globalThis.fetch;
let fetches = 0;
globalThis.fetch = async () => { fetches++; throw Error('unexpected network in publication bounds test'); };
globalThis.REGIONS = {};
globalThis.DEPLOYMENT = {allowed_origins: [], public_origin: 'https://example.invalid'};
globalThis.SHELLS = {};
globalThis.BUILD_ID = 'synthetic-publication-bounds';
const {publicationMarker, scheduleTripChecks, STATE_KEY, SETTLE_MS} = await import('../server/trip-queue.ts');
after(() => {
  globalThis.fetch = savedFetch;
  assert.equal(fetches, 0, 'no attempted network access');
});
const DONE = '2026-11-09T01:00:00.000Z';
const NEXT = '2026-11-09T02:00:00.000Z';
const NOW = Date.parse(NEXT) + SETTLE_MS;
const bounded = length => ({run_id: 'r'.repeat(length - 1 - DONE.length), completed_at: DONE});
const equal = (actual, expected, message) => assert.ok(isDeepStrictEqual(actual, expected), message);

function scenario(t, previous = null) {
  const sql = new DatabaseSync(':memory:');
  t.after(() => sql.close());
  const read = relative => JSON.parse(readFileSync(new URL(relative, import.meta.url), 'utf8'));
  for (const {tag} of [...read('../drizzle/meta/_journal.json').entries].sort((a, b) => a.idx - b.idx)) {
    sql.exec(readFileSync(new URL(`../drizzle/${tag}.sql`, import.meta.url), 'utf8'));
  }
  sql.prepare('INSERT INTO trips(id,owner,region,point,species,date,start_hour,end_hour,wind_limit,gust_limit,sea_limit,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)')
    .run('synthetic-trip', 'synthetic-owner', 'synthetic-region', 'north', 'reef', '9999-12-31', 7, 13, 8, 12, 3, DONE);
  sql.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?)').run('synthetic-other', 'preserved', DONE);
  if (previous !== null) sql.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?)').run(STATE_KEY, previous, DONE);
  const queries = [], sends = [];
  const DB = {prepare(query) {
    queries.push(query);
    const statement = sql.prepare(query); let args = [];
    return {bind(...values) { args = values; return this; },
      async first() { return statement.get(...args) || null; },
      async all() { return {results: statement.all(...args)}; },
      async run() { return {meta: {changes: Number(statement.run(...args).changes)}}; }};
  }};
  const TRIP_QUEUE = {async sendBatch(batch) { sends.push(structuredClone(batch)); }};
  return {queries, sends, env: {DB, TRIP_QUEUE},
    run(feed, now = NOW) { return scheduleTripChecks(this.env, now, Promise.resolve(feed)); },
    rows() { return sql.prepare('SELECT * FROM job_state ORDER BY key').all(); },
    marker() { return sql.prepare('SELECT value FROM job_state WHERE key=?').get(STATE_KEY)?.value ?? null; }};
}

test('marker_exact_bound_is_lossless', () => {
  for (const length of [199, 200]) {
    const feed = bounded(length), raw = `${feed.run_id}@${DONE}`;
    assert.equal(raw.length, length);
    assert.ok(publicationMarker(feed) === raw, 'complete identity retained');
  }
});

test('marker_over_bound_refuses_instead_of_colliding', () => {
  const feeds = [bounded(201),
    {run_id: 'r'.repeat(200), completed_at: DONE},
    {run_id: 'r'.repeat(200), completed_at: NEXT},
    {run_id: `${'r'.repeat(200)}a`, completed_at: DONE},
    {run_id: `${'r'.repeat(200)}b`, completed_at: DONE}];
  for (const feed of feeds) assert.ok(publicationMarker(feed) === null, 'oversized marker refused');
});

test('marker_generated_and_unicode_bounds', () => {
  for (const length of [200, 201]) {
    const feed = bounded(length);
    const generated = {run_id: feed.run_id, generated_at: DONE};
    assert.ok(publicationMarker(generated) === (length === 200 ? `${feed.run_id}@${DONE}` : null));
    const run_id = '🦀'.repeat(87) + (length === 201 ? 'xx' : 'x');
    assert.equal(run_id.length + 1 + DONE.length, length);
    assert.ok(publicationMarker({run_id, completed_at: DONE}) === (length === 200 ? `${run_id}@${DONE}` : null));
  }
  for (const run_id of [undefined, null, 42, {}]) {
    assert.equal(publicationMarker({run_id, generated_at: DONE}), `@${DONE}`);
  }
  const padded = ` Mon, 09 Nov 2026 01:00:00 GMT${' '.repeat(201)}`;
  assert.ok(Number.isFinite(Date.parse(padded)), 'overlong timestamp remains parseable');
  assert.equal(publicationMarker({completed_at: padded}), null);
  assert.equal(publicationMarker({generated_at: padded}), null);
  assert.equal(publicationMarker({completed_at: DONE, generated_at: padded}), `@${DONE}`);
});

test('oversized_publication_has_no_side_effects', async t => {
  for (const previous of [null, `old@${DONE}`, 'r'.repeat(200)]) {
    const s = scenario(t, previous), before = s.rows();
    for (const feed of [bounded(201), {run_id: 'r'.repeat(200), generated_at: NEXT}]) {
      equal(await s.run(feed), {action: 'no-feed'}, 'oversized publication refused');
      assert.equal(s.queries.length, 0, 'no DB prepare, including reads');
      assert.equal(s.sends.length, 0, 'no sendBatch');
      equal(s.rows(), before, 'every stored row unchanged');
    }
  }
});

test('healthy_publication_recovers_after_refusal', async t => {
  const s = scenario(t, 'r'.repeat(200));
  equal(await s.run(bounded(201)), {action: 'no-feed'}, 'refused before recovery');
  const feeds = [{run_id: 'ordinary', completed_at: DONE}, bounded(200), {...bounded(200), completed_at: NEXT}];
  for (const [index, feed] of feeds.entries()) {
    const publication = `${feed.run_id}@${feed.completed_at}`;
    equal(await s.run(feed), {action: 'enqueued', publication, owners: 1, batches: 1}, 'new publication queued');
    equal(s.sends[index], [{body: {owner: 'synthetic-owner', publication}, contentType: 'json'}], 'exact owner and marker');
    assert.ok(s.marker() === publication, 'exact stored marker');
    equal(await s.run(feed), {action: 'unchanged', publication}, 'repeat is idempotent');
    assert.equal(s.sends.length, index + 1, 'one send per distinct accepted publication');
  }
});

test('legacy_and_gate_behavior_unchanged', async t => {
  assert.equal(publicationMarker({run_id: '42', completed_at: DONE}), `42@${DONE}`);
  assert.equal(publicationMarker({completed_at: DONE}), `@${DONE}`);
  for (const feed of [null, undefined, {}, 'text', {completed_at: 'yesterday'}]) {
    assert.equal(publicationMarker(feed), null);
    const s = scenario(t);
    equal(await s.run(feed), {action: 'no-feed'}, 'unreadable feed');
    assert.equal(s.queries.length, 0);
  }
  const s = scenario(t), bad = Promise.resolve(bounded(201));
  equal(await scheduleTripChecks({}, NOW, bad), {action: 'no-queue'}, 'no-queue takes precedence');
  equal(await scheduleTripChecks({TRIP_QUEUE: s.env.TRIP_QUEUE}, NOW, bad), {action: 'no-db'}, 'no-db takes precedence');
  const recent = {run_id: 'recent', generated_at: new Date(NOW - SETTLE_MS + 1).toISOString()};
  equal(await s.run(recent), {action: 'settling', publication: `recent@${recent.generated_at}`}, 'recent feed settles');
  assert.equal(s.queries.length, 0);
  assert.equal(s.sends.length, 0);
  assert.equal((await s.run(recent, NOW + 1)).action, 'enqueued', 'settled at exact boundary');
});
