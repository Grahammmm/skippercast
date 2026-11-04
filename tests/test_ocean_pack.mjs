// SC1938-03: web/map/ocean-pack.ts saves a region's sst-analysis and wcofs-surface-forecast layers whole or not at all
// (docs/plans/offline-ocean-coverage.md D1, D2, D4, D5, D5a, D7). Synthetic manifests in the pipeline's shape.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readdirSync, readFileSync} from 'node:fs';
import test from 'node:test';
import {OCEAN_BYTE_CAP, OCEAN_LAYERS, MANIFEST_CAP, saveOcean} from '../web/map/ocean-pack.ts';
import {wcofsFeed} from './helpers/wcofs-feed.mjs';

const ORIGIN = 'https://s.test', REGION = 'test-coast', BASE = `${ORIGIN}/feeds/conditions/regions/${REGION}/`, MANIFEST = `${BASE}habitat-dynamics.json`;
const SST_FIELDS = ['latitude', 'longitude', 'temperature_c', 'analysis_error_c'];
const TIME = Date.parse('2026-10-15T12:00:00Z') / 1000, RETRIEVED = '2026-10-16T06:00:00Z';
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const grids = [{bounds: [-121, 35, -120.85, 35.2], cells: [[35.05, -120.95], [35.1, -120.9]]}, {bounds: [-120.85, 35, -120.7, 35.2], cells: [[35.05, -120.8], [35.1, -120.75]]}];
const flow = () => [0.2, -0.1];

function sstFeed({region = REGION, tile = t => t, record = r => r} = {}) {
  const tiles = grids.map(({bounds, cells}, k) => {
    const body = tile({schema_version: 1, region_id: region, layer_id: 'sst-analysis', bounds, resolution_degrees: [0.05, 0.05], fields: SST_FIELDS,
      frames: [{time: TIME, cells: cells.map(([lat, lon]) => [lat, lon, 14.5, 0.3])}]}, k);
    const bytes = Buffer.from(JSON.stringify(body));
    return {bytes, record: record({path: `habitat-tiles/sst-analysis-${k}-0-${sha(bytes).slice(0, 16)}.json`, bounds, sha256: sha(bytes), bytes: bytes.length}, k)};
  });
  const layer = {id: 'sst-analysis', kind: 'analysis', sample_at: '2026-10-15T12:00:00Z', resolution_degrees: [0.05, 0.05], fields: SST_FIELDS, status: 'ok', max_age_hours: 72,
    native_stride: 1, source_id: 'noaa-blended-sst', frames: [{time: TIME, valid_cells: 2, total_cells: 2}], tiles: tiles.map(t => t.record)};
  const source = {id: 'sst-analysis', name: 'NOAA Geo-Polar Blended night SST, 5 km', kind: 'analysis', url: 'https://coastwatch.noaa.gov/', max_age_hours: 72, status: 'ok', data_retrieved_at: RETRIEVED};
  return {layer, source, tiles};
}

/** Both layers in one manifest; `edit(manifest)` may break it; `tiles` is every tile body by URL. */
function feed({sst = {}, wcofs = {}, edit = m => m} = {}) {
  const s = sstFeed(sst), w = wcofsFeed({region: REGION, times: [TIME, TIME + 3600], grids, flow, issuedAt: '2026-10-16T03:00:00Z', retrievedAt: RETRIEVED, ...wcofs});
  const manifest = edit({schema_version: 1, region_id: REGION, generated_at: '2026-10-16T06:10:00Z',
    layers: {'sst-analysis': s.layer, ...w.manifest.layers}, sources: {'sst-analysis': s.source, ...w.manifest.sources}});
  const tiles = new Map([...s.tiles, ...w.tiles].map(t => [BASE + t.record.path, t.bytes]));
  return {manifest, manifestBytes: Buffer.from(JSON.stringify(manifest)), tiles, sstTiles: s.tiles, wcofsTiles: w.tiles};
}

