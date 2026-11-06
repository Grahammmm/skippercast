// SC1137-05: the words web/ranking.ts and web/area-reasons.ts write for the Where to look list read Spanish on a Spanish page, from catalogue
// parts the producers attach, while every plain English field (what the Run line, the planner and the exports read) stays exactly as it was.
// Offline: the committed Morro Bay atlas, synthetic reviewed reefs and a synthetic publication.
import assert from 'node:assert/strict';
import {mkdtemp} from 'node:fs/promises';
import {readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {pathToFileURL} from 'node:url';
import {isDeepStrictEqual} from 'node:util';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import catalogue from '../catalog/app/strings.json' with {type: 'json'};
import {rankedHabitat} from '../packages/coast/src/coast3d/regional.ts';
import {CHECKING, assessScreen} from '../web/map/habitat.ts';
import {ranking} from '../web/ranking.ts';
import {MAX_REASONS, NO_REASONS, reasonsFor, targetEvidence} from '../web/area-reasons.ts';
import {partsText, pickFit, pickName, pickReason, rankingAbout, rankingBasis, rankingEmpty, rankingLabel, reasonText} from '../web/brief/ranking-copy.ts';

const ROOT = new URL('..', import.meta.url).pathname, NOW = Date.now();
const read = path => JSON.parse(readFileSync(new URL(`../dist/${path}`, import.meta.url), 'utf8'));
const DATA = {region: {...read('regions/morro-bay/region.json'), id: 'morro-bay'}, atlas: read('data/atlas.json'), survey: null, geology: null};
const CHECKED = assessScreen({areas: read('data/protected-areas.geojson').features, checkedAt: new Date(NOW).toISOString(), live: true}, NOW);
const LATER = new Date(NOW + 86400000).toISOString();
const reef = (id, props = {}) => ({type: 'Feature', id, geometry: {type: 'Polygon', coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]]}, properties: {
  id, region: 'morro-bay', exportable: true, screen_status: 'pass', screen_expires_at: LATER, waypoint_latitude: 35.3, waypoint_longitude: -120.95,
  depth_min_ft: 40, depth_max_ft: 80, terrain_score: 70, terrain_grade: 'B', fit_lingcod: 2, fit_rockfish_reef: 2, fit_gopher_rockfish: 3, fit_cabezon_shallow_reef: 2, ...props}});
const READY = {state: 'ready', features: [reef('t-a', {fit_lingcod: 3}), reef('t-b', {terrain_grade: '', terrain_score: 55.5}), reef('t-c', {fit_lingcod: 9})], expiresAt: NOW + 3600000, rank: rankedHabitat};
const WATER = () => ({state: 'water'}), UNKNOWN = () => ({state: 'unknown', reason: 'edge'}), PENDING = () => ({state: 'unknown', reason: 'pending'});
const inputs = (patch = {}) => ({region: 'morro-bay', profile: 'boat', target: 'lingcod', coast: 'lingcod', data: DATA, screen: CHECKED, terrain: {state: 'unavailable'}, now: NOW, place: WATER, ...patch});
// The words English never uses in a Spanish sentence of this list.
const ENGLISH = /\b(?:the|and|with|for|ranked|marks|within|from|only|your|listed|check|reef|score|grade|terrain|places|shoreline|withheld)\b/i;
const en = parts => partsText(parts, 'en'), es = parts => partsText(parts, 'es');

/** Every plain field a list has stays what its parts say in English; the parts in Spanish read Spanish. Returns the Spanish texts. */
function both(r, what) {
  assert.ok(r.copy, `${what}: the list carries parts`);
  const out = {};
  for (const [key, plain] of [['label', r.label], ['basis', r.basis], ['empty', r.empty]]) {
    if (!r.copy[key]) { assert.ok(key !== 'label' || !r.source, `${what}: ${key} has parts when there is a source`); continue; }
    assert.equal(en(r.copy[key]), plain, `${what}: ${key} in English is the plain field`);
    out[key] = es(r.copy[key]);
    assert.notEqual(out[key], plain, `${what}: ${key} reads Spanish`);
    assert.doesNotMatch(out[key], ENGLISH, `${what}: ${key} has no English word left: ${out[key]}`);
  }
  return out;
}

