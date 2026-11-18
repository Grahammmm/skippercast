// SCA-606 / F13-06: closing the offline sheet during a delayed chart-pack save must not leave a false idle state.
// Required suite: node --test tests/test_f13_06_audit.mjs
// Read-only contract replay: node tests/test_f13_06_audit.mjs --audit
// The replay runs the real web/app/Trip.tsx through the same observer and must fail on an affected baseline
// (ChartPack keeps the AbortController in component state, so Close drops the only Cancel control while the save runs)
// and pass once the save is owned outside the dialog (controls reattach) or aborted on close with visible feedback.
// Required suite = synthetic controls only: a store-owned model and an abort-on-close model must pass, and a
// local-state model (the cited gap) must be detected. Synthetic data, no browser, cache, storage or network.
import assert from 'node:assert/strict';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {after, before, test} from 'node:test';
import {build} from 'esbuild';
import {preparedCatalogue} from './helpers/esbuild-url.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const inventory = resolve(root, 'tests/fixtures/sp1502_pack_inventory');
const fixtures = resolve(root, 'tests/fixtures/chart_pack_delete');
const SAVE = 'Save Fixture Harbor for offline', CANCELLED = 'Cancelled. Nothing new was saved.';
const deferred = () => { let resolve; const promise = new Promise(yes => { resolve = yes; }); return {promise, resolve}; };

// What a boater can see after close + reopen while the delayed save is (or is not) still running.
// Verdict: "ok" when the save is still active and exactly one Cancel is offered with Save held off, or when it was
// aborted and the sheet says so; "false-idle" when the save is active but the sheet offers Save and no Cancel.
function verdict({active, view}) {
  if (active) return view.cancels === 1 && !view.saveEnabled ? 'ok' : (view.cancels === 0 && view.saveEnabled ? 'false-idle' : 'inconsistent');
  return view.status === CANCELLED && view.cancels === 0 ? 'ok' : 'silent-abort';
}
async function scenario(driver) {
  await driver.start();
  const before = {active: driver.active(), view: await driver.view()};
  assert.deepEqual([before.active, before.view.cancels, before.view.saveEnabled], [true, 1, false], 'control: a save in progress offers Cancel and holds Save');
  await driver.close();
  await driver.reopen();
  const observed = {active: driver.active(), view: await driver.view()};
  await driver.finish();
  return {...observed, verdict: verdict(observed)};
}

// Synthetic models: same interface as the real-component driver below.
function model(kind) {
  const state = {controller: null, local: null, status: ''};
  const owned = kind !== 'local-state';
  return {
    async start() { state.controller = new AbortController(); state.local = state.controller; },
    async close() {
      if (!owned) state.local = null;                              // the dialog's state dies with it
      if (kind === 'abort-on-close') { state.controller.abort(); state.status = CANCELLED; }
    },
    async reopen() {},
    active: () => !!state.controller && !state.controller.signal.aborted,
    async view() {
      const shown = owned ? state.controller : state.local, running = !!shown && !shown.signal.aborted;
      return {cancels: running ? 1 : 0, saveEnabled: !running, status: owned ? state.status : ''};
    },
    async finish() { state.controller?.abort(); },
  };
}

test('valid control: save owned outside the dialog reattaches Cancel after reopen', async () => {
  const result = await scenario(model('store-owned'));
  assert.equal(result.verdict, 'ok');
  assert.equal(result.active, true);
});
test('valid control: abort on close says so on reopen', async () => {
  const result = await scenario(model('abort-on-close'));
  assert.equal(result.verdict, 'ok');
  assert.equal(result.active, false);
});
test('negative control: local dialog state is detected as a false idle sheet over a live save', async () => {
  const result = await scenario(model('local-state'));
  assert.equal(result.verdict, 'false-idle');
  assert.deepEqual([result.active, result.view.cancels, result.view.saveEnabled], [true, 0, true]);
});

