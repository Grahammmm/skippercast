// Land or water for ranked places (CI6-01B; docs/land-water-method.md, web/land-water.ts).
// Synthetic products built from injected geometry by tests/unit/test_land_water.py
// (tests/fixtures/land-water/, rebuilt and compared there), offline and independent of the
// committed region: a mainland crossing the fixture region edge to edge with land to the east,
// a closed island ring and an enclosed water ring. Then the ranked list, the planner's
// bestSpots and the committed Morro Bay product (acceptance item 5).
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {bestSpots} from '../dist/spot-ranking.js';
import {assessScreen} from '../web/map/habitat.ts';
import {
  NO_LAND_WATER, decodeCells, ensureLandWater, keepWater, landWater, landWaterLines, landWaterModel, linesPlace, loadLandWater, loadLandWaterLines,
  placeFor, placeOf, resetLandWater, withheldNote,
} from '../web/land-water.ts';
import {ranking} from '../web/ranking.ts';

const fixture = name => JSON.parse(readFileSync(new URL(`./fixtures/land-water/${name}`, import.meta.url), 'utf8'));
const dist = path => JSON.parse(readFileSync(new URL(`../dist/${path}`, import.meta.url), 'utf8'));
const distText = path => readFileSync(new URL(`../dist/${path}`, import.meta.url), 'utf8');

// tests/unit/test_land_water.py `at`: metres east and north of the fixture region's south-west corner.
const WEST = -120.99, SOUTH = 35.40, MID = 35.42;
const at = (x, y) => ({longitude: WEST + x / (111320 * Math.cos(MID * Math.PI / 180)), latitude: SOUTH + y / 110540});
const model = landWaterModel(fixture('coast.json'), 'fixture');
const lines = landWaterLines(fixture('coast.lines.json'), model);
const place = p => placeOf(model, lines, p);

test('the fixture coast: mainland and island are land, open water and the enclosed ring are water', () => {
  assert.ok(model && lines, 'the fixture product loads');
  assert.deepEqual(place(at(3300, 3500)), {state: 'land'}, 'mainland interior');
  assert.deepEqual(place(at(750, 1950)), {state: 'land'}, 'island interior');
  assert.deepEqual(place(at(400, 600)), {state: 'water'}, 'offshore');
  // The note (step 7): a ring lying in land bounds water.
  assert.deepEqual(place(at(2950, 1950)), {state: 'water'}, 'inside the enclosed water ring');
});

test('the edge band: within 25 m of a line is unknown; just beyond it on the water side is water', () => {
  // The mainland runs straight north-south at x = 2000 m from y = 0 to 1200 m.
  assert.deepEqual(place(at(1980, 600)), {state: 'unknown', reason: 'edge'}, '20 m off, water side');
  assert.deepEqual(place(at(2020, 600)), {state: 'unknown', reason: 'edge'}, '20 m off, land side');
  assert.deepEqual(place(at(1973, 600)), {state: 'water'}, '27 m off, water side');
  assert.deepEqual(place(at(2027, 600)), {state: 'land'}, '27 m off, land side');
  assert.deepEqual(place(at(750, 1790)), {state: 'unknown', reason: 'edge'}, '10 m outside the island');
  // Near the line the index cell is mixed: the lines file decides, and until it loads the place waits.
  assert.deepEqual(placeOf(model, null, at(1973, 600)), {state: 'unknown', reason: 'pending'});
  assert.deepEqual(placeOf(model, false, at(1973, 600)), {state: 'unknown', reason: 'unavailable'}, 'a failed lines file is not water');
});

test('coverage: outside the bounds, unserved tiles and non-finite positions are unknown', () => {
  assert.deepEqual(place(at(-100, 600)), {state: 'unknown', reason: 'outside-bounds'});
  assert.deepEqual(place({latitude: NaN, longitude: -120.97}), {state: 'unknown', reason: 'outside-bounds'});
  assert.deepEqual(place({latitude: '35.41', longitude: -120.97}), {state: 'unknown', reason: 'outside-bounds'});
  const index = fixture('coast.json'), [tile] = Object.keys(index.tiles);
  const unserved = landWaterModel({...index, tiles: {}}, 'fixture');
  assert.deepEqual(placeOf(unserved, lines, at(400, 600)), {state: 'unknown', reason: 'unserved-tile'}, `${tile} not served`);
});