test('ranking_es_all_sources_and_states: every label, basis and empty line of every production branch reads Spanish and keeps its English', () => {
  const home = {latitude: 35.37, longitude: -120.86, name: 'Morro Bay'};
  // Atlas, with a range, then withheld, pending, and the screen's own notes.
  const atlas = ranking(inputs({reachNm: 12.5}));
  let s = both(atlas, 'atlas');
  assert.match(s.label, /^Atlas de arrecifes cartografiados$/); assert.match(s.basis, /desde Morro Bay\. Solo se muestran los lugares dentro de tu alcance de 12,5 nm\./);
  assert.match(s.basis, /Un lugar clasificado es un lugar donde buscar; la presencia de peces no está verificada\.$/);
  assert.match(s.basis, /Se omiten los lugares en tierra, a menos de 25 m de la línea costera de NOAA/);
  assert.equal(rankingAbout(atlas, 'es'), 'Acerca de la clasificación del atlas de arrecifes cartografiados');
  assert.equal(rankingAbout(atlas, 'en'), 'About the survey reef atlas ranking');
  const held = ranking(inputs({place: UNKNOWN, reachNm: 12}));
  s = both(held, 'atlas withheld');
  assert.ok(held.withheld > 1 && !held.picks.length);
  assert.match(s.empty, new RegExp(`^${held.withheld} lugares omitidos: no se ha confirmado si son tierra o agua\\. No hay otras marcas de arrecife cartografiadas dentro de 300 ft y 12 nm de Morro Bay para este objetivo\\.$`));
  assert.match(s.basis, /lugares omitidos: no se ha confirmado si son tierra o agua\.$/);
  s = both(ranking(inputs({place: PENDING})), 'atlas pending'); assert.equal(s.empty, 'Comprobando tierra y agua para estos lugares…');
  s = both(ranking(inputs({screen: CHECKING})), 'atlas screen checking'); assert.match(s.empty, /^Comprobando áreas protegidas/);
  s = both(ranking(inputs({screen: {...CHECKED, status: 'stale', note: 'Boundary check stale; fishing targets withheld', noteCopy: [{id: 'mark.layer.habitat.screen.stale'}]}})), 'atlas stale');
  assert.match(s.empty, /^Comprobación de límites desactualizada/);
  const custom = ranking(inputs({screen: {...CHECKED, status: 'unavailable', note: 'A custom note nobody translated'}}));
  assert.equal(custom.empty, 'A custom note nobody translated'); assert.equal(custom.copy.empty, undefined, 'an unknown note keeps its supplied words and is never promoted to a clear check');
  assert.equal(rankingEmpty(custom, 'es'), 'A custom note nobody translated');
  // Spanish unrated-by-range empty line, no harbor position, an unnamed harbor.
  s = both(ranking(inputs({reachNm: 0.1})), 'atlas none'); assert.match(s.empty, /^No hay marcas de arrecife cartografiadas dentro de 300 ft y 0,1 nm de Morro Bay para este objetivo\.$/);
  const noHarbor = ranking(inputs({data: {...DATA, region: {...DATA.region, harbor: undefined}}}));
  s = both(noHarbor, 'no harbor'); assert.match(s.basis, /desde el puerto de la región, que aquí no tiene una posición publicada, por lo que no se muestra ninguna distancia\./);
  const unnamed = ranking(inputs({data: {...DATA, region: {...DATA.region, harbor: {latitude: 35.37, longitude: -120.86}}}}));
  s = both(unnamed, 'unnamed harbor'); assert.match(s.basis, /desde el puerto\. /);
  const named = ranking(inputs({origin: {...home, name: 'the harbor'}}));
  assert.match(es(named.copy.basis), /desde the harbor\. /, 'a published name is never translated'); assert.equal(en(named.copy.basis), named.basis);
  // Spear: the swim limit, applied and not applied.
  const lines = [[[-120.96, 34.9], [-120.96, 35.5]]];
  const swum = ranking(inputs({profile: 'spear', shore: {maxYd: 1200, lines}})); s = both(swum, 'swim');
  assert.match(s.basis, /Solo se muestran lugares a 1200 yd o menos de la línea costera cartografiada, medidos en línea recta hasta la línea general simplificada, por lo que la distancia es aproximada y no es una ruta para nadar\./);
  s = both(ranking(inputs({profile: 'spear', shore: {maxYd: 1200, lines: null}})), 'swim off'); assert.match(s.basis, /No se aplica tu límite de nado: la línea costera desde la que medir no se ha cargado, o esta región no tiene ninguna\./);
  s = both(ranking(inputs({profile: 'spear', shore: {maxYd: 20, lines}})), 'swim empty'); assert.match(s.empty, /dentro de 60 ft y 20 yd de la costa para este objetivo\.$/);
  // Terrain, publication and the sourceless lines.
  const terrain = ranking(inputs({terrain: READY})); assert.equal(terrain.source, 'terrain'); s = both(terrain, 'terrain');
  assert.equal(s.label, 'Hábitat del terreno revisado'); assert.match(s.basis, /^Hábitat de terreno costero revisado que pasa la revisión vigente de áreas protegidas y cierres/);
  assert.match(both(ranking(inputs({terrain: READY, place: UNKNOWN})), 'terrain withheld').empty, /No hay otro hábitat de terreno revisado dentro de 300 ft/);
  assert.match(both(ranking(inputs({terrain: READY, screen: CHECKING})), 'terrain checking').empty, /^Comprobando áreas protegidas/);
  assert.equal(both(ranking(inputs({missing: true})), 'missing').empty, 'No hay lugares clasificados: esta región no existe.');
  assert.equal(both(ranking(inputs({profile: 'shore'})), 'shore').empty, 'Las salidas desde la costa y su estado de revisión se muestran en la Carta.');
  assert.equal(both(ranking(inputs({data: null})), 'map loading').empty, 'Los lugares clasificados se cargan con el mapa.');
  const pending = ranking(inputs({originPending: true})); s = both(pending, 'home port');
  assert.equal(s.empty, 'Buscando tu puerto base…'); assert.equal(s.basis, 'Las distancias parten de tu puerto base, que todavía se está cargando.'); assert.equal(s.label, 'Atlas de arrecifes cartografiados');
  assert.equal(both(ranking(inputs({originPending: true, data: null})), 'home port, no source').empty, 'Buscando tu puerto base…');
  assert.ok(isDeepStrictEqual(ranking(inputs()).picks.map(p => p.id), ranking(inputs({originPending: false})).picks.map(p => p.id)), 'the picks are the picks');
});

