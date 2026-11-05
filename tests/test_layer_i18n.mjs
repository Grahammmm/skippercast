// SC0707-09: the layer rail and legend in Spanish. The registry's labels, basis sentences and legend rows, the rail's
// labels and Chart-only reasons, and the legend's fixed chrome come from the catalogue; every caveat a basis sentence
// carries survives in the Spanish; producer-written runtime text stays whole, escaped and labelled English; English
// output is unchanged. LayerRail.tsx and Legend.tsx are bundled with esbuild; nothing is fetched.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp} from 'node:fs/promises';
import {readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';

const ROOT = new URL('..', import.meta.url).pathname;
const ORIGIN = 'https://s.test/map';
const CATALOGUE = JSON.parse(readFileSync(join(ROOT, 'catalog/app/strings.json'), 'utf8')).strings;

let bundle;
async function load() {
  if (bundle) return bundle;
  const out = join(await mkdtemp(join(tmpdir(), 'layer-i18n-')), 'bundle.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {LayerRail, baseNote, baseOptions} from './web/app/LayerRail.tsx';
      export {Legend, MpaRow, researchDate} from './web/app/Legend.tsx';
      export {RAIL_ENTRIES, railEntries} from './web/app/rail.ts';
      export {LAYERS, CHART_ONLY, chartOnly, layerCopy, layerEntry} from './web/map/layers.ts';
      export {STATION_BASIS} from './web/map/station-model.ts';
      export {language} from './web/i18n.ts';
      export {mpaState, TRANSIENT_DETAILS} from './web/map/mpa.ts';
      export {waterTempState} from './web/map/sst.ts';
      export {groundsState} from './web/map/charter-grounds.ts';
      export {aisOn, aisState, AIS_CREDIT} from './web/map/commercial-ais.ts';
      export {terrainCoarsened} from './web/map/stage.ts';
      export * as state from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: rendererPlugins,
  });
  bundle = await import(pathToFileURL(out).href);
  return bundle;
}
const rail = (m, lang) => { m.language.value = lang; return m.render(m.h(m.LayerRail)); };
const legend = (m, lang) => { m.language.value = lang; return m.render(m.h(m.Legend)); };
const placeholders = text => [...text.matchAll(/\{(\w+)\}/g)].map(x => x[1]).sort().join(',');

// The caveats each basis sentence carries, sentence by sentence: the Spanish must keep every one (the PR lists them).
const CAVEATS = {
  basemap: [/OpenStreetMap/, /cada trimestre/],
  chart: [/nunca para navegar/, /zoom 10/],
  relief: [/hash/],
  'water-temp': [/72 horas/, /Solo agua superficial/, /ni un pronóstico/],
  'sst-contrast': [/72 horas/, /Solo agua superficial/, /no indica un pez ni un lugar de captura/],
  'sst-fronts': [/72 horas/, /Solo agua superficial/, /no un pez ni un lugar de captura/],
  chlorophyll: [/0\.0375°/, /No indica carnada ni peces/, /vacíos por nubes quedan vacíos/],
  swell: [/36 horas/, /no observaciones de boyas/],
  wind: [/no son observaciones/, /36 horas/, /6 horas/],
  'depth-contours': [/ni sirven para navegar/, /MLLW/, /sin verificar/, /un año después/],
  mpas: [/no como delimitación legal/, /ds582/],
  'shore-runs': [/El orden no establece permiso legal/, /contexto histórico/, /se ocultan cuando vence/],
  seafloor: [/35 días/, /comprobación legal/],
  'charter-grounds': [/no posiciones de pesca confirmadas por AIS/, /lingcod y rockfish/, /no límites chárter publicados/],
  'commercial-ais': [/muestra fechada/, /ni una fuente en vivo/, /0\.01°/, /0\.9 × 1\.1 km/, /no es prueba de pesca ni de capturas/],
  'fleet-heat': [/Inferido del movimiento/],
  currents: [/ilustrativo/, /6 horas/],
  clouds: [/nunca un pronóstico/, /90 minutos/],
  reach: [/no indica el estado del mar, la barra ni el combustible/, /ruta real es más larga/],
  'trip-ranked': [/comprobación de áreas protegidas/],
  'saved-spots': [/solo para ti/, /no permiso para pescar/],
  stations: [/no son boyas de observación/, /desactualizadas/, /nunca se muestra en otro punto/],
};

