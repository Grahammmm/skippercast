// FE-33: the brief's tide trend and sparkline (web/tides.ts, web/brief/TideSpark.tsx).
// The rules are packages/coast ui/briefing.ts's (`tideAt`, `tideChart`); these
// tests pin web/tides.ts to them over a synthetic six-minute curve on the
// fixture coast report, then render the sparkline.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import fixture from './fixtures/coast/skippercast-report.json' with {type: 'json'};
import {rendererPlugins} from './helpers/esbuild-url.mjs';

const {tideTrend, sparkArgs, TIDE_UNAVAILABLE, TIDE_COLOUR} = await import('../web/tides.ts');
const {tideAt, tideChart} = await import('../packages/coast/src/ui/briefing.ts');
const {chart} = await import('../packages/coast/src/charts/series.ts');
const {slo} = await import('../packages/coast/src/counties.ts');
const {buildCoastBrief} = await import('../web/brief/model.ts');

const ROOT = new URL('..', import.meta.url).pathname;
const MIN = 60_000;
const now = new Date(Date.parse(fixture.generatedAt) + 10 * MIN);
const date = '2026-10-08';
const iso = ms => new Date(ms).toISOString();
const curve = (start, heights, stepMin = 6) => heights.map((heightFt, i) => ({at: iso(Date.parse(start) + i * stepMin * MIN), heightFt}));

// Synthetic: a semidiurnal sine every six minutes over the local day (07:00Z to 07:00Z), with a flat stand at 18:00Z.
const DAY0 = Date.parse('2026-10-08T07:00:00Z');
const synthetic = Array.from({length: 241}, (_, i) => {
  const t = DAY0 + i * 6 * MIN, stand = t >= Date.parse('2026-10-08T18:00:00Z') && t <= Date.parse('2026-10-08T18:30:00Z');
  return {at: iso(t), heightFt: stand ? 2.5 : 3 + 2 * Math.sin(2 * Math.PI * (t - DAY0) / (12.42 * 60 * MIN))};
});
const report = {...fixture, tides: synthetic};
const state = at => ({report, county: slo, mode: 'boat', areaId: 'central', species: 'lingcod', date, at, view: 'map', layer: 'habitat', base: 'ocean', maxDepth: 300, playing: false, motion: false, now, selectedSite: null});

test('acceptance 1: Rising, Falling or Turning by the 15-minute rule', () => {
  const start = '2026-10-08T18:00:00Z';
  assert.equal(tideTrend(curve(start, [1, 1.1]), start), 'Rising');
  assert.equal(tideTrend(curve(start, [1, 0.9]), start), 'Falling');
  assert.equal(tideTrend(curve(start, [1, 1.004]), start), 'Turning', 'a change under 0.005 ft');
  assert.equal(tideTrend(curve(start, [1, 1.006]), start), 'Rising');
  assert.equal(tideTrend(curve(start, [1, 1.1], 15), start), 'Rising', 'the next point at exactly 15 minutes counts');
  assert.equal(tideTrend(curve(start, [1, 1.1], 16), start), null, 'a coarser curve gives no trend');
  assert.equal(tideTrend(curve(start, [1, 1.1]), Date.parse(start) + 4 * MIN), 'Rising', 'the selected time may sit 4 minutes off a point');
  assert.equal(tideTrend(curve(start, [1, 1.1, 1.2]), Date.parse(start) - 5 * MIN), null, 'no point within 4 minutes');
  assert.equal(tideTrend(curve(start, [1, 1.1]), iso(Date.parse(start) + 6 * MIN)), null, 'the last point has no next one');
  assert.equal(tideTrend([], start), null);
  assert.equal(tideTrend(curve(start, [1, 1.1]), 'not a time'), null);
});

test('the trend equals briefing.ts tideAt over a whole day of the curve', () => {
  // The brief's curve does not depend on the selected time; tideAt rebuilds the day for each call.
  const {tides} = buildCoastBrief({report, county: slo, areaId: 'central', profile: 'boat', date, now});
  assert.equal(tides.length, synthetic.length - 1, 'the next midnight is the next day');
  let compared = 0;
  for (const point of synthetic) for (const offset of [0, 3, 5]) {
    const at = iso(Date.parse(point.at) + offset * MIN);
    assert.equal(tideTrend(tides, at) ?? 'Station prediction', tideAt(state(at)).trend, at);
    compared++;
  }
  assert.ok(compared > 700);
  const kinds = new Set(synthetic.map(p => tideTrend(synthetic, p.at)));
  for (const kind of ['Rising', 'Falling', 'Turning', null]) assert.ok(kinds.has(kind), `the synthetic day exercises ${kind}`);
});

