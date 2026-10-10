// The trip planner's ranked spots on the Chart (#495, web/map/ranked.ts): v1's draw gate
// and 44 px grouping pinned to v1's own dist/trip-ranking-layer.js over a fake Leaflet with
// EPSG:3857's projection, the marks' run-time screen (#492) over them, the style from the
// palette, the card's wording, and the Chart path (source data, a lone pin's card, a group's
// zoom, a screen that stops being ready, a cleared plan) over a fake MapLibre.
// Synthetic plan: the 20 screened reefs of e2e/ranked-export.spec.ts, 0.007° apart.
import assert from 'node:assert/strict';
import test from 'node:test';
import {initTripRanking} from '../dist/trip-ranking-layer.js';
import {RANKED_SOURCE} from '../web/map/layers.ts';
import {chartFailed, chartMark, createChart, unavailable} from '../web/map/chart.ts';
import {CHECKING, assessScreen} from '../web/map/habitat.ts';
import {markScreen} from '../web/map/marks.ts';
import {readPalette} from '../web/map/palette.ts';
import {
  NO_PLAN, RANKED_PICK, RANKED_PIN, drawnSpots, fitCamera, rankedCard, rankedFeatures, rankedSpots, rankedStyle, recheckPlan, screenRanked, zoomToGroup,
} from '../web/map/ranked.ts';
import {createStage, terrainFailed} from '../web/map/stage.ts';
import {configureStore, syncFromURL} from '../web/state.ts';

const PAGE = 'https://s.test/map';
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
const settle = async () => { for (let i = 0; i < 6; i++) await tick(); };
const sentinel = readPalette(name => `token(${name})`);
const SENTINELS = new Set(Object.values(sentinel));
/** Words § 12 keeps off every card: no count, chance or promise of fish, and no "best". */
const PROMISE = /\b(?:hotspot|chance|odds|probab\w*|productive|best|catch rate|bite|guarantee\w*)\b/i;

const square = (x, y) => ({type: 'Polygon', coordinates: [[[x, y], [x + .002, y], [x + .002, y + .002], [x, y + .002], [x, y]]]});
const publication = {region: 'morro-bay', status: 'ready', archive_sha256: 'a'.repeat(64), export_sha256: 'b'.repeat(64),
  expires_at: new Date(Date.now() + 86400000).toISOString(), verified_at: new Date(Date.now() - 1000).toISOString()};
const reefs = Array.from({length: 20}, (_, i) => {
  const x = -121.17 + i * .007, y = 35.43, id = 'test-reef-' + String(i).padStart(2, '0');
  return {target: {id, name: `${String(i + 1).padStart(2, '0')} LR H3 C90% 90-120ft`, latitude: y + .001, longitude: x + .001, trip_rank: i + 1, trip_fit: 3,
    evidence_confidence: {percent: 90}, area_ids: [id], survey_year: 2008, terrain_interpretation: '12.0 m local relief; 2.0 ha reef footprint.',
    special_note: 'Interior reef reference point, not a sampled point depth. Search the reef on your sounder and test your drift.',
    evidence_status: '90% habitat evidence index (habitat-evidence-v1); not catch probability.'}, area: {id, geometry: square(x, y)}};
});
// The planner's order is the ranks; the event may list them in any order.
const PLAN = {targets: reefs.map(r => r.target).reverse(), areas: reefs.map(r => r.area), publication};
/** A screen that is current and withholds the named points and areas. */
const screen = ({ready = true, points = [], areas = []} = {}) => ({
  ready: () => ready,
  pointAllowed: p => ready && !points.includes(p.id),
  geometryAllowed: g => ready && !areas.some(id => PLAN.areas.find(a => a.id === id).geometry === g),
});

/** The marks' run-time screen (#492): ready with these boundaries, stale (37 h old) or unavailable (no boundaries). */
const HOUR = 3600000;
const marksReady = (areas = []) => assessScreen({areas, checkedAt: new Date().toISOString(), live: true}, Date.now());
const marksStale = () => assessScreen({areas: [], checkedAt: new Date(Date.now() - 37 * HOUR).toISOString(), live: false}, Date.now());
const marksUnavailable = () => assessScreen({areas: null, checkedAt: null, live: false}, Date.now());

