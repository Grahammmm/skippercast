// Workers Analytics Engine data points (server/analytics.ts): one per request,
// LLM call, queue batch and cron run; bounded route patterns; nothing personal.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import {deployConfig, features, stripJsonComments} from '../scripts/wrangler_config.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
const {default: worker} = await import('../server/index.ts');
const {FEED_SAMPLE, DATASET, writePoint} = await import('../server/analytics.ts');
const {TRIP_DLQ, TRIP_QUEUE} = await import('../server/trip-queue.ts');

const ORIGIN = 'https://skippercast.com';
const ASSETS = {fetch: async request => new Response('<html>', {status: 200, headers: {'Content-Type': 'text/html'}})};
function sink() { const points = []; return {points, ANALYTICS: {writeDataPoint: p => points.push(structuredClone(p))}}; }
const of = (points, kind) => points.filter(p => p.indexes[0] === kind);
function database() {
  const sql = new DatabaseSync(':memory:'), journal = read('../drizzle/meta/_journal.json');
  for (const {tag} of [...journal.entries].sort((a, b) => a.idx - b.idx)) sql.exec(readFileSync(new URL(`../drizzle/${tag}.sql`, import.meta.url), 'utf8'));
  return {sql, adapter: {prepare(query) { let args = []; const s = sql.prepare(query); return {bind(...a) { args = a; return this; }, async first() { return s.get(...args) || null; }, async all() { return {results: s.all(...args)}; }, async run() { return {meta: {changes: Number(s.run(...args).changes)}}; }}; },
    async batch(list) { for (const q of list) await q.run(); }}};
}
async function quietly(run) {
  const {log, error, warn} = console, lines = [];
  console.log = console.error = console.warn = (...a) => lines.push(a.map(x => typeof x === 'string' ? x : JSON.stringify(x)).join(' '));
  try { return {value: await run(), lines}; } finally { Object.assign(console, {log, error, warn}); }
}

test('each request writes one point: route pattern, method, status, cache, colo, hashed request id, time', async () => {
  const {points, ANALYTICS} = sink();
  const request = new Request(ORIGIN + '/api/health?owner=alice@example.com', {headers: {'X-Request-Id': 'abcdefgh12345678'}});
  Object.defineProperty(request, 'cf', {value: {colo: 'LAX'}});
  const response = await worker.fetch(request, {ANALYTICS, ASSETS});
  assert.equal(response.status, 200);
  const [point] = of(points, 'request');
  assert.equal(points.length, 1);
  assert.deepEqual(point.blobs.slice(0, 5), ['request', '/api/health', 'GET', 'none', 'LAX']);
  assert.match(point.blobs[5], /^[0-9a-f]{16}$/);
  assert.notEqual(point.blobs[5], 'abcdefgh12345678');
  assert.equal(point.doubles[0], 200);
  assert.ok(point.doubles[1] >= 0);
  assert.equal(point.doubles[2], 1);
  assert.doesNotMatch(JSON.stringify(points), /alice|example\.com|owner=/, 'no query string or personal value');
});

test('routes are recorded as patterns, errors keep their status, and pages fall under the catch-all', async () => {
  const {points, ANALYTICS} = sink();
  await worker.fetch(new Request(ORIGIN + '/api/trips'), {ANALYTICS, ASSETS, IDENTITY_PROVIDER: 'skippercast'});   // 401, no DB
  await worker.fetch(new Request(ORIGIN + '/api/no-such-thing/12345'), {ANALYTICS, ASSETS});   // private gate answers 401 first
  await worker.fetch(new Request(ORIGIN + '/some/page/42'), {ANALYTICS, ASSETS});
  const rows = of(points, 'request').map(p => [p.blobs[1], p.doubles[0]]);
  assert.deepEqual(rows, [['/api/*', 401], ['/api/*', 401], ['/*', 200]]);
  for (const [route] of rows) assert.doesNotMatch(route, /12345|42|no-such-thing/, `route ${route} is a pattern, not a raw path`);
});

