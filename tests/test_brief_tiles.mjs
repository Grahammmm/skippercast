// SC1137-01: the brief tiles' own words (source line, age, provisional, basis popover, empty state)
// come from the string catalogue. English stays byte-identical; Spanish keeps source names as published.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import {COVERED, NOT_COVERED} from '../scripts/check_copy.mjs';

const ROOT = new URL('..', import.meta.url).pathname;
let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'tiles-')), 'tiles.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {Tiles, tileProps, ageText, sourceLine, emptyTiles} from './web/brief/Tiles.tsx';
      export {language, STRINGS} from './web/i18n.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: rendererPlugins,
  });
  mod = await import(pathToFileURL(out).href);
  return mod;
}

const MIN = 60_000, HOUR = 60 * MIN, DAY = 24 * HOUR;
const tile = (id, over = {}) => ({id, label: id[0].toUpperCase() + id.slice(1), value: 5, unit: 'kt', detail: 'detail', source: 'NDBC 46042', sourceUrl: null,
  state: 'fresh', ageMs: 5 * HOUR, limitMs: 3 * HOUR, lastGood: false, ...over});

test('tile_age_boundaries_and_defaults: English results unchanged even while the page is Spanish', async () => {
  const {ageText, sourceLine, language} = await load();
  language.value = 'es';
  try {
    const cases = [[-1, 'clock ahead'], [0, '0 min'], [59 * MIN, '59 min'], [60 * MIN, '1 h'], [47 * HOUR, '47 h'], [48 * HOUR, '2 d'], [5 * DAY, '5 d']];
    for (const [ms, want] of cases) assert.equal(ageText(ms), want);
    assert.equal(ageText(-1, 'es'), 'reloj adelantado');
    assert.equal(ageText(47 * HOUR, 'es'), '47 h');
    assert.equal(sourceLine(tile('water')), 'NDBC 46042 · 5 h old');
    assert.equal(sourceLine(tile('water'), true), 'NDBC 46042 · 5 h');
    assert.equal(sourceLine(tile('water', {lastGood: true})), 'NDBC 46042 · last good 5 h old');
    assert.equal(sourceLine(tile('water', {lastGood: true}), true), 'NDBC 46042 · last good 5 h');
    assert.equal(sourceLine(tile('water', {ageMs: null, lastGood: true})), 'NDBC 46042 · unavailable');
    assert.equal(sourceLine(tile('water', {state: 'unavailable'}), false, 'es'), 'NDBC 46042 · no disponible');
    assert.equal(sourceLine(tile('water'), false, 'es'), 'NDBC 46042 · antigüedad: 5 h');
    assert.equal(sourceLine(tile('water'), true, 'es'), 'NDBC 46042 · 5 h');
    assert.equal(sourceLine(tile('water', {lastGood: true}), false, 'es'), 'NDBC 46042 · última lectura válida, antigüedad: 5 h');
    assert.equal(sourceLine(tile('water', {lastGood: true}), true, 'es'), 'NDBC 46042 · última lectura válida, 5 h');
    assert.equal(sourceLine(tile('water', {ageMs: -1}), false, 'es'), 'NDBC 46042 · antigüedad: reloj adelantado');
  } finally { language.value = 'en'; }
});

