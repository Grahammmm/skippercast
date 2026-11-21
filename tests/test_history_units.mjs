import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import test from 'node:test';
import {build} from 'esbuild';
import {preparedRendererPlugins} from './helpers/esbuild-url.mjs';
import {fToC, M_PER_FT, WIND_SPEED} from '../web/units.ts';
import fixture from './fixtures/coast/history.json' with {type: 'json'};
import region from '../dist/regions/morro-bay/region.json' with {type: 'json'};

const dir = await mkdtemp(join(tmpdir(), 'history-units-'));
const app = await (async () => {
  try {
    const outfile = join(dir, 'history.mjs');
    await build({
      stdin: {resolveDir: fileURLToPath(new URL('..', import.meta.url)), loader: 'ts', contents: `
        export {History} from './web/app/views/History.tsx';
        export {CoastMarkup, coastMarkup} from './web/app/CoastMarkup.tsx';
        export {coastData} from './web/coast-data.ts';
        export {overviewReportContext} from './web/overview-context.ts';
        export {language} from './web/i18n.ts';
        export {setUnits} from './web/unit-choice.ts';
        export {historyCopy} from './web/view-copy.ts';
        export {historyView} from './packages/coast/src/ui/history.ts';
        export {h, options} from 'preact';
        export {render} from 'preact-render-to-string';`},
      bundle: true, platform: 'node', format: 'esm', outfile,
      jsx: 'automatic', jsxImportSource: 'preact', plugins: preparedRendererPlugins,
    });
    return await import(pathToFileURL(outfile).href);
  } finally {
    await rm(dir, {recursive: true, force: true});
  }
})();

const ctx = {county: {id: 'slo', timezone: 'UTC'}, now: new Date('2026-10-07T15:00:00Z')};
const defaults = {temp: 'F', wind: 'kt', height: 'ft'};
const metricUnits = {temp: 'C', wind: 'kmh', height: 'm'};
const mph = {...metricUnits, wind: 'mph'};
const selection = metric => ({station: 'synthetic-buoy', metric, days: 7});
// Stored p10/median/p90; water's stored difference is +1.8 °F.
const baseline = {
  waterTempF: [50, 55.6, 66.2], airTempF: [48, 62, 70], waveFt: [1, 2, 5],
  windKnots: [3, 5, 9], gustKnots: [5, 10, 15], periodS: [6, 10, 14],
};
const bundle = structuredClone(fixture);
bundle.stations[0].baseline.years = [2025];
bundle.stations[0].baseline.months = Object.entries(baseline).map(([metric, [p10, median, p90]]) => ({
  month: 10, metric, p10, median, p90, count: 12, expectedHours: 24, rawSampleCount: 60,
  yearsWithData: [2025], coverageFraction: 0.5,
}));
const digest = docs => createHash('sha256').update(docs.join('\n')).digest('hex');
const renderHistory = (metric, copy, units) => app.historyView(ctx, bundle, selection(metric), copy, units);
// ICU's localized date punctuation varies between Node builds. Pin the time formatter
// for the byte-level baseline while leaving the real Spanish copy and numbers intact.
const baselineCopy = lang => {
  const copy = app.historyCopy(lang);
  return copy && {...copy, time: (at, tz, options) => `${at}|${tz}|${JSON.stringify(options)}`};
};
// Captured with baselineCopy from origin/main 7335068e, over all six full views.
const prior = {en: '7af5393d50f239fc10cfa2e8e757904995877fda8742af777c3bc433b1cf17f5', es: 'b46811aa783b4e8908bab488ec542ad1348f7b11f0977a6cbc029b566a0bd806'};

test('C1: no units argument preserves all English and Spanish history bytes', () => {
  const rendered = Object.fromEntries(['en', 'es'].map(lang => [lang, digest(Object.keys(baseline).map(
    metric => app.historyView(ctx, bundle, selection(metric), baselineCopy(lang)),
  ))]));
  assert.deepEqual(rendered, prior);
  for (const metric of Object.keys(baseline)) {
    assert.equal(app.historyView(ctx, bundle, selection(metric)), renderHistory(metric, app.historyCopy('en')));
  }
});

