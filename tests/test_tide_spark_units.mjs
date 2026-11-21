import test, {before, after} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {preparedRendererPlugins} from './helpers/esbuild-url.mjs';
import {sparkArgs} from '../web/tides.ts';
import {M_PER_FT} from '../web/units.ts';

const start = '2026-10-08T20:00:00.000Z', end = '2026-10-08T20:18:00.000Z';
const now = new Date(start), tz = 'America/Los_Angeles';
const brief = {
  tides: [{at: start, heightFt: 3.33}, {at: end, heightFt: 2.17}],
  tideEvents: [{at: start, heightFt: 5.16, type: 'H'}, {at: '2026-10-09T03:00:00.000Z', heightFt: -0.4, type: 'L'}],
  tideDatum: 'MLLW', sunrise: '2026-10-08T14:00:00.000Z', sunset: '2026-10-09T01:30:00.000Z',
};
const options = {mini: true, sunrise: brief.sunrise, sunset: brief.sunset};
const feet = [[{
  label: 'Tide', unit: 'ft MLLW', color: 'var(--coast-amber)',
  points: [{at: start, value: 3.33}, {at: end, value: 2.17}], gapMs: 900_000, min: -0.4, max: 5.16 + 0.3,
}], start, end, start, tz, options];
const metres = [[{
  label: 'Tide', unit: 'm MLLW', color: 'var(--coast-amber)',
  points: [{at: start, value: 3.33 * M_PER_FT}, {at: end, value: 2.17 * M_PER_FT}],
  gapMs: 900_000, min: -0.4 * M_PER_FT, max: (5.16 + 0.3) * M_PER_FT,
}], start, end, start, tz, options];

// A default-unit change or a conversion using only the sampled range would move the chart bounds.
test('C1: default and explicit feet preserve the whole result; metres scale the whole range', () => {
  assert.deepEqual(sparkArgs(brief, start, tz), feet);
  assert.deepEqual(sparkArgs(brief, start, tz, undefined, 'ft'), feet);
  assert.deepEqual(sparkArgs(brief, start, tz, undefined, 'm'), metres);
});

test('C1: metric mode preserves missing-curve exits and scales the non-finite fallback bounds', () => {
  assert.equal(sparkArgs({...brief, tideDatum: null}, start, tz, undefined, 'm'), null);
  assert.equal(sparkArgs({...brief, tides: brief.tides.slice(0, 1)}, start, tz, undefined, 'm'), null);
  assert.deepEqual(sparkArgs({...brief, tideEvents: [], tides: [{at: start, heightFt: NaN}, {at: end, heightFt: NaN}]}, start, tz, 'red', 'm'), [[{
    label: 'Tide', unit: 'm MLLW', color: 'red', points: [{at: start, value: NaN}, {at: end, value: NaN}],
    gapMs: 900_000, min: 0, max: 5.3 * M_PER_FT,
  }], start, end, start, tz, options]);
});

let dir, view;
before(async () => {
  dir = await mkdtemp(join(tmpdir(), 'tide-units-'));
  const outfile = join(dir, 'bundle.mjs');
  await build({
    stdin: {resolveDir: fileURLToPath(new URL('..', import.meta.url)), loader: 'ts', contents: `
      export {TideSpark} from './web/brief/TideSpark.tsx';
      export {language} from './web/i18n.ts';
      export {setUnits} from './web/unit-choice.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile, jsx: 'automatic', jsxImportSource: 'preact', plugins: preparedRendererPlugins,
  });
  view = await import(pathToFileURL(outfile).href);
});
after(async () => { if (dir) await rm(dir, {recursive: true, force: true}); });

const select = (lang, height) => {
  view.language.value = lang;
  view.setUnits({height});
};
const render = (data = brief) => view.render(view.h(view.TideSpark, {brief: data, now}));

// Inspect the real chart's input: the shadow-root chart itself is not part of the SSR HTML.
test('C2: the chart receives the chosen unit and preserves the translated row label', () => {
  for (const [lang, height, expected] of [
    ['en', 'ft', feet], ['en', 'm', metres], ['es', 'm', [[{...metres[0][0], label: 'Marea'}], ...metres.slice(1)]],
  ]) {
    select(lang, height);
    const chart = view.TideSpark({brief, now}).props.children[0];
    assert.deepEqual([chart.props.renderer, chart.props.args], ['chart', expected]);
  }
});

const eventList = html => html.match(/<ul class="app-spark-events">.*?<\/ul>/s)?.[0];
const list = (high, low) => `<ul class="app-spark-events"><li>${high}</li><li>${low}</li></ul>`;
const mono = (label, text) => `${label} <span class="ui-mono">${text}</span>`;
const pair = (clock, metric, imperial) => `${clock}<span class="app-screen-height"> · ${metric} m MLLW</span><span class="app-print-height"> · ${imperial} ft MLLW</span>`;

// Detect a hard-coded unit, unlocalized decimal, or loss of the feet fallback in print.
test('C3: full metric event lists localize decimals and retain feet for print', () => {
  select('en', 'm');
  assert.equal(eventList(render()), list(mono('High', pair('1:00 pm', '1.6', '5.2')), mono('Low', pair('8:00 pm', '-0.1', '-0.4'))));
  assert.equal(eventList(render({...brief, tideDatum: null})), list(mono('High', '1:00 pm'), mono('Low', '8:00 pm')));
  select('es', 'm');
  assert.equal(eventList(render()), list(mono('Pleamar', pair('13:00', '1,6', '5,2')), mono('Bajamar', pair('20:00', '-0,1', '-0,4'))));
});

// Whole figure from main: feet must not gain wrappers, new spacing or rewritten labels.
test('C4: feet renders match the pre-change bytes in English and Spanish', () => {
  const chart = '<div class="app-coast-markup" data-coast-theme="tokens" data-renderer="chart"></div>';
  for (const [lang, aria, events] of [
    ['en', 'Tide curve', list(mono('High', '1:00 pm · 5.2 ft MLLW'), mono('Low', '8:00 pm · -0.4 ft MLLW'))],
    ['es', 'Curva de marea', list(mono('Pleamar', '13:00 · 5,2 ft MLLW'), mono('Bajamar', '20:00 · -0,4 ft MLLW'))],
  ]) {
    select(lang, 'ft');
    assert.equal(render(), `<figure class="app-spark" aria-label="${aria}">${chart}<figcaption>${events}</figcaption></figure>`);
  }
});
