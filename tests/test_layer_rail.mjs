// Layer rail, legend, ?layers= and profile defaults (FE-20, docs/plans/front-end/dev-plan.md;
// design § 6, § 8, § 9): the store's rail list and Currents choice from links, storage and profile
// switches (#482), and the rail and legend rendered to strings on the Chart and in Terrain 2D/3D,
// with the base choice. LayerRail.tsx and Legend.tsx are bundled with esbuild; MapLibre and the
// terrain renderer stay out (dynamic imports that rendering never reaches). Layer states are set
// on the modules' signals with synthetic values; nothing is fetched.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';

const ROOT = new URL('..', import.meta.url).pathname;
const ORIGIN = 'https://s.test/map';
const memory = () => { const m = new Map(); return {getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v)), map: m}; };

let bundle;
async function load() {
  if (bundle) return bundle;
  const out = join(await mkdtemp(join(tmpdir(), 'rail-')), 'rail.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {LayerRail, baseNote, baseOptions, shownBase} from './web/app/LayerRail.tsx';
      export {Legend} from './web/app/Legend.tsx';
      export {RAIL_ENTRIES} from './web/app/rail.ts';
      export {CHART_ONLY, drawsIn} from './web/map/layers.ts';
      export {seafloorState} from './web/map/seafloor.ts';
      export {currentsState} from './web/map/currents.ts';
      export {waterTempState} from './web/map/sst.ts';
      export {swellState} from './web/map/swell.ts';
      export {cloudStamp} from './web/map/clouds.ts';
      export {groundsState} from './web/map/charter-grounds.ts';
      export {aisOn, aisState} from './web/map/commercial-ais.ts';
      export {currentStatus, terrainOptions, TERRAIN_DEFAULTS} from './web/map/stage.ts';
      export * as state from './web/state.ts';
      export {PROFILE_TABLE, RAIL_IDS} from './web/profile.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: [{name: 'renderers', setup: b => b.onResolve({filter: /^\.\/(?:terrain|maplibre)\.js$/}, args => ({path: args.path, external: true}))}],
  });
  bundle = await import(pathToFileURL(out).href);
  return bundle;
}

/** The rail's toggles by label: pressed, disabled and the note under the name. */
const railItems = html => Object.fromEntries([...html.matchAll(
  /<li class="ui-rail-item" data-on="(true|false)"><button([^>]*)>.*?<span class="ui-rail-label">([^<]+)<\/span>(?:<span class="ui-rail-note ui-mono">([^<]*)<\/span>)?/gs,
)].map(m => [m[3], {on: m[1] === 'true', disabled: /\sdisabled(?:[\s>=]|$)/.test(m[2]), note: m[4] ?? ''}]));
const pressed = items => Object.keys(items).filter(label => items[label].on);
/** The colour keys the legend shows, in order. */
const swatches = html => [...html.matchAll(/class="app-swatch" data-layer="([a-z-]+)"/g)].map(m => m[1]);
const reasons = html => Object.fromEntries([...html.matchAll(/data-reason="([a-z-]+)">([^<]*)</g)].map(m => [m[1], m[2]]));
/** The base select and its note. */
const baseChoice = html => html.match(/<div class="app-rail-base">.*$/s)[0];

test('?layers=seafloor,currents restores both; Fish ?layer=temperature opens Water temp (Accept 1)', async () => {
  const m = await load(), s = m.state;
  s.configureStore({v2: true, storage: memory()});
  s.syncFromURL(`${ORIGIN}?region=morro-bay&layers=seafloor,currents`);
  assert.deepEqual(s.layers.value, ['seafloor', 'currents']);
  assert.equal(s.current.value, 'wcofs', 'no ?current=: a rail list with Currents draws the WCOFS forecast (#482)');
  assert.deepEqual(pressed(railItems(m.render(m.h(m.LayerRail)))), ['Seafloor', 'Currents']);
  const legend = m.render(m.h(m.Legend));
  assert.match(legend, /class="app-legend-seafloor"/);
  assert.match(legend, /class="app-legend-currents"/);
  // An explicit choice wins: off stays off, and a named source draws whatever the list says.
  s.syncFromURL(`${ORIGIN}?region=morro-bay&layers=seafloor,currents&current=off`);
  assert.equal(s.current.value, 'off');
  assert.deepEqual(pressed(railItems(m.render(m.h(m.LayerRail)))), ['Seafloor']);
  s.syncFromURL(`${ORIGIN}?region=morro-bay&layers=seafloor&current=hfr-6`);
  assert.equal(s.current.value, 'hfr-6');
  s.syncFromURL(`${ORIGIN}?region=morro-bay&layers=seafloor`);
  assert.equal(s.current.value, 'off', 'a list without Currents draws none');
  // A Fish link is translated before the store reads it (web/fish-links.ts).
  s.syncFromURL(`${ORIGIN}?place=morro&layer=temperature`);
  assert.equal(s.region.value, 'morro-bay');
  assert.deepEqual(s.layers.value, ['water-temp']);
  assert.deepEqual(pressed(railItems(m.render(m.h(m.LayerRail)))), ['Water temp']);
  s.syncFromURL(`${ORIGIN}?place=morro&layer=currents`);
  assert.equal(s.current.value, 'wcofs', 'Fish\'s currents layer opens with Currents drawn');
  // v1 keeps its rule (#402): no ?current= is off.
  s.configureStore({v2: false, storage: null});
  s.syncFromURL(`${ORIGIN}?region=morro-bay&layers=seafloor,currents`);
  assert.equal(s.current.value, 'off');
});

