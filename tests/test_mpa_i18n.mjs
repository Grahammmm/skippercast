// SC1352-04: protected-area layer words in Spanish. The producer (web/map/mpa.ts) keeps its English strings and attaches catalogue
// parts; the Legend row and the mark card resolve them in the page's language at render. Status, counts, Retry and the screen
// stay decided by the English values. Offline: committed dist/ region files, no fetch, esbuild bundle rendered to strings.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';

const ROOT = new URL('..', import.meta.url).pathname;
const PAGE = 'https://s.test/map';
const json = path => JSON.parse(readFileSync(new URL(`../${path}`, import.meta.url), 'utf8'));
const plain = html => html.replace(/<[^>]*>/g, '').replace(/\s/g, ' ');

let bundle;
async function load() {
  if (bundle) return bundle;
  const out = join(await mkdtemp(join(tmpdir(), 'mpa-i18n-')), 'bundle.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {MpaRow} from './web/app/Legend.tsx';
      export * as mpa from './web/map/mpa.ts';
      export {retryMpas} from './web/map/chart.ts';
      export {resolveMarkCopy} from './web/mark-copy.ts';
      export {statusIn, resolveStatusText} from './web/map/status-copy.ts';
      export {language, STRINGS} from './web/i18n.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins,
  });
  return (bundle = await import(pathToFileURL(out).href));
}

const snapshot = json('dist/data/protected-areas.geojson');
const files = json('dist/regions/morro-bay/region.json'), coverage = json('dist/regions/morro-bay/coverage.json');
const input = (over = {}) => ({region: 'morro-bay', config: files, snapshot, coverage, ...over});
const need = status => ({...coverage, needs: coverage.needs.map(n => n.id === 'protected-areas' ? {...n, status} : n)});
const closures = {type: 'FeatureCollection', region_id: 'morro-bay', features: []};

/** Every state the producer can report, by name. */
async function states(m) {
  const {assessMpas, loadMpas, shownMpaState, MAP_UNAVAILABLE, LOADING} = m.mpa;
  const served = (down = [], over = {}) => async url => {
    const path = new URL(url).pathname;
    if (down.includes(path)) return {ok: false, status: 503, json: async () => ({})};
    if (path === '/regions/morro-bay/region.json' && over.config) return {ok: true, json: async () => over.config};
    return {ok: true, json: async () => JSON.parse(readFileSync(new URL(`../dist${path}`, import.meta.url), 'utf8'))};
  };
  const load = async (down, over) => (await loadMpas('morro-bay', served(down, over), PAGE)).state;
  const complete = assessMpas(input()).state;
  return {
    loading: LOADING, mapUnavailable: MAP_UNAVAILABLE, complete,
    drawFailed: shownMpaState(complete, {sourceFailed: true}),
    partialReviewed: assessMpas(input({coverage: need('partial')})).state, partialUnreviewed: assessMpas(input({coverage: null})).state,
    incompleteMany: assessMpas(input({snapshot: {...snapshot, region_id: 'elsewhere', source_url: undefined, features: snapshot.features.slice(0, 1)}, closures: null})).state,
    badSnapshot: assessMpas(input({snapshot: null})).state,
    regionDown: await load(['/regions/morro-bay/region.json']), snapshotDown: await load(['/data/protected-areas.geojson']),
    noSnapshot: await load([], {config: {...files, assets: {...files.assets, protected_areas: 'https://evil.test/x.geojson'}}}),
  };
}

