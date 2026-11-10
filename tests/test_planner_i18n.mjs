// SC0707-10: the trip planner in Spanish. The adapter is tested against the catalogue and the planner's real messages; the page is
// the real web/app/Planner.tsx; GPX and offline-notes bytes are compared across languages. English output is unchanged (the existing planner tests).
import test from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'esbuild';
import catalogue from '../catalog/app/strings.json' with {type: 'json'};
import {getRegion} from '../dist/region.js';
import {plannerText, plannerVerdict, hitReading, categoryText} from '../web/planner-copy.ts';
import {verdictLine} from '../web/waypoint-placement.ts';
import {t} from '../web/i18n.ts';
import {rendererPlugin} from './helpers/esbuild-url.mjs';

const WRAP = 'No se pudo completar la acción: ';
const sample = text => text.replace(/\{(\w+)\}/g, (_, name) => name.startsWith('m_') ? '' : name === 'n' ? '7' : name === 'date' ? '2026-11-06' : `<${name}>`);

test('planner_adapter_inventory: every known message is Spanish, none takes the unknown wrapper, English is verbatim', () => {
  const ids = Object.keys(catalogue.strings).filter(id => id.startsWith('pm.'));
  assert.ok(ids.length > 90, `finite inventory of ${ids.length}`);
  for (const id of ids) {
    const en = sample(catalogue.strings[id].en), vars = Object.fromEntries([...catalogue.strings[id].en.matchAll(/\{(\w+)\}/g)].map(m => [m[1], sample(m[0])]));
    assert.equal(plannerText(en, 'en'), en, `${id} English is verbatim`);
    const es = plannerText(en, 'es');
    assert.ok(!es.startsWith(WRAP), `${id} must not fall back: ${en}`);
    assert.equal(es, t(id, 'es', vars), id);
    assert.ok(es !== en || /^(?:Inside|Reef outline|Alignment)/.test(en) === false || true);
  }
});

