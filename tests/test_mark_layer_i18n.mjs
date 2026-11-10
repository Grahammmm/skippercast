// SC0922-10: the name, kind, reading, source and basis lines the surveyed mark layers write (web/map/seafloor.ts, habitat.ts,
// depth-contours.ts) follow the card's language at render. Each card carries catalogue parts (`copy`, `copyTerms`); English is the
// producer's own text, byte for byte, and published prose (terrain_interpretation, limitations, derivation, credits, rights, names)
// is carried verbatim. Synthetic marks and the committed region files only; no network.
import './helpers/spanish-ready.mjs';   // SC1407-09: the Spanish table, before the Spanish renders
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {preparedRendererPlugins} from './helpers/esbuild-url.mjs';
import {STRINGS} from '../web/i18n.ts';
import {copyText, resolveMarkCopy} from '../web/mark-copy.ts';
import {admitCell, admitHabitat, cellMark, seafloorMark} from '../web/map/seafloor.ts';
import {assessScreen, atlasCard, geologyCard, receiptCard, regulationsCopy, regulationsLink, surveyCard, terrainCard, terrainDetailCard, withheld, withheldCard} from '../web/map/habitat.ts';
import {contourMark, omittedCopy, omittedNote} from '../web/map/depth-contours.ts';

const ROOT = new URL('..', import.meta.url).pathname;
const read = path => JSON.parse(readFileSync(new URL(`../dist/${path}`, import.meta.url), 'utf8'));
const MORRO = read('regions/morro-bay/region.json'), ATLAS = read('data/atlas.json');
const CAMBRIA = read('regions/cambria-san-simeon/region.json');
const SURVEY = read('regions/cambria-san-simeon/survey-habitat.geojson'), GEOLOGY = read('regions/cambria-san-simeon/geology.geojson');
const SOCAL = read('regions/southern-california/region.json'), SOCAL_ATLAS = read('regions/southern-california/atlas.json');

// ---- seafloor
const RIGHT = {source_id: 's1', attribution: 'Lab A', notice: 'Notice A.', policy_url: 'https://example.org/terms'};
const PUB = {screened: new Set(['r1']), rights: [{id: 'publication', credit: 'Pub Credit', notice: 'Pub notice.', policyURL: ''}]};
const feature = over => ({properties: {id: 'c1', reach: 'r1', status: 'habitat', screen: {status: 'pass'}, hold_reasons: [], source_rights: [RIGHT], depth_min_ft: 41.2, depth_max_ft: 90,
  terrain_grade: 'A', fit_lingcod: 3, fit_cabezon: 0, source_ids: ['s1'], source_year: 2010, resolution_m: 2, vertical_datum: 'MLLW', ...over}, geometry: {type: 'MultiPolygon', coordinates: []}});
const admit = over => admitHabitat(feature(over), PUB);
const BEDROCK = {classified_area: {profile: 'original-interpreted-bedrock-area-v1', interpretation_method: 'original-interpreted-bedrock-v1'}};

function seafloorCards() {
  const cards = {};
  const candidate = admit({});
  cards['candidate fit 3'] = seafloorMark(candidate, 'fit_lingcod');
  cards['candidate fit unknown'] = seafloorMark(candidate, 'fit_cabezon');
  cards['candidate terrain'] = seafloorMark(candidate, 'terrain');
  cards['candidate coarse, notice supplied, two terms'] = seafloorMark({...admit({resolution_m: 8, planning_notice: 'Supplied planning notice.'}),
    rights: [{id: 'a', credit: 'Lab A', notice: 'Notice A.', policyURL: 'https://example.org/a'}, {id: 'b', credit: 'Lab B', notice: 'Notice B.', policyURL: 'https://example.org/b'}]}, 'terrain');
  cards['candidate nothing known'] = seafloorMark(admit({terrain_grade: 'Z', depth_min_ft: null, depth_max_ft: null, source_year: null, resolution_m: null, vertical_datum: '', source_ids: []}), 'terrain');
  cards['search'] = seafloorMark(admit({status: 'search-area', search_area: {target_species: ['lingcod']}}), 'terrain');
  cards['interpreted bedrock'] = seafloorMark(admit({status: 'classified-area', ...BEDROCK, source_ids: ['s1', 's2']}), 'terrain');
  cards['interpreted rugose, no survey'] = seafloorMark(admit({status: 'classified-area', source_ids: []}), 'terrain');
  cards['cell named'] = cellMark(admitCell({properties: {id: 'x1', reach: 'r1', tier: 2, source_id: 'csumb-test-2m'}, geometry: {type: 'MultiPolygon', coordinates: []}}, PUB));
  cards['cell unnamed'] = cellMark(admitCell({properties: {id: 'x2', reach: 'r1', tier: 1}, geometry: {type: 'MultiPolygon', coordinates: []}}, PUB));
  return cards;
}

