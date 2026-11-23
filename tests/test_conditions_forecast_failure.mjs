// SCB2222-09: the Conditions view says why its forecast rows are missing. The real loader (web/conditions.ts), the real request, retry and
// generation code (web/brief/Brief.tsx) run over scripted fetches and the real Conditions view is rendered to a string. Contract: a settled
// failure of the selected region's own forecast request (an unmarked 503, a timeout) shows the shared ForecastFailure reason and Try again;
// loading, success (even with no model rows), absent and another region's outcome show none; the nearshore and tide rows and the view's
// controls stay mounted either way. Believable bugs: reading `regionalForecast === null` as a failure (loading and absent show an error),
// ignoring the region/point key (an old region's failure shows), or the panel replacing the local series.
import assert from 'node:assert/strict';
import test, {after, mock} from 'node:test';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {preparedRendererPlugins} from './helpers/esbuild-url.mjs';
import montereyDaily from './fixtures/brief/monterey-daily.json' with {type: 'json'};

const root = fileURLToPath(new URL('..', import.meta.url));
const dir = await mkdtemp(join(tmpdir(), 'conditions-forecast-failure-'));
after(() => rm(dir, {recursive: true, force: true}));
const outfile = join(dir, 'views.mjs');
await build({
  stdin: {resolveDir: root, loader: 'ts', contents: `
    export {Conditions} from './web/app/views/Conditions.tsx';
    export {regionInfo} from './web/app/App.tsx';
    export * from './web/brief/Brief.tsx';
    export {language} from './web/i18n.ts';
    export {configureStore, region, hour, day} from './web/state.ts';
    export {fixtures} from 'conditions-fixtures';
    export {render} from 'preact-render-to-string';
    export {h, options} from 'preact';`},
  bundle: true, platform: 'node', format: 'esm', outfile, jsx: 'automatic', jsxImportSource: 'preact', logLevel: 'silent',
  plugins: [...preparedRendererPlugins, {name: 'conditions-fixtures', setup(b) {
    // Only the view's own local coast report is a fixture (the nearshore and tide series); everything else is the real code.
    b.onResolve({filter: /^(conditions-fixtures|\.\.\/\.\.\/coast-data\.ts)$/}, args => {
      if (args.path === 'conditions-fixtures') return {path: 'inputs', namespace: 'fixtures'};
      if (args.importer.endsWith('/views/Conditions.tsx')) return {path: args.path, namespace: 'fixtures'};
    });
    b.onLoad({filter: /.*/, namespace: 'fixtures'}, ({path}) => ({resolveDir: root, contents: {
      inputs: `export const fixtures = {coastReport: {value: null}, coastBinding: {value: null}};`,
      '../../coast-data.ts': `import {fixtures} from 'conditions-fixtures';
        export const {coastReport, coastBinding} = fixtures;
        export const coastData = {};`,
    }[path]}));
  }}],
});

const PAGE = 'https://skippercast.test/map';
const at = '2026-10-08T18:00:00.000Z', later = '2026-10-08T19:00:00.000Z', now = new Date(at);
const INFO = {id: montereyDaily.region_id, name: 'Monterey', timezone: 'America/Los_Angeles', center: [36.62, -121.9]};
const OTHER = {id: 'morro-bay', name: 'Morro Bay', timezone: 'America/Los_Angeles', center: [35.37, -120.86]};
const predictions = [{time: '2026-10-08T20:00:00Z', type: 'H', height_ft: 3.3}, {time: '2026-10-09T03:00:00Z', type: 'L', height_ft: -0.4}];
const coastReport = {sources: [], tides: [{at, heightFt: 3.3}, {at: later, heightFt: -0.4}], nearshore: [{
  name: 'Fixture', areaId: 'fixture', availability: 'available', freshness: 'current', issuedAt: at, fetchedAt: at, hours: [{at, waveFt: 2.5}],
}]};

