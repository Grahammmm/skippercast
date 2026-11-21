// F15-04 / SCA-547: offline controls for tile membership, not a production fix.
// Run `node tests/test_f15_04_audit.mjs --check-bounds` to also check the desired
// refusal contract. That opt-in check is expected to expose the gap until SCA-204.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import test from 'node:test';
import {CHLOROPHYLL_LAYER_ID, SST_LAYER_ID, regionalChlorophyll} from '../web/map/habitat-feed.ts';
import {eligibility, saveOcean} from '../web/map/ocean-pack.ts';

const regionId = 'bounds-fixture', origin = 'https://example.test';
const base = `${origin}/feeds/conditions/regions/${regionId}/`;
const manifestURL = `${base}habitat-dynamics.json`;
const sample = '2026-01-01T00:00:00.000Z', time = Date.parse(sample) / 1000;
const now = new Date('2026-01-01T02:00:00Z');
// habitat_dynamics.publish_tiles bins centers by floor(lon/.5), floor(lat/.5).
// Bounds are [west,south,east,north]; row coordinates are [latitude,longitude].
// West/south edges belong to this tile; east/north start the next tile. A cell
// centered on an edge is valid even if its footprint crosses it. The negative
// is well beyond any rounding tolerance, not a test of a proposed epsilon.
const bounds = [-2, 0.5, -1.5, 1];
const edge = [0.5, -2], misplaced = [0.5, -1.25];

function fixture(id, center) {
  const isChlorophyll = id === CHLOROPHYLL_LAYER_ID;
  const fields = ['latitude', 'longitude', ...(isChlorophyll ? ['chlorophyll_mg_m3'] : ['temperature_c', 'analysis_error_c'])];
  const kind = isChlorophyll ? 'observation' : 'analysis';
  const cell = [...center, ...(isChlorophyll ? [1] : [14.5, 0.3])];
  const resolution_degrees = [0.05, 0.05];
  const frame = {time, valid_cells: 1};
  const header = {schema_version: 1, region_id: regionId};
  const body = Buffer.from(JSON.stringify({...header, layer_id: id, bounds, fields, resolution_degrees,
    frames: [{...frame, cells: [cell]}]}) + '\n');
  const sha256 = createHash('sha256').update(body).digest('hex');
  const path = `habitat-tiles/${id}--4-1-${sha256.slice(0, 16)}.json`;
  const manifest = {...header, layers: {[id]: {id, kind, fields, resolution_degrees, frames: [frame],
    sample_at: sample, status: 'ok', max_age_hours: 24, native_stride: 1,
    tiles: [{path, bounds, bytes: body.length, sha256}]}},
  sources: {[id]: {name: 'Synthetic ocean feed', data_retrieved_at: sample}}};
  const url = base + path;
  const fetchFn = async key => {
    if (key === manifestURL) return Response.json(manifest);
    if (key === url) return new Response(body);
    throw new Error(`Unexpected fixture URL: ${key}`);
  };
  return {fetchFn, url, body};
}

const drawInput = center => regionalChlorophyll(regionId, {fetchFn: fixture(CHLOROPHYLL_LAYER_ID, center).fetchFn, page: origin, now});

// The pack saves SST and currents, not chlorophyll. Use SST to exercise the
// same tile validator through the actual pack builder with a recording put.
async function packInput(center) {
  const {fetchFn, url, body} = fixture(SST_LAYER_ID, center), writes = new Map();
  const pack = await saveOcean({regionId, origin, fetchFn, signal: new AbortController().signal,
    eligible: (id, manifest) => eligibility(id, manifest, now),
    put: async (key, bytes) => { writes.set(key, Buffer.from(bytes)); }});
  return {layer: pack.layers[SST_LAYER_ID], writes, url, body};
}

test('chlorophyll offers the exact edge cell to the map', async () => {
  const result = await drawInput(edge);
  assert.equal(result.state, 'ready');
  assert.deepEqual(result.observation.cells, [{lat: edge[0], lon: edge[1], value: 1}]);
});

test('the pack saves the exact bytes of the SST edge tile', async () => {
  const {layer, writes, url, body} = await packInput(edge);
  assert.equal(layer.state, 'saved');
  assert.deepEqual([...writes.keys()], [url, manifestURL]);
  assert.deepEqual(writes.get(url), body);
});

if (process.argv.includes('--check-bounds')) {
  test('chlorophyll must withhold a correctly hashed cell outside its tile', async () => {
    const {state, observation} = await drawInput(misplaced);
    assert.deepEqual({state, cells: observation?.cells ?? []}, {state: 'error', cells: []});
  });

  test('the pack must refuse a correctly hashed SST tile with a misplaced cell', async () => {
    const {layer, writes, url} = await packInput(misplaced);
    assert.deepEqual({state: layer.state, tiles: layer.tiles.saved, bytes: layer.bytes, wroteTile: writes.has(url)},
      {state: 'failed', tiles: 0, bytes: 0, wroteTile: false});
    assert.deepEqual([...writes.keys()], [manifestURL]);
  });
}