test('successful /feeds/ reads are sampled 1 in FEED_SAMPLE with a weight; failures are always written', async () => {
  const {points, ANALYTICS} = sink(), original = globalThis.fetch, random = Math.random;
  globalThis.fetch = async url => String(url).includes('missing') ? new Response('no', {status: 404}) : Response.json({ok: true});
  try {
    Math.random = () => 0.99;   // not sampled
    assert.equal((await worker.fetch(new Request(ORIGIN + '/feeds/conditions/latest.json'), {ANALYTICS})).status, 200);
    assert.equal(of(points, 'request').length, 0);
    Math.random = () => 0;      // sampled
    assert.equal((await worker.fetch(new Request(ORIGIN + '/feeds/conditions/latest.json'), {ANALYTICS})).status, 200);
    Math.random = () => 0.99;
    assert.equal((await worker.fetch(new Request(ORIGIN + '/feeds/conditions/missing.json'), {ANALYTICS})).status, 404);
  } finally { globalThis.fetch = original; Math.random = random; }
  assert.deepEqual(of(points, 'request').map(p => [p.blobs[1], p.doubles[0], p.doubles[2]]), [['/feeds/*', 200, FEED_SAMPLE], ['/feeds/*', 404, 1]]);
});

test('without the binding nothing is written, and a failing dataset never breaks a response', async () => {
  assert.equal((await worker.fetch(new Request(ORIGIN + '/api/health'), {ASSETS})).status, 200);
  const broken = {writeDataPoint() { throw Error('dataset unavailable'); }};
  assert.equal((await worker.fetch(new Request(ORIGIN + '/api/health'), {ANALYTICS: broken, ASSETS})).status, 200);
  assert.doesNotThrow(() => writePoint(undefined, 'request', {blobs: [], doubles: []}));
});

test('queue batches and dead letters write a queue_batch point with counts only', async () => {
  const {sql, adapter} = database(), {points, ANALYTICS} = sink();
  const date = new Intl.DateTimeFormat('en-CA', {timeZone: 'America/Los_Angeles'}).format(new Date(Date.now() + 2 * 86400000));
  sql.prepare('INSERT INTO trips(id,owner,region,point,species,date,start_hour,end_hour,wind_limit,gust_limit,sea_limit,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)').run('t1', 'alice', 'morro-bay', 'north', 'reef', date, 7, 13, 8, 12, 3, new Date().toISOString());
  const batch = (queue, bodies) => ({queue, messages: bodies.map(body => ({body, attempts: 1, ack() {}, retry() {}})), ackAll() {}, retryAll() {}});
  const original = globalThis.fetch; globalThis.fetch = async () => Response.json({}, {status: 503});
  try {
    await quietly(() => worker.queue(batch(TRIP_QUEUE, [{owner: 'alice', publication: 'p'}]), {DB: adapter, ANALYTICS}));
    await quietly(() => worker.queue(batch(TRIP_DLQ, [{owner: 'alice', publication: 'p'}, {owner: 'bob', publication: 'p'}]), {DB: adapter, ANALYTICS}));
  } finally { globalThis.fetch = original; sql.close(); }
  const [ok, dead] = of(points, 'queue_batch');
  assert.deepEqual(ok.blobs, ['queue_batch', TRIP_QUEUE, 'ok']);
  assert.deepEqual(ok.doubles.slice(0, 9), [1, 1, 0, 0, 1, 1, 0, 0, 1]);
  assert.deepEqual(dead.blobs, ['queue_batch', TRIP_DLQ, 'dead']);
  assert.equal(dead.doubles[0], 2);
  assert.doesNotMatch(JSON.stringify(points), /alice|bob/);
});

