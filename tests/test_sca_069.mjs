import assert from 'node:assert/strict';
import test from 'node:test';
import {signal} from '@preact/signals';
import {createCharterGrounds, GROUNDS_FILL, GROUNDS_SOURCE, HATCH_SOURCE} from '../web/map/charter-grounds.ts';
import {CHECKING} from '../web/map/habitat.ts';
import {terrainLayers} from '../web/map/layers.ts';
import {markData, markScreen} from '../web/map/marks.ts';
import {configureStore, syncFromURL} from '../web/state.ts';

const box = (lo, hi) => [[lo, lo], [hi, lo], [hi, hi], [lo, hi], [lo, lo]];

test('terrain does not clip hatches; Chart hatches and both pick paths are unchanged', async t => {
  const page = 'https://fixture.invalid/map?region=morro-bay&layers=fleet&species=lingcod';
  configureStore({v2: true, storage: null});
  syncFromURL(page);
  markData.value = {region: {id: 'morro-bay', assets: {charters: 'fixture.json'}}};
  markScreen.value = CHECKING;

  const coordinates = [box(0, 0.01), box(0.004, 0.006)];
  let hatchReads = 0;
  // Each hatch call reads the rings once. The synthetic ready screen has no
  // boundaries to compare, and the inert terrain sink does not read the rings.
  const geometry = {type: 'Polygon', get coordinates() { hatchReads++; return coordinates; }};
  const id = 'fixture-ground', label = 'Fixture Ground';
  const ground = {id, label, geometry, precision: 'Named ground', longitude: 0.001, latitude: 0.001,
    map_species: ['lingcod'], reports: [{species: ['lingcod']}], report_count: 1, boats: [],
    latest_report: '2026-01-01', depth_ft: [20, 40], survey_year: 2025};
  const engine = signal(null);
  const controller = createCharterGrounds({engine, page: () => page, palette: () => ({amber: 'amber', bg: 'white'}),
    fetchFn: async () => ({ok: true, json: async () => ({audit_date: '2026-01-02', grounds: [ground]})})});
  t.after(() => { controller.destroy(); markData.value = null; markScreen.value = CHECKING; });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(terrainLayers.value[GROUNDS_SOURCE], undefined, 'an unready screen admits no drape');

  markScreen.value = {...CHECKING, status: 'ready'};
  const drape = terrainLayers.value[GROUNDS_SOURCE];
  const terrainHatchCalls = hatchReads;
  hatchReads = 0;
  const data = new Map();
  engine.value = {setOverlay() {}, setData: (source, collection) => data.set(source, collection)};
  const chartHatchCalls = hatchReads;

  const outline = {type: 'Polygon', coordinates};
  assert.deepEqual(drape.features, [{id, geometry: outline, properties: {id, label}}]);
  const [chartOutline] = data.get(GROUNDS_SOURCE).features;
  assert.deepEqual(chartOutline, {type: 'Feature', geometry: outline, properties: {id, label}});
  const [chartHatch] = data.get(HATCH_SOURCE).features;
  assert.deepEqual(chartHatch.properties, {id});
  assert.equal(chartHatch.geometry.type, 'MultiLineString');
  const segments = chartHatch.geometry.coordinates;
  assert.equal(segments.length, 11);
  const throughHole = segments.filter(([[x, y]]) => Math.abs(x + y - 0.01) < 1e-12);
  assert.deepEqual(throughHole.map(line => line.map(p => p.map(v => Math.round(v * 1000)))),
    [[[0, 10], [4, 6]], [[6, 4], [10, 0]]]);
  const chartPick = controller.pick.mark(GROUNDS_FILL, chartOutline.properties);
  assert.equal(chartPick.id, `charter:${id}`);
  assert.deepEqual(drape.pick(drape.features[0].id), chartPick);

  t.diagnostic(`hatch calls: terrain=${terrainHatchCalls}, Chart=${chartHatchCalls}`);
  assert.equal(chartHatchCalls, 1, 'the Chart still reads the hatch rings once');
  assert.equal(terrainHatchCalls, 0, 'the terrain alone must not read the hatch rings');
});
