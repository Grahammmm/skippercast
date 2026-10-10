// Charter grounds and commercial AIS 2024 (FE-21, docs/plans/front-end/dev-plan.md): the
// public part of the Charter fleet entry, drawn from the committed files v1 draws
// (dist/data/charter-grounds.json, dist/data/commercial-ais-effort.geojson) and screened
// against the committed protected-area snapshot, all read from disk (offline). The
// basis sentences are v1's, pinned verbatim, and v1's commercial AIS copy is pinned unchanged.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {signal} from '@preact/signals';
import {
  AIS_LAYERS, BROAD, GROUNDS_FILL, GROUNDS_HATCH, GROUNDS_LABEL, GROUNDS_LINE, GROUNDS_SOURCE, HATCH_SOURCE, NOTES, createCharterGrounds,
  groundCollections, groundMark, groundsOverlay, groundsState, hatchLines, shownGrounds,
} from '../web/map/charter-grounds.ts';
import {AIS_CREDIT, AIS_HEAT, AIS_LINE, AIS_SOURCE, aisMark, aisOn, aisOverlay, aisState, aisSummary, cellCollection, createCommercialAis, shownCells} from '../web/map/commercial-ais.ts';
import {assessScreen, CHECKING} from '../web/map/habitat.ts';
import {layerEntry, railNotes, terrainLayers} from '../web/map/layers.ts';
import {MARK_PICK, markData, markScreen} from '../web/map/marks.ts';
import {readPalette} from '../web/map/palette.ts';
import {configureStore, syncFromURL} from '../web/state.ts';

const ROOT = new URL('..', import.meta.url);
const read = path => readFileSync(new URL(path, ROOT), 'utf8');
const json = path => JSON.parse(read(path));
const REGION = json('dist/regions/morro-bay/region.json');
const asset = key => `dist/${REGION.assets[key]}`;
const GROUNDS = json(asset('charters')), CELLS = json(asset('commercial_ais')), SNAPSHOT = json(asset('protected_areas'));
const NOW = Date.parse('2026-10-09T18:00:00Z');
/** The committed ds582 snapshot as a check made this hour. */
const READY = assessScreen({areas: SNAPSHOT.features, checkedAt: new Date(NOW - 3_600_000).toISOString(), live: false, closures: undefined}, NOW);
const sentinel = readPalette(name => `token(${name})`);
const sha = path => createHash('sha256').update(readFileSync(new URL(path, ROOT))).digest('hex');
const flush = () => new Promise(resolve => setImmediate(resolve));

