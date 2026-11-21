// F21-18 (SCA-596 / SCA-449): exercise the real collectors/reporter with
// synthetic page events and reef results. No browser, network or speed claims.
import test from 'node:test';
import assert from 'node:assert/strict';
import {EventEmitter} from 'node:events';
import {formatTable, measureStartup} from '../scripts/measure_startup.mjs';
import {captureReefRun, summariseReefRuns} from '../scripts/reef_slim_browser.mjs';

const ORIGIN = 'https://fixture.invalid';
const START = Date.parse('2026-11-01T00:00:00Z');
const TIMEOUT = 5000;
const never = () => new Promise(() => {});

function fakePage(t, {bodies = [], hang = false, readinessTimeout = false}) {
  return Object.assign(new EventEmitter(), {
    async goto() {
      const respond = (path, type, body, navigation = false) => {
        const request = {isNavigationRequest: () => navigation};
        this.emit('request', request);
        this.emit('response', {request: () => request, url: () => ORIGIN + path, status: () => 200,
          headers: () => ({'content-type': type}), body});
      };
      respond('/map', 'text/html', undefined, true);
      for (const [path, body] of bodies) respond(path, 'application/json', body);
      if (hang) this.emit('request', {isNavigationRequest: () => false});
    },
    locator: () => ({first: () => ({waitFor: async ({timeout}) => {
      if (readinessTimeout) {
        t.mock.timers.tick(timeout);
        throw Object.assign(new Error('canvas unavailable'), {name: 'TimeoutError'});
      }
    }})}),
    waitForTimeout: async ms => { t.mock.timers.tick(ms); },
  });
}

const good = ['/dist/a.json', async () => Buffer.alloc(1000)];
const slow = ['/api/a', () => new Promise(resolve => setTimeout(() => resolve(Buffer.alloc(500)), 3000))];
const broken = ['/dist/b.json', async () => { throw new Error('body stream failed'); }];
const stuck = ['/dist/c.json', never];

function startup(t, options) {
  t.mock.timers.enable({apis: ['Date', 'setTimeout'], now: START});
  return measureStartup(fakePage(t, options), {timeout: TIMEOUT});
}

test('F21-18 startup: a quiet capture waits for a slow body and keeps the static/live split', async t => {
  const run = await startup(t, {bodies: [good, slow]});
  assert.deepEqual([run.complete, run.quiet, run.deadlineReached, run.incomplete], [true, true, false, []]);
  assert.deepEqual([run.static, run.live, run.startup, run.interactive], [1000, 500, 1500, 1500]);
  assert.match(formatTable(run), /Static files \(budgeted\): .*1000 bytes/);
});

for (const [name, options, quiet, deadline, paths] of [
  ['rejected body', {bodies: [good, broken]}, true, false, ['/dist/b.json']],
  ['unanswered request', {bodies: [good], hang: true}, false, true, []],
  ['stalled body despite quiet', {bodies: [good, stuck]}, true, true, ['/dist/c.json']],
  ['canvas timeout', {bodies: [good], readinessTimeout: true}, false, true, []],
]) {
  test(`F21-18 startup: ${name} is inconclusive and cannot supply a budget total`, async t => {
    const run = await startup(t, options);
    assert.deepEqual([run.complete, run.quiet, run.deadlineReached, run.incomplete], [false, quiet, deadline, paths]);
    assert.deepEqual([run.static, run.live, run.startup, run.interactive], [null, null, null, null]);
    assert.equal(run.observed.static, 1000);
    assert.equal(run.rows[0].path, '/dist/a.json');
    const table = formatTable(run);
    assert.match(table, /Inconclusive capture/);
    assert.doesNotMatch(table, /Static files \(budgeted\)/);
    for (const path of paths) assert.ok(table.includes(path));
  });
}

const reefRun = (outcome, usedSlim, load_ms, file) => ({outcome, usedSlim, load_ms,
  longTaskMs: load_ms, longestMs: load_ms, maxTimerLagMs: load_ms, files: [{file, transfer: load_ms}]});
const fallback = reefRun('ok', false, 1, 'full');
const failed = reefRun('body stream failed', null, 2, 'failed');
const slim = ms => reefRun('ok', true, ms, 'slim');

test('F21-18 reef: a slim median and its transfer sample ignore fallback, body errors and timeouts', async t => {
  t.mock.timers.enable({apis: ['setTimeout']});
  const capture = captureReefRun({evaluate: never}, 'slim', 10);
  t.mock.timers.tick(10);
  const timedOut = await capture;
  assert.equal(timedOut.outcome, 'timeout');
  const invalid = [fallback, failed, timedOut];
  assert.deepEqual(summariseReefRuns([...invalid, slim(120), slim(100), slim(110)], 'slim'), {
    comparable: true, included: 3, excluded: 3, load_ms: 110, longTaskMs: 110,
    longestMs: 110, maxTimerLagMs: 110, transfer: 'slim:120',
  });
  assert.deepEqual(summariseReefRuns(invalid, 'slim'), {comparable: false, included: 0, excluded: 3, load_ms: null});
});

test('F21-18 reef: a full result requires explicit full representation and success', () => {
  const full = reefRun('ok', false, 800, 'full');
  const unverified = reefRun('ok', null, 1, 'unknown');
  assert.deepEqual(summariseReefRuns([failed, slim(5), unverified, full], 'full'), {
    comparable: true, included: 1, excluded: 3, load_ms: 800, longTaskMs: 800,
    longestMs: 800, maxTimerLagMs: 800, transfer: 'full:800',
  });
});
