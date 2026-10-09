// Habitat, geology, reef marks and the one mark card (FE-18, docs/plans/front-end/dev-plan.md,
// design § 9 "Habitat and marks", § 12): the data-to-feature step over the committed
// region files (read from dist/, offline), the v1 rules it restates pinned to the v1
// functions, the card's claim wording, and one selection across `?spot=` and
// `?habitat=` through the stage and the Chart with fake renderers. The web/map/*.ts
// files run by type stripping.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {speciesFit} from '../dist/species-fit.js';
import {matchesSpecies} from '../dist/species.js';
import {habitatMatches} from '../dist/survey-habitat.js';
import {
  CDFW_REGULATIONS, EMPTY, atlasCard, fitLine, geologyCard, geologyFeatures, geologyShown, habitatFamily, markFeatures, markFit, markShown,
  receiptCard, regulationsLink, surveyCard, surveyFeatures, surveyMatches, terrainCard, terrainDetailCard,
} from '../web/map/habitat.ts';
import {
  GEOLOGY_PICK, MARK_PICK, SURVEY_PICK, chartPick, createMarks, habitatCard, habitatReceipt, markData, markSources, markStyle, picked, spotCard, spotHref,
} from '../web/map/marks.ts';
import {GEOLOGY_SOURCE, MARKS_SOURCE, SELECTION_SOURCE, SURVEY_SOURCE} from '../web/map/layers.ts';
import {ENC_LAYER, chartFailed, chartMark, chartStyle, createChart, unavailable} from '../web/map/chart.ts';
import {createEngine} from '../web/map/engine.ts';
import {COASTLINE_GLOW, COASTLINE_PICK} from '../web/map/coastline.ts';
import {readPalette} from '../web/map/palette.ts';
import {createStage, habitatHref, terrainDetail, terrainFailed, terrainMark} from '../web/map/stage.ts';
import {configureStore, navigate, setParams, syncFromURL} from '../web/state.ts';

const PAGE = 'https://s.test/map';
const read = path => JSON.parse(readFileSync(new URL(`../dist/${path}`, import.meta.url), 'utf8'));
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
const settle = async () => { for (let i = 0; i < 6; i++) await tick(); };
const MORRO = read('regions/morro-bay/region.json'), ATLAS = read('data/atlas.json');
const CAMBRIA = read('regions/cambria-san-simeon/region.json');
const SURVEY = read('regions/cambria-san-simeon/survey-habitat.geojson'), GEOLOGY = read('regions/cambria-san-simeon/geology.geojson');
const SOCAL = read('regions/southern-california/region.json'), SOCAL_ATLAS = read('regions/southern-california/atlas.json');
const sentinel = readPalette(name => `token(${name})`);
const SENTINELS = new Set(Object.values(sentinel));
/** Words § 12 keeps off every card: no count, chance or promise of fish. */
const PROMISE = /\b(?:hotspot|chance|odds|probab\w*|productive|best spot|catch rate|bite|guarantee\w*)\b/i;

test('v1\'s rules are kept: marks per target, survey outlines per family and the geology kinds', () => {
  for (const atlas of [ATLAS, SOCAL_ATLAS]) {
    for (const id of ['reef', 'rockfish', 'lingcod', 'halibut', 'salmon', 'dungeness']) {
      for (const t of atlas.targets) assert.equal(markShown(t, id), matchesSpecies(t, id), `${t.id} for ${id}`);
    }
  }
  assert.ok(ATLAS.targets.some(t => !markShown(t, 'lingcod')) && ATLAS.targets.some(t => markShown(t, 'lingcod')), 'lingcod keeps v1\'s rough-relief screen');
  assert.equal(markShown(ATLAS.targets[0], 'cabezon-shallow-reef'), true, 'a v2 reef target reads the reef marks');
  for (const [region, survey] of [[CAMBRIA, SURVEY], [SOCAL, read('regions/southern-california/survey-habitat.geojson')]]) {
    for (const option of region.target_options) {
      for (const f of survey.features) assert.equal(surveyMatches(f.properties, option.id, region), habitatMatches(f, option.id, region), `${f.properties.id} for ${option.id}`);
    }
  }
  assert.equal(habitatFamily('lingcod'), 'reef');
  assert.equal(habitatFamily('kelp-bass'), 'kelp-bass', 'a target with its own habitat kinds keeps them');
  // dist/geology.js: rock and mixed for reef targets, sediment for halibut and dungeness, nothing else.
  assert.deepEqual(['rock', 'mixed', 'sediment'].map(k => geologyShown(k, 'reef')), [true, true, false]);
  assert.deepEqual(['rock', 'mixed', 'sediment'].map(k => geologyShown(k, 'halibut')), [false, false, true]);
  assert.deepEqual(['rock', 'sediment'].map(k => geologyShown(k, 'salmon')), [false, false]);
});

