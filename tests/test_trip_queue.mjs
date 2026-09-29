// Queue-based trip checks (server/trip-queue.ts): the cron producer, the batch
// consumer, re-delivery, the dead-letter path, scale, and the fallback when the
// queue binding is absent. Cloudflare Queues is simulated in memory with the
// same settings the deploy config uses (scripts/wrangler_config.mjs TRIP_QUEUES).
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import {TRIP_QUEUES} from '../scripts/wrangler_config.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
const {default: worker, checkTrips} = await import('../server/index.ts');
const {scheduleTripChecks, consumeTripChecks, consumeDeadLetters, publicationMarker, SEND_BATCH, OWNER_PAGE, STATE_KEY, TRIP_QUEUE, TRIP_DLQ} = await import('../server/trip-queue.ts');

const CONSUMER = TRIP_QUEUES.consumers.find(c => c.queue === TRIP_QUEUE);

function database({failOwner} = {}) {
  const sql = new DatabaseSync(':memory:'), journal = read('../drizzle/meta/_journal.json');
  for (const {tag} of [...journal.entries].sort((a, b) => a.idx - b.idx)) sql.exec(readFileSync(new URL(`../drizzle/${tag}.sql`, import.meta.url), 'utf8'));
  const queries = [];
  const adapter = {prepare(query) { let args = []; const statement = sql.prepare(query); return {
    bind(...a) { args = a; return this; },
    check() { queries.push(query); if (failOwner && args.includes(failOwner)) throw Error('D1 unavailable for this owner'); },
    async first() { this.check(); return statement.get(...args) || null; },
    async all() { this.check(); return {results: statement.all(...args)}; },
    async run() { this.check(); const info = statement.run(...args); return {meta: {changes: Number(info.changes)}}; }}; },
    async batch(list) { sql.exec('BEGIN'); try { const out = []; for (const q of list) out.push(await q.run()); sql.exec('COMMIT'); return out; } catch (e) { sql.exec('ROLLBACK'); throw e; } }};
  return {sql, adapter, queries};
}

const DATE = new Intl.DateTimeFormat('en-CA', {timeZone: 'America/Los_Angeles'}).format(new Date(Date.now() + 2 * 86400000));
function addTrips(sql, count, ownersEvery = 1) {
  const insert = sql.prepare('INSERT INTO trips(id,owner,region,point,species,date,start_hour,end_hour,wind_limit,gust_limit,sea_limit,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)');
  sql.exec('BEGIN');
  for (let i = 0; i < count; i++) insert.run(`trip-${String(i).padStart(5, '0')}`, `owner-${String(Math.floor(i / ownersEvery)).padStart(5, '0')}`, 'morro-bay', 'north', 'reef', DATE, 7, 13, 8, 12, 3, new Date().toISOString());
  sql.exec('COMMIT');
}

/** An in-memory producer that records every sendBatch call. */
function producer({failAt = -1} = {}) {
  const calls = [];
  return {calls, messages: () => calls.flat(), async sendBatch(messages) {
    if (calls.length === failAt) throw Error('Queue send failed');
    assert.ok(messages.length <= 100, 'sendBatch takes at most 100 messages');
    calls.push(messages.map(m => ({...m})));
  }};
}

/** A MessageBatch as the Workers runtime hands it to queue(). */
function batchOf(queue, bodies, attempts = 1) {
  const messages = bodies.map((body, i) => ({id: `m${i}`, body, attempts, timestamp: new Date(), outcome: null,
    ack() { this.outcome = 'ack'; }, retry(options) { this.outcome = 'retry'; this.delay = options?.delaySeconds; }}));
  return {queue, messages, ackAll() { for (const m of messages) m.ack(); }, retryAll() { for (const m of messages) m.retry(); }};
}

/**
 * Deliver messages as Cloudflare Queues does with the configured consumer:
 * batches of max_batch_size; a retried message comes back with attempts+1 and,
 * after max_retries retries, goes to the dead-letter queue's consumer.
 */
