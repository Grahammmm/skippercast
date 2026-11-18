// F21-18 / SCA-596: an incomplete performance capture is inconclusive, not a result. Contract:
//   startup  measureStartup() records whether the network went quiet or the loop ended at the deadline, and which JSON
//            bodies could not be read (`quiet`: boolean, `incomplete`: paths); incomplete samples are reported apart
//            from the completed byte totals.
//   reef     a variant's median is comparable only over runs that loaded successfully AND returned the requested
//            representation (slim run used slim, full run used full); a timeout, load error or slim-to-full fallback
//            never yields a passing comparable result.
// Offline: a fake Playwright page (no browser, no network) and synthetic per-run records. The two tools are measurement
// scripts; no speed of any real page or browser is measured here.
//
// Controls (all pass; this file never asserts the defect is desired):
//   valid control     a reference measurer / comparison that follows the contract has no gaps.
//   affected control  a synthetic stand-in with today's shape (swallowed body failures, no quiet marker, medians over all
//                     runs) is reported with each gap by the same checker.
//   baseline receipt  the real measureStartup() and the median section of scripts/reef_slim_browser.mjs are observed and
//                     their gaps printed as diagnostics (not asserted), so this file stays green before and after a fix.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {measureStartup, summarise} from '../scripts/measure_startup.mjs';

const ORIGIN = 'https://fixture.invalid';
const START = Date.parse('2026-11-01T00:00:00Z');

// ---- startup ----------------------------------------------------------------------------------------------------

/**
 * A fake Playwright page. `responses` are served on goto(): {path, body} (a Buffer, or an Error for a body that rejects).
 * With `hang`, one request never gets its response, so the quiet loop can only end at the deadline.
 */
function fakePage(t, {responses, hang = false}) {
  const handlers = {};
  const emit = (name, ...args) => { for (const h of handlers[name] || []) h(...args); };
  return {
    on(name, fn) { (handlers[name] ||= []).push(fn); },
    async goto() {
      const nav = {isNavigationRequest: () => true};
      emit('request', nav);
      emit('response', {request: () => nav, url: () => ORIGIN + '/map', status: () => 200, headers: () => ({'content-type': 'text/html'})});
      for (const {path, body} of responses) {
        const request = {isNavigationRequest: () => false};
        emit('request', request);
        emit('response', {request: () => request, url: () => ORIGIN + path, status: () => 200, headers: () => ({'content-type': 'application/json'}),
          body: () => (body instanceof Error ? Promise.reject(body) : Promise.resolve(body))});
      }
      if (hang) emit('request', {isNavigationRequest: () => false});
    },
    locator: () => ({first: () => ({waitFor: async () => {}})}),
    waitForTimeout: async ms => { t.mock.timers.tick(ms); },
  };
}
const GOOD = [{path: '/dist/a.json', body: Buffer.alloc(1000)}, {path: '/dist/b.json', body: Buffer.alloc(500)}];
const BROKEN = [...GOOD, {path: '/dist/c.json', body: new Error('body stream failed')}];

/** The startup contract over a measurer `(page) => result`. */
async function startupGaps(t, measure) {
  const gaps = [];
  const quietRun = await measure(fakePage(t, {responses: GOOD}), 5000);
  if (quietRun.quiet !== true) gaps.push('a capture that went quiet is not marked quiet');
  const brokenRun = await measure(fakePage(t, {responses: BROKEN}), 5000);
  if (!Array.isArray(brokenRun.incomplete) || !brokenRun.incomplete.includes('/dist/c.json')) gaps.push('a rejected body read is not reported as incomplete');
  const hungRun = await measure(fakePage(t, {responses: GOOD, hang: true}), 5000);
  if (hungRun.quiet !== false) gaps.push('a capture that ended at the deadline is not marked not-quiet');
  return gaps;
}

/** A reference measurer that follows the contract (an offline stand-in, not product code). */
async function referenceMeasure(page, timeout) {
  const entries = [], incomplete = [], reads = [], open = new Set();
  let last = Date.now();
  page.on('request', r => { open.add(r); last = Date.now(); });
  page.on('response', response => {
    open.delete(response.request()); last = Date.now();
    if (!/json/i.test(response.headers()['content-type'] || '')) return;
    const path = new URL(response.url()).pathname;
    reads.push(response.body().then(b => entries.push({path, bytes: b.length, beforeInteractive: true, live: false}), () => { incomplete.push(path); }));
  });
  const started = Date.now();
  await page.goto('/map');
  let quiet = false;
  while (Date.now() - started < timeout) {
    if (!open.size && Date.now() - last >= 2500) { quiet = true; break; }
    await page.waitForTimeout(250);
  }
  await Promise.all(reads);
  return {...summarise(entries), quiet, incomplete};
}
/** A stand-in with today's shape: body failures swallowed, no quiet/deadline marker (as the cited lines behave). */
async function swallowingMeasure(page, timeout) {
  const entries = [], reads = [], open = new Set();
  page.on('request', r => open.add(r));
  page.on('response', response => {
    open.delete(response.request());
    if (!/json/i.test(response.headers()['content-type'] || '')) return;
    reads.push(response.body().then(b => entries.push({path: new URL(response.url()).pathname, bytes: b.length, beforeInteractive: true, live: false}), () => {}));
  });
  await page.goto('/map');
  await Promise.all(reads);
  return {...summarise(entries)};
}