test('fit is v1\'s ordinal, 3 the strongest, in the one wording "fits <species> habitat n of 3"', () => {
  for (const t of ATLAS.targets) {
    for (const species of ['lingcod', 'rockfish']) {
      const v1 = speciesFit(t, species);
      assert.deepEqual(markFit(t, species), v1 && {n: 4 - v1.rank, line: `Fits ${species} habitat ${4 - v1.rank} of 3`});
    }
    // v1's combined reef fit (dist/app.js selectedSpeciesFit): the weaker of the two screens.
    const both = ['lingcod', 'rockfish'].map(s => speciesFit(t, s).rank);
    assert.equal(markFit(t, 'reef').line, `Fits lingcod and rockfish habitat ${4 - Math.max(...both)} of 3`);
  }
  const top = ATLAS.targets.find(t => t.id === 'SC26-001');
  assert.equal(markFit(top, 'lingcod').line, 'Fits lingcod habitat 3 of 3');
  assert.equal(markFit(top, 'gopher-rockfish').line.startsWith('Fits rockfish habitat'), true, 'a rockfish target reads v1\'s rockfish screen and says so');
  assert.equal(markFit(top, 'cabezon-shallow-reef'), null, 'no screen rates cabezon');
  assert.equal(markFit(SOCAL_ATLAS.targets[0], 'lingcod'), null, 'missing terrain metrics leave the fit unrated');
  assert.equal(fitLine('lingcod', 2), 'Fits lingcod habitat 2 of 3');
});

test('marks are points with their fit badge, inside the profile\'s depth limit', () => {
  const boat = markFeatures(ATLAS, 'lingcod', 'boat');
  assert.equal(boat.features.length, ATLAS.targets.filter(t => matchesSpecies(t, 'lingcod')).length);
  const first = boat.features.find(f => f.properties.id === 'SC26-001');
  assert.deepEqual(first, {type: 'Feature', geometry: {type: 'Point', coordinates: [-120.843179, 35.164314]}, properties: {id: 'SC26-001', fit: '3'}});
  const spear = markFeatures(ATLAS, 'reef', 'spear');
  assert.ok(spear.features.length > 0 && spear.features.every(f => ATLAS.targets.find(t => t.id === f.properties.id).neighborhood_depth_ft[1] <= 60), 'Spear: 60 ft');
  assert.ok(markFeatures(ATLAS, 'cabezon-shallow-reef', 'spear').features.every(f => !('fit' in f.properties)), 'no badge without a fit');
  assert.deepEqual(markFeatures(ATLAS, 'halibut', 'boat').features, [], 'soft-bottom targets show no reef marks');
  assert.deepEqual(markFeatures(null, 'reef', 'boat'), EMPTY);
});

