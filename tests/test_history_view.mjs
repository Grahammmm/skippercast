// FE-35: the v2 History view (web/app/views/History.tsx, design § 10) over
// packages/coast historyView. The bundle is the committed synthetic
// tests/fixtures/coast/history.json with a second synthetic station added.
// 1. A region without a history binding shows the unavailable state.
// 2. The copy says "recorded history" (never "climatology" except to say it is not one).
// 3. Picker choices are store keys, so they round-trip through the address (Back and Forward: e2e/v2-history.spec.ts).
import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import fixture from './fixtures/coast/history.json' with {type: 'json'};

const ROOT = new URL('..', import.meta.url).pathname;
const dir = mkdtempSync(join(tmpdir(), 'history-view-'));
const out = join(dir, 'history.mjs');
await build({
  stdin: {resolveDir: ROOT, loader: 'ts', contents: `
    export * from './web/app/views/History.tsx';
    export {coastMarkup, isRenderableHistory} from './web/app/CoastMarkup.tsx';
    export {configureStore, readURL, syncFromURL, withParams, historyStation, historyMetric, historyRange} from './web/state.ts';
    export {render} from 'preact-render-to-string';
    export {h} from 'preact';`},
  bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
  plugins: rendererPlugins,
});
const v = await import(pathToFileURL(out).href);
rmSync(dir, {recursive: true, force: true});

const NOW = new Date('2026-10-07T15:10:00Z');
const bundle = structuredClone(fixture);
bundle.stations.push({...structuredClone(fixture.stations[0]), stationId: 'synthetic-two', name: 'Second synthetic buoy'});
const snapshot = data => ({product: 'history', data, generatedAt: data.generatedAt, receivedAt: NOW.toISOString(), savedAt: null, expiresAt: '2026-10-09T03:00:00.000Z'});
const text = html => html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');

test('acceptance 1: a region without a history binding shows the unavailable state', () => {
  // The shell's coast client starts unbound and nothing binds during a static render.
  const html = v.render(v.h(v.History, {now: NOW}));
  assert.match(html, /<section class="app-history" aria-labelledby="app-history-title"><h2 id="app-history-title">Recorded history<\/h2><p class="app-empty" role="status">Recorded history is unavailable for this region\./);
  assert.doesNotMatch(html, /app-coast-markup/, 'no renderer mounts without a snapshot');
  assert.deepEqual(v.historyState(null, 'unbound'), {kind: 'unbound'});
  assert.deepEqual(v.historyState(null, 'loading'), {kind: 'loading'});
  for (const status of ['error', 'invalid', 'expired']) assert.deepEqual(v.historyState(null, status), {kind: 'unavailable'}, status);
  // A snapshot for a county packages/coast does not know is not shown either.
  assert.equal(v.historyState(snapshot({...bundle, countyId: 'elsewhere'}), 'ready').kind, 'unavailable');
});

test('a bound snapshot renders historyView with its station, measurement and range pickers', () => {
  const state = v.historyState(snapshot(bundle), 'ready');
  assert.equal(state.kind, 'ready');
  assert.equal(state.county.id, 'slo');
  const markup = v.coastMarkup('historyView', [{county: state.county, now: NOW}, state.bundle, v.historySelection('synthetic-two', 'waveFt', '14')]);
  assert.match(markup, /<select id="history-station"><option value="synthetic-buoy" >Synthetic buoy · synthetic-buoy<\/option><option value="synthetic-two" selected>/);
  assert.match(markup, /<option value="waveFt" selected>Wave height<\/option>/);
  assert.match(markup, /data-history-days="14" class="active" aria-pressed="true"/);
});

test('acceptance 2: the copy says recorded history and never offers a climatology', () => {
  const state = v.historyState(snapshot(bundle), 'ready');
  const words = text(v.coastMarkup('historyView', [{county: state.county, now: NOW}, state.bundle, v.historySelection(null, null, null)])).toLowerCase();
  assert.match(words, /recorded ocean history/);
  assert.deepEqual(words.match(/[^.]*climatology[^.]*/g), [' they are not a standard 30-year climatology, a forecast, or a prediction of fishing success'], 'climatology appears only to say this is not one');
  for (const note of ['unbound', 'loading', 'unavailable']) {
    assert.doesNotMatch(v.render(v.h(v.History, {now: NOW})), /climatology/i, note);
  }
});

test('acceptance 3: picker choices are store keys that round-trip through the address', () => {
  v.configureStore({storage: null});
  let href = 'https://s.test/map?region=morro-bay&view=history';
  for (const choice of [{name: 'history-station', value: 'synthetic-two'}, {name: 'history-metric', value: 'windKnots'}, {name: 'history-days', value: '7'}]) {
    href = v.withParams(href, v.historyPatch(choice));
  }
  assert.equal(new URL(href).search, '?region=morro-bay&view=history&station=synthetic-two&metric=windKnots&range=7');
  v.syncFromURL(href);
  assert.deepEqual([v.historyStation.value, v.historyMetric.value, v.historyRange.value], ['synthetic-two', 'windKnots', '7']);
  assert.deepEqual(v.historySelection(v.historyStation.value, v.historyMetric.value, v.historyRange.value), {station: 'synthetic-two', metric: 'windKnots', days: 7});
  // Going back to the address without them restores the defaults.
  v.syncFromURL('https://s.test/map?region=morro-bay&view=history');
  assert.deepEqual(v.historySelection(v.historyStation.value, v.historyMetric.value, v.historyRange.value), {station: '', metric: 'waterTempF', days: 45});
  assert.equal(v.historyPatch({name: 'open', value: 'x'}), null, 'other renderer controls are not history choices');
});

test('unlisted picker values fall back, including prototype names', () => {
  assert.deepEqual(v.historySelection('x', 'toString', '30'), {station: 'x', metric: 'waterTempF', days: 45});
  assert.deepEqual(v.historySelection(null, 'constructor', 'abc'), {station: '', metric: 'waterTempF', days: 45});
});

test('a bundle whose unescaped numbers are not numbers never reaches the DOM', () => {
  const bad = structuredClone(bundle);
  bad.stations[0].baseline.years = ['<img src=x onerror=alert(1)>'];
  assert.equal(v.isRenderableHistory(bad), false);
  assert.equal(v.historyState(snapshot(bad), 'ready').kind, 'unavailable');
  assert.throws(() => v.coastMarkup('historyView', [{county: {id: 'slo', timezone: 'UTC'}, now: NOW}, bad, v.historySelection(null, null, null)]), TypeError);
  const counts = structuredClone(bundle);
  counts.stations[0].baseline.months = [{month: 10, metric: 'waterTempF', unit: '°F', count: 5, rawSampleCount: 5, expectedHours: '<b>', coverageFraction: 1, yearsWithData: [2025], p10: 1, median: 2, p90: 3, min: 1, max: 3, mean: 2}];
  assert.equal(v.isRenderableHistory(counts), false);
  assert.equal(v.isRenderableHistory(null), true, 'null renders the unavailable state');
});