async function drain(env, bodies) {
  let pending = bodies.map(body => ({body, attempts: 1}));
  const dead = [], stats = {batches: 0, deliveries: 0, deadBatches: 0};
  while (pending.length) {
    const next = [];
    for (let i = 0; i < pending.length; i += CONSUMER.max_batch_size) {
      const slice = pending.slice(i, i + CONSUMER.max_batch_size), batch = batchOf(TRIP_QUEUE, slice.map(p => p.body));
      batch.messages.forEach((m, j) => { m.attempts = slice[j].attempts; });
      await worker.queue(batch, env);
      stats.batches++; stats.deliveries += batch.messages.length;
      batch.messages.forEach((m, j) => {
        assert.ok(m.outcome, 'every message is acked or retried');
        if (m.outcome !== 'retry') return;
        if (slice[j].attempts > CONSUMER.max_retries) dead.push(slice[j].body);
        else next.push({body: slice[j].body, attempts: slice[j].attempts + 1});
      });
    }
    pending = next;
  }
  if (dead.length) {
    const batch = batchOf(TRIP_DLQ, dead);
    await worker.queue(batch, env);
    stats.deadBatches++;
    assert.ok(batch.messages.every(m => m.outcome === 'ack'), 'dead letters are acknowledged');
  }
  return {dead, stats};
}

async function quietly(run) {
  const {log, error, warn} = console, lines = [];
  console.log = console.error = console.warn = (...args) => lines.push(args.map(a => typeof a === 'string' ? a : JSON.stringify(a)).join(' '));
  try { return {value: await run(), lines}; } finally { Object.assign(console, {log, error, warn}); }
}
// Public feeds and NWS alerts unavailable: every trip becomes an in-app "unverified" alert.
async function withFeedsDown(run) {
  const original = globalThis.fetch; let calls = 0;
  globalThis.fetch = async () => { calls++; return Response.json({}, {status: 503}); };
  try { return await run(() => calls); } finally { globalThis.fetch = original; }
}
const feed = (run, minutesAgo = 10) => {
  const at = new Date(Date.now() - minutesAgo * 60000).toISOString();
  return Promise.resolve({completed_at: at, published_at: at, run_id: run});
};
const count = (sql, table) => sql.prepare(`SELECT COUNT(*) AS n FROM ${table}`).get().n;

test('the deploy config and the Worker agree on queue names and consumer limits', () => {
  assert.equal(TRIP_QUEUES.producers[0].queue, TRIP_QUEUE);
  assert.equal(TRIP_QUEUES.producers[0].binding, 'TRIP_QUEUE');
  assert.equal(CONSUMER.dead_letter_queue, TRIP_DLQ);
  assert.equal(CONSUMER.max_batch_size, 25);
  assert.equal(CONSUMER.max_retries, 3);
  assert.ok(CONSUMER.max_concurrency >= 1 && CONSUMER.max_concurrency <= 10);
  assert.ok(TRIP_QUEUES.consumers.some(c => c.queue === TRIP_DLQ), 'the dead-letter queue has a consumer');
});

test('a publication marker is stable per run and completion time, and null for an unreadable feed', () => {
  assert.equal(publicationMarker({run_id: '42', completed_at: '2026-09-29T10:00:00Z'}), '42@2026-09-29T10:00:00Z');
  assert.equal(publicationMarker({completed_at: '2026-09-29T10:00:00Z'}), '@2026-09-29T10:00:00Z');
  for (const bad of [null, undefined, {}, {completed_at: 'yesterday'}, 'text']) assert.equal(publicationMarker(bad), null);
});

test('the consumer checks every trip of each owner in a batch and acknowledges each message', async () => {
  const {sql, adapter} = database(), env = {DB: adapter};
  addTrips(sql, 6, 2);   // owner-00000..owner-00002, two trips each
  sql.prepare('INSERT INTO trips(id,owner,region,point,species,date,start_hour,end_hour,wind_limit,gust_limit,sea_limit,enabled,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,0,?)').run('trip-off', 'owner-00000', 'morro-bay', 'north', 'reef', DATE, 7, 13, 8, 12, 3, new Date().toISOString());
  await withFeedsDown(async fetches => {
    const batch = batchOf(TRIP_QUEUE, ['owner-00000', 'owner-00001', 'owner-00002'].map(owner => ({owner, publication: 'p1'})));
    const {value} = await quietly(() => consumeTripChecks(batch, env));
    assert.deepEqual(value, {owners: 3, retried: 0, invalid: 0, checked: 6, changes: 6, delivered: 0, held: 0, in_app: 6});
    assert.ok(batch.messages.every(m => m.outcome === 'ack'));
    assert.equal(count(sql, 'alert_events'), 6, 'one event per enabled trip; the disabled trip is not checked');
    assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM alert_events WHERE status='in-app'").get().n, 6);
    assert.ok(fetches() <= 4, 'public feeds are read once per batch, not once per trip');
  });
  sql.close();
});