test('F21-18 startup valid control: the reference measurer records quiet/deadline and reports incomplete reads apart', async t => {
  t.mock.timers.enable({apis: ['Date'], now: START});
  assert.deepEqual(await startupGaps(t, referenceMeasure), []);
  const run = await referenceMeasure(fakePage(t, {responses: BROKEN}), 5000);
  assert.deepEqual([run.static, run.incomplete], [1500, ['/dist/c.json']], 'completed totals exclude the failed read');
});

test('F21-18 startup affected control: a swallowing measurer is reported with each gap', async t => {
  t.mock.timers.enable({apis: ['Date'], now: START});
  assert.deepEqual(await startupGaps(t, swallowingMeasure), [
    'a capture that went quiet is not marked quiet',
    'a rejected body read is not reported as incomplete',
    'a capture that ended at the deadline is not marked not-quiet',
  ]);
});

test('F21-18 startup baseline receipt: the real measureStartup observed against the contract (diagnostic; not asserted)', async t => {
  const real = (page, timeout) => measureStartup(page, {timeout});
  t.mock.timers.enable({apis: ['Date'], now: START});
  const ok = await real(fakePage(t, {responses: GOOD}), 5000);
  assert.equal(ok.static, 1500, 'successful body reads are awaited and counted');   // holds before and after a fix
  t.diagnostic(`measureStartup keys=${Object.keys(ok).join(',')}; gaps=${JSON.stringify(await startupGaps(t, real))}`);
});

// ---- reef comparison --------------------------------------------------------------------------------------------

const med = a => [...a].sort((x, y) => x - y)[Math.floor(a.length / 2)];
const run = (variant, outcome, usedSlim, load_ms) => ({profile: 'phone', variant, outcome, usedSlim, load_ms});

/** Reference comparison: medians only over successful runs that returned the requested representation; the rest are reported apart. */
function comparable(results, variant) {
  const rs = results.filter(r => r.variant === variant);
  const good = rs.filter(r => r.outcome === 'ok' && r.usedSlim === (variant === 'slim'));
  return {comparable: good.length > 0, median: good.length ? med(good.map(r => r.load_ms)) : null, excluded: rs.length - good.length};
}
/** What the cited median section computes: every run of the variant, whatever its outcome or representation. */
const allRuns = (results, variant) => {
  const rs = results.filter(r => r.variant === variant);
  return {comparable: true, median: med(rs.map(r => r.load_ms)), excluded: 0};
};

const FALLBACK = [run('slim', 'ok', false, 900), run('slim', 'ok', true, 100), run('slim', 'ok', true, 120), run('slim', 'ok', true, 110)];
const ERRORS = [run('slim', 'Failed to fetch', null, 5), run('slim', 'Failed to fetch', null, 6), run('slim', 'ok', true, 800)];
const ALLBAD = [run('slim', 'ok', false, 900), run('slim', 'Failed to fetch', null, 5)];

function reefGaps(compare) {
  const gaps = [];
  const a = compare(FALLBACK, 'slim');
  if (a.excluded !== 1 || a.median !== 110) gaps.push('a slim-to-full fallback run is counted in the slim median instead of being reported apart');
  const b = compare(ERRORS, 'slim');
  if (b.median !== 800 || b.excluded !== 2) gaps.push('load-error runs counted in the median or not reported apart');
  const c = compare(ALLBAD, 'slim');
  if (c.comparable !== false || c.median !== null) gaps.push('no successful matching run still produced a comparable result');
  return gaps;
}

test('F21-18 reef valid control: medians use only successful matching runs; failures are reported apart', () => {
  assert.deepEqual(reefGaps(comparable), []);
  assert.deepEqual(comparable(ALLBAD, 'slim'), {comparable: false, median: null, excluded: 2});
});

test('F21-18 reef affected control: a median over every run is reported with each gap', () => {
  assert.deepEqual(reefGaps(allRuns), [
    'a slim-to-full fallback run is counted in the slim median instead of being reported apart',
    'load-error runs counted in the median or not reported apart',
    'no successful matching run still produced a comparable result',
  ]);
});

test('F21-18 reef baseline receipt: the cited median section of scripts/reef_slim_browser.mjs (diagnostic; not asserted)', t => {
  const source = readFileSync(new URL('../scripts/reef_slim_browser.mjs', import.meta.url), 'utf8');
  const section = source.slice(source.indexOf("console.log('\\nmedians')"));
  const filtersOutcome = /outcome\s*===\s*'ok'/.test(section), filtersRepresentation = /usedSlim/.test(section);
  t.diagnostic(`median section found=${section.length > 0}; filters on a successful outcome=${filtersOutcome}; checks the representation=${filtersRepresentation}`);
  assert.ok(section.length > 0, 'the median section is still where the audit cited it');
});
