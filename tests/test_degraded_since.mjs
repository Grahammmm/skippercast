// RF0910-3: the cost-ceiling notice's saved-copy time (web/degraded.ts). A
// X-SC-Last-Known-At before 2020-01-01 or more than SKEW_MS past the page's
// clock counts as no time: the degraded mark is still published, but such a
// time can neither date the notice nor beat a real older one.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';

const ROOT = new URL('..', import.meta.url).pathname;
const NOW = Date.parse('2026-10-05T20:00:00Z');
const iso = ms => new Date(ms).toISOString();

let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'degraded-')), 'degraded.mjs');
  await build({entryPoints: [join(ROOT, 'web/degraded.ts')], bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent'});
  mod = await import(pathToFileURL(out).href);
  return mod;
}
const mark = at => ({headers: new Headers(at === undefined ? {'X-SC-Degraded': 'cost-ceiling'} : {'X-SC-Degraded': 'cost-ceiling', 'X-SC-Last-Known-At': at})});
/** `since` after a fresh page notes each header in turn at NOW. */
async function sinceAfter(...ats) {
  const {degraded, noteResponse} = await load();
  degraded.value = null;
  for (const at of ats) noteResponse(mark(at), NOW);
  return degraded.peek();
}

test('the window is 2020-01-01 to the page clock plus five minutes', async () => {
  const {EARLIEST, SKEW_MS} = await load();
  assert.equal(EARLIEST, Date.parse('2020-01-01T00:00:00Z'));
  assert.equal(SKEW_MS, 300_000);
});

test('a real past time dates the notice, as before', async () => {
  assert.deepEqual(await sinceAfter(iso(NOW - 3_600_000)), {since: '2026-10-05T19:00:00.000Z'});
});

test('a time up to five minutes ahead is clock skew and kept; six minutes ahead is no time, the mark still shown', async () => {
  assert.deepEqual(await sinceAfter(iso(NOW + 4 * 60_000)), {since: '2026-10-05T20:04:00.000Z'});
  assert.deepEqual(await sinceAfter(iso(NOW + 5 * 60_000)), {since: '2026-10-05T20:05:00.000Z'});
  assert.deepEqual(await sinceAfter(iso(NOW + 5 * 60_000 + 1)), {since: null});
  assert.deepEqual(await sinceAfter(iso(NOW + 6 * 60_000)), {since: null});
  assert.deepEqual(await sinceAfter('2099-01-01T00:00:00Z'), {since: null});
});

test('a time before 2020 is no time; 2020-01-01 itself is kept', async () => {
  assert.deepEqual(await sinceAfter('1970-01-01T00:00:00Z'), {since: null});
  assert.deepEqual(await sinceAfter('2019-12-31T23:59:59Z'), {since: null});
  assert.deepEqual(await sinceAfter('2020-01-01T00:00:00Z'), {since: '2020-01-01T00:00:00.000Z'});
});

test('the oldest real time wins over a rejected one, in either order', async () => {
  const older = '2026-10-04T15:30:00Z', want = {since: '2026-10-04T15:30:00.000Z'};
  assert.deepEqual(await sinceAfter(older, iso(NOW + 3_600_000)), want);
  assert.deepEqual(await sinceAfter(iso(NOW + 3_600_000), older), want);
  assert.deepEqual(await sinceAfter(older, '1970-01-01T00:00:00Z'), want);
  assert.deepEqual(await sinceAfter('1970-01-01T00:00:00Z', older), want);
  // Real times still order among themselves: the older one wins whichever comes first.
  assert.deepEqual(await sinceAfter(iso(NOW - 60_000), older), want);
});

test('a missing, empty or unparseable header is no time; an unmarked response changes nothing', async () => {
  assert.deepEqual(await sinceAfter(undefined), {since: null});
  assert.deepEqual(await sinceAfter(''), {since: null});
  assert.deepEqual(await sinceAfter('not a time'), {since: null});
  const {degraded, noteResponse} = await load();
  degraded.value = null;
  noteResponse({headers: new Headers({'X-SC-Last-Known-At': iso(NOW - 60_000)})}, NOW);
  noteResponse(null, NOW);
  assert.equal(degraded.peek(), null);
  noteResponse(mark(iso(NOW - 60_000)), NOW);
  noteResponse({headers: new Headers({'X-SC-Degraded': 'other', 'X-SC-Last-Known-At': '2021-01-01T00:00:00Z'})}, NOW);
  assert.deepEqual(degraded.peek(), {since: iso(NOW - 60_000)});
  degraded.value = null;
});

test('the default clock is the real one, so a future header read through watchDegraded is no time', async () => {
  const {degraded, watchDegraded} = await load();
  degraded.value = null;
  await watchDegraded(async () => new Response('{}', mark(iso(Date.now() + 86_400_000))))('/feeds/x.json');
  assert.deepEqual(degraded.peek(), {since: null});
  degraded.value = null;
});

test('a rejected future time leaves the notice undated', async () => {
  const {degradedText} = await load();
  const state = await sinceAfter(iso(NOW + 86_400_000));
  assert.equal(degradedText(state, () => 'TIME'), 'Live data is paused for today to keep SkipperCast free; some readings are saved copies.');
  assert.equal(degradedText(await sinceAfter(iso(NOW - 60_000)), () => 'TIME'), 'Live data is paused for today to keep SkipperCast free; some readings are saved copies from TIME.');
});
