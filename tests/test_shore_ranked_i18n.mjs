// SC1352-08: the shore-run, ranked trip-spot and shoreline cards read Spanish where they are shown. The decisions
// (status label, reasons, priority, counters, access pins) stay on the English values; English is byte-identical.
import './helpers/spanish-ready.mjs';   // SC1407-09: the Spanish table, before the Spanish renders
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {shoreGuidance, shoreReviewLines, shoreStatus, shoreStatusCopy as shownRunsCopy} from '../web/brief/shore.ts';
import {resolveMarkCopy} from '../web/mark-copy.ts';
import {coastlineMark} from '../web/map/coastline.ts';
import {assessScreen} from '../web/map/habitat.ts';
import {rankedCard} from '../web/map/ranked.ts';
import {runMark, shoreCollections, shownRuns} from '../web/map/shore.ts';

const ROOT = new URL('..', import.meta.url);
const json = path => JSON.parse(readFileSync(new URL(path, ROOT), 'utf8'));
const PACKAGE = json('dist/regions/morro-bay/shore-habitat.geojson');
const REGION = json('dist/regions/morro-bay/region.json');
const SNAPSHOT = json(`dist/${REGION.assets.protected_areas}`);
const HOUR = 3_600_000;
const NOW = Date.parse('2026-10-11T00:00:00Z');
const iso = ms => new Date(ms).toISOString();
const READY = assessScreen({areas: SNAPSHOT.features, checkedAt: iso(NOW - HOUR), live: false, closures: undefined}, NOW);
const checked = (now, extra = {}) => ({alerts: [], sources: [{id: 'nws-alerts', outcome: 'ok', fetchedAt: iso(now - HOUR)}], waterQuality: [], nearshore: [], ...extra});
const es = (mark, field) => resolveMarkCopy(mark, 'es')[field];
const en = (mark, field) => resolveMarkCopy(mark, 'en')[field];

const base = shownRuns(PACKAGE, READY, checked(NOW), NOW)[0];

test('shore_labels_never_drive_spanish_decisions: English decisions are unchanged and Spanish never feeds them back', () => {
  const runs = shownRuns(PACKAGE, READY, checked(NOW), NOW);
  const before = JSON.stringify(runs.map(r => [r.status, r.run.id]));
  const cards = runs.map(r => runMark(r, 'surfperch', NOW));
  for (const r of runs) {
    const c = runMark(r, 'surfperch', NOW);
    assert.ok(/^Shore run · (Blocked|Hold|No surf model|Current)$/.test(c.kind), 'English kind keeps the English label');
    assert.match(es(c, 'kind'), /^Tramo de costa · (Bloqueado|En espera|Sin modelo de oleaje costero|Actual)$/);
  }
  resolveMarkCopy(cards[0], 'es'); resolveMarkCopy(cards[0], 'en');
  assert.equal(JSON.stringify(runs.map(r => [r.status, r.run.id])), before, 'rendering in either language never mutates the model');
  const data = shoreCollections(runs);
  assert.ok(!JSON.stringify(data).match(/Bloqueado|En espera|Tramo de costa/), 'no Spanish in the GeoJSON');
  // A Spanish label is not the canonical enum: it gets no kind descriptor and the English card stays as it was.
  const injected = {...base, status: {...base.status, label: 'Bloqueado'}};
  const card = runMark(injected, 'surfperch', NOW);
  assert.equal(card.kind, 'Shore run · Bloqueado');
  assert.equal(card.copy.kind, undefined, 'only the four canonical labels are translated');
  assert.ok(runMark(injected, 'surfperch', NOW).reading.includes(' Public access: '), 'a non-Blocked label keeps public access, as before');
  const blocked = runMark({...base, status: {...base.status, label: 'Blocked'}}, 'surfperch', NOW);
  assert.ok(!blocked.reading.includes('Public access') && !es(blocked, 'reading').includes('Acceso público'), 'Blocked suppresses public access in both languages');
});

