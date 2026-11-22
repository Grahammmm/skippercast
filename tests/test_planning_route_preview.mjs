// SC1407-15: Show route on Chart. The real planner and the real route builder over the synthetic coast of tests/test_protected_route.mjs;
// the Chart side is a fake engine. The drawn line must never outlive what it was built from.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import test, {after} from 'node:test';
import {isDeepStrictEqual} from 'node:util';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import {signal} from '@preact/signals';
import {closureHits, geometryCoveredByBounds} from '../dist/geo-screen.js';
import {landWater, landWaterModel} from '../web/land-water.ts';
import {configureStore, region as activeRegion, syncFromURL, presentation} from '../web/state.ts';
import {language, prepareCatalogue, t} from '../web/i18n.ts';
import {createPlanner} from '../web/planner.ts';
import {ROUTE_WARNING} from '../web/protected-route.ts';
import {createPlanningRouteLayer, planningRoute, planningRouteFeatures} from '../web/map/planning-route.ts';
import {LAYERS, sourceLayer, PLANNING_ROUTE_SOURCE} from '../web/map/layers.ts';
import {MARK_PICK} from '../web/map/marks.ts';
import {readPalette} from '../web/map/palette.ts';

const dir = await mkdtemp(join(tmpdir(), 'planning-route-')), out = join(dir, 'ui.mjs');
await build({stdin: {resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts', contents: `
    export {PlanningRouteRow} from './web/app/Legend.tsx';
    export {planningRoute} from './web/map/planning-route.ts';
    export {region} from './web/state.ts';
    export {language} from './web/i18n.ts';
    export {render} from 'preact-render-to-string'; export {h} from 'preact';`},
  bundle: true, format: 'esm', platform: 'node', outfile: out, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins});
const ui = await import(pathToFileURL(out).href);
after(() => rm(dir, {recursive: true, force: true}));

const coast = JSON.parse(readFileSync(new URL('./fixtures/land-water/coast.json', import.meta.url)));
const mk = () => landWaterModel({...coast, bounds: [-12110000, 3530000, -12075000, 3555000], tiles: {'12/671/1616': 'w1024'}}, 'fixture');
const model = mk();
const lon = x => (671 + x / 32) / 4096 * 360 - 180;
const lat = y => Math.atan(Math.sinh(Math.PI * (1 - 2 * (1616 + y / 32) / 4096))) * 180 / Math.PI;
const point = (x, y) => ({longitude: lon(x), latitude: lat(y)});
const polygon = (x0, y0, x1, y1) => ({type: 'Polygon', coordinates: [[[lon(x0), lat(y0)], [lon(x1), lat(y0)], [lon(x1), lat(y1)], [lon(x0), lat(y1)], [lon(x0), lat(y0)]]]});
const NOW = new Date('2026-11-07T17:00:00Z'), CHECKED = NOW.toISOString();
const bounds = [lon(0), lat(32), lon(32), lat(0)];
const REGION = {id: 'fixture', timezone: 'America/Los_Angeles', mpa: {bounds}};
const settle = () => new Promise(resolve => setTimeout(resolve, 0));

/** A document that only carries events, as the planner's boundary and visibility listeners need. */
globalThis.document = new EventTarget();
globalThis.location = {href: 'https://fixture.test/map?region=fixture&presentation=chart'};
globalThis.history = {state: null, pushState(_s, _t, url) { location.href = url; }, replaceState(_s, _t, url) { location.href = url; }};
globalThis.dispatchEvent = () => true;
configureStore({v2: true, storage: null});
after(() => { delete globalThis.document; delete globalThis.location; delete globalThis.history; delete globalThis.dispatchEvent; });

function harness({polygons = [polygon(13, 8, 19, 24)], routeContext, landWaterFn} = {}) {
  const ctl = {features: polygons.map(geometry => ({geometry})), covered: true, ready: true, checkedAt: CHECKED, clock: NOW, exclusionReads: 0, throwing: false};
  const screen = {
    ready: () => ctl.ready,
    exportExclusions: () => { ctl.exclusionReads++; if (ctl.throwing) throw Error('broken'); return {checked_at: ctl.checkedAt, features: ctl.features}; },
    coversGeometry: g => ctl.covered && geometryCoveredByBounds(g, bounds),
    geometryAllowed: g => geometryCoveredByBounds(g, bounds) && !closureHits([g], ctl.features).length,
    pointAllowed: p => screen.geometryAllowed({type: 'Point', coordinates: [p.longitude, p.latitude]}),
  };
  const targets = [point(5, 16), point(27, 16), point(5, 27)].map((p, i) => ({...p, id: `user:p${i}`, name: `Stop ${i}`, category: 'other'}));
  const raw = JSON.stringify({ids: ['user:p0', 'user:p1'], userWaypoints: targets, name: 'Detour', date: '2026-11-07'});
  const nav = {shown: 0, fitted: [], open() {}, showMap() { nav.shown++; }, conditions() {}, fit(points) { nav.fitted.push(points); }};
  const stored = [];
  const planner = createPlanner({atlas: {targets: [], areas: []}, screen, region: REGION, now: () => ctl.clock,
    map: {getSize: () => ({x: 512}), getBounds: () => ({getWest: () => bounds[0], getSouth: () => bounds[1], getEast: () => bounds[2], getNorth: () => bounds[3]})},
    getVisible: () => [], storage: {getItem: () => raw, setItem: (k, v) => { stored.push([k, v]); }}, landWater: landWaterFn ?? (async () => () => ({state: 'water'})),
    routeContext: routeContext ?? (async () => ({model, lines: null})), loadPorts: async () => null, emit() {}, nav});
  return {planner, ctl, nav, stored, targets};
}
const seeded = () => { landWater.value = {region: 'fixture', state: 'ready', model, lines: null, linesLoading: false}; activeRegion.value = 'fixture'; };
const unseed = () => { planningRoute.value = null; activeRegion.value = null; };
async function shown(h) { seeded(); const ok = await h.planner.showRouteOnChart(); assert.equal(ok, true, h.planner.routeStatus.value); assert.ok(planningRoute.value, 'a line is held'); return planningRoute.value; }
const gone = (h, why) => { assert.equal(planningRoute.value, null, `${why}: the line is removed`); assert.equal(planningRouteFeatures(planningRoute.value, 'fixture').features.length, 0, `${why}: nothing to draw`); };

test('preview_uses_real_detour_and_same_ordered_inputs: one dashed line of the builder\'s own points, status with length and NOT FOR NAVIGATION, no download', async () => {
  const h = harness();
  try {
    const route = await shown(h);
    assert.ok(route.points.length > 2, 'a detour around the polygon, not the endpoint chord');
    assert.deepEqual(route.points[0], point(5, 16)); assert.deepEqual(route.points.at(-1), point(27, 16));
    const fc = planningRouteFeatures(route, 'fixture');
    assert.equal(fc.features.length, 1); assert.equal(fc.features[0].geometry.type, 'LineString');
    assert.ok(isDeepStrictEqual(fc.features[0].geometry.coordinates, route.points.map(p => [p.longitude, p.latitude])), 'exactly the returned points, in order');
    assert.match(h.planner.routeStatus.value, new RegExp(`Boundary check: ${CHECKED} · ${route.nm.toFixed(1)} nm planning route\\. NOT FOR NAVIGATION`));
    assert.equal(h.nav.shown, 1, 'the dialog closes onto the Chart'); assert.equal(h.nav.fitted.length, 1); assert.equal(h.nav.fitted[0].length, route.points.length, 'the camera fits every route point');
    assert.equal(h.stored.filter(([, v]) => /planning|checkedAt|rtept/.test(v)).length, 0, 'nothing of the line is saved');
    assert.equal(planningRouteFeatures(route, 'other-region').features.length, 0, 'another region draws nothing');
  } finally { h.planner.dispose(); unseed(); }
});

test('preview_selects_chart_from_both_terrain_presentations', async () => {
  for (const mode of ['2d', '3d']) {
    location.href = `https://fixture.test/map?region=fixture&presentation=${mode}`;
    syncFromURL(location.href);
    const h = harness();
    try {
      assert.equal(presentation.value, mode);
      await shown(h);
      assert.equal(presentation.value, 'chart', `${mode}: route and warning must be visible`);
      assert.equal(new URL(location.href).searchParams.get('presentation'), 'chart');
    } finally { h.planner.dispose(); unseed(); }
  }
});

