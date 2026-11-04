// BF-spanish-app: one string catalogue (catalog/app/strings.json) read by web/i18n.ts, the language chosen from
// preference, then Accept-Language, then English, and the first answer, the brief and the rules card rendered
// from it. Components are bundled with esbuild and rendered to strings, as tests/test_first_answer.mjs does.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, mkdir, readFile, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import montereyDaily from './fixtures/brief/monterey-daily.json' with {type: 'json'};
import catalogue from '../catalog/app/strings.json' with {type: 'json'};
import {LANGUAGES, acceptedLanguage, initLanguage, language, localeOf, lookup, num, resolveLanguage, supported, t} from '../web/i18n.ts';
import {COVERED, catalogueProblems} from '../scripts/check_copy.mjs';

const ROOT = new URL('..', import.meta.url).pathname;
const NOW = new Date('2026-09-30T16:00:00Z'); // 9 am PDT; tomorrow is 1 October
const vars = text => [...new Set([...text.matchAll(/\{(\w+)\}/g)].map(m => m[1]))].sort();

test('Accept-Language: absent, es, es-MX, weights, malformed -> the documented choice', () => {
  for (const [header, want] of [[undefined, null], ['', null], ['es', 'es'], ['es-MX', 'es'], ['es-419', 'es'], ['en;q=0.9, es;q=0.8', 'en'], ['es;q=0.8, en;q=0.9', 'en'],
    ['fr, es;q=0.5', 'es'], ['fr, de', null], ['es;q=0, en', 'en'], ['es;q=abc', null], [';;;,,', null], ['es;q=1.5', null], ['*', null], ['en-US,en;q=0.9,es;q=0.8', 'en']])
    assert.equal(acceptedLanguage(header), want, String(header));
  assert.equal(resolveLanguage(null, 'garbage;;'), 'en', 'malformed header reads English');
  assert.equal(supported('ES_419'), 'es'); assert.equal(supported('fr-CA'), null);
  assert.equal(resolveLanguage(undefined, 'es-MX,es;q=0.9'), 'es');
});

test('an explicit preference beats the header; an unsupported preference reads English, not the header', () => {
  assert.equal(resolveLanguage('en', 'es'), 'en');
  assert.equal(resolveLanguage('es', 'en-US'), 'es');
  assert.equal(resolveLanguage('fr', 'es'), 'en');
  assert.equal(resolveLanguage('', 'es'), 'es', 'an empty preference is no preference');
});

test('t(): substitution in both languages, English for a missing es value, a missing id throws in tests and renders the id in production', () => {
  for (const lang of LANGUAGES) {
    const day = lang === 'es' ? 'mañana' : 'tomorrow';
    assert.ok(t('fa.yes', lang, {day}).includes(day));
    assert.ok(t('brief.models.hours', lang, {n: 2, total: 5}).includes('2') && t('brief.models.hours', lang, {n: 2, total: 5}).includes('5'));
    assert.ok(t('brief.gaps.unchecked', lang, {n: 1}).includes('(1)'));
  }
  const table = {a: {en: 'Hello {name}'}, b: {en: 'Hi', es: ''}, c: {en: 'Two {n} of {n2}', es: 'Dos {n} de {n2}'}};
  assert.equal(lookup(table, 'a', 'es', {name: 'Ana'}), 'Hello Ana', 'no es value: English');
  assert.equal(lookup(table, 'b', 'es'), 'Hi', 'an empty es value is a gap, not a blank');
  assert.equal(lookup(table, 'c', 'es', {n: 1}), 'Dos 1 de {n2}', 'an unfilled variable stays visible');
  assert.throws(() => lookup(table, 'nope', 'en'), /unknown string id nope/);
  assert.throws(() => lookup(table, 'constructor', 'en'), /unknown string id/, 'inherited keys are not ids');
  assert.equal(lookup(table, 'nope', 'es', {}, false), 'nope', 'production: never an empty string');
  assert.equal(t('fa.yes', 'fr', {day: 'x'}), t('fa.yes', 'en', {day: 'x'}), 'an unsupported language reads English');
});

