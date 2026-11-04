// SC2207-04: the trip planner's Best available keeps its maximum one-way distance by water where a route is computed
// (web/planner.ts selectBest -> dist/spot-ranking.js bestSpots `distanceFor`), as Where to look does (SC1322-10, web/ranking.ts
// `routedPicks`): at most ROUTE_BUDGET routes a click, a reef whose route runs past the range is dropped and the next eligible
// reef fills its place, a reef without a route keeps its straight line, labelled. Offline: synthetic reefs, an injected route
// and context, and the fixture land/water product of tests/test_trip_legs_route.mjs; fetch is replaced where lines are asked.
import assert from 'node:assert/strict';
import test, {after} from 'node:test';
import {mkdtemp, rm} from 'node:fs/promises';
import {readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createHash} from 'node:crypto';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import {distanceNm} from '../dist/spot-ranking.js';
import {draftKey} from '../dist/trip-export.js';
import {ROUTE_BUDGET} from '../web/ranking.ts';

const dir = await mkdtemp(join(tmpdir(), 'planner-route-')), out = join(dir, 'ui.mjs');
await build({stdin: {resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts', contents: `
    export {Planner} from './web/app/Planner.tsx';
    export {createPlanner} from './web/planner.ts';
    export {tripLegs} from './web/trip-legs.ts';
    export {cruiseSpeed} from './web/limits.ts';
    export {landWater, landWaterModel, resetLandWater} from './web/land-water.ts';
    export {render} from 'preact-render-to-string'; export {h} from 'preact';`},
  bundle: true, format: 'esm', platform: 'node', outfile: out, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins});
const m = await import(pathToFileURL(out).href);
after(() => rm(dir, {recursive: true, force: true}));

const NOW = new Date('2026-10-12T18:00:00Z');
const REGION = {id: 'test-coast', name: 'Test Coast', timezone: 'America/Los_Angeles', mpa: {bounds: [-10, -10, 10, 10]}};
const SCREEN = {ready: () => true, pointAllowed: () => true, geometryAllowed: () => true, exportExclusions: () => ({features: [], checked_at: NOW.toISOString()})};
const MAP = {getSize: () => ({x: 512, y: 512}), getBounds: () => ({getWest: () => -1, getEast: () => 1, getNorth: () => 1, getSouth: () => -1, contains: () => true})};
const ATLAS = {targets: [], areas: [], drifts: []};
const PORT = {id: 'p1', name: 'Port 1', region: 'test-coast', match: [0, 0]};
const settle = () => new Promise(resolve => setTimeout(resolve, 0));
const water = () => ({state: 'water'});
const ring = (x, y, w = 0.002) => [[x, y], [x + w, y], [x + w, y + w], [x, y + w], [x, y]];

/** A screened publication: reef i lies `nms[i]` nm due north of the port at (0, 0); ranked best first (same confidence, falling score). */
function reefsAt(nms) {
  const targets = nms.map((nm, i) => ({id: `reef-${i}`, label: `Reef ${i}`, canonical_habitat: true, latitude: nm / 60, longitude: 0, habitat_grade: 'A', habitat_score: 1000 - i,
    neighborhood_depth_ft: [90, 120], resolution_m: 2, evidence_confidence: {percent: 90}, species_fit: {lingcod: 3, 'rockfish-reef': 3}, area_ids: [`area-${i}`],
    terrain_interpretation: 'Raised structure', source_url: 'https://example.org/s', evidence_status: 'Fish presence unverified.'}));
  const areas = targets.map(t => ({id: t.area_ids[0], target_ids: [t.id], geometry: {type: 'Polygon', coordinates: [ring(t.longitude, t.latitude)]}}));
  return {targets, areas, publication: {export_sha256: 'a'.repeat(64), status: 'ready', expires_at: '2099-12-31T00:00:00Z', region: 'test-coast'}, source_validation_date: '2026-10-01'};
}
const straightNm = t => distanceNm({latitude: 0, longitude: 0}, t);
/** A route spy: `answer(to, from)` per call, every call recorded. */
const spy = answer => { const calls = []; const route = (model, lines, from, to) => { calls.push({model, lines, from, to}); return answer(to, from); }; return {route, calls}; };
const ok = nm => ({ok: true, nm, points: []});
const none = () => ({model: null, lines: null});

function harness({nms = [3, 4, 5], ports = [PORT], route, routeContext, stored = null, port = 'p1', limit = 20, distance = 10, loadReefs} = {}) {
  const store = new Map(stored ? [[draftKey(REGION.id), stored]] : []), emitted = [], contexts = [];
  const storage = {getItem: k => store.get(k) ?? null, setItem: (k, v) => { store.set(k, v); }};
  const planner = m.createPlanner({atlas: ATLAS, screen: SCREEN, region: REGION, map: MAP, getVisible: () => [], storage, now: () => NOW, landWater: async () => water,
    loadReefs: loadReefs ?? (async () => reefsAt(nms)), loadPorts: async () => ({ports}), emit: d => emitted.push(d), route,
    routeContext: routeContext ? async id => { contexts.push(id); return routeContext(id); } : undefined, nav: {open() {}, showMap() {}, conditions() {}}});
  return {planner, store, emitted, contexts, saved: () => JSON.parse(store.get(draftKey(REGION.id)) ?? 'null'), async ready() {
    await settle();
    if (port) planner.setFilter('port', port);
    planner.setFilter('limit', limit); planner.setFilter('distance', distance);
  }};
}
/** Select Best available and return the ranked targets in rank order. */
async function select(h) {
  await h.ready();
  await h.planner.selectBest();
  return h.planner.spots.value.filter(t => t.trip_rank);
}

test('a reef 13 nm by water is dropped from a 10 nm plan and the next reef fills its place; ranks stay contiguous', async () => {
  const r = spy(to => ok(to.latitude * 60 > 8 ? 13 : straightNm(to) * 1.1)), h = harness({nms: [9, 3, 4, 5], route: r.route, routeContext: async () => none(), limit: 3});
  const got = await select(h);
  assert.equal(h.planner.ranked.value, true, h.planner.scopeStatus.value);
  assert.deepEqual(got.map(t => [t.id, t.trip_rank, t.distance_basis]), [['reef-1', 1, 'water'], ['reef-2', 2, 'water'], ['reef-3', 3, 'water']]);
  assert.ok(got.every(t => t.name.startsWith(`0${t.trip_rank} `)));
  assert.ok(Math.abs(got[0].distance_nm - straightNm(got[0]) * 1.1) < 1e-9, 'the water nm, not the straight line');
  assert.deepEqual(r.calls.map(c => c.to.id), ['reef-0', 'reef-1', 'reef-2', 'reef-3'], 'it stops routing once three are kept');
  assert.deepEqual(h.saved().ids, ['reef-1', 'reef-2', 'reef-3']);
  assert.deepEqual(h.saved().rankedPlan.priorities, [{id: 'reef-1', rank: 1}, {id: 'reef-2', rank: 2}, {id: 'reef-3', rank: 3}]);
  assert.ok(!JSON.stringify([...h.store.values()]).includes('distance'), 'route metadata is in the page only');
  assert.ok(h.emitted.some(d => d.targets.length === 3));
  // The same plan without a route for that reef keeps its straight line (9 nm), labelled, in its habitat order.
  const g = harness({nms: [9, 3, 4, 5], route: () => null, routeContext: async () => none(), limit: 3}), straight = await select(g);
  assert.deepEqual(straight.map(t => [t.id, t.distance_basis]), [['reef-0', 'straight'], ['reef-1', 'straight'], ['reef-2', 'straight']]);
  h.planner.dispose(); g.planner.dispose();
});

test('the range is inclusive and unrounded on the water nm; a reef past it by straight line is never routed', async () => {
  const r = spy(to => ok(to.id === 'reef-0' ? 10 : to.id === 'reef-1' ? 10.0001 : 5)), h = harness({nms: [4, 5, 11, 6], route: r.route, routeContext: async () => none()});
  const got = await select(h);
  assert.deepEqual(got.map(t => t.id), ['reef-0', 'reef-3']);
  assert.equal(got[0].distance_nm, 10);
  assert.deepEqual(r.calls.map(c => c.to.id), ['reef-0', 'reef-1', 'reef-3'], 'reef-2 (11 nm straight) is outside the range before any route');
  h.planner.dispose();
});

test('40 reefs, every route past the range: 24 routes, then the next reefs fill by labelled straight line, in order', async () => {
  const nms = Array.from({length: 40}, (_, i) => 1 + i * 0.25);
  for (const limit of [10, 20]) {
    const r = spy(to => ok(straightNm(to) * 20)), h = harness({nms, route: r.route, routeContext: async () => none(), limit, distance: 12});
    const got = await select(h);
    assert.equal(r.calls.length, ROUTE_BUDGET, `limit ${limit}: the budget is spent and not passed`);
    const expected = nms.map((_, i) => `reef-${i}`).slice(ROUTE_BUDGET).filter(id => straightNm(h.planner.tripAtlas.value.targets.find(t => t.id === id) ?? {latitude: 0, longitude: 0}) <= 12);
    assert.deepEqual(got.map(t => t.id), expected.slice(0, limit), `limit ${limit}: habitat order, no re-sort by distance`);
    assert.ok(got.every(t => t.distance_basis === 'straight' && t.distance_why === undefined));
    assert.deepEqual(got.map(t => t.trip_rank), got.map((_, i) => i + 1));
    h.planner.dispose();
  }
  const wide = Array.from({length: 80}, (_, i) => 1 + i * 0.2);
  for (const limit of [30, 50]) {
    const r = spy(to => ok(straightNm(to) * 20)), h = harness({nms: wide, route: r.route, routeContext: async () => none(), limit, distance: 20});
    const got = await select(h);
    assert.ok(r.calls.length === ROUTE_BUDGET && got.length === limit, `limit ${limit}: ${r.calls.length} routes, ${got.length} kept`);
    assert.equal(got[0].id, `reef-${ROUTE_BUDGET}`);
    h.planner.dispose();
  }
  const full = spy(to => ok(straightNm(to))), h = harness({nms, route: full.route, routeContext: async () => none(), limit: 10, distance: 12});
  await select(h);
  assert.equal(full.calls.length, 10, 'it stops routing once the list is full');
  h.planner.dispose();
});

test('every route failure, a route not computed, an absent product and another region\'s product keep the labelled straight line', async () => {
  for (const reason of ['no-product', 'lines-needed', 'start-not-water', 'end-not-water', 'no-route', 'too-far']) {
    const h = harness({nms: [3, 12], route: () => ({ok: false, reason}), routeContext: async () => none()});
    const got = await select(h);
    assert.deepEqual(got.map(t => [t.id, t.distance_basis, t.distance_why, t.distance_nm]), [['reef-0', 'straight', reason, straightNm(got[0])]], reason);
    h.planner.dispose();
  }
  const nul = harness({nms: [3], route: () => null, routeContext: async () => none()}), [plain] = await select(nul);
  assert.ok(plain.distance_basis === 'straight' && !('distance_why' in plain), 'null: not computed, no reason');
  nul.planner.dispose();
  // The real router with no product, and with a product that belongs to another region (the default context).
  m.resetLandWater();
  const absent = harness({nms: [3]}), [a] = await select(absent);
  assert.deepEqual([a.distance_basis, a.distance_why], ['straight', 'no-product']);
  absent.planner.dispose();
  m.landWater.value = {region: 'elsewhere', state: 'ready', model: m.landWaterModel(coast('w1024', 'elsewhere'), 'elsewhere'), lines: false, linesLoading: false};
  const seen = spy(() => null), other = harness({nms: [3], route: seen.route}), [o] = await select(other);
  assert.ok(seen.calls.length === 1 && seen.calls[0].model === null, 'another region\'s model is never used');
  assert.equal(o.distance_basis, 'straight');
  other.planner.dispose(); m.resetLandWater();
});

test('an invalid route answer or a rejected plan writes nothing; an empty result keeps the previous selection', async () => {
  const base = harness({nms: [3, 4], route: () => ok(1), routeContext: async () => none()});
  await select(base);
  const before = base.store.get(draftKey(REGION.id));
  assert.deepEqual(base.planner.draft.value.ids, ['reef-0', 'reef-1']);
  for (const bad of [ok(NaN), ok(Infinity), ok(-2)]) {
    const h = harness({nms: [3], route: () => bad, routeContext: async () => none(), stored: before});
    await h.ready(); await h.planner.selectBest();
    assert.equal(h.planner.scopeStatus.value, 'Invalid trip distance.');
    assert.equal(h.store.get(draftKey(REGION.id)), before, 'nothing was written');
    assert.equal(h.planner.ranked.value, false); assert.deepEqual(h.planner.draft.value.ids, ['reef-0', 'reef-1']);
    h.planner.dispose();
  }
  // Every reef is past the range by water: the existing no-ranked message, the saved selection untouched.
  const far = harness({nms: [3, 4], route: () => ok(30), routeContext: async () => none(), stored: before});
  await far.ready(); await far.planner.selectBest();
  assert.match(far.planner.scopeStatus.value, /^No ranked reefs meet these filters and current checks\./);
  assert.equal(far.store.get(draftKey(REGION.id)), before);
  assert.deepEqual(far.planner.draft.value.ids, ['reef-0', 'reef-1']);
  base.planner.dispose(); far.planner.dispose();
});

test('the route runs from the chosen port; no port means no context, no route, no distance and no device position', async () => {
  const geo = [], saved = Object.getOwnPropertyDescriptor(globalThis, 'navigator');
  Object.defineProperty(globalThis, 'navigator', {configurable: true, writable: true, value: {geolocation: {getCurrentPosition() { geo.push('get'); }, watchPosition() { geo.push('watch'); return 1; }, clearWatch() {}}}});
  try {
    const ports = [PORT, {id: 'p2', name: 'Launch 2', region: 'test-coast', match: [0.05, 0.03]}], answers = {};
    for (const id of ['p1', 'p2']) {
      const r = spy((to, from) => ok(distanceNm(from, to) * (from.latitude === 0 ? 1.2 : 1.5))), h = harness({ports, port: id, route: r.route, routeContext: async () => none()});
      const [first] = await select(h);
      assert.deepEqual([r.calls[0].from.latitude, r.calls[0].from.longitude], ports.find(p => p.id === id).match);
      answers[id] = first.distance_nm; assert.equal(first.distance_basis, 'water');
      h.planner.dispose();
    }
    assert.notEqual(answers.p1, answers.p2, 'two ports, two routes');
    const r = spy(() => ok(1)), h = harness({ports: [], port: '', route: r.route, routeContext: async () => none()}), got = await select(h);
    assert.ok(got.length > 0 && got.every(t => t.distance_nm === null && !('distance_basis' in t)), 'no port, no distance');
    assert.ok(r.calls.length === 0 && h.contexts.length === 0, 'no context and no route work');
    assert.deepEqual(geo, []);
    h.planner.dispose();
  } finally { if (saved) Object.defineProperty(globalThis, 'navigator', saved); else delete globalThis.navigator; }
});

test('a change made while the route context loads wins: no stale persistence or emission', async () => {
  for (const change of [p => p.setFilter('distance', 5), p => p.preset('none'), p => p.toggleSpot('reef-9', true)]) {
    let release;
    const r = spy(() => ok(1)), h = harness({nms: [3, 4], route: r.route, routeContext: () => new Promise(resolve => { release = () => resolve(none()); })});
    await h.ready();
    const done = h.planner.selectBest();
    for (let i = 0; i < 20 && !release; i++) await settle();
    assert.ok(release, 'the click is waiting on the context');
    change(h.planner); h.emitted.length = 0;
    const edited = h.store.get(draftKey(REGION.id));
    release(); await done;
    assert.equal(r.calls.length, 0, 'no route after the click went stale');
    assert.equal(h.store.get(draftKey(REGION.id)), edited, 'the stale answer wrote nothing');
    assert.ok(h.planner.ranked.value === false && !h.emitted.some(d => d.targets.length), 'and drew nothing');
    h.planner.dispose();
  }
});

// The default context: the loaded product of this region and the shared lines file (one request across clicks).
const COAST = '12/671/1616', fixture = name => JSON.parse(readFileSync(new URL(`./fixtures/land-water/${name}`, import.meta.url), 'utf8'));
// The fixture index and lines file say region `fixture`; these are the same bytes made this planner's region, the index naming the lines' new hash.
const linesText = readFileSync(new URL('./fixtures/land-water/coast.lines.json', import.meta.url), 'utf8');
const linesFor = region => JSON.stringify({...JSON.parse(linesText), region_id: region});
const coast = (base, region = 'test-coast') => ({...fixture('coast.json'), region_id: region, lines: {...fixture('coast.json').lines, sha256: createHash('sha256').update(linesFor(region)).digest('hex')}, tiles: {[COAST]: base}});
test('the default context reads only this region\'s ready product and asks the shared lines request once', async () => {
  const text = linesFor('test-coast'), real = globalThis.fetch;
  let asked = 0;
  globalThis.fetch = async () => { asked++; return {ok: true, text: async () => text}; };
  try {
    m.resetLandWater();
    const model = m.landWaterModel(coast('w1024'), 'test-coast');
    m.landWater.value = {region: 'test-coast', state: 'ready', model, lines: null, linesLoading: false};
    const r = spy(() => null), h = harness({nms: [3], route: r.route});
    await select(h); await h.planner.selectBest();
    assert.equal(asked, 1, 'one lines request across two clicks');
    assert.ok(r.calls.length === 2 && r.calls.every(c => c.model === model && c.lines && typeof c.lines === 'object'), 'the loaded model and lines are used');
    // A failed lines file reads as failed (false), once: the route runs on the model without lines.
    m.resetLandWater(); asked = 0;
    globalThis.fetch = async () => { asked++; return {ok: false, text: async () => ''}; };
    m.landWater.value = {region: 'test-coast', state: 'ready', model, lines: null, linesLoading: false};
    const f = spy(() => null), g = harness({nms: [3], route: f.route}); await select(g);
    assert.ok(asked === 1 && f.calls[0].model === model && f.calls[0].lines === false);
    // The region changes while the lines load: the foreign product is never handed to a route.
    m.resetLandWater(); asked = 0;
    let finish;
    globalThis.fetch = () => new Promise(resolve => { finish = () => resolve({ok: true, text: async () => text}); });
    m.landWater.value = {region: 'test-coast', state: 'ready', model, lines: null, linesLoading: false};
    const s = spy(() => null), k = harness({nms: [3], route: s.route});
    await k.ready();
    const click = k.planner.selectBest();
    for (let i = 0; i < 20 && !finish; i++) await settle();
    m.landWater.value = {region: 'elsewhere', state: 'ready', model: m.landWaterModel(coast('w1024', 'elsewhere'), 'elsewhere'), lines: null, linesLoading: false};
    finish(); await click;
    assert.ok(s.calls.length === 1 && s.calls[0].model === null && s.calls[0].lines === null, 'a mismatch after the await gives no model');
    for (const p of [h, g, k]) p.planner.dispose();
  } finally { globalThis.fetch = real; m.resetLandWater(); }
});

test('idle land/water state and an injected classifier make no network request', async () => {
  const real = globalThis.fetch; let asked = 0;
  globalThis.fetch = async () => { asked++; throw new Error('offline'); };
  try { m.resetLandWater(); const h = harness({nms: [3, 4]}), got = await select(h); assert.ok(got.length === 2 && asked === 0); h.planner.dispose(); }
  finally { globalThis.fetch = real; }
});

test('the planner shows each ranked reef\'s basis and the new help; legs, GPX and saved plan do not change; a restored plan claims no basis', async () => {
  const html = p => m.render(m.h(m.Planner, {model: p, open: false})), list = markup => markup.match(/id="export-spot-list"[\s\S]*?<\/div>/)[0];
  const r = spy(to => to.id === 'reef-1' ? null : ok(straightNm(to) * 1.25));
  const h = harness({nms: [3, 4, 5], route: r.route, routeContext: async () => none()});
  m.cruiseSpeed.value = 20;
  const got = await select(h), markup = html(h.planner), rows = list(markup);
  assert.equal(got.length, 3);
  assert.ok(rows.includes(`${(straightNm(got[0]) * 1.25).toFixed(1)} nm by water`));
  assert.ok(rows.includes(`${straightNm(got[1]).toFixed(1)} nm straight line`));
  assert.match(markup, /Distance is by water where routed, else straight line, from the selected port\. Planning distance, not a navigation route\. Habitat ranks stay fixed; check the selected day’s conditions separately\./);
  assert.doesNotMatch(markup, /straight-line reference only/);
  // The stops in order are tripLegs over the same stops, not the reef's range distance.
  const stops = got.map(t => ({id: t.id, name: t.name, lat: t.latitude, lon: t.longitude})), legs = m.tripLegs({name: PORT.name, lat: 0, lon: 0}, stops, 20, () => null);
  const shown = [...markup.matchAll(/<li>([^<]*)<\/li>/g)].map(x => x[1]).filter(t => t.includes('→'));
  assert.deepEqual(shown, legs.legs.map(l => `${l.from} → ${l.to} · ${l.nm.toFixed(1)} nm straight line${l.runMin === null ? '' : ` · at least ${l.runMin} min`} · Protected areas not checked`));
  assert.ok(markup.includes(`Total: ${legs.totalNm.toFixed(1)} nm`));
  // The GPX is the same with or without route metadata.
  const plain = harness({nms: [3, 4, 5], route: () => null, routeContext: async () => none()});
  await select(plain);
  assert.equal(await (await h.planner.exportFile('gpx')).text(), await (await plain.planner.exportFile('gpx')).text(), 'the GPX carries no distance basis');
  // An older plan restored from the saved draft shows no basis.
  const again = harness({nms: [3, 4, 5], stored: h.store.get(draftKey(REGION.id)), route: r.route, routeContext: async () => none()});
  await settle(); await again.planner.restore();
  assert.equal(again.planner.ranked.value, true, again.planner.scopeStatus.value);
  const old = list(html(again.planner));
  assert.ok(old.includes('#1 ·') && !/nm by water|nm straight line/.test(old), 'no invented distance basis');
  for (const p of [h, plain, again]) p.planner.dispose();
});