/** A synthetic /api/forecast answer for `region` (values invented), hourly for eight days from before `at`. */
function forecastFeed({region = INFO.id, models = true} = {}) {
  const start = Date.parse('2026-10-08T07:00:00Z') / 1000, time = Array.from({length: 8 * 24}, (_, i) => start + i * 3600);
  const series = values => ({utc_offset_seconds: 0, hourly_units: {time: 'unixtime', ...Object.fromEntries(Object.entries(values).map(([k, [, u]]) => [k, u]))},
    hourly: {time, ...Object.fromEntries(Object.entries(values).map(([k, [v]]) => [k, time.map(() => v)]))}});
  const meta = {last_run_initialisation_time: Date.parse(at) / 1000 - 6 * 3600, data_end_time: time.at(-1)};
  return {region_id: region, retrieved: Date.parse(at) - 20 * 60_000, requested_points: [['monterey-bay', 36.7, -121.95], ['offshore-0-0', 36.5, -122.25]],
    models: !models ? {} : {gfs_global: {meta, data: [0, 1].map(() => series({wind_speed_10m: [9, 'kn'], wind_gusts_10m: [14, 'kn'], wind_direction_10m: [300, '°'], temperature_2m: [60, '°F'], cloud_cover: [30, '%']}))},
      ncep_gfswave016: {meta, data: [0, 1].map(() => series({wave_height: [5.1, 'ft'], wave_period: [12, 's']}))}}};
}
const good = (body = forecastFeed()) => async () => new Response(JSON.stringify(body), {status: 200});
const status = code => async () => new Response('', {status: code});
const timeout = async () => { throw new DOMException('timed out', 'TimeoutError'); };
function scripted(...responders) {
  const queue = [...responders], calls = [];
  const fn = async (url, init) => { calls.push(String(url)); return (queue.length > 1 ? queue.shift() : queue[0])(url, init); };
  fn.calls = calls;
  return fn;
}
function manual() {
  const pending = [];
  const fn = () => new Promise((resolve, reject) => pending.push({resolve, reject}));
  fn.pending = pending;
  return fn;
}

let bundle, n = 0;
async function load({timers = false} = {}) {
  bundle ??= pathToFileURL(outfile).href;
  delete globalThis.document;   // the app shell touches the page's document on import
  if (timers) mock.timers.enable({apis: ['setTimeout']});   // the verdict epoch's deadline is a real timer
  const m = await import(`${bundle}?${++n}`);   // a fresh module (and so fresh request state) per test, as a fresh page load
  globalThis.document = {visibilityState: 'hidden', addEventListener() {}};
  m.configureStore({v2: true, storage: null});
  m.language.value = 'en';
  m.region.value = INFO.id;
  m.regionInfo.value = INFO;
  m.day.value = null;
  m.hour.value = null;
  m.dailyFeed.value = montereyDaily;
  m.fixtures.coastBinding.value = {areaId: 'fixture'};
  m.fixtures.coastReport.value = {data: coastReport};
  m.beginVerdictRegion(INFO.id); m.noteRegionInfo(INFO.id);
  return m;
}
after(() => { delete globalThis.document; mock.timers.reset(); });

/** The real Conditions view; `click` is the Try again button's real handler. */
function show(m) {
  let click = null;
  const was = m.options.vnode;
  m.options.vnode = v => { if (v.type === 'button' && String(v.props.class ?? '').includes('app-forecast-retry')) click = v.props.onClick; was?.(v); };
  try { return {html: m.render(m.h(m.Conditions, {now})), click}; } finally { m.options.vnode = was; }
}
const retryButton = html => /<button[^>]*app-forecast-retry[^>]*>/.exec(html)?.[0] ?? null;
const readings = html => Object.fromEntries(Array.from((/<dl class="app-conditions-now"[^>]*>[\s\S]*?<\/dl>/.exec(html)?.[0] ?? '')
  .matchAll(/<dt class="ui-eyebrow">([^<]*)<\/dt><dd class="ui-mono">([^<]*)<\/dd>/g), ([, label, value]) => [label, value]));

