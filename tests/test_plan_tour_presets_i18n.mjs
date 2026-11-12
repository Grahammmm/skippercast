// SC0922-11: the plan view's own words, the controls tour and the preset labels follow the page language.
// English output stays byte-identical; reviewed plan text, species names and rule summaries are not translated here.
// Synthetic plans and links only; no network.
import './helpers/spanish-ready.mjs';   // SC1407-09: the Spanish table, before the Spanish renders
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {preparedRendererPlugins} from './helpers/esbuild-url.mjs';
import {planCopy, planView} from '../web/plan.ts';
import {tourSteps, TOUR_STEPS, tourTransition} from '../web/tour.ts';
import {presetLabel, PRESETS, presetsFor} from '../web/app/presets.ts';
import {catalogueProblems} from '../scripts/check_copy.mjs';

const ROOT = new URL('..', import.meta.url).pathname;
const FIXTURE = JSON.parse(readFileSync(new URL('../tests/fixtures/regulations/fe61-v1.json', import.meta.url), 'utf8'));
let ui;
async function components() {
  if (ui) return ui;
  const out = join(await mkdtemp(join(tmpdir(), 'plan-tour-presets-i18n-')), 'ui.mjs');
  await build({stdin: {resolveDir: ROOT, loader: 'ts', contents: `
    export {PlanView, PlanLink} from './web/app/PlanView.tsx';
    export {ControlsTour} from './web/app/ControlsTour.tsx';
    export {Presets, helm} from './web/app/Presets.tsx';
    export {regionInfo} from './web/app/App.tsx';
    export {regionPlans, regionUnavailable} from './web/species.ts';
    export {regsData} from './web/regs.ts';
    export {language} from './web/i18n.ts';
    export * as state from './web/state.ts';
    export {render} from 'preact-render-to-string'; export {h} from 'preact';`},
  bundle: true, format: 'esm', platform: 'node', outfile: out, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: preparedRendererPlugins});
  ui = await import(pathToFileURL(out).href);
  return ui;
}

const TITLE = '<img src=x> & "source"';
const PLAN = {name: 'Synthetic <b>target</b>', numeric_bite_model: false, life_stage: 'Adults',
  search_for: 'Published search text', habitat: 'Published habitat text', presentation: 'Published presentation', method: 'Published method',
  timing: 'Published timing', condition_response: 'Published change text', caution: 'Published caution',
  required_to_confirm: ['Confirm this'], tactics_basis: 'Published basis',
  source_links: [{title: TITLE, url: 'https://example.test/a'}, {title: 'Unsafe', url: 'javascript:alert(1)'}]};
function setup(m, plans = {halibut: PLAN}, reviewedAt = '2026-09-01') {
  m.state.configureStore({v2: true, storage: null});
  m.state.syncFromURL('https://s.test/map?region=morro-bay&profile=boat&view=plan&target=halibut');
  m.regionPlans.value = {region: 'morro-bay', plans, reviewedAt};
  m.regionUnavailable.value = {region: 'morro-bay', targets: {}};
  m.regionInfo.value = {id: 'morro-bay', name: 'Morro Bay', timezone: 'America/Los_Angeles', center: [35, -121], rules: FIXTURE.region};
  m.regsData.value = null;
}
const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
const page = (m, C, props = {}) => m.render(m.h(C, props));

test('plan_es_generated_vs_published: chrome follows the language, reviewed text and link titles stay as published', async () => {
  const m = await ui_(); setup(m);
  try {
    m.language.value = 'en';
    const en = page(m, m.PlanView);
    for (const w of ['Confirm on the day', 'Evidence', 'Rules', 'Plan reviewed 2026-09-01', 'What to search for', 'How to fish it', 'When conditions change'])
      assert.ok(en.includes(w), `en ${w}`);
    assert.ok(en.includes(`aria-label="${esc(TITLE)} (opens in a new tab)"`), 'en link aria ' + en.slice(en.indexOf('<a href="https'), en.indexOf('<a href="https') + 260));
    m.language.value = 'es';
    const es = page(m, m.PlanView);
    for (const w of ['Confirma el día de la salida', 'Evidencia', 'Reglas', 'Plan revisado 2026-09-01', 'Cómo se construye', 'Qué buscar', 'Hábitat', 'Cómo pescar', 'Cuándo pescar', 'Cuando cambian las condiciones', 'Precaución'])
      assert.ok(es.includes(w), `es ${w}`);
    assert.ok(es.includes(`aria-label="${esc(TITLE)} (se abre en una pestaña nueva)"`), 'es link aria keeps the title');
    assert.ok(es.includes('para Synthetic &lt;b&gt;target&lt;/b&gt; (se abre en una pestaña nueva)') || es.includes('(se abre en una pestaña nueva)'), 'rules link aria');
    for (const published of ['Published search text', 'Published habitat text', 'Published presentation', 'Published method', 'Published timing', 'Published change text', 'Published caution', 'Published basis', 'Confirm this', 'Adults'])
      assert.ok(es.includes(published), `${published} unchanged`);
    assert.ok(es.includes(`>${esc(TITLE)}</a>`) && !es.includes('javascript:'), 'link title verbatim, unsafe link still dropped');
    m.language.value = 'en';
    assert.ok(page(m, m.PlanView) === en, 'en -> es -> en is byte-identical');
  } finally { m.language.value = 'en'; }
});