// A seafloor publication in the loadReefTrip shape (as tests/test_ranking_publication.mjs builds it).
const box = (w, s, e, n) => ({type: 'Polygon', coordinates: [[[w, s], [e, s], [e, n], [w, n], [w, s]]]});
const target = (id, lat, lon, depth, fit, extra = {}) => ({id, canonical_habitat: true, name: id, label: 'Surveyed reef habitat', latitude: lat, longitude: lon, neighborhood_depth_ft: depth, habitat_score: 50,
  species_fit: {lingcod: fit, 'rockfish-reef': fit}, resolution_m: 2, evidence_confidence: {percent: 80}, area_ids: [id], ...extra});
const TARGETS = [target('p-a', 35.30, -120.95, [40, 80], 3, {terrain_interpretation: 'Ledge and boulders.'}), target('p-b', 35.32, -120.95, [60, 110], 2)];
const LOADED = {targets: TARGETS, areas: TARGETS.map(t => ({id: t.id, geometry: box(t.longitude - 0.002, t.latitude - 0.002, t.longitude + 0.002, t.latitude + 0.002)})),
  publication: {status: 'ready', region: 'morro-bay', archive_sha256: 'a'.repeat(64), export_sha256: 'b'.repeat(64), expires_at: new Date(NOW + 3600000).toISOString()}};
const SCREEN_OK = {state: 'loaded', region: 'morro-bay', screen: {ready: () => true, pointAllowed: () => true, geometryAllowed: () => true}};
const PUB = {state: 'ready', region: 'morro-bay', loaded: LOADED};