/** The nearshore and tide series, the chart, the family and surface-current controls: all independent of the forecast. */
function assertLocalSeries(html, where) {
  const r = readings(html);
  assert.equal(r.Nearshore, '2.5 ft', `${where}: the nearshore series is shown`);
  assert.equal(r.Tide, '3.3 ft', `${where}: the tide series is shown`);
  assert.match(html, /<ul class="app-conditions-tides">/, `${where}: the tide events are listed`);
  assert.match(html, /class="app-conditions-chart"/, `${where}: the chart is mounted`);
  assert.match(html, /<label class="app-rail-source">[^<]*<select/, `${where}: the surface-current control is mounted`);
  assert.match(html, /<div role="group" aria-label="[^"]*" class="ui-segmented">/, `${where}: the model-family control is mounted`);
}
const failureShown = html => html.includes('data-forecast="failed"');

test('conditions_reports_http_and_timeout: an unmarked 503 and a timeout each show the reason and a native retry, with the local series intact', async () => {
  for (const [name, answer, copy] of [['an unmarked 503', status(503), 'HTTP 503'], ['a timeout', timeout, 'timeout']]) {
    const m = await load();
    assert.equal(await m.ensureRegionalForecast(INFO.id, INFO.center, scripted(answer), PAGE), null);
    const {html} = show(m);
    assert.ok(html.includes('Couldn\'t load the forecast'), `${name}: says the forecast could not be loaded`);
    assert.ok(failureShown(html) && html.includes(copy === 'timeout' ? 'data-reason="timeout"' : copy), `${name}: names the failure`);
    assert.match(retryButton(html) ?? '', /^<button[^>]*type="button"/, `${name}: offers a native Try again`);
    assert.doesNotMatch(retryButton(html), /disabled/, `${name}: Try again is available`);
    assert.match(html, /role="status"/);
    assertLocalSeries(html, name);
    assert.equal(readings(html).Wind, '—', `${name}: no invented value in the model rows`);
    m.language.value = 'es';
    try { assert.ok(show(m).html.includes('No se pudo cargar el pronóstico'), `${name}: in the page language`); } finally { m.language.value = 'en'; }
  }
});

test('conditions_loading_success_and_absent_are_not_failures: loading, success (with and without model rows) and no request show no error or retry', async () => {
  const m = await load();
  const hold = manual(), read = m.ensureRegionalForecast(INFO.id, INFO.center, hold, PAGE);
  let html = show(m).html;
  assert.ok(!failureShown(html) && !retryButton(html) && !html.includes('Couldn\'t'), 'still loading: no failure');
  assertLocalSeries(html, 'loading');
  hold.pending[0].resolve(new Response(JSON.stringify(forecastFeed()), {status: 200}));
  await read;
  html = show(m).html;
  assert.ok(!failureShown(html) && !retryButton(html), 'success: no failure');
  assert.equal(readings(html).Wind, '9 kt', 'success: the model rows are filled');
  assertLocalSeries(html, 'success');

  const bare = await load();
  await bare.ensureRegionalForecast(INFO.id, INFO.center, scripted(good(forecastFeed({models: false}))), PAGE);
  assert.equal(bare.regionalForecastState.value.state, 'loaded');
  html = show(bare).html;
  assert.ok(!failureShown(html) && !retryButton(html), 'admitted data with no model rows is not a transport failure');
  assertLocalSeries(html, 'no model rows');

  const none = await load();   // no request made: absent
  assert.equal(none.regionalForecastState.value.state, 'absent');
  html = show(none).html;
  assert.ok(!failureShown(html) && !retryButton(html), 'absent: no failure');
  assertLocalSeries(html, 'absent');
});