if (process.argv.includes('--audit')) {
  let m, dir, controllers, saved = {};
  const forbid = label => () => { throw new Error(`offline sentinel: ${label}`); };
  before(async () => {
    for (const [key, value] of Object.entries({fetch: forbid('fetch'), navigator: {onLine: true}, caches: {keys: forbid('caches.keys'), open: forbid('caches.open'), delete: forbid('caches.delete')}})) {
      saved[key] = Object.getOwnPropertyDescriptor(globalThis, key);
      Object.defineProperty(globalThis, key, {value, configurable: true, writable: true});
    }
    const RealController = AbortController;
    controllers = [];
    saved.AbortController = Object.getOwnPropertyDescriptor(globalThis, 'AbortController');
    globalThis.AbortController = class extends RealController { constructor() { super(); controllers.push(this); } };
    dir = await mkdtemp(join(tmpdir(), 'f13-06-'));
    const trip = resolve(root, 'web/app/Trip.tsx');
    await build({
      entryPoints: [resolve(inventory, 'entry.mjs')], outfile: resolve(dir, 'trip.mjs'),
      bundle: true, format: 'esm', platform: 'node', jsx: 'automatic', jsxImportSource: 'preact', logLevel: 'silent',
      plugins: [preparedCatalogue, {name: 'f13-06-boundary', setup(b) {
        b.onResolve({filter: /.*/}, args => {
          if (args.importer !== trip) return;
          if (args.path === 'preact/hooks') return {path: resolve(inventory, 'runtime.mjs')};
          if (['../ui/Button.tsx', '../ui/scroll-cue.ts', '../landing/PortInput.tsx', '../state.ts', '../trip.ts', '../trip-ocean-lines.ts', '../trip-forecast-end.ts', './App.tsx', './PositionCheck.tsx'].includes(args.path))
            return {path: resolve(fixtures, 'boundary.mjs')};
          if (['../../dist/offline-core.js', 'preact/jsx-runtime', '../i18n.ts', '../size-text.ts', '../brief/remaining-copy.ts', '../ui/focus-return.ts'].includes(args.path)) return;
          throw new Error(`unadmitted product import: ${args.path}`);
        });
      }}],
    });
    m = await import(pathToFileURL(resolve(dir, 'trip.mjs')).href);
  });
  after(async () => {
    m?.cleanup();
    for (const [key, d] of Object.entries(saved)) { if (d) Object.defineProperty(globalThis, key, d); else delete globalThis[key]; }
    if (dir) await rm(dir, {recursive: true, force: true});
  });

  function real() {
    const gate = deferred();
    const render = () => {
      m.runtime.cursor = 0; m.runtime.actions.clear();
      const html = m.render(m.h(m.Trip));
      for (const effect of m.runtime.effects.splice(0)) effect();
      return html.match(/<section[^>]*aria-labelledby="app-offline-pack"[\s\S]*?<\/section>/)?.[0] ?? assert.fail('ChartPack section missing');
    };
    const settle = async () => { for (let i = 0; i < 16; i++) await Promise.resolve(); return render(); };
    let live;
    return {
      async start() {
        controllers.length = 0;
        m.reset(Array.from({length: 8}, () => () => Promise.resolve([])));
        m.runtime.saveGate = gate;
        render(); await settle();
        m.runtime.actions.get(SAVE)();
        await settle();
        live = controllers.at(-1);
      },
      async close() { m.cleanup(); m.runtime.slots = []; m.runtime.actions.clear(); },   // unmount: state and effects go, the save promise stays
      async reopen() { m.runtime.cursor = 0; render(); },
      active: () => m.runtime.saves === 1 && !!live && !live.signal.aborted,
      async view() {
        const html = await settle();
        return {
          cancels: (html.match(/<button[^>]*>Cancel<\/button>/g) ?? []).length,
          saveEnabled: !/<button[^>]*\sdisabled[^>]*>Save Fixture Harbor for offline<\/button>/.test(html) && html.includes('>Save Fixture Harbor for offline</button>'),
          status: html.match(/<p role="status" aria-live="polite">([^<]*)<\/p>/)?.[1] ?? '',
        };
      },
      async finish() { live.abort(); gate.resolve(); m.cleanup(); m.runtime.slots = []; },
    };
  }

  test('baseline replay: real Trip.tsx after close and reopen has one Cancel over a live save, or a stated cancellation', async () => {
    const result = await scenario(real());
    assert.equal(result.verdict, 'ok', `close + reopen during a delayed save looked like "${result.verdict}": ${JSON.stringify(result)}`);
  });
}