/** v1's layer over a fake Leaflet: Leaflet's EPSG:3857 projection at `zoom`, and the pins it draws. */
async function v1Pins(plan, s, zoom) {
  const saved = Object.fromEntries(['L', 'document', 'fetch', 'setInterval', 'requestAnimationFrame'].map(k => [k, globalThis[k]]));
  const R = 6378137, d = Math.PI / 180, k = 0.5 / (Math.PI * R), size = 256 * 2 ** zoom;
  const point = (x, y) => ({x, y, distanceTo: o => Math.hypot(o.x - x, o.y - y)});
  const pins = [], drawable = () => ({addTo() { return this; }, bindTooltip() { return this; }, on() { return this; }});
  const layer = {clearLayers() { pins.length = 0; }, remove() {}, addTo() {}};
  Object.assign(globalThis, {document: new EventTarget(), setInterval() {}, requestAnimationFrame() {},
    L: {layerGroup: () => layer, canvas: () => ({}), geoJSON: drawable, divIcon: x => x,
      marker: ([lat, lng], {icon, title}) => { pins.push({lat, lng, title, html: icon.html}); return drawable(); }}});
  try {
    const map = {on() {}, latLngToLayerPoint([lat, lng]) {
      const sin = Math.sin(Math.max(Math.min(85.0511287798, lat), -85.0511287798) * d);
      return point(size * (k * R * lng * d + 0.5), size * (-k * R * Math.log((1 + sin) / (1 - sin)) / 2 + 0.5));
    }};
    initTripRanking(map, s, () => {});
    document.dispatchEvent(new CustomEvent('skippercast:trip-ranked', {detail: plan}));
    return pins.map(p => ({rank: Number(/<span>(\d+)<\/span>/.exec(p.html)[1]), more: Number(/\+(\d+)/.exec(p.html)?.[1] ?? 0), coordinates: [p.lng, p.lat]}));
  } finally { Object.assign(globalThis, saved); }
}
const v2Pins = (plan, s, zoom) => rankedFeatures(screenRanked(plan, s, new Map(), 'morro-bay'), zoom).features
  .map(f => ({rank: f.properties.rank, more: f.properties.more, coordinates: f.geometry.coordinates}));

test('the pins are v1\'s: the same spots withheld, numbered by rank and grouped within 44 px at the camera\'s zoom', async () => {
  const cases = [
    ['all screened', PLAN, screen(), 10.9],
    ['zoomed in', PLAN, screen(), 16],
    ['a withheld point', PLAN, screen({points: ['test-reef-00', 'test-reef-06']}), 10.9],
    ['a withheld reef area', PLAN, screen({areas: ['test-reef-02']}), 13],
    ['a stale screen', PLAN, screen({ready: false}), 12],
    ['a spot without a rank', {...PLAN, targets: PLAN.targets.map(t => t.id === 'test-reef-04' ? {...t, trip_rank: undefined} : t)}, screen(), 16],
    ['an expired publication', {...PLAN, publication: {...publication, expires_at: '2000-01-01'}}, screen(), 12],
    ['a held publication', {...PLAN, publication: {...publication, status: 'held'}}, screen(), 12],
    ['a cleared plan', {targets: [], areas: []}, screen(), 12],
  ];
  for (const [name, plan, s, zoom] of cases) assert.deepEqual(v2Pins(plan, s, zoom), await v1Pins(plan, s, zoom), name);
  const grouped = v2Pins(PLAN, screen(), 10.9);
  assert.deepEqual(grouped.map(p => [p.rank, p.more]), [[1, 4], [6, 4], [11, 4], [16, 4]], 'each pin sits at its best-ranked spot');
  assert.deepEqual(grouped[0].coordinates, [-121.169, 35.431]);
  assert.equal(v2Pins(PLAN, screen(), 16).length, 20);
  assert.deepEqual(v2Pins(PLAN, screen({points: ['test-reef-00']}), 16)[0].rank, 2, 'a withheld spot keeps the others\' numbers');
});