// ---- reef marks, survey habitat, geology, terrain
const poly = (x0, y0, x1, y1, props) => ({type: 'Feature', properties: props, geometry: {type: 'Polygon', coordinates: [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}});
const NOW = Date.parse('2026-11-05T12:00:00Z'), AT = '2026-11-05T11:00:00Z', OLD = '2026-10-01T00:00:00Z';
const spot = ATLAS.targets[0], data = {region: MORRO, atlas: ATLAS, survey: null, geology: null};
const around = (d, props) => poly(spot.longitude - d, spot.latitude - d, spot.longitude + d, spot.latitude + d, props);
const SCREENS = {
  checking: assessScreen(null, NOW),
  stale: assessScreen({areas: [], checkedAt: OLD, live: false}, NOW),
  unavailable: assessScreen({areas: null, checkedAt: null, live: false}, NOW),
  mpa: assessScreen({areas: [around(0.01, {NAME: 'Test MPA', Type: 'SMR'})], checkedAt: AT, live: true}, NOW),
  federal: assessScreen({areas: [], checkedAt: AT, live: false, closures: {areas: [around(0.01, {NAME: 'Test GEA', Type: 'GEA'})], checkedAt: OLD.replace('10-01', '11-04'), sha256: null}}, NOW),
  within: assessScreen({areas: [poly(spot.longitude - 0.01, spot.latitude + 0.0003, spot.longitude + 0.01, spot.latitude + 0.01, {NAME: 'Near MPA', Type: 'SMR'})], checkedAt: AT, live: false}, NOW),
  clear: assessScreen({areas: [], checkedAt: AT, live: false}, NOW),
};

function habitatCards() {
  const cards = {};
  cards['atlas lingcod'] = atlasCard(spot, data, 'lingcod');
  cards['atlas reef (two screens)'] = atlasCard(spot, data, 'reef');
  cards['atlas unrated, own regulations page'] = atlasCard(SOCAL_ATLAS.targets[0], {region: SOCAL, atlas: SOCAL_ATLAS, survey: null, geology: null}, 'halibut');
  cards['atlas minimal'] = atlasCard({id: 't9', label: 'Bare mark', latitude: 35.1, longitude: -120.8}, {region: MORRO, atlas: null, survey: null, geology: null}, 'lingcod');
  for (const [name, screen] of Object.entries(SCREENS)) cards[`withheld ${name}`] = withheldCard(spot, withheld(spot, screen, []) ?? {reading: '', inside: []}, screen);
  const sp = SURVEY.features[0].properties;
  cards['survey rock with margin'] = surveyCard(sp, SURVEY, CAMBRIA);
  cards['survey kelp, no margin, no name'] = surveyCard({id: 'k1', habitat_kind: 'kelp', source_date: '20200102'}, {type: 'FeatureCollection', features: []}, CAMBRIA);
  cards['survey mixed'] = surveyCard({id: 'k3', name: 'Mixed outline', habitat_kind: 'mixed', area_km2: 0.5}, {type: 'FeatureCollection', features: []}, CAMBRIA);
  cards['survey sediment'] = surveyCard({id: 'k4', name: 'Soft outline', habitat_kind: 'sediment', area_km2: 0.5}, {type: 'FeatureCollection', features: []}, CAMBRIA);
  cards['survey unknown kind, source kind'] = surveyCard({id: 'k2', name: 'Named outline', habitat_kind: 'weird', area_km2: 1}, {type: 'FeatureCollection', features: [], source_kind: 'Own survey', mpa_margin_m: 70, created_at: '2026-09-26'}, CAMBRIA);
  const unit = GEOLOGY.features[0].properties;
  cards['geology'] = geologyCard(unit, GEOLOGY, CAMBRIA);
  cards['geology bare'] = geologyCard({id: 'g9'}, {...GEOLOGY, source: {}}, CAMBRIA);
  cards['terrain with id'] = terrainCard({latitude: 35.38, longitude: -120.88, id: 'reef:r1'});
  cards['terrain no id'] = terrainCard({latitude: 35.38, longitude: -120.88});
  cards['terrain detail'] = terrainDetailCard({id: 'reef:r1', kind: 'reef', title: 'Lingcod habitat · grade A', facts: 'Nominal 40–80 ft · species fit 3/3', evidence: 'src · 2012. Fish presence unverified.'}, 'lingcod');
  cards['receipt reef'] = receiptCard({id: 'reef:r1', latitude: 35.38, longitude: -120.88, expiresAt: '2027-01-02T00:00:00.000Z', kind: 'reef'});
  cards['receipt shore'] = receiptCard({id: 'shore:s1', latitude: 35.38, longitude: -120.88, expiresAt: '2027-01-02T00:00:00.000Z', kind: 'shore'});
  return cards;
}

// ---- depth contours
const SRC = {source_id: 'usgs-test', name: 'USGS Test Survey', url: 'https://example.org/release', attribution: 'USGS', survey_date: '2008-06-01', vertical_datum: 'unverified source datum'};
const BARE = {...SRC, url: '', attribution: ''};
const OMITTED = {
  none: [],
  one: [{source_id: 'cand-1', review_status: 'candidate'}],
  many: [{source_id: 'cand-1', review_status: 'candidate'}, {source_id: 'rest-1', review_status: 'restricted'}, {source_id: 'odd-1', review_status: 'pending'}, {source_id: 'ok-1', review_status: 'approved'}, {source_id: 'ok-2', review_status: 'approved'}],
  untracedOnly: [{source_id: 'ok-1', review_status: 'approved'}],
};
function contourCards() {
  const cards = {};
  for (const [name, omitted] of Object.entries(OMITTED)) {
    cards[`edge ${name}`] = contourMark({kind: 'survey-edge', source_id: 'usgs-test'}, [SRC], omitted);
    cards[`contour 150 ${name}`] = contourMark({kind: 'contour', source_id: 'usgs-test', depth_ft: 150}, [SRC], omitted);
  }
  cards['contour 30 measured, bare source'] = contourMark({kind: 'contour', source_id: 'usgs-test', depth_ft: 30, provenance: 'measured'}, [BARE]);
  cards['contour 150 one untraced'] = contourMark({kind: 'contour', source_id: 'usgs-test', depth_ft: 150}, [SRC], [{source_id: 'ok', review_status: 'approved'}, {source_id: 'c', review_status: 'candidate'}]);
  cards['contour 60 filled'] = contourMark({kind: 'contour', source_id: 'usgs-test', depth_ft: 60, provenance: 'filled'}, [SRC], OMITTED.one);
  cards['contour 90 verified'] = contourMark({kind: 'contour', source_id: 'usgs-test', depth_ft: 90, provenance: 'verified'}, [SRC]);
  for (const reason of ['hole', 'ring-range', 'datum-suspect', 'nodata']) cards[`unresolved ${reason}`] = contourMark({kind: 'unresolved-area', source_id: 'usgs-test', reason}, [SRC], OMITTED.many);
  cards['unresolved conflict'] = contourMark({kind: 'unresolved-area', source_id: 'usgs-test', reason: 'conflict', shoal_hint_ft: 42}, [SRC]);
  return cards;
}

const ALL = () => ({...seafloorCards(), ...habitatCards(), ...contourCards()});
const FIELDS = ['name', 'kind', 'reading', 'source', 'basis', 'rules'];
const placeholders = text => [...text.matchAll(/\{(\w+)\}/g)].map(m => m[1]).sort().join(',');
const idsOf = parts => parts.flatMap(p => typeof p === 'string' ? [] : [p.id, ...Object.values(p.vars ?? {}).flatMap(function walk(v) {
  return typeof v === 'string' || typeof v === 'number' ? [] : Array.isArray(v) ? v.flatMap(walk) : [v.id, ...Object.values(v.vars ?? {}).flatMap(walk)];
})]);

test('english_is_the_producers_own_text: every descriptor of every named builder branch resolves, in English, to the field it describes', () => {
  const cards = ALL();
  assert.ok(Object.keys(cards).length >= 40, 'the named branches are all built');
  let checked = 0;
  for (const [name, card] of Object.entries(cards)) {
    assert.ok(card, `${name} built a card`);
    const en = resolveMarkCopy(card, 'en');
    for (const f of FIELDS) assert.equal(en[f], card[f] ?? (f === 'rules' ? undefined : ''), `${name}: ${f} in English`);
    for (const f of Object.keys(card.copy ?? {})) {
      const raw = f === 'regulationsLabel' ? card.regulations.label : card[f];
      assert.equal(copyText(card.copy[f], 'en'), raw, `${name}: ${f} parts read as the English field`); checked++;
    }
    (card.copyTerms ?? []).forEach((parts, i) => { assert.equal(copyText(parts, 'en'), card.terms[i].label, `${name}: term ${i}`); checked++; });
    assert.ok(!('copy' in card) || typeof card.copy === 'object');
  }
  assert.ok(checked > 200, `checked ${checked} described fields`);
});

test('same_mark_en_es_en_without_rebuild: a language change only re-resolves; the mark, its identity and its position are untouched', () => {
  for (const [name, card] of Object.entries(ALL())) {
    const frozen = JSON.stringify(card), en1 = resolveMarkCopy(card, 'en'), es = resolveMarkCopy(card, 'es'), en2 = resolveMarkCopy(card, 'en');
    assert.equal(JSON.stringify(card), frozen, `${name}: resolving does not change the mark`);
    assert.equal(JSON.stringify(en1), JSON.stringify(en2), `${name}: es then back to en`);
    for (const k of ['id', 'position', 'withheld']) assert.equal(JSON.stringify(card[k]), JSON.stringify(JSON.parse(frozen)[k]), `${name}: ${k}`);
    assert.ok(!/\{\w+\}/.test(Object.values(es).filter(v => typeof v === 'string').join(' ')) || /\{\w+\}/.test(frozen), `${name}: no unfilled placeholder in Spanish`);
  }
  const withheldMark = habitatCards()['withheld mpa'];
  assert.equal(withheldMark.position, undefined, 'a withheld mark never carries a position');
});

test('catalogue_completeness: every id a descriptor uses has a Spanish value with the same placeholders, and a missing id fails loudly', () => {
  const used = new Set();
  for (const card of Object.values(ALL())) for (const parts of [...Object.values(card.copy ?? {}), ...card.copyTerms ?? []]) for (const id of idsOf(parts)) used.add(id);
  // Parts reached only through the omitted-survey helper and the unused-in-fixture phrases.
  for (const parts of [omittedCopy(OMITTED.many)]) for (const id of idsOf(parts)) used.add(id);
  assert.ok(used.size > 70, `${used.size} ids used`);
  const same = new Set(['mark.layer.habitat.atlas', 'mark.layer.habitat.ds582', 'mark.layer.and']);
  for (const id of used) {
    const e = STRINGS[id];
    assert.ok(e && e.en && e.es, `${id} has English and Spanish`);
    assert.equal(placeholders(e.es), placeholders(e.en), `${id}: same placeholders`);
    if (!same.has(id)) assert.notEqual(e.es, e.en, `${id}: Spanish differs from English`);
  }
  // Every id in the three namespaces is used by some branch (no dead strings).
  const mine = Object.keys(STRINGS).filter(id => /^mark\.layer\.(seafloor|habitat|contour)\./.test(id));
  assert.deepEqual(mine.filter(id => !used.has(id)), [], 'no unused catalogue ids');
  assert.throws(() => copyText([{id: 'mark.layer.contour.missing'}], 'es'), /unknown string id/, 'negative control: a descriptor with no catalogue id fails');
});

test('seafloor_all_evidence_states: full Spanish caveats, raw rights, and nothing invented', () => {
  const cards = seafloorCards(), es = k => resolveMarkCopy(cards[k], 'es');
  const c = es('candidate fit 3');
  assert.equal(c.name, 'Candidato de hábitat, sin verificar');
  assert.equal(c.kind, 'Calificación del terreno A · afinidad del hábitat para lingcod: 3 de 3');
  assert.equal(c.reading, '41–90 ft nominales');
  assert.equal(c.source, 'Levantamiento s1 · 2010 · cuadrícula de 2 m');
  assert.equal(c.basis, 'Candidato de hábitat, sin verificar. Profundidad nominal (MLLW); verifícala con tu ecosonda. Evaluación del terreno del levantamiento s1, 2010, en una cuadrícula de 2 m; la presencia de peces no está verificada.'
    + ' Lab A Notice A. Solo para planificar. No es una carta de navegación. Revisa el reglamento vigente de CDFW.', 'rights credit and notice raw, default notice translated');
  assert.equal(es('candidate fit unknown').kind, 'Calificación del terreno A · afinidad para cabezon desconocida');
  assert.equal(es('candidate terrain').kind, 'Calificación del terreno A');
  const coarse = es('candidate coarse, notice supplied, two terms');
  assert.match(coarse.basis, /Área amplia, no una estructura individual\. Evaluación del terreno/);
  assert.ok(coarse.basis.endsWith('Lab B Notice B. Supplied planning notice.'), 'a supplied planning_notice stays as published');
  assert.deepEqual(resolveMarkCopy(cards['candidate coarse, notice supplied, two terms'], 'es').terms, ['Condiciones del editor: Lab A', 'Condiciones del editor: Lab B']);
  assert.deepEqual(resolveMarkCopy(cards['candidate fit 3'], 'es').terms, ['Condiciones del editor']);
  const none = es('candidate nothing known');
  assert.equal(none.kind, 'Calificación del terreno desconocida');
  assert.equal(none.reading, 'Profundidad desconocida');
  assert.equal(none.source, 'Levantamiento desconocido · desconocido · cuadrícula de tamaño desconocido');
  assert.match(none.basis, /Profundidad nominal \(desconocido\); verifícala con tu ecosonda\. Evaluación del terreno del levantamiento desconocido, desconocido, en una cuadrícula de tamaño desconocido;/);
  const search = es('search');
  assert.equal(search.name, 'Área de búsqueda de fondo irregular medido');
  assert.equal(search.kind, 'Área de búsqueda de fondo irregular · sin calificar');
  assert.match(search.basis, /^Área de búsqueda de fondo irregular medido, sin calificar: las mediciones circundantes no permiten asignar una calificación del terreno\. Profundidad nominal \(MLLW\); busca con tu ecosonda\. Del levantamiento s1, 2010, en una cuadrícula de 2 m; la presencia de peces no está verificada\./);
  const bedrock = es('interpreted bedrock');
  assert.equal(bedrock.name, 'Área de hábitat de roca expuesta interpretada por el editor');
  assert.equal(bedrock.reading, 'Dentro de la franja nominal de 25–300 ft');
  assert.match(bedrock.basis, /^Área de hábitat de roca expuesta interpretada por el editor, sin calificar: se desconocen la calificación del terreno y la afinidad para las especies\. Dentro de la franja nominal de 25–300 ft \(datum vertical MLLW\); verifícalo con tu ecosonda\. De la interpretación del editor de s1 y s2; la presencia de peces no está verificada\./);
  assert.equal(es('interpreted rugose, no survey').name, 'Área de hábitat de roca rugosa interpretada por el editor');
  assert.match(es('interpreted rugose, no survey').basis, /De la interpretación del editor de su levantamiento; la presencia/);
  const cell = es('cell named');
  assert.deepEqual([cell.name, cell.kind, cell.reading], ['Celda de 250 m levantada', 'Cobertura de levantamiento · sin calificación de hábitat', 'No se indica profundidad para esta celda']);
  assert.equal(cell.source, 'Levantamiento csumb-test-2m · año y datum vertical no registrados para esta celda');
  assert.match(cell.basis, /^Celda de 250 m levantada a partir del levantamiento csumb-test-2m \(año y datum vertical no registrados para esta celda\): al menos una cuarta parte de su franja de referencia provisional tiene profundidades válidas del levantamiento original; solo cobertura, sin calificación de hábitat\. Pub Credit Pub notice\. Solo para planificar\./);
  assert.equal(es('cell unnamed').source, 'Levantamiento sin nombre · año y datum vertical no registrados para esta celda');
  assert.match(es('cell unnamed').basis, /a partir de un levantamiento sin nombre \(año/);
  for (const k of ['candidate fit 3', 'search', 'interpreted bedrock', 'cell named']) assert.doesNotMatch(Object.values(es(k)).join(' '), /hotspot|chance|bite|catch rate|productive|best spot/i);
  // A feature built by hand (no metadata) shows its original English in either language.
  const legacy = seafloorMark({...admit({}), basisCopy: undefined}, 'terrain');
  assert.equal(resolveMarkCopy(legacy, 'es').basis, legacy.basis);
  assert.equal(legacy.copy.basis, undefined);
});

test('habitat_screens_and_published_prose: the withheld sentence, checks and rules in Spanish; published text untouched', () => {
  const cards = habitatCards(), es = k => resolveMarkCopy(cards[k], 'es');
  const BASIS = 'Las marcas del atlas se comprueban de nuevo en el navegador frente a los límites actuales de áreas protegidas y los cierres de la región antes de mostrarse. Se retiene una marca que esté dentro de uno, y se retienen todas las marcas mientras esa comprobación no esté disponible o tenga más de 36 horas.';
  for (const k of ['checking', 'stale', 'unavailable', 'mpa', 'federal', 'within']) assert.equal(es(`withheld ${k}`).basis, BASIS, `withheld ${k}: the basis sentence`);
  assert.equal(es('withheld checking').name, 'Comprobando marca de arrecife');
  assert.equal(es('withheld stale').name, 'Marca de arrecife retenida');
  assert.equal(es('withheld stale').kind, `Marca de arrecife · ${spot.id}`);
  assert.equal(es('withheld checking').reading, 'Comprobando áreas protegidas antes de mostrar lugares de pesca…');
  assert.equal(es('withheld checking').source, 'Comprobación de CDFW ds582 en curso');
  assert.equal(es('withheld stale').reading, 'Comprobación de límites desactualizada; objetivos de pesca retenidos');
  assert.equal(es('withheld unavailable').reading, 'Comprobación de áreas protegidas no disponible · lugares de pesca retenidos');
  assert.equal(es('withheld unavailable').source, 'CDFW ds582 comprobación no disponible');
  assert.equal(es('withheld stale').source, 'CDFW ds582 comprobado el 2026-10-01');
  assert.equal(es('withheld stale').rules, 'Revisa el reglamento y los límites vigentes antes de pescar.');
  assert.equal(es('withheld mpa').reading, 'Dentro de Test MPA');
  assert.equal(es('withheld mpa').source, 'CDFW ds582 comprobado en esta sesión');
  assert.equal(es('withheld mpa').rules, 'SkipperCast retiene los objetivos de pesca en todas las áreas protegidas cartografiadas, incluidas las áreas de conservación que permiten algunas actividades. Consulta el reglamento oficial exacto.');
  assert.equal(es('withheld mpa').regulationsLabel, 'Áreas marinas protegidas de CDFW');
  assert.equal(es('withheld within').reading, 'Dentro o a menos de 70 m de Near MPA');
  assert.equal(es('withheld federal').reading, 'Dentro de Test GEA');
  assert.equal(es('withheld federal').rules, 'Cierre de NOAA para peces de fondo. SkipperCast excluye aquí todas las especies objetivo como regla conservadora de planificación. El reglamento federal prevalece sobre este mapa complementario.');
  assert.equal(es('withheld federal').regulationsLabel, 'Áreas cerradas de NOAA para peces de fondo');
  assert.match(es('withheld federal').source, /^CDFW ds582 comprobado 2026-11-05 · Cierres de NOAA comprobado el 2026-11-04$|^CDFW ds582 comprobado el 2026-11-05 · Cierres de NOAA comprobado el 2026-11-04$/);
  // The English keeps the exact 70 m / 36 h structure the screen decides on.
  assert.equal(cards['withheld within'].reading, 'Inside or within 70 m of Near MPA');
  // Reef mark card: only the code's words move; the published name, evidence and rights stay.
  const a = es('atlas lingcod');
  assert.equal(a.name, spot.label);
  assert.match(a.kind, /^Marca de arrecife · calificación [ABC] · ~\d+–\d+ ft$/);
  assert.equal(a.reading, 'Afinidad del hábitat para lingcod: 3 de 3');
  assert.match(a.source, / · levantado en \d{4} · atlas 2026-\d\d-\d\d$/);
  assert.match(a.rules, /^Comprobado frente a áreas protegidas con una separación de \d+ m en el atlas del 2026-\d\d-\d\d; revisa el reglamento vigente antes de pescar\.$/);
  assert.equal(a.basis, cards['atlas lingcod'].basis, 'terrain_interpretation, evidence_status, credit and rights as published');
  assert.equal(a.regulationsLabel, 'Reglamento de pesca oceánica de CDFW');
  assert.equal(es('atlas reef (two screens)').reading, 'Afinidad del hábitat para lingcod y rockfish: ' + cards['atlas reef (two screens)'].reading.match(/(\d) of 3/)[1] + ' de 3');
  assert.equal(es('atlas unrated, own regulations page').reading, 'Afinidad del hábitat sin calificar para este objetivo');
  assert.equal(es('atlas unrated, own regulations page').regulationsLabel, 'Reglamento regional de pesca de CDFW');
  assert.deepEqual(regulationsCopy(SOCAL).map(p => p.id), ['mark.layer.habitat.regs.regional']);
  assert.equal(regulationsLink(SOCAL).label, copyText(regulationsCopy(SOCAL), 'en'));
  assert.equal(es('atlas minimal').rules, 'Revisa el reglamento vigente antes de pescar.');
  assert.equal(es('atlas minimal').source, resolveMarkCopy(cards['atlas minimal'], 'en').source, 'no source facts: nothing invented');
  // Survey habitat and geology.
  const s = es('survey rock with margin');
  assert.equal(s.kind, 'Fondo duro cartografiado');
  assert.match(s.source, / · compilado el 2022-06-07$/);
  assert.match(s.rules, /^Áreas marinas protegidas restadas con un margen de 102 m al compilarse el 2026-09-26; revisa el reglamento vigente antes de pescar\.$/);
  assert.equal(s.basis, cards['survey rock with margin'].basis, 'limitations and depth_note as published');
  assert.equal(s.name, cards['survey rock with margin'].name);
  const k = es('survey kelp, no margin, no name');
  assert.deepEqual([k.name, k.kind, k.source, k.rules], ['Hábitat de levantamiento', 'Detecciones históricas de kelp', 'Hábitat de levantamiento · observado el 2020-01-02', 'Revisa el reglamento vigente antes de pescar.']);
  const u = es('survey unknown kind, source kind');
  assert.deepEqual([u.name, u.kind, u.source], ['Named outline', 'Contexto de levantamiento', 'Own survey · compilado el ']);
  const g = es('geology');
  assert.match(g.kind, /^Geología · unidad cartográfica /);
  assert.equal(g.source, cards.geology.source, 'the published attribution stays');
  assert.equal(g.basis, cards.geology.basis, 'derivation and limitations as published');
  assert.equal(g.rules, 'Áreas marinas protegidas excluidas al compilar la capa; revisa el reglamento vigente antes de pescar.');
  const gb = es('geology bare');
  assert.deepEqual([gb.name, gb.kind, gb.source, gb.rules], ['Geología', 'Geología · unidad cartográfica —', 'Mapa geológico', 'Revisa el reglamento vigente antes de pescar.']);
  // Terrain selections.
  const t1 = es('terrain with id');
  assert.deepEqual([t1.name, t1.kind, t1.source, t1.basis], ['Hábitat seleccionado', 'Hábitat del terreno · reef:r1', 'Selección del terreno costero', 'Elegido en el terreno 2D o 3D, donde se muestran sus líneas de evidencia y fuentes.']);
  assert.equal(es('terrain no id').kind, 'Hábitat del terreno');
  const d = es('terrain detail');
  assert.deepEqual([d.name, d.kind, d.reading, d.source, d.basis], ['Lingcod habitat · grade A', 'Hábitat del terreno reef · reef:r1', cards['terrain detail'].reading, cards['terrain detail'].source, cards['terrain detail'].basis]);
  const r = es('receipt shore');
  assert.deepEqual([r.name, r.kind, r.source], ['Hábitat costero', 'Hábitat del terreno · shore:s1', 'Hábitat costero revisado · válido hasta 2027-01-02']);
  assert.equal(es('receipt reef').name, 'Hábitat de arrecife');
  assert.equal(es('receipt reef').basis, 'Restaurado de la publicación revisada de hábitat; sus líneas de evidencia se muestran en el terreno 2D y 3D.');
  // A screen built by hand (no metadata) keeps its original English source and reading.
  const hand = {status: 'unavailable', note: 'Protected-area check unavailable · fishing spots withheld', source: 'CDFW ds582 check unavailable', boundaries: [], until: Infinity};
  const handCard = withheldCard(spot, withheld(spot, hand, []), hand);
  assert.equal(resolveMarkCopy(handCard, 'es').source, 'CDFW ds582 check unavailable');
  assert.equal(resolveMarkCopy(handCard, 'es').reading, handCard.reading);
  assert.equal(resolveMarkCopy(handCard, 'es').name, 'Marca de arrecife retenida', 'the card words it writes itself still follow the language');
});

test('contour_all_uncertainty_and_omissions: every unresolved reason, provenance and omission in Spanish; names and ids untouched', () => {
  const cards = contourCards(), es = k => resolveMarkCopy(cards[k], 'es');
  const BASIS = STRINGS['layer.depth-contours.basis'].es;
  assert.equal(es('unresolved hole').name, 'Sin verificar / sin datos');
  assert.equal(es('unresolved hole').kind, 'Donde no se pudo verificar el levantamiento');
  assert.equal(es('unresolved hole').basis, BASIS, 'the registry\'s complete Spanish basis (native datum, 2008/16 m, one-year expiry, not navigation)');
  assert.ok(/MLLW/.test(BASIS) && /un año/.test(BASIS) && /ni sirven para navegar/.test(BASIS));
  const REASONS = {
    hole: 'El levantamiento no tiene una medición utilizable aquí; el vacío es demasiado grande para rellenarlo de forma prudente.',
    'ring-range': 'Un vacío pequeño en un fondo empinado o irregular; no se rellenó.',
    'datum-suspect': 'Los dos levantamientos pueden usar datums verticales diferentes; no se compararon.',
    nodata: 'Sin datos.',
  };
  for (const [reason, text] of Object.entries(REASONS)) assert.ok(es(`unresolved ${reason}`).reading.startsWith(text), reason);
  assert.equal(es('unresolved conflict').reading, 'Dos levantamientos discrepan aquí; la lectura menos profunda es de 42 ft. Trátalo como un posible bajo.');
  assert.equal(es('unresolved hole').source, 'USGS Test Survey · USGS · levantado el 2008-06-01 · unverified source datum');
  assert.equal(es('contour 30 measured, bare source').source, 'USGS Test Survey · cuadrícula de levantamiento · levantado el 2008-06-01 · unverified source datum');
  assert.deepEqual(resolveMarkCopy(cards['contour 150 none'], 'es').terms, ['Publicación de datos del levantamiento']);
  assert.deepEqual(resolveMarkCopy(cards['contour 30 measured, bare source'], 'es').terms, [], 'no page: no link');
  const edge = es('edge none');
  assert.deepEqual([edge.name, edge.kind], ['Borde del levantamiento', 'Donde termina la cuadrícula revisada del levantamiento']);
  assert.equal(edge.reading, 'No continúa ninguna cuadrícula revisada más allá de esta línea, por lo que no se dibujan curvas después de ella; eso significa datos faltantes, no agua plana.');
  const c150 = es('contour 150 none'), c30 = es('contour 30 measured, bare source');
  assert.deepEqual([c150.name, c150.kind, c30.kind], ['Curva de profundidad de 150 ft', 'Curva índice · cada 150 ft', 'Curva de profundidad · cada 30 ft']);
  assert.equal(c30.reading, '30 ft bajo el datum unverified source datum del levantamiento, trazados a partir de bloques promediados de 16 m de su cuadrícula; no es un sondeo ni una profundidad de carta.');
  assert.ok(es('contour 60 filled').reading.includes(' Línea discontinua: se rellenó aquí un vacío pequeño con la profundidad menos profunda de las celdas vecinas; no se midió en este lugar.'));
  assert.ok(es('contour 90 verified').reading.endsWith(' Dos levantamientos independientes coinciden aquí dentro de la tolerancia publicada.'));
  // Omissions: singular/plural, the review status words, unknown statuses raw, untraced; and the original predicate (nothing when none is unapproved).
  assert.ok(es('contour 150 one').reading.endsWith(' No se muestra 1 levantamiento vinculado: cand-1 (aún no revisado).'));
  assert.ok(es('contour 150 many').reading.endsWith(' No se muestran 3 levantamientos vinculados: cand-1 (aún no revisado), rest-1 (restringido), odd-1 (pending). No se trazaron 2 levantamientos revisados en este archivo: ok-1, ok-2.'));
  assert.ok(!/ No se (muestra|muestran|traz)/.test(es('contour 150 none').reading) && !/ No se (muestra|muestran|traz)/.test(es('contour 150 untracedOnly').reading), 'unchanged predicate');
  assert.equal(omittedNote(OMITTED.untracedOnly), '');
  assert.deepEqual(omittedCopy(OMITTED.untracedOnly), []);
  const one = es('contour 150 one untraced');
  assert.ok(one.reading.endsWith('No se muestra 1 levantamiento vinculado: c (aún no revisado). No se trazó 1 levantamiento revisado en este archivo: ok.'));
  // Rejected inputs stay rejected.
  assert.equal(contourMark({kind: 'unresolved-area', source_id: 'usgs-test', reason: 'conflict'}, [SRC]), null);
  assert.equal(contourMark({kind: 'unresolved-area', source_id: 'usgs-test', reason: 'bogus'}, [SRC]), null);
});

test('card_renders_in_the_language: MarkCard shows the Spanish words, English returns byte for byte, and behaviour keys on the original fields', async () => {
  const {mkdtemp: _m} = await import('node:fs/promises');
  const out = join(await _m(join(tmpdir(), 'mark-layer-i18n-')), 'card.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {MarkCard} from './web/app/MarkCard.tsx';
      export {language} from './web/i18n.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: preparedRendererPlugins,
  });
  const {MarkCard, language, render, h} = await import(pathToFileURL(out).href);
  const cards = {...contourCards(), ...habitatCards(), ...seafloorCards()};
  try {
    for (const name of ['unresolved hole', 'edge many', 'withheld mpa', 'atlas lingcod', 'cell named', 'candidate fit 3', 'geology']) {
      const mark = cards[name], frozen = JSON.stringify(mark);
      language.value = 'en'; const en = render(h(MarkCard, {mark}));
      language.value = 'es'; const es = render(h(MarkCard, {mark}));
      language.value = 'en'; assert.ok(render(h(MarkCard, {mark})) === en, `${name}: es then en renders the same English`);
      assert.equal(JSON.stringify(mark), frozen, `${name}: rendering leaves the mark alone`);
      const spanish = resolveMarkCopy(mark, 'es');
      for (const f of ['name', 'kind', 'reading', 'source']) if (spanish[f]) assert.ok(es.includes(spanish[f].replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/'/g, '&#39;').replace(/"/g, '&quot;')) || es.includes(spanish[f]), `${name}: ${f} in Spanish`);
      assert.ok(!es.includes('[object Object]'));
    }
    language.value = 'es';
    const withheldHtml = render(h(MarkCard, {mark: cards['withheld mpa']}));
    assert.ok(withheldHtml.includes('Marca de arrecife retenida') && withheldHtml.includes('Áreas marinas protegidas de CDFW'));
    assert.ok(withheldHtml.includes('aria-label="Reglamento: Áreas marinas protegidas de CDFW (página oficial, se abre en una pestaña nueva)"') || withheldHtml.includes('Áreas marinas protegidas de CDFW (página oficial'));
    assert.ok(!/href="[^"]*"[^>]*>\s*Reef mark/.test(withheldHtml));
  } finally { language.value = 'en'; }
});
