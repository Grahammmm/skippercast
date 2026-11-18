// F12-11 (SCA-220): the mark card's route-distance line follows the selected language and number format, for the straight line
// and the by-water line, keeping the unit, the lower-bound sign and the run. Synthetic data, no network.
import './helpers/spanish-ready.mjs';   // the Spanish table, before the Spanish renders
import assert from 'node:assert/strict';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {preparedRendererPlugins} from './helpers/esbuild-url.mjs';
import {markDistanceLine} from '../web/mark-distance.ts';

const ROOT = new URL('..', import.meta.url).pathname;
let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'f12-11-')), 'card.mjs');
  await build({stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {MarkCard} from './web/app/MarkCard.tsx';
      export {language} from './web/i18n.ts';
      export {regionPorts, plannerPort} from './web/ports.ts';
      export {launchPoints} from './web/launches.ts';
      export {launchChoice} from './web/reach.ts';
      export {markData} from './web/map/marks.ts';
      export {cruiseSpeed} from './web/limits.ts';
      export {profile, region} from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
  bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: preparedRendererPlugins});
  mod = await import(pathToFileURL(out).href);
  return mod;
}

const ORIGIN = {latitude: 35.37, longitude: -120.86};
const north = nm => ({latitude: ORIGIN.latitude + nm / 60, longitude: ORIGIN.longitude});
const port = {id: 'a', name: 'First Port', region: 'morro-bay', status: 'active', forecast_point: 'x', forecast_name: 'x', match: [ORIGIN.latitude, ORIGIN.longitude]};
const mark = {id: 'spot:SC26-001', name: 'Synthetic mark', kind: 'Reef mark', reading: 'A reading', source: 'Source', basis: 'Basis', position: north(5.25)};
const LINE = /<p class="ui-mono" data-mark-distance="(water|straight)">([^<]*)<\/p>/;

async function card(lang) {
  const k = await load();
  k.profile.value = 'boat'; k.region.value = 'morro-bay'; k.cruiseSpeed.value = 20;
  k.regionPorts.value = {region: 'morro-bay', state: 'ready', list: [port]}; k.plannerPort.value = null;
  k.launchPoints.value = null; k.launchChoice.value = {}; k.markData.value = null;
  k.language.value = lang;
  try { return k.render(k.h(k.MarkCard, {mark})); } finally { k.language.value = 'en'; }
}

test('f12_11_open_card_switches_en_to_es: the straight line, its comma, unit, lower bound and run follow the language', async () => {
  const en = (await card('en')).match(LINE), es = (await card('es')).match(LINE);
  assert.ok(en && es);
  assert.equal(en[1], 'straight'); assert.equal(es[1], 'straight');
  assert.match(en[2], /^First Port · \d+\.\d nm straight line/);
  assert.match(es[2], /^First Port · \d+,\d nm en línea recta/, 'Spanish words and decimal comma');
  assert.ok(!/straight|by water|\d\.\d/.test(es[2]), 'no English words or decimal point left');
  assert.match(es[2], /≥/, 'the lower-bound sign is kept');
  assert.notEqual(en[2], es[2]);
});

test('f12_11_water_line_is_spanish: by-water words, comma and unit, with no lower bound', () => {
  const d = {nm: 3.25, basis: 'water'};
  const es = markDistanceLine('P', d, 20, 'es');
  assert.match(es, /^P · 3,3 nm por agua/);
  assert.ok(!es.includes('≥') && !es.includes('.'), es);
  assert.match(markDistanceLine('P', d, 20, 'en'), /^P · 3\.3 nm by water/);
});

test('f12_11_negative_control: the old hardcoded English line is distinguishable from the Spanish one', () => {
  const d = {nm: 5.25, basis: 'straight'};
  assert.doesNotMatch(markDistanceLine('P', d, 20, 'en'), /línea recta|5,3/);
  assert.match(markDistanceLine('P', d, 20, 'es'), /5,3 nm en línea recta/);
});
