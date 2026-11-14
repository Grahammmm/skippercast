// SCB-11: web/early-reads.ts starts the first verdict's reads with the page (web/app/early.ts) and hands each answer to the
// app's own first read of the same URL, once. These tests pin the reads to the paths the app asks for, and the hand-over rules.
import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {dailyPartPath} from '../dist/offline-core.js';
import {feedPath} from '../web/landing/readings.ts';
import {EARLY_READ_TTL_MS, REPORT_REGIONS, earlyReads, earlyRegion, startEarlyReads} from '../web/early-reads.ts';

const PAGE = 'https://s.test/map?region=morro-bay';
const read = path => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');

/** A page scope whose fetch records each call and answers it with a fresh Response naming the call number. */
function scope(href = PAGE) {
  const calls = [];
  const fetch = (input, init = {}) => {
    calls.push({url: String(input), init});
    if (init.signal?.aborted) return Promise.reject(init.signal.reason);
    return Promise.resolve(new Response(String(calls.length)));
  };
  return {calls, page: {fetch, location: {href}}};
}

test('the early reads are the paths the brief asks for its verdict', () => {
  const paths = earlyReads('morro-bay').map(r => r.path);
  assert.deepEqual(paths, [
    new URL('regions/morro-bay/region.json', PAGE).pathname,   // web/app/region-info.ts reads it relative to the page
    dailyPartPath('morro-bay', 'brief'),                       // web/brief/Brief.tsx readDaily
    feedPath(undefined, 'morro-bay'),                          // web/brief/Brief.tsx readFeed (conditions)
    '/api/forecast?region=morro-bay',                          // web/conditions.ts loadConditionsForecast
    '/api/coast/report',                                       // packages/coast transport.ts coastFetch
  ]);
  // The sources the paths above are copied from still name them.
  assert.match(read('web/app/region-info.ts'), /fetchFn\(`regions\/\$\{encodeURIComponent\(id\)\}\/region\.json`/);
  assert.match(read('web/conditions.ts'), /`\/api\/forecast\?region=\$\{encodeURIComponent\(region\)\}`/);
  assert.match(read('web/brief/Brief.tsx'), /readFeed\(dailyPartPath\(id, 'brief'\)/);
  assert.match(read('web/brief/Brief.tsx'), /readFeed\(feedPath\(undefined, id\)/);
  assert.match(read('packages/coast/src/transport.ts'), /credentials: 'omit', redirect: 'error'/);
  assert.deepEqual(earlyReads('morro-bay').at(-1).init, {credentials: 'omit', redirect: 'error'});
  assert.equal(earlyReads('big-sur-coast').length, 4, 'a region with no report binding does not read the report');
});

test('REPORT_REGIONS equals the regions packages/coast binds a report to', () => {
  const block = /const bindings[^=]*=\{([\s\S]*?)\n\};/.exec(read('packages/coast/src/state/report-binding.ts'));
  assert.ok(block, 'the bindings table');
  const ids = [...block[1].matchAll(/^\s*'([a-z0-9-]+)':\{/gm)].map(m => m[1]);
  assert.deepEqual([...REPORT_REGIONS].sort(), ids.sort());
});

test('only a well-formed region in the page address starts reads', () => {
  assert.equal(earlyRegion(PAGE), 'morro-bay');
  for (const href of ['https://s.test/map', 'https://s.test/map?region=', 'https://s.test/map?region=Morro', 'https://s.test/map?region=a--b',
    'https://s.test/map?region=../x', `https://s.test/map?region=${'a'.repeat(65)}`, 'not a url']) assert.equal(earlyRegion(href), null, href);
  const {calls, page} = scope('https://s.test/map');
  assert.deepEqual(startEarlyReads(page), []);
  assert.equal(calls.length, 0);
});

test('the app\'s first plain read of each URL takes the started answer, once; every other read goes to the network', async () => {
  const {calls, page} = scope();
  const started = startEarlyReads(page);
  assert.equal(started.length, 5);
  assert.equal(calls.length, 5, 'all five start at once');
  // The app's own reads: a relative path, a full URL, a signal: each takes its started answer (calls 1, 2 and 4).
  assert.equal(await (await page.fetch('regions/morro-bay/region.json', {signal: new AbortController().signal})).text(), '1');
  assert.equal(await (await page.fetch('/api/daily?region=morro-bay&part=brief')).text(), '2');
  assert.equal(await (await page.fetch(new URL('/api/forecast?region=morro-bay', PAGE))).text(), '4');
  assert.equal(await (await page.fetch('/api/coast/report', {credentials: 'omit', redirect: 'error'})).text(), '5');
  assert.equal(calls.length, 5, 'no second request');
  // A second read of the same URL, a retry with a cache mode, headers or other credentials: the network.
  await page.fetch('/api/daily?region=morro-bay&part=brief');
  await page.fetch('/feeds/conditions/regions/morro-bay/latest.json', {cache: 'reload'});
  assert.equal(calls.length, 7);
  assert.deepEqual(calls.at(-1).init, {cache: 'reload'});
  const other = scope();
  startEarlyReads(other.page);
  await other.page.fetch('/api/coast/report');  // same-origin credentials: not the report's read
  await other.page.fetch('/api/forecast?region=morro-bay', {headers: {'x-test': '1'}});
  await other.page.fetch('/api/forecast?region=morro-bay', {method: 'POST', body: 'x'});
  await other.page.fetch('/regions/morro-bay/region.json', {credentials: 'include'});
  assert.equal(other.calls.length, 9, 'each mismatch asked the network itself');
});

test('a started answer is handed over only within its time to live, and a caller\'s abort ends only its own wait', async () => {
  let now = 1000;
  const {calls, page} = scope();
  startEarlyReads(page, 'morro-bay', () => now);
  now += EARLY_READ_TTL_MS + 1;
  assert.equal(await (await page.fetch('/api/forecast?region=morro-bay')).text(), '6', 'too late: a new request');
  assert.equal(calls.length, 6);
  const aborted = new AbortController();
  aborted.abort(new Error('left the page'));
  now = 1000;
  const late = scope();
  startEarlyReads(late.page, 'morro-bay', () => now);
  await assert.rejects(late.page.fetch('/api/daily?region=morro-bay&part=brief', {signal: aborted.signal}), /left the page/);
  const pending = new AbortController(), slow = {fetch: () => new Promise(() => {}), location: {href: PAGE}};
  startEarlyReads(slow, 'morro-bay');
  const wait = slow.fetch('/api/forecast?region=morro-bay', {signal: pending.signal});
  pending.abort(new Error('timed out'));
  await assert.rejects(wait, /timed out/);
});

test('a caller\'s abort after the headers arrive still ends the reading of the body', async () => {
  // Headers at once, a body that never ends: the app's own request would reject its body read when its signal aborts.
  const stalled = () => Promise.resolve(new Response(new ReadableStream({start(controller) { controller.enqueue(new TextEncoder().encode('{')); }}),
    {status: 200, headers: {'x-origin': 'net'}}));
  const page = {fetch: stalled, location: {href: PAGE}};
  startEarlyReads(page, 'morro-bay');
  const timeout = new AbortController();
  const response = await page.fetch('/api/forecast?region=morro-bay', {signal: timeout.signal});
  assert.equal(response.ok, true);
  assert.equal(response.headers.get('x-origin'), 'net');
  const body = response.json();
  const outcome = Promise.race([body.then(() => 'resolved', error => error), new Promise(resolve => setTimeout(resolve, 2000, 'still waiting'))]);
  await new Promise(resolve => setTimeout(resolve, 10));
  timeout.abort(new DOMException('limit', 'TimeoutError'));
  assert.equal((await outcome).name, 'TimeoutError', 'the abort rejects the body read');
  // Aborted before the body is first read, and a body that finishes before any abort: both as the caller's own request.
  const early = {fetch: stalled, location: {href: PAGE}};
  startEarlyReads(early, 'morro-bay');
  const first = new AbortController();
  const got = await early.fetch('/api/daily?region=morro-bay&part=brief', {signal: first.signal});
  first.abort(new Error('left the page'));
  await assert.rejects(got.text(), /left the page/);
  const whole = scope();
  startEarlyReads(whole.page, 'morro-bay');
  const live = new AbortController();
  const answer = await whole.page.fetch('/regions/morro-bay/region.json', {signal: live.signal});
  assert.equal(await answer.text(), '1');
  live.abort(new Error('too late to matter'));
});

test('a failed early read reports nowhere until the app takes it, and then to the app', async () => {
  const page = {location: {href: PAGE}, fetch: () => Promise.reject(new TypeError('offline'))};
  const unhandled = [];
  const record = error => unhandled.push(error);
  process.on('unhandledRejection', record);
  try {
    startEarlyReads(page);
    await new Promise(resolve => setTimeout(resolve, 10));
    assert.deepEqual(unhandled, []);
    await assert.rejects(page.fetch('/api/coast/report', {credentials: 'omit', redirect: 'error'}), /offline/);
  } finally { process.off('unhandledRejection', record); }
});

test('/map\'s early script starts the reads at once, unless the app is already running', async t => {
  const saved = {location: globalThis.location, fetch: globalThis.fetch};
  t.after(() => { globalThis.location = saved.location; globalThis.fetch = saved.fetch; delete globalThis.skippercastApp; });
  for (const [running, expected] of [[true, 0], [false, 5]]) {
    const {calls, page} = scope();
    globalThis.location = page.location; globalThis.fetch = page.fetch;
    if (running) globalThis.skippercastApp = true; else delete globalThis.skippercastApp;
    await import(`../web/app/early.ts?running=${running}`);
    assert.equal(calls.length, expected, running ? 'the app asked for its files itself' : 'the five reads started');
  }
  // The app marks the page before its first read (installDegradedWatch wraps fetch, and every read follows it).
  const main = read('web/app/main.tsx');
  assert.ok(main.indexOf('.skippercastApp = true;') >= 0 && main.indexOf('.skippercastApp = true;') < main.indexOf('\ninstallDegradedWatch();'));
});