test('the catalogue: every id has en and es with the same variables, and the English matches the code that still names it', async () => {
  for (const [id, e] of Object.entries(catalogue.strings)) {
    assert.ok(e.en && e.es, `${id} has both languages`);
    assert.deepEqual(vars(e.en), vars(e.es), `${id}: same variables`);
  }
  const boat = await import('../web/boat-range.ts'), verdict = await import('../web/brief/verdict.ts'), regs = await import('../web/regs.ts');
  assert.equal(t('brief.boat.note'), boat.BOAT_MODEL_NOTE);
  assert.equal(t('brief.boat.reference'), boat.REFERENCE_BOAT_NAME);
  for (const [k, word] of Object.entries(verdict.VERDICT_WORD)) assert.equal(t(`brief.verdict.${k}`), word);
  assert.equal(regs.ruleSummary(null, 'lingcod', {status: 'closed', today: ''}, {id: 'x'}).label, 'Closed');
  assert.equal(regs.ruleSummary(null, 'lingcod', {status: 'closed', today: ''}, {id: 'x'}, 'es').label, 'Cerrado');
});

test('regulation numbers, species and source names are identical in both languages; the document lang follows the choice', async () => {
  const m = await load(), { region, data } = await registry();
  try {
    m.markData.value = {region, atlas: null, survey: null, geology: null}; m.regsData.value = {region: region.id, data}; m.species.value = 'salmon'; m.profile.value = 'boat';
    const mark = {id: 'spot:x', name: 'x', kind: 'Reef mark', reading: '', source: '', basis: ''};
    const cells = html => [...html.matchAll(/<dd[^>]*>(.*?)<\/dd>/g)].map(x => x[1]), hrefs = html => [...html.matchAll(/href="([^"]+)"/g)].map(x => x[1]);
    m.language.value = 'en'; const en = m.render(m.h(m.RulesLine, {mark}));
    m.language.value = 'es'; const es = m.render(m.h(m.RulesLine, {mark}));
    assert.ok(cells(en).length > 0, 'the card has bag and size values');
    assert.deepEqual(cells(es), cells(en), 'bag and size clauses are the registry\'s own words');
    assert.deepEqual(hrefs(es), hrefs(en), 'the official links are the same');
    assert.match(es, /aria-label="Reglas de un vistazo: /); assert.match(es, /<dt>Límite de captura<\/dt>/); assert.match(es, /<dt>Talla<\/dt>/);
    assert.match(es, /<dd class="ui-mono" lang="en">/, 'rule wording is marked English'); assert.doesNotMatch(en, /lang="en"/);
    assert.ok(es.includes(t('rules.english', 'es')) && !en.includes(t('rules.english', 'es')), 'a Spanish card says its rule wording is English');
    assert.ok(es.includes(t('rules.status.restricted', 'es')) || es.includes(t('rules.status.open', 'es')) || es.includes(t('rules.status.unknown', 'es')), 'the status label is Spanish');
  } finally { m.language.value = 'en'; m.markData.value = null; m.regsData.value = null; m.species.value = null; }
  const doc = {documentElement: {lang: 'en'}}, store = new Map(), storage = {getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, v)};
  assert.equal(initLanguage({search: '', storage, languages: ['es-MX', 'en'], doc}), 'es'); assert.equal(doc.documentElement.lang, 'es');
  assert.equal(initLanguage({search: '?lang=en', storage, languages: ['es-MX'], doc}), 'en', 'a link\'s choice beats the header'); assert.equal(doc.documentElement.lang, 'en');
  assert.equal(initLanguage({search: '', storage, languages: ['es'], doc}), 'en', 'and is remembered');
  assert.equal(initLanguage({search: '?lang=fr', storage, languages: ['es'], doc}), 'en', 'an unsupported link choice is ignored; the remembered one stands');
  assert.equal(initLanguage({search: '', storage: {getItem() { throw Error('blocked'); }, setItem() {}}, languages: ['es'], doc}), 'es', 'blocked storage: the header decides');
  language.value = 'en';
});

test('numbers and dates follow the locale; a fixed zone fixes the day', async () => {
  const m = await load();
  assert.equal(localeOf('es'), 'es'); assert.equal(localeOf('en'), 'en-US');
  assert.equal(num(1.5, 'es'), '1,5'); assert.equal(num(1.5, 'en'), '1.5'); assert.equal(num(1234.5, 'es', 0), '1235', 'no grouping');
  const TZ = 'America/Los_Angeles';
  assert.equal(m.leadDayText('2026-09-30', NOW, TZ, 'es'), 'hoy'); assert.equal(m.leadDayText('2026-10-01', NOW, TZ, 'es'), 'mañana');
  assert.equal(m.leadDayText('2026-10-10', NOW, TZ), 'Sat Oct 10'); assert.match(m.leadDayText('2026-10-10', NOW, TZ, 'es'), /^el sáb\.? 10 oct\.?$/);
  assert.equal(m.leadDayText('2026-10-01', NOW, TZ), 'tomorrow', 'English is the default');
});

