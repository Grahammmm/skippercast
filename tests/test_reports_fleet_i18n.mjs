// SC0922-13: Reports and the public Fleet view in Spanish. The real renderers (ReportsBody, CatchCards,
// catchSheet, the sections, Fleet's Public part) are bundled with esbuild and rendered to strings over synthetic
// fixtures (invented boats and links, no publisher data). English must be byte-identical before and after a
// language switch; Spanish keeps every caveat; published names stay as published; the admin part stays English.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdir, mkdtemp, readFile, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {preparedRendererPlugins} from './helpers/esbuild-url.mjs';
import catalogue from '../catalog/app/strings.json' with {type: 'json'};
import {COVERED, catalogueProblems} from '../scripts/check_copy.mjs';
import {CATCH_COPY_KEYS} from '../packages/coast/src/ui/catches.ts';

const ROOT = new URL('..', import.meta.url).pathname;
const NOW = new Date('2026-10-08T19:00:00Z');
const iso = ms => new Date(NOW.getTime() - ms).toISOString();
const same = (a, b, what) => assert.ok(a === b, `${what}: output differs`);

let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'reports-fleet-i18n-')), 'bundle.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export * from './web/app/views/Reports.tsx';
      export * from './web/reports.ts';
      export * from './web/reports-copy.ts';
      export {Fleet, Public, ACTIVITY_OFF} from './web/app/views/Fleet.tsx';
      export {Admin} from './web/app/views/FleetAdmin.tsx';
      export {coastMarkup} from './web/app/CoastMarkup.tsx';
      export {slo} from './packages/coast/src/counties.ts';
      export {language} from './web/i18n.ts';
      export {groundsState} from './web/map/charter-grounds.ts';
      export {aisOn, aisState} from './web/map/commercial-ais.ts';
      export {activityChoices} from './web/map/fleet.ts';
      export * as state from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: [...preparedRendererPlugins, {name: 'reports-trip-renderer', setup: b => { b.onResolve({filter: /^\.\/map\/maplibre\.js$/}, args => ({path: args.path, external: true})); }}],
  });
  mod = await import(pathToFileURL(out).href);
  return mod;
}

const trip = (i, species, over = {}) => ({id: `t${i}`, tripDate: `2026-10-0${8 - (i % 6)}`, boat: `Fixture Boat ${i}`, landing: 'Fixture Landing', anglers: i === 0 ? null : 10 + i,
  tripType: '1/2 Day AM', species, sourceUrl: `https://reports.example/${i}`, retrievedAt: iso(3_600_000), ...over});
const report = (catches, over = {}) => ({schemaVersion: 1, countyId: 'slo', generatedAt: iso(600_000), catches, catchStatus: 'Synthetic catch status.',
  catchContext: {feedUrl: 'https://feeds.example/c.json', feedGeneratedAt: iso(3_600_000), receivedAt: iso(1_800_000), windowStart: '2026-10-01', windowEnd: '2026-10-08', latestTripDate: '2026-10-08',
    rights: {scope: 'linked-factual-counts', reviewedAt: '2026-10-01', sourceCatalogUrl: 'https://skippercast.example/rights'}}, ...over});
const NINE = Array.from({length: 9}, (_, i) => trip(i, i === 0
  ? [{name: 'Lingcod', count: 4, disposition: 'released'}, {name: 'Vermilion Rockfish', count: 30, disposition: 'retained'}, {name: 'Sanddab', count: 12}]
  : [{name: 'Lingcod', count: i}]));
const widths = html => [...html.matchAll(/width:([\d.]+)%/g)].map(m => m[1]).join(',');
const hrefs = html => [...html.matchAll(/href="([^"]*)"/g)].map(m => m[1]).join(',');

