// SCJ-1: the brief's recommended places are reviewed terrain habitat (`habitat:` cards), which the atlas
// does not know. Their card's Add to trip and GPX save the place as a user waypoint (web/planner.ts
// `addPlace`, web/trip.ts `addPlaceToTrip` / `reviewPlace`) and its Regulations links the region's
// official page; a habitat card with no position says why in one sentence of its own.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import {createPlanner} from '../web/planner.ts';
import {draftKey} from '../dist/trip-export.js';

const ROOT = new URL('..', import.meta.url).pathname, PAGE = 'https://s.test/map';
const read = path => JSON.parse(readFileSync(new URL(`../dist/${path}`, import.meta.url), 'utf8'));
const MORRO = read('regions/morro-bay/region.json'), SOCAL = read('regions/southern-california/region.json');
const REGION = {id: 'test-coast', name: 'Test Coast', timezone: 'America/Los_Angeles', mpa: {bounds: [-10, -10, 10, 10]}};
const SCREEN = {ready: () => true, pointAllowed: () => true, geometryAllowed: () => true, exportExclusions: () => ({features: [], checked_at: new Date().toISOString()})};
const MAP = {getSize: () => ({x: 512, y: 512}), getBounds: () => ({getWest: () => -1, getEast: () => 1, getNorth: () => 1, getSouth: () => -1, contains: () => true})};
const PLACE = {id: 'habitat:reef:r1', name: 'Lingcod habitat · grade A', latitude: 0.25, longitude: 0.5};
const WHY = '<p class="app-mark-why">This place has no saved position yet, so it cannot be added to a trip or exported.</p>';
const DISABLED = label => new RegExp(`<button disabled type="button" class="ui-button ui-button--ghost ui-button--sm">(?:(?!</button>).)*${label}</button>`, 's');
const ENABLED = label => new RegExp(`<button type="button" class="ui-button ui-button--ghost ui-button--sm">(?:(?!</button>).)*${label}</button>`, 's');
const regsLink = href => new RegExp(`<a class="ui-button ui-button--ghost ui-button--sm" href="${href}" target="_blank" rel="noopener" aria-label="Regulations: [^"]+">`);

function planner(stored = null) {
  const store = new Map(stored ? [[draftKey(REGION.id), stored]] : []), nav = [];
  const p = createPlanner({atlas: {targets: [], areas: [], drifts: []}, screen: SCREEN, region: REGION, map: MAP, getVisible: () => [], now: () => new Date('2026-10-12T18:00:00Z'),
    storage: {getItem: k => store.get(k) ?? null, setItem: (k, v) => { store.set(k, v); }}, loadPorts: async () => ({ports: []}), emit: () => {}, landWater: async () => () => ({state: 'water'}),
    nav: {open: () => nav.push('open'), showMap() {}, conditions() {}}});
  return {p, store, nav};
}

test('a habitat place joins the trip once as a user waypoint; again adds nothing and returns the same id', () => {
  const {p, store} = planner();
  const id = p.addPlace(PLACE);
  assert.equal(id, 'user:habitat-reef-r1');
  assert.equal(p.addPlace(PLACE), id, 'the same place, the same id');
  assert.deepEqual(p.draft.value.ids, [id]);
  assert.deepEqual(p.draft.value.userWaypoints, [{id, name: PLACE.name, category: 'reef', latitude: 0.25, longitude: 0.5}]);
  assert.equal(JSON.parse(store.get(draftKey(REGION.id))).ids.length, 1, 'persisted once');
  assert.equal(p.addPlace({...PLACE, id: 'habitat:shore:s1', name: 'Shore habitat', shore: true}), 'user:habitat-shore-s1');
  assert.equal(p.draft.value.userWaypoints[1].category, 'other', 'a shore place is labelled other');
  p.dispose();
});

test('at the 100-waypoint cap, or with an invalid position, nothing is saved and the validation sentence shows', () => {
  const full = Array.from({length: 100}, (_, i) => ({id: `user:w${i}`, name: `W ${i}`, category: 'reef', latitude: 0, longitude: 0}));
  const raw = JSON.stringify({ids: full.map(w => w.id), userWaypoints: full, rankedPlan: null, name: 'Day', date: '2026-10-12', avoidScope: 'region',
    layers: {waypoints: true, outlines: false, alignments: false, exclusions: false}});
  const {p, store} = planner(raw);
  assert.equal(p.addPlace(PLACE), null);
  assert.match(p.actionStatus.value, /^Choose a name \(up to 80 characters\), a listed category and a valid map position\. Limit: 100 waypoints\.$/);
  assert.equal(store.get(draftKey(REGION.id)), raw, 'nothing persisted');
  assert.equal(p.draft.value.userWaypoints.length, 100);
  p.dispose();
  const empty = planner();
  assert.equal(empty.p.addPlace({...PLACE, latitude: 95}), null, 'an off-earth position is refused');
  assert.equal(empty.p.addPlace({...PLACE, name: ' '}), null, 'a blank name is refused');
  assert.deepEqual(empty.p.draft.value.ids, []);
  assert.equal(empty.store.size, 0);
  empty.p.dispose();
});

