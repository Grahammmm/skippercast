import test from 'node:test';
import {SEARCH_COLOR, CLASSIFIED_COLOR} from '../dist/seafloor-data.js';
import assert from 'node:assert/strict';
import {
  manifestState, loadManifest, manifestURL, archiveURL, decodeTile, decodeRings, classifyRings,
  toLngLat, tileFeatures, dedupeById, tilesForBounds, habitatColor, habitatDetails, GRADE_STYLE, UNKNOWN_COLOR,
  HABITAT_LABEL, DEPTH_NOTE,
} from '../dist/seafloor-data.js';

test('geologic bedrock interpretation keeps rugosity and species fit unknown', () => {
  const p = {status: 'classified-area', fit_lingcod: 3, classified_area: JSON.stringify({
    profile: 'original-interpreted-bedrock-area-v1',
    interpretation_method: 'original-interpreted-bedrock-v1',
  })};
  const d = habitatDetails(p);
  assert.equal(d.classifiedBedrock, true);
  assert.match(d.title, /exposed-bedrock/);
  assert.equal(d.grade, 'unknown');
  assert.equal(d.fits[0].value, 'unknown');
  assert.equal(habitatColor(p), CLASSIFIED_COLOR);
  assert.match(habitatDetails({status: 'classified-area'}).title, /rugose-rock/);
});

test('unranked search areas have a distinct style and honest details', () => {
  const p = {status: 'search-area', terrain_grade: 'unknown', fit_lingcod: 'unknown',
    search_area: JSON.stringify({target_species: ['lingcod']}), depth_min_ft: 40, depth_max_ft: 50};
  assert.equal(habitatColor(p, 'fit_lingcod'), SEARCH_COLOR);
  assert.equal(habitatColor(p, 'terrain'), SEARCH_COLOR);
  const d = habitatDetails(p);
  assert.equal(d.searchArea, true);
  assert.equal(d.grade, 'unknown');
  assert.deepEqual(d.searchTargets, ['lingcod']);
  assert.equal(d.fits[0].value, 'unknown');
});

// --- a tiny MVT encoder, enough to round-trip what the decoder reads -------
const varint = (n) => { const out = []; while (n > 127) { out.push((n & 127) | 128); n = Math.floor(n / 128); } out.push(n); return out; };
const key = (field, type) => varint(field * 8 + type);
const lenField = (field, bytes) => [...key(field, 2), ...varint(bytes.length), ...bytes];
const str = (field, s) => lenField(field, [...new TextEncoder().encode(s)]);
const zig = (n) => (n << 1) ^ (n >> 31);
function value(v) {
  if (typeof v === 'string') return str(1, v);
  if (typeof v === 'boolean') return [...key(7, 0), ...varint(v ? 1 : 0)];
  if (Number.isInteger(v) && v >= 0) return [...key(5, 0), ...varint(v)];
  if (Number.isInteger(v)) return [...key(6, 0), ...varint(zig(v))];
  const b = new Uint8Array(8); new DataView(b.buffer).setFloat64(0, v, true); return [...key(3, 1), ...b];
}
function geometry(rings) {
  const out = []; let x = 0, y = 0;
  for (const ring of rings) {
    const [first, ...rest] = ring;
    out.push(1 | (1 << 3), zig(first[0] - x), zig(first[1] - y)); [x, y] = first;
    out.push(2 | (rest.length << 3));
    for (const p of rest) { out.push(zig(p[0] - x), zig(p[1] - y)); [x, y] = p; }
    out.push(7 | (1 << 3));
  }
  return out;
}
function encodeTile(layers) {
  const bytes = [];
  for (const [name, features] of Object.entries(layers)) {
    const keys = [], values = [], layer = [...key(15, 0), ...varint(2), ...str(1, name)];
    for (const f of features) {
      const tags = [];
      for (const [k, v] of Object.entries(f.properties)) {
        if (!keys.includes(k)) keys.push(k);
        let vi = values.findIndex((x) => x === v);
        if (vi < 0) { values.push(v); vi = values.length - 1; }
        tags.push(keys.indexOf(k), vi);
      }
      const packed = (arr) => arr.flatMap(varint);
      layer.push(...lenField(2, [...lenField(2, packed(tags)), ...key(3, 0), ...varint(3), ...lenField(4, packed(geometry(f.rings)))]));
    }
    for (const k of keys) layer.push(...str(3, k));
    for (const v of values) layer.push(...lenField(4, value(v)));
    layer.push(...key(5, 0), ...varint(4096));
    bytes.push(...lenField(3, layer));
  }
  return new Uint8Array(bytes);
}
// Clockwise in tile space (y down) = exterior; the hole winds the other way.
const square = (x0, y0, s) => [[x0, y0], [x0 + s, y0], [x0 + s, y0 + s], [x0, y0 + s]];
const hole = (x0, y0, s) => [[x0, y0], [x0, y0 + s], [x0 + s, y0 + s], [x0 + s, y0]];

