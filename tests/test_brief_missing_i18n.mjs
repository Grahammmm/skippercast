// SC2022-03: the brief's "Not checked in this brief" list (BriefGaps) in Spanish. packages/coast/src/daily.ts writes brief.missing in
// English; the list translates each line at render: one catalogue entry per fixed sentence (English = the producer's exact text), a
// template for each parametrised one, and any other line kept English inside lang="en". English output is the producer's text unchanged.

import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import catalogue from '../catalog/app/strings.json' with {type: 'json'};

const ROOT = new URL('..', import.meta.url).pathname;

let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'brief-missing-')), 'gaps.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {BriefGaps} from './web/brief/Brief.tsx';
      export {language, prepareCatalogue} from './web/i18n.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: rendererPlugins,
  });
  mod = await import(pathToFileURL(out).href);
  return mod;
}

/** The list items BriefGaps renders for `missing` in `lang`, as inner HTML strings. */
async function items(missing, lang) {
  const {BriefGaps, language, prepareCatalogue, render, h} = await load();
  await prepareCatalogue('es');
  language.value = lang;
  const html = render(h(BriefGaps, {brief: {gaps: [], missing}}));
  const list = /<ul>([\s\S]*)<\/ul>/.exec(html);
  assert.ok(list, 'the unchecked list renders');
  return {html, lines: [...list[1].matchAll(/<li>([\s\S]*?)<\/li>/g)].map(m => m[1])};
}

