// SC-PERF-LAZY-1: the 15 MB reef export is fetched after the map's first paint, never silently on Save-Data or a slow link, and the
// brief ranks without it. Offline: the loader, the link and the clock are stubs; the paths are real (web/reef-lazy.ts, web/ranking.ts).
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {linkVerdict, measuredBytesPerSecond, offerMegabytes, pageTimings, requestReefPublication, acceptReefLoad, mapFirstIdle, SLOW_BYTES_PER_S} from '../web/reef-lazy.ts';
import {ranking, reefPublication} from '../web/ranking.ts';

const read = path => JSON.parse(readFileSync(new URL(`../dist/${path}`, import.meta.url), 'utf8'));
const DATA = {region: {...read('regions/morro-bay/region.json'), id: 'morro-bay'}, atlas: read('data/atlas.json'), survey: null, geology: null};
const SCREEN = {status: 'ready', note: '', source: 'test', boundaries: [], until: Infinity};
const inputs = publication => ({region: 'morro-bay', profile: 'boat', target: 'lingcod', coast: 'lingcod', data: DATA, screen: SCREEN, terrain: {state: 'idle'},
  now: Date.now(), place: () => ({state: 'water'}), publication, plannerScreen: {state: 'idle'}});
const FAST = {slow: false}, EXPORT_BYTES = 15_414_929;

/** A promise whose resolution the test controls: "the map has painted" is something the test says, never a timer. */
const gate = () => { let go; const p = new Promise(r => { go = r; }); return {p, go}; };
function setup({link = FAST, size = EXPORT_BYTES, fail = false} = {}) {
  reefPublication.value = {state: 'idle'};
  const map = gate(), idle = gate(), calls = {fetch: 0, size: 0};
  const published = {targets: [], areas: [], publication: {export_sha256: 'b'.repeat(64)}};
  const loader = async () => { calls.fetch++; if (fail) throw new Error('offline'); return published; };
  const deps = {mapIdle: () => map.p, idle: () => idle.p, link: () => link, size: async () => { calls.size++; return size; },
    load: async region => { const { loadReefPublication } = await import('../web/ranking.ts'); await loadReefPublication(region, loader); }};
  return {map, idle, calls, deps, loader};
}
const tick = () => new Promise(r => setImmediate(r));

test('fast link: nothing is fetched until the map has painted and the browser is idle, then the reef data loads by itself', async () => {
  const s = setup();
  const done = requestReefPublication('morro-bay', s.deps);
  await tick();
  assert.equal(reefPublication.value.state, 'deferred');
  assert.equal(s.calls.fetch, 0, 'no download before the first paint');
  assert.equal(ranking(inputs(reefPublication.value)).empty, 'Loading ranked reef places…', 'the brief says it is loading, not that nothing exists');
  s.map.go(); await tick();
  assert.equal(s.calls.fetch, 0, 'map painted but the browser is not idle yet');
  s.idle.go(); await done;
  assert.equal(s.calls.fetch, 1);
  assert.equal(reefPublication.value.state, 'ready');
  assert.equal(s.calls.size, 0, 'a fast link never asks for the size');
});

test('Save-Data: no silent download; the brief offers "about 15 MB on Wi-Fi", keeps ranking from the built-in list, and a tap loads it', async () => {
  const s = setup({link: {slow: true, why: 'save-data'}});
  const done = requestReefPublication('morro-bay', s.deps);
  s.map.go(); s.idle.go(); await done;
  assert.equal(s.calls.fetch, 0);
  const state = reefPublication.value;
  assert.deepEqual({...state}, {state: 'offer', region: 'morro-bay', bytes: EXPORT_BYTES, why: 'save-data'});
  assert.equal(offerMegabytes(state.bytes), 15);
  const r = ranking(inputs(state));
  assert.notEqual(r.empty, 'Loading ranked reef places…', 'an offer is not a spinner');
  assert.equal(r.source, 'atlas', 'the brief still ranks, from the built-in list');
  assert.ok(r.picks.length > 0);
  await acceptReefLoad('morro-bay', s.loader);
  assert.equal(s.calls.fetch, 1);
  assert.equal(reefPublication.value.state, 'ready');
});