test('C4: explicit default preferences preserve the complete pre-change output in both languages', () => {
  assert.deepEqual(Object.fromEntries(['en', 'es'].map(lang => [lang, digest(Object.keys(baseline).map(
    metric => renderHistory(metric, baselineCopy(lang), defaults),
  ))])), prior);
  for (const lang of ['en', 'es']) for (const metric of Object.keys(baseline)) {
    const copy = app.historyCopy(lang);
    assert.equal(renderHistory(metric, copy, defaults), renderHistory(metric, copy));
  }
});

const stats = html => html.match(/<div class="history-stats">.*<\/div>/)[0];
const reference = html => html.match(/<details class="history-measurement-note">.*?<\/details>/)[0];
const charts = html => html.match(/<div class="chart-title"><h3>.*?<\/div>|<svg class="(?:history|season)-chart"[\s\S]*?<\/svg>/g);
const expectedStats = (color, unit, [latest, mean, median, delta]) =>
  `<div class="history-stats"><div><span>Latest hourly mean</span><b style="color:var(--coast-${color})">${latest}<small> ${unit}</small></b><small>Hour starting Oct 7, 2 PM UTC</small></div>` +
  `<div><span>7-day average</span><b>${mean}<small> ${unit}</small></b><small>2 / 168 hourly bins · 1.2% metric coverage</small></div>` +
  `<div><span>Recorded UTC October median</span><b>${median}<small> ${unit}</small></b><small>1 contributing year · 12 hours · 50.0% coverage</small></div>` +
  `<div><span>Versus that month's median</span><b class="${delta.startsWith('+') ? 'coral' : 'blue'}">${delta}<small> ${unit}</small></b><small>Recorded hourly comparison · not a forecast</small></div></div>`;

// Literal rounded outputs catch wrong factors, units, or a temperature offset on a difference.
const cases = [
  ['waterTempF', 'Sea temperature', 'coral', '°F', '°C', fToC, metricUnits, ['14.1', '14.1', '13.1', '+1.0', '10.0', '19.0']],
  ['airTempF', 'Air temperature', 'amber', '°F', '°C', fToC, metricUnits, ['16.1', '15.8', '16.7', '-0.6', '8.9', '21.1']],
  ['waveFt', 'Wave height', 'blue', 'ft', 'm', n => n * M_PER_FT, metricUnits, ['1.0', '1.0', '0.6', '+0.4', '0.3', '1.5']],
  ['windKnots', 'Wind', 'mint', 'kt', 'km/h', n => n * WIND_SPEED.kmh.factor, metricUnits, ['13.0', '12.0', '9.3', '+3.7', '5.6', '16.7']],
  ['gustKnots', 'Reported gust', 'series-gust', 'kt', 'km/h', n => n * WIND_SPEED.kmh.factor, metricUnits, ['18.5', '17.6', '18.5', '0.0', '9.3', '27.8']],
  ['windKnots', 'Wind', 'mint', 'kt', 'mph', n => n * WIND_SPEED.mph.factor, mph, ['8.1', '7.5', '5.8', '+2.3', '3.5', '10.4']],
  ['gustKnots', 'Reported gust', 'series-gust', 'kt', 'mph', n => n * WIND_SPEED.mph.factor, mph, ['11.5', '10.9', '11.5', '0.0', '5.8', '17.3']],
];

for (const [metric, label, color, , unit, , preferences, values] of cases) {
  const contract = metric === 'waterTempF' || metric === 'waveFt' ? 'C4' : 'C2';
  test(`${contract}: ${label} in ${unit} has the full converted stats and reference`, () => {
    const html = renderHistory(metric, undefined, preferences);
    assert.equal(stats(html), expectedStats(color, unit, values));
    const [, , median, , p10, p90] = values;
    assert.equal(reference(html), '<details class="history-measurement-note"><summary>Reference coverage and contributing years</summary>' +
      `<p>UTC October ${label.toLowerCase()}: 12 observed hours out of 24 calendar hours; 60 valid original samples. 10th / median / 90th percentile: ${p10} / ${median} / ${p90} ${unit}.</p>` +
      '<p>Contributing years: 2025.</p></details>');
  });
}