test('mpa_es_failure_matrix: every state keeps its English strings and its meaning in Spanish; a missing outline never reads as clear', async () => {
  const m = await load(), all = await states(m);
  assert.ok(Object.keys(all).length >= 11);
  for (const [name, s] of Object.entries(all)) {
    const {note, reason} = s.copy ?? {};
    assert.ok(note, `${name} carries a note descriptor`);
    // English: the descriptors reproduce the producer's own strings byte for byte and are never re-rendered.
    // (A date descriptor reads "Sep 21" in the catalogue's English; the page never renders English from it, so the ISO date is put back to compare.)
    const iso = text => s.checked ? text.replace(/\b[A-Z][a-z]{2} \d{1,2}\b/g, s.checked) : text;
    assert.equal(iso(m.statusIn(note, 'en')), s.note, `${name} note`);
    assert.equal(reason ? iso(m.statusIn(reason, 'en')) : '', s.detail, `${name} detail`);
    assert.equal(m.resolveStatusText(s.note, note, 'en'), s.note);
    const es = m.resolveStatusText(s.note, note, 'es'), esDetail = m.resolveStatusText(s.detail, reason, 'es');
    assert.notEqual(es, s.note, `${name} is translated`);
    assert.doesNotMatch(`${es} ${esDetail}`, /\b(?:boundar|snapshot|region|protected|loaded|draw)/i, `${name} leaves no English`);
    if (s.status !== 'complete' && s.status !== 'loading') assert.match(`${es} ${esDetail}`, /un área sin contorno puede seguir estando protegida\./, `${name}: may still be protected`);
    if (name === 'badSnapshot') assert.equal(esDetail, 'La instantánea de límites no superó la comprobación de integridad.');
  }
  const es = (name, field = 'note') => m.resolveStatusText(all[name][field === 'note' ? 'note' : 'detail'], all[name].copy[field === 'note' ? 'note' : 'reason'], 'es');
  assert.equal(es('loading'), 'Cargando límites.');
  assert.equal(es('mapUnavailable'), 'Mapa no disponible.');
  assert.equal(es('mapUnavailable', 'reason'), 'El mapa no pudo iniciarse, por lo que no se muestran límites; un área sin contorno puede seguir estando protegida.');
  assert.equal(es('drawFailed', 'reason'), 'El mapa no pudo dibujar los datos de límites.');
  assert.equal(es('partialReviewed'), 'La revisión de límites de esta región es parcial; un área sin contorno puede seguir estando protegida.');
  assert.equal(es('incompleteMany'), 'La instantánea de límites está incompleta para esta región; un área sin contorno puede seguir estando protegida.');
  assert.equal(es('regionDown', 'reason'), 'El paquete de la región no se cargó.');
  assert.equal(es('snapshotDown', 'reason'), 'La instantánea de límites no se cargó.');
  assert.equal(es('noSnapshot', 'reason'), 'Esta región no indica ninguna instantánea de límites.');
  // Several gaps are joined in the producer's order, each its own sentence, with the count and the minimum kept.
  assert.match(es('incompleteMany', 'reason'), /^La instantánea contiene 1 áreas; la comprobación de esta región requiere al menos \d+\. La instantánea se obtuvo para otra región\. El área de consulta de la instantánea no abarca toda esta región\. Los cierres federales para peces de fondo indicados para esta región no se cargaron\.$/);
  // The decisions are the English ones.
  assert.deepEqual(Object.fromEntries(Object.entries(all).map(([k, s]) => [k, s.status])), {
    loading: 'loading', mapUnavailable: 'unavailable', complete: 'complete', drawFailed: 'unavailable', partialReviewed: 'partial', partialUnreviewed: 'partial', incompleteMany: 'incomplete',
    badSnapshot: 'unavailable', regionDown: 'unavailable', snapshotDown: 'unavailable', noSnapshot: 'unavailable',
  });
});

