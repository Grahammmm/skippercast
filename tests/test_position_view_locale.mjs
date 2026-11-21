import assert from 'node:assert/strict';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';

const out = join(await mkdtemp(join(tmpdir(), 'position-locale-')), 'view.mjs');
await build({
  stdin: {resolveDir: fileURLToPath(new URL('..', import.meta.url)), loader: 'ts', contents: `
    export {PositionView, distanceText} from './web/app/PositionView.tsx';
    export {prepareCatalogue} from './web/i18n.ts';
    export {render} from 'preact-render-to-string';
    export {h} from 'preact';`},
  bundle: true, format: 'esm', platform: 'node', outfile: out, jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins,
});
const {PositionView, distanceText, prepareCatalogue, render, h} = await import(pathToFileURL(out).href);
await prepareCatalogue('es');

const evening = '2026-11-21T03:30:00Z';
function renderedCheck(lang, checkedAt) {
  const fix = {latitude: 35, longitude: -120, accuracyM: 85};
  const reading = {kind: 'checked', fix, where: 'outside', name: 'Synthetic reserve', distanceM: 2400,
    lowAccuracy: false, stale: false, missing: [], clock: 'ok', checkedAt};
  const state = {phase: 'done', result: {located: {ok: true, fix}, reading}};
  const html = render(h(PositionView, {state, pack: 'saved', onCheck() {}, lang}));
  return Array.from(html.matchAll(/<p class="pos-line(?: pos-small)?">([^<]*)<\/p>/g), match => match[1]);
}

// C1: Localizing the decimal must not introduce grouping, drop a trailing zero, or change English bytes.
test('C1: format both distance branches in Spanish and preserve English output', () => {
  assert.deepEqual([distanceText(85, 'es'), distanceText(2400, 'es'), distanceText(20000, 'es')],
    ['85 m (279 ft)', '1,3 nmi (2,4 km)', '10,8 nmi (20,0 km)']);
  assert.deepEqual([distanceText(85, 'en'), distanceText(2400, 'en'), distanceText(20000)],
    ['85 m (279 ft)', '1.3 nmi (2.4 km)', '10.8 nmi (20.0 km)']);
});

// C2: Slicing UTC gives the next day for this instant; interpreting a calendar-only value as an instant shifts it back.
test('C2: report the Pacific day of a timestamp but preserve a date-only calendar day', () => {
  assert.equal(renderedCheck('en', evening).at(-1), 'Boundaries last checked Nov 20, 2026');
  assert.equal(renderedCheck('en', '2026-11-21').at(-1), 'Boundaries last checked Nov 21, 2026');
  assert.equal(renderedCheck('es', '2026-11-21').at(-1), 'Límites revisados por última vez el 21 nov 2026');
});

// C2: Invalid or absent inputs must not throw or print the normalized date of an impossible day.
test('C2: localize the unknown-date fallback for invalid or missing values', () => {
  assert.equal(renderedCheck('en', 'not a date').at(-1), 'Boundaries last checked unknown date');
  assert.equal(renderedCheck('es', '2026-02-30').at(-1), 'Límites revisados por última vez el fecha desconocida');
  assert.equal(renderedCheck('es', null).at(-1), 'Límites revisados por última vez el fecha desconocida');
});

// C3: The Spanish page must pass its language to the formatters, not just translate the surrounding labels.
test('C3: render Spanish distance, accuracy, and evening check date together', () => {
  assert.deepEqual(renderedCheck('es', evening), [
    'Cierre más cercano: a 1,3 nmi (2,4 km)',
    'Precisión de la posición: ±85 m (279 ft)',
    'Límites revisados por última vez el 20 nov 2026',
  ]);
});
