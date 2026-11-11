// RF1925-2: when the Chart cannot start, the map says so in the reader's language, offers Try again (a reload of the
// current page), and drops the controls that can draw nothing. Real Preact renders of the real components and signals;
// no browser here (e2e/v2-map.spec.ts runs the real reload and the layout).
import assert from 'node:assert/strict';
import util from 'node:util';
import test from 'node:test';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {preparedRendererPlugins} from './helpers/esbuild-url.mjs';

const root = new URL('..', import.meta.url).pathname;
const ORIGIN = 'https://s.test/map';
const now = new Date('2026-10-05T20:00:00Z');
let app;
async function load() {
  if (app) return app;
  const outfile = join(await mkdtemp(join(tmpdir(), 'map-unavailable-')), 'app.mjs');
  await build({stdin: {resolveDir: root, loader: 'ts', contents: `
    export {MapStage, MapUnavailable, mapUnavailable} from './web/app/MapStage.tsx';
    export {Desktop} from './web/app/Desktop.tsx';
    export {LayerRail} from './web/app/LayerRail.tsx';
    export {RailItem} from './web/ui/Rail.tsx';
    export {LayersPanel, Mobile, SheetBrief} from './web/app/Mobile.tsx';
    export {chartFailed, chartMark} from './web/map/chart.ts';
    export {terrainFailed} from './web/map/stage.ts';
    export {poster} from './web/map/poster.ts';
    export {language} from './web/i18n.ts';
    export * as state from './web/state.ts';
    export {h} from 'preact';
    export {render} from 'preact-render-to-string';`},
  outfile, bundle: true, format: 'esm', platform: 'node', jsx: 'automatic', jsxImportSource: 'preact', plugins: preparedRendererPlugins, logLevel: 'silent'});
  app = await import(pathToFileURL(outfile).href);
  return app;
}
async function setup(query = '', {failed = true} = {}) {
  const a = await load();
  a.state.configureStore({v2: true, storage: null});
  a.state.syncFromURL(`${ORIGIN}?region=morro-bay${query}`);
  a.language.value = 'en';
  a.chartFailed.value = failed; a.terrainFailed.value = false; a.chartMark.value = null;
  return a;
}
const count = (html, re) => (html.match(re) || []).length;
const EN = /This browser could not start the map graphics\. Graphics support may be unavailable or temporarily blocked\. Trying again reloads this page\. Forecasts and trip tools remain available\./;
const ES = /Este navegador no pudo iniciar los gráficos del mapa\. Es posible que los gráficos no estén disponibles o estén bloqueados temporalmente\. Al intentarlo de nuevo se recarga esta página\. Los pronósticos y las herramientas de viaje siguen disponibles\./;
const MARK = {id: 'shore:1', name: 'Shoreline', kind: 'Shoreline', reading: '', source: 'NOAA NGS CUSP', basis: 'Lidar', copy: {}};

test('graphics_notice_en_es: a failed Chart explains itself once, in each language, with one Try again button and no map-only chrome', async () => {
  const a = await setup();
  a.poster.value = {region: 'morro-bay', width: 10, height: 10, path: 'M0 0'};
  try {
    for (const [lang, text, heading, retry] of [['en', EN, 'Map unavailable.', 'Try again'], ['es', ES, 'Mapa no disponible.', 'Intentar de nuevo'], ['en', EN, 'Map unavailable.', 'Try again']]) {
      a.language.value = lang;
      const html = a.render(a.h(a.MapStage, {}));
      assert.match(html, text);
      assert.ok(html.includes(`<strong>${heading}</strong>`), `${lang} heading`);
      assert.equal(count(html, /<button\b/g), 1, 'exactly one button');
      assert.match(html, new RegExp(`<button[^>]*type="button"[^>]*>${retry}</button>`));
      assert.equal(count(html, /role="status"/g), 1, 'one polite status region');
      assert.equal(count(html, /app-stage-failed/g), 1, 'no duplicate notice');
      assert.doesNotMatch(html, /app-poster|app-presentation|app-terrain-controls|Failed to initialize/, 'no poster, presentation or terrain chrome, no raw error');
    }
  } finally { a.poster.value = null; }
});