test('layer_copy_all_ids_and_english_metadata', async () => {
  const m = await load();
  for (const e of m.LAYERS) {
    const en = m.layerCopy(e.id), es = m.layerCopy(e.id, 'es');
    assert.deepEqual(en, {label: e.label, basis: e.basis, legend: e.legend}, `${e.id}: English is the compatibility registry`);
    assert.ok(es.label && es.basis, `${e.id}: Spanish label and basis`);
    assert.notEqual(es.basis, e.basis, `${e.id}: the basis is translated`);
    assert.equal(es.legend.length, e.legend.length, `${e.id}: legend rows`);
    es.legend.forEach((row, i) => { assert.equal(row.swatch, e.legend[i].swatch, `${e.id}: swatch ${i} kept`); assert.ok(row.label); });
    assert.notEqual(es.basis, e.label);
  }
  assert.throws(() => m.layerCopy('nope'), /Unknown map layer nope/);
  assert.throws(() => m.layerCopy('nope', 'es'), /Unknown map layer nope/);
  assert.equal(m.layerCopy('stations').basis, m.STATION_BASIS, 'the catalogue holds the station sentence byte for byte');
  assert.equal(m.CHART_ONLY, 'Chart only');
  assert.equal(m.chartOnly('es'), 'Solo en la Carta');
  assert.deepEqual(m.railEntries(), m.RAIL_ENTRIES);
  assert.deepEqual(m.railEntries('es').map(e => e.id), m.RAIL_ENTRIES.map(e => e.id), 'order and ids never depend on the language');
  assert.deepEqual(m.railEntries('es').map(e => e.label), ['Fondo marino', 'Corrientes', 'Temperatura del agua', 'Contraste de temperatura', 'Frentes de temperatura', 'Clorofila', 'Oleaje y viento', 'Estaciones', 'Flota chárter', 'Nubes']);
  const swell = m.railEntries('es').find(e => e.id === 'swell').basis;
  assert.equal(swell, `${m.layerCopy('swell', 'es').basis} ${m.layerCopy('wind', 'es').basis}`);
  assert.equal(m.railEntries('es').find(e => e.id === 'fleet').basis, 'Zonas chárter y esfuerzo AIS comercial de 2024; la actividad se infiere del movimiento.');
  assert.equal(m.railEntries('es').find(e => e.id === 'clouds').basis, m.layerCopy('clouds', 'es').basis);
});

test('every caveat a basis sentence carries is kept in the Spanish', async () => {
  const m = await load();
  for (const [id, patterns] of Object.entries(CAVEATS)) for (const re of patterns) assert.match(m.layerCopy(id, 'es').basis, re, `${id}: ${re}`);
  // Published names and credits are not translated.
  assert.match(m.layerCopy('mpas', 'es').basis, /CDFW/);
  assert.equal(m.layerEntry('commercial-ais').attribution, 'Global Fishing Watch · CC BY-NC 4.0');
  assert.equal(m.layerCopy('commercial-ais', 'es').label, 'AIS comercial 2024');
});

test('the new catalogue ids have en and es values with equal placeholders', () => {
  const ids = Object.keys(CATALOGUE).filter(id => /^(layer|rail|legend|dev)\./.test(id));
  assert.ok(ids.length > 200);
  for (const id of ids) {
    assert.ok(CATALOGUE[id].en !== '' && CATALOGUE[id].es?.trim(), `${id}: en and es`);
    assert.equal(placeholders(CATALOGUE[id].es), placeholders(CATALOGUE[id].en), `${id}: placeholders`);
  }
});