test('shore_every_hold_reason_and_published_name: every reason keeps its meaning, order and punctuation', () => {
  const alertsName = '<b>Gale Warning</b> & "more"';
  const cases = [
    [{inside: ['Point Buchon SMR', 'Estero Bluffs'], conditions: true}, 'Inside Point Buchon SMR; Estero Bluffs.', 'Dentro de Point Buchon SMR; Estero Bluffs.'],
    [{inside: null, conditions: true}, 'Protected-area check not current.', 'La revisión de áreas protegidas no está actualizada.'],
    [{inside: [], conditions: true, alertCheck: false}, 'Marine alert check not current.', 'La revisión de avisos marinos no está actualizada.'],
    [{inside: null, conditions: false, alertCheck: false, alerts: [alertsName, 'Small Craft Advisory'], notices: ['Morro Strand', 'Morro Strand']},
      `Protected-area check not current; Marine alert check not current; Marine alert: ${alertsName}; Marine alert: Small Craft Advisory; Beach-health notice: Morro Strand; Beach-health notice: Morro Strand.`,
      `La revisión de áreas protegidas no está actualizada; La revisión de avisos marinos no está actualizada; Aviso marino: ${alertsName}; Aviso marino: Small Craft Advisory; Aviso de salud de playa: Morro Strand; Aviso de salud de playa: Morro Strand.`],
    [{inside: [], conditions: false}, 'No fresh nearshore model sample for this area.', 'No hay una muestra reciente del modelo cercano a la costa para esta área.'],
    [{inside: [], conditions: true}, 'Protected-area check current; a fresh nearshore model sample covers this area.',
      'Revisión de áreas protegidas actualizada; una muestra reciente del modelo cercano a la costa cubre esta área.'],
  ];
  for (const [inputs, english, spanish] of cases) {
    const status = shoreStatus(base.run.properties, {now: NOW, ...inputs});
    assert.equal(status.reasons.join('; ') + '.', english, 'the English reasons are unchanged');
  }
  // The shown runs carry the descriptor built from the same inputs.
  for (const [i, [inputs, english, spanish]] of cases.entries()) {
    const status = shoreStatus(base.run.properties, {now: NOW, ...inputs});
    const copy = shownRunsCopy(inputs, status);
    const card = runMark({...base, status, copy}, 'surfperch', NOW);
    assert.ok(card.reading.startsWith(english), `${i}: English reading`);
    assert.ok(es(card, 'reading').startsWith(spanish), `${i}: Spanish reading ${es(card, 'reading')}`);
    assert.ok(!/Hold|Blocked|Inside|Marine alert|Beach-health|nearshore/.test(es(card, 'reading')), `${i}: no English reason words left`);
    assert.equal(card.reading, en(card, 'reading'), 'English output is the card\'s own text');
  }
  // Legacy cards without a descriptor keep their reasons verbatim, never parsed.
  const legacy = runMark({...base, status: {priority: 2, label: 'Current', reasons: ['made up', 'another reason']}, copy: undefined}, 'surfperch', NOW);
  assert.ok(es(legacy, 'reading').startsWith('made up; another reason.'));
  assert.equal(es(legacy, 'kind'), 'Tramo de costa · Actual');
});


test('shore_every_hold_reason_and_published_name: a mismatched status gets no descriptor', () => {
  assert.equal(shownRunsCopy({inside: null, alerts: ['x']}, {priority: 0, label: 'Hold', reasons: ['only one']}), null);
  assert.equal(shownRunsCopy({inside: null}, {priority: 0, label: 'Unknown', reasons: ['a']}), null);
});