test('conditions_reports_http_and_timeout: Try again hides the failure while it runs, asks the same region once, and a good answer removes it', async () => {
  const m = await load();
  const fetchFn = scripted(status(503), good());
  await m.ensureRegionalForecast(INFO.id, INFO.center, fetchFn, PAGE);
  const failed = show(m);
  assert.ok(failureShown(failed.html) && typeof failed.click === 'function', 'the mounted button has its handler');
  failed.click();
  assert.equal(fetchFn.calls.length, 2, 'one more request');
  assert.ok(fetchFn.calls.every(url => url.includes(encodeURIComponent(INFO.id)) || url.includes(INFO.id)), 'the same region is asked again');
  const retrying = show(m).html;
  assert.ok(!failureShown(retrying) && !retryButton(retrying), 'while the retry loads the old failure is hidden');
  assertLocalSeries(retrying, 'retrying');
  await m.retryRegionalForecast();
  assert.equal(fetchFn.calls.length, 2, 'not one request per press');
  const done = show(m).html;
  assert.ok(!failureShown(done) && !retryButton(done), 'recovered: no failure');
  assert.equal(readings(done).Wind, '9 kt');

  const again = await load();   // a retry that fails again surfaces a fresh failure
  const second = scripted(status(500), status(503));
  await again.ensureRegionalForecast(INFO.id, INFO.center, second, PAGE);
  show(again).click();
  await again.retryRegionalForecast();
  assert.ok(show(again).html.includes('HTTP 503'), 'the second failure is reported');
});

test('conditions_does_not_show_old_region_failure: another region\'s or point\'s failure, and a stale outcome after a switch, show nothing', async () => {
  const m = await load();
  await m.ensureRegionalForecast(INFO.id, INFO.center, scripted(status(503)), PAGE);
  assert.ok(failureShown(show(m).html), 'the failure belongs to the selected region');
  // Select another region: the shared state is still the old region's failure.
  m.region.value = OTHER.id; m.regionInfo.value = OTHER;
  let html = show(m).html;
  assert.ok(!failureShown(html) && !retryButton(html), 'the old region\'s failure is not shown for the new one');
  // The new region's own read is pending; an outcome of the old region's earlier request then settles late.
  const stale = manual(), staleRead = m.ensureRegionalForecast(INFO.id, INFO.center, stale, PAGE);
  const current = manual(), currentRead = m.ensureRegionalForecast(OTHER.id, OTHER.center, current, PAGE);
  stale.pending[0].resolve(new Response('', {status: 500}));
  await staleRead;
  html = show(m).html;
  assert.ok(!failureShown(html) && !retryButton(html), 'a stale outcome after the switch surfaces nothing');
  current.pending[0].resolve(new Response('', {status: 503}));
  await currentRead;
  assert.ok(failureShown(show(m).html), 'the selected region\'s own failure does show');

  // The same region at another point: the earlier point's failure is not the current request's.
  const p = await load();
  await p.ensureRegionalForecast(INFO.id, INFO.center, scripted(status(503)), PAGE);
  p.regionInfo.value = {...INFO, center: [36.8, -121.8]};
  assert.ok(!failureShown(show(p).html), 'a different point\'s failure is not shown');
});

test('conditions_does_not_show_old_region_failure: a read the epoch gave up on at its deadline is a timeout with Try again, for the selected request only', async () => {
  const m = await load({timers: true});
  try {
    const hold = manual();
    void m.ensureRegionalForecast(INFO.id, INFO.center, hold, PAGE);
    assert.ok(!failureShown(show(m).html), 'before the deadline: still loading');
    mock.timers.tick(20_000);
    assert.equal(m.verdictEpoch.value.inputs.forecast.state, 'timedout');
    const html = show(m).html;
    assert.ok(failureShown(html) && html.includes('data-reason="timeout"'), 'after the deadline: the timeout is reported');
    assert.doesNotMatch(retryButton(html) ?? 'disabled', /disabled/, 'Try again stays available while the old read is pending');
    assertLocalSeries(html, 'timed out');
    // The same epoch, but for another selected region: nothing.
    m.region.value = OTHER.id; m.regionInfo.value = OTHER;
    assert.ok(!failureShown(show(m).html), 'the epoch of another region is not this region\'s timeout');
  } finally { mock.timers.reset(); }
});