const evidenceFeed = (over = {}, retrieved = false) => {
  const sources = {};
  if (retrieved) for (let d = 1; d <= 7; d++) sources['catches-' + new Date(Date.parse('2026-10-08T12:00:00Z') - d * 86400000).toISOString().slice(0, 10)] = {status: 'ok', data_retrieved_at: iso(3_600_000)};
  const reports = [
    {date: '2026-10-07', boat: 'Fixture Boat A', port: 'Morro Bay', anglers: 12, source_url: 'https://reports.example/a', catches: [{species: 'lingcod', label: 'Lingcod', count: 6}, {species: 'lingcod', label: 'Lingcod', count: 2, disposition: 'released'}]},
    {date: '2026-10-06', boat: 'Fixture Boat B', port: 'Morro Bay', ground: 'Fixture Reef', source_url: 'javascript:alert(1)', catches: [{species: 'rockfish', label: 'Rockfish', count: 40}]},
    {date: '2026-10-06', boat: 'Fixture Boat C', catches: [{species: 'lingcod', label: 'Lingcod', count: 3}]},
  ];
  return {schema_version: 1, region_id: 'morro-bay', generated_at: iso(3_600_000), health: {status: 'ok'}, catch_probability: null, bite_score: null, sources, reports, ...over};
};
const MANY = Array.from({length: 6}, (_, i) => ({date: `2026-10-0${7 - (i % 3)}`, boat: `Fixture Boat ${i % 2}`, port: 'Morro Bay', catches: [{species: 'lingcod', label: 'Lingcod', count: 2 + i}]}));

test('reports_en_es_en_real_renderer: the catch sheet in Spanish keeps counts, widths, links, names and every caveat; English is unchanged', async () => {
  const {coastMarkup, catchCopy, slo} = await load();
  const hostile = [...NINE.slice(0, 3), trip(3, [{name: 'Lingcod', count: 1}], {boat: '<img src=x onerror=1>', landing: 'Fixture <b>Landing</b>'})];
  const state = catches => ({report: report(catches), county: slo, now: NOW});
  const en = coastMarkup('catchSheet', [state(NINE)]);
  same(en, coastMarkup('catchSheet', [state(NINE), undefined]), 'no copy is the English path');
  same(en, coastMarkup('catchSheet', [state(NINE), catchCopy('en')]), 'catchCopy(en) is undefined');
  const es = coastMarkup('catchSheet', [state(NINE), catchCopy('es')]);
  assert.equal((es.match(/<article class="catch-trip">/g) ?? []).length, 8, 'eight cards at most');
  assert.equal(widths(es), widths(en), 'bar widths');
  assert.equal(hrefs(es), hrefs(en), 'source links');
  for (const text of ['FLOTA LOCAL / EVIDENCIA FECHADA', 'Lo que reportó la flota.', 'Último viaje disponible: 8 oct. 9 reportes enlazados en los últimos siete días del calendario local.',
    'Categorías seleccionadas de capturas reportadas, a través de SoCal Fish Reports y SkipperCast. Los reportes originales pueden incluir otras especies. Son registros por viaje; no identifican un arrecife específico ni establecen resultados de pesca desde la costa o de buceo.',
    'Pescadores no reportados', '11 pescadores', 'Lingcod <small>liberados</small>', 'Vermilion Rockfish <small>retenidos</small>', '<dt>Sanddab</dt>',
    'Conteo original fechado de peces', 'Página del editor revisada hace 1 h; esta es la hora de consulta, no la de publicación.',
    'Se muestran los 8 reportes más recientes de 9 disponibles.',
    'Se conservan las categorías originales de especies. Los conteos sin marca significan reportados; no se estableció la retención. La falta de reportes no significa cero capturas. Las barras comparan conteos reportados dentro de cada viaje, no probabilidades de captura ni abundancia.',
    'Fuente recopilada hace 1 h; Fish la recibió hace 30 min. Elegir un día de pronóstico no cambia estas fechas históricas de viajes.',
    'Alcance revisado de reutilización de datos factuales únicamente', 'Texto de la fuente (en inglés): <span lang="en">Synthetic catch status.</span>', '<span lang="en">1/2 Day AM</span>'])
    assert.ok(es.includes(text), text);
  for (const text of ['Anglers unreported', 'Unmarked counts mean reported', 'Showing the latest', 'LOCAL FLEET']) assert.ok(!es.includes(text), `no English left: ${text}`);
  // Hostile published strings stay escaped in both languages.
  for (const html of [coastMarkup('catchSheet', [state(hostile)]), coastMarkup('catchSheet', [state(hostile), catchCopy('es')])]) {
    assert.ok(!html.includes('<img src=x') && !html.includes('<b>Landing'), 'published strings are escaped');
    assert.ok(html.includes('&lt;img src=x onerror=1&gt;'));
  }
  // 0 and 1 reports.
  const none = coastMarkup('catchSheet', [state([]), catchCopy('es')]);
  assert.ok(none.includes('No hay conteos locales de viajes verificados recientemente.') && !none.includes('Se muestran'));
  const one = coastMarkup('catchSheet', [state(NINE.slice(1, 2)), catchCopy('es')]);
  assert.ok(one.includes('1 reportes enlazados') && !one.includes('Se muestran'));
  // No status text: no disclosure; stale feed: no trips, no invented zero.
  const bare = coastMarkup('catchSheet', [{report: report(NINE.slice(0, 1), {catchStatus: ''}), county: slo, now: NOW}, catchCopy('es')]);
  assert.ok(!bare.includes('Texto de la fuente'));
  const stale = coastMarkup('catchSheet', [{report: report(NINE, {catchContext: {...report([]).catchContext, feedGeneratedAt: '2020-01-01T00:00:00Z'}}), county: slo, now: NOW}, catchCopy('es')]);
  assert.ok(stale.includes('No hay conteos locales de viajes verificados recientemente.') && !stale.includes('<article'));
  // The age words, their thresholds and the unavailable case.
  const copy = catchCopy('es');
  for (const [minutes, want] of [[0, 'ahora mismo'], [1, 'ahora mismo'], [2, 'hace 2 min'], [59, 'hace 59 min'], [60, 'hace 1 h'], [1439, 'hace 23 h'], [1440, 'hace 1 d'], [-5, 'hora no disponible']])
    assert.equal(copy.age(new Date(NOW.getTime() - minutes * 60000).toISOString(), NOW), want, String(minutes));
  assert.equal(copy.age('not a time', NOW), 'hora no disponible');
});