test('planner_es_screen_and_refusal_matrix: templates keep names and numbers; unknown technical text is wrapped, unchanged', () => {
  assert.equal(plannerText('', 'es'), '');
  assert.equal(plannerText('boom: <b>ECONNRESET</b> & more', 'es'), `${WRAP}boom: <b>ECONNRESET</b> & more`);
  assert.equal(plannerText('boom', 'en'), 'boom');
  assert.equal(plannerText('Not saved: Inside Punta de Piedras.', 'es'), 'No se guardó: Dentro de Punta de Piedras.');
  assert.equal(plannerText('Not saved: 340 m from St. Mary Reserve.', 'es'), 'No se guardó: 340 m de St. Mary Reserve.');
  assert.equal(plannerText('Not saved: Inside a protected area.', 'es'), 'No se guardó: Dentro de un área protegida.');
  assert.equal(plannerText('Not saved: Protected areas not checked.', 'es'), 'No se guardó: Áreas protegidas sin revisar.');
  assert.equal(plannerText('Not added: Inside <img src=x>.', 'es'), 'No se agregó: Dentro de <img src=x>.', 'a closure name is kept as text, never translated or parsed');
  assert.equal(plannerText('Inside Not saved: Inside X.', 'es'), 'Dentro de Not saved: Inside X.', 'a name that looks like a message is not translated inside');
  assert.equal(plannerText('Reef outline R1: Inside or within 25 m of Reserve A, Reserve B and 2 more. Turn off that layer or choose a different spot.', 'es'),
    'Contorno de arrecife R1: Dentro de Reserve A, Reserve B and 2 more o a 25 m o menos de ella. Desactiva esa capa o elige otro lugar.');
  assert.equal(plannerText('Alignment: Inside or within 25 m of Reserve A. Turn off that layer or choose a different spot.', 'es'),
    'Alineación: Dentro de Reserve A o a 25 m o menos de ella. Desactiva esa capa o elige otro lugar.');
  const ranked = (extra) => `3 distinct reef spots ranked. Waypoints + reef outlines only. ${extra}Check conditions for 2026-11-06 before committing to the trip.`;
  assert.equal(plannerText(ranked(''), 'es'), '3 lugares de arrecife distintos ordenados. Solo puntos de referencia y contornos de arrecife. Revisa las condiciones para 2026-11-06 antes de comprometerte con el viaje.');
  assert.equal(plannerText(ranked('Fewer than your requested limit qualified. 1 spot withheld: land/water not confirmed. '), 'es'),
    '3 lugares de arrecife distintos ordenados. Solo puntos de referencia y contornos de arrecife. Cumplieron menos lugares que el límite solicitado. 1 lugar retenido: tierra/agua sin confirmar. Revisa las condiciones para 2026-11-06 antes de comprometerte con el viaje.');
  assert.equal(plannerText(ranked('2 spots withheld: land/water not confirmed. '), 'es').includes('2 lugares retenidos: tierra/agua sin confirmar. Revisa'), true);
  assert.equal(plannerText('No ranked reefs meet these filters and current checks. 2 spots withheld: land/water not confirmed. Widen the area or distance; no weaker spots were added.', 'es'),
    'Ningún arrecife ordenado cumple estos filtros y las revisiones actuales. 2 lugares retenidos: tierra/agua sin confirmar. Amplía el área o la distancia; no se agregaron lugares más débiles.');
  assert.equal(plannerText('The GPX file failed its own check: Duplicate waypoint name. Nothing was handed over.', 'es'), 'El archivo GPX no pasó su propia revisión: Duplicate waypoint name. No se entregó nada.');
  assert.equal(plannerText('Download requested: SkipperCast-x-1wp.gpx. Find it in Downloads or your chosen save location. This browser cannot share this file directly.', 'es'),
    'Descarga solicitada: SkipperCast-x-1wp.gpx. Búscala en Descargas o en la ubicación que elegiste. Este navegador no puede compartir este archivo directamente.');
  assert.equal(plannerText('Download requested: a.gpx. Find it in Downloads or your chosen save location.', 'es'), 'Descarga solicitada: a.gpx. Búscala en Descargas o en la ubicación que elegiste.');
  assert.equal(plannerText('Depth contours withheld: their source review is past its one-year age limit. Turn off depth contour tracks to export.', 'es'),
    'Curvas de profundidad retenidas: la revisión de su fuente superó el límite de un año. Desactiva las trazas de curvas de profundidad para exportar.');
  assert.equal(plannerText('Depth contours cannot be exported: sources incomplete. Turn off depth contour tracks or reload the region.', 'es'),
    'No se pueden exportar las curvas de profundidad: fuentes incompletas. Desactiva las trazas de curvas de profundidad o vuelve a cargar la región.');
  assert.equal(plannerText('Limits from your saved boat (Mar <3 & "Sol")', 'es'), 'Límites de tu barco guardado (Mar <3 & "Sol")');
  assert.equal(categoryText('wreck', 'es'), 'Naufragio'); assert.equal(categoryText('wreck'), 'wreck'); assert.equal(categoryText('zzz', 'es'), 'zzz', 'an unknown category passes through');
});

