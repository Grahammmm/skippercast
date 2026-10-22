import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import test from 'node:test';
import {signal} from '@preact/signals';
import {regionalChlorophyll} from '../web/map/habitat-feed.ts';
import {chlorophyllCells, chlorophyllOverlay, chlorophyllStatus, chlorophyllState, createChlorophyll} from '../web/map/chlorophyll.ts';
import {PROFILE_TABLE} from '../web/profile.ts';
import {layerEntry} from '../web/map/layers.ts';
import {readPalette} from '../web/map/palette.ts';
import {configureStore, setParams, syncFromURL} from '../web/state.ts';

const HOUR = 3_600_000, NOW = new Date('2026-10-20T12:00:00Z'), ID = 'chlorophyll-observation';
const PAGE = 'https://example.test/map', BASE = 'https://example.test/feeds/conditions/regions/test-coast/';
const palette = () => readPalette(name => `token(${name})`);
function fixture({age = 24, maxAge = 96, status = 'ok'} = {}) {
  const time = (NOW.getTime() - age * HOUR) / 1000, sample = new Date(time * 1000).toISOString();
  const fields = ['latitude', 'longitude', 'chlorophyll_mg_m3'], resolution = [.0375, .0375], bounds = [-121.5, 35, -121, 35.5];
  const tile = {schema_version: 1, region_id: 'test-coast', layer_id: ID, fields, bounds, resolution_degrees: resolution,
    frames: [{time, cells: [[35.1, -121.2, .1], [35.1, -121.1625, null], [35.1, -121.125, 10]]}]};
  const bytes = Buffer.from(JSON.stringify(tile)), hash = createHash('sha256').update(bytes).digest('hex');
  const record = {path: `habitat-tiles/${ID}--243-70-${hash.slice(0,16)}.json`, bounds, sha256: hash, bytes: bytes.length};
  const layer = {id: ID, kind: 'observation', fields, resolution_degrees: resolution, frames: [{time, valid_cells: 2}],
    sample_at: sample, status, max_age_hours: maxAge, native_stride: 1, tiles: [record]};
  const manifest = {schema_version: 1, region_id: 'test-coast', layers: {[ID]: layer}, sources: {[ID]: {name: 'NOAA NPP/NOAA-20 merged OCI chlorophyll, near real time', data_retrieved_at: NOW.toISOString()}}};
  const asked = [];
  const fetchFn = async url => {
    asked.push(url);
    if (url === `${BASE}habitat-dynamics.json`) return Response.json(manifest);
    return url === BASE + record.path ? new Response(bytes) : new Response('', {status: 404});
  };
  return {manifest, layer, record, asked, fetchFn};
}
const read = f => regionalChlorophyll('test-coast', {fetchFn: f.fetchFn, page: PAGE, now: NOW});