test('retry_reloads_current_address_once: the rendered button calls location.reload() once and changes nothing else', async t => {
  const a = await setup('&target=halibut&layers=swell#x');
  const calls = [];
  const had = Object.getOwnPropertyDescriptor(globalThis, 'location');
  const loc = {href: `${ORIGIN}?region=morro-bay&target=halibut&layers=swell#x`, reload: () => calls.push('reload'), assign: () => calls.push('assign'), replace: () => calls.push('replace')};
  Object.defineProperty(globalThis, 'location', {value: loc, configurable: true, writable: true});
  const pushed = [];
  globalThis.history = {pushState: () => pushed.push('push'), replaceState: () => pushed.push('replace')};
  globalThis.localStorage = {setItem: () => pushed.push('storage'), removeItem: () => pushed.push('storage'), clear: () => pushed.push('storage'), getItem: () => null};
  t.after(() => { if (had) Object.defineProperty(globalThis, 'location', had); else delete globalThis.location; delete globalThis.history; delete globalThis.localStorage; });
  const find = (node, pick) => {
    if (!node || typeof node !== 'object') return null;
    if (pick(node)) return node;
    for (const child of [].concat(node.props?.children ?? [])) { const hit = find(child, pick); if (hit) return hit; }
    return null;
  };
  const button = find(a.MapUnavailable(), n => typeof n.props?.onClick === 'function');
  assert.ok(button, 'the notice holds the retry handler');
  button.props.onClick();
  assert.deepEqual(calls, ['reload'], 'one reload, no assign or replace');
  assert.deepEqual(pushed, [], 'no history or storage mutation');
  assert.equal(loc.href, `${ORIGIN}?region=morro-bay&target=halibut&layers=swell#x`, 'the complete address is kept');
  assert.equal(a.chartFailed.value, true, 'no in-place reset: the page reloads');
});

test('desktop_failure_preserves_tools: no legend or mark card, the rail stays but disabled; brief, time dock, Conditions and History stay', async () => {
  const a = await setup('&layers=swell,clouds');
  a.chartMark.value = MARK;
  try {
    const home = a.render(a.h(a.Desktop, {now}));
    assert.doesNotMatch(home, /app-chrome-left|class="app-mark"/, 'no legend or mark card');
    assert.match(home, /app-rail/, 'the layer rail stays (SC1922-07), its buttons disabled');
    assert.match(home, /aria-label="Brief"/);
    assert.match(home, /class="app-dock"/);
    assert.match(home, EN);
    a.state.syncFromURL(`${ORIGIN}?region=morro-bay&layers=swell,clouds&view=conditions`);
    const conditions = a.render(a.h(a.Desktop, {now}));
    assert.match(conditions, /class="app-dock"/);
    assert.match(conditions, /app-conditions|Conditions/, 'Conditions content remains');
    a.state.syncFromURL(`${ORIGIN}?region=morro-bay&layers=swell,clouds&view=history`);
    assert.match(a.render(a.h(a.Desktop, {now})), /class="app-dock"/);
    a.state.syncFromURL(`${ORIGIN}?region=morro-bay&layers=swell,clouds`);
    a.chartFailed.value = false;
    const ok = a.render(a.h(a.Desktop, {now}));
    assert.match(ok, /app-rail/, 'ordinary map chrome returns');
    assert.match(ok, /class="app-mark"/, 'with the mark card');
    assert.doesNotMatch(ok, /app-stage-failed/);
  } finally { a.chartMark.value = null; }
});

test('phone_failure_while_layers_open: the Layers trigger and panel stay with disabled buttons, no mark-card substitution; the other tools stay', async () => {
  const a = await setup('&layers=swell');
  a.chartMark.value = MARK;
  try {
    const failed = a.render(a.h(a.Mobile, {now}));
    assert.match(failed, /aria-label="Layers"/, 'the layers trigger stays');
    assert.doesNotMatch(failed, /app-sheet--mark/, 'no mark class');
    assert.doesNotMatch(failed, /class="app-mark"/, 'no mark card');
    assert.match(failed, EN);
    assert.match(failed, /aria-label="Time"/, 'the hour control stays');
    assert.match(failed, /app-tabs/, 'tabs stay');
    const panel = a.render(a.h(a.LayersPanel, {onClose() {}}));
    assert.match(panel, /app-rail/, 'the panel shows the rail');
    assert.ok(toggles(panel).length > 0 && toggles(panel).every(b => /aria-disabled="true"/.test(b)), 'no live toggle');
    a.chartFailed.value = false;
    const ok = a.render(a.h(a.Mobile, {now}));
    assert.match(ok, /aria-label="Layers"/);
    assert.match(ok, /app-sheet--mark/);
    assert.match(ok, /class="app-mark"/);
    assert.match(a.render(a.h(a.LayersPanel, {onClose() {}})), /app-rail/);
    assert.doesNotMatch(ok, /app-stage-failed/);
  } finally { a.chartMark.value = null; }
});