const entries = catalogue.strings;
const ids = prefix => Object.keys(entries).filter(id => id.startsWith(prefix));
/** The producer's fixed sentences: every single-quoted missing.push literal in daily.ts, and the two templates (`${...}` read as a catalogue {name}). */
function producer() {
  const source = readFileSync(join(ROOT, 'packages/coast/src/daily.ts'), 'utf8');
  const fixed = [...source.matchAll(/missing\.push\('((?:[^'\\]|\\.)*)'\)/g)].map(m => m[1].replace(/\\'/g, "'"));
  const templated = [...source.matchAll(/missing\.push\(`([^`]*)`\)/g)].map(m => m[1]);
  return {fixed, templated};
}
const FIXED_IDS = ids('brief.missing.').filter(id => !/^brief\.missing\.(field|clarity|and)/.test(id));

test('every literal missing.push sentence in daily.ts has an exact English catalogue entry and a distinct Spanish one', () => {
  const {fixed} = producer();
  assert.ok(fixed.length >= 20, `daily.ts fixed sentences read (${fixed.length})`);
  const english = new Map(FIXED_IDS.map(id => [entries[id].en, id]));
  for (const text of fixed) {
    const id = english.get(text);
    assert.ok(id, `no brief.missing catalogue entry has the English text of daily.ts sentence: ${text}`);
    assert.notEqual(entries[id].es, text, `the Spanish of ${id} differs from the English`);
  }
  assert.equal(new Set(FIXED_IDS.map(id => entries[id].en)).size, FIXED_IDS.length, 'one entry per distinct sentence');
  assert.equal(FIXED_IDS.length, new Set(fixed).size, 'no catalogue sentence the producer no longer writes');
});

test('the two templates in daily.ts are the catalogue templates', () => {
  const {templated} = producer();
  assert.ok(templated.includes('${label} missing for some forecast hours'));
  assert.ok(templated.includes("Clarity estimate needs ${spear.clarity.missing.join(' and ')}"));
  assert.equal(entries['brief.missing.field'].en, '{field} missing for some forecast hours');
  assert.equal(entries['brief.missing.clarity'].en, 'Clarity estimate needs {inputs}');
  const source = readFileSync(join(ROOT, 'packages/coast/src/daily.ts'), 'utf8');
  for (const label of ids('brief.missing.field.').map(id => entries[id].en)) assert.ok(source.includes(`'${label}'`), `daily.ts labels a field ${label}`);
});

test('Spanish page: each fixed sentence reads Spanish, in order, with no lang="en" marker', async () => {
  const {fixed} = producer();
  const {lines, html} = await items(fixed, 'es');
  assert.equal(lines.length, fixed.length);
  fixed.forEach((text, i) => {
    const id = FIXED_IDS.find(x => entries[x].en === text);
    assert.equal(lines[i], entries[id].es.replace(/&/g, '&amp;'), `line ${i}: ${text}`);
  });
  assert.ok(!html.includes('lang="en"'), 'every known sentence is translated');
  assert.match(html, /<summary>No revisado en este resumen \(\d+\)<\/summary>/);
});

test('Spanish page: the field template reads each closed label; the clarity template joins its inputs with the Spanish conjunction', async () => {
  const labels = ['Wind', 'Gusts', 'Offshore seas', 'Wave period', 'Air temperature', 'Rain probability'];
  const fields = await items(labels.map(l => `${l} missing for some forecast hours`), 'es');
  assert.deepEqual(fields.lines, ['Faltan datos de viento en algunas horas del pronóstico', 'Faltan datos de ráfagas en algunas horas del pronóstico',
    'Faltan datos de oleaje en alta mar en algunas horas del pronóstico', 'Faltan datos de período de las olas en algunas horas del pronóstico',
    'Faltan datos de temperatura del aire en algunas horas del pronóstico', 'Faltan datos de probabilidad de lluvia en algunas horas del pronóstico']);
  const clarity = await items(['Clarity estimate needs satellite chlorophyll', 'Clarity estimate needs a recent chlorophyll reading and recent swell',
    'Clarity estimate needs satellite chlorophyll and recent swell', 'Clarity estimate needs daylight forecast hours', 'Clarity estimate needs forecast hours'], 'es');
  assert.deepEqual(clarity.lines, ['La estimación de claridad necesita clorofila satelital', 'La estimación de claridad necesita una lectura reciente de clorofila y oleaje reciente',
    'La estimación de claridad necesita clorofila satelital y oleaje reciente', 'La estimación de claridad necesita horas de pronóstico con luz de día', 'La estimación de claridad necesita horas de pronóstico']);
  assert.ok(!fields.html.includes('lang="en"') && !clarity.html.includes('lang="en"'));
});

test('Spanish page: a line that matches nothing, or only partly matches, stays whole English inside lang="en", in order', async () => {
  const spear = 'Clarity estimate: satellite chlorophyll is an offshore area average and may read clearer than the shoreline';
  const odd = ['Tide curve unavailable for this date', spear, 'A future sentence <b>&</b> "x"', 'Moon missing for some forecast hours',
    'Clarity estimate needs satellite chlorophyll and the moon', 'Clarity estimate needs ', 'Wind missing for some forecast hours, really', 'Clarity estimate: wind unknown'];
  const {lines} = await items(odd, 'es');
  assert.equal(lines[0], entries['brief.missing.tideCurve'].es);
  assert.equal(lines[1], `<span lang="en">${spear}</span>`);
  assert.equal(lines[2], '<span lang="en">A future sentence &lt;b>&amp;&lt;/b> &quot;x&quot;</span>');
  assert.equal(lines[3], '<span lang="en">Moon missing for some forecast hours</span>');
  assert.equal(lines[4], '<span lang="en">Clarity estimate needs satellite chlorophyll and the moon</span>', 'no partial translation');
  assert.equal(lines[5], '<span lang="en">Clarity estimate needs </span>');
  assert.equal(lines[6], '<span lang="en">Wind missing for some forecast hours, really</span>');
  assert.equal(lines[7], '<span lang="en">Clarity estimate: wind unknown</span>');
});

test('English page: the producer text is rendered unchanged, with no span, for fixed, templated and unknown lines; nothing missing renders nothing', async () => {
  const {fixed} = producer();
  const mixed = [...fixed, 'Wind missing for some forecast hours', 'Clarity estimate needs satellite chlorophyll and recent swell', 'Clarity estimate: wind unknown', 'Odd <i>&</i>'];
  const {html, lines} = await items(mixed, 'en');
  const escape = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
  assert.equal(html, `<div class="app-gaps"><details class="app-gaps-more"><summary>Not checked in this brief (${mixed.length})</summary><ul>${mixed.map(text => `<li>${escape(text)}</li>`).join('')}</ul></details></div>`);
  assert.equal(lines.length, mixed.length);
  const {BriefGaps, language, render, h} = await load();
  language.value = 'en';
  assert.equal(render(h(BriefGaps, {brief: {gaps: [], missing: []}})), '');
});