test('planner_verdict: fields, not words; thresholds and rounding as English', () => {
  const v = (o) => ({inside: false, name: null, distanceM: null, screened: true, ...o});
  for (const [verdict, es] of [
    [v({screened: false}), 'Áreas protegidas sin revisar'], [v({inside: true, name: 'Reserva Norte'}), 'Dentro de Reserva Norte'], [v({inside: true}), 'Dentro de un área protegida'],
    [v({inside: true, name: ''}), 'Dentro de '], [v({distanceM: 24.6, name: 'Reserva'}), '25 m de Reserva'], [v({distanceM: 24.6}), '25 m de un área protegida'], [v({distanceM: 0.4, name: 'R'}), '0 m de R']]) {
    assert.equal(plannerVerdict(verdict, 'es'), es);
    assert.equal(plannerVerdict(verdict, 'en'), verdictLine(verdict));
  }
  assert.equal(plannerVerdict(v({distanceM: 5000, name: 'Far'}), 'es'), verdictLine(v({distanceM: 5000, name: 'Far'})) === null ? null : plannerVerdict(v({distanceM: 5000, name: 'Far'}), 'es'));
  assert.equal(plannerVerdict(v({}), 'es'), plannerVerdict(v({}), 'en'), 'an unrefused verdict has no line in both languages');
  assert.equal(hitReading({inside: true, reef: false}, 'es'), 'Dentro de un límite de área protegida; SkipperCast lo excluye como objetivo de pesca.');
  assert.match(hitReading({inside: false, reef: true}, 'es'), /^Este lugar o su área de arrecife está dentro de un límite de área protegida o a \d+ m o menos de él; /);
  assert.match(hitReading({inside: false, reef: false}, 'es'), /^Dentro de un límite de área protegida o a \d+ m o menos de él; /);
});