test('a mark\'s card: fit, grade and depth range; source and age; the regulations line; credit and rights in the basis', () => {
  const data = {region: MORRO, atlas: ATLAS, survey: null, geology: null};
  const card = atlasCard(ATLAS.targets.find(t => t.id === 'SC26-001'), data, 'lingcod');
  assert.deepEqual({...card, basis: undefined}, {
    id: 'spot:SC26-001', name: 'Southern rocky rise', kind: 'Reef mark · grade A · ~135–184 ft', reading: 'Fits lingcod habitat 3 of 3',
    source: 'Avila / Point Buchon · surveyed 2008 · atlas 2026-09-27',
    rules: 'Screened against protected areas with 2992 m clearance in the atlas of 2026-09-27; check current rules before you fish.',
    regulations: {href: 'https://wildlife.ca.gov/Fishing/Ocean/Regulations', label: 'CDFW ocean fishing regulations'}, basis: undefined,
  });
  assert.match(card.basis, /^Raised, rough bedrock.*Research-only historical terrain candidate.*USGS; CSUMB Seafloor Mapping Lab.*U\.S\. public domain/);
  const socal = atlasCard(SOCAL_ATLAS.targets[0], {region: SOCAL, atlas: SOCAL_ATLAS, survey: null, geology: null}, 'reef');
  assert.equal(socal.reading, 'Habitat fit unrated for this target');
  assert.equal(socal.source, 'NOAA H13093: Vicinity of Anacapa Island · surveyed 2017 · atlas 2026-09-24');
  assert.match(socal.basis, /CC0-1\.0/, 'each feature carries its own source\'s rights');
  assert.equal(socal.rules, 'Screened against protected areas with 75 m clearance in the atlas of 2026-09-24; check current rules before you fish.', 'v1\'s terrain-evidence wording');
  assert.deepEqual(socal.regulations, {href: 'https://wildlife.ca.gov/Fishing/Ocean/Regulations/Fishing-Map/Southern', label: 'CDFW regional fishing regulations'}, 'the region\'s own CDFW page');
  assert.equal(regulationsLink({id: 'x', regulations_url: 'https://example.test/rules'}).href, CDFW_REGULATIONS, 'only an official CDFW page');
  for (const t of [...ATLAS.targets, ...SOCAL_ATLAS.targets]) {
    const c = atlasCard(t, {region: MORRO, atlas: ATLAS, survey: null, geology: null}, 'reef');
    assert.doesNotMatch(`${c.name} ${c.kind} ${c.reading} ${c.rules}`, PROMISE, t.id);
    assert.doesNotMatch(c.rules, /\bclear of\b|\ballowed\b|\blegal to\b/i, 'never a clearance promise');
    if (/of 3/.test(c.reading)) assert.match(c.reading, /^Fits .+ habitat [1-3] of 3$/, 'the fit line is the one wording');
  }
});

test('survey habitat fills and geology outlines carry their class; their cards name source, age and the build\'s MPA screen', () => {
  const data = {region: CAMBRIA, atlas: null, survey: SURVEY, geology: GEOLOGY};
  const fills = surveyFeatures(data, 'lingcod');
  assert.equal(fills.features.length, SURVEY.features.length);
  assert.deepEqual(fills.features[0].properties, {id: SURVEY.features[0].properties.id, kind: 'rock'});
  assert.deepEqual(surveyFeatures(data, 'halibut').features, [], 'rocky outlines are reef habitat');
  assert.ok(geologyFeatures(data, 'reef').features.every(f => f.properties.kind !== 'sediment'));
  assert.ok(geologyFeatures(data, 'halibut').features.every(f => f.properties.kind === 'sediment'));
  assert.deepEqual(geologyFeatures(data, 'salmon'), {type: 'FeatureCollection', features: []});

  const survey = surveyCard(SURVEY.features[0].properties, SURVEY, CAMBRIA);
  assert.equal(survey.kind, 'Mapped hard bottom');
  assert.equal(survey.reading, '0.574 km²');
  assert.equal(survey.source, 'USGS original seafloor-character class 3 · compiled 2022-06-07');
  assert.equal(survey.rules, 'MPAs subtracted with a 102 m margin when built on 2026-09-26; check current rules before you fish.');
  assert.match(survey.basis, /^Compiled historical habitat, not a waypoint/);
  const unit = GEOLOGY.features[0].properties, geology = geologyCard(unit, GEOLOGY, CAMBRIA);
  assert.deepEqual([geology.name, geology.kind, geology.source], ['Coast Range ophiolite', 'Geology · map unit Jo?', 'U.S. Geological Survey, Watt and others, SIM 3327 (2015)']);
  assert.equal(geology.rules, 'MPAs excluded when the layer was built; check current rules before you fish.');
  assert.equal(geologyCard(unit, {...GEOLOGY, source: {}}, CAMBRIA).rules, 'Check current rules before you fish.', 'no screen claimed where the build states none');
  for (const c of [survey, geology]) assert.equal(c.regulations.href, CDFW_REGULATIONS, 'every card links the official rules');
  for (const c of [survey, geology]) assert.doesNotMatch(`${c.kind} ${c.reading} ${c.rules}`, PROMISE);
});