/** A fetch serving the feed. `special(url)` may answer a URL itself; every request is recorded with its init. */
function server(f, {manifestResponse, special = () => undefined, delay = 0} = {}) {
  const asked = [], init = [];
  let live = 0, peak = 0;
  const fetchFn = async (url, options) => {
    asked.push(url); init.push(options);
    live++; peak = Math.max(peak, live);
    try {
      if (delay) await new Promise(r => setTimeout(r, delay));
      const own = url === MANIFEST ? manifestResponse?.() : special(url);
      if (own) return own;
      if (url === MANIFEST) return new Response(f.manifestBytes);
      return f.tiles.has(url) ? new Response(f.tiles.get(url)) : new Response('Not found', {status: 404});
    } finally { live--; }
  };
  return {fetchFn, asked, init, peak: () => peak};
}

/** A put that records every write; `fail(n, key)` may reject the n-th (1-based). */
function store(fail = () => null) {
  const writes = [];
  const put = async (key, body, headers) => {
    const error = fail(writes.length + 1, key);
    if (error) throw error;
    writes.push({key, body: Buffer.from(body), headers});
  };
  return {put, writes, keys: () => writes.map(w => w.key)};
}
const run = (f, opts = {}, serverOpts = {}) => {
  const srv = server(f, serverOpts), st = store(opts.fail), signal = opts.signal ?? new AbortController().signal;
  return {srv, st, done: () => saveOcean({regionId: REGION, origin: ORIGIN, put: st.put, signal, fetchFn: srv.fetchFn, eligible: opts.eligible, progress: opts.progress})};
};
const sstKeys = f => f.sstTiles.map(t => BASE + t.record.path), wcofsKeys = f => f.wcofsTiles.map(t => BASE + t.record.path);

test('both layers pass: tiles are written, then the manifest last from the validated bytes', async () => {
  const f = feed(), r = run(f), result = await r.done();
  assert.deepEqual([...OCEAN_LAYERS], ['sst-analysis', 'wcofs-surface-forecast']);
  assert.deepEqual(r.st.keys(), [...sstKeys(f), ...wcofsKeys(f), MANIFEST]);
  for (const layer of OCEAN_LAYERS) assert.equal(result.layers[layer].state, 'saved');
  assert.deepEqual(result.layers['sst-analysis'].tiles, {saved: 2, listed: 2});
  const sstBytes = f.sstTiles.reduce((a, t) => a + t.bytes.length, 0), wcofsBytes = f.wcofsTiles.reduce((a, t) => a + t.bytes.length, 0);
  assert.equal(result.layers['sst-analysis'].bytes, sstBytes);
  assert.equal(result.layers['wcofs-surface-forecast'].bytes, wcofsBytes);
  assert.equal(result.bytes, f.manifestBytes.length + sstBytes + wcofsBytes);
  assert.equal(result.cap_bytes, OCEAN_BYTE_CAP);
  const stored = r.st.writes.at(-1).body;
  assert.ok(stored.equals(f.manifestBytes), 'the stored manifest is the validated bytes');
  assert.deepEqual(result.manifest, {url: new URL(MANIFEST).pathname, sha256: sha(stored), bytes: stored.length, generated_at: '2026-10-16T06:10:00Z', stored: true});
  assert.ok(r.srv.init.every(i => i.cache === 'no-cache'), 'every read bypasses the HTTP cache');
  assert.ok(r.srv.peak() <= 4);
});

test('tiles are fetched at most four at a time', async () => {
  const wide = [...grids, ...grids, ...grids];
  const f = feed({wcofs: {grids: wide}}), r = run(f, {}, {delay: 5}), result = await r.done();
  assert.equal(result.layers['wcofs-surface-forecast'].tiles.listed, 6);
  assert.equal(r.srv.peak(), 4);
});