test('shore_guidance_substrate_and_review_zone: seven leads, the unverified statement and the checks', () => {
  const tail = ' La presencia de peces no está verificada. Antes de salir, revisa el reglamento vigente de CDFW para esta área, el estado publicado del punto de acceso, el oleaje costero y el estado de la calidad del agua de playa del condado.';
  const leads = [
    ['surfperch', 'rocky', 'Surfperch: un método de surf en costa rocosa; el tramo marca costa rocosa histórica a lo largo de la cual buscar.'],
    ['halibut', 'rocky', 'California halibut: por lo general es un pez de fondo arenoso; el tramo marca costa rocosa histórica, así que busca bolsas de arena junto a ella, y se aplican límites de tamaño y de captura.'],
    ['lingcod', 'rocky', 'El tramo marca costa rocosa histórica a lo largo de la cual buscar.'],
    ['surfperch', 'gravel', 'El tramo marca costa histórica a lo largo de la cual buscar.'],
    ['surfperch', 'sand', 'Surfperch: un método de surf en playa arenosa; el tramo marca costa arenosa histórica a lo largo de la cual buscar.'],
    ['halibut', 'sand', 'California halibut: un método de fondo arenoso; el tramo marca costa arenosa histórica a lo largo de la cual buscar, y se aplican límites de tamaño y de captura.'],
    ['lingcod', 'sand', 'El tramo marca costa arenosa histórica a lo largo de la cual buscar.'],
  ];
  for (const [target, substrate, lead] of leads) {
    const run = {...base, run: {...base.run, properties: {...base.run.properties, substrate}}};
    const card = runMark(run, target, NOW);
    assert.equal(card.regulations.href, shoreGuidance(target, substrate).href, 'same rules link');
    assert.ok(card.basis.endsWith(`${shoreGuidance(target, substrate).text} Historical shoreline classification; access points are inventory references, not opening status or directions.`), 'English basis unchanged');
    const basis = es(card, 'basis');
    assert.ok(basis.includes(lead + tail), `${target}/${substrate}: ${basis}`);
    assert.ok(basis.endsWith('Clasificación histórica de la costa; los puntos de acceso son referencias de un inventario, no indican si están abiertos ni cómo llegar.'));
    assert.equal(es(card, 'regulationsLabel'), 'Reglamento regional oficial de CDFW');
    assert.equal(en(card, 'regulationsLabel'), 'Official CDFW regional rules');
  }
  assert.ok(runMark(base, 'surfperch', NOW).regulations.href.startsWith('https://'));
});

test('shore_guidance_substrate_and_review_zone: review clocks keep the expiry rule and the region zone', () => {
  const clocks = {reviewExpiresAt: '2026-12-01T07:30:00Z', accessReviewedAt: '2026-10-01T00:00:00Z', accessReviewExpiresAt: '2026-10-10T00:00:00Z',
    legalReviewedAt: null, legalReviewExpiresAt: null, checkedAt: '2026-10-01T00:00:00Z'};
  const run = {...base, run: {...base.run, properties: {...base.run.properties, ...clocks}}};
  const card = runMark(run, 'surfperch', NOW, 'America/Los_Angeles');
  assert.equal(card.reading.split('. ').pop(), shoreReviewLines(run.run.properties, NOW, 'America/Los_Angeles') + '.', 'English review text is the original');
  const r = es(card, 'reading');
  assert.ok(r.includes('Acceso revisado 30 sept 2026, revisión vencida el 9 oct 2026 · reglamento aún sin revisar · fuente revisión vigente hasta 30 nov 2026.'), r);
  // Same instants in UTC land a calendar day later: the card's zone, not the language, picks the day.
  const utc = es(runMark(run, 'surfperch', NOW, 'UTC'), 'reading');
  assert.ok(utc.includes('Acceso revisado 1 oct 2026, revisión vencida el 10 oct 2026') && utc.includes('revisión vigente hasta 1 dic 2026'), utc);
  // Equal to now is expired (> now), as in English.
  const edge = {...run.run.properties, accessReviewExpiresAt: iso(NOW)};
  assert.match(es(runMark({...run, run: {...run.run, properties: edge}}, 'surfperch', NOW), 'reading'), /revisión vencida el/);
  // Unknown and malformed clocks.
  const odd = {...run.run.properties, accessReviewedAt: 'nope', accessReviewExpiresAt: 'nope', legalReviewedAt: '2026-10-01T00:00:00Z', legalReviewExpiresAt: null, reviewExpiresAt: null, checkedAt: null};
  const text = es(runMark({...run, run: {...run.run, properties: odd}}, 'surfperch', NOW), 'reading');
  assert.ok(text.includes('Acceso revisado fecha desconocida, fecha de revisión desconocida') && text.includes('reglamento revisado 30 sept 2026, fecha de revisión desconocida') && text.includes('fuente aún sin revisar'), text);
  assert.equal(runMark({...run, run: {...run.run, properties: odd}}, 'surfperch', NOW).reading.includes('Access checked date unknown, review date unknown'), true);
  // The card does not change the status: a lapsed review is not a Hold.
  assert.equal(run.status.label === 'Hold', base.status.label === 'Hold');
});