test('the committed screen is ready and admits the named grounds and cells; a stale or missing check draws nothing', () => {
  assert.equal(READY.status, 'ready');
  assert.deepEqual(shownGrounds(GROUNDS, 'lingcod', 'boat', READY).map(g => g.id), ['CHARTER-PECHO', 'CHARTER-DIABLO'], 'the broad Morro Bay name has no outline');
  assert.ok(GROUNDS.grounds.some(g => g.precision === BROAD));
  assert.deepEqual(shownGrounds(GROUNDS, 'reef', 'boat', READY).length, 2);
  assert.deepEqual(shownGrounds(GROUNDS, 'halibut', 'boat', READY), [], 'lingcod and rockfish only');
  assert.deepEqual(shownGrounds(GROUNDS, 'lingcod', 'spear', READY), [], 'the spear profile\'s 60 ft limit excludes both outlines (127 and 194 ft)');
  assert.deepEqual(shownGrounds(GROUNDS, 'lingcod', 'boat', CHECKING), []);
  const stale = assessScreen({areas: SNAPSHOT.features, checkedAt: new Date(NOW - 37 * 3_600_000).toISOString(), live: false, closures: undefined}, NOW);
  assert.equal(stale.status, 'stale');
  assert.deepEqual(shownGrounds(GROUNDS, 'lingcod', 'boat', stale), []);
  assert.deepEqual(shownCells(CELLS, READY).map(f => f.properties.id), ['AIS-COMM-001', 'AIS-COMM-002', 'AIS-COMM-003']);
  assert.deepEqual(shownCells(CELLS, stale), []);
  // A ground whose outline crosses a protected area is withheld (v1's geometryAllowed), as is one anchored inside one.
  const pecho = GROUNDS.grounds.find(g => g.id === 'CHARTER-PECHO');
  const box = ([x, y], r = 0.0005) => ({type: 'Polygon', coordinates: [[[x - r, y - r], [x + r, y - r], [x + r, y + r], [x - r, y + r], [x - r, y - r]]]});
  const area = geometry => ({...READY, boundaries: [...READY.boundaries, {name: 'Test area', federal: false, geometry}]});
  assert.deepEqual(shownGrounds(GROUNDS, 'lingcod', 'boat', area(box([pecho.longitude, pecho.latitude]))).map(g => g.id), ['CHARTER-DIABLO'], 'anchor inside');
  const diablo = GROUNDS.grounds.find(g => g.id === 'CHARTER-DIABLO');
  const far = pecho.geometry.coordinates[0].reduce((a, b) => Math.hypot(b[0] - diablo.longitude, b[1] - diablo.latitude) > Math.hypot(a[0] - diablo.longitude, a[1] - diablo.latitude) ? b : a);
  assert.deepEqual(shownGrounds(GROUNDS, 'lingcod', 'boat', area(box(far))).map(g => g.id), ['CHARTER-DIABLO'], 'outline crosses an area, anchor outside');
  const cell = CELLS.features[2];
  assert.deepEqual(shownCells(CELLS, {...READY, boundaries: [{name: 'Test area', federal: false, geometry: cell.geometry}]}).map(f => f.properties.id), ['AIS-COMM-001', 'AIS-COMM-002']);
});

test('hatching is diagonal lines clipped to the outline, holes left open', () => {
  const square = {type: 'Polygon', coordinates: [[[0, 0], [0.01, 0], [0.01, 0.01], [0, 0.01], [0, 0]]]};
  const lines = hatchLines(square, 0.002);
  assert.equal(lines.length, 9, 'c = 0.002 … 0.018; the corners at 0 and 0.02 draw nothing');
  for (const [[x1, y1], [x2, y2]] of lines) {
    assert.ok(Math.abs(x1 + y1 - (x2 + y2)) < 1e-12, 'each segment lies on one diagonal');
    for (const v of [x1, y1, x2, y2]) assert.ok(v >= -1e-12 && v <= 0.01 + 1e-12, 'inside the square');
  }
  const holed = {type: 'Polygon', coordinates: [...square.coordinates, [[0.004, 0.004], [0.006, 0.004], [0.006, 0.006], [0.004, 0.006], [0.004, 0.004]]]};
  const middle = hatchLines(holed, 0.002).filter(([[x, y]]) => Math.abs(x + y - 0.01) < 1e-9);
  assert.equal(middle.length, 2, 'the diagonal through the hole is cut in two');
  assert.deepEqual(hatchLines({type: 'Point', coordinates: [0, 0]}), []);
  // The committed outlines hatch.
  const {outlines, hatch} = groundCollections(shownGrounds(GROUNDS, 'lingcod', 'boat', READY));
  assert.deepEqual(outlines.features.map(f => [f.properties.id, f.geometry.type]), [['CHARTER-PECHO', 'Polygon'], ['CHARTER-DIABLO', 'Polygon']]);
  for (const f of hatch.features) assert.ok(f.geometry.coordinates.length > 5, `${f.properties.id} has hatch lines`);
});

