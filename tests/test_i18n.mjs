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
import {LANGUAGES, LANGUAGE_KEY, acceptedLanguage, initLanguage, language, localeOf, lookup, num, resolveLanguage, setLanguage, supported, t} from '../web/i18n.ts';
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
  assert.match(m.comfortBasis({loa_ft: 18.5}, 'es'), /18,5 ft/);
  assert.match(m.comfortBasis({loa_ft: 18.5}, 'en'), /18\.5 ft/);
});

test('Spanish verdict window and model agreement times use the region clock, not English labels', async () => {
  const m = await load(), tz = 'America/Los_Angeles';
  const at = hour => Date.parse(`2026-10-01T${String(hour + 7).padStart(2, '0')}:00:00Z`);
  const clock = ms => new Intl.DateTimeFormat('es', {hour: 'numeric', minute: '2-digit', timeZone: tz}).format(ms).replace(':00', '').toLowerCase();
  try {
    await setup(m);
    m.language.value = 'es';
    const f = m.regionalForecast.value;
    f.models.ecmwf_ifs025 = structuredClone(f.models.gfs_global);
    f.models.ecmwf_wam = structuredClone(f.models.ncep_gfswave016);
    const html = m.render(m.h(m.Verdict, {now: NOW}));
    const window = /data-day="2026-10-01">([^<]*)</.exec(html)[1];
    assert.match(window, new RegExp(`${clock(at(12))}$`));
    assert.doesNotMatch(window, /am|pm|noon|midnight/);
    const agree = /data-agreement="agree">([^<]*)</.exec(html)[1];
    assert.ok(agree.includes(`hasta ${clock(at(12))}`), agree);
    f.models.ecmwf_ifs025.data.hourly.wind_speed_10m.fill(25);
    const differ = /data-agreement="differ">([^<]*)</.exec(m.render(m.h(m.Verdict, {now: NOW})))[1];
    assert.doesNotMatch(differ, /am|pm|noon|midnight/);
    assert.ok(differ.includes(`a las ${clock(at(7))}`), differ);
  } finally { m.language.value = 'en'; reset(m); }
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
    assert.match(esAnswer, /<h2 class="app-first-answer-line">(?:Sí|Marginal|No|Aún no se sabe) - mañana/);
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

test('first_answer_es_marginal_not_dudoso: the Spanish first answer uses the brief\'s word Marginal, keeps its sentence and its day', () => {
  const es = catalogue.strings['fa.marginal'].es;
  assert.equal(es, 'Marginal - {day} es un día límite para pescar.');
  assert.equal(t('fa.marginal', 'es', {day: 'mañana'}), 'Marginal - mañana es un día límite para pescar.');
  assert.ok(es.startsWith(`${catalogue.strings['brief.verdict.marginal'].es} - `), 'the same word as the brief verdict');
  assert.doesNotMatch(es, /Dudoso/);
  assert.equal(es.split('{day}').length, 2, 'the placeholder appears once');
});

test('first_answer_es_rough_not_choppy: the Spanish too-rough sentence uses agitado, not picado, and stays a negative; Choppy keeps picado', () => {
  const es = catalogue.strings['fa.no'].es;
  assert.equal(es, 'No - {day} el mar está demasiado agitado para pescar.');
  assert.equal(t('fa.no', 'es', {day: 'mañana'}), 'No - mañana el mar está demasiado agitado para pescar.');
  assert.ok(es.includes(catalogue.strings['brief.verdict.rough'].es.toLowerCase()), 'the brief\'s Agitado, in sentence case');
  assert.doesNotMatch(es, /picado/);
  assert.equal(es.split('{day}').length, 2, 'the placeholder appears once');
  assert.equal(catalogue.strings['verdict.band.choppy'].es, 'picado', 'Choppy is still picado');
});

test('first_answer_en_templates_unchanged: the English first-answer templates are the old literals', () => {
  assert.equal(catalogue.strings['fa.marginal'].en, 'Marginal - {day} is a borderline day to fish.');
  assert.equal(catalogue.strings['fa.no'].en, 'No - {day} looks too rough to fish.');
  assert.equal(t('fa.marginal', 'en', {day: 'tomorrow'}), 'Marginal - tomorrow is a borderline day to fish.');
  assert.equal(t('fa.no', 'en', {day: 'tomorrow'}), 'No - tomorrow looks too rough to fish.');
});

test('the verdict reason (limit and hold) is Spanish and the same sentence on the Brief and the first answer; flipping back restores English', async () => {
  const m = await load();
  const limitOf = html => /<p class="app-verdict-limit">([^<]*)<\/p>/.exec(html)?.[1] ?? '';
  const reasonOf = html => /<p class="app-first-answer-reason">([^<]*)<\/p>/.exec(html)?.[1] ?? '';
  // Each case: the change to the synthetic feed and the Spanish sentence both surfaces must show (the English one is the old literal).
  const cases = {
    held: [() => {}, 'Viento de hasta 5 kt y mar de hasta 2 ft hasta las 12. Se mantiene en Marginal: el detalle del pronóstico es parcial; la revisión de avisos marinos no está disponible.'],
    rough: [() => { const g = m.regionalForecast.value.models.gfs_global.data.hourly; g.wind_speed_10m.fill(34); g.wind_gusts_10m.fill(42); },
      'Viento de 34 kt con ráfagas de 42 a las 7. No hay una revisión actual de avisos marinos.'],
    unknown: [() => { m.regionalForecast.value = null; }, 'Aún no hay pronóstico para este día.'],
  };
  try {
    for (const [name, [change, want]] of Object.entries(cases)) {
      await setup(m); change();
      m.language.value = 'en';
      const en = {limit: limitOf(m.render(m.h(m.Verdict, {now: NOW}))), reason: reasonOf(answer(m.render(m.h(m.App, {now: NOW}))))};
      m.language.value = 'es';
      const es = {limit: limitOf(m.render(m.h(m.Verdict, {now: NOW}))), reason: reasonOf(answer(m.render(m.h(m.App, {now: NOW}))))};
      assert.equal(es.limit, want, `${name}: the Brief says why in Spanish`);
      assert.equal(es.reason, want, `${name}: the first answer repeats the Brief's Spanish sentence`);
      assert.equal(en.reason, en.limit, `${name}: the English first answer repeats the Brief's sentence`);
      assert.doesNotMatch(en.limit, /[áéíóúñ]/, `${name}: the English sentence is the old one`);
      m.language.value = 'en';
      assert.equal(limitOf(m.render(m.h(m.Verdict, {now: NOW}))), en.limit, `${name}: back to English restores the sentence`);
      reset(m);
    }
  } finally { m.language.value = 'en'; reset(m); }
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
      export {BriefFooter, BriefGaps, BriefTiles, Details, FEED_GAP, Verdict, comfortBasis, dailyFeed, feedGaps, leadDayText, regionalForecast} from './web/brief/Brief.tsx';
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

// SC0452-10: Where to look and the Boat run line, rendered from the bundled components in both languages.
let wr;
async function loadWR() {
  if (wr) return wr;
  const out = join(await mkdtemp(join(tmpdir(), 'i18n-wr-')), 'wr.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {WhereToLook, boatPicks, pickRun, routeWhyText, diveText, screenLine} from './web/brief/WhereToLook.tsx';
      export {EntranceLine, RunLine, runText, runBasis, fishingWords} from './web/brief/Run.tsx';
      export {regionInfo} from './web/app/region-info.ts';
      export {regsData} from './web/regs.ts';
      export {cruiseSpeed, wantedHours} from './web/limits.ts';
      export {reachRange, spearPlan} from './web/reach.ts';
      export {landWater} from './web/land-water.ts';
      export {language} from './web/i18n.ts';
      export {profile, region, selection, habitat, species} from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins,
  });
  return (wr = await import(pathToFileURL(out).href));
}

const TZ = 'America/Los_Angeles';
const WINDOW = {start: '2026-10-12T14:00:00.000Z', end: '2026-10-12T19:00:00.000Z', label: 'Lower wind & offshore seas', confidence: 'Low', reasons: [], wind: 8, gust: 12, wave: 3, period: 10};
const runBrief = (over = {}) => ({profile: 'boat', windows: [WINDOW], alerts: [], missing: [], tiles: [{id: 'wind', state: 'fresh'}], limits: {custom: false}, sunrise: null, sunset: null, ...over});
const SCREEN = {inside: false, name: null, distanceM: null, screened: true};
const spot = (id, nm, screen = SCREEN) => ({id, kind: 'spot', name: `Reef ${id}`, distance: `${nm} nm`, nm, depth: '~60–90 ft', fit: 'Fits', reason: 'Hard bottom.', screen});
const MARKUP = '<img src=x onerror=alert(1)> Reserve';

test('where_screen_es_all_verdicts: the list, its screen lines and its heading read Spanish; a closure name is shown as published; English is byte-identical after the round trip', async () => {
  const m = await loadWR();
  try {
    m.profile.value = 'boat'; m.cruiseSpeed.value = 20; m.reachRange.value = {boat: 12};
    const r = {source: 'atlas', label: 'Survey reef atlas', basis: 'How it ranks.', empty: '', harbor: 'Morro Bay',
      picks: [spot('a', 7.4, {inside: false, name: null, distanceM: null, screened: false}), spot('b', 3.1, {inside: true, name: MARKUP, distanceM: 0, screened: true}),
        spot('c', 2.2, {inside: false, name: 'Área Marina Protegida de Piedras Blancas', distanceM: 39.6, screened: true}), spot('d', 1.1)]};
    m.language.value = 'en'; const en = m.render(m.h(m.WhereToLook, {ranking: r}));
    m.language.value = 'es'; const es = m.render(m.h(m.WhereToLook, {ranking: r}));
    assert.match(en, /<h2 class="ui-eyebrow">Where to look<\/h2>/); assert.match(es, /<h2 class="ui-eyebrow">Dónde buscar<\/h2>/);
    assert.match(en, /Protected areas not checked/); assert.match(es, /Áreas protegidas sin revisar/);
    assert.match(en, /Inside &lt;img src=x onerror=alert\(1\)> Reserve/); assert.match(es, /Dentro de &lt;img src=x onerror=alert\(1\)> Reserve/);
    assert.match(en, /40 m from Área Marina Protegida de Piedras Blancas/); assert.match(es, /A 40 m de Área Marina Protegida de Piedras Blancas/);
    assert.doesNotMatch(en + es, /<img/, 'a closure name is text, never markup');
    assert.equal((es.match(/app-pick-reason">(?:Áreas protegidas|Dentro|A \d)/g) ?? []).length, 3, 'the clear pick adds no screen line');
    assert.match(en, /7\.4 nm straight line · ~60–90 ft · run ≥ 25 min</); assert.match(es, /7,4 nm en línea recta · ~60–90 ft · recorrido ≥ 25 min</);
    assert.match(es, /aria-label="Acerca de la clasificación survey reef atlas"/); assert.match(en, /aria-label="About the survey reef atlas ranking"/);
    assert.match(es, /Morro Bay/, 'the harbor is shown as published');
    m.language.value = 'en';
    assert.ok(m.render(m.h(m.WhereToLook, {ranking: r})) === en, 'en to es to en: the same English page');
  } finally { m.language.value = 'en'; m.profile.value = 'boat'; m.cruiseSpeed.value = null; m.reachRange.value = {}; }
});

test('where_routes_and_controls_es: by water, route reasons, the range and dive controls, and the search plan labels', async () => {
  const m = await loadWR(), {distanceNm} = await import('../dist/spot-ranking.js'), {landWaterModel} = await import('../web/land-water.ts');
  const REASONS = {'no-product': ['no land/water data', 'sin datos de tierra y agua'], 'lines-needed': ['shoreline still loading', 'la línea de costa sigue cargando'],
    'start-not-water': ['launch/origin not on confirmed water', 'la botadura o el origen no está en agua confirmada'], 'end-not-water': ['place not on confirmed water', 'el lugar no está en agua confirmada'],
    'no-route': ['no water path found', 'no se encontró un trayecto por agua'], 'too-far': ['route search limit reached', 'se alcanzó el límite de búsqueda del trayecto']};
  const pick = {...spot('a', 3), basis: 'straight'};
  for (const [why, [en, es]] of Object.entries(REASONS)) { assert.equal(m.routeWhyText({...pick, why}), en); assert.equal(m.routeWhyText({...pick, why}, 'es'), es); }
  for (const extra of [{}, {why: 'not-a-failure'}]) { assert.equal(m.routeWhyText({...pick, ...extra}), 'water route not computed'); assert.equal(m.routeWhyText({...pick, ...extra}, 'es'), 'trayecto por agua aún sin calcular'); }
  assert.equal(m.routeWhyText({...pick, basis: 'water'}, 'es'), null); assert.equal(m.routeWhyText({...pick, nm: null}, 'es'), null);
  assert.equal(m.pickRun(7.4, 20, 'straight', 'es'), ' · recorrido ≥ 25 min'); assert.equal(m.pickRun(7.4, 20, 'water', 'es'), ' · recorrido 25 min');
  assert.equal(m.pickRun(7.4, 20, 'straight'), ' · run ≥ 25 min'); assert.equal(m.pickRun(null, 20, 'straight', 'es'), ''); assert.equal(m.pickRun(3, null, 'water', 'es'), '');
  const plan = [[60, {from: null, shoreYd: null}, 'To 60 ft', 'Hasta 60 ft'], [40, {from: 'boat', shoreYd: 300}, 'To 40 ft · from a boat', 'Hasta 40 ft · desde un barco'],
    [40, {from: 'shore', shoreYd: null}, 'To 40 ft · from shore', 'Hasta 40 ft · desde la costa'], [40, {from: 'shore', shoreYd: 300}, 'To 40 ft · 300 yd from shore', 'Hasta 40 ft · a 300 yd de la costa']];
  for (const [ft, p, en, es] of plan) { assert.equal(m.diveText(ft, p), en); assert.equal(m.diveText(ft, p, 'es'), es); }
  // A routed Boat row, the range title and the Boat/Kayak/Spear controls, rendered; the list is not routed again by changing language.
  const G = 32, N = 4096, cell = (col, row) => ({latitude: Math.atan(Math.sinh(Math.PI * (1 - 2 * (1616 + (row + 0.5) / G) / N))) * 180 / Math.PI, longitude: (671 + (col + 0.5) / G) / N * 360 - 180});
  const coast = JSON.parse(await readFile(new URL('./fixtures/land-water/coast.json', import.meta.url), 'utf8'));
  const model = landWaterModel({...coast, bounds: [-12110000, 3530000, -12075000, 3555000], tiles: {'12/671/1616': `w${G * G}`}}, 'fixture');
  const from = cell(4, 8), to = cell(28, 8), straight = distanceNm(from, to);
  const r = {source: 'atlas', label: 'Survey reef atlas', basis: 'b', empty: '', harbor: 'Fixture Harbor', origin: from, reach: 30,
    picks: [{id: 'a', kind: 'spot', name: 'Reef a', distance: `${straight.toFixed(1)} nm`, nm: straight, at: to, depth: '~60–90 ft', fit: 'Fits', reason: 'Hard bottom.', screen: SCREEN}]};
  try {
    m.region.value = 'fixture'; m.profile.value = 'boat'; m.cruiseSpeed.value = 20; m.reachRange.value = {boat: 30};
    m.landWater.value = {region: 'fixture', state: 'ready', model, lines: null, linesLoading: false};
    const [routed] = m.boatPicks(r), nm = routed.nm.toFixed(1);
    assert.equal(routed.basis, 'water');
    m.language.value = 'en'; const en = m.render(m.h(m.WhereToLook, {ranking: r}));
    m.language.value = 'es'; const es = m.render(m.h(m.WhereToLook, {ranking: r}));
    assert.ok(en.includes(`${nm} nm by water · ~60–90 ft`)); assert.ok(es.includes(`${nm.replace('.', ',')} nm por agua · ~60–90 ft · recorrido `), es);
    assert.match(es, /title="Alcance a considerar: 30 nm por agua donde haya un trayecto calculado; de lo contrario, en línea recta, desde Fixture Harbor"[^>]*>Alcance 30 nm</);
    assert.match(en, /title="Range to consider: 30 nm by water where routed, else straight line, from Fixture Harbor"[^>]*>Range 30 nm</);
    assert.ok(es.includes('Tus límites · Barco'), 'the dialog title'); assert.ok(en.includes('Your limits · Boat'));
    m.reachRange.value = {}; m.language.value = 'es';
    assert.match(m.render(m.h(m.WhereToLook, {ranking: r})), /title="Define hasta dónde buscar"[^>]*>Definir alcance</);
    m.language.value = 'en'; assert.match(m.render(m.h(m.WhereToLook, {ranking: r})), /title="Set how far out to look"[^>]*>Set range</);
    // Kayak: the reason beside a straight line, the title and the dialog in Spanish.
    m.profile.value = 'kayak'; m.reachRange.value = {kayak: 10}; m.landWater.value = {region: null, state: 'idle', model: null, lines: null, linesLoading: false};
    m.language.value = 'es'; const kayak = m.render(m.h(m.WhereToLook, {ranking: r}));
    assert.match(kayak, /data-route-why="not-computed"> · trayecto por agua aún sin calcular</); assert.ok(kayak.includes('Tus límites · Kayak') && kayak.includes('en línea recta · ~60–90 ft'));
    assert.doesNotMatch(kayak, /recorrido/, 'Kayak shows no Boat run text');
    // Spear: dive limits.
    m.profile.value = 'spear'; const spear = m.render(m.h(m.WhereToLook, {ranking: r}));
    assert.match(spear, /title="Tus límites de buceo"/); assert.match(spear, /Hasta \d+ ft/); assert.ok(spear.includes('Tus límites · Pesca submarina'));
    m.language.value = 'en'; const spearEn = m.render(m.h(m.WhereToLook, {ranking: r}));
    assert.match(spearEn, /title="Your dive limits"/); assert.match(spearEn, /To \d+ ft/);
    // Shore keeps its list, with no range control, in Spanish too.
    m.profile.value = 'shore'; m.language.value = 'es'; assert.doesNotMatch(m.render(m.h(m.WhereToLook, {ranking: r})), /app-where-range/);
  } finally {
    m.language.value = 'en'; m.profile.value = 'boat'; m.cruiseSpeed.value = null; m.reachRange.value = {}; m.region.value = null;
    m.landWater.value = {region: null, state: 'idle', model: null, lines: null, linesLoading: false};
  }
});

test('run_es_all_states: every state of the run line, its eight prompts and seven no-window reasons, in both languages', async () => {
  const m = await loadWR(), now = new Date('2026-10-12T12:00:00Z');
  const ranking = {source: 'atlas', label: 'Survey reef atlas', basis: '', picks: [spot('a', 7.4), spot('b', 3.1)], empty: '', harbor: 'Morro Bay'};
  const line = (over = {}, speed = 20, rank = ranking) => { m.cruiseSpeed.value = speed; return m.render(m.h(m.RunLine, {brief: runBrief(over), ranking: rank, now})); };
  const both = (over, enText, esText, speed, rank) => {
    m.language.value = 'en'; const en = line(over, speed, rank);
    m.language.value = 'es'; const es = line(over, speed, rank);
    assert.ok(en.includes(enText), `en: ${enText}`); assert.ok(es.includes(esText), `es: ${esText}\n${es}`);
    assert.ok(!en.includes(esText) || enText === esText, `en has no Spanish: ${esText}`);
    m.language.value = 'en'; assert.ok(line(over, speed, rank) === en, 'back to English: byte for byte');
  };
  try {
    m.regionInfo.value = {id: 'morro-bay', name: 'Morro Bay', center: [35.34, -120.965], timezone: TZ}; m.profile.value = 'boat'; m.selection.value = null;
    both({}, 'Up to 4 h 10 min fishing at Reef a.', 'Hasta 4 h 10 min de pesca en Reef a.');
    both({}, 'Leave 7 am · there 7:25 am · turn back 11:35 am · in by 12 pm · window 7 am–12 pm', 'Salida 7 · llegada 7:25 · regreso 11:35 · de vuelta a más tardar 12 · ventana 7–12');
    both({}, '7.4 nm straight line (water route not computed yet) · at least 25 min each way at 20 kt · top pick', '7,4 nm en línea recta (trayecto por agua aún sin calcular) · al menos 25 min por tramo a 20 kt · primera opción');
    both({}, '>basis<', '>fundamento<'); both({}, 'aria-label="Fishing time and return"', 'aria-label="Tiempo de pesca y regreso"'); both({}, '>Fishing time</span>', '>Tiempo de pesca</span>');
    both({sunrise: '2026-10-12T06:52:00-07:00', sunset: '2026-10-12T17:21:00-07:00'}, ' · Daylight 6:52 am–5:21 pm', ' · Luz del día 6:52–17:21');
    both({}, 'Set your cruise speed to see run time and when to turn back.', 'Define tu velocidad de crucero para ver el tiempo de recorrido y cuándo regresar.', null);
    both({}, '>Set cruise speed</button>', '>Definir velocidad de crucero</button>', null);
    both({}, 'Run time shows once a place to look is listed.', 'El tiempo de recorrido se muestra cuando aparece un lugar donde buscar.', 20, {...ranking, picks: []});
    both({}, 'No harbor position to measure from, so no run time.', 'Sin posición del puerto desde donde medir, no hay tiempo de recorrido.', 20, {...ranking, picks: [{...spot('a', 1), nm: null}]});
    both({}, 'No listed place is within your range, so no run time.', 'Ningún lugar de la lista está dentro de tu alcance, así que no hay tiempo de recorrido.', 20, {...ranking, reach: 5, picks: [spot('a', 7.4), spot('b', 8)]});
    both({windows: [{...WINDOW, end: '2026-10-12T14:30:00.000Z'}]}, 'The run to Reef a and back fills the 7 am–7:30 am window at 20 kt.', 'El recorrido de ida y vuelta a Reef a ocupa toda la ventana de 7–7:30 a 20 kt.');
    both({windows: [{...WINDOW, end: '2026-10-12T14:30:00.000Z'}]}, 'at least 25 min each way · top pick', 'al menos 25 min por tramo · primera opción');
    m.cruiseSpeed.value = 20;
    m.language.value = 'en'; const late = new Date('2026-10-12T18:50:00Z'), over = m.render(m.h(m.RunLine, {brief: runBrief(), ranking, now: late}));
    m.language.value = 'es'; assert.ok(over.includes('Turn-back time for the 7 am–12 pm window has passed.') && m.render(m.h(m.RunLine, {brief: runBrief(), ranking, now: late})).includes('Ya pasó la hora de regresar para la ventana de 7–12.'));
    m.selection.value = 'elsewhere';
    both({}, 'Your selected place is outside the ranked list, so times are for the top pick. Up to 4 h 10 min fishing at Reef a.', 'El lugar que seleccionaste está fuera de la lista clasificada, así que los horarios corresponden a la primera opción. Hasta 4 h 10 min de pesca en Reef a.');
    m.selection.value = null;
    // The seven reasons there is no window, each whole, in both languages.
    const wind = state => [{id: 'wind', state}], none = {windows: []};
    for (const [over, enText, esText] of [
      [{...none, alerts: [{event: 'Gale Warning'}]}, 'No return time while a marine alert is in effect.', 'Sin hora de regreso mientras haya un aviso marino vigente.'],
      [{...none, tiles: wind('unavailable')}, 'No return time without a forecast for this day.', 'Sin hora de regreso sin un pronóstico para este día.'],
      [{...none, tiles: wind('stale')}, 'No return time from a stale forecast.', 'Sin hora de regreso con un pronóstico desactualizado.'],
      [{...none, missing: ['Current marine alert check unavailable']}, 'No return time while the marine alert check is unavailable.', 'Sin hora de regreso mientras la revisión de avisos marinos no esté disponible.'],
      [{...none, missing: ['Wind missing for some forecast hours']}, 'No return time: some forecast hours are incomplete.', 'Sin hora de regreso: faltan datos en algunas horas del pronóstico.'],
      [{...none, limits: {custom: true}}, 'No lower-exposure window within your limits, so no return time.', 'Sin ventana de menor exposición dentro de tus límites, no hay hora de regreso.'],
      [none, 'No lower-exposure window for this day, so no return time.', 'Sin ventana de menor exposición para este día, no hay hora de regreso.'],
    ]) both(over, enText, esText);
    // A sentence the catalogue does not know is never guessed at: it passes through, marked as English on a Spanish page.
    m.language.value = 'es';
    assert.equal(m.runText({kind: 'no-window', reason: 'No return time while the harbor is closed.'}, TZ, false, 'es').lead, 'No return time while the harbor is closed.');
    m.language.value = 'en';
    // The bar note beside a run time, matched whole with the entrance name kept as published.
    const bar = 'Morro Bay: bar caution or unknown at departure or return (estimate); check the bar status';
    both({windows: [{...WINDOW, reasons: [bar]}]}, '<p class="app-run-note">Morro Bay: bar caution or unknown at departure or return (estimate); check the bar status.</p>',
      '<p class="app-run-note">Morro Bay: precaución o estado desconocido en la barra a la salida o al regreso (estimación); revisa el estado de la barra.</p>');
    m.language.value = 'es';
    const odd = line({windows: [{...WINDOW, reasons: ['Morro Bay: bar caution or unknown at a new time of day']}]});
    assert.match(odd, /<p class="app-run-note"><span lang="en">Morro Bay: bar caution or unknown at a new time of day<\/span>\.<\/p>/, 'unknown text stays English and is marked');
  } finally { m.language.value = 'en'; m.cruiseSpeed.value = null; m.selection.value = null; m.regionInfo.value = null; m.profile.value = 'boat'; }
});

test('closed run hours mark only the registry reason as English on a Spanish page', async () => {
  const m = await loadWR(), now = new Date('2026-10-12T12:00:00Z');
  const fixture = JSON.parse(await readFile(new URL('./fixtures/regulations/fe61-v1.json', import.meta.url), 'utf8'));
  const rules = fixture.region, data = structuredClone(fixture.regulations);
  data.reviewed_at = now.toISOString(); data.rules_review_status = 'reviewed';
  for (const [id, source] of Object.entries(data.sources)) {
    source.approved_content_sha256 = 'a'.repeat(64);
    data.checks[id] = {url: source.url, normalization: source.normalization, status: 'unchanged', source_status: 'ok', content_sha256: source.approved_content_sha256, data_retrieved_at: data.reviewed_at};
  }
  data.species.salmon.windows = [];
  const ranking = {source: 'atlas', label: 'Survey reef atlas', basis: '', picks: [spot('a', 7.4)], empty: '', harbor: 'Morro Bay'};
  const line = () => m.render(m.h(m.RunLine, {brief: runBrief(), ranking, now}));
  try {
    m.regionInfo.value = {id: rules.id, timezone: TZ, rules}; m.regsData.value = {region: rules.id, data};
    m.profile.value = 'boat'; m.species.value = 'salmon'; m.cruiseSpeed.value = 20; m.wantedHours.value = 4;
    m.language.value = 'en'; const en = line();
    assert.match(en, /data-kind="closed">Chinook salmon is closed that day: Outside the reviewed local season\./);
    assert.doesNotMatch(en, /lang="en"/);
    m.language.value = 'es'; const es = line();
    assert.match(es, /data-kind="closed">Chinook salmon está cerrado ese día: <span lang="en">Outside the reviewed local season\.<\/span>/);
    assert.match(es, /href="https:\/\/wildlife.ca.gov/);
    assert.doesNotMatch(es, /\d+ (?:h|min) disponibles/);
    m.language.value = 'en'; assert.equal(line(), en, 'English output is byte-identical after the language round trip');
  } finally {
    m.language.value = 'en'; m.regionInfo.value = null; m.regsData.value = null; m.species.value = null;
    m.cruiseSpeed.value = null; m.wantedHours.value = null;
  }
});

test('run_es_all_states: the fishing-time sentence for every branch, and the method basis, keep their limits and legal caveats', async () => {
  const m = await loadWR(), tz = TZ, opens = Date.parse('2026-10-12T15:00:00Z'), sunset = '2026-10-13T00:21:00Z';
  const cases = [
    [{kind: 'closed', label: 'Salmon', reason: 'Outside the reviewed local season'}, 'Salmon is closed that day: Outside the reviewed local season', 'Salmon está cerrado ese día: Outside the reviewed local season'],
    [{kind: 'no-wanted'}, '', ''],
    [{kind: 'none', endedBy: 'conditions'}, 'No fishing time remains — ended by the conditions window.', 'No queda tiempo de pesca: terminó por la ventana de condiciones.'],
    [{kind: 'none', endedBy: 'opening', rulesUnconfirmed: true}, 'Rules not confirmed · No fishing time remains — ended by the legal opening at 8 am.', 'Reglas sin confirmar · No queda tiempo de pesca: terminó por la apertura legal a las 8.'],
    [{kind: 'beyond-daylight', wantedMin: 600, daylightMin: 540}, '10 h wanted · the day has 9 h of daylight.', '10 h deseadas · el día tiene 9 h de luz.'],
    [{kind: 'enough', availableMin: 240, wantedMin: 180, spareMin: 60}, '3 h wanted · 4 h available (1 h to spare).', '3 h deseadas · 4 h disponibles (1 h de sobra).'],
    [{kind: 'short', availableMin: 215, wantedMin: 240, shortMin: 25, endedBy: 'opening'}, '4 h wanted · 3 h 35 min available, 25 min short — ended by the legal opening at 8 am.', '4 h deseadas · 3 h 35 min disponibles, faltan 25 min: terminó por la apertura legal a las 8.'],
    [{kind: 'short', availableMin: 215, wantedMin: 240, shortMin: 25, endedBy: 'daylight'}, '4 h wanted · 3 h 35 min available, 25 min short — ended by the sunset at 5:21 pm.', '4 h deseadas · 3 h 35 min disponibles, faltan 25 min: terminó por la puesta del sol a las 17:21.'],
    [{kind: 'short', availableMin: 215, wantedMin: 240, shortMin: 25, endedBy: 'conditions'}, '4 h wanted · 3 h 35 min available, 25 min short — ended by the conditions window.', '4 h deseadas · 3 h 35 min disponibles, faltan 25 min: terminó por la ventana de condiciones.'],
    [{kind: 'short', availableMin: 215, wantedMin: 240, shortMin: 25, endedBy: 'opening', rulesUnconfirmed: true}, 'Rules not confirmed · 4 h wanted · 3 h 35 min available; check the official rules.', 'Reglas sin confirmar · 4 h deseadas · 3 h 35 min disponibles; consulta las reglas oficiales.'],
  ];
  for (const [result, enText, esText] of cases) {
    assert.equal(m.fishingWords(result, tz, sunset, opens), enText); assert.equal(m.fishingWords(result, tz, sunset, opens, 'en'), enText);
    assert.equal(m.fishingWords(result, tz, sunset, opens, 'es'), esText);
  }
  assert.equal(m.fishingWords({kind: 'none', endedBy: 'daylight'}, tz, null, null, 'es'), 'No queda tiempo de pesca: terminó por la ventana de condiciones.', 'no sunset: the conditions edge, as in English');
  const basis = m.runBasis('Morro Bay'), es = m.runBasis('Morro Bay', 'es');
  assert.ok(basis.startsWith('Run time is the distance from Morro Bay at the cruise speed you set, rounded up to 5 minutes. It follows water cells of the NOAA shoreline and reads "by water"; '));
  assert.ok(basis.endsWith('including a 70 m planning margin. This does not determine whether transit or fishing is allowed; check the official rules.'));
  assert.ok(es.startsWith('El tiempo de recorrido usa la distancia desde Morro Bay a la velocidad de crucero que definiste, redondeada hacia arriba a 5 minutos.'));
  for (const caveat of ['no una ruta de navegación', '«por agua»', 'no autoriza el cruce de la entrada ni promete un regreso', 'consulta las reglas oficiales', 'margen de planificación de 70 m'])
    assert.ok(es.includes(caveat), caveat);
  assert.doesNotMatch(es, /\{\w+\}/);
});

test('entrance_es_judged_and_unknown: leave-by and be-back-by, caution hours on the region clock, and every not-judged reason', async () => {
  const m = await loadWR(), {entranceFor} = await import('../packages/coast/src/bar-conditions.ts');
  const HOUR = 3_600_000, start = Date.parse('2026-10-12T14:00:00Z'), entrance = entranceFor('morro-bay', 'morro-bay');
  const hours = bands => bands.map((band, i) => ({at: new Date(start + i * HOUR).toISOString(), band, tide: {stage: 'flood', midEbb: false, fraction: 0.5}, swell: {heightFt: 1, periodS: 10, basis: 'offshore', longPeriodS: null}, windAgainst: false, reasons: []}));
  const brief = (hs, ent = entrance) => ({profile: 'boat', bar: {entrance: ent, hours: hs}, sunrise: null, sunset: null, windows: [], alerts: [], tiles: [], missing: []});
  const render = (hs, lang, ent) => { m.language.value = lang; try { return m.render(m.h(m.EntranceLine, {brief: brief(hs, ent), tz: TZ})); } finally { m.language.value = 'en'; } };
  const clear = 'No bar flag', bad = 'Hazardous', name = entrance.name;
  assert.ok(render(hours([clear, clear]), 'en').includes(`${name}: Leave by 7 am · be back by 9 am. No bar flag in this window.`));
  assert.ok(render(hours([clear, clear]), 'es').includes(`${name}: Sal a más tardar 7 · vuelve a más tardar 9. Sin señal de riesgo en la barra durante esta ventana.`));
  assert.ok(render(hours([clear, 'Caution', clear]), 'en').includes('Leave by 7 am · be back by 10 am. Caution hours: 8 am.'));
  assert.ok(render(hours([clear, 'Caution', clear]), 'es').includes('Sal a más tardar 7 · vuelve a más tardar 10. Horas de precaución: 8.'));
  const unknown = hours([clear]); unknown[0].tide.stage = null;
  for (const [hs, ent, enText, esText] of [
    [hours([bad]), entrance, 'No window today.', 'No hay ventana hoy.'],
    [[], entrance, 'Entrance not judged: no hourly readings.', 'Entrada sin evaluar: no hay lecturas por hora.'],
    [unknown, entrance, 'Entrance not judged: tide or swell driver missing in the window.', 'Entrada sin evaluar: faltan datos de marea u oleaje en la ventana.'],
    [hours([clear]), {...entrance, seawardDeg: null}, 'Entrance not judged: wind against the ebb not judged (no seaward bearing).', 'Entrada sin evaluar: no se evaluó el viento contra la marea saliente (sin rumbo hacia mar abierto).'],
  ]) {
    const en = render(hs, 'en', ent), es = render(hs, 'es', ent);
    assert.ok(en.includes(`${ent.name}: ${enText}`), en); assert.ok(es.includes(`${ent.name}: ${esText}`), es);
    for (const out of [en, es]) assert.doesNotMatch(out, /Leave by|be back by|Sal a más tardar|vuelve a más tardar/, 'no time is shown for a window that is not judged');
  }
});

test('language_switch_roundtrip_and_lint: both files are covered, a bare literal or a missing es value in either fails the lint, and the new ids keep their variables', async () => {
  assert.ok(COVERED.includes('web/brief/WhereToLook.tsx') && COVERED.includes('web/brief/Run.tsx'));
  const ids = Object.keys(catalogue.strings).filter(id => /^(?:where|run)\./.test(id));
  assert.ok(ids.length >= 90, 'the where.* and run.* entries are in the catalogue');
  const sources = Object.fromEntries(await Promise.all(['web/brief/WhereToLook.tsx', 'web/brief/Run.tsx'].map(async p => [p, await readFile(join(ROOT, p), 'utf8')])));
  for (const [path, source] of Object.entries(sources)) {
    const used = new Set([...source.matchAll(/\bt\(\s*(['"`])([\w.${}-]+)\1/g)].map(x => x[2]));
    assert.ok([...used].every(id => id.includes('$') || Object.hasOwn(catalogue.strings, id)), `${path}: every id it names is in the catalogue`);
  }
  const root = await mkdtemp(join(tmpdir(), 'i18n-lint2-'));
  const put = async (path, text) => { await mkdir(join(root, path, '..'), {recursive: true}); await writeFile(join(root, path), text); };
  await put('catalog/app/strings.json', JSON.stringify({strings: {'x.ok': {en: 'One', es: 'Uno'}}}));
  for (const path of ['web/brief/WhereToLook.tsx', 'web/brief/Run.tsx']) {
    await put(path, "export const A = () => <p class=\"app-note\">Fish are biting here today</p>;\n");
    assert.match(catalogueProblems(root).join('\n'), new RegExp(`${path.replace(/[./]/g, '\\$&')}:1 bare literal "Fish are biting here today"`), `${path}: injected prose fails the lint`);
    await put(path, "import {t} from '../i18n.ts';\nexport const a = l => t('x.ok', l) + ` Not translated ${l}`;\n");
    assert.match(catalogueProblems(root).join('\n'), /bare literal/, `${path}: prose in a template literal fails`);
    await put(path, "import {t} from '../i18n.ts';\nexport const a = l => t('x.ok', l);\n");
    assert.deepEqual(catalogueProblems(root), [], `${path}: only catalogue ids is clean`);
  }
  await put('catalog/app/strings.json', JSON.stringify({strings: {'where.title': {en: 'Where to look', es: ''}}}));
  assert.match(catalogueProblems(root).join('\n'), /where\.title has no es value/, 'a removed es value fails');
});

// SC0452-08: the app menu's choice. A page is simulated by a store, a document and an address whose history.replaceState moves it.
function page(href, {languages = ['en'], store = new Map(), state = {from: 'history'}, blockStorage = false, blockHistory = false} = {}) {
  const calls = [], doc = {documentElement: {lang: 'en'}}, writes = [];
  const where = {href};
  const storage = blockStorage ? null : {getItem: k => store.get(k) ?? null, setItem: (k, v) => { writes.push(k); store.set(k, String(v)); }};
  const history = blockHistory ? {get state() { throw Error('history blocked'); }, replaceState() { throw Error('history blocked'); }}
    : {state, replaceState: (...args) => { calls.push(args); where.href = new URL(args[2], where.href).href; }};
  return {store, doc, calls, writes, where, state, env: () => ({search: new URL(where.href).search, href: where.href, storage, history, languages, doc})};
}

test('language_choice_both_directions: choosing sets the signal and the document lang at once and stores only the language key', () => {
  const p = page('https://s.test/map?region=morro-bay', {languages: ['en-US']});
  try {
    assert.equal(initLanguage(p.env()), 'en');
    assert.equal(setLanguage('es', p.env()), 'es');
    assert.equal(language.value, 'es'); assert.equal(p.doc.documentElement.lang, 'es'); assert.equal(p.store.get(LANGUAGE_KEY), 'es');
    assert.equal(setLanguage('en', p.env()), 'en');
    assert.equal(language.value, 'en'); assert.equal(p.doc.documentElement.lang, 'en'); assert.equal(p.store.get(LANGUAGE_KEY), 'en');
    assert.deepEqual([...new Set(p.writes)], [LANGUAGE_KEY], 'nothing else is written');
    assert.equal(setLanguage('fr', p.env()), 'en', 'only English and Spanish can be chosen'); assert.equal(p.store.get(LANGUAGE_KEY), 'en');
    assert.deepEqual(p.calls, [], 'an address without ?lang= is left alone: no replace, no new entry');
  } finally { language.value = 'en'; }
});

test('language_choice_reload_and_opposing_link: a stored choice survives a reload, also over the old ?lang= link', () => {
  try {
    // The browser asks for English, the visitor chooses Español, a fresh page reads it back.
    const a = page('https://s.test/map?region=morro-bay#chart', {languages: ['en']});
    initLanguage(a.env()); setLanguage('es', a.env());
    assert.equal(initLanguage(page(a.where.href, {store: a.store, languages: ['en']}).env()), 'es', 'the stored choice beats the browser');
    assert.equal(initLanguage(page(a.where.href, {store: new Map(), languages: ['en']}).env()), 'en', 'positive control: without the stored choice the browser decides');
    // ?lang=en then Español, and the inverse: only the lang value moves; query order, other parameters, hash and history.state stay.
    for (const [from, to] of [['en', 'es'], ['es', 'en']]) {
      const b = page(`https://s.test/map?region=morro-bay&lang=${from}&note=a%20b&day=2#chart`, {languages: [from === 'en' ? 'es' : 'en']});
      assert.equal(initLanguage(b.env()), from);
      setLanguage(to, b.env());
      assert.equal(b.calls.length, 1); assert.equal(b.calls[0][0], b.state, 'history.state is kept as is'); assert.equal(b.calls[0][1], '');
      assert.equal(b.where.href, `https://s.test/map?region=morro-bay&lang=${to}&note=a%20b&day=2#chart`);
      assert.equal(initLanguage(page(b.where.href, {store: b.store, languages: [from]}).env()), to, `reload keeps ${to}`);
    }
    // A bare or repeated lang parameter, and an unsupported one, are all replaced by the choice; a longer name is not touched.
    const c = page('https://s.test/map?lang&langx=1&lang=fr&lang=en');
    setLanguage('es', c.env());
    assert.equal(c.where.href, 'https://s.test/map?lang=es&langx=1&lang=es&lang=es');
    // A supported link is stored by init, and a later choice replaces the stored value too.
    const d = page('https://s.test/map?lang=es', {languages: ['en']});
    assert.equal(initLanguage(d.env()), 'es'); assert.equal(d.store.get(LANGUAGE_KEY), 'es');
    setLanguage('en', d.env()); assert.equal(d.store.get(LANGUAGE_KEY), 'en');
  } finally { language.value = 'en'; }
});

test('language_choice_storage_unavailable: blocked storage or history never throws and the choice holds for the visit', () => {
  const quota = () => { throw Object.assign(Error('full'), {name: 'QuotaExceededError'}); };
  try {
    for (const [label, storage] of [['null storage', null], ['throwing setItem', {getItem: () => null, setItem: quota}], ['throwing getItem and setItem', {getItem: quota, setItem: quota}]]) {
      const doc = {documentElement: {lang: 'en'}};
      assert.doesNotThrow(() => setLanguage('es', {storage, doc}), label);
      assert.equal(language.value, 'es', label); assert.equal(doc.documentElement.lang, 'es', label);
      assert.doesNotThrow(() => setLanguage('en', {storage, doc}), label); assert.equal(language.value, 'en', label);
      assert.doesNotThrow(() => initLanguage({search: '', storage, languages: ['es'], doc}), `init: ${label}`);
      assert.equal(language.value, 'es', `init: ${label}: the browser decides`);
    }
    const throwing = search => Object.defineProperty({search, doc: {documentElement: {lang: 'en'}}}, 'storage', {get() { throw new DOMException('denied', 'SecurityError'); }});
    assert.doesNotThrow(() => setLanguage('es', throwing(''))); assert.equal(language.value, 'es');
    assert.doesNotThrow(() => initLanguage(throwing('?lang=en'))); assert.equal(language.value, 'en', 'a supported link wins when storage cannot even be reached');
    // A supported link still wins init when its write throws.
    assert.equal(initLanguage({search: '?lang=es', storage: {getItem: () => null, setItem: quota}, languages: ['en']}), 'es');
    // History refusing does not cancel the choice (storage still takes it).
    const h = page('https://s.test/map?lang=en', {blockHistory: true});
    assert.doesNotThrow(() => setLanguage('es', h.env())); assert.equal(language.value, 'es'); assert.equal(h.store.get(LANGUAGE_KEY), 'es');
    // Both refusing: the visit keeps the choice; nothing throws.
    const both = {...page('https://s.test/map?lang=en', {blockStorage: true, blockHistory: true}).env()};
    assert.doesNotThrow(() => setLanguage('en', both)); assert.equal(language.value, 'en');
    assert.doesNotThrow(() => setLanguage('es', both)); assert.equal(language.value, 'es');
    // The page's own globals: a localStorage getter that throws (the default environment).
    const saved = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
    Object.defineProperty(globalThis, 'localStorage', {configurable: true, get() { throw new DOMException('denied', 'SecurityError'); }});
    try {
      assert.doesNotThrow(() => setLanguage('en')); assert.equal(language.value, 'en');
      assert.doesNotThrow(() => initLanguage());
    } finally { if (saved) Object.defineProperty(globalThis, 'localStorage', saved); else delete globalThis.localStorage; }
  } finally { language.value = 'en'; }
});

test('SC0707-06: first run and Your limits are covered, and their ids keep their variables in es', () => {
  assert.ok(COVERED.includes('web/app/FirstRun.tsx') && COVERED.includes('web/app/LimitsPanel.tsx'));
  const ids = Object.entries(catalogue.strings).filter(([id]) => /^(?:firstRun|boatEntry|limits)\./.test(id));
  assert.ok(ids.length >= 60, 'the three families are in the catalogue');
  const vars = text => [...text.matchAll(/\{(\w+)\}/g)].map(x => x[1]).sort().join();
  for (const [id, entry] of ids) { assert.ok(entry.es?.trim(), `${id} has an es value`); assert.equal(vars(entry.es), vars(entry.en), `${id}: same variables in en and es`); }
});

test('SC0707-07: the app shell is covered, and its ids keep their variables in es', () => {
  for (const file of ['Masthead', 'Mobile', 'CommandBar', 'AccountMenu']) assert.ok(COVERED.includes(`web/app/${file}.tsx`), file);
  const ids = Object.entries(catalogue.strings).filter(([id]) => /^(?:shell|command|accountMenu)\./.test(id));
  assert.ok(ids.length >= 88, 'the three families are in the catalogue');
  const vars = text => [...text.matchAll(/\{(\w+)\}/g)].map(x => x[1]).sort().join();
  for (const [id, entry] of ids) { assert.ok(entry.es?.trim(), `${id} has an es value`); assert.equal(vars(entry.es), vars(entry.en), `${id}: same variables in en and es`); }
});