test('the terrain\'s evidence lines read verbatim in the card, with its fit in the same wording', () => {
  const detail = {id: 'reef:r1', kind: 'reef', title: 'Lingcod habitat · grade A', facts: 'Nominal 40–80 ft · physical score 72/100 · species fit 3/3',
    evidence: 'morro bay · 2 m source grid · 2012 · 85% metric support. Independent substrate confirmation absent. Depth reference NAVD88. Screening valid until 1/2/2027. Fish presence unverified.'};
  assert.deepEqual(terrainDetailCard(detail, 'lingcod'), {
    id: 'habitat:reef:r1', name: 'Lingcod habitat · grade A', kind: 'Terrain reef habitat · reef:r1',
    reading: 'Nominal 40–80 ft · physical score 72/100 · fits lingcod habitat 3 of 3',
    source: 'morro bay · 2 m source grid · 2012 · 85% metric support.',
    basis: 'Independent substrate confirmation absent. Depth reference NAVD88. Screening valid until 1/2/2027. Fish presence unverified.',
  });
  assert.equal(terrainDetailCard({...detail, facts: 'Nominal 40–80 ft · physical score 72/100 · species fit 2/3'}, 'rockfish-reef').reading.endsWith('fits reef rockfish habitat 2 of 3'), true);
  assert.equal(terrainDetailCard({...detail, facts: 'Nominal 40–80 ft · physical score 72/100'}, 'all').reading, 'Nominal 40–80 ft · physical score 72/100');
  const receipt = {id: 'reef:r1', latitude: 35.38, longitude: -120.88, expiresAt: '2027-01-02T00:00:00.000Z', kind: 'reef'};
  assert.deepEqual(receiptCard(receipt), {id: 'habitat:reef:r1', name: 'Reef habitat', kind: 'Terrain habitat · reef:r1', reading: '35.3800° N, 120.8800° W',
    source: 'Reviewed coastal habitat · valid until 2027-01-02', basis: 'Restored from the reviewed habitat release; its evidence lines show in the 2D and 3D terrain.'});
  assert.equal(terrainCard({latitude: 35.38, longitude: -120.88, id: 'reef:r1'}).reading, '35.3800° N, 120.8800° W');
  // The rewrite depends on the renderer's own facts string: a change there fails here, not silently in the card.
  const viewer = readFileSync(new URL('../packages/coast/src/coast3d/viewer.ts', import.meta.url), 'utf8');
  assert.match(viewer, /' · species fit '\+p\[this\.option\(\)\.field!\]\+'\/3'/, 'packages/coast still writes "species fit n/3"');
});

test('web/map/coast-habitat.js is packages/coast\'s resolver: an unknown species answers null without a request', async () => {
  const {resolveHabitatSelection} = await import('../web/map/coast-habitat.js');
  const original = globalThis.fetch;
  let asked = 0;
  globalThis.fetch = async () => { asked++; throw new Error('offline'); };
  try {
    assert.equal(await resolveHabitatSelection({id: 'reef:r1', species: 'not-a-species', depthLimitFt: 60}), null);
    assert.equal(asked, 0);
  } finally { globalThis.fetch = original; }
});