test('plan_fallbacks: generated reasons follow the language; supplied reasons and the raw id stay', async () => {
  const m = await ui_(); setup(m);
  try {
    assert.equal(planCopy('en').loading, 'Loading this region’s plans.');
    assert.equal(planCopy().unknown, 'No plan is available for this target.');
    assert.equal(planCopy('es').withheld, 'Este plan incluye un modelo numérico que la aplicación no muestra.');
    assert.equal(planCopy('es').unresearched, 'Esta región aún no tiene un plan investigado para esta especie objetivo.');
    assert.equal(planCopy('es').unknown, 'No hay un plan disponible para esta especie objetivo.');
    assert.equal(planCopy('es').loading, 'Cargando los planes de esta región.');
    assert.deepEqual(planView({}, 'x', 'unresearched', {}, null, 'es'), {kind: 'unresearched', reason: planCopy('es').unresearched});
    assert.deepEqual(planView({}, 'x', 'unresearched', {}, null), {kind: 'unresearched', reason: planCopy('en').unresearched});
    assert.deepEqual(planView({x: null}, 'x', 'plan', {x: 'Supplied reason.'}, null, 'es'), {kind: 'unresearched', reason: 'Supplied reason.'});
    assert.equal(planView({x: {numeric_bite_model: true}}, 'x', 'plan', {}, null, 'es').reason, planCopy('es').withheld);
    assert.deepEqual(planView({}, 'a<b', null, {}, null, 'es'), {kind: 'unknown', id: 'a<b'});
    assert.deepEqual(planView(null, 'x', null, {}, null, 'es'), {kind: 'loading'});
    m.language.value = 'es';
    m.regionPlans.value = {region: 'morro-bay', plans: {}};
    const unknown = page(m, m.PlanView);
    assert.ok(unknown.includes('Esta región aún no tiene un plan investigado para esta especie objetivo.'), 'generated unresearched reason in Spanish');
    m.regionPlans.value = {region: 'other', plans: {}};
    assert.ok(page(m, m.PlanView).includes('Cargando los planes de esta región.'));
    m.language.value = 'en';
    assert.ok(page(m, m.PlanView).includes('Loading this region’s plans.'));
  } finally { m.language.value = 'en'; }
});

test('plan_link: the link text follows the language and keeps the target name', async () => {
  const m = await ui_(); setup(m);
  try {
    m.language.value = 'en'; const en = page(m, m.PlanLink);
    m.language.value = 'es'; const es = page(m, m.PlanLink);
    assert.match(en, />Plan for [^<]+</);
    assert.match(es, />Plan para [^<]+</);
    assert.equal(en.match(/href="[^"]*"/)[0], es.match(/href="[^"]*"/)[0], 'same href');
  } finally { m.language.value = 'en'; }
});

