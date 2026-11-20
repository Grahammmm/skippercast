import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import {build} from 'esbuild';
import {preparedRendererPlugins} from './helpers/esbuild-url.mjs';

const root = new URL('../', import.meta.url);
const {outputFiles: [out]} = await build({stdin: {resolveDir: root.pathname, loader: 'ts', contents: `
    export {signal} from '@preact/signals';
    export {h} from 'preact';
    export {render} from 'preact-render-to-string';
    export {DepthContoursRow, Legend} from './web/app/Legend.tsx';
    export {reliefDrawn, reliefFeatures, reliefLook, reliefSurveyView} from './web/app/MapStage.tsx';
    export {reliefLook as pointerLook} from './web/map/relief-data.ts';
    export {NEARSHORE_STYLE_DIGESTS} from './web/map/nearshore-style.gen.ts';
    export {createDepthContours, contourState, depthContoursURL} from './web/map/depth-contours.ts';
    export {camera} from './web/map/stage.ts';
    export {publishedChartFiles} from './web/chart-files.ts';
    export {language, prepareCatalogue, t} from './web/i18n.ts';
    export {configureStore, region, syncFromURL} from './web/state.ts';`},
  bundle: true, write: false, format: 'esm', platform: 'node', jsx: 'automatic', jsxImportSource: 'preact', plugins: preparedRendererPlugins});
const m = await import(`data:text/javascript;base64,${Buffer.from(out.contents).toString('base64')}`);

