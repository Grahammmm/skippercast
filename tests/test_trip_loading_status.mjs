// RF1935-1: the trip dialog is always mounted, so its "Loading the trip planner" status and Retry button must exist only while the
// dialog is open. The page is the real web/app/Trip.tsx (real catalogue, real Preact hooks, server render); only the planner store
// (web/trip.ts), buttons and neighbours are a test-owned virtual boundary below, with a loader the test settles by hand.
// This is a render-state test, not a browser or screen-reader check (e2e/v2-trip.spec.ts covers the browser).
import './helpers/spanish-ready.mjs';   // the Spanish table, before the Spanish renders
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp} from 'node:fs/promises';
import {resolve} from 'node:path';
import {tmpdir} from 'node:os';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {preparedCatalogue} from './helpers/esbuild-url.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const BOUNDARY = 'trip-loading-boundary';
const boundarySource = `
import {h} from 'preact';
export const region = {value: 'fixture-harbor'}, regionInfo = {value: {name: 'Fixture Harbor'}}, zone = () => 'UTC';
export const oceanLines = () => null, forecastEndLine = () => '';
export const tripOpen = {value: false}, tripError = {value: ''}, plannerView = {value: null}, tripReady = {value: false}, offlineOpen = {value: false};
export const probe = {loads: 0, closes: 0, actions: new Map()};
export function Button({children, ...props}) {
  if (props.onClick) probe.actions.set(Array.isArray(children) ? children.join('') : children, props.onClick);
  return h('button', {type: 'button'}, children);
}
export const IconButton = () => null, PortDialog = ({children}) => h('div', {}, children), PositionCheck = () => null;
export const closeTrip = () => { probe.closes++; };
export const loadPlanner = () => { probe.loads++; return probe.loader(); };
export const listPacks = async () => [], canSaveCoastal = async () => false, readCoastal = async () => null, deleteCoastal = async () => {}, saveCoastal = async () => {}, savePack = async () => ({});
export const KEEP_WORDS = {agreed: '', already: '', refused: '', unavailable: ''}, storageLine = async () => null, estimateWords = () => '', savePackKept = async save => ({meta: await save(), keep: 'unavailable'});
`;

async function load() {
  const dir = await mkdtemp(resolve(tmpdir(), 'trip-loading-'));
  const trip = resolve(root, 'web/app/Trip.tsx');
  await build({
    stdin: {resolveDir: root, loader: 'js', contents: `export {Trip} from './web/app/Trip.tsx'; export {language, t} from './web/i18n.ts'; export {h} from 'preact'; export {render} from 'preact-render-to-string'; export * from '${BOUNDARY}';`},
    outfile: resolve(dir, 'trip.mjs'), bundle: true, format: 'esm', platform: 'node', jsx: 'automatic', jsxImportSource: 'preact', logLevel: 'silent',
    plugins: [preparedCatalogue, {name: 'trip-loading-boundary', setup(b) {
      const stubbed = ['../ui/Button.tsx', '../landing/PortInput.tsx', '../state.ts', '../trip.ts', '../trip-ocean-lines.ts', '../trip-forecast-end.ts', './App.tsx', './PositionCheck.tsx'];
      b.onResolve({filter: /.*/}, args => {
        if (args.path === BOUNDARY || (args.importer === trip && stubbed.includes(args.path))) return {path: BOUNDARY, namespace: BOUNDARY};
      });
      b.onLoad({filter: /.*/, namespace: BOUNDARY}, () => ({contents: boundarySource, loader: 'js', resolveDir: root}));
    }}],
  });
  return import(pathToFileURL(resolve(dir, 'trip.mjs')).href);
}

const m = await load();
const VIEW_MARK = 'data-planner-view-sentinel';
const view = ({open}) => m.h('div', {[VIEW_MARK]: open ? 'open' : 'closed'}, 'planner view');
const render = () => { m.probe.actions.clear(); return m.render(m.h(m.Trip)); };
const statuses = html => [...html.matchAll(/<p role="status">([^<]*)<\/p>/g)].map(x => x[1]);
const retryShown = (html, lang) => html.includes(`>${m.t('trip.retry', lang)}<`);
const failure = detail => m.t('trip.loadFailed', 'en', {detail});

function setState({open = false, ready = false, error = '', withView = false} = {}) {
  m.tripOpen.value = open; m.tripReady.value = ready; m.tripError.value = error;
  m.plannerView.value = withView ? {View: view, model: {}} : null;
  m.probe.loads = 0; m.probe.closes = 0;
  m.probe.loader = () => new Promise(() => {});
}