test('one bad WCOFS tile fails the whole WCOFS layer; SST and the manifest are still written', async () => {
  const cases = {
    http: {special: url => url === BASE + feed().wcofsTiles[1].record.path ? new Response('boom', {status: 500}) : undefined},
    integrity: {wcofs: {tile: (t, k) => k === 1 ? {...t, frames: t.frames.map(fr => ({...fr, cells: fr.cells.map(c => [...c.slice(0, 3), 9.9, 9.9, null])}))} : t, record: (rec, k) => k === 1 ? {...rec, sha256: '0'.repeat(64)} : rec}},
    'offline-copy': {special: url => url === BASE + feed().wcofsTiles[0].record.path ? new Response(feed().wcofsTiles[0].bytes, {headers: {'X-SC-Offline': '1'}}) : undefined},
    length: {wcofs: {record: (rec, k) => k === 0 ? {...rec, bytes: rec.bytes + 1} : rec}},
    identity: {wcofs: {tile: (t, k) => k === 1 ? {...t, region_id: 'other-coast'} : t}},
    'byte-limit': {special: url => url === BASE + feed().wcofsTiles[1].record.path ? new Response(Buffer.concat([feed().wcofsTiles[1].bytes, Buffer.from(' ')])) : undefined},
    network: {special: url => { if (url === BASE + feed().wcofsTiles[1].record.path) throw new TypeError('offline'); }},
  };
  for (const [reason, c] of Object.entries(cases)) {
    const f = feed({wcofs: c.wcofs}), r = run(f, {}, {special: c.special}), result = await r.done();
    assert.equal(result.layers['wcofs-surface-forecast'].state, 'failed', reason);
    assert.equal(result.layers['wcofs-surface-forecast'].reason, reason);
    assert.equal(result.layers['wcofs-surface-forecast'].bytes, 0, reason);
    assert.equal(result.layers['sst-analysis'].state, 'saved', reason);
    assert.deepEqual(r.st.keys(), [...sstKeys(f), MANIFEST], `${reason}: no WCOFS key written`);
    assert.equal(result.bytes, f.manifestBytes.length + result.layers['sst-analysis'].bytes, `${reason}: only written bytes are counted`);
    assert.equal(result.manifest.stored, true);
  }
});

test('declared bytes past the remaining budget, or too many tiles, skip the layer whole with no tile fetched', async () => {
  const big = (rec) => ({...rec, bytes: 4_900_000});   // 2 tiles x 4.9 MB: past what 12 MB leaves after a small SST
  const f = feed({wcofs: {grids: [...grids, ...grids], record: big}}), r = run(f), result = await r.done();
  assert.equal(result.layers['wcofs-surface-forecast'].state, 'over-cap');
  assert.equal(result.layers['sst-analysis'].state, 'saved');
  assert.ok(!r.srv.asked.some(u => wcofsKeys(f).includes(u)), 'no WCOFS tile requested');
  assert.deepEqual(r.st.keys(), [...sstKeys(f), MANIFEST]);

  // The declared total is judged against what is left after the manifest and the earlier layer.
  const exact = feed({wcofs: {record: rec => ({...rec, bytes: 1})}});
  const left = OCEAN_BYTE_CAP - exact.manifestBytes.length - exact.sstTiles.reduce((a, t) => a + t.bytes.length, 0);
  const over = feed({wcofs: {record: (rec, k) => ({...rec, bytes: k === 0 ? left : 1})}}), ro = run(over), overResult = await ro.done();
  assert.equal(overResult.layers['wcofs-surface-forecast'].state, 'over-cap', 'one byte more than the budget left');

  const many = feed({edit: m => { const l = m.layers['wcofs-surface-forecast']; l.tiles = Array.from({length: 65}, () => l.tiles[0]); return m; }});
  const rm = run(many), manyResult = await rm.done();
  assert.equal(manyResult.layers['wcofs-surface-forecast'].state, 'over-cap');
  assert.deepEqual(manyResult.layers['wcofs-surface-forecast'].tiles, {saved: 0, listed: 65});
  assert.ok(!rm.srv.asked.some(u => u.includes('wcofs-surface-forecast')));

  const fat = feed({wcofs: {record: (rec, k) => k === 0 ? {...rec, bytes: 5_000_001} : rec}}), rf = run(fat), fatResult = await rf.done();
  assert.equal(fatResult.layers['wcofs-surface-forecast'].state, 'over-cap', 'a tile over 5,000,000 bytes');
  assert.ok(!rf.srv.asked.some(u => u.includes('wcofs-surface-forecast')));
});

