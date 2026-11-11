// SC1922-08: the freshness chip's Refresh. The real orchestrator and loaders (web/brief/Brief.tsx, web/conditions.ts, web/coast-data.ts)
// run over scripted fetches; the chip is rendered with the real FreshnessDot and its button's own handler is pressed.
import assert from 'node:assert/strict';
import test, {mock} from 'node:test';
import {readFileSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import montereyDaily from './fixtures/brief/monterey-daily.json' with {type: 'json'};

const ROOT = new URL('..', import.meta.url).pathname;
const json = path => JSON.parse(readFileSync(new URL(path, import.meta.url), 'utf8'));
const REPORT = json('./fixtures/coast/report.json');
const MORRO_REGION = json('../dist/regions/morro-bay/region.json');
const ID = 'monterey-point-sur', PAGE = 'https://skippercast.test/map';
const INFO = {id: ID, name: 'Monterey', center: [36.62, -121.9], timezone: 'America/Los_Angeles'};
const GENERATED = Date.parse(REPORT.generatedAt);

let bundle, n = 0;
async function load() {
  if (!bundle) {
    const out = join(await mkdtemp(join(tmpdir(), 'brief-refresh-')), 'brief.mjs');
    await build({
      stdin: {resolveDir: ROOT, loader: 'ts', contents: `
        export * from './web/brief/Brief.tsx';
        export {FreshnessDot} from './web/app/Masthead.tsx';
        export {regionInfo, freshness} from './web/app/App.tsx';
        export {coastData} from './web/coast-data.ts';
        export {language} from './web/i18n.ts';
        export {prepareCatalogue} from './web/i18n-catalogue.ts';
        export {overviewReportContext} from './web/overview-context.ts';
        export {render} from 'preact-render-to-string';
        export {h, options} from 'preact';`},
      bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins,
    });
    bundle = pathToFileURL(out).href;
  }
  delete globalThis.document;
  const m = await import(`${bundle}?${++n}`); // fresh request state per test
  await m.prepareCatalogue('es');
  globalThis.document = {visibilityState: 'hidden', addEventListener() {}};
  return m;
}
test.after(() => { delete globalThis.document; });

/** One fetch for the page's loaders and another for the coast bridge, each counting what it was asked; `fail` names sources that answer 503. */
function network({fail = [], conditionsAt = '2026-10-08T21:00:00Z'} = {}) {
  const calls = {forecast: 0, daily: 0, conditions: 0, report: 0}, state = {fail: new Set(fail), conditionsAt};
  const forecast = () => {
    const start = Date.parse('2026-10-08T07:00:00Z') / 1000, time = Array.from({length: 8 * 24}, (_, i) => start + i * 3600);
    const series = values => ({utc_offset_seconds: 0, hourly_units: {time: 'unixtime', ...Object.fromEntries(Object.entries(values).map(([k, [, u]]) => [k, u]))}, hourly: {time, ...Object.fromEntries(Object.entries(values).map(([k, [v]]) => [k, time.map(() => v)]))}});
    const meta = {last_run_initialisation_time: start, data_end_time: time.at(-1)};
    return {region_id: ID, retrieved: Date.parse('2026-10-08T20:40:00Z'), requested_points: [['monterey-bay', 36.7, -121.95], ['offshore-0-0', 36.5, -122.25]],
      models: {gfs_global: {meta, data: [0, 1].map(() => series({wind_speed_10m: [9, 'kn'], wind_gusts_10m: [14, 'kn'], wind_direction_10m: [300, '°'], temperature_2m: [60, '°F'], cloud_cover: [30, '%']}))},
        ncep_gfswave016: {meta, data: [0, 1].map(() => series({wave_height: [5.1, 'ft'], wave_period: [12, 's']}))}}};
  };
  const page = async path => {
    path = String(path);
    const kind = path.includes('forecast') ? 'forecast' : path.startsWith('/feeds/data/') ? 'daily' : path.startsWith('/api/daily') ? 'part' : 'conditions';
    if (kind === 'part') return new Response('', {status: 404}); // the brief part refused: the whole daily feed is read
    calls[kind]++;
    if (state.fail.has(kind)) return new Response('', {status: 503});
    if (kind === 'forecast') return new Response(JSON.stringify(forecast()), {status: 200});
    if (kind === 'daily') return new Response(JSON.stringify({...montereyDaily, region_id: ID}), {status: 200});
    return new Response(JSON.stringify({schema_version: 1, region_id: ID, sources: {diablo: {id: 'diablo', name: 'NDBC 46042', kind: 'observation', url: '', checked_at: state.conditionsAt, status: 'ok'}}}), {status: 200});
  };
  const bridge = async () => { calls.report++; return state.fail.has('report') ? new Response('', {status: 503}) : new Response(JSON.stringify(REPORT), {status: 200, headers: {'Content-Type': 'application/json'}}); };
  return {calls, page, bridge, state};
}

/** Start the brief's three sources the way the app does, so each loader has the request a refresh repeats. */
async function startUp(t, m, net) {
  mock.timers.enable({apis: ['Date'], now: GENERATED + 3_600_000});
  const original = globalThis.fetch;
  globalThis.fetch = net.bridge;
  t.after(() => { m.coastData.destroy(); globalThis.fetch = original; mock.timers.reset(); });
  m.regionInfo.value = INFO;
  const region = {...MORRO_REGION};
  const bound = m.coastData.setPlace(m.overviewReportContext({latitude: 35.36, longitude: -120.94}, {latitude: 35.36, longitude: -120.94, id: 'sel', region: 'morro-bay'}, [region], 'boat', 'lingcod', new Date(GENERATED + 3_600_000)));
  assert.ok(bound, 'Morro Bay binds the coast report');
  await Promise.all([m.ensureRegionalForecast(ID, INFO.center, net.page, PAGE), m.loadDailyFeed(ID, net.page), m.coastData.load('report')]);
  const total = () => Object.values(net.calls).reduce((a, b) => a + b, 0);
  const before = {...net.calls};
  return {before, total};
}
const asked = (net, before) => Object.fromEntries(Object.keys(before).map(k => [k, net.calls[k] - before[k]]));

/** The chip's Refresh button, rendered by the real FreshnessDot, and its own handler. */
function chip(m) {
  let click = null, disabled = null;
  const was = m.options.vnode;
  m.options.vnode = v => { if (v.type === 'button' && String(v.props.class ?? '').includes('app-fresh-refresh')) { click = v.props.onClick; disabled = v.props.disabled; } was?.(v); };
  try { return {html: m.render(m.h(m.FreshnessDot, {})), click, disabled}; } finally { m.options.vnode = was; }
}

test('a press asks the forecast, the daily feeds and the coast report once each, and two quick presses ask once', async t => {
  const m = await load(), net = network();
  const {before} = await startUp(t, m, net);
  const {click, html} = chip(m);
  assert.ok(click, 'the chip has a Refresh button');
  assert.match(html, /<button[^>]*type="button"[^>]*>Refresh<\/button>|Refresh<\/button>/);
  const first = click(), second = click();
  assert.equal(m.manualRefresh.value, 'refreshing');
  assert.equal(chip(m).disabled, true, 'the button is busy while the press runs');
  await Promise.all([first, second, m.refreshBriefNow()]);
  const got = asked(net, before);
  assert.equal(got.forecast, 1); assert.equal(got.daily, 1); assert.equal(got.conditions, 1); assert.equal(got.report, 1);
  assert.equal(m.manualRefresh.value, 'idle');
  await m.refreshBriefNow();
  assert.equal(net.calls.forecast - before.forecast, 2, 'a later deliberate press asks again, once');
});

test('offline asks nothing and says Offline', async t => {
  const m = await load(), net = network();
  const {total} = await startUp(t, m, net);
  const was = total();
  await m.refreshBriefNow(() => false);
  assert.equal(total(), was);
  assert.equal(m.manualRefresh.value, 'offline');
  m.freshness.value = {state: 'offline', age: '3 h'};
  assert.match(chip(m).html, /data-refresh-line="offline">Offline</);
});

for (const source of ['forecast', 'conditions', 'report']) {
  test(`a failed ${source} refresh keeps the last brief inputs and says the refresh failed, in both languages`, async t => {
    const m = await load(), net = network();
    await startUp(t, m, net);
    const forecast = m.regionalForecast.value, daily = m.dailyFeed.value, report = m.coastData.coastReport.value;
    assert.ok(forecast && daily && report, `${source}: all three on screen`);
    net.state.fail.add(source);
    await m.refreshBriefNow();
    assert.equal(m.manualRefresh.value, 'failed', source);
    assert.equal(m.regionalForecast.value?.retrieved, forecast.retrieved, `${source}: the forecast stays`);
    assert.equal(m.regionalForecastState.value.state, 'loaded', `${source}: a failed refresh is not a failed forecast verdict`);
    assert.ok(m.dailyFeed.value && m.dailyFeed.value.region_id === ID, `${source}: the daily feed stays`);
    assert.ok(m.coastData.coastReport.value, `${source}: the coast report stays`);
    assert.match(chip(m).html, /data-refresh-line="failed">Refresh failed; showing the previous brief</);
    m.language.value = 'es';
    try { assert.match(chip(m).html, />Actualizar</); assert.match(chip(m).html, /No se pudo actualizar; se muestra el resumen anterior/); } finally { m.language.value = 'en'; }
    // The next deliberate press, answered, clears the failure.
    net.state.fail.delete(source);
    await m.refreshBriefNow();
    assert.equal(m.manualRefresh.value, 'idle', `${source}: a fresh answer ends the failure line`);
  });
}

test('a fresh answer updates what the chip ages from', async t => {
  const m = await load(), net = network();
  await startUp(t, m, net);
  const oldest = () => Date.parse(m.dailyFeed.value.sources.diablo.checked_at);
  assert.equal(oldest(), Date.parse('2026-10-08T21:00:00Z'));
  net.state.conditionsAt = '2026-10-08T22:30:00Z';
  await m.refreshBriefNow();
  assert.equal(oldest(), Date.parse('2026-10-08T22:30:00Z'), 'the new observation clock reaches the brief');
  assert.equal(m.manualRefresh.value, 'idle');
});