test('switching profile with no ?layers= applies that profile\'s layers, its defaults until chosen (Accept 2)', async () => {
  const m = await load(), s = m.state, store = memory();
  s.configureStore({v2: true, storage: store});
  let href = `${ORIGIN}?region=morro-bay&profile=boat`;
  const go = patch => { href = s.withParams(href, patch); s.syncFromURL(href); return new URL(href).searchParams; };
  go({});
  assert.deepEqual(s.layers.value, m.PROFILE_TABLE.boat.defaultLayers);
  assert.equal(s.current.value, 'wcofs', 'the boat profile\'s default Currents is drawn (#482)');
  // The rail writes ?layers= (and Currents its source); a profile switch drops them with the target.
  go({layers: 'seafloor,currents,clouds', current: 'hfr-6', target: 'vermilion'});
  let params = go(s.profilePatch('shore'));
  assert.deepEqual(['layers', 'current', 'target'].filter(key => params.has(key)), []);
  assert.equal(params.get('profile'), 'shore');
  assert.deepEqual(s.layers.value, m.PROFILE_TABLE.shore.defaultLayers);
  assert.equal(s.current.value, 'off');
  assert.deepEqual(pressed(railItems(m.render(m.h(m.LayerRail)))), ['Water temp', 'Swell']);
  // Each profile keeps its own last list; one never chosen gets its defaults.
  go({layers: 'swell'});
  go(s.profilePatch('boat'));
  assert.deepEqual(s.layers.value, ['seafloor', 'currents', 'clouds']);
  assert.equal(s.current.value, 'wcofs', 'the source is not stored: the list turns on the default');
  go(s.profilePatch('shore'));
  assert.deepEqual(s.layers.value, ['swell']);
  go(s.profilePatch('spear'));
  assert.deepEqual(s.layers.value, m.PROFILE_TABLE.spear.defaultLayers);
  assert.equal(s.current.value, 'off');
  s.configureStore({storage: null});
});

