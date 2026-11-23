import assert from 'node:assert/strict';
import test, {after} from 'node:test';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {preparedRendererPlugins} from './helpers/esbuild-url.mjs';
import montereyDaily from './fixtures/brief/monterey-daily.json' with {type: 'json'};
import {fToC, M_PER_FT, WIND_SPEED} from '../web/units.ts';

const root = fileURLToPath(new URL('..', import.meta.url));
const dir = await mkdtemp(join(tmpdir(), 'conditions-units-'));
after(() => rm(dir, {recursive: true, force: true}));
const outfile = join(dir, 'views.mjs');
await build({
  stdin: {resolveDir: root, loader: 'ts', contents: `
    export {Conditions} from './web/app/views/Conditions.tsx';
    export {CoastMarkup} from './web/app/CoastMarkup.tsx';
    export {HourlyTable} from './web/app/views/HourlyTable.tsx';
    export {regionInfo} from './web/app/App.tsx';
    export {dailyFeed, regionalForecast} from './web/brief/Brief.tsx';
    export {language} from './web/i18n.ts';
    export {configureStore, region, hour, day} from './web/state.ts';
    export {setUnits} from './web/unit-choice.ts';
    export {fixtures} from 'conditions-fixtures';
    export {render} from 'preact-render-to-string';
    export {h, options} from 'preact';`},
  bundle: true, platform: 'node', format: 'esm', outfile, jsx: 'automatic', jsxImportSource: 'preact',
  plugins: [...preparedRendererPlugins, {name: 'conditions-fixtures', setup(b) {
    b.onResolve({filter: /^(conditions-fixtures|\.\.\/\.\.\/(?:coast-data|view-copy)\.ts)$/}, args => {
      if (args.path === 'conditions-fixtures') return {path: 'inputs', namespace: 'fixtures'};
      if (args.importer.endsWith('/views/Conditions.tsx')) return {path: args.path, namespace: 'fixtures'};
    });
    b.onLoad({filter: /.*/, namespace: 'fixtures'}, ({path}) => ({resolveDir: root, contents: {
      inputs: `export const fixtures = {rows: null, coastReport: {value: null}, coastBinding: {value: null}};`,
      '../../coast-data.ts': `import {fixtures} from 'conditions-fixtures';
        export const {coastReport, coastBinding} = fixtures;
        export const coastData = {};`,
      // C1 injects a frozen result at the copy boundary, including units and
      // scale bounds that today's built-in row producers don't emit.
      '../../view-copy.ts': `import {fixtures} from 'conditions-fixtures';
        export * from './web/view-copy.ts';
        import {conditionsCopy as real} from './web/view-copy.ts';
        export const conditionsCopy = lang => {
          const copy = real(lang);
          return fixtures.rows ? {...copy, rows: () => fixtures.rows} : copy;
        };`,
    }[path]}));
  }}],
});
const v = await import(pathToFileURL(outfile).href);

const at = '2026-10-08T18:00:00.000Z', later = '2026-10-08T19:00:00.000Z', now = new Date(at);
const info = {id: montereyDaily.region_id, name: 'Monterey', timezone: 'America/Los_Angeles', center: [36.62, -121.9]};
const defaults = {temp: 'F', wind: 'kt', height: 'ft'}, metric = {temp: 'C', wind: 'kmh', height: 'm'};
const tide = {label: 'Tide', unit: 'ft', color: 'var(--coast-mint)', points: [{at, value: 3.3}, {at: later, value: -0.4}]};
const predictions = [
  {time: '2026-10-08T20:00:00Z', type: 'H', height_ft: 3.3},
  {time: '2026-10-09T03:00:00Z', type: 'L', height_ft: -0.4},
];
const model = variables => ({issued: Date.parse(at) / 1000 - 3600, data: {
  utc_offset_seconds: 0,
  hourly: {time: [Date.parse(at) / 1000, Date.parse(later) / 1000],
    ...Object.fromEntries(Object.entries(variables).map(([k, [x, y]]) => [k, [x, y]]))},
  hourly_units: {time: 'unixtime', ...Object.fromEntries(Object.entries(variables).map(([k, [, , unit]]) => [k, unit]))},
}});
const forecast = {region: info.id, point: {id: 'fixture'}, retrieved: now.getTime(), models: {
  gfs_global: model({wind_speed_10m: [12.4, 10, 'kn'], wind_gusts_10m: [16.5, 12, 'kn'], temperature_2m: [50, 41, '°F'], cloud_cover: [34.5, 5, '%']}),
  ncep_gfswave016: model({wave_height: [5, 6, 'ft'], wave_period: [12, 12, 's']}),
}};
const report = {sources: [], tides: tide.points.map(({at, value}) => ({at, heightFt: value})), nearshore: [{
  name: 'Fixture', areaId: 'fixture', availability: 'available', freshness: 'current', issuedAt: at, fetchedAt: at, hours: [{at, waveFt: 2.5}],
}]};
v.configureStore({v2: true, storage: null});
v.region.value = info.id;
v.regionInfo.value = info;
v.day.value = null;
v.hour.value = null;
v.regionalForecast.value = forecast;
v.fixtures.coastBinding.value = {areaId: 'fixture'};
v.fixtures.coastReport.value = {data: report};