test('a gap wider than the join limit, a missing file and malformed geometry: every place unknown, never land or water', async () => {
  const points = [at(3300, 3500), at(750, 1950), at(400, 600), at(2950, 1950), at(2000, 1000)];
  for (const name of ['gap', 'empty-line', 'non-numeric', 'unclosed-island', 'bowtie']) {
    const index = fixture(`${name}.json`);
    assert.equal(index.status, 'unavailable', name);
    assert.ok(index.causes.length, `${name} names its cause`);
    assert.equal(landWaterModel(index, 'fixture'), null, name);
    for (const p of points) assert.deepEqual(placeOf(landWaterModel(index, 'fixture'), null, p), {state: 'unknown', reason: 'unavailable'}, name);
  }
  // The review's 50 m mid-tile gap is never bridged.
  assert.match(fixture('gap.json').causes[0], /gap not a tile seam/);
  // A three-position "ring" (a-b-a) is collinear: an edge line, never an island.
  const short = landWaterModel(fixture('short-ring.json'), 'fixture'), shortLines = landWaterLines(fixture('short-ring.lines.json'), short);
  assert.deepEqual(placeOf(short, shortLines, at(700, 1810)), {state: 'unknown', reason: 'edge'});
  assert.notEqual(placeOf(short, shortLines, at(700, 1900)).state, 'land');
  // A missing shoreline product: the region is unavailable, every place unknown, and nothing is ranked.
  resetLandWater();
  const state = await loadLandWater('fixture', async () => new Response('', {status: 404}));
  assert.equal(state.state, 'unavailable');
  assert.deepEqual(placeFor(state, 'fixture')(at(400, 600)), {state: 'unknown', reason: 'unavailable'});
  resetLandWater();
});

test('a malformed index or lines file is rejected', () => {
  const index = fixture('coast.json');
  assert.equal(landWaterModel(index, 'morro-bay'), null, 'another region');
  assert.equal(landWaterModel({...index, tiles: {[Object.keys(index.tiles)[0]]: 'w10'}}, 'fixture'), null, 'short grid');
  assert.equal(landWaterModel({...index, tiles: {[Object.keys(index.tiles)[0]]: `x${32 * 32}`}}, 'fixture'), null, 'unknown cell');
  assert.equal(landWaterModel({...index, bounds: [1, 2, 3]}, 'fixture'), null);
  assert.equal(landWaterModel({...index, constants: {...index.constants, unit: 1000}}, 'fixture'), null);
  assert.equal(decodeCells('w2l2', 4), 'wwll');
  assert.equal(decodeCells('w2l3', 4), null);
  const data = fixture('coast.lines.json');
  assert.equal(landWaterLines({...data, derived_from: {sha256: 'other'}}, model), null, 'lines from another shoreline');
  assert.equal(landWaterLines({...data, parity: [[1, 2, 3]]}, model), null);
  assert.equal(landWaterLines({...data, edge: [[1, 2, 'x', 4]]}, model), null);
});

test('loading: the index once, the lines file only when a place needs it, checked against the index hash', async () => {
  resetLandWater();
  const calls = [], files = {'land-water.json': JSON.stringify(fixture('coast.json')), 'land-water-lines.json': readFileSync(new URL('./fixtures/land-water/coast.lines.json', import.meta.url), 'utf8')};
  const fetchFn = async url => { calls.push(url.split('/').pop()); return new Response(files[url.split('/').pop()]); };
  const far = await ensureLandWater('fixture', [at(400, 600), at(3300, 3500)], fetchFn);
  assert.deepEqual(calls, ['land-water.json'], 'clean cells need no lines file');
  assert.deepEqual(far(at(400, 600)), {state: 'water'});
  const near = await ensureLandWater('fixture', [at(1973, 600)], fetchFn);
  assert.deepEqual(calls, ['land-water.json', 'land-water-lines.json']);
  assert.deepEqual(near(at(1973, 600)), {state: 'water'});
  resetLandWater();
  files['land-water-lines.json'] = files['land-water-lines.json'].replace('"parity"', '"parity" ');
  const tampered = await ensureLandWater('fixture', [at(1973, 600)], fetchFn);
  assert.equal(landWater.value.lines, false, 'bytes that differ from the index hash are refused');
  assert.deepEqual(tampered(at(1973, 600)), {state: 'unknown', reason: 'unavailable'});
  resetLandWater();
  assert.deepEqual(placeFor(landWater.value, 'fixture')(at(400, 600)), {state: 'unknown', reason: 'pending'}, 'before the index loads');
  assert.deepEqual(placeFor(landWater.value, null)(at(400, 600)), {state: 'unknown', reason: 'unavailable'});
});

