// F14-04: drive the real Chart and engine with synthetic region files and a
// recording renderer. Hold JSON bodies (not transport), so sharing the static
// response still permits independently settling reads of the same region.
import assert from 'node:assert/strict';
import test from 'node:test';
import {chartMark, createChart, unavailable} from '../web/map/chart.ts';
import {MPA_SOURCE, terrainLayers} from '../web/map/layers.ts';
import {MPA_FILL, MPA_LABEL, MPA_LINE, MPA_SERVICE, mpaState} from '../web/map/mpa.ts';
import {readPalette} from '../web/map/palette.ts';
import {createStage, terrainPick} from '../web/map/stage.ts';
import {configureStore, setParams, syncFromURL} from '../web/state.ts';
import {settlePicks} from './helpers/pick-settle.mjs';

const A = 'morro-bay', B = 'southern-california';
const PAGE = 'https://synthetic.test/map';
const palette = readPalette(key => /(?:opacity|width)$/.test(key) ? '1' : `token(${key})`);
const bounds = [0, 0, 1, 1];
const snapshot = (id, name) => ({type: 'FeatureCollection', region_id: id,
  source_url: `${MPA_SERVICE}?geometry=${bounds.join(',')}`, checked_at: '2026-01-01T00:00:00Z',
  features: [{type: 'Feature', properties: {NAME: name, Type: 'SMR'},
    geometry: {type: 'Polygon', coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]]}}]});
const notFound = {ok: false, status: 404};
const json = read => ({ok: true, json: read});
const turn = () => new Promise(resolve => setImmediate(resolve));

function fixture(t, {holdA = false} = {}) {
  const href = `${PAGE}?region=${A}&presentation=chart&layers=none`;
  globalThis.location = {href};
  globalThis.history = {state: null, pushState(_s, _t, url) { location.href = url; }, replaceState(_s, _t, url) { location.href = url; }};
  globalThis.dispatchEvent = () => true;
  t.mock.method(globalThis, 'fetch', async () => notFound);
  t.mock.method(console, 'warn', () => {});
  configureStore({v2: true, storage: null});
  syncFromURL(href);

  const pending = new Map();
  const hold = id => {
    const {promise, resolve} = Promise.withResolvers();
    pending.set(id, promise);
    return name => resolve(snapshot(id, name));
  };
  const oldA = holdA ? hold(A) : null;
  const fetchFn = async url => {
    const [, id, file] = /^\/regions\/([^/]+)\/([^/]+)$/.exec(new URL(url).pathname) ?? [];
    if (file === 'region.json') return json(async () => ({assets: {protected_areas: `regions/${id}/mpa.geojson`}, mpa: {bounds, minimum_features: 1}}));
    if (file === 'coverage.json') return json(async () => ({region_id: id, needs: [{id: 'protected-areas', status: 'ready'}]}));
    if (file === 'mpa.geojson') return json(() => pending.get(id) ?? Promise.resolve(snapshot(id, `Initial ${id}`)));
    return notFound;
  };

  let map;
  const writes = [];
  class MapDouble {
    events = {};
    visibility = {};
    keyboard = this.touchZoomRotate = {disableRotation() {}};
    constructor({style}) { this.style = style; map = this; }
    on(type, fn) { (this.events[type] ??= []).push(fn); }
    addControl() {}
    jumpTo() {}
    remove() {}
    getLayer(id) { return this.style.layers.find(l => l.id === id); }
    getSource(id) { return this.style.sources[id] && {setData(data) { if (id === MPA_SOURCE) writes.push(data); }}; }
    setLayoutProperty(id, _property, value) { this.visibility[id] = value; }
    queryRenderedFeatures(_point, {layers}) {
      return layers.includes(MPA_FILL) && this.hit ? [{layer: {id: MPA_FILL}, properties: this.hit}] : [];
    }
  }
  const Control = class {};
  const library = {lib: {Map: MapDouble, NavigationControl: Control, ScaleControl: Control, AttributionControl: Control,
    setWorkerUrl() {}, addProtocol() {}}, Protocol: class {}};
  const host = {dataset: {}};
  const stage = createStage({host: {shadowRoot: {replaceChildren() {}}}, center: () => [0, 0],
    doc: {hidden: false, addEventListener() {}, removeEventListener() {}},
    renderers: [() => createChart({host, load: async () => library, page: () => href, palette: () => palette, fetchFn})]});
  t.after(() => stage.destroy());
  return {host, hold, oldA, writes, features: () => writes.at(-1)?.features ?? [],
    visibility: () => [MPA_FILL, MPA_LINE, MPA_LABEL].map(id => map.visibility[id]),
    click(properties, settle = true) {
      map.hit = properties;
      for (const fn of map.events.click) fn({point: {x: 1, y: 1}});
      if (settle) settlePicks();
    },
  };
}