// Record the real chart and table's inputs without replacing either renderer.
function view(choice = defaults, lang = 'en', {datum = 'MLLW', events = predictions, rows = null} = {}) {
  v.language.value = lang;
  v.setUnits(choice);
  v.dailyFeed.value = {...montereyDaily, sources: {...montereyDaily.sources, tides: {...montereyDaily.sources.tides,
    data: {...montereyDaily.sources.tides.data, predictions: events, datum}}}};
  v.fixtures.rows = rows;
  let chartRows, hourlyTide;
  const previous = v.options.vnode;
  v.options.vnode = vnode => {
    previous?.(vnode);
    if (vnode.type === v.CoastMarkup && vnode.props.renderer === 'chart') chartRows = vnode.props.args[0];
    if (vnode.type === v.HourlyTable) hourlyTide = vnode.props.tide;
  };
  try {
    return {html: v.render(v.h(v.Conditions, {now})), chartRows, hourlyTide};
  } finally {
    v.options.vnode = previous;
    v.fixtures.rows = null;
  }
}

const summary = html => html.match(/<dl class="app-conditions-now"[^>]*>[\s\S]*?<\/dl>/)[0];
const readings = html => Array.from(summary(html).matchAll(/<dt class="ui-eyebrow">([^<]*)<\/dt><dd class="ui-mono">([^<]*)<\/dd>/g), ([, label, value]) => [label, value]);
const tideList = html => html.match(/<ul class="app-conditions-tides">([\s\S]*?)<\/ul>/)?.[0] ?? null;
const clock = (en, es, lang) => lang === 'en' ? en : es;
const list = (lang, high, low) => `<ul class="app-conditions-tides"><li>${clock('High', 'Pleamar', lang)} <span class="ui-mono">${clock('1:00 PM PDT', '13:00 PDT', lang)}${high}</span></li><li>${clock('Low', 'Bajamar', lang)} <span class="ui-mono">${clock('8:00 PM PDT', '20:00 PDT', lang)}${low}</span></li></ul>`;
const heightPair = (screen, print) => `<span class="app-screen-height">${screen}</span><span class="app-print-height">${print}</span>`;
const enLabels = ['Wind', 'Gusts', 'Offshore seas', 'Nearshore', 'Tide', 'Air', 'Cloud'];
const esLabels = ['Viento', 'Ráfagas', 'Oleaje mar adentro', 'Cerca de la costa', 'Marea', 'Aire', 'Nubes'];
const labelled = (labels, values) => labels.map((label, i) => [label, values[i]]);
const enDefaults = ['12 kt', '17 kt', '5 ft', '2.5 ft', '3.3 ft', '50 °F', '35 %'];

// C1: a chart with the right unit label but an old value or scale still lies.
test('C1: chart rows use converted points and bounds without altering the originals', () => {
  const row = (label, unit, value, bounds = {}) => ({label, unit, color: '#123', gapMs: 120_000,
    points: [{at, value}, {at: later, value: null}, {at: '2026-10-08T20:00:00.000Z', value: undefined}], ...bounds});
  const originals = [row('Air', '°F', 50, {min: 30, max: 86}), row('Wind', 'kt', 12.4, {max: 20}),
    row('Tide', 'ft', -3.3, {min: -5}), row('Cloud', '%', 34.5, {min: 0, max: 100}), row('Period', 's', 12), row('Other', 'ft MLLW', 4)];
  const fixture = structuredClone(originals);
  for (const r of fixture) { r.points.forEach(Object.freeze); Object.freeze(r.points); Object.freeze(r); }
  Object.freeze(fixture);
  assert.deepEqual(view(defaults, 'en', {rows: fixture}).chartRows, originals);
  const result = view(metric, 'en', {rows: fixture}).chartRows;
  assert.deepEqual(result, [row('Air', '°C', 10, {min: fToC(30), max: 30}),
    row('Wind', 'km/h', 12.4 * WIND_SPEED.kmh.factor, {max: 20 * WIND_SPEED.kmh.factor}),
    row('Tide', 'm', -3.3 * M_PER_FT, {min: -5 * M_PER_FT}), ...originals.slice(3)]);
  assert.deepEqual(fixture, originals);
});

