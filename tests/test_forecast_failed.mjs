// SC1722-01: a forecast read that failed says so and offers Try again; it is never read as a weather verdict. The real loader
// (web/conditions.ts) and the real request/retry/generation code (web/brief/Brief.tsx) run over scripted fetches; the brief column
// (Desktop.tsx Brief, which the phone sheet also composes) and the first answer line are rendered to strings.
// 'Unknown' stays for a forecast that loaded but cannot rate the day.
import assert from 'node:assert/strict';
import {isDeepStrictEqual} from 'node:util';
import test from 'node:test';
import {mkdtemp, readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import montereyDaily from './fixtures/brief/monterey-daily.json' with {type: 'json'};

const ROOT = new URL('..', import.meta.url).pathname;
const INFO = {id: 'monterey-point-sur', name: 'Monterey', center: [36.62, -121.9], timezone: 'America/Los_Angeles'};
const NOW = new Date('2026-10-08T21:00:00Z');
const TOMORROW = new Date('2026-10-09T12:00:00Z'); // 5 am PDT, the morning still ahead
const PAGE = 'https://skippercast.test/map';
const KEY = 'monterey-point-sur|36.62,-121.9';
const FAILED_EN = 'Couldn\'t load the forecast', FAILED_ES = 'No se pudo cargar el pronóstico';
const VERDICT_WORD = /app-verdict-word|data-verdict=|data-fishable=|Comfortable|Marginal|Rough|Unknown|Desconocido/;

let bundle, n = 0;
async function load() {
  if (!bundle) {
    const out = join(await mkdtemp(join(tmpdir(), 'forecast-failed-')), 'forecast.mjs');
    await build({
      stdin: {resolveDir: ROOT, loader: 'ts', contents: `
        export * from './web/brief/Brief.tsx';
        export * from './web/brief/saved-brief.ts';
        export {loadConditionsForecast, parseConditionsForecast} from './web/conditions.ts';
        export {Brief} from './web/app/Desktop.tsx';
        export {FirstAnswerLine, regionInfo} from './web/app/App.tsx';
        export {language} from './web/i18n.ts';
        export {region} from './web/state.ts';
        export {render} from 'preact-render-to-string';
        export {h, options} from 'preact';`},
      bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins,
    });
    bundle = pathToFileURL(out).href;
  }
  delete globalThis.document; // the app shell touches the page's document on import
  const m = await import(`${bundle}?${++n}`); // a fresh module (and so fresh request state) per test, as a fresh page load
  globalThis.document = {visibilityState: 'hidden', addEventListener: (type, fn) => listeners.push([type, fn])};
  return m;
}
const listeners = [];
test.after(() => { delete globalThis.document; });

/** A synthetic /api/forecast answer for `region` (values invented): NOAA wind and waves hourly for eight days, the runs issued 6 h before NOW. */
function forecastFeed({region = INFO.id, models = true} = {}) {
  const start = Date.parse('2026-10-08T07:00:00Z') / 1000, time = Array.from({length: 8 * 24}, (_, i) => start + i * 3600);
  const series = values => ({utc_offset_seconds: 0, hourly_units: {time: 'unixtime', ...Object.fromEntries(Object.entries(values).map(([k, [, u]]) => [k, u]))},
    hourly: {time, ...Object.fromEntries(Object.entries(values).map(([k, [v]]) => [k, time.map(() => v)]))}});
  const meta = {last_run_initialisation_time: NOW.getTime() / 1000 - 6 * 3600, data_end_time: time.at(-1)};
  return {region_id: region, retrieved: NOW.getTime() - 20 * 60_000, requested_points: [['monterey-bay', 36.7, -121.95], ['offshore-0-0', 36.5, -122.25]],
    models: !models ? {} : {gfs_global: {meta, data: [0, 1].map(() => series({wind_speed_10m: [9, 'kn'], wind_gusts_10m: [14, 'kn'], wind_direction_10m: [300, '°'], temperature_2m: [60, '°F'], cloud_cover: [30, '%']}))},
      ncep_gfswave016: {meta, data: [0, 1].map(() => series({wave_height: [5.1, 'ft'], wave_period: [12, 's']}))}}};
}

const good = (body = forecastFeed()) => async () => new Response(JSON.stringify(body), {status: 200});
const status = code => async () => new Response('', {status: code});
const thrown = name => async () => { throw new DOMException('refused', name); };
/** A fetch that answers with each responder in turn (the last repeats) and records every request. */
function scripted(...responders) {
  const queue = [...responders], calls = [];
  const fn = async (url, init) => { calls.push(String(url)); return (queue.length > 1 ? queue.shift() : queue[0])(url, init); };
  fn.calls = calls;
  return fn;
}
/** A fetch whose answers the test settles by hand, one per request. */
function manual() {
  const pending = [];
  const fn = () => new Promise((resolve, reject) => pending.push({resolve, reject}));
  fn.pending = pending;
  return fn;
}

/** The brief column as the desktop and the phone sheet show it, with the first answer line; `click` is the Try again button's real handler. */
function show(m, now = TOMORROW) {
  let click = null;
  const was = m.options.vnode;
  m.options.vnode = v => { if (v.type === 'button' && String(v.props.class ?? '').includes('app-forecast-retry')) click = v.props.onClick; was?.(v); };
  try { return {brief: m.render(m.h(m.Brief, {now})), first: m.render(m.h(m.FirstAnswerLine, {now})), click}; } finally { m.options.vnode = was; }
}
const retryButton = html => /<button[^>]*app-forecast-retry[^>]*>/.exec(html)?.[0] ?? null;
/** The part of the column that leads: everything before the tiles. */
const lead = html => html.split('class="ui-tile"')[0];

async function onScreen(m, {daily = true} = {}) {
  m.regionInfo.value = INFO;
  if (daily) m.dailyFeed.value = montereyDaily;
}

test('forecast_failed_abort_500_invalid: the loader tells a failed read from a loaded one, with a finite reason and no exception text', async () => {
  const {loadConditionsForecast} = await load();
  const read = fetchFn => loadConditionsForecast(INFO.id, INFO.center, fetchFn, PAGE);
  const cases = [
    [thrown('AbortError'), {state: 'failed', reason: 'aborted'}],
    [thrown('TimeoutError'), {state: 'failed', reason: 'timeout'}],
    [async () => { throw new TypeError('fetch failed: https://secret.example/api/forecast'); }, {state: 'failed', reason: 'network'}],
    [status(500), {state: 'failed', reason: 'http', status: 500}],
    [status(404), {state: 'failed', reason: 'http', status: 404}],
    [async () => new Response('{nope', {status: 200}), {state: 'failed', reason: 'invalid'}],
    [good({}), {state: 'failed', reason: 'invalid'}],
    [good(forecastFeed({region: 'morro-bay'})), {state: 'failed', reason: 'invalid'}],
  ];
  for (const [fetchFn, want] of cases) {
    const got = await read(fetchFn);
    assert.ok(isDeepStrictEqual(got, want), `${JSON.stringify(want)}: got ${JSON.stringify(got)}`);
  }
  const loaded = await read(good(forecastFeed({models: false})));
  assert.equal(loaded.state, 'loaded', 'an admitted feed with no model runs is a loaded forecast');
  assert.ok(isDeepStrictEqual(loaded.forecast.models, {}));
});

for (const [name, answer, reason, code] of [['an aborted request', thrown('AbortError'), 'aborted'], ['HTTP 500', status(500), 'http', 500], ['{}', good({}), 'invalid']]) {
  test(`forecast_failed_abort_500_invalid: ${name} gives the failed state with Try again and no verdict word, on the column and the first answer`, async () => {
    const m = await load();
    await onScreen(m);
    assert.equal(await m.ensureRegionalForecast(INFO.id, INFO.center, scripted(answer), PAGE), null);
    const s = m.regionalForecastState.value;
    assert.ok(isDeepStrictEqual(s, {region: INFO.id, key: KEY, generation: 1, state: 'failed', reason, ...(code ? {status: code} : {})}), JSON.stringify(s));
    assert.equal(m.regionalForecast.value, null);
    const {brief, first} = show(m);
    for (const [where, html] of [['column', lead(brief)], ['first answer', first]]) {
      assert.ok(html.includes(FAILED_EN), `${where} says the forecast could not be loaded`);
      assert.ok(retryButton(html), `${where} offers a native Try again button`);
      assert.match(html, />Try again</);
      assert.doesNotMatch(html.replace(/<p class="app-first-answer-rules">.*?<\/p>/, ''), VERDICT_WORD, `${where}: no verdict word or attribute`);
    }
    assert.match(lead(brief), /data-reason="/);
    if (code) assert.ok(lead(brief).includes(`HTTP ${code}`), 'the plain reason names the status');
    // The same failure in Spanish, retained and re-worded when the language changes.
    m.language.value = 'es';
    try {
      const es = show(m);
      assert.ok(lead(es.brief).includes(FAILED_ES) && es.first.includes(FAILED_ES));
      assert.match(es.first, />Intentar de nuevo</);
      assert.doesNotMatch(lead(es.brief), VERDICT_WORD);
    } finally { m.language.value = 'en'; }
  });
}

test('forecast_failed_abort_500_invalid: Try again is a native button with a 44 px target', async () => {
  const m = await load();
  await onScreen(m);
  await m.ensureRegionalForecast(INFO.id, INFO.center, scripted(status(500)), PAGE);
  const html = lead(show(m).brief);
  assert.match(retryButton(html), /^<button[^>]*type="button"/);
  const [ui, tokens] = await Promise.all([readFile(join(ROOT, 'web/ui/ui.css'), 'utf8'), readFile(join(ROOT, 'web/tokens.css'), 'utf8')]);
  assert.match(tokens, /--touch-min: 44px;/);
  assert.match(ui, /\.ui-button \{[^}]*min-height: var\(--touch-min\)/, 'the default button keeps the 44 px target');
});

test('forecast_retry_recovers_once: Try again runs the same loader; a good answer gives the verdict, with no Unknown step between', async () => {
  const m = await load();
  await onScreen(m);
  const fetchFn = scripted(status(500), good());
  await m.ensureRegionalForecast(INFO.id, INFO.center, fetchFn, PAGE);
  const failed = show(m);
  assert.equal(typeof failed.click, 'function', 'the mounted button has its handler');
  failed.click();   // the button's own handler
  assert.equal(m.regionalForecastState.value.state, 'loading');
  assert.equal(m.regionalForecastState.value.reason, 'http', 'the failure being retried is kept while it runs');
  assert.equal(fetchFn.calls.length, 2);
  const retry = m.retryRegionalForecast();
  failed.click();
  assert.equal(m.retryRegionalForecast(), retry, 'a second press joins the read in flight');
  const waiting = show(m);
  for (const html of [lead(waiting.brief), waiting.first]) {
    assert.ok(html.includes('Waiting for readings.'), 'retrying with nothing held reads as waiting');
    assert.doesNotMatch(html.replace(/<p class="app-first-answer-rules">.*?<\/p>/, ''), VERDICT_WORD, 'not Unknown while it runs');
    assert.ok(!retryButton(html));
  }
  const f = await retry;
  assert.equal(fetchFn.calls.length, 2, 'one more request, not one per press');
  assert.equal(f.region, INFO.id);
  assert.ok(isDeepStrictEqual(m.regionalForecastState.value, {region: INFO.id, key: KEY, generation: 2, state: 'loaded'}));
  const done = show(m);
  assert.match(done.brief, /<span class="app-verdict-word">(Comfortable|Marginal|Rough)<\/span>/, 'the real verdict');
  assert.match(done.first, /data-fishable="(yes|marginal|no)"/);
  assert.doesNotMatch(done.brief + done.first, /app-forecast-failed|Try again/);
});

test('forecast_retry_recovers_once: a retry that fails again stays an error, and a language switch re-words it', async () => {
  const m = await load();
  await onScreen(m);
  const fetchFn = scripted(status(500), status(503));
  await m.ensureRegionalForecast(INFO.id, INFO.center, fetchFn, PAGE);
  show(m).click();
  assert.equal(await m.retryRegionalForecast(), null);
  assert.equal(fetchFn.calls.length, 2);
  const s = m.regionalForecastState.value;
  assert.ok(s.state === 'failed' && s.status === 503 && s.generation === 2, JSON.stringify(s));
  const again = show(m);
  assert.ok(lead(again.brief).includes('HTTP 503') && retryButton(lead(again.brief)));
  assert.doesNotMatch(lead(again.brief), VERDICT_WORD);
  m.language.value = 'es';
  try { assert.ok(lead(show(m).brief).includes(FAILED_ES)); } finally { m.language.value = 'en'; }
});

test('forecast_loaded_gap_is_unknown: a loaded forecast with no usable hours still reads Unknown, never a transport failure', async () => {
  const m = await load();
  await onScreen(m);
  const f = await m.ensureRegionalForecast(INFO.id, INFO.center, scripted(good(forecastFeed({models: false}))), PAGE);
  assert.ok(f && Object.keys(f.models).length === 0);
  assert.equal(m.regionalForecastState.value.state, 'loaded');
  const {brief, first} = show(m);
  assert.match(brief, /<span class="app-verdict-word">Unknown<\/span>/);
  assert.match(first, /data-fishable="unknown"/);
  assert.doesNotMatch(brief + first, /app-forecast-failed|Try again|Couldn't/);
});

test('forecast_generation_and_visibility: same-key requests join one read, and an older read cannot overwrite a newer one (A, B, A)', async () => {
  const m = await load();
  const fetchFn = manual();
  const a1 = m.ensureRegionalForecast('A', null, fetchFn, PAGE), joined = m.ensureRegionalForecast('A', null, fetchFn, PAGE);
  assert.equal(joined, a1, 'the second call joins the pending read');
  assert.equal(fetchFn.pending.length, 1);
  const b = m.ensureRegionalForecast('B', null, fetchFn, PAGE);
  const a2 = m.ensureRegionalForecast('A', null, fetchFn, PAGE);
  assert.equal(fetchFn.pending.length, 3);
  assert.equal(m.regionalForecastState.value.generation, 3);
  fetchFn.pending[0].resolve(new Response('', {status: 500}));   // the first A read, long superseded
  await a1;
  assert.ok(m.regionalForecastState.value.state === 'loading' && m.regionalForecastState.value.generation === 3, 'a superseded failure leaves the current read alone');
  fetchFn.pending[1].resolve(new Response(JSON.stringify(forecastFeed({region: 'B'})), {status: 200}));
  await b;
  assert.equal(m.regionalForecast.value, null, 'B\'s answer is not shown for A');
  assert.equal(m.regionalForecastState.value.region, 'A');
  fetchFn.pending[2].resolve(new Response(JSON.stringify(forecastFeed({region: 'A'})), {status: 200}));
  const f = await a2;
  assert.ok(f?.region === 'A' && m.regionalForecast.value === f);
  assert.ok(isDeepStrictEqual(m.regionalForecastState.value, {region: 'A', key: 'A|', generation: 3, state: 'loaded'}));
});

test('forecast_generation_and_visibility: an obsolete abort is ignored; the current request\'s abort is a failed state', async () => {
  const m = await load();
  const first = manual();
  const stale = m.ensureRegionalForecast('A', null, first, PAGE);
  const current = m.ensureRegionalForecast('B', null, scripted(thrown('AbortError')), PAGE);
  first.pending[0].reject(new DOMException('gone', 'AbortError'));
  await stale;
  assert.equal(m.regionalForecastState.value.region, 'B');
  await current;
  const s = m.regionalForecastState.value;
  assert.ok(s.region === 'B' && s.state === 'failed' && s.reason === 'aborted' && s.generation === 2, JSON.stringify(s));
});

test('forecast_generation_and_visibility: the 30-minute rule, fresh no-fetch, and a visible page retries a failed read', async () => {
  const m = await load();
  listeners.length = 0;
  globalThis.document.visibilityState = 'hidden';
  let fail = false;
  const fetchFn = scripted(async () => fail ? new Response('', {status: 503}) : new Response(JSON.stringify(forecastFeed()), {status: 200}));
  await m.ensureRegionalForecast(INFO.id, INFO.center, fetchFn, PAGE);
  assert.equal(fetchFn.calls.length, 1);
  const now = Date.now();
  assert.equal(m.refreshForecastIfStale(now + m.FORECAST_MAX_AGE_MS - 60_000), null, 'inside 30 minutes: kept, no request');
  assert.equal(fetchFn.calls.length, 1);
  fail = true;
  await m.refreshForecastIfStale(now + m.FORECAST_MAX_AGE_MS + 60_000);
  assert.equal(fetchFn.calls.length, 2, 'past 30 minutes: read again');
  assert.equal(m.regionalForecastState.value.state, 'failed');
  assert.equal(m.regionalForecast.value, null);
  fail = false;
  globalThis.document.visibilityState = 'visible';
  listeners.find(l => l[0] === 'visibilitychange')[1]();
  await new Promise(r => setTimeout(r, 50));
  assert.equal(fetchFn.calls.length, 3, 'a visible page retries after a failure');
  assert.equal(m.regionalForecastState.value.state, 'loaded');
  listeners.find(l => l[0] === 'visibilitychange')[1]();
  assert.equal(fetchFn.calls.length, 3, 'a fresh forecast is not read again');
});

const memory = () => { const map = new Map(); return {getItem: k => map.get(k) ?? null, setItem: (k, v) => { map.set(k, String(v)); }, map}; };
const feedServer = () => async path => {
  path = String(path);
  if (path.startsWith('/api/daily')) return new Response('', {status: 404});
  const isDaily = path.startsWith('/feeds/data/'), id = decodeURIComponent(path.split('/')[4]);
  return new Response(JSON.stringify(isDaily ? {...montereyDaily, region_id: id} : {schema_version: 1, region_id: id, sources: {diablo: {id: 'diablo', name: 'NDBC 46042', kind: 'observation', url: '', checked_at: '2026-10-08T21:00:00Z', status: 'ok'}}}), {status: 200});
};

test('forecast_saved_hold_is_labelled: a failed update keeps the saved forecast and its time, says so beside the saved line, and a good retry replaces it', async () => {
  const store = memory();
  const first = await load();
  first.regionInfo.value = INFO;
  first.enableSavedBrief(store);
  await first.loadDailyFeed(INFO.id, feedServer());
  await first.ensureRegionalForecast(INFO.id, INFO.center, scripted(good()), PAGE);
  const savedAt = JSON.parse(store.map.get(first.SAVED_BRIEF_KEY)).forecast.at;
  assert.equal(typeof savedAt, 'number');

  const m = await load();   // the next visit
  m.enableSavedBrief(store);
  assert.equal(m.showSavedBrief(INFO.id), true);
  const held = m.regionalForecast.value;
  assert.equal(held?.region, INFO.id, 'the saved forecast is on screen before any read');
  const fetchFn = scripted(status(500), good());
  await m.loadDailyFeed(INFO.id, feedServer());   // the daily read succeeds; only the forecast fails
  await m.ensureRegionalForecast(INFO.id, INFO.center, fetchFn, PAGE);
  assert.equal(m.regionalForecast.value, held, 'the saved forecast stays');
  assert.equal(m.regionalForecastState.value.state, 'failed');
  assert.equal(m.savedBrief.value.state, 'failed');
  assert.equal(JSON.parse(store.map.get(m.SAVED_BRIEF_KEY)).forecast.at, savedAt, 'a failed update never writes the saved forecast as fresh');
  const failed = show(m);
  assert.match(failed.brief, /data-saved="failed"/, 'the saved line is beside it');
  assert.match(failed.brief, /<span class="app-verdict-word">(Comfortable|Marginal|Rough|Unknown)<\/span>/, 'the saved answer stays');
  assert.ok(failed.brief.includes(FAILED_EN) && failed.first.includes(FAILED_EN), 'with the failed-update notice');
  assert.ok(retryButton(failed.brief) && !/disabled/.test(retryButton(failed.brief)));
  failed.click();
  const retry = m.retryRegionalForecast();
  const busy = show(m);
  assert.match(retryButton(busy.brief), /disabled/, 'disabled while the read runs');
  assert.match(busy.brief, /aria-busy="true"/);
  assert.equal(m.retryRegionalForecast(), retry, 'a second press joins the read in flight');
  await retry;
  assert.equal(fetchFn.calls.length, 2);
  assert.equal(m.savedBrief.value, null, 'the new read replaces the saved one');
  const done = show(m);
  assert.doesNotMatch(done.brief + done.first, /app-forecast-failed|data-saved/);
});

test('forecast_saved_hold_is_labelled: storage unavailable changes nothing about the failure', async () => {
  const m = await load();
  await onScreen(m);
  m.enableSavedBrief({getItem() { throw new Error('blocked'); }, setItem() { throw new Error('full'); }});
  await m.ensureRegionalForecast(INFO.id, INFO.center, scripted(status(500)), PAGE);
  assert.equal(m.regionalForecastState.value.state, 'failed');
  assert.equal(m.savedBrief.value, null);
  assert.ok(lead(show(m).brief).includes(FAILED_EN));
});