test('the legend shows a colour key only while its layer draws, and says why otherwise (Accept 3)', async t => {
  const m = await load(), s = m.state;
  t.after(() => {
    for (const [signal, value] of reset) signal.value = value;
  });
  const reset = [m.seafloorState, m.currentsState, m.waterTempState, m.swellState, m.cloudStamp, m.currentStatus, m.groundsState, m.aisOn, m.aisState].map(signal => [signal, signal.value]);
  s.configureStore({v2: true, storage: null});
  s.syncFromURL(`${ORIGIN}?region=morro-bay&presentation=chart&layers=seafloor,currents,water-temp,swell,fleet,clouds`);
  m.swellState.value = {...m.swellState.value, drawn: null, reason: 'Swell unavailable: no forecast grid for this region.'};
  m.currentsState.value = {...m.currentsState.value, drawn: null, note: 'loading', reason: 'Loading the surface-current packet.'};
  m.waterTempState.value = {...m.waterTempState.value, drawn: null, reason: 'Water temp unavailable: no analysis for this region.'};
  let html = m.render(m.h(m.Legend));
  assert.deepEqual(swatches(html), ['mpas'], 'nothing draws: only the protected areas\' outline, which the Chart always draws');
  assert.equal(reasons(html)['charter-grounds'], 'Loading charter grounds.', 'FE-21: the grounds say why they do not draw');
  assert.equal(reasons(html).currents, 'Loading the surface-current packet.');
  assert.match(reasons(html)['water-temp'], /^Water temp unavailable/);
  assert.match(reasons(html).swell, /^Swell unavailable/);
  // Each key appears once its layer draws (synthetic states).
  m.seafloorState.value = {status: 'ready', note: '', view: 'terrain', fit: null, surveys: [], credits: [], drawn: 3};
  m.currentsState.value = {...m.currentsState.value, drawn: {}, note: 'forecast Wed 5 am', reason: ''};
  m.waterTempState.value = {...m.waterTempState.value, drawn: {range: [57, 65], product: 'Synthetic analysis', stamp: 'Oct 8'}, reason: ''};
  m.swellState.value = {...m.swellState.value, drawn: {key: 'k', validAt: 0, issuedAt: 0, step: [0.25, 0.25], height: [3, 5], period: [11, 13], from: 290, stamp: 'run Oct 8'}, reason: ''};
  m.cloudStamp.value = {at: '2026-10-08T20:00:00Z', label: 'observed 1:00 pm · 5 min ago', canLoop: false};
  m.groundsState.value = {drawn: 2, note: '', audit: '2026-09-21'};
  m.aisOn.value = true;
  m.aisState.value = {offered: true, drawn: 3, note: '3 historical grid cells · Jul & Sep 2024 · depth unknown'};
  html = m.render(m.h(m.Legend));
  assert.deepEqual(swatches(html), ['seafloor', 'currents', 'currents-fast', 'water-temp', 'swell', 'swell', 'charter-grounds', 'commercial-ais', 'clouds', 'mpas'], 'the swell row\'s key and its scale');
  assert.equal(reasons(html)['charter-grounds'], undefined, 'FE-21: drawn grounds give no reason');
  assert.equal(reasons(html)['commercial-ais'], '3 historical grid cells · Jul &amp; Sep 2024 · depth unknown', 'v1\'s status line (HTML-escaped)');
  // The Charter fleet entry offers v1's commercial AIS layer as an option where the region has it, off by default.
  assert.match(m.render(m.h(m.LayerRail)), /<label class="app-rail-option"><input type="checkbox" checked\/?>Commercial AIS 2024<\/label>/);
  m.aisState.value = {offered: false, drawn: 0, note: ''};
  assert.doesNotMatch(m.render(m.h(m.LayerRail)), /app-rail-option/);
  // In 3D the Chart's layers draw nothing: chart-only rows say so, Currents gives the renderer's status, and
  // the layers the terrain drapes (FE-82: charter grounds, protected areas) keep their keys.
  m.currentStatus.value = 'Surface currents: NOAA WCOFS forecast.';
  s.syncFromURL(`${ORIGIN}?region=morro-bay&presentation=3d&layers=seafloor,currents,water-temp,swell,fleet,clouds`);
  html = m.render(m.h(m.Legend));
  assert.deepEqual(swatches(html), ['seafloor', 'charter-grounds', 'mpas'], 'FE-80: the Seafloor row keys the terrain\'s depth ramp');
  const why = reasons(html);
  for (const id of ['water-temp', 'swell', 'clouds']) assert.equal(why[id], m.CHART_ONLY, id);
  assert.equal(why.seafloor, `Screened candidates: ${m.CHART_ONLY}`, 'the screened candidates still draw on the Chart only');
  assert.equal(why.fleet, undefined, 'the charter grounds drape on the terrain');
  assert.equal(why.currents, 'Surface currents: NOAA WCOFS forecast.');
  assert.match(html, /app-legend-mpa/, 'the protected areas drape on the terrain');
  // Commercial AIS has no drape: its option says so in the terrain and shows no key.
  m.aisState.value = {offered: true, drawn: 3, note: '3 historical grid cells · Jul & Sep 2024 · depth unknown'};
  html = m.render(m.h(m.Legend));
  assert.equal(reasons(html)['commercial-ais'], m.CHART_ONLY);
  assert.deepEqual(swatches(html), ['seafloor', 'charter-grounds', 'mpas']);
  m.aisState.value = {offered: false, drawn: 0, note: ''};
});

test('in Terrain, chart-only entries and the base read "Chart only" and cannot be switched (Accept 4)', async () => {
  const m = await load(), s = m.state;
  for (const id of m.RAIL_IDS) assert.equal(m.drawsIn(id, 'chart'), true, `${id} draws on the Chart`);
  assert.deepEqual(m.RAIL_IDS.filter(id => m.drawsIn(id, '3d')).sort(), ['currents', 'fleet', 'seafloor'],
    'Currents (setCurrentLayer), the charter grounds (FE-82 setOverlay) and the terrain itself (FE-80, the Seafloor entry\'s options) draw in the terrain');
  assert.deepEqual([m.drawsIn('base', 'chart'), m.drawsIn('base', '2d')], [true, false]);
  s.configureStore({v2: true, storage: null});
  s.syncFromURL(`${ORIGIN}?region=morro-bay&presentation=3d&layers=seafloor,water-temp`);
  let html = m.render(m.h(m.LayerRail)), items = railItems(html);
  for (const label of ['Water temp', 'Swell', 'Clouds']) {
    assert.deepEqual([items[label].disabled, items[label].note], [true, m.CHART_ONLY], label);
  }
  assert.deepEqual([items.Seafloor.disabled, items.Seafloor.note], [false, ''], 'FE-80: Seafloor holds the terrain\'s options');
  assert.deepEqual(pressed(items), ['Seafloor', 'Water temp'], 'the choice is kept for the Chart');
  assert.equal(items.Currents.disabled, false);
  assert.deepEqual([items['Charter fleet'].disabled, items['Charter fleet'].note], [false, ''], 'FE-82: no "Chart only" on an entry the terrain drapes');
  assert.match(baseChoice(html), /<select disabled aria-describedby="app-rail-base-note">.*<span id="app-rail-base-note" class="ui-rail-note ui-mono">Chart only<\/span>/s);
  // On the Chart, and wherever the stage falls back to it, every entry can be switched.
  for (const href of [`${ORIGIN}?region=morro-bay&presentation=chart`, `${ORIGIN}?region=santa-cruz-monterey-bay&presentation=3d`]) {
    s.syncFromURL(href);
    html = m.render(m.h(m.LayerRail));
    assert.deepEqual(Object.values(railItems(html)).filter(item => item.disabled), [], href);
    assert.doesNotMatch(html, /Chart only|<select disabled/, href);
  }
});