test('ranking_es_all_sources_and_states: the seafloor publication list, its checking, not-current and loading lines', () => {
  const pub = patch => ranking(inputs({publication: PUB, plannerScreen: SCREEN_OK, ...patch}));
  const r = pub({}); assert.equal(r.source, 'publication'); let s = both(r, 'publication');
  assert.equal(s.label, 'Publicación de arrecifes del fondo marino'); assert.match(s.basis, /^Lugares de la publicación de arrecifes del fondo marino que usa el planificador de viajes/);
  assert.equal(rankingAbout(r, 'es'), 'Acerca de la clasificación de la publicación de arrecifes del fondo marino');
  s = both(pub({plannerScreen: {state: 'loaded', region: 'morro-bay', screen: {...SCREEN_OK.screen, ready: () => false}}}), 'publication not current');
  assert.equal(s.empty, 'La revisión de áreas protegidas no está actualizada · se omiten los lugares de pesca');
  s = both(pub({plannerScreen: {state: 'failed'}}), 'publication failed'); assert.match(s.empty, /^La revisión de áreas protegidas no está actualizada/);
  s = both(pub({plannerScreen: {state: 'loading'}}), 'publication checking'); assert.match(s.empty, /^Comprobando áreas protegidas/);
  s = both(pub({publication: {state: 'loading', region: 'morro-bay'}}), 'publication loading'); assert.equal(s.empty, 'Cargando los lugares de arrecife clasificados…');
  s = both(pub({place: UNKNOWN}), 'publication withheld'); assert.match(s.empty, /^\d+ lugares? omitidos?: no se ha confirmado si .* No hay otros lugares de arrecife clasificados dentro de 300 ft para este objetivo\.$/);
  const none = pub({publication: {...PUB, loaded: {...LOADED, targets: []}}}); s = both(none, 'publication none');
  assert.match(s.empty, /^Ningún lugar de arrecife clasificado pasa la revisión vigente de áreas protegidas dentro de 300 ft para este objetivo\.$/);
});

