// SC2222-03: the brief reads the /api/daily 'brief' part (about a sixth of the 1.49 MB daily feed) on
// every map load; only when that read fails or is refused does it read the whole feed, once, with the
// same identity checks, the same gap lines and the conditions feed's buoys merged first.
import assert from 'node:assert/strict';
import test from 'node:test';
import {isDeepStrictEqual} from 'node:util';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import montereyDaily from './fixtures/brief/monterey-daily.json' with {type: 'json'};

const ROOT = new URL('..', import.meta.url).pathname;
const ID = 'monterey-point-sur', MIN = 60_000;
const INFO = {id: ID, name: 'Monterey', center: [36.62, -121.9], timezone: 'America/Los_Angeles'};
const NOW = new Date('2026-10-08T21:00:00Z');
const PART = id => `/api/daily?region=${id}&part=brief`, WHOLE = id => `/feeds/data/regions/${id}/latest.json`;
const LIVE = id => `/feeds/conditions/regions/${id}/latest.json`;

let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'brief-part-')), 'brief.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `export * from './web/brief/Brief.tsx';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: rendererPlugins,
  });
  return (mod = await import(pathToFileURL(out).href));
}

const conditionsFor = id => ({schema_version: 1, region_id: id, sources: {diablo: {id: 'diablo', name: 'NDBC 46042 every 30 min', kind: 'observation', url: '', checked_at: NOW.toISOString(), status: 'ok'}}});
const partFor = id => ({...montereyDaily, region_id: id, part: 'brief', catch_probability: null, bite_score: null});
const json = body => new Response(JSON.stringify(body), {status: 200});
/** Part answers: a body, an HTTP status, or 'throw' (network error). The whole and live feeds answer for their path's region or 503. */
const PART_FAILS = {404: 404, 500: 500, network: 'throw', regulations: id => ({...partFor(id), part: 'regulations'}),
  'other region': () => partFor('morro-bay'), 'sources array': id => ({...partFor(id), sources: []})};
function server({part = partFor, whole = true, live = true} = {}) {
  const s = {paths: [], held: null};
  s.fetch = async path => {
    path = String(path); s.paths.push(path);
    if (s.held) await new Promise(r => s.held.push(r));
    if (path.startsWith('/api/daily')) {
      const id = new URL(path, 'https://x.test').searchParams.get('region');
      if (part === 'throw') throw new TypeError('network');
      return typeof part === 'number' ? new Response('', {status: part}) : json(part(id));
    }
    const id = decodeURIComponent(path.split('/')[4]);
    if (!(path.startsWith('/feeds/data/') ? whole : live)) return new Response('', {status: 503});
    return json(path.startsWith('/feeds/data/') ? {...montereyDaily, region_id: id} : conditionsFor(id));
  };
  s.release = () => { const w = s.held; s.held = null; w.forEach(r => r()); };
  return s;
}
const daily = paths => paths.filter(p => !p.startsWith('/feeds/conditions/'));

test('edge 1 and 5: a good part is the one daily-side read; the whole feed is never requested; the conditions buoy comes first', async () => {
  const {loadDailyFeed, dailyFeed, feedGaps} = await load();
  const s = server();
  const feed = await loadDailyFeed(ID, s.fetch);
  assert.deepEqual(daily(s.paths), [PART(ID)]);
  assert.ok(!s.paths.includes(WHOLE(ID)), 'no whole-feed read');
  assert.equal(feed, dailyFeed.value);
  assert.deepEqual(feedGaps.value, []);
  assert.equal(Object.keys(feed.sources)[0], 'diablo', 'mergeFeeds unchanged: the 30-minute buoy first');
  assert.ok(feed.sources.tides, 'the part keeps its tides');
  assert.deepEqual(feed.reports, montereyDaily.reports);
});

test('edge 2: a failed or refused part falls back to one whole-feed read with today\'s brief', async () => {
  const {loadDailyFeed, briefFrom, feedGaps} = await load();
  const today = server({part: 404});
  const expected = briefFrom({info: INFO, feed: await loadDailyFeed(ID, today.fetch), coast: null, profile: 'boat', hour: null}, NOW);
  assert.ok(expected, 'the Monterey fixture builds a brief');
  for (const [name, part] of Object.entries(PART_FAILS)) {
    const s = server({part});
    const feed = await loadDailyFeed(ID, s.fetch);
    assert.deepEqual(daily(s.paths), [PART(ID), WHOLE(ID)], `${name}: the part, then the whole feed once`);
    assert.ok(isDeepStrictEqual(briefFrom({info: INFO, feed, coast: null, profile: 'boat', hour: null}, NOW), expected), `${name}: same brief as the whole feed`);
    assert.deepEqual(feedGaps.value, [], `${name}: no gap line`);
  }
});

test('edge 3: part and whole feed both failing give one daily gap line; with the conditions feed failing too, the both line', async () => {
  const {loadDailyFeed, feedGaps, FEED_GAP} = await load();
  const s = server({part: 500, whole: false});
  await loadDailyFeed(ID, s.fetch);
  assert.deepEqual(daily(s.paths), [PART(ID), WHOLE(ID)]);
  assert.equal(feedGaps.value.length, 1, 'one gap line, not two');
  assert.match(feedGaps.value[0], new RegExp(`^${FEED_GAP.daily}: tide predictions and marine alert checks are missing\\.$`));
  await loadDailyFeed(ID, server({part: 'throw', whole: false, live: false}).fetch);
  assert.deepEqual(feedGaps.value, [FEED_GAP.both]);
});

test('edge 4: a region switch while the part read is in flight: the later region wins and the stale one reads no fallback', async () => {
  const {loadDailyFeed, dailyFeed, feedGaps} = await load();
  const a = server({part: 404}), b = server();
  a.held = [];
  const first = loadDailyFeed(ID, a.fetch);
  await loadDailyFeed('morro-bay', b.fetch);
  a.release(); await first;
  assert.deepEqual(daily(a.paths), [PART(ID)], 'no whole-feed read for the stale region');
  assert.equal(dailyFeed.value.region_id, 'morro-bay');
  assert.deepEqual(daily(b.paths), [PART('morro-bay')]);
  assert.deepEqual(feedGaps.value, []);
});

test('edge 6: the SC2222-01 refresh reads the part first, and falls back the same way', async () => {
  const {loadDailyFeed, refreshDailyIfStale, dailyFeed} = await load();
  const s = server();
  await loadDailyFeed(ID, s.fetch);
  await refreshDailyIfStale(Date.now() + 31 * MIN);
  assert.deepEqual(daily(s.paths), [PART(ID), PART(ID)], 'the refresh read the part, not the whole feed');
  const f = server({part: 404});
  await loadDailyFeed(ID, f.fetch);
  await refreshDailyIfStale(Date.now() + 31 * MIN);
  assert.deepEqual(daily(f.paths), [PART(ID), WHOLE(ID), PART(ID), WHOLE(ID)]);
  assert.equal(dailyFeed.value.region_id, ID);
});