test('preview_uses_launch_first: an included launch starts the line and the moved stop keeps its place', async () => {
  const {launchPoints} = await import('../web/launches.ts');
  const h = harness();
  try {
    seeded();
    launchPoints.value = {region: 'fixture', points: [{id: 'ramp', name: 'Ramp', ...point(5, 5)}]};
    h.planner.setLaunch(true);
    assert.equal(await h.planner.showRouteOnChart(), true, h.planner.routeStatus.value);
    assert.deepEqual(planningRoute.value.points[0], point(5, 5), 'the launch comes first');
    assert.ok(h.planner.moveStop('user:p1', 'up'));
    gone(h, 'a reordered stop');
  } finally { h.planner.dispose(); launchPoints.value = null; unseed(); }
});

test('preview_invalidates_each_input_independently: stops, order, region, boundary refresh, readiness, age, water; changing back does not restore', async () => {
  const changes = {
    'a stop added': h => h.planner.toggleSpot('user:p2', true),
    'a stop removed': h => h.planner.toggleSpot('user:p1', false),
    'a stop order change': h => h.planner.moveStop('user:p1', 'up'),
    'a stop moved': h => h.planner.removeWaypoint('user:p0'),
    'the region': () => { activeRegion.value = 'elsewhere'; },
    'a boundary refresh with the same object and time': () => document.dispatchEvent(new CustomEvent('skippercast:boundaries')),
    'the screen not ready': (h) => { h.ctl.ready = false; h.planner.checkRoutePreview(); },
    'same-timestamp polygons replaced without an event': h => { h.ctl.features = [{geometry: polygon(13, 0, 19, 32)}]; h.planner.checkRoutePreview(); },
    'same-timestamp polygons mutated without an event': h => { h.ctl.features[0].geometry.coordinates = polygon(13, 0, 19, 32).coordinates; document.dispatchEvent(new Event('visibilitychange')); },
    'the screen envelope shrinks without an event': h => { h.ctl.covered = false; h.planner.checkRoutePreview(); },
    'a different boundary check time': (h) => { h.ctl.checkedAt = '2026-11-07T17:00:01.000Z'; h.planner.checkRoutePreview(); },
    'a screen that throws': (h) => { h.ctl.throwing = true; h.planner.checkRoutePreview(); },
    '36 h and 1 ms past the check': (h) => { h.ctl.clock = new Date(NOW.getTime() + 36 * 3600_000 + 1); h.planner.checkRoutePreview(); },
    'a clock far before the check': (h) => { h.ctl.clock = new Date(NOW.getTime() - 301_000); h.planner.checkRoutePreview(); },
    'the water state reloading': () => { landWater.value = {...landWater.value, state: 'loading'}; },
    'a new water model with the same source': () => { landWater.value = {...landWater.value, model: mk()}; },
    'new water lines': () => { landWater.value = {...landWater.value, lines: {}}; },
    'the planner disposed': h => h.planner.dispose(),
  };
  for (const [what, change] of Object.entries(changes)) {
    const h = harness();
    try {
      await shown(h);
      change(h);
      gone(h, what);
      if (what === 'a stop added') { h.planner.toggleSpot('user:p2', false); gone(h, 'changing it back'); }
      if (what === 'the region') { activeRegion.value = 'fixture'; gone(h, 'returning to the region'); }
    } finally { h.planner.dispose(); unseed(); }
  }
});