test('slow link: a 3g connection and a measured slow first request each get the offer, not the download', async () => {
  for (const why of ['slow-type', 'slow-measured']) {
    const s = setup({link: {slow: true, why}});
    const done = requestReefPublication('morro-bay', s.deps);
    s.map.go(); s.idle.go(); await done;
    assert.equal(s.calls.fetch, 0, why);
    assert.equal(reefPublication.value.state, 'offer'); assert.equal(reefPublication.value.why, why);
  }
  assert.deepEqual(linkVerdict({saveData: true, effectiveType: '4g'}, []), {slow: true, why: 'save-data'});
  for (const type of ['slow-2g', '2g', '3g']) assert.deepEqual(linkVerdict({effectiveType: type}, []), {slow: true, why: 'slow-type'});
  assert.deepEqual(linkVerdict({effectiveType: '4g'}, []), {slow: false});
  assert.deepEqual(linkVerdict(undefined, []), {slow: false}, 'a browser without the Network Information API is judged by its timings only');
  // 312 KB + 270 KB over 5.7 s at once: the PERF-BASELINE-1 slow-4G phone (~100 KB/s) is slow; the same bytes in 0.3 s are not.
  const slow = [{bytes: 312_000, start: 3400, end: 9100}, {bytes: 270_000, start: 3500, end: 9200}];
  assert.ok(measuredBytesPerSecond(slow) < SLOW_BYTES_PER_S);
  assert.deepEqual(linkVerdict({effectiveType: '4g'}, slow), {slow: true, why: 'slow-measured'});
  assert.deepEqual(linkVerdict({effectiveType: '4g'}, [{bytes: 312_000, start: 280, end: 350}, {bytes: 270_000, start: 360, end: 680}]), {slow: false});
  assert.equal(measuredBytesPerSecond([{bytes: 312_000, start: 0, end: 9000}]), null, 'one request is too little to judge');
  assert.equal(measuredBytesPerSecond([{bytes: 5000, start: 0, end: 9000}, {bytes: 5000, start: 0, end: 9000}]), null, 'small files say nothing about the link');
  const entries = [{name: 'https://x.test/a.js', transferSize: 300_000, startTime: 10, responseEnd: 5000}, {name: 'https://x.test/b.json', transferSize: 0, startTime: 10, responseEnd: 20},
    {name: 'https://other.test/c', transferSize: 900_000, startTime: 10, responseEnd: 20}];
  assert.deepEqual(pageTimings({getEntriesByType: () => entries}, 'https://x.test'), [{bytes: 300_000, start: 10, end: 5000}], 'cache hits and other origins are left out');
  assert.deepEqual(pageTimings({getEntriesByType: () => { throw new Error('no timing API'); }}, 'https://x.test'), []);
});

test('an unknown size still gets a plain button, with no invented number', async () => {
  const s = setup({link: {slow: true, why: 'save-data'}, size: null});
  const done = requestReefPublication('morro-bay', s.deps); s.map.go(); s.idle.go(); await done;
  assert.equal(reefPublication.value.bytes, null);
  assert.equal(offerMegabytes(null), null); assert.equal(offerMegabytes(400_000), 1);
});

test('ranking opened or a tap before the map paints: the tap wins and the waiting load does not fetch a second time', async () => {
  const s = setup();
  const done = requestReefPublication('morro-bay', s.deps);
  await tick();
  await acceptReefLoad('morro-bay', s.loader);
  assert.equal(s.calls.fetch, 1);
  s.map.go(); s.idle.go(); await done;
  assert.equal(s.calls.fetch, 1, 'the late map paint finds the data already answered');
  assert.equal(reefPublication.value.state, 'ready');
});

test('a new region while one waits: only the newest region loads', async () => {
  const s = setup();
  const a = requestReefPublication('morro-bay', s.deps);
  await tick();
  const b = requestReefPublication('santa-barbara', s.deps);
  await tick();
  s.map.go(); s.idle.go(); await Promise.all([a, b]);
  assert.equal(s.calls.fetch, 1);
  assert.equal(reefPublication.value.region, 'santa-barbara');
});

test('reef fetch failing: the brief still ranks from the built-in list, and Try again loads it', async () => {
  const s = setup({fail: true});
  const done = requestReefPublication('morro-bay', s.deps); s.map.go(); s.idle.go(); await done;
  assert.equal(s.calls.fetch, 1);
  assert.deepEqual({...reefPublication.value}, {state: 'unavailable', region: 'morro-bay'});
  const r = ranking(inputs(reefPublication.value));
  assert.equal(r.source, 'atlas'); assert.ok(r.picks.length > 0);
  let ok = 0;
  await acceptReefLoad('morro-bay', async () => { ok++; return {targets: [], areas: [], publication: {}}; });
  assert.equal(ok, 1); assert.equal(reefPublication.value.state, 'ready');
});

test("the map's own first-idle signal (or the chart failing to start) releases the load, so the brief never waits for a map that will not come", async () => {
  const { markMapIdle } = await import('../web/reef-lazy.ts');
  mapFirstIdle.value = false; reefPublication.value = {state: 'idle'};
  let loaded = 0;
  const done = requestReefPublication('morro-bay', {idle: async () => {}, link: () => FAST, load: async () => { loaded++; }});
  await tick(); await tick();
  assert.equal(loaded, 0, 'the real signal has not fired');
  markMapIdle(); await done;
  assert.equal(loaded, 1);
});