test('a held region change withdraws Chart geometry and all old protected-area picks', async t => {
  const f = fixture(t);
  await turn();
  const initial = f.features()[0].properties;
  f.click(initial);
  assert.equal(chartMark.value?.name, `Initial ${A}`);
  terrainPick.value = terrainLayers.value.mpas.pick(0);
  assert.equal(terrainPick.value?.name, `Initial ${A}`);
  f.click(initial, false); // captured before changing region, settles afterwards

  const releaseB = f.hold(B);
  setParams({region: B});
  assert.equal(f.host.dataset.mpa, 'loading');
  assert.equal(terrainLayers.value.mpas, undefined);
  assert.equal(terrainPick.value, null);
  assert.deepEqual(f.features(), [], 'withdraw the previous Chart source without waiting for B');
  assert.deepEqual(f.visibility(), ['none', 'none', 'none'], 'hide while the renderer processes the empty source');
  settlePicks();
  assert.equal(chartMark.value, null);
  f.click(initial); // MapLibre may still have hits from its previous frame
  assert.equal(chartMark.value, null, 'old rendered hits are not selectable while loading');

  releaseB('New B');
  await turn();
  assert.equal(f.host.dataset.mpa, 'complete');
  assert.deepEqual(f.visibility(), ['visible', 'visible', 'visible']);
  f.click(initial);
  assert.equal(chartMark.value, null, 'an old rendered hit is not admitted with the new source');
  f.click(f.features()[0].properties);
  assert.equal(chartMark.value?.name, 'New B');
});

test('A→B→A only publishes and picks the newest A when it settles first', async t => {
  const f = fixture(t, {holdA: true});
  await turn(); // first A is reading its held body
  const releaseB = f.hold(B);
  setParams({region: B});
  await turn(); // B is also held
  const releaseLatestA = f.hold(A);
  setParams({region: A});
  await turn();
  assert.equal(f.host.dataset.mpa, 'loading');
  assert.deepEqual(f.features(), []);

  releaseLatestA('Latest A');
  await turn();
  assert.equal(f.host.dataset.mpa, 'complete');
  const admitted = mpaState.value, terrain = terrainLayers.value.mpas, writes = f.writes.length;
  assert.deepEqual(f.features().map(f => f.properties.NAME), ['Latest A']);
  f.click(f.features()[0].properties);
  assert.equal(chartMark.value?.name, 'Latest A');
  assert.equal(terrain.pick(0)?.name, 'Latest A');

  f.oldA('Superseded A');
  await turn();
  releaseB('Superseded B');
  await turn();
  assert.equal(f.writes.length, writes, 'no late source writes, even from the same region');
  assert.equal(mpaState.value, admitted);
  assert.equal(terrainLayers.value.mpas, terrain);
  assert.ok(!unavailable.value.includes('mpas'));
  f.click(f.features()[0].properties);
  assert.equal(chartMark.value?.name, 'Latest A');
});