test('reports_en_es_en_real_renderer: the page body switches language and back with identical English', async () => {
  const {ReportsBody, CatchCards, Reports, evidenceFrom, language, render, h, slo} = await load();
  const data = {
    evidence: evidenceFrom(evidenceFeed(), 'morro-bay', 'reef', NOW.getTime()),
    discussions: {status: 'degraded', checkedQueries: 3, totalQueries: 4, generatedAt: iso(3_600_000),
      candidates: [{url: 'https://forum.example/t/1', title: 'Fixture thread title', source: 'Fixture forum', published_at: iso(86_400_000), location_basis: ''}]},
    watch: {coast: 'Central', checked: false, items: [{name: 'Yellowtail', located: true, links: [{date: '2026-10-01', publisher: 'Fixture Pub', url: 'https://pub.example/1'}]}, {name: 'Lingcod', located: false, links: []}]},
    charters: {audit: '2026-09-21', more: 2, rows: [{label: 'Fixture Rock', ground: 'Fixture Rock', trips: 3, boats: 1, latest: '2026-09-17', sources: [{date: '2026-09-17', boat: 'Fixture Boat', url: 'https://c.example/1'}]}]},
  };
  const props = {data, catches: {report: report(NINE), county: slo, now: NOW}};
  try {
    language.value = 'en';
    const before = render(h(ReportsBody, props));
    language.value = 'es';
    const es = render(h(ReportsBody, props));
    language.value = 'en';
    same(before, render(h(ReportsBody, props)), 'English after es');
    assert.ok(before.includes('Recent fishing evidence') && before.includes('Report counts are not catch rates or a popularity ranking.'));
    for (const text of ['aria-label="Conteos de capturas de la flota"', 'Evidencia reciente de pesca', 'Conversaciones recientes', 'Seguimiento estacional', 'Dónde reportan pescar los chárteres locales',
      'Evidencia de actividad reciente', '<strong>Baja</strong>', '3 viajes reportados · 3 barcos · 2 fechas con reportes.',
      'La confianza describe la evidencia de actividad reciente, no un pronóstico de tu captura ni una predicción a siete días. Fuente recopilada el 8 oct 2026.',
      '6 Lingcod reportados · 2 Lingcod liberados', 'Morro Bay: desembarque · lugar de pesca no reportado', 'Fuente</a>',
      'Actualizado el 8 oct 2026 · 3/4 búsquedas rotativas revisadas en esta actualización · algunas fuentes fallaron o devolvieron resultados parciales. La cobertura de búsqueda rota entre regiones; un resultado vacío no significa que no haya peces.',
      'Publicado el 7 oct 2026 · Fixture forum · búsqueda regional',
      'Estos enlaces no están revisados. La fecha de publicación no es la fecha de pesca; la búsqueda no verifica una captura, especie ni posición de barco.',
      'Yellowtail · reportes recientes con ubicación; Lingcod.', 'La comprobación actual de fuentes no está disponible.',
      'El seguimiento es un motivo para revisar el agua y los reportes locales; no establece la presencia de peces.',
      'Los capitanes nombraron «Fixture Rock» · 3 viajes reportados · 1 barco · último reporte 17 sept 2026', 'Reportes de origen: ', '2 más en la capa Flota del mapa.',
      'Primero el reporte más reciente. Áreas reportadas en registros de viajes publicados; las paradas exactas se desconocen. Los conteos de reportes no son tasas de captura ni una clasificación de popularidad. Investigación revisada el 21 sept 2026.',
      'Seguir el informe costero (RSS)', 'Informe costero para leer'])
      assert.ok(es.includes(text), text);
    // Names, counts and links published by the sources are the same in both languages.
    assert.equal(hrefs(es), hrefs(before));
    language.value = 'es';
    assert.ok(render(h(ReportsBody, {data: null, catches: null})).includes('Cargando reportes fechados…'));
    assert.ok(render(h(CatchCards, {state: null})).includes('Las fichas fechadas de capturas de la flota se muestran para los puertos cubiertos por el informe costero. Elige uno de esos puertos en el mapa o lee el <a href="/report">informe costero</a>.'));
    const unsafe = {report: report([{...NINE[1], sourceUrl: 'javascript:alert(1)'}]), county: slo, now: NOW};
    assert.ok(render(h(CatchCards, {state: unsafe})).includes('Los conteos de capturas de la flota de este informe no pasaron una comprobación y no se muestran.'));
    const page = render(h(Reports, {now: NOW}));
    assert.ok(page.includes('<span class="ui-eyebrow">Evidencia fechada</span><h1 id="reports-title">Reportes</h1>') && page.includes('La falta de reportes no significa cero capturas.'));
  } finally { language.value = 'en'; }
});