test('a rejected publication stays hidden until verified again; another region or an invalid plan draws nothing', () => {
  const rejected = new Map([[publication.export_sha256, Date.now()]]);
  assert.deepEqual(screenRanked(PLAN, screen(), rejected, 'morro-bay'), [], 'verified before the rejection');
  const later = {...PLAN, publication: {...publication, verified_at: new Date(Date.now() + 1000).toISOString()}};
  assert.equal(screenRanked(later, screen(), rejected, 'morro-bay').length, 20);
  assert.equal(rejected.size, 0, 'a later verification lifts it');
  assert.deepEqual(screenRanked({...PLAN, invalid: true}, screen(), rejected, 'morro-bay'), []);
  assert.deepEqual(screenRanked(PLAN, screen(), rejected, 'cambria-san-simeon'), [], 'the plan is bound to its region');
  assert.deepEqual(screenRanked(PLAN, null, rejected, 'morro-bay'), [], 'no screen, no pins');
  assert.deepEqual(screenRanked(NO_PLAN, screen(), rejected, 'morro-bay'), []);
  assert.deepEqual(rankedFeatures(screenRanked(PLAN, screen(), rejected, 'morro-bay'), null).features, [], 'no camera, no pins');
});

test('the every-minute re-check keeps a plan its publication still matches; a changed or not-ready one holds it until verified again', () => {
  const now = Date.now(), ready = {state: 'ready', manifest: {export_sha256: publication.export_sha256}};
  const kept = new Map();
  assert.equal(recheckPlan(PLAN, ready, kept, now), PLAN, 'same hash, ready: the same plan');
  assert.equal(kept.size, 0);
  assert.equal(recheckPlan(NO_PLAN, {state: 'held'}, kept, now), NO_PLAN, 'a cleared plan is left alone');
  const gates = [['a changed hash', {state: 'ready', manifest: {export_sha256: 'c'.repeat(64)}}],
    ['held', {state: 'held'}], ['updating', {state: 'updating'}], ['unavailable', {state: 'unavailable'}]];
  for (const [name, gate] of gates) {
    const rejected = new Map(), next = recheckPlan(PLAN, gate, rejected, now);
    assert.deepEqual(next, {...PLAN, invalid: true}, name);
    assert.deepEqual([...rejected], [[publication.export_sha256, now]], `${name}: the hash is held`);
  }
  const rejected = new Map();
  recheckPlan(PLAN, {state: 'held'}, rejected, now);
  assert.deepEqual(screenRanked(PLAN, screen(), rejected, 'morro-bay'), [], 'held: nothing drawn');
  const later = {...PLAN, publication: {...publication, verified_at: new Date(now + 1000).toISOString()}};
  assert.equal(screenRanked(later, screen(), rejected, 'morro-bay').length, 20, 'a later verification lifts the hold');
});

test('a spot the marks\' run-time screen (#492) withholds is not drawn, the others keep their ranks; no ready screen, no pins', () => {
  rankedSpots.value = screenRanked(PLAN, screen(), new Map(), 'morro-bay');
  try {
    for (const s of [CHECKING, marksStale(), marksUnavailable()]) {
      markScreen.value = s;
      assert.deepEqual(drawnSpots.value, [], `${s.status}: the planner's screen alone draws nothing`);
    }
    // A boundary the marks' screen holds over spot 1 (its reef square) that the planner's screen does not.
    markScreen.value = marksReady([{type: 'Feature', properties: {NAME: 'Test SMR'}, geometry: reefs[0].area.geometry}]);
    assert.deepEqual(drawnSpots.value.map(t => t.trip_rank), Array.from({length: 19}, (_, i) => i + 2));
    assert.deepEqual(rankedFeatures(drawnSpots.value, 16).features.map(f => f.properties.rank)[0], 2, 'pin 2 keeps its number');
    markScreen.value = marksReady();
    assert.equal(drawnSpots.value.length, 20);
  } finally { rankedSpots.value = []; markScreen.value = CHECKING; }
});

