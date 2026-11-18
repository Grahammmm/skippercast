import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {signal} from '@preact/signals';
import {attachBottomRelief} from '../web/map/bottom-relief.ts';

// Reuse the existing one-tile PMTiles directory. Retag it as PNG for the
// transport test; PMTiles returns opaque bytes, not decoded images.
const bytes = readFileSync(new URL('./fixtures/basemap/tiny.pmtiles', import.meta.url));
bytes[99] = 2;
const payloadOffset = Number(bytes.readBigUInt64LE(56));
const sha = body => createHash('sha256').update(body).digest('hex');
const hash = sha(bytes);
const chunkPath = '10/2_6.json';
const chunk = JSON.stringify([[168, 404, sha(bytes.subarray(payloadOffset))]]);
const digestRoot = JSON.stringify({chunks: {[chunkPath]: sha(chunk)}});
const digestRootHash = sha(digestRoot);
const id = 'synthetic-survey';
const pointer = region => ({region, status: 'reviewed', private: false, sha256: hash, bytes: bytes.length,
  minzoom: 10, maxzoom: 10, bounds: [-121, 35, -120, 36], release_sha256: 'b'.repeat(64),
  envelope_sha256: 'c'.repeat(64), digest_root_sha256: digestRootHash,
  sources: [{id, rights_class: 'public', rights: {public_display: 'allowed'}, attribution: 'Synthetic survey',
    label: 'estimated', vertical_datum: 'synthetic', survey_dates: ['2025-01-01']}],
  detail_summary: {mask: 'transparent-nodata', depth_bands: [{source_id: id, resolution_m: 10, min_depth_m: 0, max_depth_m: 90}]},
  native_support_by_zoom: {10: {tiles: 1, limit_m: 91.44, sources: []}}});
const tick = () => new Promise(resolve => setImmediate(resolve));

function chart(t) {
  const root = {dataset: {}};
  const old = Object.fromEntries(['document', 'getComputedStyle', 'MutationObserver'].map(k => [k, globalThis[k]]));
  let themeChanged;
  Object.assign(globalThis, {
    document: {documentElement: root},
    getComputedStyle: () => ({getPropertyValue: key => key.endsWith('opacity') ? '1' : `${root.dataset.theme ?? 'dark'}:${key}`}),
    MutationObserver: class { constructor(cb) { themeChanged = cb; } observe() {} disconnect() { themeChanged = null; } },
  });
  const errors = [], fetches = [], handles = [];
  const seafloor = signal(false), field = signal(false);
  let overlay, before, protocol, breakRange = false;
  const engine = {
    setOverlay(owner, next, anchor) { assert.equal(owner, 'bottom-relief'); overlay = next; before = anchor; },
    setRasterOpacity(id, opacity) { assert.equal(id, overlay.layers[0].id); overlay.layers[0].paint['raster-opacity'] = opacity; },
  };
  const library = {addProtocol(_, action) { protocol = action; }};
  const start = (region, reply = pointer(region)) => {
    const handle = attachBottomRelief({engine, region, library, page: 'https://chart.test/map',
      seafloorOn: () => seafloor.value, fieldOn: () => field.value, unavailable: e => errors.push(e.message),
      async fetchFn(raw, init) {
        const url = new URL(raw);
        fetches.push([url.pathname, init]);
        const digestPath = `/feeds/tiles/relief/${region}/${hash}.digests/${digestRootHash}/`;
        if (url.pathname === digestPath + 'root.json') return new Response(digestRoot);
        if (url.pathname === digestPath + chunkPath) return new Response(chunk);
        if (url.pathname === `/catalog/relief/${region}.json`) return Response.json(await reply);
        if (breakRange) return new Response(bytes); // full response must never be mistaken for a range
        const [, start, end] = /^bytes=(\d+)-(\d+)$/.exec(init.headers.Range).map(Number);
        return new Response(bytes.subarray(start, end + 1), {status: 206,
          headers: {'Content-Range': `bytes ${start}-${end}/${bytes.length}`}});
      }});
    handles.push(handle);
    return handle;
  };
  t.after(() => { handles.reverse().forEach(h => h.destroy()); Object.assign(globalThis, old); });
  const tile = (url, x = 168) => Promise.resolve().then(() => protocol({url: url.replace('{z}/{x}/{y}', `10/${x}/404`)}, new AbortController()));
  return {start, tile, errors, fetches, seafloor, field, breakRange: () => { breakRange = true; },
    theme(value) { root.dataset.theme = value; themeChanged?.(); },
    get overlay() { return overlay; }, get before() { return before; },
    get template() { return Object.values(overlay.sources)[0].tiles[0]; }};
}