// C2: changing only the chart would still leave incompatible summary readings.
test('C2: metric summary rounds the entire list in English and Spanish; gaps show a dash', () => {
  assert.deepEqual(readings(view(metric).html), labelled(enLabels, ['23 km/h', '31 km/h', '1.5 m', '0.8 m', '1.0 m', '10.0 °C', '35 %']));
  assert.deepEqual(readings(view(metric, 'es').html), labelled(esLabels, ['23 km/h', '31 km/h', '1,5 m', '0,8 m', '1,0 m', '10,0 °C', '35 %']));
  assert.deepEqual(readings(view(metric, 'en', {rows: [{label: 'Wind', unit: 'kt', color: '#123', points: [{at, value: null}]}]}).html), [['Wind', '—']]);
});

// C3: passing chart Tide into HourlyTable multiplies by M_PER_FT twice and corrupts print.
test('C3: the original ft series goes to HourlyTable, which displays metres just once', () => {
  const {html, hourlyTide} = view(metric);
  assert.deepEqual(hourlyTide, tide);
  const cells = Array.from(html.matchAll(/<tr[^>]* data-at="[^"]+"[^>]*>(.*?)<\/tr>/gs), ([, tr]) => Array.from(tr.matchAll(/<td class="ui-mono">(.*?)<\/td>/gs), m => m[1])[6]);
  assert.deepEqual(cells, [heightPair('1.0 m', '3.3 ft'), heightPair('-0.1 m', '-0.4 ft')]);
});

// C4: metric events must retain the original feet for print, without inventing undeclared datums.
test('C4: tide events show metric screen and original print heights, or clocks alone without a datum', () => {
  for (const [lang, screen, print] of [['en', ['1.0', '-0.1'], ['3.3', '-0.4']], ['es', ['1,0', '-0,1'], ['3,3', '-0,4']]]) {
    assert.equal(tideList(view(metric, lang).html), list(lang, ...screen.map((n, i) => heightPair(` · ${n} m MLLW`, ` · ${print[i]} ft MLLW`))));
    assert.equal(tideList(view(metric, lang, {datum: ''}).html), list(lang, '', ''));
    const {html} = view(metric, lang, {events: []});
    assert.equal(tideList(html), null);
    assert.equal(html.match(/<h3 class="ui-eyebrow">[^<]*<\/h3>(<p class="app-empty">[^<]*<\/p>)/)?.[1],
      `<p class="app-empty">${clock('No tide predictions for Thu.', 'No hay predicciones de marea para jueves.', lang)}</p>`);
  }
});

// C5: default output must not gain padding or print wrappers, and mph must not be treated as km/h.
test('C5: default summary and tide lists preserve all baseline bytes in both languages; mph changes only wind', () => {
  for (const [lang, labels, values, aria, high, low] of [
    ['en', enLabels, enDefaults, 'Selected hour, Thu, 11:00 AM PDT', '3.3', '-0.4'],
    ['es', esLabels, ['12 kt', '17 kt', '5 ft', '2,5 ft', '3,3 ft', '50 °F', '35 %'], 'Hora seleccionada, jue, 11:00 PDT', '3,3', '-0,4'],
  ]) {
    const {html} = view(defaults, lang);
    const rows = labelled(labels, values).map(([label, value]) => `<div><dt class="ui-eyebrow">${label}</dt><dd class="ui-mono">${value}</dd></div>`).join('');
    assert.equal(summary(html), `<dl class="app-conditions-now" aria-label="${aria}">${rows}</dl>`);
    assert.equal(tideList(html), list(lang, ` · ${high} ft MLLW`, ` · ${low} ft MLLW`));
  }
  assert.deepEqual(readings(view({...defaults, wind: 'mph'}).html), labelled(enLabels, ['14 mph', '19 mph', ...enDefaults.slice(2)]));
});