test('chlorophyll strict age boundary and metadata-driven limit', async () => {
  for (const [age, maxAge, state] of [[95.999,96,'ready'], [96,96,'listed'], [96.001,96,'listed'], [108,96,'listed'], [80,72,'listed'], [80,96,'ready']]) {
    const f = fixture({age,maxAge});
    assert.equal((await read(f)).state, state, `${age}/${maxAge}`);
    if (state !== 'ready') assert.equal(f.asked.length, 1, 'withheld before fetching tiles');
  }
});
test('retained and reused products keep their original sample clock', async () => {
  for (const age of [24,108]) {
    const f = fixture({age,status:'retained'});
    f.manifest.generated_at = NOW.toISOString(); f.manifest.sources[ID].reused = true;
    const got = await read(f);
    assert.equal(got.state, age === 24 ? 'ready' : 'listed');
    if (got.state === 'ready') assert.equal(got.observation.sampleAt, f.layer.sample_at);
  }
});
test('invalid or absent age limits fail closed', async () => {
  for (const maxAge of [undefined,null,0,-1,'96','bad']) {
    const f = fixture(); f.layer.max_age_hours = maxAge;
    assert.equal((await read(f)).state, 'error', String(maxAge));
  }
});
test('sample and frame clocks must exist, agree and not be over one hour ahead', async () => {
  for (const sample of [undefined,null,'bad']) {
    const f = fixture(); f.layer.sample_at = sample; assert.notEqual((await read(f)).state,'ready');
  }
  for (const time of [undefined,null,'bad']) {
    const f = fixture(); f.layer.frames[0].time = time; assert.notEqual((await read(f)).state,'ready');
  }
  const mismatch = fixture(); mismatch.layer.sample_at = NOW.toISOString(); assert.notEqual((await read(mismatch)).state,'ready');
  assert.equal((await read(fixture({age:-1.001}))).state,'listed');
  assert.equal((await read(fixture({age:-1}))).state,'ready');
});
test('native cell footprints preserve cloud gaps and log palette matches legend', async () => {
  const got = await read(fixture()); assert.equal(got.state,'ready');
  const cells = chlorophyllCells(got.observation);
  assert.equal(cells.features.length,2);
  assert.deepEqual(cells.features.map(f => f.properties.value), [.1,10]);
  const [first,second] = cells.features.map(f => f.geometry.coordinates[0]);
  assert.ok(Math.abs(first[1][0] - first[0][0] - .0375) < 1e-10);
  assert.ok(second[0][0] > first[1][0], 'missing center cell remains an empty interval');
  const paint = chlorophyllOverlay(got.observation, palette()).layers[0].paint;
  assert.deepEqual(paint['fill-color'][2], ['log10',['get','value']]);
  assert.equal(paint['fill-antialias'],false);
  assert.equal(layerEntry('chlorophyll').legend.length,5);
  assert.ok(layerEntry('chlorophyll').legend.every(r => r.label.includes('mg/m³')));
  const s = chlorophyllStatus(true, got, NOW);
  assert.match(s.basis,/NOAA.*0.0375°.*sample.*Withheld at 96 h/);
  assert.match(s.basis,/not bait or fish/);
  assert.equal(chlorophyllStatus(true,got,new Date(Date.parse(got.observation.sampleAt)+96*HOUR)).drawn,null);
});
test('empty scenes, missing tiles and corrupt hashes cannot draw', async () => {
  const empty = fixture(); empty.layer.frames[0].valid_cells = 0; empty.layer.tiles = [];
  assert.equal((await read(empty)).state,'listed');
  const noTiles = fixture(); noTiles.layer.tiles = []; assert.equal((await read(noTiles)).state,'listed');
  const corrupt = fixture(); corrupt.record.sha256 = 'f'.repeat(64); assert.equal((await read(corrupt)).state,'error');
  const later = fixture({age:108}); later.layer.frames.push({time:NOW.getTime()/1000, valid_cells:0});
  assert.equal((await read(later)).state,'listed', 'new empty frame cannot refresh old populated data');
});
test('off by default; controller fetches on demand and withdraws on off and region change', async () => {
  for (const profile of Object.values(PROFILE_TABLE)) assert.ok(!profile.defaultLayers.includes('chlorophyll'));
  globalThis.location = {href: `${PAGE}?region=test-coast&layers=none`};
  globalThis.history = {state:null, pushState(_s,_t,url) { location.href=url; }, replaceState(_s,_t,url) { location.href=url; }};
  globalThis.dispatchEvent = () => true;
  configureStore({v2:true,storage:null}); syncFromURL(`${PAGE}?region=test-coast&layers=none`);
  const f = fixture(), overlays = [], data = [];
  const engine = signal({setOverlay:(id,overlay)=>overlays.push(overlay),setData:(id,value)=>data.push(value)});
  const controller = createChlorophyll({engine,fetchFn:f.fetchFn,page:()=>PAGE,now:()=>NOW,palette});
  const settle = async () => { for (const end = Date.now()+5000; chlorophyllState.value.note === 'loading' && Date.now()<end;) await new Promise(resolve=>setTimeout(resolve,5)); };
  try {
    await settle(); assert.equal(f.asked.length,0);
    setParams({layers:'chlorophyll'}); await settle();
    assert.ok(chlorophyllState.value.drawn); assert.equal(data.at(-1).features.length,2);
    setParams({region:'other-coast'}); await settle(); assert.equal(overlays.at(-1),null);
    setParams({layers:'none'}); assert.equal(overlays.at(-1),null);
  } finally {controller.destroy(); setParams({layers:'none'});}
});