test('reports_sections_fail_independently: each section unavailable or empty in Spanish, all five confidence reasons, 0/1/many counts', async () => {
  const {EvidenceSection, DiscussionsSection, WatchSection, ChartersSection, evidenceFrom, evidenceCopy, rowCopy, countPhrase, language, render, h} = await load();
  try {
    language.value = 'es';
    for (const [Section, props, text] of [
      [EvidenceSection, {evidence: null}, 'La fuente diaria de evidencia de esta región no está disponible. No se supone ninguna puntuación de captura.'],
      [DiscussionsSection, {discussions: {status: 'unavailable', candidates: [], checkedQueries: 0, totalQueries: 0}}, 'La búsqueda de conversaciones recientes no está disponible. Revisa el estado de sus fuentes en la tarea de datos públicos.'],
      [DiscussionsSection, {discussions: {status: 'stale', candidates: [], checkedQueries: 0, totalQueries: 0, generatedAt: '2026-09-01'}}, 'La última instantánea de investigación está fechada el 1 sept 2026. La cobertura actual de conversaciones locales no está verificada.'],
      [DiscussionsSection, {discussions: {status: 'current', candidates: [], checkedQueries: 4, totalQueries: 4, generatedAt: 'nonsense'}}, 'Todavía no hay enlaces locales fechados que hayan pasado el filtro de búsqueda para esta región.'],
      [DiscussionsSection, {discussions: {status: 'current', candidates: [], checkedQueries: 4, totalQueries: 4, generatedAt: 'nonsense'}}, 'Actualizado el fecha no disponible · 4/4'],
      [WatchSection, {watch: null}, 'El seguimiento estacional de esta costa no está disponible.'],
      [WatchSection, {watch: {coast: 'Central', checked: true, items: []}}, 'Central: ninguna especie en seguimiento.'],
      [ChartersSection, {charters: null}, 'No hay evidencia chárter geográficamente específica publicada para esta región y especie objetivo.'],
      [ChartersSection, {charters: {audit: '2026-09-21', more: 0, rows: []}}, 'No hay zonas chárter con reportes para esta especie objetivo.'],
    ]) assert.ok(render(h(Section, props)).includes(text), text);
    assert.ok(!render(h(WatchSection, {watch: {coast: 'Central', checked: true, items: []}})).includes('comprobación actual'), 'a checked watch has no unavailable suffix');

    // Count phrases: exactly 1 is singular; 0 and many are plural.
    assert.deepEqual([0, 1, 2].map(n => countPhrase('trips', n, 'es')), ['0 viajes reportados', '1 viaje reportado', '2 viajes reportados']);
    assert.deepEqual([0, 1, 2].map(n => countPhrase('boats', n, 'es')), ['0 barcos', '1 barco', '2 barcos']);
    assert.deepEqual([0, 1, 2].map(n => countPhrase('days', n, 'es')), ['0 fechas con reportes', '1 fecha con reportes', '2 fechas con reportes']);
    assert.deepEqual([0, 1, 2].map(n => countPhrase('days', n, 'en')), ['0 reporting dates', '1 reporting date', '2 reporting dates']);
  } finally { language.value = 'en'; }

  // The five reasons, from reportEvidence's own flags: the English reason equals the producer's, Spanish is the written sentence.
  const at = NOW.getTime();
  const cases = [
    ['stale', evidenceFeed({generated_at: '2026-09-01T00:00:00Z'}, true), 'La fuente diaria está desactualizada o no disponible; los reportes conservados son contexto histórico.'],
    ['coverage', evidenceFeed(), '0/7 páginas de reportes recientes verificadas; los vacíos limitan la confianza.'],
    ['none', evidenceFeed({reports: []}, true), 'No hay reportes recientes de esta especie en la muestra recopilada. Esto no establece su ausencia.'],
    ['thin', evidenceFeed({}, true), 'Hay reportes recientes, pero son muy pocos barcos o fechas para una confianza mayor.'],
    ['strong', evidenceFeed({reports: MANY}, true), 'Los reportes repetidos de varios barcos respaldan actividad reciente. Las capturas exactas en tu sitio siguen sin verificarse.'],
  ];
  for (const [kind, feed, es] of cases) {
    const e = evidenceFrom(feed, 'morro-bay', 'reef', at);
    assert.equal(e.reasonKind, kind);
    assert.equal(evidenceCopy(e, 'en').reason, e.reason, 'English is the producer\'s own reason');
    assert.equal(evidenceCopy(e, 'es').reason, es, kind);
  }
  assert.deepEqual(['Insufficient', 'Low', 'Moderate', 'Odd'].map(c => evidenceCopy({reasonKind: 'thin', confidence: c}, 'es').confidence), ['Insuficiente', 'Baja', 'Moderada', 'Odd']);
  // Rows: the raw facts translate; a row without them keeps its English, labelled.
  const row = evidenceFrom(evidenceFeed(), 'morro-bay', 'reef', at).rows;
  assert.deepEqual(row.map(r => rowCopy(r, 'es')).map(r => [r.catches, r.where]), [['6 Lingcod reportados · 2 Lingcod liberados', 'Morro Bay: desembarque · lugar de pesca no reportado'], ['40 Rockfish reportados', 'Zona reportada: Fixture Reef'], ['3 Lingcod reportados', 'Puerto: desembarque · lugar de pesca no reportado']]);
  assert.equal(row[2].where, 'Port landing · fishing location unreported', 'English fallback port kept');
  const legacy = {confidence: 'Low', reason: 'Old <b>reason</b>', start: '2026-10-01', end: '2026-10-07', boats: 1, days: 1, trips: 1, generatedAt: '2026-10-08', rows: [{date: '2026-10-07', boat: 'B', catches: '1 X reported', where: 'W', url: null}]};
  try {
    language.value = 'es';
    const html = render(h(EvidenceSection, {evidence: legacy}));
    assert.ok(html.includes('Detalles de la fuente (en inglés): <span lang="en">Old &lt;b>reason&lt;/b></span>'), 'unknown legacy reason keeps its escaped original, labelled');
    assert.ok(html.includes('<span lang="en">1 X reported</span>') && html.includes('<span lang="en">W</span>'));
    assert.ok(!html.includes('Old <b>'));
  } finally { language.value = 'en'; }
});