test('a manifest that is missing, over 1 MiB, not JSON, a saved copy or another region fails both layers and writes nothing', async () => {
  const f = feed();
  const cases = {
    http: () => new Response('Not found', {status: 404}),
    'byte-limit': () => new Response(Buffer.alloc(MANIFEST_CAP + 1, 32)),
    identity: () => new Response('not json {'),
    'offline-copy': () => new Response(f.manifestBytes, {headers: {'X-SC-Offline': '1'}}),
    network: () => { throw new TypeError('offline'); },
  };
  for (const [reason, manifestResponse] of Object.entries(cases)) {
    const r = run(f, {}, {manifestResponse}), result = await r.done();
    assert.deepEqual(result.manifest, {stored: false, reason}, reason);
    for (const id of OCEAN_LAYERS) { assert.equal(result.layers[id].state, 'failed'); assert.equal(result.layers[id].reason, 'manifest'); }
    assert.equal(result.bytes, 0);
    assert.deepEqual(r.st.writes, [], reason);
    assert.equal(r.srv.asked.length, 1, `${reason}: no tile fetched`);
  }
  const other = feed({edit: m => ({...m, region_id: 'other-coast'})}), ro = run(other), otherResult = await ro.done();
  for (const id of OCEAN_LAYERS) assert.deepEqual([otherResult.layers[id].state, otherResult.layers[id].reason], ['failed', 'identity']);
  assert.ok(!ro.srv.asked.some(u => u !== MANIFEST), 'no tile of another region\'s manifest is fetched');
  assert.deepEqual(ro.st.keys(), [MANIFEST], 'a manifest that parsed is still stored');
  const exactly = Buffer.alloc(MANIFEST_CAP, 32);
  Buffer.from(JSON.stringify({schema_version: 1, region_id: REGION, layers: {}})).copy(exactly);
  const r1 = run(f, {}, {manifestResponse: () => new Response(exactly)});
  const at = await r1.done();
  assert.equal(at.manifest.stored, true, 'exactly 1 MiB is within the cap');
  assert.deepEqual(OCEAN_LAYERS.map(id => at.layers[id].state), ['absent', 'absent']);
});

test('a layer absent from the manifest is absent; a malformed or empty one fails identity; the other still saves', async () => {
  const absent = feed({edit: m => { delete m.layers['sst-analysis']; return m; }}), ra = run(absent), result = await ra.done();
  assert.equal(result.layers['sst-analysis'].state, 'absent');
  assert.equal(result.layers['wcofs-surface-forecast'].state, 'saved');
  const bad = feed({edit: m => { m.layers['sst-analysis'].fields = ['latitude']; return m; }}), result2 = await run(bad).done();
  assert.deepEqual([result2.layers['sst-analysis'].state, result2.layers['sst-analysis'].reason], ['failed', 'identity']);
  assert.equal(result2.layers['wcofs-surface-forecast'].state, 'saved');
  const empty = feed({edit: m => { m.layers['wcofs-surface-forecast'].tiles = []; return m; }}), result3 = await run(empty).done();
  assert.deepEqual([result3.layers['wcofs-surface-forecast'].state, result3.layers['wcofs-surface-forecast'].reason], ['failed', 'identity']);
  const escaping = feed({edit: m => { m.layers['sst-analysis'].tiles[0] = {...m.layers['sst-analysis'].tiles[0], path: '../../other/habitat-tiles/sst-analysis-0123456789abcdef.json'}; return m; }});
  const re = run(escaping), escapingResult = await re.done();
  assert.equal(escapingResult.layers['sst-analysis'].reason, 'identity', 'a tile path outside the region folder');
  assert.ok(!re.st.keys().some(k => k.includes('sst-analysis')));
});