for (const lang of ['en', 'es']) {
  const loading = () => m.t('trip.loading', lang);
  const failed = detail => lang === 'es' ? m.t('trip.loadFailed', 'es', {detail}) : failure(detail);

  test(`idle_closed_has_no_phantom_load_${lang}: a never-opened planner announces nothing and shows no Retry`, () => {
    m.language.value = lang;
    setState();
    const html = render();
    assert.deepEqual(statuses(html), [], 'no status in the closed, never-used dialog');
    assert.ok(!html.includes(loading()), 'the loading words are not in the page');
    assert.ok(!retryShown(html, lang));
    assert.equal(m.probe.loads, 0, 'rendering never starts the planner');
  });

  test(`pending_open_survives_slow_load_${lang}: an open dialog whose planner is pending keeps its one loading status`, () => {
    m.language.value = lang;
    setState({open: true});
    for (let i = 0; i < 3; i++) assert.deepEqual(statuses(render()), [loading()], 'still loading on every render, nothing clears it but readiness');
    assert.ok(!retryShown(render(), lang), 'no Retry while merely pending');
  });

  test(`ready_clears_status_keeps_view_${lang}: ready removes loading, and the mounted view survives close and reopen`, () => {
    m.language.value = lang;
    setState({open: true, withView: true});
    assert.deepEqual(statuses(render()), [loading()]);
    m.tripReady.value = true;
    let html = render();
    assert.deepEqual(statuses(html), []);
    assert.ok(html.includes(`${VIEW_MARK}="open"`), 'the view is drawn open');
    m.tripOpen.value = false;
    html = render();
    assert.deepEqual(statuses(html), [], 'no loading flash on close');
    assert.ok(html.includes(`${VIEW_MARK}="closed"`), 'the view stays mounted while closed');
    m.tripOpen.value = true;
    html = render();
    assert.deepEqual(statuses(html), [], 'no loading flash on reopen');
    assert.ok(html.includes(`${VIEW_MARK}="open"`));
    assert.equal(m.probe.loads, 0, 'rendering starts no second initialisation');
  });

  test(`close_during_pending_then_settle_${lang}: closing removes loading at once; reopening a still-pending planner brings it back`, () => {
    m.language.value = lang;
    setState({open: true});
    assert.deepEqual(statuses(render()), [loading()]);
    m.tripOpen.value = false;
    assert.deepEqual(statuses(render()), [], 'closed while pending: nothing announced');
    m.tripOpen.value = true;
    assert.deepEqual(statuses(render()), [loading()], 'reopened before it settled: still pending');
    m.tripOpen.value = false;
    m.tripReady.value = true;   // settles while closed
    m.tripOpen.value = true;
    assert.deepEqual(statuses(render()), [], 'reopened after it settled: no stale status');
    assert.equal(m.probe.loads, 0, 'no duplicate start from rendering');
  });

  test(`failure_retry_is_not_loading_${lang}: an open failure shows its words and Retry; Retry calls the loader once and restores loading`, async () => {
    m.language.value = lang;
    setState({open: true, error: failure('offline')});
    let html = render();
    assert.deepEqual(statuses(html), [failed('offline')], 'the failure, not the generic loading line');
    assert.ok(retryShown(html, lang));
    const retry = m.probe.actions.get(m.t('trip.retry', lang));
    assert.equal(typeof retry, 'function', 'Retry is wired');
    let settle;
    m.probe.loader = () => { m.tripError.value = ''; return new Promise(resolve => { settle = resolve; }); };
    retry();
    assert.equal(m.probe.loads, 1, 'one loader call');
    html = render();
    assert.deepEqual(statuses(html), [loading()], 'error cleared and pending again: loading returns');
    assert.ok(!retryShown(html, lang));
    m.tripReady.value = true; settle(null);
    assert.deepEqual(statuses(render()), [], 'success removes it');
    // A repeated failure stays actionable.
    setState({open: true, error: failure('again')});
    html = render();
    assert.deepEqual(statuses(html), [failed('again')]);
    assert.ok(retryShown(html, lang));
  });

  test(`failure_hidden_when_closed_${lang}: closing a failed planner removes the dormant failure and Retry; reopening shows them again`, () => {
    m.language.value = lang;
    setState({open: true, error: failure('offline')});
    assert.equal(statuses(render()).length, 1);
    m.tripOpen.value = false;
    const closed = render();
    assert.deepEqual(statuses(closed), []);
    assert.ok(!retryShown(closed, lang));
    m.tripOpen.value = true;
    const reopened = render();
    assert.deepEqual(statuses(reopened), [failed('offline')], 'the failure is still honest when reopened');
    assert.ok(retryShown(reopened, lang));
  });
}

test('language_switch_changes_words_not_work: en to es to en changes the status words only', () => {
  setState({open: true});
  for (const [lang, words] of [['en', 'Loading the trip planner…'], ['es', 'Cargando el planificador de viajes…'], ['en', 'Loading the trip planner…']]) {
    m.language.value = lang;
    assert.deepEqual(statuses(render()), [words]);
  }
  setState({open: true, error: failure('offline')});
  m.language.value = 'es';
  assert.deepEqual(statuses(render()), [m.t('trip.loadFailed', 'es', {detail: 'offline'})]);
  m.language.value = 'en';
  assert.deepEqual(statuses(render()), [failure('offline')]);
  assert.equal(m.probe.loads, 0, 'a language change starts no work');
  assert.equal(m.probe.closes, 0);
  m.language.value = 'en';
});