test('reports_locale_does_not_reload: switching language neither fetches, clears nor re-keys loaded sections; dates keep their rule', async () => {
  const {openReports, reportsData, reportDay, language} = await load();
  const asked = [];
  let release;
  const gate = new Promise(r => { release = r; });
  const fetchFn = async url => { asked.push(url); await gate; return {ok: false, status: 404, json: async () => ({})}; };
  try {
    language.value = 'en';
    const opening = openReports('morro-bay', 'reef', null, fetchFn, NOW.getTime());
    await new Promise(r => setTimeout(r, 20));
    const during = asked.length;
    language.value = 'es';
    await openReports('morro-bay', 'reef', null, fetchFn, NOW.getTime());
    assert.equal(asked.length, during, 'switching while pending asks nothing more');
    release();
    await opening;
    assert.ok(reportsData.value && reportsData.value.key === 'morro-bay:reef', 'the pending load published once');
    // A fully settled load (no failed section) is kept for 30 minutes whatever the language.
    const good = {discussions: {status: 'current', candidates: [], checkedQueries: 1, totalQueries: 1}, evidence: {confidence: 'Low', reason: 'r', start: '2026-10-01', end: '2026-10-07', boats: 1, days: 1, trips: 1, generatedAt: '2026-10-08', rows: []},
      watch: {coast: 'Central', checked: true, items: []}, charters: null};
    const settled = {key: 'morro-bay:reef', data: good, loadedAt: NOW.getTime()};
    reportsData.value = settled;
    const count = asked.length;
    language.value = 'en';
    await openReports('morro-bay', 'reef', null, fetchFn, NOW.getTime() + 60_000);
    language.value = 'es';
    await openReports('morro-bay', 'reef', null, fetchFn, NOW.getTime() + 120_000);
    assert.equal(asked.length, count, 'no reload within the 30-minute window');
    assert.ok(reportsData.value === settled, 'same loaded object and key');
  } finally { language.value = 'en'; reportsData.value = null; }

  // Dates: a bare date is a civil date read in UTC, an instant is read in the default zone; only the locale changes.
  assert.equal(reportDay('2026-10-07', 'en'), 'Oct 7, 2026');
  assert.equal(reportDay('2026-10-07', 'es'), '7 oct 2026');
  assert.equal(reportDay('2026-10-08T05:00:00Z', 'en'), 'Oct 7, 2026', 'an instant late in UTC is still the previous local day');
  assert.equal(reportDay('2026-03-08T09:30:00Z', 'es'), '8 mar 2026', 'DST change day');
  for (const bad of [null, undefined, '', 'garbage', '2026-13-45']) { assert.equal(reportDay(bad, 'en'), 'date unavailable'); assert.equal(reportDay(bad, 'es'), 'fecha no disponible'); }
});