test('rail_es_chart_terrain_and_language_switch', async t => {
  const m = await load(), s = m.state;
  t.after(() => { m.language.value = 'en'; });
  s.configureStore({v2: true, storage: null});
  s.syncFromURL(`${ORIGIN}?region=morro-bay&presentation=chart&layers=seafloor,currents,fleet,water-temp`);
  const enRail = rail(m, 'en'), enLegend = legend(m, 'en');
  const esRail = rail(m, 'es'), esLegend = legend(m, 'es');
  assert.match(esRail, /aria-label="Capas"/);
  for (const label of ['Fondo marino', 'Corrientes', 'Temperatura del agua', 'Flota chárter', 'Nubes']) assert.match(esRail, new RegExp(`ui-rail-label">${label}<`), label);
  assert.match(esRail, /aria-label="Fondo marino: fundamento"|Fondo marino: fundamento/);
  assert.match(esRail, /Fuente/);
  assert.match(esRail, /Base/);
  assert.match(esRail, /Nocturno/);
  assert.match(esRail, /Detalle de carta/);
  assert.match(esRail, /Calificación/);
  assert.match(esRail, /Todas/);
  assert.match(esRail, /Buscar/);
  assert.doesNotMatch(esRail, /Seafloor|Water temp|Chart detail/);
  assert.match(esLegend, /aria-label="Leyenda"/);
  assert.match(esLegend, /Fondo marino/);
  // Switching back is byte-identical to the first English render, and the stable control values never change.
  assert.equal(rail(m, 'en'), enRail);
  assert.equal(legend(m, 'en'), enLegend);
  const values = html => [...html.matchAll(/value="([^"]*)"/g)].map(x => x[1]);
  assert.deepEqual(values(esRail), values(enRail), 'option and control values are language-free');
  assert.equal(s.layers.value.join(','), 'seafloor,currents,fleet,water-temp');
  // Terrain: an entry that draws only on the Chart reads the Spanish reason and stays unavailable; unavailable data says missing.
  s.syncFromURL(`${ORIGIN}?region=morro-bay&presentation=2d&layers=water-temp,seafloor`);
  const terrainRail = rail(m, 'es');
  assert.match(terrainRail, /Solo en la Carta/);
  assert.match(terrainRail, /Opciones del terreno/);
  assert.match(terrainRail, /Relieve del fondo marino/);
  assert.match(terrainRail, /Escala real/);
  assert.match(terrainRail, /Exagerado/);
  assert.match(terrainRail, /Superficie de agua ilustrativa de \+0\.8 m\. No es una marea en vivo\./);
  assert.match(terrainRail, /Arrecifes y puntos de especies/);
  assert.match(terrainRail, /Foto/);
  assert.match(legend(m, 'es'), /Candidatos evaluados: Solo en la Carta/);
  assert.match(legend(m, 'es'), /Fondo marino · de menor a mayor profundidad/);
  assert.match(legend(m, 'es'), /app-legend-plain">Temperatura del agua<p class="app-legend-note" data-reason="water-temp">Solo en la Carta/);
  m.language.value = 'en';
  s.syncFromURL(`${ORIGIN}?region=morro-bay&presentation=chart&layers=water-temp`);
  const prior = m.waterTempState.value;
  t.after(() => { m.waterTempState.value = prior; });
  m.waterTempState.value = {...prior, drawn: null, basis: '', reason: 'Water temp unavailable: no analysis for this region.'};
  const unavailable = legend(m, 'es');
  assert.match(unavailable, /Water temp unavailable: no analysis for this region\./, 'the producer reason stays whole');
  assert.match(unavailable, /Detalles de la fuente \(en inglés\): <span lang="en">Water temp unavailable/);
  s.syncFromURL(`${ORIGIN}?region=morro-bay&presentation=chart&layers=clouds`);
  assert.match(legend(m, 'es'), /app-legend-clouds/);
});

test('mpa_fleet_es_caveats_and_drape', async t => {
  const m = await load(), s = m.state;
  const before = {mpa: m.mpaState.value, grounds: m.groundsState.value, ais: m.aisState.value, on: m.aisOn.value};
  t.after(() => { m.language.value = 'en'; m.mpaState.value = before.mpa; m.groundsState.value = before.grounds; m.aisState.value = before.ais; m.aisOn.value = before.on; m.terrainCoarsened.value = []; });
  s.configureStore({v2: true, storage: null});
  s.syncFromURL(`${ORIGIN}?region=morro-bay&presentation=chart&layers=fleet`);
  const retryDetail = m.TRANSIENT_DETAILS.region;
  for (const status of ['complete', 'partial', 'incomplete', 'loading', 'unavailable']) {
    m.mpaState.value = {status, note: `Synthetic ${status} note.`, detail: status === 'unavailable' ? retryDetail : '', checked: '2026-09-21', count: status === 'loading' ? 0 : 3};
    const en = legend(m, 'en'), es = legend(m, 'es');
    for (const html of [en, es]) assert.match(html, /<a class="app-mpa-rules" href="https:\/\/wildlife\.ca\.gov[^"]*" target="_blank" rel="noopener">/, `${status}: the CDFW rules link keeps its href, target and rel`);
    assert.equal(en.match(/app-mpa-rules" href="([^"]+)"/)[1], es.match(/app-mpa-rules" href="([^"]+)"/)[1]);
    assert.match(es, /Reglas y límites oficiales \(CDFW\)<\/a>/);
    assert.match(es, new RegExp(`Synthetic ${status} note\\.`), `${status}: the producer note is kept`);
    assert.match(es, /<p class="app-mpa-note">Detalles de la fuente \(en inglés\): <span lang="en">/);
    assert.match(es, /Áreas marinas protegidas/);
    assert.match(es, /no como delimitación legal/);
    assert.match(es, /Selección regional de SkipperCast a partir de <a href="[^"]+"[^>]*>CDFW Marine Region GIS Lab, California MPAs ds582<\/a>, <a href="[^"]+"[^>]*>CC BY 4\.0<\/a>/);
    assert.equal(/Intentar de nuevo/.test(es), status === 'unavailable', `${status}: Try again only after a transient failure`);
    assert.equal(/Try again/.test(en), status === 'unavailable');
    assert.doesNotMatch(en, /Detalles|lang="en"/, 'English markup carries no Spanish disclosure');
  }
  if (true) {
    m.mpaState.value = {status: 'complete', note: '', detail: 'Synthetic <b>detail</b> with "quotes".', checked: '2026-09-21', count: 3};
    const es = legend(m, 'es');
    assert.match(es, /Synthetic &lt;b>detail&lt;\/b> with &quot;quotes&quot;\./, 'runtime detail is escaped, whole and labelled English');
    assert.doesNotMatch(es, /<b>detail/);
  }
  // Fleet: counts, the dated research line and the commercial AIS caveat.
  m.groundsState.value = {drawn: 1, note: '', audit: '2026-09-21'};
  m.aisOn.value = true;
  m.aisState.value = {...m.aisState.value, offered: true, drawn: 0, note: 'Synthetic AIS status · Jul & Sep 2024 · depth unknown'};
  let es = legend(m, 'es'), en = legend(m, 'en');
  assert.match(es, /1 zona con nombre · sin AIS chárter verificado/);
  assert.match(es, /Investigación revisada 21 sept 2026\./);
  assert.match(en, /1 named vicinity · no verified charter AIS/);
  assert.match(en, /Research checked Sep 21, 2026\./);
  assert.match(es, /AIS comercial 2024/);
  assert.match(es, /muestra fechada, no una temporada continua ni una fuente en vivo de la flota/);
  assert.match(es, /No es prueba|no es prueba de pesca ni de capturas/);
  assert.match(es, new RegExp(m.AIS_CREDIT.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/&/g, '&amp;')), 'the Global Fishing Watch credit stays verbatim');
  assert.match(es, /Jul &amp; Sep 2024 · depth unknown/, 'the producer note keeps its dates');
  m.groundsState.value = {drawn: 2, note: '', audit: '2026-09-21'};
  assert.match(legend(m, 'es'), /2 zonas con nombre · sin AIS chárter verificado/);
  assert.match(legend(m, 'en'), /2 named vicinities · no verified charter AIS/);
  // Dates: missing, invalid, rolled over and the UTC new year never invent a research line.
  for (const audit of [null, '', 'invalid', '2026-02-30', '2026-09-21T00:00:00Z']) {
    m.groundsState.value = {drawn: 1, note: '', audit};
    assert.doesNotMatch(legend(m, 'es'), /Investigación revisada/, String(audit));
  }
  assert.equal(m.researchDate('2027-01-01'), 'Jan 1, 2027');
  assert.equal(m.researchDate('2027-01-01', 'es'), '1 ene 2027');
  assert.equal(m.researchDate('2024-02-29', 'es'), '29 feb 2024');
  assert.equal(m.researchDate('2026-02-30', 'es'), null);
  assert.equal(m.researchDate(null, 'es'), null);
  // Commercial AIS draws on the Chart only and says so in the terrain, in Spanish.
  m.groundsState.value = {drawn: 1, note: '', audit: null};
  s.syncFromURL(`${ORIGIN}?region=morro-bay&presentation=2d&layers=fleet`);
  assert.match(legend(m, 'es'), /data-reason="commercial-ais">Solo en la Carta</);
  // Coarse-drape notes: gated per layer, only on the terrain, translated whole.
  const DRAPE = 'Este relleno se adaptó al terreno con menos muestras. En un relieve pronunciado puede quedar por encima o por debajo de la superficie. Las posiciones de su contorno no cambian.';
  const notes = html => [...html.matchAll(/data-drape="([a-z-]+)">([^<]*)</g)].map(x => [x[1], x[2]]);
  m.terrainCoarsened.value = ['mpas', 'charter-grounds'];
  assert.deepEqual(notes(legend(m, 'es')), [['charter-grounds', DRAPE], ['mpas', DRAPE]]);
  m.terrainCoarsened.value = ['marks'];
  assert.deepEqual(notes(legend(m, 'es')), []);
  m.terrainCoarsened.value = ['mpas', 'charter-grounds'];
  s.syncFromURL(`${ORIGIN}?region=morro-bay&presentation=chart&layers=fleet`);
  assert.deepEqual(notes(legend(m, 'es')), [], 'no note on the Chart');
});

test('dynamic_details_never_silently_dropped', async t => {
  const m = await load(), s = m.state, prior = m.waterTempState.value;
  t.after(() => { m.language.value = 'en'; m.waterTempState.value = prior; });
  s.configureStore({v2: true, storage: null});
  s.syncFromURL(`${ORIGIN}?region=morro-bay&presentation=chart&layers=water-temp`);
  const runtime = 'Synthetic basis: error 0.4 °F, age 5 h, depth unknown, forecast hour 3 <i>future</i> text & more.';
  m.waterTempState.value = {...prior, drawn: {range: [57, 65], product: 'Synthetic product', stamp: 'Oct 8'}, basis: runtime, reason: 'Synthetic reason: stale beyond 72 hours.'};
  const en = legend(m, 'en'), es = legend(m, 'es');
  const escaped = 'Synthetic basis: error 0.4 °F, age 5 h, depth unknown, forecast hour 3 &lt;i>future&lt;/i> text &amp; more.';
  assert.ok(en.includes(escaped), 'English shows the runtime basis as before');
  assert.equal(en.includes(m.layerCopy('water-temp').basis), false, 'English adds no registry sentence beside a richer runtime basis');
  assert.doesNotMatch(en, /Detalles|lang="en"/);
  assert.ok(es.includes(m.layerCopy('water-temp', 'es').basis), 'Spanish leads with the translated registry basis');
  assert.ok(es.includes(`Detalles de la fuente (en inglés): <span lang="en">${escaped}</span>`), 'then the full unchanged runtime basis, escaped, labelled English');
  assert.ok(es.includes('<span lang="en">Synthetic product · Oct 8</span>'), 'the product and stamp stay as published');
  assert.ok(es.includes('<span lang="en">Synthetic reason: stale beyond 72 hours.</span>'));
  // A runtime basis that is the registry's own English sentence is covered by the translation, not repeated.
  m.waterTempState.value = {...prior, basis: m.layerCopy('water-temp').basis, reason: ''};
  assert.equal(legend(m, 'es').includes('lang="en">The bound'), false);
  // No sentence parsing: unknown future text passes through untouched.
  m.waterTempState.value = {...prior, basis: 'Totally new producer wording.', reason: ''};
  assert.ok(legend(m, 'es').includes('<span lang="en">Totally new producer wording.</span>'));
  // Empty producer text adds no empty disclosure.
  m.waterTempState.value = {...prior, basis: '', reason: ''};
  assert.doesNotMatch(legend(m, 'es'), /Detalles de la fuente \(en inglés\): <span lang="en"><\/span>/);
});