test('ranking_es_fit_and_generated_reason_variants: fit strength 1-3, combined and known targets, grade present or absent, relief and nearby reasons, swim distance', () => {
  // Reviewed terrain habitat: the fit strength, a target with no fit field, and the grade.
  const habitat = coast => ranking(inputs({terrain: READY, coast, target: coast, profile: 'boat'})).picks;
  const lingcod = habitat('lingcod'), byId = Object.fromEntries(lingcod.map(p => [p.id, p]));
  assert.equal(pickFit(byId['t-a'], 'es'), 'Afinidad del hábitat para lingcod: 3 de 3'); assert.equal(pickFit(byId['t-a'], 'en'), 'Fits lingcod habitat 3 of 3');
  assert.equal(pickFit(byId['t-c'], 'es'), 'Hábitat de arrecife revisado', 'a fit outside 1-3 is the screened-habitat line'); assert.equal(byId['t-c'].fit, 'Screened reef habitat');
  assert.equal(pickReason(byId['t-a'], 'es'), 'Puntuación del terreno 70/100 · grado B.'); assert.equal(byId['t-a'].reason, 'Terrain score 70/100 · grade B.');
  assert.equal(pickReason(byId['t-b'], 'es'), 'Puntuación del terreno 55.5/100.'); assert.equal(byId['t-b'].reason, 'Terrain score 55.5/100.');
  assert.equal(pickName(byId['t-a'], 'es'), 'Hábitat de arrecife'); assert.equal(byId['t-a'].name, 'Reef habitat', 'the plain name stays English for the Run line and exports');
  for (const [coast, label, es_] of [['rockfish-reef', 'reef rockfish', 'rockfish de arrecife'], ['gopher-rockfish', 'gopher rockfish', 'rockfish gopher'], ['cabezon-shallow-reef', 'cabezon', 'cabezón']]) {
    const p = habitat(coast).find(x => x.fit.startsWith('Fits')); assert.ok(p, coast);
    assert.equal(en(p.copy.fit), p.fit); assert.match(p.fit, new RegExp(`^Fits ${label} habitat [1-3] of 3$`)); assert.match(pickFit(p, 'es'), new RegExp(`^Afinidad del hábitat para ${es_}: [1-3] de 3$`));
  }
  const all = habitat('all'); assert.ok(all.length && all.every(p => p.fit === 'Screened reef habitat' && pickFit(p, 'es') === 'Hábitat de arrecife revisado'));
  // Atlas marks: the combined fit names both screens, the unrated line, and the generated relief and nearby-habitat reasons.
  const atlas = (t) => ranking(inputs({target: t, coast: t === 'reef' ? 'all' : t === 'rockfish' ? 'rockfish-reef' : t})).picks;
  const lc = atlas('lingcod'), rf = atlas('rockfish'), reefAll = atlas('reef');
  assert.ok(lc.length && rf.length && reefAll.length);
  for (const p of lc) { assert.equal(en(p.copy.reason), p.reason, 'relief: the same English'); assert.match(pickReason(p, 'es'), /^\d+,\d m de relieve local; \d+% de cobertura rugosa cartografiada\.$/); }
  for (const p of rf) { assert.equal(en(p.copy.reason), p.reason); assert.match(pickReason(p, 'es'), /^\d+,\d ha de hábitat rugoso cercano; \d+% de cobertura rugosa cartografiada\.$/); }
  for (const p of reefAll) { assert.equal(en(p.copy.fit), p.fit); assert.match(pickFit(p, 'es'), /^Afinidad del hábitat para lingcod y rockfish: [1-3] de 3$/); }
  const unrated = atlas('halibut'); for (const p of unrated) { assert.equal(p.fit, 'Habitat fit unrated for this target'); assert.equal(pickFit(p, 'es'), 'Afinidad del hábitat sin calificar para este objetivo'); }
  // A mark with no species screen and its own published sentence keeps the published words; one without, the generated sentence.
  const generated = ranking(inputs({target: 'halibut', coast: 'halibut', data: {...DATA, atlas: {...DATA.atlas, targets: DATA.atlas.targets.slice(0, 3).map((t, i) => ({...t, metrics: undefined, terrain_interpretation: i ? 'Published note.' : undefined, habitat_grade: 'A'}))}}}));
  for (const p of generated.picks.length ? generated.picks : []) assert.ok(p.reason === 'Published note.' ? pickReason(p, 'es') === 'Published note.' : pickReason(p, 'es') === 'Terreno de arrecife cartografiado.');
  // Spear's swim distance, in yards rounded to 25.
  const lines = [[[-120.96, 34.9], [-120.96, 35.5]]];
  const swim = ranking(inputs({terrain: {...READY, features: [reef('s-a', {depth_max_ft: 55})]}, profile: 'spear', coast: 'cabezon-shallow-reef', target: 'cabezon-shallow-reef', shore: {maxYd: 1200, lines}})).picks;
  assert.ok(swim.length); for (const p of swim) { assert.match(p.distance, /^~\d+ yd from shore$/); assert.equal(partsText(p.copy.distance, 'en'), p.distance); assert.match(partsText(p.copy.distance, 'es'), /^~\d+ yd de la costa$/); }
});

