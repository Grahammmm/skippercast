// SC1952-03: Save for offline stores the region's published land-water index and lines and both depth-contour
// files beside its shorelines (web/trip.ts packFiles), counts their bytes once (dist/offline-pack.js store),
// and keeps a listed file that would not download visible as a miss. The real dist/offline-pack.js savePack runs
// with a `more` callback that iterates the real packFiles through the real `store`; Cache Storage and fetch are
// in-memory stubs, restored after each run, and any request the test did not plan throws (no network).
import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {packFiles} from '../web/trip.ts';
import {publishedChartFiles} from '../web/chart-files.ts';
import {getRegion} from '../dist/region.js';
import {savePack} from '../dist/offline-pack.js';
import {PACK_META} from '../dist/offline-core.js';

const ORIGIN = 'https://s.test', PAGE = ORIGIN + '/map', ID = getRegion().id;
const NAMES = {
  shore: 'shoreline.geojson', shoreOverview: 'shoreline-overview.geojson', index: 'land-water.json', lines: 'land-water-lines.json',
  contours: 'depth-contours.geojson', overview: 'depth-contours-overview.geojson',
};
const ALL_SIDE = Object.values(NAMES);
const urlOf = (name, id = ID) => `${ORIGIN}/regions/${encodeURIComponent(id)}/${name}`;
const publish = (region, files) => { publishedChartFiles.value = region === null ? null : {region, files}; };
const requested = (id = ID) => packFiles(id, PAGE, ['/assets/app.js']).map(([url]) => url);
const sideRequested = (id = ID) => requested(id).filter(u => ALL_SIDE.some(n => u === urlOf(n, id)));

test.afterEach(() => publish(null));

test('chart_files: [] for the matching region requests none of the six chart side files; the rest keep their order', () => {
  publish(ID, []);
  const urls = requested();
  assert.deepEqual(sideRequested(), []);
  assert.equal(urls[0], PAGE, 'the shell first');
  assert.equal(urls.at(-1), ORIGIN + '/assets/app.js', 'hashed files last');
  assert.equal(urls.length, 5, 'shell, basemap manifest, marks, plan index, hashed file');
});

test('each of the four new files is listed or left out on its own; no file stands in for its partner', () => {
  for (const name of [NAMES.index, NAMES.lines, NAMES.contours, NAMES.overview]) {
    publish(ID, [name]);
    assert.deepEqual(sideRequested(), [urlOf(name)], `only ${name}`);
  }
  publish(ID, [NAMES.shore, NAMES.lines, NAMES.overview]);
  assert.deepEqual(sideRequested(), [NAMES.shore, NAMES.lines, NAMES.overview].map(n => urlOf(n)), 'a mixed subset, in pack order');
  publish(ID, ['poster.svg', 'future-file.json', 'LAND-WATER.JSON']);
  assert.deepEqual(sideRequested(), [], 'poster.svg, unknown names and wrong-case names are never saved');
  publish(ID, [NAMES.index, NAMES.index, NAMES.index]);
  assert.deepEqual(sideRequested(), [urlOf(NAMES.index)], 'a repeated name is requested once');
});

test('all six listed: exact URL and key pairs, in order, each once, full and overview contours both kept', () => {
  publish(ID, [...ALL_SIDE, 'poster.svg']);
  const files = packFiles(ID, PAGE, ['/assets/app.js']);
  assert.ok(files.every(([url, key]) => url === key), 'the key is the URL');
  const urls = files.map(([url]) => url);
  assert.deepEqual(urls.slice(2, 8), [NAMES.shore, NAMES.shoreOverview, NAMES.index, NAMES.lines, NAMES.contours, NAMES.overview].map(n => urlOf(n)));
  assert.equal(new Set(urls).size, urls.length, 'no duplicates');
  assert.ok(!urls.some(u => u.endsWith('poster.svg')));
});

test('the region id is encoded as the readers encode it', () => {
  publish('a b/c', [NAMES.index, NAMES.lines, NAMES.contours, NAMES.overview]);
  assert.deepEqual(sideRequested('a b/c'), [NAMES.index, NAMES.lines, NAMES.contours, NAMES.overview].map(n => `${ORIGIN}/regions/a%20b%2Fc/${n}`));
});

test('the real Morro Bay published list saves the four new files and the shorelines, without a fetch', () => {
  const region = JSON.parse(readFileSync(new URL('../dist/regions/morro-bay/region.json', import.meta.url), 'utf8'));
  assert.ok(Array.isArray(region.chart_files));
  publish('morro-bay', region.chart_files);
  assert.deepEqual(sideRequested('morro-bay'), ALL_SIDE.filter(n => region.chart_files.includes(n)).map(n => urlOf(n, 'morro-bay')));
  for (const n of [NAMES.index, NAMES.lines, NAMES.contours, NAMES.overview]) assert.ok(region.chart_files.includes(n), `Morro Bay publishes ${n}`);
});

