// SC1352-12: chart-pack Delete reports a refused delete, re-reads the list either way, and is off during a save.
// Whole Trip.tsx module, deterministic hooks, installed SSR; synthetic storage only (no browser, cache, network).
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, readFile} from 'node:fs/promises';
import {resolve, join} from 'node:path';
import {tmpdir} from 'node:os';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {preparedCatalogue} from './helpers/esbuild-url.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const inventory = resolve(root, 'tests/fixtures/sp1502_pack_inventory');
const fixtures = resolve(root, 'tests/fixtures/chart_pack_delete');
const packs = JSON.parse(await readFile(resolve(inventory, 'packs.json'), 'utf8'));
const DELETED = 'Saved region deleted.';
const FAILED = 'Saved region could not be deleted. Offline storage may be unavailable.';
const UNKNOWN = 'Saved regions could not be checked. Offline storage may be unavailable.';
const STALE = 'Last checked listing; not rechecked.';
const EMPTY = 'Nothing saved on this device yet.';
const DELETE_HARBOR = 'Delete the saved Fixture Harbor';
const SAVE = 'Save Fixture Harbor for offline';
const success = value => () => Promise.resolve(structuredClone(value));
const rejected = () => Promise.reject(new Error('synthetic enumeration unavailable'));
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}

async function harness(t, responses) {
  const descriptors = new Map(), blocked = [], unhandled = [];
  const onUnhandled = reason => unhandled.push(reason);
  process.on('unhandledRejection', onUnhandled);
  const forbid = label => () => { blocked.push(label); throw new Error(`offline sentinel: ${label}`); };
  for (const [key, value] of Object.entries({
    fetch: forbid('fetch'), localStorage: new Proxy({}, {get: forbid('localStorage')}),
    indexedDB: new Proxy({}, {get: forbid('indexedDB')}), navigator: {onLine: true, serviceWorker: {register: forbid('service worker')}},
    caches: {keys: forbid('live caches.keys'), open: forbid('live caches.open'), delete: forbid('unexpected caches.delete')},
  })) {
    descriptors.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
    Object.defineProperty(globalThis, key, {value, configurable: true, writable: true});
  }
  let m;
  t.after(() => {
    m?.cleanup();
    process.off('unhandledRejection', onUnhandled);
    for (const [key, descriptor] of descriptors) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else delete globalThis[key];
    }
    assert.deepEqual(blocked, [], 'no live/network/store access');
  });
  const dir = await mkdtemp(join(tmpdir(), 'chart-pack-delete-'));
  const trip = resolve(root, 'web/app/Trip.tsx');
  const result = await build({
    entryPoints: [resolve(inventory, 'entry.mjs')], outfile: resolve(dir, 'trip.mjs'),
    bundle: true, format: 'esm', platform: 'node', jsx: 'automatic', jsxImportSource: 'preact', logLevel: 'silent', metafile: true,
    plugins: [preparedCatalogue, {name: 'chart-pack-delete-boundary', setup(b) {
      b.onResolve({filter: /.*/}, args => {
        if (args.importer !== trip) return;
        if (args.path === 'preact/hooks') return {path: resolve(inventory, 'runtime.mjs')};
        if (['../ui/Button.tsx', '../ui/scroll-cue.ts', '../landing/PortInput.tsx', '../state.ts', '../trip.ts', '../trip-ocean-lines.ts', '../trip-forecast-end.ts', './App.tsx', './PositionCheck.tsx'].includes(args.path))
          return {path: resolve(fixtures, 'boundary.mjs')};
        if (['../../dist/offline-core.js', 'preact/jsx-runtime', '../i18n.ts', '../brief/remaining-copy.ts'].includes(args.path)) return;   // SC0707-10: the real catalogue reader, nothing else
        throw new Error(`unadmitted product import: ${args.path}`);
      });
    }}],
  });
  for (const input of Object.keys(result.metafile.inputs)) {
    const path = resolve(root, input);
    assert.ok(path === trip || path === resolve(root, 'dist/offline-core.js') || path === resolve(root, 'web/i18n.ts') || path === resolve(root, 'web/brief/remaining-copy.ts') || path === resolve(root, 'web/i18n-core.ts') || path === resolve(root, 'web/i18n-catalogue.ts') || path === resolve(root, 'web/strings.en.generated.json') || path === resolve(root, 'web/strings.es.generated.json') || path.startsWith(inventory + '/') || path.startsWith(fixtures + '/') ||
      /[/]node_modules[/](?:.*[/])?(?:@?preact|preact-render-to-string|signals-core|signals)[/]/.test(path), `unadmitted import graph input: ${input}`);
  }
  m = await import(pathToFileURL(resolve(dir, 'trip.mjs')).href);
  m.reset(responses);
  m.runtime.saveGate = null;
  const deletes = [];
  globalThis.caches.delete = async cache => { deletes.push(cache); return true; };
  const render = () => {
    m.runtime.cursor = 0;
    m.runtime.actions.clear();
    const html = m.render(m.h(m.Trip));
    for (const effect of m.runtime.effects.splice(0)) effect();
    return html.match(/<section[^>]*aria-labelledby="app-offline-pack"[\s\S]*?<\/section>/)?.[0] ?? assert.fail('ChartPack section missing');
  };
  const settle = async () => { for (let i = 0; i < 16; i++) await Promise.resolve(); return render(); };
  const action = key => { const call = m.runtime.actions.get(key); assert.equal(typeof call, 'function', `action ${key}`); return call; };
  render();
  await settle();
  return {render, settle, action, runtime: m.runtime, deletes, unhandled};
}

