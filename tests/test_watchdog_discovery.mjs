// Watchdog dispatch admission (server/watchdog.ts): an HTTP error or malformed active-run count is
// unknown, not "no run", so it never dispatches and fails the cron invocation. Offline: fetch is
// replaced and restored in every case; the stub never reaches a network.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {useBucket} from '../server/feeds.ts';
import {watchdog} from '../server/watchdog.ts';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
const {default: worker} = await import('../server/index.ts');

const NOW = Date.parse('2026-09-28T14:00:00Z');
const STALE = Promise.resolve({completed_at: '2026-09-28T12:30:00Z'});
const TOKEN = 'fake-token-sentinel-7731', BODY = 'upstream-body-sentinel-5521';
const API = 'https://api.github.com/repos/Grahammmm/skippercast';
const json = (value, status = 200) => new Response(JSON.stringify(value), {status});

/** Run fn with fetch answering from `answers` (status name -> Response | thunk); returns the request log. */
async function withFetch(answers, fn) {
  const real = globalThis.fetch, calls = [];
  globalThis.fetch = async (url, init = {}) => {
    const method = init.method || 'GET', text = String(url).replace(API, '');
    calls.push(`${method} ${text}`);
    if (method === 'POST') return new Response(null, {status: 204});
    const answer = answers[text.includes('status=in_progress') ? 'in_progress' : text.includes('status=queued') ? 'queued' : ''];
    if (answer === undefined) throw Error(`unexpected request ${method} ${text}`);
    return typeof answer === 'function' ? answer() : answer;
  };
  try { return await fn(calls); } finally { globalThis.fetch = real; }
}
const posts = calls => calls.filter(call => call.startsWith('POST'));
const zero = () => json({total_count: 0});

async function refused(answers, message = /^Error: watchdog run discovery (unavailable|unreadable|malformed)$/) {
  return withFetch(answers, async calls => {
    const error = await watchdog({GITHUB_TOKEN: TOKEN}, NOW, STALE).then(() => null, e => e);
    assert.ok(error, 'discovery failure rejects instead of returning an action');
    assert.match(String(error), message);
    assert.doesNotMatch(String(error) + String(error.stack), new RegExp(`${TOKEN}|${BODY}|api\\.github`), 'content-free');
    assert.deepEqual(posts(calls), [], 'no dispatch after unknown discovery');
    return calls;
  });
}

test('first_list_http_failure_never_dispatches', async () => {
  for (const status of [401, 403, 429, 503]) {
    const calls = await refused({in_progress: () => new Response(BODY, {status}), queued: zero}, /unavailable$/);
    assert.equal(calls.length, 1, `${status}: the queued list is not needed after a definitive failure`);
  }
});

test('second_list_failure_after_zero_never_dispatches', async () => {
  await refused({in_progress: zero, queued: () => new Response(BODY, {status: 503})}, /unavailable$/);
  await refused({in_progress: zero, queued: () => new Response(BODY, {status: 200})}, /unreadable$/);
  await refused({in_progress: zero, queued: () => json({workflow_runs: []})}, /malformed$/);
  await refused({in_progress: zero, queued: () => json({total_count: '0'})}, /malformed$/);
});

test('malformed_count_is_unknown_not_empty', async () => {
  const bodies = [null, [], [{total_count: 0}], 0, 'zero', true, {}, {total_count: null}, {total_count: true}, {total_count: '0'},
    {total_count: -1}, {total_count: 0.5}, {total_count: 2 ** 53}, {total_count: [0]}];
  for (const body of bodies) {
    await refused({in_progress: () => json(body), queued: zero}, /malformed$/);
    await refused({in_progress: zero, queued: () => json(body)}, /malformed$/);
  }
  // JSON cannot carry these on the wire; a controlled json() stub can.
  for (const value of [NaN, Infinity, -Infinity]) {
    await refused({in_progress: () => ({ok: true, status: 200, body: null, json: async () => ({total_count: value})}), queued: zero}, /malformed$/);
  }
});

test('two_valid_zero_counts_dispatch_once', async () => {
  await withFetch({in_progress: zero, queued: () => json({total_count: 0, workflow_runs: [], extra: 'ignored'})}, async calls => {
    assert.equal((await watchdog({GITHUB_TOKEN: TOKEN}, NOW, STALE)).action, 'dispatched');
    assert.deepEqual(posts(calls), ['POST /actions/workflows/live-conditions.yml/dispatches']);
    assert.equal(calls.length, 3);
  });
  await withFetch({in_progress: zero, queued: zero}, async calls => {
    const real = globalThis.fetch;
    globalThis.fetch = async (url, init) => init?.method === 'POST' ? new Response(null, {status: 422}) : real(url, init);
    try { assert.equal((await watchdog({GITHUB_TOKEN: TOKEN}, NOW, STALE)).action, 'dispatch-failed-422'); } finally { globalThis.fetch = real; }
  });
});