// Sol review round 1, must-fix 2: a second caller awaits the request in flight, never a loading snapshot.
const FILES = {'land-water.json': JSON.stringify(fixture('coast.json')), 'land-water-lines.json': readFileSync(new URL('./fixtures/land-water/coast.lines.json', import.meta.url), 'utf8')};
const NEAR = at(1973, 600), FAR = at(400, 600);
/** A fetch whose answers wait until released; `calls` lists the files asked for. */
function deferredFetch(answer = name => new Response(FILES[name])) {
  const calls = [], held = [];
  const fetchFn = url => {
    const name = url.split('/').pop();
    calls.push(name);
    return new Promise((resolve, reject) => held.push(() => { try { resolve(answer(name)); } catch (e) { reject(e); } }));
  };
  return {fetchFn, calls, release: () => { while (held.length) held.shift()(); }};
}
const NO_FETCH = () => { throw new Error('a second request for the same file'); };
const tick = () => new Promise(r => setImmediate(r));
/** Resolves `promise` into `box.value`, so a test can see whether it has settled yet. */
const watch = promise => { const box = {done: false, promise}; promise.then(v => { box.done = true; box.value = v; }); return box; };

test('concurrent index loads share one request and every caller gets the settled index', async () => {
  resetLandWater();
  const d = deferredFetch();
  const first = loadLandWater('fixture', d.fetchFn);
  const second = watch(ensureLandWater('fixture', [FAR], NO_FETCH));
  const third = watch(loadLandWater('fixture', NO_FETCH));
  await tick();
  assert.equal(second.done || third.done, false, 'no caller resolves while the index is in flight');
  assert.equal(landWater.value.state, 'loading');
  d.release();
  assert.equal((await first).state, 'ready');
  await Promise.all([second.promise, third.promise]);
  assert.deepEqual(second.value(FAR), {state: 'water'}, 'the second caller\'s classifier is bound to the loaded index');
  assert.equal(third.value.state, 'ready');
  assert.deepEqual(d.calls, ['land-water.json']);
  resetLandWater();
});

test('a failed index request settles every waiting caller as unavailable', async () => {
  for (const answer of [() => new Response('', {status: 404}), () => { throw new Error('offline'); }]) {
    resetLandWater();
    const d = deferredFetch(answer);
    const first = ensureLandWater('fixture', [FAR], d.fetchFn), second = ensureLandWater('fixture', [NEAR], NO_FETCH);
    await tick();
    d.release();
    for (const place of await Promise.all([first, second])) assert.deepEqual(place(FAR), {state: 'unknown', reason: 'unavailable'});
    assert.equal(landWater.value.state, 'unavailable');
    assert.deepEqual(d.calls, ['land-water.json']);
  }
  // A fetch that throws before it returns a promise still settles through the shared request.
  resetLandWater();
  const state = await loadLandWater('fixture', () => { throw new Error('at once'); });
  assert.equal(state.state, 'unavailable');
  resetLandWater();
});

test('concurrent lines loads share one request and every caller gets the loaded lines', async () => {
  resetLandWater();
  await loadLandWater('fixture', async name => new Response(FILES[name.split('/').pop()]));
  const d = deferredFetch();
  const first = watch(ensureLandWater('fixture', [NEAR], d.fetchFn));
  await tick();
  const second = watch(ensureLandWater('fixture', [NEAR], NO_FETCH));
  const third = watch(loadLandWaterLines('fixture', NO_FETCH));
  await tick();
  assert.equal(first.done || second.done || third.done, false, 'no caller resolves while the lines file is in flight');
  assert.equal(landWater.value.linesLoading, true);
  d.release();
  await Promise.all([first.promise, second.promise, third.promise]);
  assert.deepEqual(first.value(NEAR), {state: 'water'});
  assert.deepEqual(second.value(NEAR), {state: 'water'}, 'the second caller is not left pending');
  assert.ok(third.value.lines);
  assert.deepEqual(d.calls, ['land-water-lines.json']);
  resetLandWater();
});