test('region switches retire the old reader; a late or held pointer cannot add a source', async t => {
  const c = chart(t);
  const north = c.start('north');
  await tick();
  const northTiles = c.template;
  assert.deepEqual(c.fetches.map(([url]) => url), ['/catalog/relief/north.json']);
  assert.deepEqual(Buffer.from((await c.tile(northTiles)).data), bytes.subarray(payloadOffset));
  await assert.rejects(c.tile(northTiles, 169), {status: 404}, 'an absent tile permits overzoom without retiring the region');
  assert.ok(c.overlay);
  north.destroy();
  assert.equal(c.overlay, null);
  const count = c.fetches.length;
  await assert.rejects(c.tile(northTiles), {status: 404});
  assert.equal(c.fetches.length, count);
  let release;
  const stale = c.start('north', new Promise(resolve => { release = resolve; }));
  stale.destroy();
  c.start('south');
  await tick();
  const southTiles = c.template;
  release(pointer('north'));
  await tick();
  assert.equal(c.template, southTiles);
  assert.notEqual(northTiles, southTiles);
  await c.tile(southTiles);
  assert.ok(c.fetches.at(-1)[0].startsWith('/feeds/tiles/relief/south/'));
  assert.deepEqual(c.errors, []);
});

test('held inputs do not fetch archive bytes; a failed range unloads the raster and land stack', async t => {
  const c = chart(t);
  c.start('held', {...pointer('held'), status: 'held'});
  await tick();
  assert.equal(c.overlay, undefined);
  assert.equal(c.fetches.length, 1);
  c.start('north');
  await tick();
  const active = c.template;
  await c.tile(active);
  c.breakRange();
  await assert.rejects(c.tile(active), /did not return the requested range/);
  assert.equal(c.overlay, null);
  assert.deepEqual(c.errors, ['Relief unavailable: unreviewed', 'Relief server did not return the requested range']);
  await assert.rejects(c.tile(active), {status: 404});
});

test('land, parks and coast cover the raster; theme and field paints preserve the source', async t => {
  const c = chart(t);
  c.seafloor.value = true;
  c.theme('light'); // late attachment must already use the changed theme
  c.start('north');
  await tick();
  const [raster, earth, parks, coast] = c.overlay.layers;
  assert.equal(c.before, 'boundaries'); // above the water fill, under labels and contours
  assert.equal(raster.type, 'raster');
  assert.equal(raster.paint['raster-resampling'], 'linear');
  assert.equal(raster.paint['raster-brightness-min'], 0.30);
  assert.equal(raster.paint['raster-brightness-max'], 1);
  assert.equal(earth.paint['fill-color'], 'light:--map-land');
  assert.equal(parks.paint['fill-color'], 'light:--map-park');
  assert.equal(coast.paint['line-color'], 'light:--map-coast');
  await c.tile(c.template);
  const source = raster.source, count = c.fetches.length;
  c.theme('dark');
  c.field.value = true;
  assert.equal(c.overlay.layers[0].source, source);
  assert.equal(c.overlay.layers[0].paint['raster-brightness-max'], 0.75);
  assert.equal(c.overlay.layers[0].paint['raster-brightness-min'], 0);
  assert.equal(c.overlay.layers[0].paint['raster-saturation'], -0.8);
  assert.equal(c.overlay.layers[0].paint['raster-opacity'], 0.6);
  c.seafloor.value = false;
  assert.equal(c.overlay.layers[0].paint['raster-saturation'], 0);
  assert.equal(c.overlay.layers[0].paint['raster-brightness-max'], 1);
  assert.equal(c.fetches.length, count);
});
