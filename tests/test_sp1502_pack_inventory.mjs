// SP-15-v1 A1–A4. Whole Trip.tsx module, deterministic hooks, installed SSR.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, readFile, mkdir} from 'node:fs/promises';
import {resolve, dirname, relative, join} from 'node:path';
import {tmpdir} from 'node:os';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {preparedCatalogue} from './helpers/esbuild-url.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const fixtures = resolve(root, 'tests/fixtures/sp1502_pack_inventory');
const packs = JSON.parse(await readFile(resolve(fixtures, 'packs.json'), 'utf8'));
const extraTest = process.env.SP1502_BASELINE_PAIR === '1' ? () => {} : test;
const EMPTY = 'Nothing saved on this device yet.';
const UNKNOWN = 'Saved regions could not be checked. Offline storage may be unavailable.';
const STALE = 'Last checked listing; not rechecked.';
const success = value => () => Promise.resolve(structuredClone(value));
const rejected = () => Promise.reject(new Error('synthetic enumeration unavailable'));
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}

async function harness(t, responses) {
  const descriptors = new Map();
  const blocked = [];
  const forbid = label => () => { blocked.push(label); throw new Error(`offline sentinel: ${label}`); };
  for (const [key, value] of Object.entries({
    fetch: forbid('network/model fetch'), WebSocket: forbid('WebSocket'), XMLHttpRequest: forbid('XMLHttpRequest'),
    localStorage: new Proxy({}, {get: forbid('localStorage')}), sessionStorage: new Proxy({}, {get: forbid('sessionStorage')}),
    indexedDB: new Proxy({}, {get: forbid('indexedDB')}), navigator: {onLine: true, serviceWorker: {register: forbid('service worker')}},
    caches: {keys: forbid('live caches.keys'), open: forbid('live caches.open'), delete: forbid('unexpected caches.delete')},
  })) {
    descriptors.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
    Object.defineProperty(globalThis, key, {value, configurable: true, writable: true});
  }
  let m;
  t.after(() => {
    m?.cleanup();
    for (const [key, descriptor] of descriptors) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else delete globalThis[key];
    }
    assert.deepEqual(blocked, [], 'no live/network/model/store access');
  });
  // Ordinary discovery uses the inherited temporary root, not a checkout sibling.
  let dir;
  if (process.env.SP1502_TEST_OUTPUT) {
    const candidateOut = resolve(root, '../out');
    const output = resolve(process.env.SP1502_TEST_OUTPUT);
    assert.ok(relative(candidateOut, output) !== '..' && !relative(candidateOut, output).startsWith('../'), 'candidate-local test output');
    await mkdir(output, {recursive: true});
    dir = await mkdtemp(resolve(output, 'ssr-'));
  } else {
    dir = await mkdtemp(join(tmpdir(), 'sp1502-pack-inventory-'));
  }
  const result = await build({
    entryPoints: [resolve(fixtures, 'entry.mjs')], outfile: resolve(dir, 'trip.mjs'),
    bundle: true, format: 'esm', platform: 'node', jsx: 'automatic', jsxImportSource: 'preact',
    logLevel: 'silent', metafile: true,
    plugins: [{name: 'inventory-offline-boundary', setup(b) {
      b.onResolve({filter: /.*/}, args => {
        if (args.importer !== resolve(root, 'web/app/Trip.tsx')) return;
        if (args.path === 'preact/hooks') return {path: resolve(fixtures, 'runtime.mjs')};
        if (['../ui/Button.tsx', '../ui/scroll-cue.ts', '../landing/PortInput.tsx', '../state.ts', '../trip.ts', '../trip-ocean-lines.ts', '../trip-forecast-end.ts', './App.tsx', './PositionCheck.tsx'].includes(args.path))
          return {path: resolve(fixtures, 'boundary.mjs')};
        if (['../../dist/offline-core.js', 'preact/jsx-runtime', '../i18n.ts', '../brief/remaining-copy.ts', '../ui/focus-return.ts'].includes(args.path)) return;   // SC0707-10: the real catalogue reader, nothing else
        throw new Error(`unadmitted product import: ${args.path}`);
      });
    }}, preparedCatalogue],
  });
  for (const input of Object.keys(result.metafile.inputs)) {
    const path = resolve(root, input);
    assert.ok(path === resolve(root, 'web/app/Trip.tsx') || path === resolve(root, 'dist/offline-core.js') || path === resolve(root, 'web/i18n.ts') || path === resolve(root, 'web/brief/remaining-copy.ts') || path === resolve(root, 'web/i18n-core.ts') || path === resolve(root, 'web/ui/focus-return.ts') || path === resolve(root, 'web/i18n-catalogue.ts') || path === resolve(root, 'web/strings.en.generated.json') || path === resolve(root, 'web/strings.es.generated.json') ||
      path.startsWith(fixtures + '/') || /[/]node_modules[/](?:.*[/])?(?:@?preact|preact-render-to-string|signals-core|signals)[/]/.test(path),
    `unadmitted import graph input: ${input}`);
  }
  m = await import(pathToFileURL(resolve(dir, 'trip.mjs')).href);
  m.reset(responses);
  globalThis.caches.delete = async cache => { m.runtime.deletes.push(cache); return true; };
  const render = () => {
    m.runtime.cursor = 0;
    m.runtime.actions.clear();
    const html = m.render(m.h(m.Trip));
    for (const effect of m.runtime.effects.splice(0)) effect();
    return html.match(/<section[^>]*aria-labelledby="app-offline-pack"[\s\S]*?<\/section>/)?.[0] ?? assert.fail('ChartPack section missing');
  };
  const settle = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); return render(); };
  const action = key => { const call = m.runtime.actions.get(key); assert.equal(typeof call, 'function', `action ${key}`); return call; };
  const refresh = async () => { action('Save Fixture Harbor for offline')(); return settle(); };
  return {render, settle, refresh, action, runtime: m.runtime};
}

