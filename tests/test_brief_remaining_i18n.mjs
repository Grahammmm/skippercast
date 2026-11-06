// SC1607-09: the plan-only search plan's labels and no-plan sentence, the saved-boat caveat on the brief and the landing, and the two
// selected-tide save refusals read the chosen language where they are shown; every raw English producer keeps its English input.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {missingSearchPlanText, searchPlanLabel, tidePackMessage} from '../web/brief/remaining-copy.ts';
import {noPlanText, planFor} from '../web/search-plan.ts';
import {BOAT_MODEL_NOTE, boatRangeNote} from '../web/boat-range.ts';
import {saveTidePack} from '../web/tide-stations.ts';
import {t} from '../web/i18n.ts';

const ROOT = new URL('..', import.meta.url).pathname;
const NONE = {source: null, label: '', basis: '', picks: [], empty: 'No surveyed reef marks within 300 ft for this target.'};
const FULL = {name: 'Chinook salmon', kind: 'pelagic', numeric_bite_model: false, life_stage: 'Adults.', search_for: 'Bait.', habitat: 'Edges.', presentation: 'Troll.', timing: 'Seasonal.',
  condition_response: 'Move.', caution: 'Fog.', required_to_confirm: ['Legal access', 'Conditions'], tactics_basis: 'Basis line.'};
const LABELS = {life_stage: ['Life stage', 'Etapa de vida'], search_for: ['What to search for', 'Qué buscar'], habitat: ['Habitat', 'Hábitat'], presentation: ['How to fish it', 'Cómo pescarlo'],
  method: ['How to fish it', 'Cómo pescarlo'], timing: ['Timing', 'Cuándo pescar'], condition_response: ['When conditions change', 'Cuando cambian las condiciones'], caution: ['Caution', 'Precaución'],
  required_to_confirm: ['Confirm on the day', 'Confirmar ese día']};

let view;
async function loadView() {
  if (view) return view;
  const out = join(await mkdtemp(join(tmpdir(), 'remaining-copy-')), 'view.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {WhereToLook} from './web/brief/WhereToLook.tsx';
      export {regionPlans} from './web/species.ts';
      export {regionInfo} from './web/app/region-info.ts';
      export {region, species, profile} from './web/state.ts';
      export {language} from './web/i18n.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: [{name: 'renderers', setup: b => b.onResolve({filter: /^\.\/(?:terrain|maplibre)\.js$/}, args => ({path: args.path, external: true}))}],
  });
  view = await import(pathToFileURL(out).href);
  return view;
}
async function where(lang, {plans = {chinook: FULL}, name = 'Test Bay', target = 'chinook'} = {}) {
  const m = await loadView();
  m.profile.value = 'boat'; m.region.value = 'test-bay'; m.species.value = target; m.language.value = lang;
  m.regionInfo.value = name === undefined ? null : {id: 'test-bay', name, center: [35, -121], timezone: 'America/Los_Angeles'};
  m.regionPlans.value = {region: 'test-bay', plans, reviewedAt: null};
  return m.render(m.h(m.WhereToLook, {ranking: NONE}));
}

test('search plan labels: every field in es, reviewed words and English unchanged', async () => {
  for (const [field, [en, es]] of Object.entries(LABELS)) {
    assert.equal(searchPlanLabel({field, label: en}, 'en'), en);
    assert.equal(searchPlanLabel({field, label: en}, 'es'), es, field);
  }
  assert.equal(searchPlanLabel({field: 'custom', label: 'Custom label'}, 'es'), 'Custom label');
  const en = await where('en'), es = await where('es');
  assert.match(en, /Life stage: Adults\./);
  assert.match(es, /Etapa de vida: Adults\./);
  assert.match(es, /Cómo pescarlo: Troll\./);
  assert.equal((es.match(/Confirmar ese día: /g) ?? []).length, 2);
  assert.match(es, /Legal access/);
  const loaded = {region: 'test-bay', plans: {chinook: FULL}};
  for (const item of planFor('chinook', loaded).items) assert.ok(item.label === LABELS[item.field][0], 'search-plan.ts keeps its English labels');
  assert.equal(await where('en'), en, 'English restored byte for byte');
});

test('no-plan sentence: named and generic region, English input untouched', async () => {
  assert.equal(missingSearchPlanText('Test Bay', 'en'), noPlanText('Test Bay'));
  assert.equal(missingSearchPlanText(null, 'en'), noPlanText(null));
  assert.equal(missingSearchPlanText('', 'en'), noPlanText(''));
  assert.equal(missingSearchPlanText('Bahía Test', 'es'), 'Aún no hay un plan de búsqueda para esta especie en Bahía Test.');
  assert.equal(missingSearchPlanText(undefined, 'es'), 'Aún no hay un plan de búsqueda para esta especie en esta región.');
  const modelled = {modelled: {...FULL, numeric_bite_model: true}};
  assert.match(await where('es', {plans: modelled, target: 'modelled'}), /Aún no hay un plan de búsqueda para esta especie en Test Bay\.<\/p>/);
  assert.match(await where('en', {plans: modelled, target: 'modelled', name: null}), /No search plan for this species in this region yet\.<\/p>/);
});

test('boat caveat: es keeps the heuristic, 23 ft and not-sea-keeping clauses (brief and landing verdict both read this entry)', () => {
  assert.equal(t('brief.boat.note', 'en'), BOAT_MODEL_NOTE);
  assert.equal(boatRangeNote(30), BOAT_MODEL_NOTE);
  assert.equal(boatRangeNote(23), null);
  const es = t('brief.boat.note', 'es');
  assert.match(es, /modelo empírico para casco de planeo/);
  assert.match(es, /23 ft/);
  assert.match(es, /no un cálculo de navegabilidad/);
});

test('tide save refusals: only the two complete messages change, at render', async () => {
  const unavailable = t('tidePack.unavailable', 'en'), notLive = t('tidePack.notLive', 'en');
  assert.equal(unavailable, 'Chosen tide predictions are unavailable. Saved regions are unchanged.');
  assert.equal(notLive, 'Chosen tide station could not be saved from a live response. Saved regions are unchanged.');
  assert.equal(tidePackMessage(unavailable, 'es'), 'Las predicciones de marea elegidas no están disponibles. Las regiones guardadas no han cambiado.');
  assert.equal(tidePackMessage(notLive, 'es'), 'No se pudo guardar la estación de marea elegida a partir de una respuesta en vivo. Las regiones guardadas no han cambiado.');
  for (const m of [unavailable, notLive, 'QuotaExceededError', `${unavailable} Extra.`, '']) assert.equal(tidePackMessage(m, 'en'), m);
  for (const m of ['QuotaExceededError', `${unavailable} Extra.`, 'Saved regions are unchanged.', '']) assert.equal(tidePackMessage(m, 'es'), m);
  // The producers keep throwing English and write nothing on a refusal.
  const puts = [], put = async key => { puts.push(key); };
  const reply = (status, body, headers = {}) => async () => new Response(body, {status, headers});
  await assert.rejects(saveTidePack(['https://x.test/a'], put, new AbortController().signal, reply(500, '{}')), {message: notLive});
  await assert.rejects(saveTidePack(['https://x.test/a'], put, new AbortController().signal, reply(200, '{}', {'X-SC-Offline': '2026-01-01T00:00:00Z'})), {message: notLive});
  await assert.rejects(saveTidePack(['https://x.test/a?interval=hilo'], put, new AbortController().signal, reply(200, '{"error":"no data"}')), {message: unavailable});
  assert.deepEqual(puts, []);
});