const status = html => html.match(/<p role="status" aria-live="polite">([^<]*)<\/p>/)?.[1];
const deleteButton = (html, region) => html.match(new RegExp(`<button[^>]*aria-label="Delete the saved ${region}"[^>]*>`))?.[0] ?? assert.fail(`Delete button for ${region}`);
const isDisabled = tag => /\sdisabled(?:[\s=>])/.test(tag);

test('chart_pack_delete_success_waits_and_refreshes', async t => {
  const h = await harness(t, [success(packs), success([packs[1]])]);
  assert.equal(h.runtime.calls, 1);
  const gate = deferred();
  globalThis.caches.delete = cache => { h.deletes.push(cache); return gate.promise; };
  h.action(DELETE_HARBOR)();
  const pending = await h.settle();
  assert.notEqual(status(pending), DELETED, 'no success before caches.delete resolves');
  assert.equal(h.runtime.calls, 1, 'no re-read before the delete settles');
  gate.resolve(true);
  const html = await h.settle();
  assert.equal(status(html), DELETED);
  assert.deepEqual(h.deletes, [packs[0].cache]);
  assert.equal(h.runtime.calls, 2);
  assert.ok(!html.includes('<strong>Fixture Harbor</strong>') && html.includes('<strong>Fixture Bay</strong>'), 'the list is the re-read one');
  assert.deepEqual(h.unhandled, []);
});

test('chart_pack_delete_resolved_false_is_an_idempotent_success_and_refreshes', async t => {
  const h = await harness(t, [success(packs), success([packs[1]])]);
  globalThis.caches.delete = async cache => { h.deletes.push(cache); return false; };
  h.action(DELETE_HARBOR)();
  const html = await h.settle();
  assert.equal(status(html), DELETED);
  assert.equal(h.runtime.calls, 2);
  assert.ok(!html.includes(FAILED));
});

test('chart_pack_delete_rejection_reports_and_refreshes', async t => {
  for (const failing of [async () => { throw new Error('synthetic delete refused'); }, () => { throw new Error('synthetic sync refusal'); }]) {
    const h = await harness(t, [success(packs), success(packs)]);
    globalThis.caches.delete = failing;
    h.action(DELETE_HARBOR)();
    const html = await h.settle();
    assert.equal(status(html), FAILED);
    assert.ok(!html.includes(DELETED) && !html.includes('synthetic'), 'no success wording or raw exception text');
    assert.equal(h.runtime.calls, 2, 'exactly one re-read after the failure');
    assert.ok(html.includes('<strong>Fixture Harbor</strong>') && html.includes('<strong>Fixture Bay</strong>'), 'rows the re-read returns stay');
    assert.deepEqual(h.unhandled, []);
  }
});

test('chart_pack_delete_and_refresh_both_reject', async t => {
  const h = await harness(t, [success(packs), rejected]);
  globalThis.caches.delete = async () => { throw new Error('synthetic delete refused'); };
  h.action(DELETE_HARBOR)();
  const html = await h.settle();
  assert.equal(status(html), FAILED);
  assert.ok(html.includes(UNKNOWN) && html.includes(STALE), 'the list says it was not rechecked');
  assert.ok(html.includes('<strong>Fixture Harbor</strong>') && !html.includes(EMPTY) && !html.includes(DELETED));
  assert.deepEqual(h.unhandled, []);
});

test('chart_pack_delete_disabled_during_save', async t => {
  for (const outcome of ['resolve', 'reject']) {
    const h = await harness(t, [success(packs), success(packs), success([packs[1]])]);
    h.runtime.saveGate = deferred();
    h.action(SAVE)();
    const busy = await h.settle();
    assert.equal(h.runtime.saves, 1);
    for (const region of ['Fixture Harbor', 'Fixture Bay']) assert.ok(isDisabled(deleteButton(busy, region)), `${region} Delete disabled while saving`);
    const before = status(busy);
    h.action(DELETE_HARBOR)();   // a callback captured from the busy render
    const after = await h.settle();
    assert.deepEqual(h.deletes, [], 'caches.delete untouched while a save runs');
    assert.equal(status(after), before);
    assert.equal(h.runtime.calls, 1, 'a refused delete does not re-read');
    if (outcome === 'resolve') h.runtime.saveGate.resolve(); else h.runtime.saveGate.reject(new Error('synthetic save failure'));
    h.runtime.saveGate = null;
    const idle = await h.settle();
    assert.ok(status(idle).startsWith(outcome === 'resolve' ? 'Saved Fixture Harbor' : 'Could not save: synthetic save failure'), status(idle));
    for (const region of ['Fixture Harbor', 'Fixture Bay']) assert.ok(!isDisabled(deleteButton(idle, region)), `${region} Delete enabled after the save`);
    h.action(DELETE_HARBOR)();
    const done = await h.settle();
    assert.equal(status(done), DELETED);
    assert.deepEqual(h.deletes, [packs[0].cache]);
  }
});

test('chart_pack_delete_cancelled_save_re_enables_delete_and_keeps_cancel_wording', async t => {
  const h = await harness(t, [success(packs), success(packs)]);
  h.runtime.saveGate = deferred();
  h.action(SAVE)();
  const busy = await h.settle();
  assert.ok(isDisabled(deleteButton(busy, 'Fixture Harbor')));
  h.action('Cancel')();
  const idle = await h.settle();
  assert.equal(status(idle), 'Cancelled. Nothing new was saved.');
  assert.ok(!isDisabled(deleteButton(idle, 'Fixture Harbor')));
});