test('legal checklist renders missing files, dates, stale warning and source links offline', async t => {
  const sample = structuredClone(packs);
  sample[0].meta.legal = {complete: false, stale: true, items: [
    {id: 'rules', saved: true, saved_at: '2026-11-07T10:00:00Z', generated_at: null, reviewed_at: '2026-10-01', valid_from: '2026-01-01', valid_through: '2026-12-31', sources: ['https://wildlife.ca.gov/Fishing/Ocean']},
    {id: 'additional-closures', saved: false, sources: []},
  ]};
  const h = await harness(t, [success(sample)]);
  h.render();
  const html = await h.settle();
  assert.match(html, /Legal files missing/);
  assert.match(html, /<summary>[^<]*Stale or unknown dates/);
  assert.match(html, /Additional closures: Missing or unreadable/);
  assert.match(html, /2026-01-01 – 2026-12-31/);
  assert.match(html, /href="https:\/\/wildlife.ca.gov\/Fishing\/Ocean"/);
  assert.match(html, /NOT FOR NAVIGATION/);
});

test('primary regression', async t => {
  const h = await harness(t, [rejected]);
  h.render();
  const html = await h.settle();
  t.diagnostic(`observed initial rejected inventory: ${html}`);
  assert.ok(html.includes(UNKNOWN) && !html.includes(EMPTY), 'A1_INITIAL_REJECTION_IS_UNKNOWN_NOT_EMPTY');
  assert.equal(h.runtime.calls, 1);
});

test('healthy control', async t => {
  const h = await harness(t, [success([])]);
  assert.match(h.render(), /Checking saved regions…/);
  const html = await h.settle();
  assert.ok(html.includes(EMPTY));
  assert.ok(!html.includes(UNKNOWN));
  assert.equal(h.runtime.calls, 1);
});