test('tiles_chrome_en_es_en: exact English, exact Spanish, English again', async () => {
  const {Tiles, tileProps, emptyTiles, language, render, h} = await load();
  const tides = tile('tide', {unit: 'ft', detail: 'Rising · MLLW', source: 'NOAA 9413450 Monterey', sourceUrl: 'https://example.test/s?a=1&b=2', lastGood: true, limitMs: 18 * HOUR, ageMs: 2 * HOUR});
  const set = [tile('wind'), tile('swell', {state: 'unavailable', ageMs: null}), tile('water', {state: 'stale'}), tides];
  const html = (lang, over = {}) => { language.value = lang; return render(h(Tiles, {tiles: set, provisional: true, ...over})); };
  try {
    const en = html('en');
    assert.ok(en.includes('NDBC 46042 · 5 h old · provisional'), 'English wind source + provisional');
    assert.ok(en.includes('NDBC 46042 · unavailable · provisional'), 'unavailable forecast tile still provisional');
    assert.ok(en.includes('NDBC 46042 · 5 h old</'), 'water has no provisional');
    assert.ok(en.includes('NOAA 9413450 Monterey · last good 2 h old'));
    assert.ok(en.includes('Reference level: MLLW. Source: ') && en.includes('. The latest check failed; this is the last good reading. Shown as stale after 18 h.'));
    assert.ok(en.includes('Forecast hour nearest the selected time, in knots with the gust; the issue time sets the age. Source: '));
    const es = html('es');
    assert.ok(es.includes('NDBC 46042 · antigüedad: 5 h · provisional'));
    assert.ok(es.includes('NDBC 46042 · no disponible · provisional'));
    assert.ok(es.includes('NOAA 9413450 Monterey · última lectura válida, antigüedad: 2 h'));
    assert.ok(es.includes('Nivel de referencia: MLLW. Fuente: '));
    assert.ok(es.includes('La última revisión falló; esta es la última lectura válida. Se muestra como desactualizada después de 18 h.'));
    assert.ok(es.includes('Viento') && es.includes('Marea'));
    assert.ok(!es.includes('Source:') && !es.includes('unavailable'), 'no English chrome left in Spanish');
    assert.ok(html('en') === en, 'English comes back byte-identical');
    // empty states, both swell profiles, in the same three modes
    for (const nearshore of [false, true]) for (const mode of [{}, {compact: true}, {dense: true}]) {
      const e = html('en', {tiles: null, nearshore, ...mode}), s = html('es', {tiles: null, nearshore, ...mode});
      assert.ok(e.includes(nearshore ? 'Nearshore site —' : 'Offshore —') && e.includes('NWS —') && e.includes('Station —'));
      assert.ok(s.includes(nearshore ? 'Sitio cercano a la costa —' : 'Mar adentro —') && s.includes('NWS —') && s.includes('Estación —') && s.includes('Boya —'));
    }
    assert.equal(emptyTiles(true)[1].basis, 'Nearest fresh nearshore model site (CDIP MOP): significant height and period.');
    assert.equal(emptyTiles(false, 'es')[1].basis, 'Boya mar adentro o pronóstico de modelo: altura significativa y período.');
    // compact keeps no basis, in both languages
    assert.equal(tileProps(tides, true, false, 'es').basis, undefined);
  } finally { language.value = 'en'; }
});

test('tile_basis_and_names_are_escaped: source names stay text, the link keeps its attributes', async () => {
  const {tileProps, render, h, language} = await load();
  const nasty = tile('swell', {source: 'CDIP MOP <b>"Sitio"</b> & last good', sourceUrl: 'https://example.test/x?a=1&b=2', limitMs: 36 * HOUR});
  try {
    for (const lang of ['en', 'es']) {
      const p = tileProps(nasty, false, false, lang);
      assert.ok(p.source.startsWith('CDIP MOP <b>"Sitio"</b> & last good · '), 'source text unchanged');
      const html = render(h('div', null, p.basis));
      assert.ok(html.includes('&lt;b>') && !html.includes('<b>'), 'markup escaped: ' + html);
      assert.ok(html.includes('href="https://example.test/x?a=1&amp;b=2"') && html.includes('rel="noopener"') && html.includes('target="_blank"'));
      assert.ok(html.includes(' 36 h.'), 'stale limit unchanged');
      assert.ok(!html.includes('Reference level') && !html.includes('Nivel de referencia'), 'no datum on a swell tile');
    }
  } finally { language.value = 'en'; }
});

test('tiles_classification_and_catalogue_positive_controls', async () => {
  const {STRINGS} = await load();
  assert.equal(COVERED.filter(p => p === 'web/brief/Tiles.tsx').length, 1);
  assert.ok(!('web/brief/Tiles.tsx' in NOT_COVERED));
  const ids = Object.keys(STRINGS).filter(k => k.startsWith('tile.'));
  assert.ok(ids.length >= 29);
  const vars = s => [...s.matchAll(/\{(\w+)\}/g)].map(m => m[1]).sort().join();
  for (const id of ids) {
    assert.ok(STRINGS[id].es, `${id} has Spanish`);
    assert.equal(vars(STRINGS[id].es), vars(STRINGS[id].en), `${id} placeholders match`);
  }
  const src = await readFile(join(ROOT, 'web/brief/Tiles.tsx'), 'utf8');
  for (const m of src.matchAll(/t\(['`]([\w.$]+)['`]/g)) if (!m[1].includes('$')) assert.ok(m[1] in STRINGS, `${m[1]} exists`);
});

test('SC1137-02 tile detail: the tile props carry the detail in the page language; compact hides it; English stays the model line', async () => {
  const {tileProps} = await load();
  const tide = tile('tide', {unit: 'ft', detail: 'Rising · Monterey · MLLW', source: 'NOAA 9413450 Monterey',
    display: {parts: [{kind: 'tideTrend', trend: 'Rising'}, {kind: 'literal', text: 'Monterey'}, {kind: 'literal', text: 'MLLW'}], datum: 'MLLW'}});
  assert.equal(tileProps(tide, false, false, 'en').detail, 'Rising · Monterey · MLLW');
  assert.equal(tileProps(tide, false, false, 'es').detail, 'Subiendo · Monterey · MLLW');
  assert.equal(tileProps(tide, true, false, 'es').detail, undefined);
  assert.equal(tileProps(tile('water', {detail: 'detail'}), false, false, 'es').detail, 'detail', 'a tile without display keeps its text');
});
