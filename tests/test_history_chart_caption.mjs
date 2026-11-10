// SC1722-18: real renderer/copy, independent labels and pre-change chart bytes.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {preparedRendererPlugins} from './helpers/esbuild-url.mjs';
import fixture from './fixtures/coast/history.json' with {type: 'json'};
const dir = mkdtempSync(join(tmpdir(), 'history-caption-'));
const out = join(dir, 'renderer.mjs');
await build({plugins: preparedRendererPlugins, stdin: {resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts', contents: `export {historyView} from './packages/coast/src/ui/history.ts'; export {historyCopy} from './web/view-copy.ts';`}, bundle: true, platform: 'node', format: 'esm', outfile: out, logLevel: 'silent'});
const {historyView, historyCopy} = await import(pathToFileURL(out).href);
rmSync(dir, {recursive: true, force: true});
const rows = [
  ['waterTempF', 'Sea temperature', 'Temperatura del mar', '°F'],
  ['waveFt', 'Wave height', 'Altura de ola', 'ft'],
  ['windKnots', 'Wind', 'Viento', 'kt'],
  ['airTempF', 'Air temperature', 'Temperatura del aire', '°F'],
  ['gustKnots', 'Reported gust', 'Ráfaga reportada', 'kt'],
  ['periodS', 'Dominant wave period', 'Período dominante de ola', 'sec'],
];
const ctx = {county: {id: 'slo', timezone: 'America/Los_Angeles'}, now: new Date('2026-10-07T15:10:00Z')};
const render = (bundle, metric, days, copy) => historyView(ctx, bundle, {station: '', metric, days}, copy);
const chart = html => html.match(/<svg class="history-chart"[\s\S]*?<\/svg>/)?.[0];
const node = text => `<text x="47" y="12" class="axis history-measurement-caption">${text}</text>`;
function caption(svg, text) {
  assert.ok(svg.includes(node(text)), text);
  assert.equal((svg.match(/history-measurement-caption/g) ?? []).length, 1);
  assert.match(svg, /viewBox="0 0 1000 270" role="img"/);
}
for (const lang of ['en', 'es']) test(`recent_caption_six_metrics_${lang}: all ranges, full aria and pre-change geometry/season`, () => {
  const charts = [];
  for (const [metric, en, es, unit] of rows) for (const days of [7, 14, 45]) {
    const name = lang === 'en' ? en : es, copy = historyCopy(lang);
    const html = render(fixture, metric, days, copy), svg = chart(html);
    caption(svg, `${name}, ${unit}`);
    const aria = lang === 'en' ? `${name}, previous ${days} days, ${unit}. Missing observations remain gaps.` : `${name}, últimos ${days} días, ${unit}. Las observaciones faltantes quedan como huecos.`;
    assert.ok(svg.includes(`aria-label="${aria}"`));
    charts.push(...html.replace(node(`${name}, ${unit}`), '').match(/<svg class="(?:history|season)-chart"[\s\S]*?<\/svg>/g));
    assert.ok(render(fixture, metric, days) === render(fixture, metric, days, historyCopy('en')), 'English roundtrip');
  }
  // Captured from current main before adding the caption: every old chart byte is retained.
  const prior = {en: 'f6e837119a1f1bc3ef15c544669ef33a0bef089a79f1eb7ed01bcacd323d54b0', es: 'bff00442583389feabcb3366ab8563896764e48caaeb2282e85990f609895d46'};
  assert.equal(createHash('sha256').update(charts.join('\n')).digest('hex'), prior[lang]);
});
test('caption_empty_and_unavailable: null/nonfinite/empty and excluded times retain caption/default scales', () => {
  for (const lang of ['en', 'es']) for (const [metric, en, es, unit] of rows) for (const mode of ['empty', 'null', 'nonfinite']) {
    const b = structuredClone(fixture), st = b.stations[0];
    st.recent.hours = mode === 'empty' ? [] : st.recent.hours.map(h => ({...h, [metric]: mode === 'null' ? null : NaN}));
    const svg = chart(render(b, metric, 7, historyCopy(lang)));
    caption(svg, `${lang === 'en' ? en : es}, ${unit}`);
    assert.ok(svg.includes('x="500" y="130"'), 'existing no-observation message');
    assert.ok(svg.includes(lang === 'en' ? 'No supported' : 'No hay observaciones válidas'));
    assert.ok(svg.includes('>0.0</text>') || svg.includes('>0,0</text>'));
    assert.ok(svg.includes('>10.0</text>') || svg.includes('>10,0</text>'));
    st.recent.hours.push({at: '2020-01-01T00:00:00Z', [metric]: -999}, {at: '2030-01-01T00:00:00Z', [metric]: 999});
    assert.ok(chart(render(b, metric, 7, historyCopy(lang))) === svg, 'excluded samples cannot change chart');
  }
  for (const b of [null, {...fixture, countyId: 'other'}, {...fixture, stations: []}]) assert.equal(chart(render(b, 'waveFt', 7)), undefined);
});
test('caption_host_copy_escaped_once and missing samples stay gap-separated', () => {
  const copy = historyCopy('es'), raw = '<g data-x="q"> & \'single\'';
  const hostile = {...copy, text: (key, vars) => key.startsWith('history.metric.') ? raw : copy.text(key, vars)};
  const svg = chart(render(fixture, 'waveFt', 14, hostile));
  caption(svg, '&lt;g data-x=&quot;q&quot;&gt; &amp; &#39;single&#39;, ft');
  assert.doesNotMatch(svg, /<g|&amp;lt;|&amp;amp;/);
  assert.equal(raw, '<g data-x="q"> & \'single\'');
  const b = structuredClone(fixture);
  b.stations[0].recent.hours = [0, 1, 2, 3, 4].map(i => ({at: new Date(ctx.now.getTime() - (5 - i) * 3600000).toISOString(), waveFt: i === 2 ? null : i + 2}));
  const gap = chart(render(b, 'waveFt', 7));
  const path = gap.match(/<path d="([^"]*)"/)[1];
  assert.equal((path.match(/M/g) ?? []).length, 2, 'null sample splits the path');
  const hostilePath = chart(render(b, 'waveFt', 7, hostile)).match(/<path d="([^"]*)"/)[1];
  assert.equal(hostilePath, path);
});