test('an unknown, absent, malformed or other-region list fails open: every side file is requested', () => {
  const all = ALL_SIDE.map(n => urlOf(n));
  publish(null);
  assert.deepEqual(sideRequested(), all, 'nothing published yet');
  publish(ID, null);
  assert.deepEqual(sideRequested(), all, 'the region names no list');
  publish('another-region', []);
  assert.deepEqual(sideRequested(), all, 'another region\'s list says nothing');
});

// ---- the real savePack, with stubbed Cache Storage and fetch ----

class FakeCache {
  constructor() { this.map = new Map(); }
  async put(k, r) { this.map.set(String(k?.url ?? k), {bytes: Buffer.from(await r.arrayBuffer()), headers: [...r.headers]}); }
  async match(k) { const e = this.map.get(String(k?.url ?? k)); return e && new Response(e.bytes, {headers: e.headers}); }
  async keys() { return [...this.map.keys()].map(url => ({url})); }
}
class FakeCaches {
  constructor() { this.map = new Map(); }
  async open(name) { if (!this.map.has(name)) this.map.set(name, new FakeCache()); return this.map.get(name); }
  async keys() { return [...this.map.keys()]; }
  async has(name) { return this.map.has(name); }
  async delete(name) { return this.map.delete(name); }
}

/** One savePack run. `listed`: the published chart_files (null: unknown). `answers`: side-file name -> body string, 404, 'throw' or 'offline' (the worker's saved answer). */
async function run({listed, answers = {}, seed, abortOn, sessionStart = 0} = {}) {
  const saved = {caches: globalThis.caches, location: globalThis.location, document: globalThis.document, fetch: globalThis.fetch};
  const had = Object.fromEntries(Object.keys(saved).map(k => [k, k in globalThis]));
  const caches = new FakeCaches(), controller = new AbortController(), unplanned = [];
  publish(null);
  const others = new Set(requested().filter(u => !ALL_SIDE.some(n => u === urlOf(n))));   // the shell, basemap manifest, marks and plan index
  publish(listed === null ? null : ID, listed ?? []);
  await seed?.(caches);
  Object.assign(globalThis, {caches, location: new URL(PAGE), document: {getElementById: () => null}});
  const side = new Map(ALL_SIDE.map(n => [urlOf(n), n]));
  globalThis.fetch = async input => {
    const url = new URL(String(input?.url ?? input), ORIGIN + '/').href;
    if (abortOn?.(url)) controller.abort();
    if (url === ORIGIN + '/regions/index.json') return Response.json({regions: [{id: ID, config: `regions/${ID}/region.json`}]});
    if (url === `${ORIGIN}/regions/${ID}/region.json`) return Response.json({id: ID});
    if (side.has(url)) {
      const a = answers[side.get(url)];
      if (a === 'throw') throw new TypeError('transport error');
      if (a === 404) return new Response('no', {status: 404});
      if (a === 'offline') return new Response('old', {headers: {'X-SC-Offline': '2026-10-01T00:00:00.000Z'}});
      return new Response(a ?? `body of ${side.get(url)}`);
    }
    if (others.has(url)) return new Response('file');
    unplanned.push(url);
    throw new TypeError('unplanned request ' + url);
  };
  const more = async ({store, signal}) => {
    const misses = [], files = packFiles(ID, PAGE, []);
    for (const [url, key, init] of files) await store(url, key, init, misses);
    return {shell: {saved: files.length - misses.length, requested: files.length}, missing: misses, signal: signal.aborted};
  };
  try {
    const outcome = await savePack({signal: controller.signal, sessionStart, more}).then(meta => ({meta}), error => ({error}));
    const [name] = [...caches.map.keys()].filter(n => n.startsWith('sc-pack-'));
    const stored = name ? Object.fromEntries([...caches.map.get(name).map].map(([k, v]) => [k, v.bytes])) : {};
    return {...outcome, caches, name, stored, unplanned,
      storedBytes: Object.entries(stored).filter(([k]) => k !== PACK_META).reduce((n, [, b]) => n + b.length, 0)};
  } finally {
    for (const k of Object.keys(saved)) if (had[k]) globalThis[k] = saved[k]; else Reflect.deleteProperty(globalThis, k);
  }
}