test('re-delivering the same messages creates no second event and changes nothing', async () => {
  const {sql, adapter} = database(), env = {DB: adapter};
  addTrips(sql, 4, 2);
  await withFeedsDown(async () => {
    const bodies = [{owner: 'owner-00000', publication: 'p1'}, {owner: 'owner-00001', publication: 'p1'}];
    await quietly(() => consumeTripChecks(batchOf(TRIP_QUEUE, bodies), env));
    const events = sql.prepare('SELECT id,status FROM alert_events ORDER BY id').all(), trips = sql.prepare('SELECT id,last_assessment FROM trips ORDER BY id').all();
    // At-least-once delivery: the same batch again, and the manual job over the same trips.
    const {value: again} = await quietly(() => consumeTripChecks(batchOf(TRIP_QUEUE, bodies, 2), env));
    assert.equal(again.changes, 0);
    const {value: manual} = await quietly(() => checkTrips(env));
    assert.equal(manual.changes, 0);
    assert.deepEqual(sql.prepare('SELECT id,status FROM alert_events ORDER BY id').all(), events);
    assert.equal(count(sql, 'alert_events'), 4);
    assert.equal(sql.prepare('SELECT id,last_assessment FROM trips ORDER BY id').all().length, trips.length);
  });
  sql.close();
});

test('a message whose check keeps failing is retried with backoff, then dead-lettered; the others are acknowledged', async () => {
  const {sql, adapter} = database({failOwner: 'owner-00001'}), env = {DB: adapter};
  addTrips(sql, 3);
  await withFeedsDown(async () => {
    const bodies = ['owner-00000', 'owner-00001', 'owner-00002'].map(owner => ({owner, publication: 'p1'}));
    const first = batchOf(TRIP_QUEUE, bodies);
    await quietly(() => consumeTripChecks(first, env));
    assert.deepEqual(first.messages.map(m => m.outcome), ['ack', 'retry', 'ack']);
    assert.equal(first.messages[1].delay, 30);
    const {value: {dead, stats}, lines} = await quietly(() => drain(env, bodies));
    assert.deepEqual(dead, [{owner: 'owner-00001', publication: 'p1'}]);
    assert.equal(stats.deliveries, 3 + CONSUMER.max_retries, 'the failing message was delivered 1 + max_retries times');
    assert.equal(stats.deadBatches, 1);
    const logged = lines.find(l => l.includes('trip_check_dead_letter'));
    assert.ok(logged, 'the dead letter is logged');
    assert.doesNotMatch(logged, /owner-0000/, 'the log names no owner');
  });
  // A malformed body is dropped, not retried forever.
  const bad = batchOf(TRIP_QUEUE, [{}, {owner: 42}, {owner: ''}, null]);
  const {value} = await quietly(() => consumeTripChecks(bad, {DB: adapter}));
  assert.equal(value.invalid, 4);
  assert.ok(bad.messages.every(m => m.outcome === 'ack'));
  assert.equal(consumeDeadLetters(batchOf(TRIP_DLQ, [{owner: 'x', publication: 'p'}])).dead, 1);
  sql.close();
});

test('the cron enqueues each owner once per new publication, in bounded batches, and not again for the same one', async () => {
  const {sql, adapter} = database(), queue = producer(), env = {DB: adapter, TRIP_QUEUE: queue};
  addTrips(sql, 30, 3);   // 10 owners
  assert.equal((await scheduleTripChecks(env, Date.now(), feed('7', 1))).action, 'settling');
  assert.equal(queue.calls.length, 0, 'a publication younger than the settle time is left for the next run');
  const published = feed('7');
  const first = await scheduleTripChecks(env, Date.now(), published);
  assert.equal(first.action, 'enqueued');
  assert.equal(first.owners, 10);
  assert.equal(queue.messages().length, 10);
  assert.deepEqual(queue.messages()[0], {body: {owner: 'owner-00000', publication: first.publication}, contentType: 'json'});
  assert.equal(sql.prepare('SELECT value FROM job_state WHERE key=?').get(STATE_KEY).value, first.publication);
  assert.equal((await scheduleTripChecks(env, Date.now(), published)).action, 'unchanged');
  assert.equal(queue.messages().length, 10, 'the same publication is queued once');
  assert.equal((await scheduleTripChecks(env, Date.now(), feed('8'))).action, 'enqueued');
  assert.equal(queue.messages().length, 20, 'the next publication queues the owners again');
  assert.equal((await scheduleTripChecks(env, Date.now(), Promise.resolve(null))).action, 'no-feed');
  sql.close();
});