test('fleet_public_es_and_admin_english: public controls and status follow the language; the admin part is exactly English', async () => {
  const m = await load();
  const {Public, Admin, Fleet, ACTIVITY_OFF, language, state, groundsState, aisState, aisOn, activityChoices, render, h} = m;
  globalThis.location = {href: 'https://s.test/map?region=morro-bay&view=fleet&layers=fleet'};
  state.configureStore({v2: true, storage: null});
  state.syncFromURL(location.href);
  const PORTS = [{id: 'morro-bay', name: 'Morro Bay'}, {id: 'port-san-luis', name: 'Port San Luis'}];
  const text = html => html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');
  try {
    aisState.value = {offered: false, drawn: 0, note: ''};
    groundsState.value = {drawn: 0, note: '', audit: null};
    const view = (lang, ports = []) => { language.value = lang; return render(h(Public, {directory: ports})); };

    // Layer on, nothing drawn yet: the layer's own English note stays whole, labelled in Spanish.
    groundsState.value = {drawn: 0, note: 'Charter grounds are loading.', audit: null};
    const enNote = view('en');
    assert.ok(enNote.includes('Charter grounds are loading.') && enNote.includes('Show charter grounds') && !enNote.includes('Detalles'));
    const esNote = view('es');
    assert.ok(esNote.includes('Zonas chárter') && esNote.includes('Mostrar zonas chárter'));
    assert.ok(esNote.includes('Detalles de la fuente (en inglés): <span lang="en">Charter grounds are loading.</span>'));
    same(enNote, view('en'), 'English after es');

    // Drawn 1 and many with the audit date; the audit value is the published one.
    groundsState.value = {drawn: 1, note: '', audit: '2026-09-21'};
    assert.ok(text(view('en')).includes('1 charter ground on the map · audited 2026-09-21'));
    assert.ok(text(view('es')).includes('1 zona chárter en el mapa · revisadas 2026-09-21'));
    groundsState.value = {drawn: 3, note: '', audit: null};
    assert.ok(text(view('en')).includes('3 charter grounds on the map') && text(view('es')).includes('3 zonas chárter en el mapa'));

    // Layer off.
    state.syncFromURL('https://s.test/map?region=morro-bay&view=fleet&layers=seafloor');
    assert.ok(text(view('en')).includes('Off. Turn it on to draw the grounds on the map.'));
    assert.ok(text(view('es')).includes('Desactivadas. Actívalas para dibujar las zonas en el mapa.'));
    state.syncFromURL('https://s.test/map?region=morro-bay&view=fleet&layers=fleet');

    // The registry basis: the full Spanish sentence, with the research-only / not-proof caveats.
    groundsState.value = {drawn: 3, note: '', audit: null};
    const basis = view('es');
    assert.ok(basis.includes('no posiciones de pesca confirmadas por AIS') && basis.includes('no límites chárter publicados'));
    assert.ok(!basis.includes('Detalles de la fuente') || !basis.includes('These are named areas'), 'the registry sentence is not repeated in English');

    // AIS: absent, offered but off, on with a runtime note.
    assert.ok(!text(view('es')).includes('AIS comercial 2024'));
    aisState.value = {offered: true, drawn: 0, note: 'AIS file is loading.'};
    aisOn.value = false;
    const aisOff = view('es');
    assert.ok(aisOff.includes('AIS comercial 2024') && !aisOff.includes('AIS file is loading.'));
    aisOn.value = true;
    const aisLive = view('es');
    assert.ok(aisLive.includes('Detalles de la fuente (en inglés): <span lang="en">AIS file is loading.</span>'));
    assert.ok(aisLive.includes('muestra fechada, no una temporada continua ni una fuente en vivo de la flota') && aisLive.includes('no es prueba de pesca ni de capturas'));
    assert.ok(text(view('en')).includes('Commercial AIS 2024') && view('en').includes('These two months are a dated sample'));
    aisOn.value = false;

    // Directory: absent, then present; port names stay as published.
    assert.ok(!view('es').includes('Directorio de barcos'));
    const dir = view('es', PORTS), dirEn = view('en', PORTS);
    assert.ok(dir.includes('Directorio de barcos') && dir.includes('Barcos que salen de Morro Bay') && dir.includes('Barcos que salen de Port San Luis'));
    assert.ok(dirEn.includes('Boat directory') && dirEn.includes('Boats out of Morro Bay'));
    assert.equal([...dir.matchAll(/href="([^"]*)"/g)].map(x => x[1]).join(), [...dirEn.matchAll(/href="([^"]*)"/g)].map(x => x[1]).join(), 'links do not change');

    // The page and the admin part.
    language.value = 'es';
    assert.ok(render(h(Fleet)).includes('<h1 id="app-fleet-title">Flota</h1>'));
    activityChoices.value = {region: 'CA', vessels: [{id: 'v1', name: 'Sea Example'}], ports: [], classes: [], trip_types: [], kinds: [], seasons: [], season_parts: [], dates: {}};
    const adminEs = render(h(Admin, {}));
    language.value = 'en';
    const adminEn = render(h(Admin, {}));
    same(adminEs, adminEn, 'admin markup is English in every language');
    assert.ok(adminEn.includes('Fleet activity · admin') && adminEn.includes('How fleet activity is inferred') && adminEn.includes(ACTIVITY_OFF));
  } finally {
    language.value = 'en'; activityChoices.value = null; aisOn.value = false;
    aisState.value = {offered: false, drawn: 0, note: ''}; groundsState.value = {drawn: 0, note: '', audit: null};
  }
});