test('with the language es the first answer, the brief and its footer render Spanish; English is unchanged', async () => {
  const m = await load();
  try {
    await setup(m);
    m.language.value = 'en';
    const en = m.render(m.h(m.App, {now: NOW})), enBrief = m.render(m.h(m.Verdict, {now: NOW}));
    assert.match(answer(en), /<h2 class="app-first-answer-line">(?:Yes|Marginal|No|Not known yet) - tomorrow/);
    m.language.value = 'es';
    const es = m.render(m.h(m.App, {now: NOW})), esAnswer = answer(es), esBrief = m.render(m.h(m.Verdict, {now: NOW})), footer = m.render(m.h(m.BriefFooter, {}));
    assert.match(esAnswer, /<h2 class="app-first-answer-line">(?:Sí|Dudoso|No|Aún no se sabe) - mañana/);
    assert.match(esAnswer, /aria-label="La respuesta"/); assert.match(esAnswer, />Ver el mapa y el detalle</); assert.match(esAnswer, /Reglas (?:revisadas|pendientes de revisión|no disponibles)/);
    assert.match(esAnswer, />Reglas oficiales</); assert.doesNotMatch(esAnswer, /Official rules|Show the map|Rules reviewed/);
    assert.match(esBrief, /<span class="app-verdict-word">(?:Cómodo|Marginal|Agitado|Desconocido)<\/span>/); assert.match(esBrief, /mañana/);
    assert.doesNotMatch(esBrief, /Comfortable|Rough|tomorrow/);
    assert.match(esBrief, /<span lang="en">/, 'the rules reason is the registry\'s English and is marked'); assert.match(esBrief, /\(en inglés\)/);
    assert.doesNotMatch(enBrief, /lang="en"|en inglés/);
    assert.ok(footer.includes(t('brief.disclaimer', 'es')) && footer.includes('>Términos<') && footer.includes('>Fuentes<'), footer);
    assert.match(m.render(m.h(m.BriefTiles, {brief: null})), /Viento.*Oleaje.*Agua.*Marea/s);
    assert.match(m.render(m.h(m.Details, {brief: null})), /<summary>Detalles/);
    m.feedGaps.value = [m.FEED_GAP.conditions, 'a gap the catalogue does not know'];
    const gaps = m.render(m.h(m.BriefGaps, {brief: null}));
    assert.ok(gaps.includes(t('brief.gap.conditions', 'es')) && gaps.includes('a gap the catalogue does not know') && gaps.includes('aria-label="Lecturas faltantes"'), gaps);
    m.language.value = 'en'; m.feedGaps.value = [];
    assert.ok(m.render(m.h(m.App, {now: NOW})) === en, 'back to English: byte-for-byte the same page');
  } finally { m.language.value = 'en'; m.feedGaps.value = []; reset(m); }
});

test('check_copy.mjs: clean on main, and fails on a gap, an unknown id and a newly added bare literal (positive control)', async () => {
  assert.deepEqual(catalogueProblems(), [], 'main\'s files and catalogue are clean');
  const root = await mkdtemp(join(tmpdir(), 'i18n-lint-'));
  const put = async (path, text) => { await mkdir(join(root, path, '..'), {recursive: true}); await writeFile(join(root, path), text); };
  await put('catalog/app/strings.json', JSON.stringify({strings: {'x.ok': {en: 'One', es: 'Uno'}, 'x.gap': {en: 'Two', es: ''}}}));
  await put(COVERED[0], "import {t} from './i18n.ts';\nexport const a = (l) => t('x.ok', l);\n");
  assert.deepEqual(catalogueProblems(root).map(p => p.replace(/^.*?: /, '')), ['x.gap has no es value (it renders English)'], 'a catalogue id with no es value is a gap');
  await put(COVERED[0], "import {t} from './i18n.ts';\nexport const a = (l) => t('x.ok', l) + t('x.missing', l) + 'Rules due for review today';\n");
  const found = catalogueProblems(root).join('\n');
  assert.match(found, /t\('x\.missing'\) is not in catalog/); assert.match(found, /bare literal "Rules due for review today"/);
  await put(COVERED[1], "export const V = () => <p class=\"app-note\">Not translated yet</p>;\n");
  assert.match(catalogueProblems(root).join('\n'), /Brief\.tsx:1 bare literal "Not translated yet"/, 'JSX text counts');
  assert.deepEqual(catalogueProblems(await mkdtemp(join(tmpdir(), 'i18n-none-'))), [], 'no catalogue, nothing to check');
});