test('the Chart style draws habitat in its § 9 slot and marks under the coastline, from the palette, with 44 px mark targets', () => {
  const style = chartStyle({palette: sentinel, archive: null, page: PAGE, region: 'morro-bay', base: 'night'});
  const ids = style.layers.map(l => l.id);
  for (const source of [SURVEY_SOURCE, GEOLOGY_SOURCE, MARKS_SOURCE, SELECTION_SOURCE]) assert.deepEqual(style.sources[source], {type: 'geojson', data: EMPTY}, source);
  // § 9: MPAs (FE-19), then habitat, the seafloor (FE-14), marks and the selection, the coastline on top.
  const at = id => ids.indexOf(id);
  assert.deepEqual(ids.slice(at(SURVEY_PICK), at(SURVEY_PICK) + 3), [SURVEY_PICK, GEOLOGY_PICK, 'geology-line']);
  assert.ok(at(ENC_LAYER) < at('mpa-line') && at('mpa-label') < at(SURVEY_PICK) && at('geology-line') < at('seafloor-fill') && at('seafloor-unranked') < at(MARK_PICK), ids.join(' '));
  assert.deepEqual(ids.slice(at(MARK_PICK)), [MARK_PICK, 'marks-ring', 'marks-fit', 'selection-ring', COASTLINE_GLOW, 'coastline']);
  const layer = id => style.layers.find(l => l.id === id);
  assert.equal(layer(SURVEY_PICK).paint['fill-opacity'], 0.25, 'habitat fills at 0.25');
  assert.deepEqual(layer('geology-line').paint['line-dasharray'], [3, 2], 'geology as a dashed outline');
  assert.equal(layer(MARK_PICK).paint['circle-radius'] * 2, 44, 'a 44 px target under each ring');
  assert.equal(layer(MARK_PICK).paint['circle-opacity'], 0);
  assert.deepEqual(layer('marks-fit').layout['text-field'], ['get', 'fit']);
  for (const id of [SURVEY_PICK, GEOLOGY_PICK, MARK_PICK, 'marks-fit']) assert.equal(layer(id).minzoom, 9, `${id} from ?view= zoom 10`);
  const colours = JSON.stringify(markStyle(sentinel)).match(/"#[0-9a-f]{3,8}"|"rgba?\(/gi);
  assert.equal(colours, null, 'no colour literal');
  const used = new Set(JSON.stringify(markStyle(sentinel)).match(/token\([a-z0-9-]+\)/g));
  assert.ok([...used].every(c => SENTINELS.has(c)) && used.size >= 5, 'every colour is a palette token');
});

/** A browser just big enough for navigate(): an address, a history stack with Back, and no-op events. */
function browser(href) {
  const stack = [href];
  globalThis.location = {href};
  globalThis.history = {state: null, pushState(_s, _t, url) { stack.push(url); location.href = url; }, replaceState(_s, _t, url) { stack[stack.length - 1] = url; location.href = url; }};
  globalThis.dispatchEvent = () => true;
  configureStore({v2: true, storage: null});
  syncFromURL(href);
  return {back() { stack.pop(); location.href = stack.at(-1); syncFromURL(location.href); }, params: () => new URL(location.href).searchParams, stack};
}
/** The committed region files, served from dist/; `fail` names paths that answer 503. */
const files = (fail = []) => async url => {
  const path = new URL(url).pathname.slice(1);
  if (fail.includes(path)) return {ok: false, status: 503, json: async () => ({})};
  return {ok: true, json: async () => read(path)};
};
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
    getSource(id) { return this.styleLoaded !== false && this.options.style.sources[id] ? {setData: data => { this.data[id] = data; }} : undefined; }
    queryRenderedFeatures(_point, {layers}) { return fake.features.filter(f => layers.includes(f.layer.id)); }
    resize() {}
    remove() {}
  }
  const control = class {};
  fake.module = {lib: {Map: FakeMap, NavigationControl: control, ScaleControl: control, AttributionControl: control, setWorkerUrl() {}, addProtocol() {}},
    workerUrl: '/w.js', Protocol: class { constructor() { this.tile = () => {}; } }};
  return fake;
}
/** A fake terrain handle recording selectHabitat. */
function terrain() {
  const fake = {options: null, selected: []};
  const handle = {load: async () => true, destroy() {}, selectHabitat: id => fake.selected.push(id)};
  for (const name of ['setPerspective', 'setLocation', 'setSpecies', 'setHour', 'setDepthLimit', 'setCurrentLayer', 'setVisible']) handle[name] = () => true;
  fake.module = {styles: [], mountCoast(_host, options) { fake.options = options; return handle; }};
  return fake;
}
function chartStage({fail = []} = {}) {
  const lib = library(), land = terrain(), host = {dataset: {}};
  terrainFailed.value = false; chartFailed.value = false; chartMark.value = null; terrainMark.value = null; terrainDetail.value = null; unavailable.value = [];
  const stage = createStage({host: {dataset: {}, shadowRoot: {replaceChildren() {}}}, load: async () => land.module, center: () => [35.37, -120.86], viewDelay: 0,
    doc: {hidden: false, addEventListener() {}, removeEventListener() {}},
    renderers: [() => createChart({host, load: async () => lib.module, fetchFn: files(fail), palette: () => sentinel, page: () => PAGE, viewDelay: 0})]});
  return {lib, land, host, stage};
}