test('Accept 1: both layers render from the committed files, offline, in the --fleet colour and § 9 order', async t => {
  globalThis.location = {href: 'https://s.test/map?region=morro-bay&layers=fleet'};
  configureStore({v2: true, storage: null});
  syncFromURL(location.href);
  const asked = [];
  const fetchFn = async url => { const path = new URL(url).pathname.slice(1); asked.push(path); return {ok: true, json: async () => json(`dist/${path}`)}; };
  const calls = [];
  const engine = signal({setOverlay: (layer, o, before) => calls.push(['overlay', layer, o && o.layers.map(l => l.id), before ?? null]),
    setData: (id, data) => calls.push(['data', id, data.features.length])});
  markScreen.value = READY;
  markData.value = {region: {...REGION, id: 'morro-bay'}, atlas: null, survey: null, geology: null};
  const grounds = createCharterGrounds({engine, fetchFn, page: () => location.href, palette: () => sentinel});
  const ais = createCommercialAis({engine, fetchFn, page: () => location.href, palette: () => sentinel});
  t.after(() => { grounds.destroy(); ais.destroy(); markData.value = null; markScreen.value = CHECKING; aisOn.value = false; });
  await flush(); await flush();
  assert.deepEqual(asked, ['data/charter-grounds.json'], 'commercial AIS waits for its option');
  assert.deepEqual(calls.filter(c => c[1] === 'charter-grounds' || c[1] === GROUNDS_SOURCE || c[1] === HATCH_SOURCE).slice(-3), [
    ['overlay', 'charter-grounds', [GROUNDS_FILL, GROUNDS_HATCH, GROUNDS_LINE, GROUNDS_LABEL], [...AIS_LAYERS, MARK_PICK]],
    ['data', GROUNDS_SOURCE, 2], ['data', HATCH_SOURCE, 2]]);
  assert.deepEqual(groundsState.value, {drawn: 2, note: '', audit: GROUNDS.audit_date});
  assert.equal(railNotes.value.fleet, '2 charter grounds');
  assert.equal(aisState.value.offered, true);
  assert.equal(aisState.value.drawn, 0);
  aisOn.value = true;
  await flush(); await flush();
  assert.deepEqual(asked, ['data/charter-grounds.json', 'data/commercial-ais-effort.geojson']);
  assert.deepEqual(calls.slice(-2), [['overlay', 'commercial-ais', [AIS_HEAT, AIS_LINE], [MARK_PICK]], ['data', AIS_SOURCE, 3]]);
  assert.deepEqual(aisState.value, {offered: true, drawn: 3, note: aisSummary(3)});
  assert.equal(aisSummary(3), '3 historical grid cells · Jul & Sep 2024 · depth unknown');
  // The cards.
  const card = grounds.pick.mark(GROUNDS_FILL, {id: 'CHARTER-PECHO'});
  assert.equal(card.name, 'Pecho Rock');
  assert.match(card.reading, /^11 reported trips · \d+ boats? · latest report Sep 17, 2026\. Outline survey depths 25–127 ft \(nominal, 2008 survey\)$/);
  assert.match(card.basis, /Reported area, exact stops unknown\. Captains named “Pecho Rock”; they did not publish GPS positions or fishing depths\./);
  for (const boat of GROUNDS.grounds[0].boats) assert.ok(!JSON.stringify(card).includes(boat), 'no boat names on the card');
  assert.equal(grounds.pick.mark(GROUNDS_FILL, {id: 'CHARTER-MORRO'}), null, 'the broad name is not drawn');
  // FE-82: the same grounds drape on the terrain, and a terrain pick opens the same card.
  const drape = terrainLayers.value['charter-grounds'];
  assert.deepEqual(drape.features.map(f => [f.id, f.geometry.type]), groundCollections(shownGrounds(GROUNDS, 'lingcod', 'boat', READY)).outlines.features.map(f => [f.properties.id, f.geometry.type]));
  assert.equal(drape.features.length, 2);
  assert.deepEqual(drape.pick('CHARTER-PECHO'), card, 'the card the Chart\'s click gives');
  assert.equal(drape.pick('CHARTER-MORRO'), null);
  const cell = ais.pick.mark(AIS_HEAT, {id: 'AIS-COMM-003'});
  assert.equal(cell.name, 'Offshore Morro Bay · Trawler activity');
  assert.match(cell.reading, /Apparent fishing activity, not a verified catch spot\.$/);
  assert.match(cell.basis, /Depth and target species unknown\. This offshore context is not qualified for the 200-foot fishing limit\./);
  // Off: both overlays leave.
  syncFromURL('https://s.test/map?region=morro-bay&layers=seafloor');
  await flush();
  assert.deepEqual(calls.slice(-2).map(c => [c[0], c[1], c[2]]).sort(), [['overlay', 'charter-grounds', null], ['overlay', 'commercial-ais', null]]);
  assert.equal(groundsState.value.drawn, 0);
  assert.equal(terrainLayers.value['charter-grounds'], undefined, 'and leave the terrain');
});

