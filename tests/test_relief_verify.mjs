import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import test from 'node:test';
import {gzipSync} from 'node:zlib';
import {tileIdToZxy, zxyToTileId} from 'pmtiles';
import {attachBottomRelief} from '../web/map/bottom-relief.ts';

const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const json = value => Buffer.from(`${JSON.stringify(value)}\n`);
const first = zxyToTileId(10, 168, 404);
const coords = [first, first + 1].map(tileIdToZxy);
const chunkName = '10/2_6.json';
const payloads = ['first raster tile', 'second raster tile'].map(s => Buffer.from(s));

function archiveFixture({changed = false, directoryHole = false} = {}) {
  // A v3 root-only directory with two distinct gzip tile payloads. Use stored
  // gzip blocks so a valid different payload takes exactly the same bytes.
  const tiles = payloads.map((bytes, i) => gzipSync(changed && i === 1 ? Buffer.from('second Raster tile') : bytes, {level: 0}));
  const directory = Buffer.from([2, ...varint(first + (directoryHole ? 2 : 0)), 1, 1, 1,
    tiles[0].length, tiles[1].length, 1, 0]);
  const header = Buffer.alloc(127);
  header.write('PMTiles');
  header[7] = 3;
  const payloadStart = header.length + directory.length;
  [header.length, directory.length, payloadStart, 0, payloadStart, 0, payloadStart,
    tiles[0].length + tiles[1].length, 2, 2, 2].forEach((n, i) => header.writeBigUInt64LE(BigInt(n), 8 + i * 8));
  header.set([1, 1, 2, 2, 10, 10], 96); // uncompressed directory, gzip tile, PNG
  return {bytes: Buffer.concat([header, directory, ...tiles]), payloadStart};
}

function varint(value) {
  const result = [];
  while (value >= 128) {
    result.push((value & 127) | 128);
    value >>>= 7;
  }
  return [...result, value];
}

const original = archiveFixture();
const archiveHash = sha(original.bytes);
const pointerPath = '/catalog/relief/north.json';
const archivePath = `/feeds/tiles/relief/north/${archiveHash}.pmtiles`;

function chart(t, {fault, status = 'reviewed', holdRoot} = {}) {
  const globals = Object.fromEntries(['document', 'MutationObserver', 'getComputedStyle'].map(key => [key, globalThis[key]]));
  Object.assign(globalThis, {
    document: {documentElement: {dataset: {}}},
    MutationObserver: class { observe() {} disconnect() {} },
    getComputedStyle: () => ({getPropertyValue: key => key.endsWith('opacity') ? '1' : 'black'}),
  });
  const served = fault === 'tile' ? archiveFixture({changed: true}) : fault === 'directory' ? archiveFixture({directoryHole: true}) : original;
  assert.equal(served.bytes.length, original.bytes.length);
  assert.deepEqual(served.bytes.subarray(0, 127), original.bytes.subarray(0, 127));
  const rows = coords.map(([, x, y], i) => [x, y, sha(payloads[i])]);
  const chunk = json(fault === 'missing digest' ? rows.slice(0, 1) : rows);
  const root = json({chunks: {[chunkName]: sha(chunk)}});
  const digestRoot = sha(root);
  const index = `/feeds/tiles/relief/north/${archiveHash}.digests/${digestRoot}/`;
  const pointer = {region: 'north', status, private: false, sha256: archiveHash, bytes: original.bytes.length,
    digest_root_sha256: fault === 'missing root' ? undefined : digestRoot, minzoom: 10, maxzoom: 10,
    bounds: [-121, 35, -120, 36], release_sha256: 'b'.repeat(64), envelope_sha256: 'c'.repeat(64),
    sources: [{id: 'fixture', rights_class: 'public', rights: {public_display: 'allowed'}, attribution: 'Fixture',
      label: 'estimated', vertical_datum: 'synthetic', survey_dates: ['2026-01-01']}],
    detail_summary: {mask: 'transparent-nodata', depth_bands: [{source_id: 'fixture', resolution_m: 10, min_depth_m: 0, max_depth_m: 90}]},
    native_support_by_zoom: {10: {tiles: 2, limit_m: 91.44, sources: []}}};
  const requests = [], unavailable = [], handedToMap = [];
  let action, overlay, handle, template;
  t.after(() => { handle?.destroy(); Object.assign(globalThis, globals); });
  return {
    requests, unavailable, handedToMap, index,
    get overlay() { return overlay; },
    async on() {
      handle = attachBottomRelief({region: 'north', page: 'https://chart.test/map',
        engine: {setOverlay(_, next) { overlay = next; if (next) template = Object.values(next.sources)[0].tiles[0]; }},
        library: {addProtocol(_, read) { action = read; }}, seafloorOn: () => false, fieldOn: () => false,
        unavailable: error => unavailable.push(error.message),
        async fetchFn(url, {headers, signal}) {
          signal.throwIfAborted();
          const path = new URL(url).pathname;
          const range = headers?.Range;
          requests.push([path, range]);
          if (path === pointerPath) return Response.json(pointer);
          if (path === index + 'root.json') {
            await holdRoot?.(signal);
            return new Response(fault === 'root' ? Buffer.concat([root, Buffer.from(' ')]) : root);
          }
          if (path === index + chunkName) {
            if (fault === 'fetch') return new Response(null, {status: 404});
            return new Response(fault === 'chunk' ? Buffer.concat([chunk, Buffer.from(' ')]) : chunk);
          }
          assert.equal(path, archivePath);
          const [, start, end] = /^bytes=(\d+)-(\d+)$/.exec(range).map(Number);
          return new Response(served.bytes.subarray(start, end + 1), {status: 206,
            headers: {'Content-Range': `bytes ${start}-${end}/${served.bytes.length}`}});
        }});
      await new Promise(resolve => setImmediate(resolve));
    },
    off() { handle.destroy(); },
    async tile(zxy, controller = new AbortController()) {
      const {data} = await action({url: template.replace('{z}/{x}/{y}', zxy.join('/'))}, controller);
      handedToMap.push(Buffer.from(data));
    },
  };
}