test('a GPX from a trip holding a habitat place has one user waypoint for it; review opens the trip', async () => {
  const {p, nav} = planner();
  const id = p.addPlace(PLACE);
  p.review(id);
  assert.deepEqual(nav, ['open']);
  const gpx = await (await p.exportFile('gpx')).text(), wpts = gpx.match(/<wpt [^>]*>.*?<\/wpt>/gs) ?? [];
  assert.equal(wpts.length, 1);
  assert.match(wpts[0], /^<wpt lat="0\.25" lon="0\.5"><name>Lingcod habitat · grade A<\/name><cmt>user:habitat-reef-r1<\/cmt><desc>User waypoint\. User-supplied label; not verified habitat/);
  p.dispose();
});

let ui;
async function components() {
  if (ui) return ui;
  const out = join(await mkdtemp(join(tmpdir(), 'place-')), 'place.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {MarkCard} from './web/app/MarkCard.tsx';
      export {habitatCard, markData} from './web/map/marks.ts';
      export {receiptCard, CDFW_REGULATIONS} from './web/map/habitat.ts';
      export {terrainDetail, terrainMark} from './web/map/stage.ts';
      export {placeTripId, tripIds} from './web/trip.ts';
      export * as state from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins,
  });
  ui = await import(pathToFileURL(out).href);
  return ui;
}

test('receipt and evidence habitat cards offer Add to trip, GPX and the region\'s Regulations page; a saved place reads Added', async () => {
  const {MarkCard, habitatCard, markData, receiptCard, CDFW_REGULATIONS, terrainDetail, terrainMark, placeTripId, tripIds, state, render, h} = await components();
  state.configureStore({v2: true, storage: null});
  state.syncFromURL(`${PAGE}?region=morro-bay&presentation=chart&target=lingcod&habitat=reef:r2`);
  terrainMark.value = {latitude: 35.38, longitude: -120.88, id: 'reef:r2'};
  terrainDetail.value = {id: 'reef:r2', kind: 'reef', title: 'Lingcod habitat · grade B', facts: 'Nominal 50–90 ft', evidence: 'morro bay · 2 m source grid. Fish presence unverified.'};
  try {
    const detail = habitatCard.value;
    assert.equal(detail.name, 'Lingcod habitat · grade B', 'the evidence card');
    assert.deepEqual(detail.position, {latitude: 35.38, longitude: -120.88}, 'keeps the selection\'s position');
    const receipt = receiptCard({id: 'reef:r1', latitude: 35.3, longitude: -120.9, expiresAt: '2030-01-01T00:00:00.000Z', kind: 'reef'});
    for (const [region, href] of [[MORRO, CDFW_REGULATIONS], [SOCAL, SOCAL.regulations_url]]) {
      markData.value = {region, atlas: null, survey: null, geology: null};
      for (const mark of [detail, receipt]) {
        const html = render(h(MarkCard, {mark}));
        assert.match(html, ENABLED('Add to trip'), `${mark.id}: Add to trip works`);
        assert.match(html, ENABLED('GPX'), `${mark.id}: GPX works`);
        assert.match(html, regsLink(href), `${mark.id}: Regulations links ${region.id}'s page`);
        assert.doesNotMatch(html, /app-mark-why/);
      }
    }
    tripIds.value = [placeTripId(receipt.id)];
    const saver = planner();
    assert.equal(saver.p.addPlace({...PLACE, id: receipt.id}), tripIds.value[0], 'the card reads the id the planner saves');
    saver.p.dispose();
    assert.match(render(h(MarkCard, {mark: receipt})), ENABLED('Added to trip'));
    assert.match(render(h(MarkCard, {mark: detail})), ENABLED('Add to trip'), 'another place is not shown as added');
  } finally {
    tripIds.value = []; terrainMark.value = null; terrainDetail.value = null; markData.value = null;
  }
});

test('a habitat card with no position keeps both buttons disabled and says why in its own line; other marks keep today\'s buttons', async () => {
  const {MarkCard, markData, state, render, h} = await components();
  state.configureStore({v2: true, storage: null});
  state.syncFromURL(`${PAGE}?region=morro-bay&presentation=chart`);
  markData.value = {region: MORRO, atlas: null, survey: null, geology: null};
  try {
    const base = {id: 'habitat:reef:r9', name: 'Selected habitat', kind: 'Terrain habitat', reading: '', source: 's', basis: 'b'};
    for (const mark of [base, {...base, position: {latitude: NaN, longitude: -120}}]) {
      const html = render(h(MarkCard, {mark}));
      assert.match(html, DISABLED('Add to trip'));
      assert.match(html, DISABLED('GPX'));
      assert.equal(html.split(WHY).length, 2, 'one why sentence, in its own <p>');
      assert.doesNotMatch(html, /<button disabled[^>]*(?:title|aria-describedby)=/, 'never an attribute on the disabled button');
    }
    const other = render(h(MarkCard, {mark: {id: 'reading:1,2', name: 'x', kind: 'k', reading: '', source: 's', basis: 'b', position: {latitude: 1, longitude: 2}}}));
    assert.match(other, DISABLED('Add to trip'), 'a terrain reading is not a place to save');
    assert.match(other, DISABLED('Regulations'), 'and names no rules page');
    assert.doesNotMatch(other, /app-mark-why/);
  } finally { markData.value = null; }
});