test('the tide tile leads its detail with the trend, then the station and reference level', () => {
  const brief = at => buildCoastBrief({report, county: slo, areaId: 'central', profile: 'boat', date, now, at});
  const tile = at => brief(at).tiles.find(t => t.id === 'tide');
  assert.equal(tile('2026-10-08T18:06:00.000Z').detail, `Turning · ${slo.tideStation.name} · MLLW`);
  assert.match(tile('2026-10-08T08:00:00.000Z').detail, new RegExp(`^(Rising|Falling) · ${slo.tideStation.name} · MLLW$`));
  // The fixture's own curve is hourly: no trend, the detail keeps the station and datum.
  assert.equal(buildCoastBrief({report: fixture, county: slo, areaId: 'central', profile: 'boat', date, now, at: '2026-10-08T21:00:00.000Z'}).tiles.find(t => t.id === 'tide').detail, `${slo.tideStation.name} · MLLW`);
});

test('the sparkline is tideChart: chart() in mini mode over the day with night shading', () => {
  const at = '2026-10-08T21:00:00.000Z', brief = buildCoastBrief({report, county: slo, areaId: 'central', profile: 'boat', date, now, at});
  const args = sparkArgs(brief, at, slo.timezone);
  assert.equal(args[0][0].color, TIDE_COLOUR);
  assert.equal(args[0][0].unit, 'ft MLLW');
  assert.equal(args[5].mini, true);
  assert.ok(args[5].sunrise && args[5].sunset, 'night shading from the day\'s sunrise and sunset');
  // briefing.ts writes the literal hue; with it the markup is identical.
  assert.equal(chart(...sparkArgs(brief, at, slo.timezone, '#eabd76')), tideChart(state(at)));
  assert.match(chart(...args), /style="stroke:var\(--coast-amber\)"/);
});

test('acceptance 2: fewer than two points give no sparkline and read "Tide series unavailable"', () => {
  const day = {tides: [], tideEvents: [], tideDatum: 'MLLW', sunrise: null, sunset: null};
  assert.equal(sparkArgs(day, '2026-10-08T21:00:00Z', slo.timezone), null);
  assert.equal(sparkArgs({...day, tides: [{at: '2026-10-08T21:00:00Z', heightFt: 3}]}, '2026-10-08T21:00:00Z', slo.timezone), null);
  assert.equal(tideChart(state('2026-10-08T21:00:00.000Z')).includes(TIDE_UNAVAILABLE), false);
  assert.match(tideChart({...state('2026-10-08T21:00:00.000Z'), report: {...report, tides: synthetic.slice(0, 1)}}), new RegExp(TIDE_UNAVAILABLE));
});

let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'tides-')), 'tides.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {TideSpark} from './web/brief/TideSpark.tsx';
      export {regionInfo} from './web/app/App.tsx';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: rendererPlugins,
  });
  mod = await import(pathToFileURL(out).href);
  return mod;
}

test('TideSpark mounts the curve through CoastMarkup and lists the events with the reference level', async () => {
  const {TideSpark, render, h} = await load();
  const brief = buildCoastBrief({report, county: slo, areaId: 'central', profile: 'boat', date, now, at: '2026-10-08T21:00:00.000Z'});
  const html = render(h(TideSpark, {brief, now}));
  assert.match(html, /^<figure class="app-spark" aria-label="Tide curve"><div class="app-coast-markup" data-coast-theme="tokens" data-renderer="chart"><\/div><figcaption>/);
  assert.equal((html.match(/<li>/g) ?? []).length, brief.tideEvents.length);
  assert.ok(brief.tideEvents.length >= 2);
  assert.match(html, /<li>(High|Low) <span class="ui-mono">\d{1,2}:\d\d [ap]m · \d+\.\d ft MLLW<\/span><\/li>/);
});

test('TideSpark: without a curve it says so and keeps the events; before a brief it shows its empty state', async () => {
  const {TideSpark, render, h} = await load();
  const brief = buildCoastBrief({report: {...report, tides: []}, county: slo, areaId: 'central', profile: 'boat', date, now, at: '2026-10-08T21:00:00.000Z'});
  const html = render(h(TideSpark, {brief, now}));
  assert.match(html, /<span class="app-spark-empty">Tide series unavailable<\/span>/);
  assert.doesNotMatch(html, /app-coast-markup/);
  assert.match(html, /<figcaption><ul class="app-spark-events"><li>/);
  assert.equal(render(h(TideSpark, {brief: null, now})), '<figure class="app-spark" aria-label="Tide curve"><span class="app-spark-empty">—</span></figure>');
});