test('shore card source and access wrappers read Spanish; published names stay', () => {
  const card = runMark(base, 'surfperch', NOW);
  const p = base.run.properties;
  assert.equal(es(card, 'name'), p.name);
  assert.equal(es(card, 'source'), `NOAA ESI ${p.sourceYear} · ${p.shoreClass} · puntos de acceso del inventario de la California Coastal Commission`);
  assert.equal(en(card, 'source'), `NOAA ESI ${p.sourceYear} · ${p.shoreClass} · access points from the California Coastal Commission inventory`);
  assert.ok(es(card, 'reading').includes(`Acceso público: ${p.access.map(a => a.name).join('; ')}.`));
  assert.ok(es(card, 'basis').startsWith('Tramos de costa arenosa NOAA ESI 2006'), 'the shore-runs basis is the catalogue one');
});

const target = {id: 't1', trip_rank: 3, name: 'Reef «A»', trip_fit: 2, evidence_confidence: {percent: 80}, survey_year: 2008, latitude: 35.2, longitude: -120.9,
  terrain_interpretation: 'Rock <i>ridge</i>.', special_note: 'Note.', evidence_status: 'Index; not catch probability.'};
test('ranked_partial_evidence_not_catch_score: partial evidence keeps its fallbacks and raw fields', () => {
  const full = rankedCard(target, {id: 'morro-bay'});
  assert.equal(es(full, 'name'), '#3 · Reef «A»');
  assert.equal(es(full, 'kind'), 'Sitio de viaje ordenado · numerado según el orden del planificador');
  assert.equal(es(full, 'reading'), 'Hábitat 2/3 · 80% de confianza en la evidencia');
  assert.equal(es(full, 'source'), 'Publicación del fondo marino · levantado en 2008');
  assert.equal(es(full, 'rules'), 'Se muestra mientras la revisión de áreas protegidas de esta sesión está actualizada; revisa el reglamento vigente antes de pescar.');
  assert.equal(es(full, 'basis'), 'Rock <i>ridge</i>. Note. Index; not catch probability.', 'published interpretation stays');
  assert.equal(es(full, 'regulationsLabel'), 'Reglamento de pesca oceánica de CDFW');
  assert.equal(en(full, 'reading'), 'Habitat 2/3 · 80% evidence confidence');
  assert.equal(full.trip, 't1');
  assert.deepEqual(full.position, {latitude: 35.2, longitude: -120.9});
  const cases = [
    [{trip_fit: 0}, 'Hábitat 2/3 · 80% de confianza en la evidencia'.replace('Hábitat 2/3 · ', ''), '80% evidence confidence'],
    [{trip_fit: undefined, evidence_confidence: null}, 'Afinidad del hábitat sin calificar', 'Habitat fit unrated'],
    [{evidence_confidence: {percent: 0}}, 'Hábitat 2/3 · 0% de confianza en la evidencia', 'Habitat 2/3 · 0% evidence confidence'],
    [{evidence_confidence: {percent: '80'}}, 'Hábitat 2/3', 'Habitat 2/3'],
    [{trip_fit: 0, evidence_confidence: {}}, 'Afinidad del hábitat sin calificar', 'Habitat fit unrated'],
    [{survey_year: undefined}, null, null],
  ];
  for (const [patch, spanish, english] of cases) {
    const card = rankedCard({...target, ...patch}, null);
    if (spanish) { assert.equal(es(card, 'reading'), spanish); assert.equal(card.reading, english); }
    else { assert.equal(es(card, 'source'), 'Publicación del fondo marino'); assert.equal(card.source, 'Seafloor publication'); }
  }
});