const NOW = Date.parse('2026-09-29T20:00:00Z');
const READY = { status: 'ready', region: 'morro-bay', expires_at: '2026-10-30T00:00:00+00:00', archive_sha256: 'a'.repeat(64) };

test('manifest gate: only a ready, unexpired, same-region, hashed publication is shown', () => {
  assert.equal(manifestState(READY, 'morro-bay', NOW).state, 'ready');
  assert.equal(manifestState({ status: 'updating' }, 'morro-bay', NOW).state, 'updating');
  assert.equal(manifestState({ ...READY, status: 'held' }, 'morro-bay', NOW).state, 'held');
  assert.equal(manifestState({ ...READY, expires_at: '2026-09-29T19:59:59Z' }, 'morro-bay', NOW).state, 'expired');
  assert.equal(manifestState({ ...READY, expires_at: 'soon' }, 'morro-bay', NOW).state, 'expired');
  assert.equal(manifestState({ ...READY, region: 'bodega-point-reyes' }, 'morro-bay', NOW).state, 'unavailable');
  assert.equal(manifestState({ ...READY, archive_sha256: 'short' }, 'morro-bay', NOW).state, 'unavailable');
  assert.equal(manifestState(null, 'morro-bay', NOW).state, 'unavailable');
  assert.equal(manifestState(READY, '../etc', NOW).state, 'unavailable');
  assert.equal(manifestURL('morro-bay'), '/feeds/tiles/seafloor/manifest-morro-bay.json');
  assert.equal(archiveURL('morro-bay'), '/feeds/tiles/seafloor/seafloor-morro-bay.pmtiles');
});

test('loadManifest bypasses caches and fails closed', async () => {
  const calls = [];
  const ok = async (url, opts) => { calls.push([url, opts]); return { ok: true, status: 200, json: async () => READY }; };
  assert.equal((await loadManifest('morro-bay', ok, NOW)).state, 'ready');
  assert.deepEqual(calls[0], ['/feeds/tiles/seafloor/manifest-morro-bay.json', { cache: 'no-store' }]);
  const busy = async () => ({ ok: false, status: 503, json: async () => { throw new Error('text'); } });
  assert.equal((await loadManifest('morro-bay', busy, NOW)).state, 'updating');
  const missing = async () => ({ ok: false, status: 404, json: async () => ({}) });
  const none = await loadManifest('morro-bay', missing, NOW);
  assert.equal(none.state, 'unavailable');
  assert.equal(none.published, false, 'a 404 means no publication for this region');
  assert.notEqual((await loadManifest('morro-bay', busy, NOW)).published, false, 'an outage is not "never published"');
  const offline = async () => { throw new TypeError('network'); };
  assert.equal((await loadManifest('morro-bay', offline, NOW)).state, 'unavailable');
  let fetched = false;
  assert.equal((await loadManifest('', async () => { fetched = true; }, NOW)).state, 'unavailable');
  assert.equal(fetched, false);
});

test('MVT decode round-trips layers, typed values and a polygon with a hole', () => {
  const bytes = encodeTile({
    habitat: [{ properties: { id: 'sc-hab-1', terrain_grade: 'A', fit_lingcod: 3, depth_min_ft: 80.5, depth_max_ft: 142.25, negative: -4, flag: true },
      rings: [square(100, 100, 400), hole(200, 200, 100)] }],
    cells: [{ properties: { id: 'cell-1', tier: 1 }, rings: [square(0, 0, 4096)] }],
  });
  const tile = decodeTile(bytes);
  assert.deepEqual(Object.keys(tile).sort(), ['cells', 'habitat']);
  const f = tile.habitat.features[0];
  assert.deepEqual(f.properties, { id: 'sc-hab-1', terrain_grade: 'A', fit_lingcod: 3, depth_min_ft: 80.5, depth_max_ft: 142.25, negative: -4, flag: true });
  const polys = classifyRings(decodeRings(f.commands));
  assert.equal(polys.length, 1);
  assert.equal(polys[0].length, 2, 'exterior ring plus one hole');
  assert.deepEqual(polys[0][0][0], [100, 100]);
  assert.deepEqual(polys[0][0].at(-1), [100, 100], 'rings are closed');
});