test('one selection: a mark click writes ?spot= and drops ?habitat=; a terrain pick does the reverse; outlines drop both', async t => {
  t.mock.method(console, 'warn', () => {});
  const nav = browser(`${PAGE}?region=morro-bay&presentation=chart&target=lingcod&habitat=reef:r1&view=35.16431,-120.84318,14`);
  const {lib, land, host, stage} = chartStage();
  await settle();
  const [map] = lib.maps;
  assert.equal(map.data[MARKS_SOURCE].features.length, Number(host.dataset.marks), 'the Chart draws the admitted marks');
  assert.ok(Number(host.dataset.marks) > 0);
  const before = picked.value;
  lib.features = [{layer: {id: MARK_PICK}, properties: {id: 'SC26-001'}}];
  map.fire('click', {point: {x: 0, y: 0}});
  assert.equal(nav.params().get('spot'), 'SC26-001');
  assert.equal(nav.params().get('habitat'), null, 'the terrain selection goes');
  assert.equal(picked.value, before + 1, 'a pick asks the card for focus');
  assert.equal(chartMark.value, null);
  assert.equal(spotCard.value.reading, 'Fits lingcod habitat 3 of 3');
  assert.deepEqual(map.data[SELECTION_SOURCE].features[0].geometry.coordinates, [-120.843179, 35.164314], 'the selected mark is outlined');
  const entries = nav.stack.length;
  map.fire('click', {point: {x: 0, y: 0}});
  assert.equal(nav.stack.length, entries, 'the same mark again adds no history entry');

  // A terrain pin in 3D: ?habitat= with a history entry, and the atlas spot goes.
  navigate(`${PAGE}?${new URLSearchParams({...Object.fromEntries(nav.params()), presentation: '3d'})}`);
  await settle();
  land.options.onSelection({latitude: 35.38, longitude: -120.88, id: 'reef:r2'});
  assert.equal(nav.params().get('habitat'), 'reef:r2');
  assert.equal(nav.params().get('spot'), null);
  land.options.onTargetDetail({id: 'reef:r2', kind: 'reef', title: 'Lingcod habitat · grade B', facts: 'Nominal 50–90 ft · physical score 61/100 · species fit 2/3', evidence: 'morro bay · 2 m source grid · 2012. Fish presence unverified.'});
  setParams({presentation: 'chart'});
  assert.equal(habitatCard.value.reading, 'Nominal 50–90 ft · physical score 61/100 · fits lingcod habitat 2 of 3', 'on the Chart the card carries the renderer\'s evidence');
  assert.deepEqual(map.data[SELECTION_SOURCE].features.map(f => f.geometry.coordinates), [[-120.88, 35.38]]);

  // A mark again: the stage tells the renderer to drop its selection.
  lib.features = [{layer: {id: MARK_PICK}, properties: {id: 'SC26-001'}}];
  map.fire('click', {point: {x: 0, y: 0}});
  await settle();
  assert.equal(land.selected.at(-1), null, 'selectHabitat(null)');
  assert.equal(nav.params().get('habitat'), null);

  // A coastline click is the Chart's own selection and drops the link's; Back brings the spot back.
  lib.features = [{layer: {id: COASTLINE_PICK}, properties: {SOURCE_ID: 'S1', ATTRIBUTE: 'Natural.Mean High Water', source_date: '2010-11-01'}}];
  map.fire('click', {point: {x: 0, y: 0}});
  assert.equal(chartMark.value.name, 'Shoreline');
  assert.equal(nav.params().get('spot'), null);
  nav.back();
  assert.equal(nav.params().get('spot'), 'SC26-001');
  assert.equal(chartMark.value, null, 'Back restores the link\'s selection and clears the Chart\'s');
  lib.features = [];
  map.fire('click', {point: {x: 0, y: 0}});
  assert.equal(nav.params().get('spot'), 'SC26-001', 'empty water leaves the link alone');
  stage.destroy();
});

