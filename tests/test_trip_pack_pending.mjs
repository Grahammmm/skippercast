// RF2345-16: a Save for offline that begins while its region's Chart publication metadata is pending requests nothing until it settles,
// then saves only the listed optional files. The real v2Pack runs inside the real dist savePack; Cache Storage and fetch are in-memory stubs
// (no network, no timers), and any request the test did not plan throws.
import assert from 'node:assert/strict';
import test from 'node:test';
import {v2Pack} from '../web/trip-runtime.ts';
import {publishedChartFiles} from '../web/chart-files.ts';
import {getRegion} from '../dist/region.js';
import {savePack} from '../dist/offline-pack.js';
import {PACK_META} from '../dist/offline-core.js';

const ORIGIN = 'https://s.test', PAGE = ORIGIN + '/map', ID = getRegion().id, OLD_PACK = `sc-pack-${ID}-1`;
const SIDE = ['shoreline.geojson', 'shoreline-overview.geojson', 'land-water.json', 'land-water-lines.json', 'depth-contours.geojson', 'depth-contours-overview.geojson'];
const sideUrl = name => `${ORIGIN}/regions/${encodeURIComponent(ID)}/${name}`;
const sideOf = url => SIDE.find(n => url === sideUrl(n));
const publish = (region, files, pending) => { publishedChartFiles.value = region === null ? null : {region, files, ...pending ? {pending: true} : {}}; };
const PRE = {build: 'b1', v2: {assets: ['/assets/app.js'], static: []}};

class FakeCache {
  constructor() { this.map = new Map(); }
  async put(k, r) { this.map.set(String(k?.url ?? k), Buffer.from(await r.arrayBuffer())); }
  async match(k) { const e = this.map.get(String(k?.url ?? k)); return e && new Response(e); }
  async keys() { return [...this.map.keys()].map(url => ({url})); }
}
class FakeCaches {
  constructor() { this.map = new Map(); }
  async open(name) { if (!this.map.has(name)) this.map.set(name, new FakeCache()); return this.map.get(name); }
  async keys() { return [...this.map.keys()]; }
  async has(name) { return this.map.has(name); }
  async delete(name) { return this.map.delete(name); }
}

/** Start one real savePack + v2Pack. Returns the pending outcome, every request seen, and `release` for a held /precache.json answer. */
async function start({initial, hold = false, answers = {}} = {}) {
  const saved = {caches: globalThis.caches, location: globalThis.location, document: globalThis.document, fetch: globalThis.fetch};
  const had = Object.fromEntries(Object.keys(saved).map(k => [k, k in globalThis]));
  const caches = new FakeCaches(), controller = new AbortController(), seen = [];
  let inMore = false;   // savePack's own region-data reads before `more` are not the pack's files
  let release, begin; const started = new Promise(r => { begin = r; });   // `started`: v2Pack has been called and is now waiting
  const gate = new Promise(r => { release = r; });
  await (await caches.open(OLD_PACK)).put(PACK_META, new Response('{"old":true}'));
  publish(...initial);
  Object.assign(globalThis, {caches, location: new URL(PAGE), document: {getElementById: () => null}});
  globalThis.fetch = async input => {
    const url = new URL(String(input?.url ?? input), ORIGIN + '/').href, path = new URL(url).pathname;
    if (inMore) seen.push(url);
    if (url === ORIGIN + '/regions/index.json') return Response.json({regions: [{id: ID, config: `regions/${ID}/region.json`}]});
    if (url === `${ORIGIN}/regions/${ID}/region.json`) return Response.json({id: ID});
    if (path === '/precache.json') { if (hold) await gate; return Response.json(PRE); }
    if (sideOf(url)) { const a = answers[sideOf(url)]; if (a === 404) return new Response('no', {status: 404}); if (a === 'throw') throw new TypeError('transport'); return new Response('body of ' + sideOf(url)); }
    if (['/map', '/assets/app.js'].includes(path)) return new Response('shell ' + path);
    throw new TypeError('unplanned request ' + url);
  };
  const outcome = savePack({signal: controller.signal, sessionStart: 0,
    more: extras => { inMore = true; begin(); return v2Pack(extras, ID, getRegion().bounds, {id: ID, center: [35.37, -120.86]}); }}).then(meta => ({meta}), error => ({error}));
  const finish = async () => { const r = await outcome; for (const k of Object.keys(saved)) if (had[k]) globalThis[k] = saved[k]; else Reflect.deleteProperty(globalThis, k); return r; };
  const stored = () => { const [name] = [...caches.map.keys()].filter(n => n.startsWith('sc-pack-') && n !== OLD_PACK); return name ? [...caches.map.get(name).map.keys()] : []; };
  return {started, controller, seen, release, finish, caches, stored, sides: () => seen.map(sideOf).filter(Boolean)};
}
const tick = () => new Promise(r => setImmediate(r));
const oldKept = r => [...r.caches.map.keys()].join() === OLD_PACK && r.caches.map.get(OLD_PACK).map.has(PACK_META);
test.afterEach(() => publish(null));