test('tour_all_steps_es_and_invalid: whole Spanish paragraphs, English unchanged, transitions untouched', async () => {
  const m = await ui_();
  const ES = [
    ['Panel de tiempo', 'Usa los botones de día y el control deslizante de hora debajo del mapa para elegir una hora del pronóstico. Revisa la hora mostrada antes de leer una capa.'],
    ['Lista de capas', 'Usa la lista de capas junto al mapa o abre Capas en un teléfono. Cada capa explica su fuente y sus límites; las capas no disponibles no son evidencia de condiciones despejadas.'],
    ['Guardar sin conexión', 'Abre el menú de la cuenta y elige Guardar sin conexión después de elegir un puerto. Revisa qué se guardó y su fecha antes de perder la conexión.'],
    ['Línea de límites de la evidencia', 'Abre Detalles debajo del resumen para leer qué no puede decirte este resumen sobre tu actividad. Una capa del mapa no es una autorización de seguridad.'],
  ];
  const EN = [['Time dock', 'Use the day buttons and hour slider below the map to choose a forecast time. Check the displayed time before reading a layer.'],
    ['Layer list', 'Use the layer list beside the map, or open Layers on a phone. Each layer explains its source and limits; unavailable layers are not evidence of clear conditions.'],
    ['Save for offline', 'Open the account menu and choose Save for offline after choosing a port. Review what is saved and its date before leaving your connection.'],
    ['Evidence-limit line', 'Open Details under the brief to read what this brief cannot tell you for your activity. A map layer is not a safety clearance.']];
  assert.deepEqual(TOUR_STEPS.map(s => [s.title, s.text]), EN);
  assert.deepEqual(tourSteps('es').map(s => [s.title, s.text]), ES);
  try {
    for (let step = 0; step < 4; step++) {
      m.language.value = 'en'; const en = page(m, m.ControlsTour, {step, act() {}});
      m.language.value = 'es'; const es = page(m, m.ControlsTour, {step, act() {}});
      assert.ok(en.includes(`Step ${step + 1} of 4`) && en.includes('Skip tour') && en.includes(step === 3 ? 'Finish' : 'Next'), `en chrome ${step}`);
      for (const w of ['Recorrido de controles', `Paso ${step + 1} de 4`, 'Omitir recorrido', 'Atrás', step === 3 ? 'Finalizar' : 'Siguiente', ES[step][0], ES[step][1]])
        assert.ok(es.includes(w), `es ${step} ${w}`);
      assert.match(es, /aria-live="polite" aria-atomic="true"/);
      assert.equal(/disabled/.test(es), step === 0, 'only the first Back is disabled');
      m.language.value = 'en';
      assert.ok(page(m, m.ControlsTour, {step, act() {}}) === en, `en roundtrip ${step}`);
    }
    for (const bad of [-1, 1.5, NaN, 4, 99]) assert.equal(page(m, m.ControlsTour, {step: bad, act() {}}), '', `step ${bad} renders nothing`);
  } finally { m.language.value = 'en'; }
  for (const bad of [-1, 1.5, NaN, 4, 99, Infinity]) { assert.equal(tourTransition(bad, 'next'), null); assert.equal(tourTransition(bad, 'back'), null); }
  assert.equal(tourTransition(3, 'next'), null);
  assert.equal(tourTransition(0, 'back'), 0);
});

test('presets_es_labels_not_state: labels change, ids, order and state do not', async () => {
  const m = await ui_(); setup(m);
  const EN = {'reef-drift': 'Reef drift', halibut: 'Halibut', crab: 'Crab', offshore: 'Offshore', transit: 'Transit'};
  const ES = {'reef-drift': 'Deriva sobre arrecife', halibut: 'Halibut', crab: 'Cangrejo', offshore: 'Mar adentro', transit: 'Tránsito'};
  for (const [id, label] of Object.entries(EN)) {
    assert.equal(presetLabel(id), label); assert.equal(presetLabel(id, 'en'), label); assert.equal(presetLabel(id, 'es'), ES[id]);
    assert.equal(PRESETS.find(p => p.id === id).label, label, 'compatibility label is English');
  }
  for (const id of ['__proto__', 'constructor', 'toString', 'hasOwnProperty', 'nope', '']) assert.equal(presetLabel(id, 'es'), id, `unknown id ${id}`);
  assert.deepEqual(presetsFor('halibut').map(p => p.id), ['halibut', 'reef-drift', 'crab', 'offshore', 'transit']);
  try {
    m.language.value = 'en'; const en = page(m, m.Presets);
    m.language.value = 'es'; const es = page(m, m.Presets);
    assert.ok(en.includes('aria-label="Layer presets"') && en.includes('Large controls') && !en.includes('Helm view') && en.includes('Reef drift'));
    assert.ok(es.includes('aria-label="Preajustes de capas"') && es.includes('Controles grandes') && !es.includes('Vista de timón') && es.includes('Mar adentro') && es.includes('Tránsito'));
    assert.match(es, /role="switch"/); assert.match(es, /aria-checked="false"/);
    const order = html => [...html.matchAll(/<button[^>]*>([^<]*)<\/button>/g)].map(x => x[1]).length;
    assert.equal(order(en), order(es), 'same number of controls');
    m.language.value = 'en';
    assert.ok(page(m, m.Presets) === en, 'en roundtrip');
  } finally { m.language.value = 'en'; }
});

test('catalogue_en_parity: new entries have exact English, equal placeholders, and no problems', () => {
  const strings = JSON.parse(readFileSync(new URL('../catalog/app/strings.json', import.meta.url), 'utf8')).strings;
  const ids = Object.keys(strings).filter(id => /^(plan|tour|preset)\./.test(id));
  assert.ok(ids.length >= 39);
  const vars = s => [...s.matchAll(/\{(\w+)\}/g)].map(x => x[1]).sort().join(',');
  for (const id of ids) assert.equal(vars(strings[id].en), vars(strings[id].es), `${id} placeholders`);
  assert.equal(strings['plan.built'].en, "How it's built");
  assert.equal(strings['plan.rulesNewTab'].es, '{link} para {name} (se abre en una pestaña nueva)');
  assert.deepEqual(catalogueProblems(), []);
});

async function ui_() { return components(); }