test('preview_removal_status_is_spanish_after_stop_reorder', async () => {
  await prepareCatalogue('es');
  const h = harness();
  try {
    language.value = 'es';
    await shown(h);
    h.planner.moveStop('user:p1', 'up');
    gone(h, 'reordered stop');
    assert.equal(h.planner.routeStatus.value, 'Ruta retirada de la Carta: cambiaron las paradas, la región, la comprobación de límites o los datos de agua. Muéstrala de nuevo para trazar otra.');
    assert.equal(h.planner.routeStatus.value, t('planner.route.removed', 'es'));
  } finally { language.value = 'en'; h.planner.dispose(); unseed(); }
});

test('preview_age_exact_boundary: exactly 36 h still stands (the builder accepts it); only the clock past it removes the line, with no new search', async () => {
  const h = harness();
  try {
    await shown(h);
    h.ctl.clock = new Date(NOW.getTime() + 36 * 3600_000);
    h.planner.checkRoutePreview();
    assert.ok(planningRoute.value, 'exactly 36 h is accepted');
    h.ctl.clock = new Date(NOW.getTime() - 300_000);
    h.planner.checkRoutePreview();
    assert.ok(planningRoute.value, 'exactly -5 min is accepted');
    const reads = h.ctl.exclusionReads;
    document.dispatchEvent(new Event('visibilitychange'));
    assert.ok(planningRoute.value, 'resume with a valid clock keeps it');
    h.ctl.clock = new Date(NOW.getTime() + 36 * 3600_000 + 1);
    document.dispatchEvent(new Event('visibilitychange'));
    gone(h, 'a resume past 36 h');
    assert.match(h.planner.routeStatus.value, /removed/i, 'the person is told it went');
    assert.ok(h.ctl.exclusionReads - reads <= 4, 'only the screen is re-read; no new route build');
  } finally { h.planner.dispose(); unseed(); }
});

