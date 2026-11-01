// SC2007-02: a failed protected-area read offers "Try again" in the legend's
// Protected areas row, and pressing it reloads the region's boundaries
// (web/map/chart.ts retryMpas, web/map/mpa.ts TRANSIENT_DETAILS,
// web/app/Legend.tsx MpaRow). Offline: the region files are the committed
// dist/ copies, the Chart's map library never loads (the boundaries load
// with the region, whatever the map does), and the .tsx row is bundled with
// esbuild so the row, the Chart and the signals share one module graph.
import assert from 'node:assert/strict';
import {existsSync, readFileSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';

const ROOT = new URL('..', import.meta.url).pathname;
const PAGE = 'https://s.test/map';
const SNAPSHOT = '/data/protected-areas.geojson', PACKAGE = '/regions/morro-bay/region.json';
const settle = async () => { for (let i = 0; i < 8; i++) await new Promise(resolve => setTimeout(resolve, 0)); };
const notFound = {ok: false, status: 503, json: async () => ({})};
const serveDist = path => {
  const file = new URL(`../dist${path}`, import.meta.url);
  return existsSync(file) ? {ok: true, json: async () => JSON.parse(readFileSync(file, 'utf8'))} : {ok: false, status: 404, json: async () => ({})};
};
const TRY = />Try again<\/button>/;

let ui;
async function components() {
  if (ui) return ui;
  const out = join(await mkdtemp(join(tmpdir(), 'mpa-retry-')), 'mpa-retry.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {MpaRow} from './web/app/Legend.tsx';
      export {TRANSIENT_DETAILS, mpaState} from './web/map/mpa.ts';
      export {createChart, unavailable} from './web/map/chart.ts';
      export * as state from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins,
  });
  return (ui = await import(pathToFileURL(out).href));
}

/** A Chart for `region`: paths in `net.down` fail, a `net.hold` answer is used once, the rest are the committed files; `reads(path)` counts requests. */
async function openChart(region, {down = [], hold = {}} = {}) {
  const m = await components(), href = `${PAGE}?region=${region}&layers=none`, seen = [], net = {down: new Set(down), hold: new Map(Object.entries(hold))};
  globalThis.location = {href};
  globalThis.history = {state: null, pushState(_s, _t, url) { location.href = url; }, replaceState(_s, _t, url) { location.href = url; }};
  globalThis.dispatchEvent = () => true;
  m.state.configureStore({v2: true, storage: null});
  m.state.syncFromURL(href);
  const fetchFn = async url => {
    const path = new URL(url).pathname, held = net.hold.get(path);
    seen.push(path);
    if (net.down.has(path) || path.includes('/feeds/')) return notFound;
    if (held) { net.hold.delete(path); return held; }
    return serveDist(path);
  };
  const chart = m.createChart({host: {dataset: {}}, load: () => new Promise(() => {}), page: () => href, viewDelay: 0, fetchFn});
  // The row's Try again, as MpaRow returns it (null when the row has none).
  const find = v => (!v || typeof v !== 'object' ? null : Array.isArray(v) ? v.map(find).find(Boolean) ?? null : v.props?.children === 'Try again' ? v : find(v.props?.children));
  return {m, net, chart, reads: path => seen.filter(p => p === path).length, row: () => m.render(m.h(m.MpaRow, {})), retry: () => find(m.MpaRow())};
}

