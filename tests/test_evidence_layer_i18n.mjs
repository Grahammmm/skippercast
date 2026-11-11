// SC1352-07: the charter-ground, historical commercial-AIS and temperature-front cards and their status lines in Spanish.
// The producers keep their English strings and attach catalogue parts; the card, rail and legend resolve them at render.
// Synthetic fixtures and the committed files, no network.
import './helpers/spanish-ready.mjs';   // SC1407-09: the Spanish table, before the Spanish renders
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {signal} from '@preact/signals';
import strings from '../catalog/app/strings.json' with {type: 'json'};
import {copyText, resolveMarkCopy} from '../web/mark-copy.ts';
import {NOTES, NOTE_COPY, createCharterGrounds, groundMark, groundsState} from '../web/map/charter-grounds.ts';
import {AIS_NOTES, AIS_NOTE_COPY, aisMark, aisOn, aisState, aisSummary, createCommercialAis} from '../web/map/commercial-ais.ts';
import {frontsMark, frontsStatus, readFronts} from '../web/map/fronts.ts';
import {assessScreen, CHECKING} from '../web/map/habitat.ts';
import {railNoteCopies, railNotes} from '../web/map/layers.ts';
import {markData, markScreen} from '../web/map/marks.ts';
import {readPalette} from '../web/map/palette.ts';
import {resolveStatusText, statusIn, statusText} from '../web/map/status-copy.ts';
import {configureStore, species, syncFromURL} from '../web/state.ts';