test('the grounds\' row says why nothing draws', async t => {
  globalThis.location = {href: 'https://s.test/map?region=santa-cruz-monterey-bay&layers=fleet'};
  syncFromURL(location.href);
  const engine = signal({setOverlay() {}, setData() {}});
  markScreen.value = READY;
  markData.value = {region: {id: 'santa-cruz-monterey-bay', assets: {charters: null, commercial_ais: null}}, atlas: null, survey: null, geology: null};
  const grounds = createCharterGrounds({engine, fetchFn: async () => { throw new Error('no request expected'); }, palette: () => sentinel});
  const ais = createCommercialAis({engine, fetchFn: async () => { throw new Error('no request expected'); }, palette: () => sentinel});
  t.after(() => { grounds.destroy(); ais.destroy(); markData.value = null; markScreen.value = CHECKING; });
  await flush();
  assert.equal(groundsState.value.note, NOTES.none);
  assert.equal(aisState.value.offered, false, 'no option where the region has no reviewed AIS layer');
});

test('overlay styles read tokens only', () => {
  const g = groundsOverlay(sentinel, groundCollections([]));
  const a = aisOverlay(sentinel, cellCollection(CELLS.features));
  const colours = [...g.layers, ...a.layers].flatMap(l => Object.entries(l.paint ?? {}).filter(([k]) => /color$/.test(k)).map(([, v]) => v));
  assert.ok(colours.length > 0);
  for (const c of colours) assert.match(c, /^token\((amber|bg)\)$/);
  assert.deepEqual(a.layers[0].paint['fill-opacity'], ['interpolate', ['linear'], ['get', 'hours'], 0, 0.15, Math.max(...CELLS.features.map(f => f.properties.apparent_fishing_hours)), 0.45]);
  assert.match(a.sources[AIS_SOURCE].attribution, /Global Fishing Watch · CC BY-NC 4\.0/);
});

test('Accept 2: the basis sentences are v1\'s, verbatim, and v1\'s commercial AIS copy is unchanged', () => {
  const html = read('dist/commercial-ais.html'), aisJs = read('dist/commercial-ais.js'), chartersJs = read('dist/charter-grounds.js');
  const sentences = s => s.match(/[^.]+?(?:\.(?=\s|$))/g).map(x => x.trim());
  for (const s of sentences(layerEntry('commercial-ais').basis)) assert.ok(html.includes(s), `commercial-ais.html says: ${s}`);
  assert.ok(html.includes(AIS_CREDIT), 'the credit is the page\'s');
  for (const s of sentences(layerEntry('charter-grounds').basis)) assert.ok(chartersJs.includes(s), `charter-grounds.js says: ${s}`);
  // The card's fixed lines are v1's card lines.
  const card = aisMark(CELLS.features[0].properties);
  for (const s of ['Apparent fishing activity, not a verified catch spot.', 'Depth and target species unknown. This offshore context is not qualified for the 200-foot fishing limit.',
    'Local sportfishing-charter identity remains unverified.']) {
    assert.ok(aisJs.includes(s)); assert.ok(`${card.reading} ${card.basis}`.includes(s));
  }
  // v1's commercial AIS page and module are byte for byte as before FE-21.
  assert.deepEqual({html: sha('dist/commercial-ais.html'), js: sha('dist/commercial-ais.js')}, PINNED);
  assert.ok(groundMark(GROUNDS.grounds[0], GROUNDS).basis.startsWith(layerEntry('charter-grounds').basis));
});

/** sha256 of dist/commercial-ais.html and dist/commercial-ais.js on main before FE-21. */
const PINNED = {html: '096874dd13a971e64ea321fd30e652048416c1aaf7335e00e72569f71a341f8e', js: 'f4c19515b6ff40304ed67f4df481e3836ae9e598e634cbe585e760d517dc7d0a'};