// The rendered row follows the validated file, not a region default.
// A missing state projection or stale v1 legend would mislabel the ft-v2 full file.
test('contour legend follows the loaded set in English and Spanish', async () => {
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

// Check the actual UI wiring: a hard-coded list would not follow a viewport
// change; an unavailable input must not render a "no survey" claim.
test('the Chart legend keys only the verified classes in view', () => {
  m.configureStore({v2: true, storage: null});
  m.syncFromURL('https://s.test/map?region=morro-bay&presentation=chart');
  m.reliefDrawn.value = true;
  m.reliefLook.value = 'deep-fixed-v1';
  const render = () => m.render(m.h(m.Legend));
  const bold = html => [...html.matchAll(/data-survey-chip="([^"]+)"[^>]*><span[^>]*><\/span><strong>/g)].map(match => match[1]);
  try {
    assert.doesNotMatch(render(), /app-relief-survey/);
    for (const lang of ['en', 'es']) {
      m.language.value = lang;
      m.reliefSurveyView.value = {classes: new Set(['2m', 'none']), shown: false, toggle() {}};
      let html = render();
      assert.deepEqual(bold(html), ['2m', 'none']);
      assert.match(html, /aria-pressed="false"/);
      assert.equal([...html.matchAll(/class="app-relief-depth-swatch"/g)].length, 12, 'eleven depths and the shallow band');
      assert.match(html, /300\+<\/li>/);
      assert.match(html, /0–66 ft \(0–20 m\)/);
      assert.ok(html.includes(m.t('legend.notForNav', lang)));
      m.reliefSurveyView.value = {classes: new Set(['estimated']), shown: true, toggle() {}};
      html = render();
      assert.deepEqual(bold(html), ['estimated']);
      assert.match(html, /aria-pressed="true"/);
    }
  } finally {
    m.reliefDrawn.value = false;
    m.reliefLook.value = null;
    m.reliefSurveyView.value = null;
    m.language.value = 'en';
  }
});

const morro = 'morro-bay', cambria = 'cambria-san-simeon';
const kitStyle = {baked: m.NEARSHORE_STYLE_DIGESTS.baked, contours: null, habitat: null, built_with: 'nearshore-v1.0.0'};
const legendHTML = () => m.render(m.h(m.Legend));
const depthChips = html => [...html.matchAll(/data-depth-chip="([^"]+)"[^>]*><span[^>]*><\/span>(\d+\+?)<\/li>/g)];
const chartRegion = id => m.syncFromURL(`https://s.test/map?region=${id}&presentation=chart`);

function drawnRelief(t) {
  m.configureStore({v2: true, storage: null});
  chartRegion(morro);
  m.reliefDrawn.value = true;
  t.after(() => {
    m.reliefDrawn.value = false;
    m.reliefLook.value = null;
    m.reliefFeatures.value = {};
    m.language.value = 'en';
  });
}

// A3: only the active region's deployed pointer keys its chips. A global default or cached
// previous-region look would show the same ramp in both regions, or survive a file restore.
test('MSK-2: rendered ramp follows the region pointer and only the restored region switches back', t => {
  drawnRelief(t);
  const prior = {region: morro};
  const files = new Map([[morro, {region: morro, style: kitStyle, previous: prior}], [cambria, {region: cambria}]]);
  const chipsFor = (id, prefix, count) => {
    chartRegion(id);
    // Supply the same look key the loader passes to the reliefDrawn/reliefLook signals.
    m.reliefLook.value = m.pointerLook(files.get(m.region.value));
    const html = legendHTML(), chips = depthChips(html);
    assert.doesNotMatch(html, /data-depth-key="unavailable"/);
    assert.equal(chips.length, count, id);
    assert.ok(chips.every(([, cssVar]) => cssVar.startsWith(prefix)), id);
    return chips.map(([, , depth]) => depth);
  };
  assert.deepEqual(chipsFor(morro, '--skn-depth-ns-', 14), ['0', '10', '20', '30', '45', '60', '80', '100', '130', '160', '200', '250', '300', '300+']);
  const unchanged = chipsFor(cambria, '--depth-b-', 11);
  files.set(morro, prior);
  assert.deepEqual(chipsFor(morro, '--depth-b-', 11), unchanged);
  assert.deepEqual(chipsFor(cambria, '--depth-b-', 11), unchanged);
});

// A3: a valid unknown digest and a malformed member both hide the colour key, not the relief.
// Falling back to legacy, suppressing the whole row, or shipping English-only copy breaks this.
test('MSK-2: unknown or invalid look keeps the relief row but renders only the localized unavailable key', async t => {
  drawnRelief(t);
  await m.prepareCatalogue('es');
  const {contours: _contours, ...missingContours} = kitStyle;
  for (const style of [{...kitStyle, baked: 'e'.repeat(64)}, missingContours, {...kitStyle, built_with: {relief: kitStyle.built_with}}]) {
    m.reliefLook.value = m.pointerLook({style});
    for (const [lang, message] of [
      ['en', 'Depth colour key unavailable for this map version'],
      ['es', 'Clave de colores de profundidad no disponible para esta versión del mapa'],
    ]) {
      m.language.value = lang;
      const html = legendHTML();
      assert.match(html, /class="app-legend-relief"/);
      assert.deepEqual([...html.matchAll(/data-depth-key="unavailable">([^<]+)</g)].map(([, text]) => text), [message]);
      assert.doesNotMatch(html, /data-depth-chip|app-relief-depths|app-relief-depth-swatch/);
    }
  }
});

// A3: feature rows are independent evidence claims. Rendering every row (or merging both pile
// flags) would claim evidence the region does not have; hard-coded text could drop {cell}/{year}.
test('MSK-2: the legend renders each nearshore row only for its own data flag', async t => {
  drawnRelief(t);
  await m.prepareCatalogue('es');
  m.reliefLook.value = m.pointerLook({style: kitStyle});
  const rows = html => [...html.matchAll(/data-nearshore-row="legend\.relief\.([^"]+)"[^>]*>(?:<span[^>]*><\/span>)?([^<]+)</g)]
    .map(([, id, text]) => [id, text]);
  for (const [flags, id, en, es] of [
    [{pilesSurveyed: true}, 'pileSurveyed', 'Rock pile (surveyed rock)', 'Pila de roca (roca del levantamiento)'],
    [{pilesFromRelief: true}, 'pileRelief', 'Rock pile (from relief, no substrate survey)', 'Pila de roca (del relieve, sin levantamiento del sustrato)'],
    [{hardEdge: {cell_m: 5, year: 2024}}, 'hardEdge', 'Hard-bottom edge: USGS seafloor character, 5 m, 2024', 'Borde de fondo duro: carácter del fondo marino del USGS, 5 m, 2024'],
    [{resolution_m: 2}, 'resolution', 'Survey resolution 2 m: finer detail not available here', 'Resolución del levantamiento 2 m: aquí no hay más detalle'],
  ]) {
    for (const [lang, text] of [['en', en], ['es', es]]) {
      m.language.value = lang;
      m.reliefFeatures.value = flags;
      assert.deepEqual(rows(legendHTML()), [[id, text]]);
      m.reliefFeatures.value = {};
      assert.doesNotMatch(legendHTML(), /data-nearshore-row=/);
    }
  }
});