test('a failed send releases the claim so the next cron run retries the publication', async () => {
  const {sql, adapter} = database();
  addTrips(sql, 3);
  sql.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?)').run(STATE_KEY, 'old@publication', new Date().toISOString());
  const failing = producer({failAt: 0});
  const {value} = await quietly(() => scheduleTripChecks({DB: adapter, TRIP_QUEUE: failing}, Date.now(), feed('9')));
  assert.equal(value.action, 'enqueue-failed');
  assert.equal(sql.prepare('SELECT value FROM job_state WHERE key=?').get(STATE_KEY).value, 'old@publication');
  const working = producer();
  assert.equal((await scheduleTripChecks({DB: adapter, TRIP_QUEUE: working}, Date.now(), feed('9'))).action, 'enqueued');
  assert.equal(working.messages().length, 3);
  sql.close();
});

test('5,000 synthetic trips are enqueued in bounded batches, one message per owner', async () => {
  const {sql, adapter, queries} = database(), queue = producer(), env = {DB: adapter, TRIP_QUEUE: queue};
  addTrips(sql, 5000, 2);   // 2,500 owners
  const scheduled = await scheduleTripChecks(env, Date.now(), feed('5000'));
  assert.equal(scheduled.action, 'enqueued');
  assert.equal(scheduled.owners, 2500);
  assert.equal(scheduled.batches, Math.ceil(2500 / SEND_BATCH));
  assert.ok(queue.calls.every(c => c.length <= SEND_BATCH));
  const owners = queue.messages().map(m => m.body.owner);
  assert.equal(new Set(owners).size, 2500, 'each owner exactly once');
  const pages = queries.filter(q => q.includes('DISTINCT owner')).length;
  assert.equal(pages, Math.floor(2500 / OWNER_PAGE) + 1, 'owners are read from D1 in pages of OWNER_PAGE');
  // The consumer side at the configured batch size: a sample of 4 batches (100
  // owners, 200 trips) end to end; the full drain is the same code 100 times.
  await withFeedsDown(async () => {
    const {value: {dead, stats}} = await quietly(() => drain(env, queue.messages().slice(0, 4 * CONSUMER.max_batch_size).map(m => m.body)));
    assert.equal(dead.length, 0);
    assert.equal(stats.batches, 4);
  });
  assert.equal(count(sql, 'alert_events'), 200, 'every trip of every delivered owner was checked');
  sql.close();
});

test('without a queue binding the cron leaves trip checks to the manual job, which still pages through them', async () => {
  const {sql, adapter} = database(), env = {DB: adapter};
  addTrips(sql, 30);
  assert.deepEqual(await scheduleTripChecks(env, Date.now(), feed('1')), {action: 'no-queue'});
  assert.deepEqual(await scheduleTripChecks({TRIP_QUEUE: producer()}, Date.now(), feed('1')), {action: 'no-db'});
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => Response.json({}, {status: 503});
  const pending = [];
  try {
    await quietly(() => worker.scheduled({}, env, {waitUntil: p => pending.push(p)}));
    await quietly(() => Promise.all(pending));
    assert.equal(count(sql, 'job_state'), 0, 'no publication is claimed without a queue');
    assert.equal(count(sql, 'alert_events'), 0, 'the cron itself checks no trips');
    const {value: page1} = await quietly(() => checkTrips(env));
    assert.equal(page1.checked, 25);
    assert.ok(page1.next_cursor);
    const {value: page2} = await quietly(() => checkTrips(env, page1.next_cursor));
    assert.equal(page2.checked, 5);
    assert.equal(page2.next_cursor, null);
    assert.equal(count(sql, 'alert_events'), 30);
  } finally { globalThis.fetch = originalFetch; }
  sql.close();
});

test('the cron handler queues checks when the binding is present', async () => {
  const {sql, adapter} = database(), queue = producer(), env = {DB: adapter, TRIP_QUEUE: queue};
  addTrips(sql, 4);
  const at = new Date(Date.now() - 10 * 60000).toISOString(), original = globalThis.fetch;
  globalThis.fetch = async url => String(url).endsWith('conditions/latest.json') ? Response.json({completed_at: at, published_at: at, run_id: '77'}) : Response.json({}, {status: 503});
  const pending = [];
  try {
    const {lines} = await quietly(async () => { await worker.scheduled({}, env, {waitUntil: p => pending.push(p)}); await Promise.all(pending); });
    assert.equal(queue.messages().length, 4);
    assert.ok(lines.some(l => l.includes('"event":"trip_check_schedule"') && l.includes('"action":"enqueued"')));
  } finally { globalThis.fetch = original; }
  sql.close();
});