test('two separate exteriors in one feature become two polygons', () => {
  const polys = classifyRings(decodeRings(decodeTile(encodeTile({ habitat: [{ properties: { id: 'x' }, rings: [square(0, 0, 10), square(50, 50, 10)] }] })).habitat.features[0].commands));
  assert.equal(polys.length, 2);
});

test('tile coordinates convert to longitude and latitude', () => {
  assert.deepEqual(toLngLat(0, 0, 0, 4096, [2048, 2048]), [0, 0]);
  const [lng, lat] = toLngLat(12, 655, 1606, 4096, [0, 0]);
  assert.ok(Math.abs(lng - -122.43164) < 1e-4);
  assert.ok(Math.abs(lat - 36.17336) < 1e-4);
  const [z, x, y] = tilesForBounds([-120.9, 35.35, -120.85, 35.4], 12)[0];
  assert.equal(z, 12);
  const [w, n] = toLngLat(z, x, y, 4096, [0, 0]), [e, s] = toLngLat(z, x, y, 4096, [4096, 4096]);
  assert.ok(w <= -120.9 && e > -120.9 && s <= 35.4 && n > 35.4, 'first tile covers the north-west corner');
});

test('features split across tiles are merged by stable id, never drawn twice as separate features', () => {
  const left = decodeTile(encodeTile({ habitat: [{ properties: { id: 'sc-hab-9', terrain_grade: 'B' }, rings: [square(3900, 100, 196)] }] }));
  const right = decodeTile(encodeTile({ habitat: [{ properties: { id: 'sc-hab-9', terrain_grade: 'B' }, rings: [square(0, 100, 50)] },
    { properties: { id: 'sc-hab-10' }, rings: [square(10, 10, 5)] }, { properties: { name: 'no id' }, rings: [square(20, 20, 5)] }] }));
  const merged = dedupeById([...tileFeatures(left, 'habitat', 12, 655, 1606), ...tileFeatures(right, 'habitat', 12, 656, 1606)]);
  assert.deepEqual(merged.map((f) => f.properties.id), ['sc-hab-9', 'sc-hab-10']);
  assert.equal(merged[0].geometry.coordinates.length, 2, 'both parts kept under one feature');
  assert.equal(tileFeatures(left, 'missing', 12, 0, 0).length, 0);
});

test('terrain grade and species fit are styled as separate assessments', () => {
  assert.equal(habitatColor({ terrain_grade: 'A', fit_lingcod: 1 }), GRADE_STYLE.A.color);
  assert.notEqual(habitatColor({ terrain_grade: 'A', fit_lingcod: 1 }, 'fit_lingcod'), GRADE_STYLE.A.color);
  assert.equal(habitatColor({ terrain_grade: 'Z' }), UNKNOWN_COLOR);
  assert.equal(habitatColor({ fit_rockfish_reef: 'unknown' }, 'fit_rockfish_reef'), UNKNOWN_COLOR);
});

test('details parse nested JSON evidence and keep unknowns unknown', () => {
  const d = habitatDetails({
    id: 'sc-hab-1', terrain_grade: 'B', fit_lingcod: 2, fit_rockfish_reef: 'unknown', depth_min_ft: 79.6, depth_max_ft: 141.2,
    source_ids: '["bathymetry-offshoremorrobay-zip-fad659557e"]', source_year: 2008, resolution_m: 2, vertical_datum: 'NAVD88',
    screen: '{"status":"pass","version":"whole-polygon-screen-v1"}', substrate: '{"same_survey_as_depth":true,"independent_confirmation":false}',
    planning_notice: 'Planning only. Not a navigation chart. Check current CDFW regulations.',
  });
  assert.equal(d.title, HABITAT_LABEL);
  assert.equal(d.depth, '80–141 ft nominal');
  assert.equal(d.depthNote, DEPTH_NOTE);
  assert.equal(d.grade, 'B');
  assert.deepEqual(d.fits, [{ key: 'fit_lingcod', name: 'lingcod', value: 2 }, { key: 'fit_rockfish_reef', name: 'rockfish reef', value: 'unknown' }]);
  assert.deepEqual(d.source, { ids: ['bathymetry-offshoremorrobay-zip-fad659557e'], year: 2008, resolution: '2 m', datum: 'NAVD88' });
  assert.deepEqual(d.substrate, { sameSurvey: true, independent: false });
  assert.equal(d.screened, true);
  const blank = habitatDetails({ id: 'x', screen: 'not json' });
  assert.equal(blank.depth, 'Depth unknown');
  assert.equal(blank.grade, 'unknown');
  assert.deepEqual(blank.source, { ids: [], year: 'unknown', resolution: 'unknown', datum: 'unknown' });
  assert.equal(blank.screened, false);
  assert.match(blank.notice, /Planning only/);
});