test('ranking_es_provenance_not_text_matching: only the sentences the code wrote are translated; published prose that reads the same stays as published', () => {
  const base = {id: 'x1', label: 'X', latitude: 35.3, longitude: -120.9, survey_year: 2019, source_name: 'USGS survey'};
  const atlas = {title: 'Survey reef atlas', source_validation_date: '2026-01-05'};
  const generated = reasonsFor('x1', targetEvidence({...base, qualification: {closure_clearance_m: 123.6}}, atlas), NOW);
  const byKind = Object.fromEntries(generated.map(r => [r.date === '2019' ? 'survey' : 'screen', r]));
  assert.equal(byKind.survey.text, 'Surveyed reef terrain.'); assert.equal(reasonText(byKind.survey, 'es'), 'Terreno de arrecife cartografiado.'); assert.equal(reasonText(byKind.survey, 'en'), 'Surveyed reef terrain.');
  assert.equal(byKind.screen.text, 'Passed the protected-area check with 124 m clearance.'); assert.equal(reasonText(byKind.screen, 'es'), 'Pasó la revisión de áreas protegidas con 124 m de separación.');
  assert.equal(byKind.screen.source, 'Survey reef atlas', 'the source title is published and stays'); assert.equal(byKind.screen.date, '2026-01-05');
  const published = reasonsFor('x1', targetEvidence({...base, terrain_interpretation: 'Surveyed reef terrain.'}, null), NOW);
  assert.equal(published.length, 1); assert.equal(published[0].copy, undefined, 'a published sentence equal to the generated one is not tagged'); assert.equal(reasonText(published[0], 'es'), 'Surveyed reef terrain.');
  // A record that arrived as data cannot claim to be a generated sentence, and the cap, dates and identity are unchanged.
  const feed = JSON.parse(JSON.stringify([{area: 'x1', kind: 'report', text: 'Passed the protected-area check with 9 m clearance.', date: '2026-02-01', source: 'A feed', copy: {key: 'clearance', m: 9}}]));
  const fed = reasonsFor('x1', feed, NOW); assert.equal(fed.length, 1); assert.equal(fed[0].copy, undefined); assert.equal(reasonText(fed[0], 'es'), 'Passed the protected-area check with 9 m clearance.');
  const many = reasonsFor('x1', [...targetEvidence({...base, qualification: {closure_clearance_m: 5}}, atlas), ...Array.from({length: 5}, (_, i) => ({area: 'x1', kind: `k${i}`, text: `Note ${i}`, date: `2026-01-0${i + 1}`, source: 'S'}))], NOW);
  assert.equal(many.length, MAX_REASONS);
  assert.deepEqual(reasonsFor('x1', [], NOW), [], 'no dated evidence: no invented reason');
  assert.equal(NO_REASONS, 'No dated evidence for this area yet');
});

async function loadWR() {
  const out = join(await mkdtemp(join(tmpdir(), 'rank-i18n-')), 'wr.mjs');
  await build({stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {WhereToLook} from './web/brief/WhereToLook.tsx';
      export {language} from './web/i18n.ts';
      export {profile, region, selection} from './web/state.ts';
      export {markData} from './web/map/marks.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
  bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins});
  return import(pathToFileURL(out).href);
}

test('ranking_en_es_en_and_export_isolation: the real list renders Spanish and back to the same English bytes; the plain fields never change with the language', async () => {
  const m = await loadWR(), r = ranking(inputs({reachNm: 12})), before = JSON.stringify({...r, copy: undefined, picks: r.picks.map(p => ({...p, copy: undefined}))});
  try {
    m.profile.value = 'spear'; m.region.value = 'morro-bay'; m.markData.value = DATA;
    m.language.value = 'en'; const english = m.render(m.h(m.WhereToLook, {ranking: r}));
    m.language.value = 'es'; const spanish = m.render(m.h(m.WhereToLook, {ranking: r}));
    assert.ok(spanish.includes('Atlas de arrecifes cartografiados') && spanish.includes('Acerca de la clasificación del atlas de arrecifes cartografiados'), 'label and about');
    assert.ok(spanish.includes(rankingBasis(r, 'es').replace(/&/g, '&amp;')) && spanish.includes('la presencia de peces no está verificada'), 'basis');
    assert.ok(spanish.includes('Afinidad del hábitat para lingcod:') && spanish.includes('de relieve local') && !spanish.includes('Fits lingcod'), 'fit and reason');
    assert.ok(english.includes('Survey reef atlas') && english.includes('About the survey reef atlas ranking') && english.includes('Fits lingcod habitat') && english.includes('fish presence is unverified.'));
    assert.ok(english.includes(r.basis), 'English shows the plain basis sentence');
    m.language.value = 'en'; assert.ok(m.render(m.h(m.WhereToLook, {ranking: r})) === english, 'en to es to en: the same English page');
    // The empty lines and the selected pick's reasons.
    const empty = ranking(inputs({reachNm: 0.1}));
    m.language.value = 'es'; assert.ok(m.render(m.h(m.WhereToLook, {ranking: empty})).includes(es(empty.copy.empty)));
    m.language.value = 'en'; assert.ok(m.render(m.h(m.WhereToLook, {ranking: empty})).includes(empty.empty));
    const withClearance = r.picks.find(p => DATA.atlas.targets.find(t => t.id === p.id)?.recorded_validation?.closed_or_screened_area_clearance_m > 0);
    if (withClearance) {
      m.selection.value = withClearance.id;
      m.language.value = 'es'; assert.match(m.render(m.h(m.WhereToLook, {ranking: r})), /Pasó la revisión de áreas protegidas con \d+ m de separación\./);
      m.language.value = 'en'; assert.match(m.render(m.h(m.WhereToLook, {ranking: r})), /Passed the protected-area check with \d+ m clearance\./);
      m.selection.value = null;
    }
    m.language.value = 'es'; m.markData.value = {...DATA, atlas: {...DATA.atlas, targets: DATA.atlas.targets.map(t => ({...t, recorded_validation: undefined, qualification: undefined}))}};
    m.selection.value = r.picks[0].id; assert.ok(m.render(m.h(m.WhereToLook, {ranking: r})).includes('Todavía no hay evidencia fechada para esta área') || /data-why="reasons"/.test(m.render(m.h(m.WhereToLook, {ranking: r}))));
  } finally { m.language.value = 'en'; m.profile.value = 'boat'; m.selection.value = null; m.markData.value = null; m.region.value = null; }
  assert.equal(JSON.stringify({...r, copy: undefined, picks: r.picks.map(p => ({...p, copy: undefined}))}), before, 'rendering changed no plain field');
});

