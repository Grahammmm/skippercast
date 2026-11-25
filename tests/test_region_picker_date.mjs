import assert from 'node:assert/strict';
import test from 'node:test';
import {fileURLToPath} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';

const {outputFiles: [bundle]} = await build({
  stdin: {resolveDir: fileURLToPath(new URL('../', import.meta.url)), contents: `
    export {coverageDay, RegionPicker} from './web/landing/RegionPicker.tsx';
    export {language, prepareCatalogue} from './web/i18n.ts';
    export {snapshot} from './web/region-coverage.ts';
    export {h} from 'preact';
    export {render} from 'preact-render-to-string';
  `},
  bundle: true, write: false, format: 'esm', platform: 'node',
  jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins,
});
const {coverageDay, RegionPicker, language, prepareCatalogue, snapshot, h, render} =
  await import(`data:text/javascript;base64,${Buffer.from(bundle.contents).toString('base64')}`);

const afterUtcMidnight = '2026-11-14T05:00:00Z';

test('C1: use the page locale, not ISO or one shared display format', () => {
  const checkedAt = '2026-11-13T22:32:27Z';
  assert.equal(coverageDay(checkedAt, 'en'), 'Nov 13, 2026');
  assert.equal(coverageDay(checkedAt, 'es'), '13 nov 2026');
});

test('C1: keep the ten-character prefix when parsing fails, rather than throwing', () => {
  assert.equal(coverageDay('invalid timestamp', 'en'), 'invalid ti');
});

test('C3: a UTC Saturday check still belongs to Friday in Pacific time', () => {
  assert.equal(coverageDay(afterUtcMidnight, 'en'), 'Nov 13, 2026');
});

test('C2: C3 — the Spanish coverage line interpolates the Pacific date, not the UTC slice', async () => {
  await prepareCatalogue('es');
  language.value = 'es';
  snapshot.checked_at = afterUtcMidnight;
  const html = render(h(RegionPicker, {
    href: 'https://skippercast.com/?lang=es', now: Date.parse(afterUtcMidnight),
  }));
  assert.equal(html.match(/<p id="[^"]+-snapshot">([^<]*)<\/p>/)?.[1],
    'Cobertura comprobada el 13 nov 2026. Es una instantánea fechada, no el estado actual de las fuentes.');
});