// Without a shared promise cache, concurrent tiles duplicate the root/chunk;
// hashing raw gzip ranges instead of the returned payload would reject both.
test('verified tiles reach the map, sharing one digest root and chunk per viewport', async t => {
  const c = chart(t);
  await c.on();
  assert.deepEqual(c.requests, [[pointerPath, undefined]]);
  assert.ok(c.overlay);
  await Promise.all(coords.map(zxy => c.tile(zxy)));
  assert.deepEqual(c.handedToMap.map(sha).sort(), payloads.map(sha).sort());
  // Exclude the original pointer and PMTiles header bootstrap, not any tile
  // ranges or verification traffic. The first cold viewport uses both.
  const bootstrap = ([path, range]) => path === pointerPath || (path === archivePath && range?.startsWith('bytes=0-'));
  assert.deepEqual(c.requests.filter(bootstrap), [[pointerPath, undefined], [archivePath, `bytes=0-${original.bytes.length - 1}`]]);
  const viewport = c.requests.filter(request => !bootstrap(request));
  assert.equal(viewport.length, coords.length + 2);
  assert.deepEqual(viewport.filter(([path]) => path !== archivePath), [[c.index + 'root.json', undefined], [c.index + chunkName, undefined]]);
  assert.deepEqual(c.unavailable, []);
});

// Every failure is reached after the existing archive/header checks. Without
// the hash chain, even JSON bytes changed only by whitespace would pass.
for (const [fault, error] of Object.entries({tile: /tile hash mismatch/, root: /root\.json hash mismatch/,
  chunk: /10\/2_6\.json hash mismatch/, fetch: /unavailable \(HTTP 404\)/,
  'missing digest': /Missing relief tile digest/, directory: /Indexed relief tile missing/})) {
  test(`${fault}: reject before handing bytes to the map and remove the whole overlay once`, async t => {
    const c = chart(t, {fault});
    await c.on();
    assert.ok(c.overlay);
    if (fault === 'tile') await c.tile(coords[0]); // previously verified relief must go too
    await assert.rejects(c.tile(coords[1]), error);
    assert.equal(c.overlay, null);
    assert.equal(c.handedToMap.length, fault === 'tile' ? 1 : 0);
    assert.equal(c.unavailable.length, 1);
    assert.match(c.unavailable[0], error);
    const count = c.requests.length;
    await assert.rejects(c.tile(coords[0]), {status: 404});
    assert.equal(c.requests.length, count);
    assert.equal(c.unavailable.length, 1);
  });
}

// Missing trusted identity and held inputs must stop at pointer selection.
for (const [options, reason] of [[{fault: 'missing root'}, /identity/], [{status: 'held'}, /unreviewed/]]) {
  test(`no archive or digest requests for ${reason.source}`, async t => {
    const c = chart(t, options);
    assert.deepEqual(c.requests, []);
    await c.on();
    assert.equal(c.overlay, undefined);
    assert.deepEqual(c.requests, [[pointerPath, undefined]]);
    assert.equal(c.unavailable.length, 1);
    assert.match(c.unavailable[0], reason);
  });
}

// A real hole is different from an indexed tile disappearing, and an
// overscaled or retired request should not start a fetch at all.
test('normal sparse tiles and overzoom stay available; switching off makes no requests', async t => {
  const c = chart(t);
  await c.on();
  await assert.rejects(c.tile(tileIdToZxy(first + 2)), {status: 404});
  const count = c.requests.length;
  await assert.rejects(c.tile([16, 168 * 64, 404 * 64]), {status: 404});
  assert.ok(c.overlay);
  assert.deepEqual(c.unavailable, []);
  c.off();
  await assert.rejects(c.tile(coords[0]), {status: 404});
  assert.equal(c.requests.length, count);
});

// Retirement must also cancel an in-flight shared fetch, not just delete the
// protocol reader. A late response must never start a chunk read or return bytes.
test('switching off during a digest request discards its late response', async t => {
  let started, release;
  const entered = new Promise(resolve => { started = resolve; });
  const pending = new Promise(resolve => { release = resolve; });
  const c = chart(t, {holdRoot: signal => { started(signal); return pending; }});
  await c.on();
  const tile = c.tile(coords[0]);
  const signal = await entered;
  const count = c.requests.length;
  c.off();
  assert.ok(signal.aborted);
  release();
  await assert.rejects(tile, {name: 'AbortError'});
  assert.equal(c.requests.length, count);
  assert.deepEqual(c.handedToMap, []);
  assert.deepEqual(c.unavailable, []);
});