test('the base choice: Night and Chart detail everywhere, Aerial where offered, the drawn base selected', async () => {
  const m = await load(), s = m.state;
  const offer = {source: 'usgs-naip', first: '2022-05-13', last: '2022-05-29', checkedAt: '2026-10-07', note: 'Synthetic.'};
  assert.deepEqual(m.baseOptions(null).map(o => o.label), ['Night', 'Chart detail']);
  assert.deepEqual(m.baseOptions(offer).map(o => o.value), ['night', 'chart', 'aerial']);
  assert.deepEqual([m.shownBase('aerial', null), m.shownBase('aerial', offer), m.shownBase('chart', null)], ['night', 'aerial', 'chart']);
  assert.deepEqual([m.baseNote('night', null, true), m.baseNote('chart', null, true), m.baseNote('aerial', offer, true), m.baseNote('night', null, false)],
    ['', 'from zoom 10', 'flown 13–29 May 2022', m.CHART_ONLY]);
  s.configureStore({v2: true, storage: null});
  s.syncFromURL(`${ORIGIN}?region=morro-bay&presentation=chart&base=chart`);
  const html = baseChoice(m.render(m.h(m.LayerRail)));
  assert.match(html, /<label class="app-rail-source">Base<select aria-describedby="app-rail-base-note"><option value="night">Night<\/option><option selected value="chart">Chart detail<\/option><\/select><\/label>/);
  assert.match(html, /<summary class="ui-popover-summary ui-eyebrow" aria-label="Base basis">/);
  assert.match(html, /Chart detail: NOAA electronic navigational chart display service, drawn from zoom 10; for planning, never for navigation\./);
  assert.match(html, /class="ui-rail-note ui-mono">from zoom 10</);
});

test('FE-80: in 2D and 3D the Seafloor entry holds the terrain\'s options with labelled controls; the Chart shows none', async () => {
  const m = await load(), s = m.state;
  s.configureStore({v2: true, storage: null});
  s.syncFromURL(`${ORIGIN}?region=morro-bay&presentation=2d&layers=seafloor`);
  m.terrainOptions.value = m.TERRAIN_DEFAULTS;
  let html = m.render(m.h(m.LayerRail));
  const terrain = html.match(/<details class="app-rail-options app-rail-terrain"><summary class="app-rail-option">Terrain options<\/summary>.*?<\/details>/s)[0];
  assert.match(terrain, /<label for="terrain-relief">Seabed relief <b class="ui-mono">×5<\/b><\/label><input id="terrain-relief" type="range" min="1" max="12" step="1" value="5" aria-valuetext="×5"/);
  assert.match(terrain, /<label for="terrain-water">Water opacity <b class="ui-mono">50%<\/b>/);
  assert.match(terrain, /Illustrative \+0\.8 m water surface\. Not a live tide\./, 'the native note, verbatim');
  const boxes = [...terrain.matchAll(/<label class="app-rail-option"><input type="checkbox"([^>]*)\/?>([^<]+)<\/label>/g)].map(x => [x[2], /checked/.test(x[1]), /disabled/.test(x[1])]);
  assert.deepEqual(boxes, [['Water &amp; channels', true, false], ['Depth contours · 10 / 30 / 500 ft', true, false], ['Source coverage', false, false], ['Reefs &amp; species pins', true, false]]);
  s.syncFromURL(`${ORIGIN}?region=morro-bay&presentation=3d&layers=currents`);
  html = m.render(m.h(m.LayerRail));
  assert.match(html, /<input type="checkbox" disabled\/?>Reefs &amp; species pins/, 'with Seafloor off the reefs and pins are off and fixed');
  s.syncFromURL(`${ORIGIN}?region=morro-bay&presentation=chart&layers=seafloor`);
  assert.doesNotMatch(m.render(m.h(m.LayerRail)), /app-rail-terrain/);
});
