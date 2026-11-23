// SCB2222-07 forecast_point_names_in_renderers (Conditions caption). Contract: the Conditions caption names the forecast point from the
// loaded region file, in English and Spanish, and reads the id only when that file names no such point. Believable bug: the caption
// prints forecast.point.id ('central'), or another region's name for the same id.
import './helpers/spanish-ready.mjs';
import assert from 'node:assert/strict';
import test, {after} from 'node:test';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {preparedRendererPlugins} from './helpers/esbuild-url.mjs';

const root = fileURLToPath(new URL('..', import.meta.url));
const dir = await mkdtemp(join(tmpdir(), 'view-conditions-'));
after(() => rm(dir, {recursive: true, force: true}));
const outfile = join(dir, 'views.mjs');
await build({
  stdin: {resolveDir: root, loader: 'ts', contents: `
    export {Conditions} from './web/app/views/Conditions.tsx';
    export {regionInfo} from './web/app/App.tsx';
    export {regionalForecast} from './web/brief/Brief.tsx';
    export {language} from './web/i18n.ts';
    export {configureStore, region} from './web/state.ts';
    export {render} from 'preact-render-to-string';
    export {h} from 'preact';`},
  bundle: true, platform: 'node', format: 'esm', outfile, jsx: 'automatic', jsxImportSource: 'preact', plugins: preparedRendererPlugins,
});
const v = await import(pathToFileURL(outfile).href);

const now = new Date('2026-10-08T18:00:00Z');
const info = {id: 'morro-bay', name: 'Morro Bay & Avila', timezone: 'America/Los_Angeles', center: [35.34, -120.965]};
const forecast = {region: info.id, point: {id: 'central', lat: 35.36, lon: -120.94}, retrieved: now.getTime(), models: {}};
v.configureStore({v2: true, storage: null});
v.region.value = info.id;
v.regionalForecast.value = forecast;

const caption = (shown, lang) => {
  v.regionInfo.value = shown;
  v.language.value = lang;
  try { return v.render(v.h(v.Conditions, {now})).match(/<p class="app-conditions-caption">([^<]*)<\/p>/)[1]; } finally { v.language.value = 'en'; }
};
const EN = name => `models at forecast point ${name};`, ES = name => `modelos NOAA en el punto de pronóstico ${name};`;

test('SCB2222-07: the Conditions caption names the forecast point in English and Spanish, and reads the id when the region file does not name it', () => {
  const named = {...info, forecastPoints: {central: 'Estero Bay'}};
  assert.ok(caption(named, 'en').includes(EN('Estero Bay')), 'English: the published name');
  assert.ok(caption(named, 'es').includes(ES('Estero Bay')), 'Spanish: the name as published, in the Spanish sentence');
  for (const [why, shown] of [['the file names other points only', {...info, forecastPoints: {north: 'Point Estero'}}], ['the file names none', info],
    ['another region names the same id', {...info, id: 'cambria-san-simeon', forecastPoints: {central: 'Decoy'}}], ['no region file', null]]) {
    assert.ok(caption(shown, 'en').includes(EN('central')), `English id: ${why}`);
    assert.ok(caption(shown, 'es').includes(ES('central')), `Spanish id: ${why}`);
  }
  assert.equal(forecast.point.id, 'central', 'the id stays the point\'s identity in the data');
});