test('ranking_copy_exhaustive_and_safe: every ranking.* entry keeps its placeholders in both languages, markup-like names are escaped once, and a list without parts is shown as it came', async () => {
  const vars = text => [...new Set([...text.matchAll(/\{(\w+)\}/g)].map(x => x[1]))].sort();
  const ids = Object.keys(catalogue.strings).filter(id => id.startsWith('ranking.'));
  assert.ok(ids.length >= 45);
  for (const id of ids) {
    const e = catalogue.strings[id]; assert.ok(e.en && e.es, `${id} has both`);
    assert.deepEqual(vars(e.es), vars(e.en), `${id}: the same placeholders`);
  }
  // Every id the producers can name exists.
  const source = readFileSync(join(ROOT, 'web/ranking.ts'), 'utf8');
  for (const m of source.matchAll(/rp\('([\w.-]+)'/g)) assert.ok(Object.hasOwn(catalogue.strings, `ranking.${m[1]}`), `ranking.${m[1]}`);
  const m = await loadWR(), MARKUP = '<img src=x onerror=alert(1)> Cove';
  try {
    m.language.value = 'es'; m.profile.value = 'boat';
    const marked = ranking(inputs({origin: {latitude: 35.37, longitude: -120.86, name: MARKUP}}));
    const html = m.render(m.h(m.WhereToLook, {ranking: marked}));
    assert.ok(!html.includes('<img') && html.includes('desde &lt;img src=x onerror=alert(1)> Cove.'), 'the published name is text, once');
    const plain = {source: 'atlas', label: 'Survey reef atlas', basis: 'Custom basis.', empty: '', picks: [{id: 'z', kind: 'spot', name: 'Z', distance: '1.0 nm', nm: 1, depth: '~40–80 ft', fit: 'Fits', reason: 'Hard bottom.', at: {latitude: 1, longitude: 1}, screen: {inside: false, name: null, distanceM: null, screened: true}}]};
    const out = m.render(m.h(m.WhereToLook, {ranking: plain}));
    assert.ok(out.includes('Survey reef atlas') && out.includes('Custom basis.') && out.includes('Hard bottom.') && out.includes('Fits'), 'no parts: shown as supplied');
    assert.equal(rankingLabel(plain, 'es'), 'Survey reef atlas'); assert.equal(pickName(plain.picks[0], 'es'), 'Z');
  } finally { m.language.value = 'en'; }
});