test('decodes a real tippecanoe PMTiles archive: 107 Morro Bay reef outlines after merging tile parts', async () => {
  const fs = await import('node:fs');
  const vm = await import('node:vm');
  const root = new URL('../dist/', import.meta.url);
  const sandbox = { TextDecoder, DecompressionStream, Response, Uint8Array, DataView, ArrayBuffer, Promise, console };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(new URL('vendor/pmtiles-4.5.0/pmtiles.js', root), 'utf8') + ';globalThis.pmtiles = pmtiles;', sandbox);
  const buf = fs.readFileSync(new URL('tiles/morro-bay-reef-outlines.pmtiles', root));
  const source = { getKey: () => 'fixture', getBytes: async (offset, length) => ({ data: buf.buffer.slice(buf.byteOffset + offset, buf.byteOffset + offset + length) }) };
  const archive = new sandbox.pmtiles.PMTiles(source);
  const h = await archive.getHeader();
  const parts = [];
  for (const [z, x, y] of tilesForBounds([h.minLon, h.minLat, h.maxLon, h.maxLat], 12)) {
    const tile = await archive.getZxy(z, x, y);
    if (tile) parts.push(...tileFeatures(decodeTile(new Uint8Array(tile.data)), 'reefs', z, x, y));
  }
  assert.ok(parts.length > 107, 'some outlines are split across tiles');
  const merged = dedupeById(parts);
  assert.equal(merged.length, 107);
  for (const f of merged) for (const poly of f.geometry.coordinates) for (const [lng, lat] of poly[0]) {
    assert.ok(lng >= h.minLon - 0.02 && lng <= h.maxLon + 0.02 && lat >= h.minLat - 0.02 && lat <= h.maxLat + 0.02);
  }
});


test('classified areas are interpreted, unranked and use no numeric fit view', () => {
  const p = {status: 'classified-area', terrain_grade: 'A', fit_lingcod: 3,
    depth_min_ft: 25, depth_max_ft: 300, source_ids: '["depth","class"]'};
  assert.equal(habitatColor(p, 'terrain'), CLASSIFIED_COLOR);
  assert.equal(habitatColor(p, 'fit_lingcod'), CLASSIFIED_COLOR);
  const d = habitatDetails(p);
  assert.equal(d.classifiedArea, true);
  assert.equal(d.searchArea, false);
  assert.equal(d.grade, 'unknown');
  assert.equal(d.fits[0].value, 'unknown');
  assert.equal(d.title, 'Publisher-interpreted rugose-rock habitat area');
  assert.equal(d.depth, 'Within nominal 25–300 ft band');
  assert.deepEqual(d.source.ids, ['depth', 'class']);
});

test('synthetic native point-contact outline survives actual tiles as one unranked feature', async () => {
  const fs = await import('node:fs');
  const vm = await import('node:vm');
  const sandbox = {TextDecoder,DecompressionStream,Response,Uint8Array,DataView,ArrayBuffer,Promise,console};
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(new URL('../dist/vendor/pmtiles-4.5.0/pmtiles.js',import.meta.url),'utf8')+';globalThis.pmtiles=pmtiles;',sandbox);
  const buf=fs.readFileSync(new URL('./fixtures/seafloor/classified-point-contact.pmtiles',import.meta.url));
  const archive=new sandbox.pmtiles.PMTiles({getKey:()=> 'synthetic-contact',getBytes:async(offset,length)=>({data:buf.buffer.slice(buf.byteOffset+offset,buf.byteOffset+offset+length)})});
  const h=await archive.getHeader();
  for(const zoom of [12,15]){
    const parts=[];
    for(const [z,x,y] of tilesForBounds([h.minLon,h.minLat,h.maxLon,h.maxLat],zoom)){
      const tile=await archive.getZxy(z,x,y);
      if(tile)parts.push(...tileFeatures(decodeTile(new Uint8Array(tile.data)),'habitat',z,x,y));
    }
    const features=dedupeById(parts);assert.equal(features.length,1);
    const f=features[0];assert.equal(f.properties.id,'synthetic-point-contact');
    assert.equal(f.properties.exportable,false);assert.equal(f.properties.tier,1);
    assert.equal(habitatColor(f.properties),CLASSIFIED_COLOR);
    assert.equal(habitatDetails(f.properties).grade,'unknown');
    assert.ok(Math.abs(f.properties.area_ha-23/24)<1e-12,'native area metadata survives quantization');
    for(const p of f.geometry.coordinates)for(const ring of p){
      assert.ok(ring.length>=4);assert.deepEqual(ring[0],ring.at(-1));
      for(const xy of ring)assert.ok(xy.every(Number.isFinite));
    }
  }
});