test('positive_active_count_short_circuits', async () => {
  await withFetch({in_progress: () => json({total_count: 1})}, async calls => {
    assert.equal((await watchdog({GITHUB_TOKEN: TOKEN}, NOW, STALE)).action, 'already-in_progress');
    assert.equal(calls.length, 1, 'no queued request, no dispatch');
  });
  await withFetch({in_progress: () => json({total_count: Number.MAX_SAFE_INTEGER}), queued: zero}, async calls => {
    assert.equal((await watchdog({GITHUB_TOKEN: TOKEN}, NOW, STALE)).action, 'already-in_progress');
    assert.equal(calls.length, 1);
  });
  await withFetch({in_progress: zero, queued: () => json({total_count: 3})}, async calls => {
    assert.equal((await watchdog({GITHUB_TOKEN: TOKEN}, NOW, STALE)).action, 'already-queued');
    assert.deepEqual(posts(calls), []);
    assert.equal(calls.length, 2);
  });
});

test('transport_or_parse_error_stays_a_failure', async () => {
  const down = () => { throw TypeError('fetch failed'); };
  const badJson = () => ({ok: true, status: 200, body: null, json: async () => { throw SyntaxError(`Unexpected token ${BODY}`); }});
  for (const answers of [{in_progress: down, queued: zero}, {in_progress: zero, queued: down}, {in_progress: badJson, queued: zero}, {in_progress: zero, queued: badJson}]) {
    await withFetch(answers, async calls => {
      await assert.rejects(watchdog({GITHUB_TOKEN: TOKEN}, NOW, STALE));
      assert.deepEqual(posts(calls), []);
    });
  }
  await withFetch({in_progress: zero, queued: zero}, async calls => {   // every stub was restored: a healthy run still works
    assert.equal((await watchdog({GITHUB_TOKEN: TOKEN}, NOW, STALE)).action, 'dispatched');
    assert.equal(posts(calls).length, 1);
  });
});

test('fresh_and_no_token_do_not_query_runs', async () => {
  await withFetch({}, async calls => {
    for (const completed_at of ['2026-09-28T13:40:00Z', '2026-09-28T13:15:00Z']) {   // 20 and exactly 45 minutes old
      assert.equal((await watchdog({GITHUB_TOKEN: TOKEN}, NOW, Promise.resolve({completed_at}))).action, 'none');
    }
    assert.equal((await watchdog({}, NOW, STALE)).action, 'no-token');
    assert.deepEqual(calls, []);
  });
});

test('scheduled_records_discovery_error_and_rejects', async () => {
  const points = [], ANALYTICS = {writeDataPoint: p => points.push(structuredClone(p))};
  const stale = '2026-10-05T18:00:00Z', fixed = Date.parse('2026-10-05T19:00:00Z'), realNow = Date.now;
  const FEEDS = {async get(key) {
    if (key !== 'conditions/latest.json') return null;
    return {size: 1, httpEtag: '"e"', body: new Blob(['{}']).stream(), json: async () => ({completed_at: stale})};
  }};
  const {log, error, warn} = console, lines = [];
  console.log = console.error = console.warn = (...a) => lines.push(a.map(x => typeof x === 'string' ? x : JSON.stringify(x)).join(' '));
  Date.now = () => fixed;
  try {
    await withFetch({in_progress: () => new Response(BODY, {status: 503}), queued: zero}, async calls => {
      await assert.rejects(worker.scheduled({cron: '*/15 * * * *'}, {ANALYTICS, FEEDS, GITHUB_TOKEN: TOKEN}, {waitUntil() {}}), /cron run failed/);
      assert.deepEqual(posts(calls), [], 'no dispatch');
    });
  } finally { Object.assign(console, {log, error, warn}); Date.now = realNow; useBucket({}); }
  const cron = points.filter(p => p.indexes[0] === 'cron');
  assert.equal(cron.length, 1);
  assert.equal(cron[0].blobs[2], 'error', 'watchdog action is recorded as error');
  const logged = lines.join('\n');
  assert.match(logged, /Cron watchdog failed.*watchdog run discovery unavailable/);
  assert.doesNotMatch(logged + JSON.stringify(points), new RegExp(`${TOKEN}|${BODY}`));
});