test('copy_inventory_and_pin_negative_controls: every new id has en and es with equal placeholders; the files are covered; gaps fail', async () => {
  const vars = text => [...new Set([...text.matchAll(/\{(\w+)\}/g)].map(x => x[1]))].sort();
  const ids = Object.keys(catalogue.strings).filter(id => /^(?:reports\.|reportCatch\.|fleet\.public\.)/.test(id));
  assert.ok(ids.length >= 80, 'the unit\'s ids are present');
  for (const id of ids) {
    const {en, es} = catalogue.strings[id];
    assert.ok(typeof en === 'string' && en !== '' && typeof es === 'string' && es.trim() !== '', `${id} has en and es`);
    assert.deepEqual(vars(es), vars(en), `${id} placeholders`);
  }
  // The catch renderer's key list and the catalogue agree exactly (age words are the host's, not the renderer's).
  assert.deepEqual(ids.filter(id => id.startsWith('reportCatch.') && !id.startsWith('reportCatch.age.')).sort(), [...CATCH_COPY_KEYS].sort());
  for (const key of CATCH_COPY_KEYS) assert.ok(Object.hasOwn(catalogue.strings, key), key);
  for (const file of ['web/app/views/Reports.tsx', 'web/reports.ts', 'web/reports-copy.ts', 'web/app/views/Fleet.tsx']) assert.ok(COVERED.includes(file), file);
  assert.ok(!COVERED.includes('web/app/views/FleetAdmin.tsx'), 'the admin part is explicitly outside the Spanish scope');
  assert.deepEqual(catalogueProblems().filter(p => /Reports|reports|Fleet/.test(p)), []);

  // Negative controls against a temporary root: a missing es value, an unknown id and an inserted English sentence all fail.
  const root = await mkdtemp(join(tmpdir(), 'reports-fleet-copy-'));
  await mkdir(join(root, 'catalog/app'), {recursive: true});
  await mkdir(join(root, 'web/app/views'), {recursive: true});
  const strings = {'reports.title': {en: 'Reports', es: 'Reportes'}, 'reports.gap': {en: 'Gap', es: ''}};
  await writeFile(join(root, 'catalog/app/strings.json'), JSON.stringify({strings}));
  await writeFile(join(root, 'web/app/views/Reports.tsx'), `export const A = () => <p>{t('reports.title', lang)}{t('reports.nope', lang)}</p>;\nexport const B = () => <p>A published sentence that was left in English.</p>;\n`);
  const found = catalogueProblems(root);
  assert.ok(found.some(p => p.includes('reports.gap has no es value')), 'missing es');
  assert.ok(found.some(p => p.includes("t('reports.nope') is not in")), 'unknown id');
  assert.ok(found.some(p => p.includes('bare literal') && p.includes('A published sentence')), 'inserted English sentence');
  assert.ok(!(await readFile(join(ROOT, 'web/app/views/Fleet.tsx'), 'utf8')).includes('Show charter grounds'), 'no public English literal left in Fleet.tsx');
});