for (const [name, path, detail] of [['snapshot', SNAPSHOT, 'snapshot'], ['region package', PACKAGE, 'region']]) {
  test(`a failed ${name} read shows Try again; pressing it with a good read draws the boundaries`, async t => {
    t.mock.method(console, 'warn', () => {});
    const {m, net, chart, reads, row, retry} = await openChart('morro-bay', {down: [path]});
    try {
      await settle();
      assert.equal(m.mpaState.value.status, 'unavailable');
      assert.equal(m.mpaState.value.detail, m.TRANSIENT_DETAILS[detail]);
      assert.ok(m.unavailable.value.includes('mpas'));
      assert.match(row(), /<p class="app-mpa-note">Boundaries did not load[^<]*<\/p><button[^>]*>Try again<\/button>/, 'the button follows the note');
      const before = reads(path);
      net.down.delete(path);
      retry().props.onClick();
      await settle();
      assert.equal(m.mpaState.value.status, 'complete');
      assert.ok(!m.unavailable.value.includes('mpas'), 'the layer is no longer named unavailable');
      assert.doesNotMatch(row(), TRY);
      assert.ok(reads(path) > before, 'the retry asked the network again');
    } finally { chart.destroy(); }
  });
}

test('a region that names no boundary snapshot gets no Try again', async t => {
  t.mock.method(console, 'warn', () => {});
  const config = JSON.parse(readFileSync(new URL(`../dist${PACKAGE}`, import.meta.url), 'utf8'));
  const foreign = {ok: true, json: async () => ({...config, assets: {...config.assets, protected_areas: 'https://evil.test/mpa.geojson'}})};
  const {m, chart, row, retry} = await openChart('morro-bay', {hold: {[PACKAGE]: foreign}});
  try {
    await settle();
    assert.equal(m.mpaState.value.detail, 'This region names no boundary snapshot.');
    assert.match(row(), /data-mpa="unavailable"/);
    assert.doesNotMatch(row(), TRY);
    assert.equal(retry(), null);
  } finally { chart.destroy(); }
});

test('a retry that fails again stays unavailable and offers Try again again; one press is one snapshot request', async t => {
  t.mock.method(console, 'warn', () => {});
  const {m, chart, reads, row, retry} = await openChart('morro-bay', {down: [SNAPSHOT]});
  try {
    await settle();
    const before = reads(SNAPSHOT);
    retry().props.onClick();
    await settle();
    assert.equal(m.mpaState.value.status, 'unavailable');
    assert.equal(m.mpaState.value.detail, m.TRANSIENT_DETAILS.snapshot);
    assert.ok(m.unavailable.value.includes('mpas'));
    assert.match(row(), TRY);
    assert.equal(reads(SNAPSHOT), before + 1, 'the first read and exactly one retry read');
  } finally { chart.destroy(); }
});

test('while the retry loads there is no button, and a region change meanwhile wins over the stale result', async t => {
  t.mock.method(console, 'warn', () => {});
  let release;
  const {m, net, chart, reads, row, retry} = await openChart('morro-bay', {down: [SNAPSHOT]});
  try {
    await settle();
    net.down.delete(SNAPSHOT);
    net.hold.set(SNAPSHOT, new Promise(resolve => { release = resolve; }));
    const before = reads(SNAPSHOT);
    retry().props.onClick();
    await settle();
    assert.equal(m.mpaState.value.status, 'loading');
    assert.match(row(), /<p class="app-mpa-note">Loading boundaries\.<\/p>/);
    assert.equal(retry(), null, 'one request at a time: no button to tap twice');
    assert.equal(reads(SNAPSHOT), before + 1);
    m.state.setParams({region: 'southern-california'});
    await settle();
    const southern = m.mpaState.value;
    assert.ok(southern.status === 'complete' || southern.status === 'partial', southern.status);
    release(serveDist(SNAPSHOT));
    await settle();
    assert.equal(m.mpaState.value, southern, 'the stale morro-bay result is ignored');
  } finally { chart.destroy(); }
});

test('a good first load never shows Try again', async t => {
  t.mock.method(console, 'warn', () => {});
  const {m, chart, row, retry} = await openChart('morro-bay');
  try {
    assert.doesNotMatch(row(), TRY, 'not while loading');
    await settle();
    assert.equal(m.mpaState.value.status, 'complete');
    assert.doesNotMatch(row(), TRY);
    assert.equal(retry(), null);
  } finally { chart.destroy(); }
});