test('preview_refusal_always_clears_previous_line: a refused route draws nothing and shows the refusal', async () => {
  const refusals = {
    'a protected stop': h => { h.ctl.features = [{geometry: polygon(3, 14, 8, 18)}]; },
    'a full-route barrier': h => { h.ctl.features = [{geometry: polygon(13, 0, 19, 32)}]; },
    'an unready screen': h => { h.ctl.ready = false; },
    'an expired screen': h => { h.ctl.clock = new Date(NOW.getTime() + 37 * 3600_000); },
    'a missing water model': (h, set) => set({model: null, lines: null}),
    'one stop': h => h.planner.toggleSpot('user:p1', false),
  };
  for (const [what, refuse] of Object.entries(refusals)) {
    let ctx = {model, lines: null};
    const h = harness({routeContext: async () => ctx});
    try {
      await shown(h);
      refuse(h, c => { ctx = c; });
      // anything that changes the inputs already removed the old line; the new attempt must also draw nothing
      const ok = await h.planner.showRouteOnChart();
      assert.equal(ok, false, what);
      gone(h, what);
      assert.match(h.planner.routeStatus.value, /unavailable|Choose 2|outside the current|boundar|Protected-area/i, `${what}: shows the refusal`);
      assert.doesNotMatch(h.planner.routeStatus.value, /planning route\. NOT FOR NAVIGATION/, `${what}: not the success line`);
      assert.equal(h.nav.shown, 1, `${what}: no navigation to an empty line`);
    } finally { h.planner.dispose(); unseed(); }
  }
});

test('preview_async_generation_no_resurrection: a change while the water is loading, or disposal, never publishes the old line', async () => {
  for (const change of ['order', 'boundary', 'dispose']) {
    let release;
    const h = harness({routeContext: () => new Promise(resolve => { release = () => resolve({model, lines: null}); })});
    try {
      seeded();
      const attempt = h.planner.showRouteOnChart();
      await settle();
      assert.equal(h.planner.routing.value, true);
      if (change === 'order') h.planner.moveStop('user:p1', 'up');
      if (change === 'boundary') document.dispatchEvent(new CustomEvent('skippercast:boundaries'));
      if (change === 'dispose') h.planner.dispose();
      release();
      assert.equal(await attempt, false, change);
      gone(h, `a ${change} during the build`);
      assert.equal(h.nav.shown, 0);
    } finally { h.planner.dispose(); unseed(); }
  }
});

test('preview_download_rebuilds_not_reuses: the download repeats the screen and refuses what the old line would have shown', async () => {
  const h = harness();
  try {
    await shown(h);
    const reads = h.ctl.exclusionReads;
    const file = await h.planner.exportRouteFile();
    assert.ok(h.ctl.exclusionReads > reads, 'the download read the screen again');
    assert.match(await file.text(), /<rte>/);
    assert.equal(h.planner.routing.value, false);
    h.ctl.features = [{geometry: polygon(13, 0, 19, 32)}];
    await assert.rejects(h.planner.exportRouteFile(), /unavailable/i, 'the download builds its own route and refuses');
  } finally { h.planner.dispose(); unseed(); }
});

test('preview_busy_blocks_duplicate_actions', async () => {
  let release;
  const h = harness({routeContext: () => new Promise(resolve => { release = () => resolve({model, lines: null}); })});
  try {
    seeded();
    const first = h.planner.showRouteOnChart();
    await settle();
    assert.equal(await h.planner.showRouteOnChart(), false, 'a second click while busy does nothing');
    release();
    assert.equal(await first, true);
  } finally { h.planner.dispose(); unseed(); }
});