test('a failed lines request settles every waiting caller as unavailable for a mixed cell, water for a clean one', async () => {
  resetLandWater();
  await loadLandWater('fixture', async name => new Response(FILES[name.split('/').pop()]));
  const d = deferredFetch(() => new Response('', {status: 500}));
  const first = ensureLandWater('fixture', [NEAR], d.fetchFn);
  await tick();
  const second = ensureLandWater('fixture', [NEAR], NO_FETCH);
  await tick();
  d.release();
  for (const place of await Promise.all([first, second])) {
    assert.deepEqual(place(NEAR), {state: 'unknown', reason: 'unavailable'});
    assert.deepEqual(place(FAR), {state: 'water'});
  }
  assert.equal(landWater.value.lines, false);
  assert.equal(landWater.value.linesLoading, false);
  resetLandWater();
});

test('a region switch: the replaced request writes nothing and its callers never read water', async () => {
  resetLandWater();
  const index = deferredFetch();
  const stale = ensureLandWater('fixture', [FAR], index.fetchFn);
  await tick();
  assert.equal((await loadLandWater('other', async () => new Response('', {status: 404}))).region, 'other');
  index.release();
  assert.deepEqual((await stale)(FAR), {state: 'unknown', reason: 'pending'}, 'a classifier for the old region is not water');
  assert.equal(landWater.value.region, 'other', 'the late index did not overwrite the newer region');
  // The same for the lines file.
  resetLandWater();
  await loadLandWater('fixture', async name => new Response(FILES[name.split('/').pop()]));
  const lines = deferredFetch();
  const staleLines = ensureLandWater('fixture', [NEAR], lines.fetchFn);
  await tick();
  await loadLandWater('other', async () => new Response('', {status: 404}));
  lines.release();
  assert.notEqual((await staleLines)(NEAR).state, 'water');
  assert.equal(landWater.value.region, 'other');
  assert.equal(landWater.value.lines, null, 'late lines are not written into another region');
  // Back to the first region: it loads afresh.
  const again = await ensureLandWater('fixture', [NEAR], async name => new Response(FILES[name.split('/').pop()]));
  assert.deepEqual(again(NEAR), {state: 'water'});
  resetLandWater();
});

test('the index grid agrees with the lines file at every clean cell (the committed Morro Bay product)', () => {
  const mb = landWaterModel(dist('regions/morro-bay/land-water.json'), 'morro-bay');
  const mbLines = landWaterLines(dist('regions/morro-bay/land-water-lines.json'), mb);
  assert.ok(mb && mbLines);
  let seed = 7, clean = 0;
  const random = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  for (const key of mb.tiles.keys()) {
    const [, x, y] = key.split('/').map(Number), n = 2 ** 12;
    for (let i = 0; i < 150; i++) {
      const fx = x + random(), fy = y + random();
      const p = {longitude: fx / n * 360 - 180, latitude: Math.atan(Math.sinh(Math.PI * (1 - 2 * fy / n))) * 180 / Math.PI};
      const grid = placeOf(mb, null, p);
      if (grid.state === 'unknown') continue;
      clean++;
      assert.deepEqual(linesPlace(mb, mbLines, p), grid, `${key} ${p.latitude},${p.longitude}`);
    }
  }
  assert.ok(clean > 2000, `${clean} clean-cell samples`);
});

test('the ranked list keeps water only and counts the rest in its basis; without a check nothing is ranked', () => {
  const items = [at(400, 600), at(3300, 3500), at(1980, 600), at(750, 1950), at(1973, 600)];
  assert.deepEqual(keepWater(items, place), {kept: [items[0], items[4]], withheld: 3, pending: false});
  assert.deepEqual(keepWater(items, NO_LAND_WATER).kept, []);
  assert.equal(keepWater(items, p => placeOf(model, null, p)).pending, true);
  assert.equal(withheldNote(3), '3 spots withheld: land/water not confirmed.');
  assert.equal(withheldNote(1), '1 spot withheld: land/water not confirmed.');
  assert.equal(withheldNote(0), '');
});

