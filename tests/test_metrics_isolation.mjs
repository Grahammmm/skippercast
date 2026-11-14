// Request metrics (server/analytics.ts metrics) are best-effort: a failure while preparing
// the data point never changes the response or replaces an escaping exception.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {Hono} from 'hono';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
const {metrics, FEED_SAMPLE} = await import('../server/analytics.ts');

const RAW_ID = 'abc';                       // sha256('abc') = ba7816bf8f01cfea414140de5dae2223...
const RAW_ID_HASH = 'ba7816bf8f01cfea';
function sink() { const points = []; return {points, ANALYTICS: {writeDataPoint: p => points.push(structuredClone(p))}}; }

/** Replace the process digest seam for one run; always restored. */
async function withDigest(digest, run) {
  Object.defineProperty(crypto.subtle, 'digest', {value: digest, configurable: true, writable: true});
  try { return await run(); } finally { delete crypto.subtle.digest; }
}
const failingDigest = () => Promise.reject(new Error('synthetic digest failure'));
async function quietly(run) {
  const {log, error, warn, info, debug} = console, lines = [];
  console.log = console.error = console.warn = console.info = console.debug = (...a) => lines.push(a.map(String).join(' '));
  try { return {value: await run(), lines}; } finally { Object.assign(console, {log, error, warn, info, debug}); }
}

/** Real Hono chain: metrics first, a stand-in for the request-id middleware, then a real handler. */
function app() {
  const hono = new Hono();
  hono.use('*', metrics);
  hono.use('*', async (c, next) => { c.set('requestId', RAW_ID); await next(); });
  hono.get('/ok', c => c.body('kept', 202, {'X-App': 'yes'}));
  hono.get('/feeds/*', c => c.body('tile', 200));
  hono.get('/getter', async (c, next) => { c.get = () => { throw Error('synthetic getter failure'); }; return c.body('kept', 202, {'X-App': 'yes'}); });
  return hono;
}
const call = (path, env) => app().fetch(new Request('https://skippercast.com' + path), env);

/** Minimal context for direct calls, so a downstream exception reaches the middleware unmapped. */
function context(env, {id = RAW_ID, status = 200} = {}) {
  return {env, res: {status, headers: new Headers()}, req: {raw: {}, method: 'GET', routeIndex: 0}, get: () => id};
}

test('digest_rejection_preserves_success_response', async () => {
  const {points, ANALYTICS} = sink();
  const response = await withDigest(failingDigest, () => call('/ok?q=secret', {ANALYTICS}));
  assert.equal(response.status, 202);
  assert.equal(await response.text(), 'kept');
  assert.equal(response.headers.get('X-App'), 'yes');
  assert.equal(points.length, 0);
  assert.doesNotMatch(JSON.stringify(points), /abc/);
});

test('instrumentation_failure_preserves_original_throwable', async () => {
  for (const sentinel of [new Error('original sentinel'), 'plain string sentinel', {code: 7}]) {
    const {points, ANALYTICS} = sink();
    await assert.rejects(
      withDigest(failingDigest, () => metrics(context({ANALYTICS}), async () => { throw sentinel; })),
      error => error === sentinel, 'the downstream throwable escapes as the same object');
    assert.equal(points.length, 0);
  }
});

test('metadata_getter_failure_is_metric_only', async () => {
  const {points, ANALYTICS} = sink();
  const response = await call('/getter', {ANALYTICS});
  assert.equal(response.status, 202);
  assert.equal(await response.text(), 'kept');
  assert.equal(response.headers.get('X-App'), 'yes');
  assert.equal(points.length, 0);
  // A header-read failure after a successful next() is equally metric-only.
  const c = context({ANALYTICS});
  c.res = {status: 200, headers: {get() { throw Error('synthetic header failure'); }}};
  await metrics(c, async () => {});
  assert.equal(points.length, 0);
});

test('absent_binding_does_not_hash', async () => {
  let digests = 0;
  const counting = () => { digests++; return Promise.reject(new Error('must not be called')); };
  const response = await withDigest(counting, () => call('/ok', {}));
  assert.equal(response.status, 202);
  assert.equal(digests, 0);
  // A healthy binding but no request id: the hash column stays empty and nothing is hashed.
  const {points, ANALYTICS} = sink();
  await withDigest(counting, () => metrics(context({ANALYTICS}, {id: ''}), async () => {}));
  assert.equal(digests, 0);
  assert.equal(points.length, 1);
  assert.equal(points[0].blobs[5], '');
});

test('healthy_metrics_keep_schema_sampling_and_error_status', async () => {
  const {points, ANALYTICS} = sink(), random = Math.random;
  try {
    assert.equal((await call('/ok', {ANALYTICS})).status, 202);
    const [point] = points;
    assert.deepEqual(point.indexes, ['request']);
    assert.deepEqual(point.blobs.slice(0, 5), ['request', '/ok', 'GET', 'none', '']);
    assert.equal(point.blobs[5], RAW_ID_HASH);
    assert.match(point.blobs[5], /^[0-9a-f]{16}$/);
    assert.deepEqual([point.doubles[0], point.doubles[2]], [202, 1]);
    assert.ok(point.doubles[1] >= 0);
    // Sampled successful /feeds/ reads carry the weight; unsampled ones write nothing.
    points.length = 0;
    Math.random = () => 0.99;
    await call('/feeds/a', {ANALYTICS});
    assert.equal(points.length, 0);
    Math.random = () => 0;
    await call('/feeds/a', {ANALYTICS});
    assert.deepEqual([points[0].blobs[1], points[0].doubles[0], points[0].doubles[2]], ['/feeds/*', 200, FEED_SAMPLE]);
    // An escaping downstream exception with healthy telemetry is recorded as 500 and still escapes unchanged.
    points.length = 0;
    const sentinel = new Error('original sentinel');
    await assert.rejects(metrics(context({ANALYTICS}), async () => { throw sentinel; }), error => error === sentinel);
    assert.equal(points.length, 1);
    assert.equal(points[0].doubles[0], 500);
    assert.equal(points[0].blobs[5], RAW_ID_HASH);
  } finally { Math.random = random; }
});

test('sink_failure_remains_best_effort', async () => {
  const points = [];
  let fail = true;
  const ANALYTICS = {writeDataPoint(p) { if (fail) throw Error('dataset unavailable'); points.push(structuredClone(p)); }};
  const {value: response, lines} = await quietly(() => call('/ok?q=secret', {ANALYTICS}));
  assert.equal(response.status, 202);
  assert.equal(await response.text(), 'kept');
  assert.equal(lines.length, 0);
  assert.doesNotMatch(lines.join('\n'), /abc|secret|\/ok/);
  fail = false;
  assert.equal((await call('/ok', {ANALYTICS})).status, 202);
  assert.equal(points.length, 1);
});