test('preview_layer_order_runtime: one dashed line under the marks, above the reach ring, no hit target; cleared line leaves the engine empty', async () => {
  const ids = LAYERS.map(e => e.id);
  assert.ok(ids.indexOf('reach') < ids.indexOf('planning-route') && ids.indexOf('planning-route') < ids.indexOf('marks'), 'registry order');
  assert.equal(sourceLayer(PLANNING_ROUTE_SOURCE), 'planning-route');
  const entry = LAYERS.find(e => e.id === 'planning-route');
  assert.deepEqual(entry.presentations, ['chart']); assert.equal(entry.control, 'always');
  const calls = [], engine = signal(null);
  const fake = {setOverlay: (id, overlay, before) => calls.push(['overlay', id, overlay, before]), setData: (id, data) => calls.push(['data', id, data])};
  const layer = createPlanningRouteLayer({engine, palette: () => readPalette(name => `token(${name})`)});
  activeRegion.value = 'fixture';
  try {
    planningRoute.value = {region: 'fixture', points: [point(5, 16), point(16, 2), point(27, 16)], nm: 1.2, checkedAt: CHECKED};
    assert.equal(calls.length, 0, 'nothing is queued without an engine');
    engine.value = fake;
    const over = calls.find(c => c[0] === 'overlay' && c[2]);
    assert.ok(over, 'drawn once the engine is up');
    assert.equal(over[3], MARK_PICK, 'inserted under the first mark layer');
    assert.equal(over[2].layers.length, 1); assert.equal(over[2].layers[0].type, 'line'); assert.ok(over[2].layers[0].paint['line-dasharray']);
    const data = calls.filter(c => c[0] === 'data').at(-1)[2];
    assert.equal(data.features.length, 1);
    planningRoute.value = null;
    assert.equal(calls.filter(c => c[0] === 'overlay').at(-1)[2], null, 'removed from the engine');
    planningRoute.value = {region: 'foreign', points: [point(5, 16), point(27, 16)], nm: 1, checkedAt: CHECKED};
    assert.equal(calls.filter(c => c[0] === 'overlay').at(-1)[2], null, 'another region\'s line is never drawn');
  } finally { layer.destroy(); planningRoute.value = null; activeRegion.value = null; }
});

test('preview_copy_warning_visible_and_default_markup_unchanged: the legend row carries the whole warning in both languages; absent preview adds nothing', () => {
  // The legend is bundled with its own copy of the signals, so it is driven through the bundle's.
  const {PlanningRouteRow, render, h: hh, planningRoute: route, region, language} = ui;
  try {
    region.value = 'fixture';
    assert.equal(render(hh(PlanningRouteRow, {})), '', 'no preview, no row');
    route.value = {region: 'fixture', points: [point(5, 16), point(16, 2), point(27, 16)], nm: 4.04, checkedAt: CHECKED};
    for (const lang of ['en', 'es']) {
      language.value = lang;
      const html = render(hh(PlanningRouteRow, {}));
      assert.match(html, /data-layer="planning-route"/);
      assert.ok(html.includes(ROUTE_WARNING), `${lang}: the full warning is on the row`);
      assert.ok(html.includes('4.0 nm') && html.includes(CHECKED), `${lang}: length and check time`);
    }
    route.value = {region: 'foreign', points: [point(5, 16), point(27, 16)], nm: 1, checkedAt: CHECKED};
    assert.equal(render(hh(PlanningRouteRow, {})), '', 'no row for another region');
  } finally { language.value = 'en'; route.value = null; region.value = null; }
});

test('preview_action_button: the dialog offers Show route on Chart beside the download', async () => {
  const src = readFileSync(new URL('../web/app/Planner.tsx', import.meta.url), 'utf8');
  assert.match(src, /id="show-planning-route"[\s\S]*?showRouteOnChart/);
  const catalog = JSON.parse(readFileSync(new URL('../catalog/app/strings.json', import.meta.url), 'utf8')).strings;
  assert.equal(catalog['planner.route.show'].en, 'Show route on Chart');
  for (const id of ['planner.route.show', 'layer.planning-route.label', 'layer.planning-route.basis', 'layer.planning-route.legend0', 'legend.planningRoute.detail', 'legend.bs.planningRoute']) {
    assert.ok(catalog[id]?.en && catalog[id]?.es, `${id} has English and Spanish`);
  }
  assert.deepEqual([...catalog['legend.planningRoute.detail'].en.matchAll(/\{(\w+)\}/g)].map(m => m[1]), [...catalog['legend.planningRoute.detail'].es.matchAll(/\{(\w+)\}/g)].map(m => m[1]), 'placeholders match');
});