const answer = html => /<section class="app-first-answer"[\s\S]*?<\/section>/.exec(html)?.[0] ?? '';

let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'i18n-')), 'm.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {App, regionInfo} from './web/app/App.tsx';
      export {RulesLine} from './web/app/MarkCard.tsx';
      export {BriefFooter, BriefGaps, BriefTiles, Details, FEED_GAP, Verdict, dailyFeed, feedGaps, leadDayText, regionalForecast} from './web/brief/Brief.tsx';
      export {parseConditionsForecast} from './web/conditions.ts';
      export {language} from './web/i18n.ts';
      export {markData} from './web/map/marks.ts';
      export {regsData} from './web/regs.ts';
      export {hour, day, species, profile} from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins,
  });
  return (mod = await import(pathToFileURL(out).href));
}

/** The frozen FE-61 registry with fresh synthetic source checks (as tests/test_first_answer.mjs builds it). */
async function registry() {
  const fixture = JSON.parse(await readFile(new URL('./fixtures/regulations/fe61-v1.json', import.meta.url))), d = structuredClone(fixture.regulations);
  d.reviewed_at = new Date(NOW.getTime() - 3_600_000).toISOString(); d.rules_review_status = 'reviewed';
  for (const [id, source] of Object.entries(d.sources)) {
    source.approved_content_sha256 = 'a'.repeat(64);
    d.checks[id] = {url: source.url, normalization: source.normalization, status: 'unchanged', source_status: 'ok', content_sha256: 'a'.repeat(64), data_retrieved_at: NOW.toISOString()};
  }
  return {region: fixture.region, data: d};
}

/** A calm synthetic forecast (5 kn all through) ending 16 days after 29 September. */
function forecastFeed(region) {
  const start = Date.parse('2026-09-29T07:00:00Z') / 1000, time = Array.from({length: 16 * 24}, (_, i) => start + i * 3600);
  const series = values => ({utc_offset_seconds: 0, hourly_units: {time: 'unixtime', ...Object.fromEntries(Object.entries(values).map(([k, [, u]]) => [k, u]))}, hourly: {time, ...Object.fromEntries(Object.entries(values).map(([k, [v]]) => [k, time.map(() => v)]))}});
  const meta = {last_run_initialisation_time: NOW.getTime() / 1000 - 6 * 3600, data_end_time: time.at(-1)};
  return {region_id: region, retrieved: NOW.getTime() - 20 * 60_000, requested_points: [['monterey-bay', 36.7, -121.95], ['offshore-0-0', 36.5, -122.25]],
    models: {gfs_global: {meta, data: [0, 1].map(() => series({wind_speed_10m: [5, 'kn'], wind_gusts_10m: [9, 'kn'], wind_direction_10m: [300, '°'], temperature_2m: [60, '°F'], cloud_cover: [30, '%']}))},
      ncep_gfswave016: {meta, data: [0, 1].map(() => series({wave_height: [2, 'ft'], wave_period: [12, 's']}))}}};
}

async function setup(m) {
  const {region, data} = await registry();
  m.regionInfo.value = {id: region.id, name: region.name, center: region.map.center, timezone: region.timezone, rules: region}; m.dailyFeed.value = {...montereyDaily, region_id: region.id};
  m.regionalForecast.value = m.parseConditionsForecast(forecastFeed(region.id), region.id, region.map.center);
  m.regsData.value = {region: region.id, data}; m.species.value = 'salmon'; m.profile.value = 'boat'; m.hour.value = null; m.day.value = null;
}
const reset = m => { m.regionInfo.value = null; m.dailyFeed.value = null; m.regionalForecast.value = null; m.regsData.value = null; m.species.value = null; };
