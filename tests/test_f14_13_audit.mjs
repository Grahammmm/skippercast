// F14-13 / SCA-241: the chlorophyll controller must build the polygon collection once per observation and share it
// between source creation (setOverlay) and update (setData). Contract protected: one geometry walk per observation.
// Believable bug: calling chlorophyllCells() again for setData (or again on every effect re-run) re-allocates every ring.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import test from 'node:test';
import {signal} from '@preact/signals';
import {chlorophyllCells, chlorophyllOverlay, chlorophyllState, createChlorophyll} from '../web/map/chlorophyll.ts';
import {readPalette} from '../web/map/palette.ts';
import {configureStore, setParams, syncFromURL} from '../web/state.ts';

const HOUR = 3_600_000, NOW = new Date('2026-10-20T12:00:00Z'), ID = 'chlorophyll-observation';
const PAGE = 'https://example.test/map', BASE = 'https://example.test/feeds/conditions/regions/test-coast/';
const palette = tag => () => readPalette(name => /^map-.*-(?:opacity|width)$/.test(name) ? '1' : `${tag}(${name})`);

function fixture() {
  const time = (NOW.getTime() - 24 * HOUR) / 1000, sample = new Date(time * 1000).toISOString();
  const fields = ['latitude', 'longitude', 'chlorophyll_mg_m3'], resolution = [.0375, .0375], bounds = [-121.5, 35, -121, 35.5];
  const tile = {schema_version: 1, region_id: 'test-coast', layer_id: ID, fields, bounds, resolution_degrees: resolution,
    frames: [{time, cells: [[35.1, -121.2, .1], [35.1, -121.1625, null], [35.1, -121.125, 10]]}]};
  const bytes = Buffer.from(JSON.stringify(tile)), hash = createHash('sha256').update(bytes).digest('hex');
  const record = {path: `habitat-tiles/${ID}--243-70-${hash.slice(0, 16)}.json`, bounds, sha256: hash, bytes: bytes.length};
  const layer = {id: ID, kind: 'observation', fields, resolution_degrees: resolution, frames: [{time, valid_cells: 2}],
    sample_at: sample, status: 'ok', max_age_hours: 96, native_stride: 1, tiles: [record]};
  const manifest = {schema_version: 1, region_id: 'test-coast', layers: {[ID]: layer}, sources: {[ID]: {name: 'NOAA test', data_retrieved_at: NOW.toISOString()}}};
  const fetchFn = async url => url === `${BASE}habitat-dynamics.json` ? Response.json(manifest) : url === BASE + record.path ? new Response(bytes) : new Response('', {status: 404});
  return {fetchFn};
}
const settle = async done => { for (const end = Date.now() + 5000; !done() && Date.now() < end;) await new Promise(resolve => setTimeout(resolve, 5)); };
const recorder = () => {
  const calls = [];
  return {calls, setOverlay: (id, overlay) => calls.push(['overlay', overlay]), setData: (id, data) => calls.push(['data', data])};
};

test('one geometry build per observation, shared by source creation and update; holes, values and palette kept', async () => {
  globalThis.location = {href: `${PAGE}?region=test-coast&layers=none`};
  globalThis.history = {state: null, pushState(_s, _t, url) { location.href = url; }, replaceState(_s, _t, url) { location.href = url; }};
  globalThis.dispatchEvent = () => true;
  configureStore({v2: true, storage: null}); syncFromURL(`${PAGE}?region=test-coast&layers=none`);
  const engine = signal(null), first = recorder(), second = recorder();
  let tag = 'a';
  const controller = createChlorophyll({engine, fetchFn: fixture().fetchFn, page: () => PAGE, now: () => NOW, palette: () => palette(tag)()});
  try {
    setParams({layers: 'chlorophyll'});
    await settle(() => chlorophyllState.value.drawn);
    const observation = chlorophyllState.value.drawn;
    assert.ok(observation, 'populated fresh observation is drawn');
    const direct = chlorophyllCells(observation);
    // Count geometry walks: chlorophyllCells maps observation.cells exactly once per build.
    let walks = 0; const map = observation.cells.map.bind(observation.cells);
    observation.cells.map = (...args) => { walks++; return map(...args); };

    engine.value = first;
    assert.equal(walks, 1, 'one build for the first draw (negative control: the old code walked twice)');
    const [overlayCall, dataCall] = first.calls;
    assert.equal(overlayCall[0], 'overlay'); assert.equal(dataCall[0], 'data');
    assert.equal(overlayCall[1].sources.chlorophyll.data, dataCall[1], 'creation and update share one immutable collection');
    assert.equal(dataCall[1].features.length, 2, 'missing cell stays a hole');
    assert.deepEqual(dataCall[1].features.map(f => f.properties.value), [.1, 10]);
    assert.deepEqual(dataCall[1], direct, 'same geometry as an independent build');

    // Same observation drawn again (new engine, new palette): paint follows the palette, geometry is not rebuilt.
    tag = 'b'; engine.value = second;
    assert.equal(walks, 1, 'no second walk for the same observation');
    const [overlay2, data2] = second.calls;
    assert.equal(overlay2[1].sources.chlorophyll.data, data2[1]);
    assert.equal(data2[1], dataCall[1], 'same observation reuses the collection');
    assert.notDeepEqual(overlay2[1].layers[0].paint, overlayCall[1].layers[0].paint, 'palette change still reaches the paint');
  } finally { controller.destroy(); setParams({layers: 'none'}); }
});

test('positive control: chlorophyllOverlay builds its own collection when none is passed, and uses a passed one verbatim', () => {
  const o = {resolution: [.1, .1], cells: [{lat: 35, lon: -121, value: 1}], sampleAt: NOW.toISOString(), maxAgeMs: 96 * HOUR, product: 'p'};
  const p = readPalette(name => /^map-.*-(?:opacity|width)$/.test(name) ? '1' : `token(${name})`);
  assert.equal(chlorophyllOverlay(o, p).sources.chlorophyll.data.features.length, 1);
  const shared = chlorophyllCells(o);
  assert.equal(chlorophyllOverlay(o, p, shared).sources.chlorophyll.data, shared);
});
