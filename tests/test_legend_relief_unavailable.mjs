// M41: the Chart's depth-shading overlay (web/map/layers.ts BOTTOM_RELIEF) is not a layer-registry entry, yet
// web/app/MapStage.tsx names it unavailable when its drawn tiles fail. The legend named every unavailable id through
// layerCopy, which throws on an id the registry does not hold, so one failed relief tile replaced the whole legend
// (every layer row, the depth key and the presets) with "This part could not load". The legend now names it by its
// rail name, "Depth shading", and every registry id keeps its own label; an unknown id still throws.
// Offline: the .tsx legend is bundled with esbuild so the legend, the Chart signals and the catalogue share one graph.
import assert from 'node:assert/strict';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';

const ROOT = new URL('..', import.meta.url).pathname;
const PAGE = 'https://s.test/map';

let ui;
async function components() {
  if (ui) return ui;
  const out = join(await mkdtemp(join(tmpdir(), 'legend-relief-')), 'legend-relief.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {Legend, unavailableLabel} from './web/app/Legend.tsx';
      export {unavailable} from './web/map/chart.ts';
      export {BOTTOM_RELIEF, layerCopy} from './web/map/layers.ts';
      export * as state from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins,
  });
  return (ui = await import(pathToFileURL(out).href));
}

async function open(region = 'morro-bay') {
  const m = await components(), href = `${PAGE}?region=${region}&presentation=chart`;
  globalThis.location = {href};
  globalThis.history = {state: null, pushState(_s, _t, url) { location.href = url; }, replaceState(_s, _t, url) { location.href = url; }};
  globalThis.dispatchEvent = () => true;
  m.state.configureStore({v2: true, storage: null});
  m.state.syncFromURL(href);
  return m;
}

test('an unavailable depth-shading overlay is named by its rail name, in English and Spanish', async () => {
  const m = await open();
  assert.equal(m.unavailableLabel(m.BOTTOM_RELIEF, 'en'), 'Depth shading');
  assert.equal(typeof m.unavailableLabel(m.BOTTOM_RELIEF, 'es'), 'string');
  assert.ok(m.unavailableLabel(m.BOTTOM_RELIEF, 'es').length > 0);
});

test('registry layers keep their own label and an unknown id still throws', async () => {
  const m = await open();
  for (const id of ['coastline', 'basemap', 'mpas', 'depth-contours']) {
    assert.equal(m.unavailableLabel(id, 'en'), m.layerCopy(id, 'en').label, id);
  }
  assert.throws(() => m.unavailableLabel('no-such-layer', 'en'), /Unknown map layer no-such-layer/);
});

test('the legend still renders, with one depth-shading row, when the relief overlay fails beside another layer', async () => {
  const m = await open();
  m.unavailable.value = [m.BOTTOM_RELIEF, 'coastline'];
  try {
    const html = m.render(m.h(m.Legend, {}));
    assert.match(html, /<p class="app-empty" data-unavailable="bottom-relief">Depth shading unavailable\.<\/p>/);
    assert.match(html, new RegExp(`data-unavailable="coastline">${m.layerCopy('coastline', 'en').label} unavailable\\.</p>`));
    assert.match(html, /app-legend-warning/, 'the rest of the legend draws');
  } finally {
    m.unavailable.value = [];
  }
});