test('Save stores each listed side file once under its URL, marked with the saved time; unlisted files are never requested', async () => {
  const r = await run({listed: [NAMES.index, NAMES.lines, NAMES.contours, NAMES.overview, 'poster.svg']});
  assert.equal(r.error, undefined, String(r.error));
  for (const n of [NAMES.index, NAMES.lines, NAMES.contours, NAMES.overview]) assert.equal(r.stored[urlOf(n)]?.toString(), `body of ${n}`, n);
  for (const n of [NAMES.shore, NAMES.shoreOverview, 'poster.svg']) assert.ok(!(urlOf(n) in r.stored), `${n} not listed or not a pack file`);
  assert.ok(!r.unplanned.some(u => u.endsWith('poster.svg') || ALL_SIDE.some(n => u === urlOf(n))), 'no unlisted side file or poster was requested');
  assert.deepEqual(r.meta.v2.missing, []);
  assert.equal(r.meta.v2.shell.saved, r.meta.v2.shell.requested);
});

test('one listed file answers 404, one throws, one is the worker\'s saved answer: the pack commits without them and each failed URL is listed once', async () => {
  const r = await run({listed: ALL_SIDE, answers: {[NAMES.index]: 404, [NAMES.lines]: 'throw', [NAMES.contours]: 'offline'}});
  assert.equal(r.error, undefined, String(r.error));
  assert.ok(PACK_META in r.stored, 'the pack is committed');
  for (const n of [NAMES.index, NAMES.lines, NAMES.contours]) assert.ok(!(urlOf(n) in r.stored), `${n} not stored`);
  for (const n of [NAMES.overview, NAMES.shore, NAMES.shoreOverview]) assert.ok(urlOf(n) in r.stored, `${n} stored`);
  assert.deepEqual([...r.meta.v2.missing].sort(), [NAMES.index, NAMES.lines, NAMES.contours].map(n => urlOf(n)).sort());
  assert.equal(r.meta.v2.shell.requested - r.meta.v2.shell.saved, 3);
  assert.ok(!r.meta.missing.includes(urlOf(NAMES.index)), 'a v2 miss is not moved to the top-level list');
  assert.equal(r.meta.bytes, r.storedBytes, 'bytes exclude the failed bodies');
});

test('cancelling while a side file is fetched stops the save and leaves no pack', async () => {
  const r = await run({listed: ALL_SIDE, abortOn: url => url === urlOf(NAMES.lines)});
  assert.ok(r.error, 'the save is refused');
  assert.equal(r.name, undefined, 'the candidate pack is deleted');
});

test('meta.bytes is the sum of the stored bodies (not PACK_META) for none, some and all side files, with a non-ASCII body', async () => {
  const answers = {[NAMES.index]: 'eau — océan 水', [NAMES.lines]: 'x'.repeat(1000)};
  const sizes = [];
  for (const listed of [[], [NAMES.index, NAMES.lines], ALL_SIDE]) {
    const r = await run({listed, answers});
    assert.equal(r.error, undefined, String(r.error));
    assert.equal(r.meta.bytes, r.storedBytes, `listed ${listed.length}`);
    sizes.push(r.meta.bytes);
  }
  assert.ok(sizes[0] < sizes[1] && sizes[1] < sizes[2]);
  const withIndex = await run({listed: [NAMES.index], answers});
  assert.equal(withIndex.stored[urlOf(NAMES.index)].length, Buffer.byteLength('eau — océan 水'), 'bytes, not characters');
  assert.equal(withIndex.meta.bytes - sizes[0], Buffer.byteLength('eau — océan 水'));
});

test('a recent copy of a side file is replaced by the live body and counted once; a failed replacement keeps the copy and its bytes', async () => {
  const copy = '{"copied":"from the recent-data cache, longer than the live body"}';
  const seed = async caches => {
    const recent = await caches.open('sc-data');
    await recent.put(urlOf(NAMES.index), new Response(copy, {headers: {'X-SC-Saved-At': new Date().toISOString()}}));
  };
  const fresh = await run({listed: [NAMES.index], answers: {[NAMES.index]: 'live'}, seed});
  assert.equal(fresh.stored[urlOf(NAMES.index)].toString(), 'live', 'the live body is the final one');
  assert.equal(fresh.meta.bytes, fresh.storedBytes, 'counted once at its final size');
  assert.ok(fresh.meta.files.from_session >= 1, 'the copy happened first');
  for (const a of [404, 'throw', 'offline']) {
    const failed = await run({listed: [NAMES.index], answers: {[NAMES.index]: a}, seed});
    assert.equal(failed.stored[urlOf(NAMES.index)].toString(), copy, `${a}: the copy stays`);
    assert.equal(failed.meta.bytes, failed.storedBytes, `${a}: its bytes stay, no failed body added`);
    assert.deepEqual(failed.meta.v2.missing, [urlOf(NAMES.index)], `${a}: still reported missing`);
  }
});

test('with an unknown list every side file is saved; with [] none is', async () => {
  const open = await run({listed: null});
  for (const n of ALL_SIDE) assert.ok(urlOf(n) in open.stored, n);
  const none = await run({listed: []});
  for (const n of ALL_SIDE) assert.ok(!(urlOf(n) in none.stored), n);
});