test('C2: whole charts match plots of display-unit data, including localized axes and gaps', () => {
  // Plot independently preconverted input via the no-units path pinned by C1.
  for (const [metric, , , stored, unit, convert, preferences] of cases) {
    const input = structuredClone(bundle);
    input.stations[0].recent.hours.unshift({at: '2026-10-07T11:00:00Z', [metric]: 0}, {at: '2026-10-07T12:00:00Z', [metric]: null});
    const projected = structuredClone(input);
    for (const row of projected.stations[0].recent.hours) if (row[metric] !== null) row[metric] = convert(row[metric]);
    for (const row of projected.stations[0].baseline.months) if (row.metric === metric) {
      for (const key of ['p10', 'median', 'p90']) row[key] = convert(row[key]);
    }
    for (const lang of ['en', 'es']) {
      const copy = app.historyCopy(lang);
      const raw = app.historyView(ctx, projected, selection(metric), copy);
      const converted = app.historyView(ctx, input, selection(metric), copy, preferences);
      const token = new RegExp(`(^|[ >])${stored}(?=[ ,.<])`, 'g');
      assert.deepEqual(charts(converted), charts(raw).map(block => block.replace(token, `$1${unit}`)), `${metric} ${unit} ${lang}`);
      if (lang === 'es') assert.equal(reference(converted), reference(raw).replace(` ${stored}.</p>`, ` ${unit}.</p>`));
    }
  }
});

test('C2: missing data retains the whole empty output except for the chosen unit', () => {
  const empty = structuredClone(bundle);
  const station = empty.stations[0];
  station.recent.hours = station.recent.hours.map(row => ({...row, waveFt: null}));
  station.baseline.months = station.baseline.months.filter(row => row.metric !== 'waveFt');
  for (const lang of ['en', 'es']) {
    const args = [ctx, empty, selection('waveFt'), app.historyCopy(lang)];
    assert.equal(app.historyView(...args, metricUnits), app.historyView(...args).replace(/(^|[ >])ft(?=[ ,.<])/g, '$1m'));
  }
});

test('C1: invalid bundles take the complete unavailable path regardless of preferences', () => {
  const expected = '<div class="view-heading"><div><span class="eyebrow">RECORDED OCEAN HISTORY</span><h2>A longer view of the coast.</h2><p>Historical observations are unavailable for this county.</p></div></div>';
  for (const input of [null, {...bundle, countyId: 'other'}, {...bundle, stations: null}, {...bundle, stations: []}, {...bundle, stations: [false]}]) {
    assert.equal(app.historyView(ctx, input, selection('waveFt'), undefined, metricUnits), expected);
  }
});

test('C4: wave period stays byte-identical with metric preferences in both languages', () => {
  for (const lang of ['en', 'es']) {
    const copy = app.historyCopy(lang);
    assert.equal(renderHistory('periodS', copy, metricUnits), renderHistory('periodS', copy));
  }
});

test('C3: the real History component supplies new preferences to CoastMarkup in English and Spanish', async t => {
  const point = {latitude: 35.36, longitude: -120.94};
  const now = new Date(Date.parse(bundle.generatedAt) + 3_600_000);
  t.mock.timers.enable({apis: ['setTimeout', 'Date'], now});
  t.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify(bundle), {headers: {'Content-Type': 'application/json'}}));
  const previous = app.options.vnode;
  const calls = [];
  // SSR does not mount the shadow root: observe the real vnode, then check the allow-listed renderer output.
  app.options.vnode = vnode => {
    previous?.(vnode);
    if (vnode.type === app.CoastMarkup) calls.push(vnode.props);
  };
  t.after(() => {
    app.options.vnode = previous;
    app.setUnits(defaults);
    app.language.value = 'en';
    app.coastData.destroy();
  });
  assert.ok(app.coastData.setPlace(app.overviewReportContext(point, {...point, id: 'synthetic-selection', region: 'morro-bay'}, [region], 'boat', 'lingcod', now)));
  await app.coastData.load('history');
  for (const lang of ['en', 'es']) for (const preferences of [defaults, metricUnits]) {
    app.language.value = lang;
    app.setUnits(preferences);
    calls.length = 0;
    app.render(app.h(app.History, {now}));
    assert.equal(calls.length, 1);
    const {renderer, args} = calls[0];
    assert.equal(renderer, 'historyView');
    assert.equal(args.length, 5);
    assert.deepEqual(args[4], preferences);
    assert.equal(app.coastMarkup(renderer, args), app.historyView(args[0], bundle, args[2], app.historyCopy(lang), preferences));
  }
});
