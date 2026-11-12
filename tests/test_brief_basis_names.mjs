// SC1722-20: each Basis disclosure in the brief is named for its row ("Source for wind") while its visible word stays, and no two
// disclosures in one brief share an accessible name. The real bundled Tiles, Tile and Popover are rendered to markup; the verdict and
// run disclosures are proved by the catalogue names they take and by e2e/v2-skip-links.spec.ts on the real page.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {preparedRendererPlugins} from './helpers/esbuild-url.mjs';

const ROOT = new URL('..', import.meta.url).pathname;
const out = join(await mkdtemp(join(tmpdir(), 'basis-names-')), 'm.mjs');
await build({stdin: {resolveDir: ROOT, loader: 'ts', contents: `
  export {Tiles} from './web/brief/Tiles.tsx';
  export {Popover} from './web/ui/Popover.tsx';
  export {Tile} from './web/ui/Tile.tsx';
  export {language} from './web/i18n.ts';
  export {render} from 'preact-render-to-string';
  export {h} from 'preact';`},
bundle: true, format: 'esm', platform: 'node', outfile: out, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: preparedRendererPlugins});
const {Tiles, Popover, Tile, language, render, h} = await import(pathToFileURL(out).href);

const HOUR = 3_600_000;
const tile = (id, over = {}) => ({id, label: id[0].toUpperCase() + id.slice(1), value: 5, unit: 'kt', detail: 'detail', source: 'NDBC 46042', sourceUrl: null, state: 'fresh', ageMs: HOUR, limitMs: 3 * HOUR, lastGood: false, ...over});
const FOUR = () => ['wind', 'swell', 'water', 'tide'].map(id => tile(id));
const NAMES = {en: ['Source for wind', 'Source for swell', 'Source for water', 'Source for tide'], es: ['Fuente del viento', 'Fuente del oleaje', 'Fuente del agua', 'Fuente de la marea']};
/** Each summary's accessible name (its aria-label, else its text) and its visible word. */
const summaries = html => [...html.matchAll(/<summary class="ui-popover-summary ui-eyebrow"(?: aria-label="([^"]*)")?>(.*?)<\/summary>/g)].map(m => ({name: m[1] ?? m[2], visible: m[2]}));
const asLang = (lang, fn) => { language.value = lang; try { return fn(); } finally { language.value = 'en'; } };

test('row_names_all_states: wind, swell, water and tide each get their own name, real or empty, nearshore or offshore, dense or full, stale or last good', () => {
  for (const lang of ['en', 'es']) asLang(lang, () => {
    const cases = {
      real: h(Tiles, {tiles: FOUR()}), dense: h(Tiles, {tiles: FOUR(), dense: true}),
      stale: h(Tiles, {tiles: ['wind', 'swell', 'water', 'tide'].map(id => tile(id, {state: 'stale', lastGood: true}))}),
      unavailable: h(Tiles, {tiles: ['wind', 'swell', 'water', 'tide'].map(id => tile(id, {value: null, state: 'unavailable', ageMs: null}))}),
      provisional: h(Tiles, {tiles: FOUR(), provisional: true}),
      emptyNearshore: h(Tiles, {tiles: null, nearshore: true}), emptyOffshore: h(Tiles, {tiles: null}),
    };
    for (const [name, vnode] of Object.entries(cases)) {
      const found = summaries(render(vnode));
      assert.deepEqual(found.map(s => s.name), NAMES[lang], `${lang} ${name}`);
      assert.equal(new Set(found.map(s => s.name)).size, 4, `${lang} ${name}: no two share a name`);
      assert.equal(new Set(found.map(s => s.visible)).size, 1, `${lang} ${name}: the visible word is unchanged and shared`);
    }
  });
});

test('compact rows have no disclosure to name, and a tile keeps its row name when its label is translated', () => {
  assert.equal(summaries(render(h(Tiles, {tiles: FOUR(), compact: true}))).length, 0);
  asLang('es', () => {
    const html = render(h(Tiles, {tiles: FOUR()}));
    assert.match(html, /<span>Viento<\/span>/, 'the label is translated');
    assert.deepEqual(summaries(html).map(s => s.name), NAMES.es, 'the name follows the row, not the translated label');
  });
});

test('opt_in_popover: the name is only set when asked for; every legacy rendering is unchanged', () => {
  const bare = render(h(Popover, {}, 'x')), named = render(h(Popover, {accessibleName: 'Source for wind'}, 'x'));
  assert.match(bare, /<summary class="ui-popover-summary ui-eyebrow">Source<\/summary>/, 'no prop: no aria-label');
  assert.match(named, /<summary class="ui-popover-summary ui-eyebrow" aria-label="Source for wind">Source<\/summary>/, 'the visible word stays');
  assert.match(render(h(Popover, {iconOnly: true, summary: 'Where'}, 'x')), /aria-label="Where"/, 'an icon-only summary is still named by its summary');
  assert.match(render(h(Popover, {iconOnly: true, summary: 'Where', accessibleName: 'Where to look'}, 'x')), /aria-label="Where to look"/);
  assert.match(render(h(Popover, {summary: ''}, 'x')), /<summary class="ui-popover-summary ui-eyebrow"><\/summary>/, 'an explicit empty summary stays empty');
  const noName = render(h(Tile, {label: 'Wind', reading: '5', basis: 'b'}));
  assert.doesNotMatch(noName, /aria-label/, 'a generic Tile keeps its markup');
  assert.match(render(h(Tile, {label: 'Wind', reading: '5', basis: 'b', basisLabel: 'Source for wind'})), /aria-label="Source for wind"/);
});

test('verdict and run names: their own catalogue words in both languages, distinct from the rows and from each other', async () => {
  const strings = JSON.parse(await readFile(join(ROOT, 'catalog/app/strings.json'), 'utf8')).strings;
  const ids = ['verdict', 'wind', 'swell', 'water', 'tide', 'run'].map(row => `a11y.basis.${row}`);
  for (const lang of ['en', 'es']) {
    const words = ids.map(id => strings[id]?.[lang]);
    assert.ok(words.every(w => typeof w === 'string' && w.trim()), `${lang}: every row has a name`);
    assert.equal(new Set(words).size, ids.length, `${lang}: all six are different`);
  }
  assert.equal(strings['a11y.basis.verdict'].en, 'Source for the verdict');
  assert.equal(strings['a11y.basis.run'].en, 'How this is worked out: run time');
  // The run disclosure's visible word stays its own "basis"/"fundamento"; the Spanish name contains it (label in name).
  assert.ok(strings['a11y.basis.run'].es.toLowerCase().includes(strings['run.basis'].es.toLowerCase()));
  for (const file of ['web/brief/Brief.tsx', 'web/brief/Run.tsx']) {
    const source = await readFile(join(ROOT, file), 'utf8');
    assert.match(source, file.endsWith('Brief.tsx') ? /accessibleName=\{t\('a11y\.basis\.verdict'/ : /accessibleName=\{t\('a11y\.basis\.run'/, file);
  }
});

// UXFIX-06: the tide basis explains MLLW in plain words; another datum keeps the plain reference-level line.
test('mllw_gloss: only a tide basis on MLLW carries the gloss, in both languages', () => {
  const GLOSS = {en: "Heights are above MLLW (mean lower low water, the chart's zero).", es: 'Alturas sobre MLLW (bajamar media inferior, el cero de la carta).'};
  const OTHER = {en: 'Reference level: NAVD88.', es: 'Nivel de referencia: NAVD88.'};
  const basis = (lang, datum) => asLang(lang, () => render(h(Tiles, {tiles: ['wind', 'swell', 'water', 'tide'].map(id => tile(id, id === 'tide' ? {detail: `Rising · ${datum}`} : {}))})));
  for (const lang of ['en', 'es']) {
    assert.ok(basis(lang, 'MLLW').includes(GLOSS[lang]), `${lang}: MLLW is explained`);
    assert.ok(!basis(lang, 'MLLW').includes(OTHER[lang].split(':')[0]), `${lang}: no bare reference line beside the gloss`);
    assert.ok(basis(lang, 'NAVD88').includes(OTHER[lang]) && !basis(lang, 'NAVD88').includes(GLOSS[lang]), `${lang}: another datum keeps today's text`);
    assert.equal(basis(lang, 'MLLW').split(GLOSS[lang]).length, 2, `${lang}: the gloss appears once, on the tide only`);
  }
});