test('pending_omitted_never_stores_side_files: nothing is requested while pending; an empty settled list requests none of the six', async () => {
  const run = await start({initial: [ID, null, true]});
  await run.started; await tick();
  assert.deepEqual(run.seen, [], 'no request, no store while the list is pending');
  publish(ID, []);
  const r = await run.finish();
  assert.equal(r.error, undefined, String(r.error));
  assert.deepEqual(run.sides(), [], 'no side file requested');
  assert.deepEqual(r.meta.v2.missing.filter(sideOf), [], 'no false missing entries');
  assert.ok(run.stored().includes(PAGE) && run.stored().includes(ORIGIN + '/assets/app.js'), 'the mandatory shell saved');
});

test('pending_listed_uses_settled_snapshot: exactly the captured subset is saved, in order, even if the global list changes mid-save', async () => {
  const run = await start({initial: [ID, null, true], hold: true});
  await run.started;
  publish(ID, ['land-water.json', 'shoreline.geojson', 'LAND-WATER-LINES.JSON', 'poster.svg', 'shoreline.geojson']);
  await tick();
  publish(ID, SIDE);   // another list arrives while the precache answer is held
  run.release();
  const r = await run.finish();
  assert.equal(r.error, undefined, String(r.error));
  assert.deepEqual(run.sides(), ['shoreline.geojson', 'land-water.json'], 'only the snapshot, in pack order, wrong-case/unknown/repeated names ignored');
  assert.deepEqual(r.meta.v2.missing.filter(sideOf), []);
});

test('pending_unknown_keeps_fail_open: a settled files:null admits all six; a listed 404 or throw is an optional miss; other callers are unchanged', async () => {
  let run = await start({initial: [ID, null, true], answers: {'land-water.json': 404, 'shoreline.geojson': 'throw'}});
  await run.started; publish(ID, null);
  let r = await run.finish();
  assert.equal(r.error, undefined, String(r.error));
  assert.deepEqual(run.sides(), SIDE, 'all six requested');
  assert.deepEqual(r.meta.v2.missing.filter(sideOf).sort(), ['land-water.json', 'shoreline.geojson'].map(sideUrl).sort());
  run = await start({initial: [null]});                       // unknown at the start
  r = await run.finish(); assert.equal(r.error, undefined); assert.deepEqual(run.sides(), SIDE);
  run = await start({initial: ['another-region', [], true]}); // another region pending: not this save's gate
  r = await run.finish(); assert.equal(r.error, undefined); assert.deepEqual(run.sides(), SIDE);
  run = await start({initial: [ID, ['land-water.json']]});     // already settled: the shared signal, as before
  r = await run.finish(); assert.equal(r.error, undefined); assert.deepEqual(run.sides(), ['land-water.json']);
});

test('abort_and_supersession_are_terminal: abort, custom reason, another region, null and A->B->A reject promptly and later settling fetches nothing', async () => {
  for (const [label, act, reason] of [
    ['abort while waiting', run => run.controller.abort()],
    ['custom reason', run => run.controller.abort(new Error('custom stop')), 'custom stop'],
    ['another region replaces it', () => publish('another-region', [], true)],
    ['null replaces it', () => publish(null)],
    ['A to B to A', () => { publish('another-region', [], true); publish(ID, [], true); }],
  ]) {
    const run = await start({initial: [ID, null, true]});
    await run.started; act(run);
    const r = await run.finish();
    assert.ok(r.error, `${label}: the save is refused`);
    if (reason) assert.equal(r.error.message, reason);
    publish(ID, []); publish(ID, SIDE); await tick();
    assert.deepEqual(run.seen, [], `${label}: nothing was ever requested, later settling does not revive it`);
    assert.ok(oldKept(run), `${label}: the older pack is untouched`);
  }
  const early = await start({initial: [ID, null, true]});
  await early.started; early.controller.abort();
  const r = await early.finish();
  assert.ok(r.error && early.seen.length === 0 && oldKept(early), 'an already-aborted signal');
});

test('save_rollback_after_wait_cancel: cancelling the pending gate leaves no candidate and the older pack bytes', async () => {
  const run = await start({initial: [ID, null, true]});
  await run.started; run.controller.abort();
  const r = await run.finish();
  assert.ok(r.error);
  assert.deepEqual(run.stored(), [], 'no candidate pack');
  assert.equal(run.caches.map.get(OLD_PACK).map.get(PACK_META).toString(), '{"old":true}');
});
