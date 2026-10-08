// FE-75: web/app/CoastMarkup.tsx, the v2 host for packages/coast markup
// (docs/plans/front-end/design.md § 3A.2). The component is bundled with
// esbuild and checked here: the renderer allow-list (at runtime and, through
// tsc on tests/fixtures/coast-markup/allow-list.tsx, in the types), the chart
// geometry its cursor reads, the selections it forwards and its host element.
// The shadow root, the token colours and the drag are e2e/coast-markup.spec.ts;
// the innerHTML rule is scripts/check_web.py (tests/unit/test_web_runtime_references.py).
import assert from 'node:assert/strict';
import test from 'node:test';
import {spawnSync} from 'node:child_process';
import {existsSync, readFileSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {basename, join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {lintFile} from '../scripts/check_tokens.mjs';
import {chart} from '../packages/coast/src/charts/series.ts';

const ROOT = new URL('..', import.meta.url).pathname;
const HOST = 'web/app/CoastMarkup.tsx';
const START = '2026-10-05T00:00:00Z', END = '2026-10-06T00:00:00Z';
const ROWS = [{label: 'Wind <gust>', unit: 'kt', color: 'var(--coast-blue)', points: [{at: '2026-10-05T06:00:00Z', value: 8}, {at: '2026-10-05T07:00:00Z', value: 11}]}];

/** Stylesheet `?url` imports resolve to their file name, as Vite's hashed URL would. */
const urlImports = {
  name: 'url-imports',
  setup(b) {
    b.onResolve({filter: /\?url$/}, args => ({path: join(args.resolveDir, args.path.replace(/\?url$/, '')), namespace: 'url'}));
    b.onLoad({filter: /.*/, namespace: 'url'}, args => ({contents: `export default ${JSON.stringify('/assets/' + basename(args.path))};`, loader: 'js'}));
  },
};

let loaded;
async function load() {
  if (loaded) return loaded;
  const out = join(await mkdtemp(join(tmpdir(), 'coast-markup-')), 'host.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `export * from './${HOST}'; export {render} from 'preact-render-to-string'; export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: [urlImports],
  });
  loaded = await import(pathToFileURL(out).href);
  return loaded;
}

test('only allow-listed packages/coast renderers produce markup', async () => {
  const {COAST_RENDERERS, coastMarkup} = await load();
  assert.deepEqual(Object.keys(COAST_RENDERERS), ['chart']);
  assert.ok(Object.isFrozen(COAST_RENDERERS));
  const args = [ROWS, START, END, '2026-10-05T12:00:00Z', 'UTC'];
  assert.equal(coastMarkup('chart', args), chart(...args), 'the string is chart()\'s own, unchanged');
  assert.match(coastMarkup('chart', args), /Wind &lt;gust&gt;/, 'feed-derived text arrives escaped by packages/coast');
  for (const name of ['historyView', 'toString', 'constructor', '__proto__', '']) assert.throws(() => coastMarkup(name, args), TypeError, name);
});

test('a chart series colour is a CSS colour, never markup', async () => {
  const {coastMarkup, isCoastColour} = await load();
  for (const ok of ['var(--coast-blue)', 'var(--blue)', '#abc', '#abcd', '#a1b2c3', '#a1b2c3d4', 'rgb(1, 2, 3)', 'rgba(1 2 3 / 50%)', 'hsl(200, 50%, 40%)', 'hsla(200 50% 40% / .5)'])
    assert.ok(isCoastColour(ok), ok);
  const attacks = ['"><img src=x onerror=alert(1)>', 'red;background:url(https://s.test/x)', 'var(--x);}', 'rgb(1,2,3)"', 'expression(alert(1))', '#abcde', 'red', '', null, 7];
  for (const bad of attacks) {
    assert.equal(isCoastColour(bad), false, String(bad));
    assert.throws(() => coastMarkup('chart', [[{...ROWS[0], color: bad}], START, END, START, 'UTC']), TypeError, String(bad));
  }
  assert.throws(() => coastMarkup('chart', [[ROWS[0], {...ROWS[0], color: '"><img onerror=alert(1)>'}], START, END, START, 'UTC']), TypeError, 'every row is checked');
  assert.throws(() => coastMarkup('chart', [null, START, END, START, 'UTC']), TypeError);
});

test('the renderer allow-list holds in the types (tsc on the fixture)', t => {
  const tsc = join(ROOT, 'node_modules/.bin/tsc');
  if (!existsSync(tsc)) { t.skip('web dependencies are not installed'); return; }
  const run = spawnSync(tsc, ['-p', join(ROOT, 'tests/fixtures/coast-markup/tsconfig.json'), '--noEmit'], {encoding: 'utf8'});
  assert.equal(run.status, 0, run.stdout + run.stderr);
});

test('the cursor geometry matches chart()\'s plot area, full and mini', async () => {
  const {CHART_GEOMETRY: g} = await load();
  // Each row's baseline spans the plot area (the faint grid ticks are vertical).
  const baseline = svg => svg.match(/<line x1="([\d.]+)" x2="([\d.]+)" y1="[\d.]+" y2="[\d.]+" style="stroke:var\(--coast-muted[^)]*\)" stroke-opacity="\.12"/).slice(1).map(Number);
  assert.match(chart(ROWS, START, END, START, 'UTC'), new RegExp(`viewBox="0 0 ${g.width} `));
  assert.deepEqual(baseline(chart(ROWS, START, END, START, 'UTC')), [g.left, g.width - g.right]);
  assert.deepEqual(baseline(chart(ROWS, START, END, START, 'UTC', {mini: true})), [g.miniLeft, g.width - g.miniRight]);
});

test('a position on the chart reads as the nearest whole hour inside its span', async () => {
  const {CHART_GEOMETRY: g, chartHourAt} = await load();
  const plot = g.width - g.left - g.right;
  assert.equal(chartHourAt(g.left, START, END), '2026-10-05T00:00Z');
  assert.equal(chartHourAt(g.left + plot / 2, START, END), '2026-10-05T12:00Z');
  assert.equal(chartHourAt(g.left + plot * (12.4 / 24), START, END), '2026-10-05T12:00Z');
  assert.equal(chartHourAt(g.left + plot * (12.6 / 24), START, END), '2026-10-05T13:00Z');
  assert.equal(chartHourAt(g.width - g.right, START, END), '2026-10-06T00:00Z');
  assert.equal(chartHourAt(0, START, END), '2026-10-05T00:00Z', 'left of the plot clamps to the start');
  assert.equal(chartHourAt(g.width, START, END), '2026-10-06T00:00Z', 'right of the plot clamps to the end');
  assert.equal(chartHourAt(g.width / 2, START, END, true), '2026-10-05T12:00Z', 'mini charts use the full width');
  assert.equal(chartHourAt(g.left, '2026-10-05T00:20:00Z', '2026-10-05T03:40:00Z'), '2026-10-05T01:00Z', 'never before the first whole hour');
  assert.equal(chartHourAt(g.width, '2026-10-05T00:20:00Z', '2026-10-05T03:40:00Z'), '2026-10-05T03:00Z', 'never after the last whole hour');
  assert.equal(chartHourAt(g.left, '2026-10-05T00:10:00Z', '2026-10-05T00:50:00Z'), null, 'no whole hour in the span');
  assert.equal(chartHourAt(Number.NaN, START, END), null);
  assert.equal(chartHourAt(g.left, 'not a time', END), null);
});

test('clicks and changes on the renderers\' controls become typed selections', async () => {
  const {clickSelection, changeSelection} = await load();
  const at = attrs => ({closest: selector => { const name = selector.slice(1, -1); return name in attrs ? {getAttribute: n => attrs[n]} : null; }});
  assert.deepEqual(clickSelection(at({'data-history-days': '14'})), {name: 'history-days', value: '14'});
  assert.deepEqual(clickSelection(at({'data-open': 'catches'})), {name: 'open', value: 'catches'});
  assert.deepEqual(clickSelection(at({'data-day': '2026-10-06'})), {name: 'day', value: '2026-10-06'});
  assert.equal(clickSelection(at({'data-other': 'x'})), null);
  assert.deepEqual(changeSelection({id: 'history-station', value: '46011'}), {name: 'history-station', value: '46011'});
  assert.deepEqual(changeSelection({id: 'history-metric', value: 'waveFt'}), {name: 'history-metric', value: 'waveFt'});
  assert.equal(changeSelection({id: 'species', value: 'x'}), null);
  assert.equal(changeSelection({id: 'toString', value: 'x'}), null);
});

test('the host element opts into the token bridge and renders no markup on the server', async () => {
  const {CoastMarkup, h, render} = await load();
  const html = render(h(CoastMarkup, {renderer: 'chart', args: [ROWS, START, END, START, 'UTC'], class: 'conditions-chart'}));
  assert.equal(html, '<div class="app-coast-markup conditions-chart" data-coast-theme="tokens" data-renderer="chart"></div>');
});

test('the host loads panel.css, its own sheet and the token bridge and holds no colour literal', () => {
  const source = readFileSync(join(ROOT, HOST), 'utf8');
  assert.match(source, /\[panelStyles, hostStyles, bridgeStyles\]/, 'panel.css first, so coast-markup.css overrides its :host variables');
  assert.deepEqual(lintFile('web/app/coast-markup.css', readFileSync(join(ROOT, 'web/app/coast-markup.css'), 'utf8')), []);
  assert.match(source, /from '\.\.\/\.\.\/packages\/coast\/panel\.css\?url'/);
  assert.match(source, /from '\.\.\/\.\.\/packages\/coast\/tokens-bridge\.css\?url'/);
  assert.deepEqual(lintFile(HOST, source), []);
  assert.equal(source.match(/\.innerHTML\s*=/g)?.length, 1, 'one assignment, of a COAST_RENDERERS result');
  assert.doesNotMatch(source, /outerHTML\s*=|insertAdjacentHTML|dangerouslySetInnerHTML|document\.write|setHTMLUnsafe|createContextualFragment|parseFromString/);
});
