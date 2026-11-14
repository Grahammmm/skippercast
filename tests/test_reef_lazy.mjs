// SC-PERF-LAZY-1: the 15 MB reef export is fetched after the map's first paint, never silently on Save-Data or a slow link, and the
// brief ranks without it. Offline: the loader, the link and the clock are stubs; the paths are real (web/reef-lazy.ts, web/ranking.ts).
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import util from 'node:util';
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
  assert.ok(measuredBytesPerSecond([{bytes: 312_000, start: 0, end: 9000}]) < SLOW_BYTES_PER_S, 'one big slow first request is enough to judge');
  assert.deepEqual(linkVerdict(undefined, [{bytes: 312_000, start: 0, end: 9000}]), {slow: true, why: 'slow-measured'});
  assert.deepEqual(linkVerdict(undefined, [{bytes: 312_000, start: 0, end: 300}]), {slow: false}, 'the same request on a fast link is fine');
  assert.equal(measuredBytesPerSecond([{bytes: 60_000, start: 0, end: 9000}]), null, 'one small request is too little to judge');
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

test('reef fetch failing: habitat is visibly unavailable without atlas picks, and Try again loads it', async () => {
  const s = setup({fail: true});
  const done = requestReefPublication('morro-bay', s.deps); s.map.go(); s.idle.go(); await done;
  assert.equal(s.calls.fetch, 1);
  assert.deepEqual({...reefPublication.value}, {state: 'unavailable', region: 'morro-bay'});
  const r = ranking(inputs(reefPublication.value));
  assert.equal(r.source, null); assert.deepEqual(r.picks, []);
  assert.equal(r.habitatUnavailable, true); assert.equal(r.empty, 'Reviewed habitat unavailable');
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

test('one measured slow first request: offer only, zero export fetches until the tap', async () => {
  const s = setup({link: linkVerdict(undefined, [{bytes: 312_000, start: 0, end: 9000}])});
  const done = requestReefPublication('morro-bay', s.deps); s.map.go(); s.idle.go(); await done;
  assert.equal(s.calls.fetch, 0);
  assert.equal(reefPublication.value.state, 'offer'); assert.equal(reefPublication.value.why, 'slow-measured');
  await acceptReefLoad('morro-bay', s.loader);
  assert.equal(s.calls.fetch, 1);
});

test('Save-Data / 3g: the offer shows without waiting for a map paint (terrain-first visits never mount Chart)', async () => {
  const s = setup({link: {slow: true, why: 'save-data'}});
  await requestReefPublication('morro-bay', s.deps); // the map gate is never released
  assert.equal(s.calls.fetch, 0);
  assert.equal(reefPublication.value.state, 'offer');
});

test('an older region load still running cannot overwrite a newer deferred request', async () => {
  const { loadReefPublication } = await import('../web/ranking.ts');
  const s = setup(), old = gate();
  const a = loadReefPublication('morro-bay', async () => { await old.p; return {targets: [], areas: [], publication: {}}; });
  const b = requestReefPublication('santa-barbara', s.deps);
  await tick();
  old.go(); await a;
  assert.deepEqual({...reefPublication.value}, {state: 'deferred', region: 'santa-barbara'}, 'the stale Morro Bay answer is dropped');
  s.map.go(); s.idle.go(); await b;
  assert.equal(s.calls.fetch, 1, 'Santa Barbara still loads');
  assert.equal(reefPublication.value.region, 'santa-barbara');
});

test('a region switch while the old region is still loading: the old answer does not overwrite the new deferred state, and the new region still loads', async () => {
  const s = setup();
  const slow = gate();
  const published = {targets: [], areas: [], publication: {export_sha256: 'c'.repeat(64)}};
  const { loadReefPublication } = await import('../web/ranking.ts');
  const a = requestReefPublication('morro-bay', {...s.deps, mapIdle: async () => {}, idle: async () => {},
    load: async region => { await loadReefPublication(region, async () => { await slow.p; return published; }); }});
  await tick(); await tick();
  assert.equal(reefPublication.value.state, 'loading');
  const b = requestReefPublication('santa-barbara', s.deps);
  await tick();
  slow.go(); await a;
  assert.deepEqual({...reefPublication.value}, {state: 'deferred', region: 'santa-barbara'}, "A's late answer must not replace B's deferred state");
  s.map.go(); s.idle.go(); await b;
  assert.equal(reefPublication.value.state, 'ready');
  assert.equal(reefPublication.value.region, 'santa-barbara');
});

test('a 2d or 3d presentation never mounts the Chart, so the terrain stage releases the first-idle signal itself', () => {
  const stage = readFileSync(new URL('../web/map/stage.ts', import.meta.url), 'utf8');
  assert.match(stage, /import \{markMapIdle\} from '\.\.\/map-ready\.ts'/);
  const mount = stage.slice(stage.indexOf('async function mount()'));
  assert.match(mount.slice(0, mount.indexOf('const visibility')), /finally \{[^}]*markMapIdle\(\)/s);
});

// RF1651-6: "same origin" is a parsed scheme + host + port, never a text prefix of the resource URL.
const row = (name, bytes = 300_000, start = 0, end = 9000) => ({name, transferSize: bytes, startTime: start, responseEnd: end});
const timingsOf = (entries, origin) => pageTimings({getEntriesByType: () => entries}, origin);
const BAD = {bytes: 300_000, start: 0, end: 9000};

test('foreign_origin_prefix_is_not_local: a lookalike or credentialed URL that starts with the page origin is left out', () => {
  const foreign = ['https://x.test.cdn.invalid/data', 'https://x.testing/a', 'https://x.test@evil.invalid/a', 'https://x.test:evil@evil.invalid/a'];
  for (const name of foreign) assert.deepEqual(timingsOf([row(name)], 'https://x.test'), [], name);
  assert.deepEqual(timingsOf([row('https://x.test/a.js', 300_000, 5, 50)], 'https://x.test'), [{bytes: 300_000, start: 5, end: 50}]);
  assert.deepEqual(linkVerdict(undefined, timingsOf([row('https://x.test.cdn.invalid/data')], 'https://x.test')), {slow: false}, 'foreign-only rows invent no slowdown');
});

test('scheme_and_effective_port_are_identity: case, default port, path, query and hash do not matter; another scheme or port does', () => {
  const ok = ['https://X.TEST/a', 'https://x.test:443/a', 'https://x.test/a/b?q=1#h', 'https://x.test'];
  for (const name of ok) assert.deepEqual(timingsOf([row(name)], 'https://x.test'), [BAD], name);
  for (const name of ['http://x.test/a', 'https://x.test:8443/a', 'wss://x.test/a']) assert.deepEqual(timingsOf([row(name)], 'https://x.test'), [], name);
  assert.deepEqual(timingsOf([row('https://x.test:8443/a')], 'https://x.test:8443'), [BAD], 'a non-default port page matches its own port');
  assert.deepEqual(timingsOf([row('https://x.test/a')], 'https://x.test:8443'), []);
  const rows = [row('https://x.test/1', 1, 0, 5), row('https://x.test.evil.invalid/2', 2, 0, 5), row('https://x.test/3', 3, 1, 6)];
  assert.ok(util.isDeepStrictEqual(timingsOf(rows, 'https://x.test'), [{bytes: 1, start: 0, end: 5}, {bytes: 3, start: 1, end: 6}]), 'accepted values and order are kept');
});

test('malformed_row_does_not_erase_siblings: bad names are skipped one by one; a bad origin matches nothing; no origin keeps timing-only behaviour', () => {
  const rows = [row('not a url'), row('/relative/path'), row('data:text/plain,hello'), row(undefined), row('https://x.test/good'), row('https://[bad/')];
  assert.deepEqual(timingsOf(rows, 'https://x.test'), [BAD], 'one good row survives the bad ones');
  for (const origin of ['not an origin', 'null', 'data:text/plain,x', 'file:///tmp/a']) {
    assert.deepEqual(timingsOf([row('https://x.test/good'), row('file:///tmp/a'), row('data:text/plain,x')], origin), [], `origin ${origin}`);
  }
  for (const origin of [undefined, '']) assert.deepEqual(timingsOf([row('anything at all'), row('https://other.test/a')], origin), [BAD, BAD], `origin ${JSON.stringify(origin)}`);
  assert.deepEqual(pageTimings(undefined, 'https://x.test'), []);
  assert.deepEqual(pageTimings({getEntriesByType: () => { throw new Error('no timing API'); }}, 'https://x.test'), []);
  assert.deepEqual(pageTimings({getEntriesByType: () => undefined}, 'https://x.test'), []);
});

test('local_speed_not_foreign_latency_controls_gate: fast local plus slow foreign loads once; slow local offers; foreign-only does not offer', async () => {
  const run = async entries => {
    const s = setup();
    s.deps.link = () => linkVerdict(undefined, timingsOf(entries, 'https://x.test'));
    const done = requestReefPublication('morro-bay', s.deps);
    s.map.go(); s.idle.go(); await done;
    return s;
  };
  const fast = row('https://x.test/a.js', 300_000, 0, 1000), slowForeign = row('https://x.test.cdn.invalid/data', 300_000, 0, 9000);
  let s = await run([fast, slowForeign]);
  assert.equal(s.calls.fetch, 1, 'the fast local download decides, so the reef loads by itself');
  assert.equal(reefPublication.value.state, 'ready');
  s = await run([slowForeign]);
  assert.equal(s.calls.fetch, 1, 'foreign-only rows are no measurement, so no offer');
  assert.equal(reefPublication.value.state, 'ready');
  s = await run([row('https://x.test/a.js', 300_000, 0, 9000)]);
  assert.equal(s.calls.fetch, 0, 'a genuinely slow local download still gets the offer');
  assert.equal(reefPublication.value.state, 'offer'); assert.equal(reefPublication.value.why, 'slow-measured');
});

test('connection_and_cache_policy_unchanged: cache hits, empty spans and small totals are left out; Save-Data and slow types still win', () => {
  assert.deepEqual(timingsOf([row('https://x.test/a', 0, 0, 9000), row('https://x.test/b', 300_000, 9000, 9000), row('https://x.test/c', 300_000, 9000, 10)], 'https://x.test'), []);
  assert.deepEqual(linkVerdict(undefined, timingsOf([row('https://x.test/a', 60_000, 0, 9000)], 'https://x.test')), {slow: false}, 'too small a total to judge');
  const fastLocal = timingsOf([row('https://x.test/a', 300_000, 0, 300)], 'https://x.test');
  assert.deepEqual(linkVerdict({saveData: true}, fastLocal), {slow: true, why: 'save-data'});
  assert.deepEqual(linkVerdict({effectiveType: '3g'}, []), {slow: true, why: 'slow-type'});
  const input = [row('https://x.test/a'), row('https://evil.invalid/b')], before = JSON.stringify(input);
  timingsOf(input, 'https://x.test');
  assert.equal(JSON.stringify(input), before, 'the timing buffer is not mutated');
});