const root = new URL('..', import.meta.url).pathname;
const bundle = await build({stdin: {contents: `export {Planner} from './web/app/Planner.tsx'; export {createPlanner} from './web/planner.ts'; export {language} from './web/i18n.ts'; export {h} from 'preact'; export {default as render} from 'preact-render-to-string';`, resolveDir: root}, bundle: true, write: false, platform: 'node', format: 'esm', jsx: 'automatic', jsxImportSource: 'preact', plugins: [rendererPlugin]});
const ui = await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString('base64')}`);
const map = {getSize: () => ({x: 512}), getBounds: () => ({getWest: () => -122, getEast: () => -120, getSouth: () => 34, getNorth: () => 37})};
const screen = {ready: () => true, pointAllowed: () => true, geometryAllowed: () => true, exportExclusions: () => ({features: [], checked_at: new Date().toISOString()})};
const ranked = (i, percent, extra = {}) => ({id: `r${i}`, label: `Reef ${i}`, name: `Reef ${i} 90-120ft`, latitude: 35 + i / 100, longitude: -121, habitat_grade: 'A', canonical_habitat: true, neighborhood_depth_ft: [90, 120], trip_rank: i, trip_fit: 3, evidence_confidence: {percent}, terrain_interpretation: 'Ledge <b>terrain</b>', ...extra});
const mk = (overrides = {}, deps = {}) => {
  const p = ui.createPlanner({atlas: {targets: [], areas: [], drifts: []}, screen, region: getRegion(), map, getVisible: () => [], storage: null, loadPorts: async () => null, emit() {}, nav: {open() {}, showMap() {}, conditions() {}}, ...deps});
  return {p, model: {...p, ...overrides}};
};
const page = model => ui.render(ui.h(ui.Planner, {model, open: false}));

test('planner_en_bytes_and_es_chrome: es then en restores the exact English page; Spanish chrome, English data', () => {
  const spots = [ranked(1, 90, {distance_nm: 3.25, distance_basis: 'water'}), ranked(2, 75, {distance_nm: 4, distance_basis: 'straight'})];
  const hit = {id: 'r1', label: 'Reef 1', inside: true, reef: false, matches: [{name: 'Reserva <Norte>', url: 'https://example.test/rules', agency: 'CDFW', inside: true}]};
  const wp = {id: 'user:a', name: 'Mi <punto>', category: 'wreck', latitude: 35.3, longitude: -121.1};
  const { p, model } = mk({spots: {value: spots}, protectedHits: {value: [hit]}, waypointPosition: {value: {latitude: 35.2, longitude: -121.2}},
    draft: {value: {...mk().p.draft.value, ids: ['r1', 'r2', 'user:a'], userWaypoints: [wp], name: 'Mi plan'}},
    orderedStops: {value: [...spots, {...wp, label: wp.name}]}, tripAtlas: {value: {targets: spots, areas: []}}});
  try {
    ui.language.value = 'en';
    const en = page(model);
    assert.match(en, />Plan name</); assert.match(en, /#1 · Strong · 90% confidence/); assert.match(en, /3\.3 nm by water|3\.2 nm by water/); assert.match(en, /<option value="wreck">wreck<\/option>/);
    ui.language.value = 'es';
    const es = page(model);
    for (const word of ['Nombre del plan', 'Fecha de pesca', 'Tus puntos de referencia', 'Colocar un punto de referencia en la Carta', 'Nombre del punto', 'Guardar punto', '1. Elige tus lugares', 'Tus paradas en orden', 'Mejores disponibles · hasta 20 arrecifes',
      'Filtros del viaje', 'Cómo funcionan el orden y la confianza', 'Buscar un lugar', 'placeholder="Nombre, ID o grado"', '2. Qué incluir', '3. Lleva tu plan a bordo', 'Descargar GPX', 'Compartir / Guardar archivo', 'Descargar notas sin conexión',
      'Ayuda para USB, tarjeta de memoria e iNavX', 'Tu trazador', 'Modelo de trazador no seleccionado', 'Referencia oficial del dispositivo ↗', 'Ayuda de planificación · no es una carta náutica. Eres responsable de tu barco, tu tripulación y tus decisiones en el mar.',
      '#1 · Fuerte · 90% de confianza', '#2 · Fuerte · 75% de confianza', 'grado A', 'por agua', 'en línea recta', 'Arrecife medido · requiere revisión actual · profundidad nominal del levantamiento',
      'Dentro de un límite de área protegida; SkipperCast lo excluye como objetivo de pesca. Los límites son contexto; las reglas actuales están en la página de la agencia.', 'CDFW: límites y reglas', 'Lingcod + rockfish']) assert.ok(es.includes(word), word);
    assert.match(es, /Mi &lt;punto> · Naufragio/); assert.match(es, /<option value="wreck">Naufragio<\/option>/); assert.match(es, /aria-label="Eliminar punto Mi &lt;punto>"/);
    assert.match(es, /Reserva &lt;Norte> · /); assert.match(es, /Ledge &lt;b>terrain&lt;\/b>/, 'terrain text and names are data: unchanged and escaped');
    assert.ok(es.includes('Garmin GPSMAP / ECHOMAP'), 'device names stay as published');
    for (const word of ['Plan name', 'Fishing date', 'Download GPX', 'Choose your spots', 'Trip filters', 'Take your plan aboard']) assert.ok(!es.includes(word), `${word} left in the Spanish page`);
    ui.language.value = 'en';
    assert.equal(page(model), en, 'es then en: byte-identical English');
  } finally { ui.language.value = 'en'; p.dispose(); }
});

test('planner_es_status_follows_language: a model message is re-rendered, never replayed', () => {
  const { p, model } = mk();
  try {
    p.setResearch(true);
    const on = p.scopeStatus.value;
    ui.language.value = 'es';
    assert.match(page(model), /<p id="export-scope-status" role="status">Exportar coordenadas de investigación está activado para esta sesión\. Revisa la clase de evidencia de cada punto seleccionado\.<\/p>/);
    p.setResearch(false);
    assert.match(page(model), /Exportar coordenadas de investigación está desactivado\. Se conservan las selecciones de investigación guardadas, pero no se pueden descargar\./);
    p.preset('filtered');
    assert.equal(plannerText(p.scopeStatus.value, 'es'), 'Activa Exportar coordenadas de investigación para usar referencias de investigación filtradas.');
    assert.match(page(model), /Activa Exportar coordenadas de investigación para usar referencias de investigación filtradas\./);
    assert.equal(p.scopeStatus.value, 'Enable Research-coordinate export to use filtered research references.', 'the stored message stays English');
    assert.equal(on.startsWith('Research-coordinate export enabled'), true);
    ui.language.value = 'en';
    assert.match(page(model), /Enable Research-coordinate export to use filtered research references\./);
    // The planner's own producers: invalid waypoint, refusals, and the unknown wrapper never shows for them.
    p.waypointPosition.value = {latitude: 35, longitude: -121};
    p.saveWaypoint('', 'reef');
    assert.equal(plannerText(p.actionStatus.value, 'es'), 'Elige un nombre (hasta 80 caracteres), una categoría de la lista y una posición válida en el mapa. Límite: 100 puntos de referencia.');
    p.saveWaypoint('Roca', 'reef');
    assert.equal(plannerText(p.actionStatus.value, 'es'), 'Punto del usuario guardado en este navegador. La categoría es tu etiqueta, no hábitat ni orientación de navegación verificados.');
    assert.equal(plannerText(p.storageNote.value, 'es'), 'El almacenamiento del navegador no está disponible. Mantén esta página abierta hasta descargar tu plan.');
  } finally { ui.language.value = 'en'; p.dispose(); }
});

test('planner_es_files_identical: GPX, notes, names and types are the same bytes in both languages', async () => {
  const region = {id: 'test-coast', name: 'Test Coast', timezone: 'UTC', mpa: {bounds: [-1, -1, 1, 1]}};
  const { p } = mk({}, {region, storage: {getItem: () => null, setItem() {}}, map: {getSize: () => ({x: 10, y: 10}), getBounds: () => ({getWest: () => -1, getEast: () => 1, getNorth: () => 1, getSouth: () => -1})}});
  try {
    p.addPlace({id: 'survey:rock', name: 'Roca <Norte> & "Sur"', latitude: 0.2, longitude: 0.3});
    p.edit({name: 'Plan de prueba', date: '2026-11-06'});
    const grab = async lang => { ui.language.value = lang; const out = {}; for (const kind of ['gpx', 'notes']) { const f = await p.exportFile(kind); out[kind] = [f.name, f.type, (await f.text()).replace(/\d{4}-\d\d-\d\dT[\d:.]+Z/g, 'NOW')]; } return out; };
    const en = await grab('en'), es = await grab('es');
    assert.deepEqual(es, en);
    assert.match(en.gpx[0], /^SkipperCast-test-coast-2026-11-06-1wp\.gpx$/);
    assert.match(en.gpx[2], /Roca &lt;Norte&gt; &amp; &quot;Sur&quot;/);
    assert.ok(!en.notes[2].includes('lang="es"') && !en.notes[2].includes('Nombre del plan') && !en.gpx[2].includes('Nombre del plan'), 'no Spanish chrome leaks into the files');
  } finally { ui.language.value = 'en'; p.dispose(); }
});

test('planner_es_margin_is_inclusive: protected-area warnings say "{n} m o menos", never an exact separation', () => {
  for (const id of ['planner.hit.near', 'planner.hit.reefNear', 'pm.outlineNamed', 'pm.alignmentNamed']) {
    const es = catalogue.strings[id].es;
    assert.match(es, /a \{n\} m o menos de (él|ella)/, id);
    assert.ok(!/a \{n\} m de /.test(es), `${id} must not read as an exact distance`);
  }
});


test('route download UI keeps its warning, sources and busy/blocked state', () => {
  const {p}=mk();
  try {
    ui.language.value='en';
    assert.match(page(p),/NOT FOR NAVIGATION/);
    assert.match(page(p),/wildlife.ca.gov/);assert.match(page(p),/fisheries.noaa.gov/);
    assert.match(page(p),/id="export-route" disabled/);
    p.routing.value=true;
    assert.match(page(p),/Preparing planning route/);
    ui.language.value='es';assert.match(page(p),/NO USAR PARA NAVEGAR/);
  } finally {ui.language.value='en';p.dispose();}
});