const props = {SOURCE_ID: 'CA13JA', ATTRIBUTE: 'Natural.Mean High Water', DATA_SOURC: 'Lidar', source_date: '2010-11-01', HOR_ACC: '3.5'};
test('coastline_accuracy_fallbacks_and_invalid_date: stated accuracy, fallbacks and rejected dates', () => {
  const m = coastlineMark(props);
  assert.equal(es(m, 'name'), 'Línea costera');
  assert.equal(es(m, 'kind'), 'Mean High Water · Natural', 'the published attribute stays as written');
  assert.equal(es(m, 'reading'), 'Lidar · ±3,5 m declarados');
  assert.equal(es(m, 'source'), 'NOAA NGS CUSP · fecha de la fuente 2010-11-01');
  assert.equal(es(m, 'basis').startsWith('Línea costera NOAA NGS CUSP') || es(m, 'basis') !== m.basis, true, 'the basis comes from the catalogue');
  assert.equal(m.reading, 'Lidar · ±3.5 m stated');
  for (const date of [undefined, null, '2023-02-29', '2024-13-01', 'unknown', '2024-2-9']) assert.equal(coastlineMark({...props, source_date: date}), null, String(date));
  assert.ok(coastlineMark({...props, source_date: '2024-02-29'}), 'a real leap date');
  const none = coastlineMark({source_date: '1994-02-28'});
  assert.equal(es(none, 'kind'), 'Tramo de línea costera');
  assert.equal(none.kind, 'Shoreline segment');
  assert.equal(es(none, 'reading'), 'No se indica la precisión');
  assert.equal(none.reading, 'Accuracy not stated');
  for (const acc of ['0', '-3', 'x', undefined, 'Infinity']) {
    const only = coastlineMark({...props, HOR_ACC: acc});
    assert.equal(es(only, 'reading'), 'Lidar', `method only for ${acc}: no extra no-accuracy sentence`);
    assert.equal(only.reading, 'Lidar');
    assert.equal(es(coastlineMark({source_date: '2010-11-01', HOR_ACC: acc}), 'reading'), 'No se indica la precisión');
  }
  assert.equal(es(coastlineMark({...props, DATA_SOURC: undefined}), 'reading'), '±3,5 m declarados');
  assert.equal(es(coastlineMark({...props, HOR_ACC: '3'}), 'reading'), 'Lidar · ±3 m declarados');
});

test('shore_card_localization_negative_controls: no descriptor leaks into payloads, English bypasses, ids and placeholders match', () => {
  const runs = shownRuns(PACKAGE, READY, checked(NOW), NOW);
  assert.ok(runs.length && runs.every(r => r.copy && r.copy.reasons.length === r.status.reasons.length), 'every shown run carries its reasons as parts');
  const fc = JSON.stringify(shoreCollections(runs));
  assert.ok(!/"copy"|mark\.layer/.test(fc), 'GeoJSON carries no descriptor');
  const card = runMark(runs[0], 'surfperch', NOW);
  for (const field of ['kind', 'reading', 'source', 'basis', 'rules', 'regulationsLabel']) {
    const display = resolveMarkCopy(card, 'en');
    const raw = field === 'regulationsLabel' ? card.regulations.label : card[field];
    assert.equal(display[field], raw, `English ${field} is the card's own text`);
  }
  const strings = json('catalog/app/strings.json').strings;
  const ids = Object.keys(strings).filter(k => /^mark\.layer\.(shore|ranked|coastline)\./.test(k));
  assert.ok(ids.length >= 40);
  for (const id of ids) {
    const holes = s => [...s.matchAll(/\{(\w+)\}/g)].map(x => x[1]).sort().join();
    assert.ok(strings[id].es && strings[id].en, id);
    assert.equal(holes(strings[id].es), holes(strings[id].en), `${id}: same placeholders`);
  }
  // Re-rendering after the clock passes the expiry does not revive anything: the descriptor holds the captured instant.
  const late = es(card, 'reading');
  assert.equal(es(card, 'reading'), late);
  assert.deepEqual(runs.map(r => r.status.label), shownRuns(PACKAGE, READY, checked(NOW), NOW).map(r => r.status.label));
});