const ROOT = new URL('..', import.meta.url);
const json = path => JSON.parse(readFileSync(new URL(path, ROOT), 'utf8'));
const REGION = json('dist/regions/morro-bay/region.json');
const GROUNDS = json(`dist/${REGION.assets.charters}`), CELLS = json(`dist/${REGION.assets.commercial_ais}`), SNAPSHOT = json(`dist/${REGION.assets.protected_areas}`);
const HOUR = 3_600_000, NOW = new Date('2026-10-16T12:00:00Z');
const READY = assessScreen({areas: SNAPSHOT.features, checkedAt: new Date(+NOW - HOUR).toISOString(), live: false, closures: undefined}, +NOW);
const sentinel = readPalette(name => `token(${name})`);
const flush = () => new Promise(resolve => setImmediate(resolve));
const ground = GROUNDS.grounds[0], cell = CELLS.features[0].properties;
const es = mark => resolveMarkCopy(mark, 'es'), en = mark => resolveMarkCopy(mark, 'en');
const FIELDS = ['name', 'kind', 'reading', 'source', 'basis'];
const dateOf = (lang, s) => new Intl.DateTimeFormat(lang, {month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC'}).format(new Date(`${s}T12:00:00Z`));
const dateKeys = [ground.latest_report, GROUNDS.audit_date];
const enDates = Object.fromEntries(dateKeys.map(d => [dateOf('es', d), dateOf('en-US', d)]));
const esDates = new RegExp(Object.keys(enDates).join('|'), 'g');

test('evidence_card_language_round_trip: English is byte-identical to the producer strings; Spanish leaves published text alone', () => {
  const g = groundMark(ground, GROUNDS), a = aisMark(cell);
  const d = frontsStatus(true, {state: 'ready', doc: readFronts(frontsDoc(6), 'test-coast')}, NOW).drawn;
  const f = frontsMark(d, {lon: -120.9, lat: 35.1}, NOW);
  for (const mark of [g, a, f]) {
    const before = JSON.stringify(mark);
    for (const key of FIELDS) {
      // The Spanish forms of dates and decimals are formatted when the descriptor is built (as SC1352-05's are), so the English parity check swaps them back.
      const english = key in mark.copy ? copyText(mark.copy[key], 'en').replace(/(\d),(\d)/g, '$1.$2').replace(esDates, m => enDates[m]) : null;
      if (english !== null) assert.equal(english, mark[key], `${mark.id} ${key}: the catalogue English is the producer's English`);
      assert.equal(en(mark)[key], mark[key]);
    }
    const spanish = es(mark);
    assert.equal(JSON.stringify(mark), before, 'resolving Spanish does not change the mark');
    assert.equal(en(mark).kind, mark.kind, 'en -> es -> en');
    for (const english of ['not catch rates', 'remains unverified', 'not a fish or catch', 'exact stops unknown', 'age limit', 'not qualified']) assert.ok(!spanish.basis.includes(english), `${mark.id}: "${english}" is not left embedded in the Spanish basis`);
  }
  // Published text stays as published.
  const sg = es(g);
  assert.equal(sg.name, ground.label);
  assert.ok(sg.kind.endsWith(ground.precision)); assert.ok(sg.basis.includes(ground.location_confidence)); assert.ok(sg.basis.includes(ground.boundary_note)); assert.ok(sg.basis.includes(`«${ground.reported_ground}»`));
  const sa = es(a);
  assert.equal(sa.name, cell.label); assert.ok(sa.source.startsWith(cell.attribution)); assert.ok(sa.source.includes(cell.active_dates_utc.join(', ')));
  for (const raw of [cell.gear_label, cell.fishing_location_confidence, cell.vessel_count_note, cell.resolution_note]) assert.ok(sa.basis.includes(raw), raw);
  const sf = es(f);
  assert.equal(sf.source.slice(0, 'Fixture product'.length), 'Fixture product');
});

test('grounds_failure_species_and_no_publish: every safety sentence keeps its meaning in Spanish', () => {
  const sg = es(groundMark(ground, GROUNDS));
  assert.match(sg.kind, /^Zona reportada por chárter · /);
  assert.match(sg.reading, /viajes reportados · \d+ embarcaci\w+ · último reporte .*\. Profundidades del levantamiento del contorno: .* ft \(nominales, levantamiento de \d{4}\)$/);
  assert.match(sg.source, /^Reportes de viajes publicados · investigación revisada el /);
  assert.ok(sg.basis.includes('Área reportada; se desconocen las paradas exactas.'));
  assert.ok(sg.basis.includes('no publicaron posiciones GPS ni profundidades de pesca.'));
  assert.ok(sg.basis.includes('Los recuentos de reportes no son tasas de captura ni una clasificación de popularidad.'));
  assert.ok(sg.basis.startsWith(strings.strings['layer.charter-grounds.basis'].es), 'the registry basis in Spanish leads');
  // 0 / 1 / many.
  const one = es(groundMark({...ground, report_count: 1, boats: ['x']}, GROUNDS)).reading;
  assert.match(one, /^1 viaje reportado · 1 embarcación · /);
  assert.equal(groundMark({...ground, report_count: 1, boats: ['x']}, GROUNDS).reading.slice(0, 31), '1 reported trips · 1 boat · lat');
  assert.match(es(groundMark({...ground, report_count: 0, boats: []}, GROUNDS)).reading, /^0 viajes reportados · 0 embarcaciones · /);
  // The date is the UTC date, and a date that is not one is not invented.
  assert.match(es(groundMark({...ground, latest_report: '2025-01-01'}, {...GROUNDS, audit_date: '2025-12-31'})).source, /31 dic 2025$/);
  assert.match(es(groundMark({...ground, latest_report: 'not a date'}, GROUNDS)).reading, /último reporte Invalid Date/);
  // Status lines.
  assert.equal(resolveStatusText(NOTES.none, NOTE_COPY.none, 'es'), 'No hay zonas chárter verificadas para esta región');
  assert.equal(resolveStatusText(NOTES.failed, NOTE_COPY.failed, 'es'), 'Reportes no disponibles · consulta la evidencia');
  assert.equal(resolveStatusText(NOTES.species, NOTE_COPY.species, 'es'), 'Esta capa solo admite lingcod y rockfish.');
  for (const k of Object.keys(NOTES)) { assert.equal(statusIn(NOTE_COPY[k], 'en'), NOTES[k]); assert.equal(resolveStatusText(NOTES[k], NOTE_COPY[k], 'en'), NOTES[k]); }
});

test('ais_historical_identity_not_verified: the historical, unqualified and unverified-identity statements all stay in Spanish', () => {
  const m = aisMark({...cell, apparent_fishing_hours: 1234.56, days_with_apparent_fishing: 1});
  assert.equal(es(m).kind, 'AIS comercial · histórico de 2024');
  assert.equal(es(m).reading, '1 día con actividad · 1234,6 h de tiempo de pesca aparente. Actividad pesquera aparente, no un lugar de captura verificado.');
  assert.equal(m.reading.slice(0, 40), '1 days with activity · 1,234.6 hr appare');
  const basis = es(m).basis;
  for (const s of ['Se desconocen la profundidad y las especies objetivo.', 'Este contexto mar adentro no está validado para el límite de pesca de 200 pies.', `Clasificación del arte: ${cell.gear_label}.`,
    'La identidad como chárter local de pesca deportiva sigue sin verificarse.']) assert.ok(basis.includes(s), s);
  assert.ok(basis.indexOf(cell.fishing_location_confidence) < basis.indexOf('La identidad como chárter'), 'the raw confidence sentence stays where it was');
  assert.match(es(aisMark({...cell, apparent_fishing_hours: 0, days_with_apparent_fishing: 0})).reading, /^0 días con actividad · 0 h de /);
  assert.equal(resolveStatusText(aisSummary(3), [{id: 'mark.layer.ais.status.summary', vars: {n: 3}}], 'es'), '3 celdas históricas de cuadrícula · jul y sep de 2024 · profundidad desconocida');
  for (const k of Object.keys(AIS_NOTES)) { assert.equal(statusIn(AIS_NOTE_COPY[k], 'en'), AIS_NOTES[k]); assert.match(resolveStatusText(AIS_NOTES[k], AIS_NOTE_COPY[k], 'es'), /AIS comercial/); }
  assert.equal(statusIn([{id: 'mark.layer.ais.status.summary', vars: {n: 3}}], 'en'), aisSummary(3));
});

const frontsDoc = (hours, extra = {}) => ({schema_version: 1, region_id: 'test-coast', layer_id: 'sst-fronts', product: 'Fixture product', credit: 'NOAA CoastWatch', max_age_hours: 48,
  observed_at: new Date(+NOW - hours * HOUR).toISOString(), fronts: [{id: 'f1', observed_at: new Date(+NOW - hours * HOUR).toISOString(), strength_c_per_km: 0.2, uncertainty_c: 0.3, band_half_width_km: 1.5,
    geometry: {type: 'LineString', coordinates: [[-121, 35], [-120.8, 35.2]]}}], ...extra});
const status = (doc, now = NOW) => frontsStatus(true, doc === null || typeof doc === 'string' ? {state: doc ?? 'none'} : {state: 'ready', doc: readFronts(doc, 'test-coast')}, now);

test('front_refusal_is_not_no_front: each refusal keeps its own complete Spanish reason; English is unchanged', () => {
  const sp = (s, key = 'reason') => resolveStatusText(s[key], s.copy[key], 'es');
  assert.equal(sp(status('none')), 'No hay datos actuales de frentes: aún no se publican frentes de temperatura mar adentro para esta región.');
  assert.equal(sp(status('error')), 'No hay datos actuales de frentes: no se pudo leer el archivo de frentes de la región o no pasó sus comprobaciones.');
  assert.equal(sp(status(frontsDoc(60))), 'No hay datos actuales de frentes: los frentes más recientes superan su límite de antigüedad de 48 horas o no tienen una hora de observación utilizable.');
  assert.match(sp(status(frontsDoc(80, {max_age_hours: 200}))), /límite de antigüedad de 72 horas/, 'the 72-hour cap');
  assert.match(sp(status(frontsDoc(1, {max_age_hours: 6, observed_at: 'bad', fronts: []}))), /límite de antigüedad de 6 horas/, 'a custom shorter limit');
  assert.equal(sp(status(frontsDoc(1, {fronts: []}))), 'No se encontró ningún frente en el análisis observado hace 1 hora.', 'a fresh analysis with no front is not a refusal');
  assert.equal(sp(status(frontsDoc(1, {fronts: []})), 'note'), 'sin frente · observado hace 1 hora');
  assert.equal(sp(status('none'), 'note'), 'sin datos actuales de frentes');
  assert.equal(frontsStatus(true, null, NOW).copy.reason[0].id, 'mark.layer.fronts.status.loading');
  assert.equal(sp(frontsStatus(true, null, NOW), 'note'), 'cargando');
  for (const s of [status('none'), status('error'), status(frontsDoc(60)), status(frontsDoc(1, {fronts: []})), frontsStatus(true, null, NOW)])
    for (const key of ['note', 'reason']) assert.equal(statusIn(s.copy[key], 'en'), s[key], `English ${key} is byte-identical`);
  // A refusal never reads as a found front, and off says nothing.
  assert.equal(frontsStatus(false, null, NOW).copy, undefined);
  assert.equal(status('error').drawn, null);
});

test('front_card_and_basis: age words use the same buckets; the safety statements, credit and uncertainty survive', () => {
  const at = h => frontsStatus(true, {state: 'ready', doc: readFronts(frontsDoc(h), 'test-coast')}, NOW);
  const note = (h, lang) => statusText(at(h).note, at(h).copy.note, lang).text;
  assert.equal(note(0.01, 'es'), '1 frente · observado hace menos de un minuto');
  assert.equal(note(1 / 60, 'es'), '1 frente · observado hace 1 minuto');
  assert.equal(note(6, 'es'), '1 frente · observado hace 6 horas');
  assert.equal(note(1, 'es'), '1 frente · observado hace 1 hora');
  assert.equal(note(47.9, 'es'), '1 frente · observado hace 47 horas');
  assert.equal(note(48, 'es'), '1 frente · observado hace 2 días');
  for (const h of [0.001, 0.5, 1 / 60, 1, 6, 47.9, 48, 60]) { const s = at(Math.min(h, 47)); assert.equal(statusIn(s.copy.note, 'en'), s.note); }
  for (const h of [0.001, 1 / 60, 0.5, 1, 6, 47]) { const s = at(h); assert.equal(statusIn(s.copy.stamp, 'en'), `Fixture product · ${s.note}`); assert.equal(statusIn(s.copy.basis, 'en'), s.basis); }
  const s = at(6), basis = statusText(s.basis, s.copy.basis, 'es');
  assert.equal(basis.translated, true);
  assert.ok(basis.text.includes('observado hace 6 horas'));
  assert.ok(basis.text.includes('la posición es incierta según el error declarado del propio análisis dividido por la intensidad del frente, a cada lado de la línea.'));
  assert.ok(basis.text.includes('Se retira al superar su límite de antigüedad de 48 horas. Solo agua superficial; un frente es un borde para orientar la búsqueda, no un pez ni un lugar de captura.'));
  assert.ok(basis.text.endsWith(' Crédito: NOAA CoastWatch.'));
  const noCredit = frontsStatus(true, {state: 'ready', doc: readFronts(frontsDoc(6, {credit: ''}), 'test-coast')}, NOW);
  assert.ok(!statusText(noCredit.basis, noCredit.copy.basis, 'es').text.includes('Crédito'));
  assert.equal(statusIn(noCredit.copy.basis, 'en'), noCredit.basis);
  const mark = frontsMark(s.drawn, {lon: -120.9, lat: 35.1}, NOW);
  const sm = es(mark);
  assert.equal(sm.name, 'Frente de temperatura'); assert.equal(sm.kind, 'Observado hace 6 horas');
  assert.equal(sm.reading, '0,20 °C por km, posición incierta en unos ±1,5 km (error del análisis 0,30 °C)');
  assert.equal(sm.source, 'Fixture product · observado hace 6 horas');
  assert.equal(en(mark).reading, mark.reading);
});

test('evidence_status_sinks: the rail and state carry parts; a borrowed screen note keeps the screen\'s own descriptor; no refetch on a language change', async t => {
  globalThis.location = {href: 'https://s.test/map?region=morro-bay&layers=fleet'};
  configureStore({v2: true, storage: null});
  syncFromURL(location.href);
  let fetched = 0;
  const fetchFn = async url => { fetched++; return {ok: true, json: async () => json(`dist/${new URL(url).pathname.slice(1)}`)}; };
  const engine = signal({setOverlay() {}, setData() {}});
  markScreen.value = CHECKING;
  markData.value = {region: {...REGION, id: 'morro-bay'}, atlas: null, survey: null, geology: null};
  const grounds = createCharterGrounds({engine, fetchFn, page: () => location.href, palette: () => sentinel});
  const ais = createCommercialAis({engine, fetchFn, page: () => location.href, palette: () => sentinel});
  aisOn.value = true;
  t.after(() => { grounds.destroy(); ais.destroy(); markData.value = null; markScreen.value = CHECKING; aisOn.value = false; species.value = null; });
  await flush(); await flush();
  assert.equal(groundsState.value.note, CHECKING.note, 'a borrowed screen note is the screen\'s own');
  assert.deepEqual(groundsState.value.copy.note, CHECKING.noteCopy);
  assert.equal(statusText(groundsState.value.note, groundsState.value.copy.note, 'es').translated, true);
  assert.deepEqual(aisState.value.copy.note, CHECKING.noteCopy);
  markScreen.value = {...CHECKING, noteCopy: undefined};
  assert.equal(groundsState.value.copy, undefined, 'a screen without parts is shown unchanged (labelled English), never guessed');
  assert.equal(statusText(groundsState.value.note, groundsState.value.copy?.note, 'es').text, CHECKING.note);
  markScreen.value = READY; await flush();
  assert.equal(railNotes.value.fleet, '2 charter grounds');
  assert.equal(statusText(railNotes.value.fleet, railNoteCopies.value.fleet, 'es').text, '2 zonas chárter');
  assert.equal(statusText(railNotes.value.fleet, railNoteCopies.value.fleet, 'en').text, '2 charter grounds');
  const asked = fetched;
  assert.equal(statusText(aisState.value.note, aisState.value.copy.note, 'es').text, '3 celdas históricas de cuadrícula · jul y sep de 2024 · profundidad desconocida');
  statusText(aisState.value.note, aisState.value.copy.note, 'en');
  assert.equal(fetched, asked, 'a language switch resolves text only');
  species.value = 'halibut'; await flush();
  assert.equal(groundsState.value.note, NOTES.species);
  assert.equal(statusText(groundsState.value.note, groundsState.value.copy.note, 'es').text, 'Esta capa solo admite lingcod y rockfish.');
  assert.equal(statusText(railNotes.value.fleet, railNoteCopies.value.fleet, 'es').text, 'Esta capa solo admite lingcod y rockfish.');
});

test('evidence_catalogue_negative_controls: placeholders match, unknown parts fall back, nothing leaks into the data', () => {
  const ids = Object.keys(strings.strings).filter(k => /^mark\.layer\.(grounds|ais|fronts)\./.test(k));
  assert.ok(ids.length >= 40);
  const holes = s => [...s.matchAll(/\{(\w+)\}/g)].map(m => m[1]).sort().join();
  for (const id of ids) { const e = strings.strings[id]; assert.ok(e.es && e.es.trim(), `${id}: Spanish value`); assert.equal(holes(e.es), holes(e.en), `${id}: same placeholders`); }
  assert.equal(resolveStatusText('Producer line', [{id: 'mark.layer.grounds.status.nope'}], 'es'), 'Producer line');
  assert.equal(resolveStatusText('Producer line', undefined, 'es'), 'Producer line');
  const g = groundMark(ground, GROUNDS), a = aisMark(cell);
  assert.equal(es({...g, copy: undefined}).reading, g.reading, 'a mark with no descriptor is shown as it is');
  for (const mark of [g, a]) assert.ok(!JSON.stringify(Object.fromEntries(Object.entries(mark).filter(([k]) => k !== 'copy'))).includes('mark.layer.'), 'descriptors stay in copy only');
});