test('the style: a 44 px target, a numbered disc and a "+n", all from the palette', () => {
  const {source, layers} = rankedStyle(sentinel);
  assert.deepEqual(source, {type: 'geojson', data: {type: 'FeatureCollection', features: []}});
  assert.deepEqual(layers.map(l => l.id), [RANKED_PICK, RANKED_PIN, 'ranked-number', 'ranked-more']);
  assert.ok(layers.every(l => l.source === RANKED_SOURCE));
  assert.equal(layers[0].paint['circle-radius'] * 2, 44, 'a 44 px target');
  assert.equal(layers[0].paint['circle-opacity'], 0);
  assert.deepEqual(layers[2].layout['text-field'], ['to-string', ['get', 'rank']], 'numbered by trip_rank');
  assert.deepEqual(layers[3].filter, ['>', ['get', 'more'], 0]);
  // The number is the documented primary-button pair (scripts/check_contrast.mjs): bg on mint.
  assert.equal(layers[1].paint['circle-color'], sentinel.mint);
  assert.equal(layers[2].paint['text-color'], sentinel.bg);
  const json = JSON.stringify(layers);
  assert.equal(json.match(/"#[0-9a-f]{3,8}"|"rgba?\(/gi), null, 'no colour literal');
  assert.ok(json.match(/token\([a-z0-9-]+\)/g).every(c => SENTINELS.has(c)), 'every colour is a palette token');
});

test('a spot\'s card has v1\'s lines in the planner\'s order and reviews the spot in the plan', () => {
  const card = rankedCard(reefs[0].target, {id: 'morro-bay'});
  assert.deepEqual(card, {
    id: 'ranked:test-reef-00', name: '#1 · 01 LR H3 C90% 90-120ft', kind: 'Ranked trip spot · numbered in the planner\'s order',
    reading: 'Habitat 3/3 · 90% evidence confidence', source: 'Seafloor publication · surveyed 2008',
    rules: 'Drawn while this session\'s protected-area check is current; check current rules before you fish.',
    regulations: {href: 'https://wildlife.ca.gov/Fishing/Ocean/Regulations', label: 'CDFW ocean fishing regulations'},
    basis: `${reefs[0].target.terrain_interpretation} ${reefs[0].target.special_note} ${reefs[0].target.evidence_status}`,
    trip: 'test-reef-00',
  });
  for (const line of [card.name, card.kind, card.reading, card.source, card.rules]) assert.doesNotMatch(line, PROMISE);
  assert.equal(rankedCard({...reefs[0].target, trip_fit: undefined, evidence_confidence: null}, null).reading, 'Habitat fit unrated');
});

/** A browser just big enough for navigate(). */
function browser(href) {
  globalThis.location = {href};
  globalThis.history = {state: null, pushState(_s, _t, url) { location.href = url; }, replaceState(_s, _t, url) { location.href = url; }};
  globalThis.dispatchEvent = () => true;
  configureStore({v2: true, storage: null});
  syncFromURL(href);
  return {params: () => new URL(location.href).searchParams};
}
/** A fake MapLibre map: GeoJSON data per source, and clicks that pick what the test puts under them. */
function library() {
  const fake = {maps: [], features: []};
  class FakeMap {
    constructor(options) { this.options = options; this.handlers = {}; this.data = {}; fake.maps.push(this); this.keyboard = this.touchZoomRotate = {disableRotation() {}}; }
    on(type, fn) { (this.handlers[type] ??= []).push(fn); }
    fire(type, event = {}) { for (const fn of this.handlers[type] ?? []) fn(event); }
    addControl() {}
    getCenter() { return {lat: this.options.center[1], lng: this.options.center[0]}; }
    getZoom() { return this.options.zoom; }
    jumpTo() {}
    getLayer(id) { return this.options.style.layers.some(l => l.id === id) ? {} : undefined; }
    setLayoutProperty() {}
    getSource(id) { return this.options.style.sources[id] ? {setData: data => { this.data[id] = data; }} : undefined; }
    queryRenderedFeatures(_point, options) { const layers = options?.layers ?? _point.layers; return fake.features.filter(f => layers.includes(f.layer.id)); }
    resize() {}
    remove() {}
  }
  const control = class {};
  fake.module = {lib: {Map: FakeMap, NavigationControl: control, ScaleControl: control, AttributionControl: control, setWorkerUrl() {}, addProtocol() {}},
    workerUrl: '/w.js', Protocol: class { constructor() { this.tile = () => {}; } }};
  return fake;
}
const files = async url => ({ok: false, status: 404, json: async () => ({}), url});

test('on the Chart: the plan\'s pins, a lone pin\'s card, a group\'s zoom, and a cleared plan', async t => {
  t.mock.method(console, 'warn', () => {});
  const nav = browser(`${PAGE}?region=morro-bay&presentation=chart&view=35.43100,-121.10000,10.9`);
  terrainFailed.value = false; chartFailed.value = false; chartMark.value = null; unavailable.value = []; rankedSpots.value = [];
  const lib = library(), host = {dataset: {}};
  const stage = createStage({host: {dataset: {}, shadowRoot: {replaceChildren() {}}}, load: async () => ({styles: [], mountCoast: () => ({})}),
    center: () => [35.37, -120.86], viewDelay: 0, doc: {hidden: false, addEventListener() {}, removeEventListener() {}},
    renderers: [() => createChart({host, load: async () => lib.module, fetchFn: files, palette: () => sentinel, page: () => PAGE, viewDelay: 0})]});
  await settle();
  markScreen.value = marksReady();
  const [map] = lib.maps;
  assert.ok(map, 'the Chart mounted');
  assert.deepEqual(map.data[RANKED_SOURCE]?.features ?? [], [], 'no plan, no pins');
  assert.equal(host.dataset.ranked, '0');

  rankedSpots.value = screenRanked(PLAN, screen(), new Map(), 'morro-bay');
  assert.equal(host.dataset.ranked, '20');
  assert.deepEqual(map.data[RANKED_SOURCE].features.map(f => [f.properties.rank, f.properties.more]), [[1, 4], [6, 4], [11, 4], [16, 4]]);
  lib.features = [{layer: {id: RANKED_PIN}}, {layer: {id: RANKED_PIN}}];
  map.fire('idle');
  assert.equal(host.dataset.rankedDrawn, '2', 'what MapLibre drew in view');

  // A group's pin zooms to its five spots and leaves the selection alone.
  chartMark.value = null;
  const group = map.data[RANKED_SOURCE].features[0].properties;
  lib.features = [{layer: {id: RANKED_PICK}, properties: group}];
  map.fire('click', {point: {x: 0, y: 0}, lngLat: {lng: -121.169, lat: 35.431}});
  const view = nav.params().get('view').split(',').map(Number);
  assert.ok(Math.abs(view[0] - 35.431) < 1e-5 && Math.abs(view[1] + 121.155) < 1e-5 && view[2] > 12.5, String(view));
  assert.equal(chartMark.value, null);
  await settle();
  assert.equal(map.data[RANKED_SOURCE].features[0].properties.more, 0, 'zoomed in, pin 1 stands alone');

  // A lone pin opens its card; the marks' screen going stale (#492) takes the pins and the card.
  const pin1 = map.data[RANKED_SOURCE].features[0].properties;
  lib.features = [{layer: {id: RANKED_PICK}, properties: pin1}];
  map.fire('click', {point: {x: 0, y: 0}, lngLat: {lng: -121.169, lat: 35.431}});
  assert.equal(chartMark.value.name, '#1 · 01 LR H3 C90% 90-120ft');
  assert.equal(chartMark.value.trip, 'test-reef-00');
  markScreen.value = marksStale();
  assert.equal(chartMark.value, null, 'the card goes with its pin');
  assert.deepEqual(map.data[RANKED_SOURCE].features, []);
  assert.equal(host.dataset.ranked, '0');
  map.fire('click', {point: {x: 0, y: 0}, lngLat: {lng: -121.169, lat: 35.431}});
  assert.equal(chartMark.value, null, 'a withheld spot opens no card');
  markScreen.value = CHECKING;
  assert.deepEqual(map.data[RANKED_SOURCE].features, [], 'checking again: still none');
  markScreen.value = marksReady();
  assert.equal(host.dataset.ranked, '20');

  // A cleared plan takes the pins and the card.
  map.fire('click', {point: {x: 0, y: 0}, lngLat: {lng: -121.169, lat: 35.431}});
  assert.equal(chartMark.value.trip, 'test-reef-00');
  rankedSpots.value = [];
  assert.equal(chartMark.value, null);
  assert.deepEqual(map.data[RANKED_SOURCE].features, []);
  assert.equal(host.dataset.ranked, '0');
  stage.destroy();
});

test('a group without an extent is not zoomed; the fit is FE-51\'s', () => {
  assert.equal(zoomToGroup({more: 0, west: 1, south: 1, east: 2, north: 2}), false);
  assert.equal(zoomToGroup({more: 2, west: 'x'}), false);
  assert.equal(zoomToGroup(null), false);
  assert.equal(fitCamera([]), null);
});
