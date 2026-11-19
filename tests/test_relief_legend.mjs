import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import {build} from 'esbuild';
import {preparedRendererPlugins} from './helpers/esbuild-url.mjs';

// Contract: the rendered row follows the validated file, not a region default.
// A missing state projection or stale v1 legend would mislabel the ft-v2 full file.
test('contour legend follows the loaded set in English and Spanish', async () => {
  const root = new URL('../', import.meta.url);
  const {outputFiles: [out]} = await build({stdin: {resolveDir: root.pathname, loader: 'ts', contents: `
    export {signal} from '@preact/signals';
    export {h} from 'preact';
    export {render} from 'preact-render-to-string';
    export {DepthContoursRow} from './web/app/Legend.tsx';
    export {createDepthContours, contourState, depthContoursURL} from './web/map/depth-contours.ts';
    export {camera} from './web/map/stage.ts';
    export {publishedChartFiles} from './web/chart-files.ts';
    export {language, t} from './web/i18n.ts';
    export {configureStore, syncFromURL} from './web/state.ts';`},
  bundle: true, write: false, format: 'esm', platform: 'node', jsx: 'automatic', jsxImportSource: 'preact', plugins: preparedRendererPlugins});
  const m = await import(`data:text/javascript;base64,${Buffer.from(out.contents).toString('base64')}`);
  const v1 = JSON.parse(await readFile(new URL('dist/regions/morro-bay/depth-contours-overview.geojson', root), 'utf8'));
  const v2 = {type: 'FeatureCollection', provenance: {
    region_id: 'morro-bay', units: 'ft', set: 'ft-v2', shelf_limit_ft: 300,
    index_depths_ft: [60, 150, 300], intervals: [
      {minzoom: 8, depths_ft: [60, 120, 180, 240, 300]},
      {minzoom: 11, depths_ft: [30, 90, 150, 210, 270]},
      {minzoom: 13, depths_ft: [10, 20, 40, 50, 70, 80, 100]},
      {minzoom: 15, depths_ft: [5, 15, 25], native_max_cell_m: 2},
    ],
    sources: [{source_id: 'synthetic', name: 'Fixture survey', survey_date: '2025', vertical_datum: 'NAVD88'}],
    sources_omitted: [], review_expires: '2027-10-20',
  }, features: [{type: 'Feature', geometry: {type: 'LineString', coordinates: [[-121, 35.3], [-120.95, 35.3]]},
    properties: {kind: 'contour', source_id: 'synthetic', survey_date: '2025', vertical_datum: 'NAVD88', depth_ft: 60, minzoom: 8, index: true, estimated: true}}]};
  const page = () => 'https://s.test/map?region=morro-bay&presentation=chart';
  m.configureStore({v2: true, storage: null});
  m.syncFromURL(page());
  m.publishedChartFiles.value = {region: 'morro-bay', files: ['depth-contours-overview.geojson', 'depth-contours.geojson']};
  m.camera.value = {longitude: -120.95, latitude: 35.35, zoom: 11};
  const layer = m.createDepthContours({page, now: () => Date.parse('2026-10-20T12:00:00Z'),
    engine: m.signal({setData() {}, setOverlay() {}}), palette: () => ({mapContourWidth: '1'}),
    fetchFn: async url => Response.json(new URL(url).pathname === `/${m.depthContoursURL('morro-bay')}` ? v2 : v1)});
  const flush = () => new Promise(resolve => setImmediate(resolve));
  const row = lang => { m.language.value = lang; return m.render(m.h(m.DepthContoursRow)); };
  try {
    await flush();
    assert.equal(m.contourState.value.status, 'drawn');
    for (const lang of ['en', 'es']) {
      const html = row(lang);
      assert.ok(html.includes(m.t('layer.depth-contours.basis', lang)));
      assert.ok(html.includes(m.t('layer.depth-contours.legend0', lang)));
    }
    m.camera.value = {...m.camera.value, zoom: 14};
    await flush();
    for (const lang of ['en', 'es']) {
      const html = row(lang);
      assert.match(html, lang === 'es' ? /hasta 300 ft, estimadas/ : /to 300 ft, estimated/);
      assert.match(html, lang === 'es' ? /60, 150 y 300 ft/ : /60, 150 and 300 ft/);
      assert.match(html, lang === 'es' ? /más juntas al ampliar el mapa/ : /closer as you zoom in/);
      assert.match(html, /2025 · NAVD88/);
      assert.ok(html.includes(m.t('legend.notForNav', lang)));
      assert.doesNotMatch(html, /600 ft|Fixture survey/);
      assert.doesNotMatch(m.t('planner.layer.contours.text', lang), /\b150\b/);
    }
  } finally { layer.destroy(); }
});