test('data set before MapLibre has parsed the style reaches the source once it has', () => {
  const lib = library();
  const engine = createEngine(lib.module, {host: {}, style: {version: 8, sources: {[MARKS_SOURCE]: {type: 'geojson', data: EMPTY}}, layers: []},
    camera: {latitude: 35.16, longitude: -120.84, zoom: 14}, onMove() {}, onLayerError() {}});
  const [map] = lib.maps, marks = {type: 'FeatureCollection', features: [{type: 'Feature', geometry: {type: 'Point', coordinates: [0, 0]}, properties: {id: 'm'}}]};
  map.styleLoaded = false;
  engine.setData(MARKS_SOURCE, EMPTY);
  engine.setData(MARKS_SOURCE, marks);
  assert.equal(map.data[MARKS_SOURCE], undefined, 'nothing to set yet');
  map.styleLoaded = true;
  map.fire('style.load');
  assert.equal(map.data[MARKS_SOURCE], marks, 'the latest data, once');
  engine.destroy();
});

test('survey and geology outlines open their own cards from the loaded files', async t => {
  t.mock.method(console, 'warn', () => {});
  browser(`${PAGE}?region=cambria-san-simeon&presentation=chart&target=lingcod`);
  const {lib, stage} = chartStage();
  await settle();
  const [map] = lib.maps;
  assert.equal(map.data[SURVEY_SOURCE].features.length, SURVEY.features.length);
  assert.ok(map.data[GEOLOGY_SOURCE].features.length > 0);
  lib.features = [{layer: {id: SURVEY_PICK}, properties: {id: SURVEY.features[0].properties.id, kind: 'rock'}}];
  map.fire('click', {point: {x: 0, y: 0}});
  assert.equal(chartMark.value.source, 'USGS original seafloor-character class 3 · compiled 2022-06-07');
  lib.features = [{layer: {id: GEOLOGY_PICK}, properties: {id: GEOLOGY.features[0].properties.id}}];
  map.fire('click', {point: {x: 0, y: 0}});
  assert.equal(chartMark.value.name, 'Coast Range ophiolite');
  assert.equal(chartPick(SURVEY_PICK, {id: 'unknown'}), null, 'an id the files lack selects nothing');
  stage.destroy();
});