test('no_false_whole_map_failure: only a failed Chart that is the shown presentation counts', async () => {
  const a = await setup('', {failed: false});
  const stage = () => a.render(a.h(a.MapStage, {}));
  assert.equal(a.mapUnavailable.value, false);
  assert.match(stage(), /app-presentation/, 'a working Chart keeps its controls');
  assert.doesNotMatch(stage(), /app-stage-failed/);
  a.chartFailed.value = true;
  a.state.syncFromURL(`${ORIGIN}?region=morro-bay&presentation=2d`);
  assert.equal(a.mapUnavailable.value, false, 'a Chart failure does not fail a shown 2D terrain');
  assert.match(stage(), /app-presentation/);
  assert.doesNotMatch(stage(), /app-stage-failed/);
  assert.match(a.render(a.h(a.Mobile, {now})), /aria-label="Layers"/);
  a.terrainFailed.value = true;
  assert.equal(a.mapUnavailable.value, true, 'terrain that failed too leaves Chart shown and failed');
  a.terrainFailed.value = false; a.chartFailed.value = false;
});

const toggles = html => [...html.matchAll(/<button([^>]*ui-rail-toggle[^>]*)>/g)].map(m => m[1]);
const find = (node, pick, out = []) => {
  if (!node || typeof node !== 'object') return out;
  if (pick(node)) out.push(node);
  for (const child of [].concat(node.props?.children ?? [])) find(child, pick, out);
  return out;
};

test('layer_buttons_disabled_keep_choice_en_es: every Chart layer button is aria-disabled with the reason, presses change nothing, healthy Chart unchanged', async () => {
  const a = await setup('&layers=swell,clouds');
  const before = a.state.layers.value.slice(), search = a.state.current.value;
  try {
    for (const [lang, reason] of [['en', 'Map could not start on this device or browser.'], ['es', 'El mapa no pudo iniciarse en este dispositivo o navegador.']]) {
      a.language.value = lang;
      const html = a.render(a.h(a.LayerRail, {}));
      const btns = toggles(html);
      assert.ok(btns.length >= 6, 'the rail entries render');
      for (const b of btns) assert.match(b, /aria-disabled="true"/, 'disabled');
      assert.equal(count(html, new RegExp(reason.replace(/\./g, '\\.'), 'g')), btns.length, 'each button names the reason');
      assert.match(html, /aria-pressed="true"/, 'chosen state kept');
      assert.doesNotMatch(html, /app-rail-option/, 'no live option under a disabled layer');
    }
    // A press: the real RailItem of every entry ignores it.
    const items = find(a.LayerRail(), n => n.type === a.RailItem);
    assert.ok(items.length >= 6);
    const calls = [];
    for (const it of items) {
      assert.equal(it.props.disabled, true);
      const btn = a.RailItem({...it.props, onToggle: (...x) => calls.push(x)});
      find(btn, n => typeof n.props?.onClick === 'function').forEach(n => n.props.onClick());
    }
    assert.deepEqual(calls, [], 'no press reaches a layer');
    assert.ok(util.isDeepStrictEqual(a.state.layers.value, before), 'layers kept');
    assert.equal(a.state.current.value, search);
    // Failure clears: buttons live again, same selection.
    a.chartFailed.value = false;
    const ok = a.render(a.h(a.LayerRail, {}));
    assert.ok(toggles(ok).every(b => !/aria-disabled/.test(b)), 'healthy: nothing disabled');
    assert.ok(util.isDeepStrictEqual(a.state.layers.value, before));
    // A working 2D terrain: only the Chart-only entries are disabled, with the old reason.
    a.chartFailed.value = true;
    a.state.syncFromURL(`${ORIGIN}?region=morro-bay&presentation=2d`);
    const terrain = a.render(a.h(a.LayerRail, {}));
    assert.doesNotMatch(terrain, /Map could not start/);
  } finally { a.chartFailed.value = false; }
});