test('each cron run writes one cron point; a failed part fails the invocation and is recorded', async () => {
  const {points, ANALYTICS} = sink(), original = globalThis.fetch;
  const at = new Date(Date.now() - 5 * 60000).toISOString();
  globalThis.fetch = async () => Response.json({completed_at: at, published_at: at, run_id: '1'});
  try {
    const pending = [];
    await quietly(() => worker.scheduled({cron: '*/15 * * * *'}, {ANALYTICS}, {waitUntil: p => pending.push(p)}));
    const [run] = of(points, 'cron');
    assert.deepEqual(run.blobs, ['cron', '*/15 * * * *', 'none', 'no-queue', 'no-db', 'disabled'], 'blob6: the advisor hook, off by default');
    assert.equal(run.doubles[2], 5, 'feed age in minutes');
    // The trip producer throws (a broken D1): the invocation fails, the point says so.
    const broken = {prepare() { throw Error('D1 down'); }};
    await assert.rejects(quietly(() => worker.scheduled({cron: '*/15 * * * *'}, {ANALYTICS, DB: broken, TRIP_QUEUE: {sendBatch() {}}}, {waitUntil() {}})), /cron run failed/);
    assert.deepEqual(of(points, 'cron')[1].blobs.slice(3), ['error', 'failed', 'disabled']);
    // With the advisor on, its outcome lands in blob6: the relay check cannot store its state in a broken D1.
    await assert.rejects(quietly(() => worker.scheduled({cron: '*/15 * * * *'}, {ANALYTICS, DB: broken, TRIP_QUEUE: {sendBatch() {}}, TEXT_ADVISOR_ENABLED: 'true', BLUEBUBBLES_URL: 'https://relay.example.test'}, {waitUntil() {}})), /cron run failed/);
    assert.equal(of(points, 'cron')[2].blobs[5], 'partial');
    const {adapter} = database();
    await quietly(() => worker.scheduled({cron: '*/15 * * * *'}, {ANALYTICS, DB: adapter, TEXT_ADVISOR_ENABLED: 'true'}, {waitUntil() {}}));
    assert.equal(of(points, 'cron')[3].blobs[5], 'ok');
  } finally { globalThis.fetch = original; }
});

test('advisor_turn and publish points carry intents, outcomes, counts and timings, never ids or text', async () => {
  const {recordAdvisorTurn, recordPublish} = await import('../server/advisor/analytics.ts');
  const {points, ANALYTICS} = sink();
  recordAdvisorTurn({ANALYTICS}, {intent: 'report.count_board', outcome: 'done', ms: 1234, actions: 3, sends: 2, retries: 1});
  recordAdvisorTurn({ANALYTICS}, {intent: 'call me at +18055550100', outcome: 'c_0123 failed!', ms: 5, actions: 0, sends: 0, retries: 0});
  recordPublish({ANALYTICS}, {kind: 'photo', outcome: 'posted', ms: 800});
  recordPublish({ANALYTICS}, {kind: 'daily', outcome: 'partial', ms: Number.NaN});
  const [turn, odd] = of(points, 'advisor_turn'), [post, partial] = of(points, 'publish');
  assert.deepEqual(turn, {indexes: ['advisor_turn'], blobs: ['advisor_turn', 'report.count_board', 'done'], doubles: [1234, 3, 2, 1]});
  assert.deepEqual(odd.blobs, ['advisor_turn', 'other', 'other'], 'free text is never written');
  assert.deepEqual(post, {indexes: ['publish'], blobs: ['publish', 'photo', 'posted'], doubles: [800]});
  assert.deepEqual(partial.doubles, [0]);
  assert.doesNotMatch(JSON.stringify(points), /8055550100|c_0123/);
  assert.doesNotThrow(() => recordAdvisorTurn(undefined, {intent: 'x', outcome: 'done', ms: 1, actions: 0, sends: 0, retries: 0}));
});

test('the dataset binding is added only with ENABLE_ANALYTICS, and log sampling stays within 0..1', () => {
  const text = readFileSync(new URL('../wrangler.jsonc', import.meta.url), 'utf8'), id = '12345678-1234-1234-1234-123456789abc';
  assert.equal(features({}).analytics, false);
  assert.equal(features({ENABLE_ANALYTICS: 'true'}).analytics, true);
  assert.equal(deployConfig(text, id, 'skippercast-feeds').analytics_engine_datasets, undefined);
  assert.deepEqual(deployConfig(text, id, 'skippercast-feeds', '', {analytics: true}).analytics_engine_datasets, [{binding: 'ANALYTICS', dataset: DATASET}]);
  const base = JSON.parse(stripJsonComments(text));
  assert.equal(base.analytics_engine_datasets, undefined);
  assert.equal(base.observability.enabled, true);
  assert.ok(base.observability.head_sampling_rate > 0 && base.observability.head_sampling_rate <= 1);
  const workflow = readFileSync(new URL('../.github/workflows/deploy-cloudflare.yml', import.meta.url), 'utf8');
  assert.match(workflow, /ENABLE_ANALYTICS: \$\{\{ vars\.ENABLE_ANALYTICS \}\}/);
});