test('mpa_es_partial_and_complete_roundtrip: dated and undated notes, reviewed and unreviewed partial detail; English comes back byte for byte', async () => {
  const m = await load(), all = await states(m), {assessMpas} = m.mpa;
  const es = (s, f) => m.resolveStatusText(f === 'note' ? s.note : s.detail, s.copy[f === 'note' ? 'note' : 'reason'], 'es');
  assert.match(es(all.complete, 'note'), /^Instantánea CDFW ds582 de esta región, revisada el \d{1,2} \S+\.$/);
  assert.ok(!es(all.complete, 'note').includes(all.complete.checked), 'the ISO date is formatted for Spanish, not kept');
  const undated = assessMpas(input({snapshot: {...snapshot, checked_at: undefined}})).state;
  assert.equal(undated.checked, null);
  assert.equal(es(undated, 'note'), 'Instantánea CDFW ds582 de esta región.');
  assert.equal(undated.note, 'CDFW ds582 snapshot for this region.');
  assert.match(es(all.partialReviewed, 'reason'), /^Se muestran \d+ áreas de la instantánea CDFW ds582, revisada el .+\. La revisión de la región no ha confirmado que sean todas las áreas protegidas de este lugar\.$/);
  assert.match(es(all.partialUnreviewed, 'reason'), /La revisión de límites de esta región no se cargó, por lo que la representación no está confirmada\.$/);
  assert.match(all.partialReviewed.detail, /^Drawn: \d+ areas from the CDFW ds582 snapshot checked \d{4}-\d{2}-\d{2}\. The region's review has not confirmed that this is every protected area here\.$/);
  // The Legend row: es then en again renders the English exactly as before, from the same state object (no refetch, no rebuild).
  for (const name of ['complete', 'partialReviewed', 'incompleteMany', 'regionDown']) {
    m.mpa.mpaState.value = all[name];
    m.language.value = 'en';
    const before = m.render(m.h(m.MpaRow, {}));
    m.language.value = 'es';
    const spanish = plain(m.render(m.h(m.MpaRow, {})));
    assert.match(spanish, /Reglas y límites oficiales \(CDFW\)/, name);
    assert.doesNotMatch(spanish, /Boundar|snapshot/i, `${name} shows no English state words`);
    m.language.value = 'en';
    assert.equal(m.render(m.h(m.MpaRow, {})), before, `${name}: English restored byte for byte`);
    assert.ok(plain(before).includes(all[name].note), name);
    assert.ok(before.includes('href="https://wildlife.ca.gov/Conservation/Marine/MPAs"'), 'the CDFW rules link is unchanged');
  }
  m.mpa.mpaState.value = m.mpa.IDLE;
});

test('mpa_designations_and_unknown_codes: Spanish label with the official designation beside it; names, citations and links stay as published', async () => {
  const m = await load(), {mpaMark, DESIGNATIONS, CDFW_MPA_PAGE, NOAA_GEA_PAGE} = m.mpa;
  const spanish = {
    SMR: 'Reserva marina estatal', SMCA: 'Área estatal de conservación marina', 'SMCA (No-Take)': 'Área estatal de conservación marina (sin extracción)',
    SMRMA: 'Área estatal de gestión recreativa marina', SMP: 'Parque marino estatal', FMR: 'Reserva marina federal', FMCA: 'Área federal de conservación marina',
    'Special Closure': 'Cierre especial', GEA: 'Área federal de exclusión para peces de fondo',
  };
  assert.deepEqual(Object.keys(spanish).sort(), Object.keys(DESIGNATIONS).sort(), 'every designation has a Spanish label');
  for (const [type, label] of Object.entries(spanish)) {
    const mark = mpaMark({NAME: 'X', FULLNAME: 'Published Full Name', Type: type, CCR: 'Section 632 (b)', source: type === 'GEA' ? 'noaa' : 'cdfw', checked: '2026-09-21'});
    assert.equal(mark.kind, DESIGNATIONS[type], 'English kind is the official designation');
    assert.equal(m.resolveMarkCopy(mark, 'en').kind, DESIGNATIONS[type]);
    const shown = m.resolveMarkCopy(mark, 'es');
    assert.equal(shown.kind, `${label} (${DESIGNATIONS[type]})`, type);
    assert.equal(shown.name, 'Published Full Name', 'area names stay as published');
    assert.equal(shown.reading, 'CCR Title 14, Section 632 (b)', 'the citation stays as published');
  }
  assert.match(m.resolveMarkCopy(mpaMark({NAME: 'X', Type: 'SMCA (No-Take)', source: 'cdfw'}), 'es').kind, /sin extracción/, 'no-take is not dropped');
  const odd = mpaMark({NAME: 'Y', Type: '<b>ZZ</b>', source: 'cdfw'});
  assert.equal(odd.kind, 'Designation <b>ZZ</b>');
  assert.equal(m.resolveMarkCopy(odd, 'es').kind, 'Designación <b>ZZ</b>', 'an unknown code is shown as given, never guessed');
  assert.equal(m.resolveMarkCopy(mpaMark({NAME: 'Y', source: 'cdfw'}), 'es').kind, 'Designación no indicada');
  assert.equal(m.resolveMarkCopy(mpaMark({NAME: 'Y', Type: 'constructor', source: 'cdfw'}), 'es').kind, 'Designación constructor');
  const fed = mpaMark({NAME: 'G', Type: 'FMR', CCR: 'N/A', source: 'cdfw'}), none = mpaMark({NAME: 'H', Type: 'SMR', CCR: '', source: 'cdfw', checked: '2026-09-21'});
  assert.equal(m.resolveMarkCopy(fed, 'es').reading, 'Aguas federales; ds582 no indica una sección estatal.');
  assert.equal(m.resolveMarkCopy(none, 'es').reading, 'ds582 no indica ninguna sección reglamentaria.');
  assert.equal(m.resolveMarkCopy(fed, 'es').source, 'CDFW ds582 · fecha de revisión no indicada');
  assert.equal(m.resolveMarkCopy(none, 'es').source, 'CDFW ds582 · revisado el 2026-09-21');
  const gea = mpaMark({NAME: 'Hidden Reef', Type: 'GEA', CCR: 'NOAA groundfish closure; see controlling federal regulations', source: 'noaa', checked: '2026-09-24'});
  const g = m.resolveMarkCopy(gea, 'es');
  assert.equal(g.reading, gea.reading, 'the published citation is not translated');
  assert.equal(g.source, 'NOAA Fisheries · revisado el 2026-09-24');
  assert.match(g.basis, /coordenadas tal como se publican; rigen los reglamentos federales\.$/, 'coordinates as published and federal control are kept');
  assert.equal(g.regulationsLabel, 'Áreas cerradas de NOAA para peces de fondo');
  assert.deepEqual(gea.regulations, {href: NOAA_GEA_PAGE, label: 'NOAA groundfish closed areas'});
  assert.deepEqual(none.regulations, {href: CDFW_MPA_PAGE, label: 'CDFW marine protected areas'});
  assert.equal(m.resolveMarkCopy(none, 'es').regulationsLabel, 'Áreas marinas protegidas de CDFW');
  assert.equal(m.resolveMarkCopy(none, 'es').basis, m.STRINGS['layer.mpas.basis'].es);
});

test('mpa_language_switch_pending_retry: language alone neither offers, hides nor presses Try again, and the canonical state is untouched', async () => {
  const m = await load(), all = await states(m), TRY = lang => lang === 'es' ? />Intentar de nuevo<\/button>/ : />Try again<\/button>/;
  const retry = m.retryMpas.value;
  for (const name of ['regionDown', 'snapshotDown']) {
    const s = all[name];
    m.mpa.mpaState.value = s;
    for (const lang of ['es', 'en', 'es']) {
      m.language.value = lang;
      assert.match(m.render(m.h(m.MpaRow, {})), TRY(lang), `${name} ${lang}`);
    }
    assert.equal(m.mpa.mpaState.value, s);
    assert.ok(Object.values(m.mpa.TRANSIENT_DETAILS).includes(s.detail), 'Retry still compares the English detail');
  }
  // Not transient: a region that names no snapshot and a failed completeness check never offer it, in either language.
  for (const name of ['noSnapshot', 'badSnapshot', 'complete', 'partialReviewed']) {
    m.mpa.mpaState.value = all[name];
    for (const lang of ['es', 'en']) { m.language.value = lang; assert.doesNotMatch(m.render(m.h(m.MpaRow, {})), /Try again|Intentar de nuevo/, `${name} ${lang}`); }
  }
  assert.equal(m.retryMpas.value, retry, 'rendering in another language never retries');
  m.language.value = 'en';
  m.mpa.mpaState.value = m.mpa.IDLE;
});