extraTest('A2 nonempty producer-shaped packs render their names and metadata', async t => {
  const h = await harness(t, [success(packs)]);
  h.render();
  const html = await h.settle();
  for (const {meta} of packs) assert.ok(html.includes(`<strong>${meta.region_name}</strong>`));
  assert.match(html, /2 of 3 chart tiles · 1 of 2 base map tiles \(zoom 8–9\) · 1 item missing/);
  assert.match(html, /1 of 1 chart tiles/);
  assert.match(html, /datetime="2026-10-20T12:00:00Z"/i);
  assert.ok(!html.includes(EMPTY) && !html.includes(UNKNOWN));
});

extraTest('A3 later failure preserves rows with not-rechecked qualifier; success empty clears them', async t => {
  const h = await harness(t, [success(packs), rejected, success([])]);
  h.render(); await h.settle();
  const failed = await h.refresh();
  assert.ok(failed.includes(UNKNOWN) && failed.includes(STALE));
  for (const {meta} of packs) assert.ok(failed.includes(`<strong>${meta.region_name}</strong>`));
  assert.ok(!failed.includes(EMPTY));
  const empty = await h.refresh();
  assert.ok(empty.includes(EMPTY) && !empty.includes(UNKNOWN) && !empty.includes(STALE));
  assert.ok(!empty.includes('<strong>Fixture Harbor</strong>') && !empty.includes('<strong>Fixture Bay</strong>'));
  assert.equal(h.runtime.calls, 3);
});

extraTest('A3 previously checked empty is not asserted as currently empty after failure', async t => {
  const h = await harness(t, [success([]), rejected]);
  h.render(); await h.settle();
  const html = await h.refresh();
  assert.ok(html.includes(UNKNOWN) && html.includes(STALE) && !html.includes(EMPTY));
});

extraTest('A4 deferred initial enumeration stays loading, then reports its actual result', async t => {
  const request = deferred();
  const h = await harness(t, [() => request.promise]);
  const pending = await h.settle();
  assert.ok(pending.includes('Checking saved regions…') && !pending.includes(EMPTY) && !pending.includes(UNKNOWN));
  request.resolve(packs);
  const html = await h.settle();
  assert.ok(html.includes('<strong>Fixture Harbor</strong>') && !html.includes('Checking saved regions…'));
});

extraTest('A4 older initial success cannot replace a newer empty response', async t => {
  const old = deferred();
  const h = await harness(t, [() => old.promise, success([])]);
  h.render();
  const newest = await h.refresh();
  assert.ok(newest.includes(EMPTY));
  old.resolve(packs);
  const html = await h.settle();
  assert.ok(html.includes(EMPTY) && !html.includes('<strong>Fixture Harbor</strong>'));
});

extraTest('A4 older rejection cannot replace a newer nonempty listing', async t => {
  const old = deferred();
  const h = await harness(t, [() => old.promise, success(packs)]);
  h.render(); await h.refresh();
  old.reject(new Error('synthetic stale rejection'));
  const html = await h.settle();
  assert.ok(html.includes('<strong>Fixture Harbor</strong>') && !html.includes(UNKNOWN) && !html.includes(STALE));
});

extraTest('A4 overlapping refreshes retain rows while pending and ignore older success after newest error', async t => {
  const old = deferred(), newest = deferred();
  const h = await harness(t, [success(packs), () => old.promise, () => newest.promise]);
  h.render(); await h.settle();
  // Existing public delete callbacks trigger independent refreshes; deletion is a synthetic in-memory receipt only.
  const remove = h.action('Delete the saved Fixture Harbor');
  remove(); await h.settle(); remove();
  const pending = await h.settle();
  assert.ok(pending.includes('Checking saved regions…') && pending.includes('<strong>Fixture Harbor</strong>'));
  newest.reject(new Error('synthetic newest failure'));
  const failed = await h.settle();
  assert.ok(failed.includes(UNKNOWN) && failed.includes(STALE));
  old.resolve([]);
  const html = await h.settle();
  assert.ok(html.includes(UNKNOWN) && html.includes(STALE) && html.includes('<strong>Fixture Harbor</strong>') && !html.includes(EMPTY));
  assert.deepEqual(h.runtime.deletes, [packs[0].cache, packs[0].cache]);
});