const MORRO = dist('regions/morro-bay/region.json'), ATLAS = dist('data/atlas.json');
const DATA = {region: {...MORRO, id: 'morro-bay'}, atlas: ATLAS, survey: null, geology: null};
const NOW = Date.now();
const CHECKED = assessScreen({areas: dist('data/protected-areas.geojson').features, checkedAt: new Date(NOW).toISOString(), live: true}, NOW);
const MB = landWaterModel(dist('regions/morro-bay/land-water.json'), 'morro-bay');
const MB_LINES = landWaterLines(dist('regions/morro-bay/land-water-lines.json'), MB);
const inputs = patch => ({region: 'morro-bay', profile: 'boat', target: 'lingcod', coast: 'lingcod', data: DATA, screen: CHECKED, terrain: {state: 'unavailable'}, now: NOW, ...patch});

test('ranking: land and unknown places are withheld and counted; pending shows a check in progress', () => {
  const all = ranking(inputs({place: () => ({state: 'water'})}));
  assert.ok(all.picks.length === 4 && !all.withheld);
  const first = all.picks[0].id, mark = ATLAS.targets.find(t => t.id === first);
  const r = ranking(inputs({place: p => p.latitude === mark.latitude && p.longitude === mark.longitude ? {state: 'land'} : {state: 'water'}}));
  assert.ok(!r.picks.some(p => p.id === first), 'a land place is never ranked');
  assert.equal(r.withheld, 1);
  assert.match(r.basis, /1 spot withheld: land\/water not confirmed\./);
  assert.match(r.basis, /within 25 m of the NOAA shoreline/);
  const none = ranking(inputs({}));
  assert.deepEqual(none.picks, [], 'no land/water check: nothing ranked (fail-closed)');
  assert.ok(none.withheld > 0);
  assert.match(none.empty, /spots withheld: land\/water not confirmed\./);
  const waiting = ranking(inputs({place: () => ({state: 'unknown', reason: 'pending'})}));
  assert.deepEqual(waiting.picks, []);
  assert.equal(waiting.pending, true);
  assert.match(waiting.empty, /Checking land and water/);
});

test('the planner ranking (bestSpots) keeps water only and reports how many it withheld', () => {
  const screen = {ready: () => true, pointAllowed: () => true, geometryAllowed: () => true};
  const area = id => ({id, geometry: {type: 'Polygon', coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]]}});
  const spot = (id, p) => ({id, ...p, canonical_habitat: true, evidence_confidence: {percent: 80}, neighborhood_depth_ft: [40, 80], resolution_m: 2,
    species_fit: {lingcod: 3, 'rockfish-reef': 3}, area_ids: [id], habitat_score: 50});
  const atlas = {targets: [spot('sea', at(400, 600)), spot('shore', at(1980, 600)), spot('hill', at(3300, 3500)), spot('isle', at(750, 1950)), spot('lagoon', at(2950, 1950))],
    areas: ['sea', 'shore', 'hill', 'isle', 'lagoon'].map(area)};
  const stats = {};
  assert.deepEqual(bestSpots(atlas, screen, {place, stats}).map(t => t.id).sort(), ['lagoon', 'sea']);
  assert.equal(stats.withheld, 3);
  const none = {};
  assert.deepEqual(bestSpots(atlas, screen, {stats: none}), [], 'no land/water check: nothing ranked');
  assert.equal(none.withheld, 5);
});

test('committed data (acceptance item 5): every Morro Bay atlas mark is water except the two in tiles NOAA did not serve', () => {
  assert.ok(MB && MB_LINES, 'the committed product is available');
  const out = {}, exceptions = [];
  for (const t of ATLAS.targets) {
    const a = placeOf(MB, MB_LINES, t), b = placeOf(MB, null, t);
    assert.deepEqual(b, a, `${t.id}: the index alone decides, so no lines file loads for today's marks`);
    const key = a.state === 'unknown' ? `unknown:${a.reason}` : a.state;
    out[key] = (out[key] ?? 0) + 1;
    if (a.state !== 'water') exceptions.push(t.id);
  }
  assert.deepEqual(out, {water: 130, 'unknown:unserved-tile': 2});
  assert.deepEqual(exceptions.sort(), ['SC26-002', 'SC26-116']);
  const r = ranking(inputs({place: p => placeOf(MB, MB_LINES, p)}));
  assert.equal(r.picks.length, 4);
  assert.match(distText('regions/morro-bay/land-water.json'), /"status":"available"/);
});