test('a rejected write is fatal and rethrown as the storage message; no later write happens', async () => {
  const f = feed(), quota = new DOMException('full', 'QuotaExceededError');
  const r = run(f, {fail: n => n === 2 ? quota : null});
  await assert.rejects(r.done(), error => {
    assert.equal(error.message, 'storage on this device is full or unavailable. Saved regions are unchanged.');
    assert.equal(error.cause, quota);
    return true;
  });
  assert.equal(r.st.writes.length, 1, 'nothing is put after the rejection');
  const manifestFails = run(f, {fail: (n, key) => key === MANIFEST ? new Error('closed') : null});
  await assert.rejects(manifestFails.done(), /storage on this device is full or unavailable/);
});

test('cancelling mid-fetch rejects with AbortError and writes nothing after the abort', async () => {
  const f = feed(), controller = new AbortController();
  const r = run(f, {signal: controller.signal}, {special: url => { if (url === wcofsKeys(f)[0]) controller.abort(); }});
  await assert.rejects(r.done(), {name: 'AbortError'});
  assert.deepEqual(r.st.keys(), sstKeys(f), 'SST was written before the abort; nothing of WCOFS or the manifest');

  const early = new AbortController(), re = run(f, {signal: early.signal});
  early.abort();
  await assert.rejects(re.done(), {name: 'AbortError'});
  assert.deepEqual(re.st.writes, []);

  const during = new AbortController(), rd = run(f, {signal: during.signal, fail: n => { if (n === 2) { during.abort(); return new Error('write failed after abort'); } return null; }});
  await assert.rejects(rd.done(), {name: 'AbortError'});
});

test('eligible decides before any tile is fetched: a why string records not-current', async () => {
  const f = feed(), seen = [];
  const r = run(f, {eligible: (id, manifest) => { seen.push([id, manifest.region_id]); return id === 'wcofs-surface-forecast' ? 'short-window' : null; }});
  const result = await r.done();
  assert.deepEqual(seen, [['sst-analysis', REGION], ['wcofs-surface-forecast', REGION]]);
  assert.deepEqual(result.layers['wcofs-surface-forecast'], {state: 'not-current', why: 'short-window', tiles: {saved: 0, listed: 2}, bytes: 0});
  assert.equal(result.layers['sst-analysis'].state, 'saved');
  assert.ok(!r.srv.asked.some(u => u.includes('wcofs-surface-forecast')), 'no WCOFS fetch made');
  assert.deepEqual(r.st.keys(), [...sstKeys(f), MANIFEST]);
  const none = await run(f, {eligible: () => 'status'}).done();
  assert.deepEqual(OCEAN_LAYERS.map(id => none.layers[id].state), ['not-current', 'not-current']);
  assert.equal(none.manifest.stored, true, 'the manifest is stored even when no layer is');
});

test('not wired: only its test imports ocean-pack, and habitat-feed exports the one layerOf', () => {
  const importers = [];
  const walk = dir => { for (const e of readdirSync(dir, {withFileTypes: true})) {
    const path = `${dir}/${e.name}`;
    if (e.isDirectory()) { if (!['node_modules', '.git', 'dist', '.worktrees'].includes(e.name)) walk(path); } else if (/\.(ts|tsx|js|mjs)$/.test(e.name) && /ocean-pack/.test(readFileSync(path, 'utf8'))) importers.push(path);
  } };
  for (const dir of ['web', 'server', 'packages', 'tests', 'scripts']) walk(new URL(`../${dir}`, import.meta.url).pathname);
  assert.deepEqual(importers.map(p => p.split('/').slice(-2).join('/')).sort(), ['tests/test_ocean_pack.mjs']);
  const feedSource = readFileSync(new URL('../web/map/habitat-feed.ts', import.meta.url), 'utf8');
  assert.equal((feedSource.match(/function layerOf\(/g) ?? []).length, 1);
  assert.match(feedSource, /export function layerOf\(/);
  assert.doesNotMatch(readFileSync(new URL('../web/map/ocean-pack.ts', import.meta.url), 'utf8'), /function layerOf|const layerOf/);
});