test('the link\'s spot loads in any presentation; a failed file marks only its layer; a new region starts over', async t => {
  t.mock.method(console, 'warn', () => {});
  browser(`${PAGE}?region=morro-bay&presentation=3d&spot=SC26-001`);
  const errors = [];
  const marks = createMarks({fetchFn: files(['data/atlas.json']), page: () => PAGE, onError: layer => errors.push(layer)});
  assert.equal(spotCard.value, undefined, 'loading: the card keeps its placeholder');
  await settle();
  assert.deepEqual(errors, ['marks']);
  assert.equal(spotCard.value, null, 'no atlas, no mark');
  marks.destroy();
  const again = createMarks({fetchFn: files(), page: () => PAGE});
  await settle();
  assert.equal(spotCard.value.name, 'Southern rocky rise', 'the 3D link names its mark');
  setParams({region: 'cambria-san-simeon'});
  assert.equal(markData.value, null, 'a new region drops the old layers at once');
  await settle();
  assert.equal(spotCard.value, null);
  assert.equal(markSources[GEOLOGY_SOURCE].value.features.length > 0, true);
  again.destroy();
});

test('the selection hrefs drop ?focus= too, and a link naming both a spot and a habitat keeps the spot', async () => {
  const both = `${PAGE}?region=morro-bay&focus=estero&spot=SC26-001&habitat=reef:r1&view=1,2,3`;
  const spot = new URL(spotHref(both, 'SC26-002')).searchParams, none = new URL(spotHref(both, null)).searchParams, terrain = new URL(habitatHref(both, 'reef:r2')).searchParams;
  assert.deepEqual([spot.get('spot'), spot.get('focus'), spot.get('habitat'), spot.get('view')], ['SC26-002', null, null, '1,2,3']);
  assert.deepEqual([none.get('spot'), none.get('focus'), none.get('habitat')], [null, null, null]);
  assert.deepEqual([terrain.get('habitat'), terrain.get('spot'), terrain.get('focus')], ['reef:r2', null, null]);

  const nav = browser(both);
  const marks = createMarks({fetchFn: files(), page: () => PAGE, resolver: async () => ({resolveHabitatSelection: async () => null})});
  assert.deepEqual([nav.params().get('spot'), nav.params().get('habitat'), nav.params().get('focus')], ['SC26-001', null, null], 'one selection: the spot');
  assert.equal(nav.stack.length, 1, 'normalised in place, without a history entry');
  marks.destroy();
  const kept = browser(`${PAGE}?region=morro-bay&focus=estero&habitat=reef:r1`);
  const again = createMarks({fetchFn: files(), page: () => PAGE, resolver: async () => ({resolveHabitatSelection: async () => null})});
  assert.equal(kept.params().get('habitat'), 'reef:r1', 'a focus area is no spot: the habitat stays');
  again.destroy();
  await settle();
});

test('on the Chart a ?habitat= the terrain has not restored resolves without graphics, until its receipt expires', async () => {
  browser(`${PAGE}?region=morro-bay&presentation=chart&profile=spear&habitat=reef:r1`);
  terrainMark.value = null;
  const asked = [];
  let expires = '2030-01-01T00:00:00.000Z';
  const resolver = async () => ({resolveHabitatSelection: async (request) => { asked.push(request); return {id: request.id, latitude: 35.38, longitude: -120.88, expiresAt: expires, kind: 'reef'}; }});
  const marks = createMarks({fetchFn: files(), page: () => PAGE, resolver, now: () => Date.parse('2029-12-31T23:59:59.900Z')});
  await settle();
  assert.deepEqual(asked, [{id: 'reef:r1', species: 'cabezon-shallow-reef', depthLimitFt: 60}], 'the profile\'s target and depth limit');
  assert.equal(habitatCard.value.source, 'Reviewed coastal habitat · valid until 2030-01-01');
  await new Promise(resolve => setTimeout(resolve, 150));
  assert.equal(habitatReceipt.value, null, 'the receipt clears when it expires');
  expires = '2000-01-01T00:00:00.000Z';
  setParams({habitat: 'reef:r3'});
  await settle();
  assert.equal(habitatCard.value, null, 'an expired receipt is never shown');
  setParams({presentation: '3d'});
  await settle();
  assert.equal(asked.length, 2, 'in the terrain the renderer restores its own selection');
  setParams({region: 'santa-cruz-monterey-bay', presentation: 'chart'});
  await settle();
  assert.equal(asked.length, 2, 'no terrain, no habitat to restore');
  marks.destroy();
});