// SC1952-03: the coverage line names the published land-water screen and contours, and a miss in either list is visible once.
const withMeta = (extra, tiles = {saved: 1, planned: 1, min_zoom: 8, max_zoom: null}) =>
  [{cache: 'skippercast-pack-fixture-harbor-20261022', meta: {...structuredClone(packs[1].meta), region_id: 'fixture-harbor', region_name: 'Fixture Harbor', tiles, ...extra}}];

extraTest('SC1952-03 the chart pack paragraph names the published land-water screen and depth contours, qualified, beside the older coverage', async t => {
  const h = await harness(t, [success([])]);
  h.render();
  const html = await h.settle();
  assert.ok(html.includes('the published land-water screen and depth contours (where the region publishes them)'));
  for (const kept of ['NOAA chart tiles', 'base map at zoom 8–12', 'Water temperature and currents are saved with the pack when current; each saved region below says what was saved. For Morro Bay and Cambria, save Coastal readings below.', 'Check the saved pack before leaving coverage.'])
    assert.ok(html.includes(kept), kept);
});

extraTest('SC1952-03 a side file missing from v2.missing is counted in the saved line, once even when the top-level list also names it', async t => {
  const url = 'https://example.test/regions/fixture-harbor/land-water.json', other = 'https://example.test/regions/fixture-harbor/depth-contours.geojson';
  for (const [meta, expected] of [
    [{missing: [], v2: {basemap: {saved: 1, planned: 1}, shell: {saved: 1, requested: 2}, missing: [url]}}, '1 item missing'],
    [{missing: ['https://example.test/other'], v2: {basemap: {saved: 1, planned: 1}, shell: {saved: 1, requested: 3}, missing: [url, other]}}, '3 items missing'],
    [{missing: [url], v2: {basemap: {saved: 1, planned: 1}, shell: {saved: 1, requested: 2}, missing: [url]}}, '1 item missing'],
    [{missing: [url], v2: {basemap: {saved: 1, planned: 1}, shell: {saved: 1, requested: 3}, missing: [url, other]}}, '2 items missing'],
    [{missing: [url, url], v2: {basemap: {saved: 1, planned: 1}, shell: {saved: 1, requested: 2}, missing: [url, url]}}, '1 item missing'],
  ]) {
    const h = await harness(t, [success(withMeta(meta))]);
    h.render();
    const html = await h.settle();
    assert.ok(html.includes(`· ${expected}`), `${expected}: ${html.match(/<span>[^<]*chart tiles[^<]*<\/span>/)?.[0]}`);
  }
});

extraTest('SC1952-03 old metadata without v2, or with v2 but no missing list, still renders; nothing missing says nothing', async t => {
  const legacy = withMeta({missing: []});
  delete legacy[0].meta.v2;
  const h = await harness(t, [success(legacy)]);
  h.render();
  const html = await h.settle();
  assert.ok(html.includes('1 of 1 chart tiles') && !html.includes('item missing') && !html.includes('items missing'));
  const noList = await harness(t, [success(withMeta({missing: [], v2: {basemap: {saved: 1, planned: 1}, shell: {saved: 1, requested: 1}}}))]);
  noList.render();
  const html2 = await noList.settle();
  assert.ok(html2.includes('1 of 1 base map tiles') && !html2.includes('item missing') && !html2.includes('items missing'));
});

extraTest('SC1952-03 the status after Save counts both lists once', async t => {
  const h = await harness(t, [success([]), success([])]);
  h.render(); await h.settle();
  h.runtime.saveMeta = {region_name: 'Fixture Harbor', bytes: 128, missing: ['https://example.test/a'], v2: {missing: ['https://example.test/a', 'https://example.test/land-water.json']}};
  const html = await h.refresh();
  assert.ok(html.includes('2 items could not be saved and will be missing offline.'), html.match(/<p role="status"[^>]*>[^<]*/g)?.join(' | '));
  h.runtime.saveMeta = {region_name: 'Fixture Harbor', bytes: 128, missing: []};
  const clean = await h.refresh();
  assert.ok(!clean.includes('could not be saved'));
});
