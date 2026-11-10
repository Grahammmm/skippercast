// RF0804-7: a position check belongs to the region and open-dialog lifetime that asked for it. The real PositionCheck component is
// bundled with deterministic hooks and a deferred check, so no geolocation, network or storage is touched.
import assert from 'node:assert/strict';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import test from 'node:test';
import {build} from 'esbuild';

const runtime = new URL('./fixtures/position_check_lifecycle/runtime.mjs', import.meta.url).pathname;
const root = new URL('..', import.meta.url).pathname;
const outfile = join(await mkdtemp(join(tmpdir(), 'position-lifecycle-')), 'bundle.mjs');
const FAKE = new Set(['preact/hooks', '../state.ts', '../trip.ts', '../i18n.ts', '../position-check.ts', './PositionView.tsx']);
await build({
  stdin: {resolveDir: root, loader: 'ts', contents: `export {PositionCheck} from './web/app/PositionCheck.tsx'; export {rt, reset, unmount} from '${runtime}';`},
  bundle: true, format: 'esm', platform: 'node', outfile, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
  plugins: [{name: 'boundaries', setup(b) { b.onResolve({filter: /.*/}, a => a.importer.endsWith('/web/app/PositionCheck.tsx') && FAKE.has(a.path) ? {path: runtime} : null); }}],
});
const m = await import(pathToFileURL(outfile));
const flush = () => { for (const e of m.rt.effects.splice(0)) e(); };
const frame = () => { m.rt.cursor = 0; return m.PositionCheck().props; };
const render = () => { const p = frame(); flush(); return p; };
const settle = async () => { for (let i = 0; i < 4; i++) await Promise.resolve(); };
const result = {located: {ok: true, fix: {latitude: 35.1, longitude: -121.1, accuracyM: 8}}, reading: {kind: 'checked', where: 'inside', name: 'Synthetic A reserve'}};
const B = 'cambria-san-simeon';
const start = () => { m.reset(); render(); render().onCheck(); };

test('completed_reading_is_hidden_on_first_render_of_new_region', async () => {
  start(); m.rt.calls[0](result); await settle();
  assert.equal(render().state.phase, 'done');
  m.rt.region.value = B;
  assert.equal(frame().state.phase, 'idle', 'first render of B shows nothing from A');
  flush();
  assert.equal(render().state.phase, 'idle');
  assert.equal(m.rt.calls.length, 1, 'no implicit second read');
});

test('pending_reading_cannot_publish_after_region_change', async () => {
  start(); m.rt.region.value = B; render();
  m.rt.calls[0](result); await settle();
  assert.equal(render().state.phase, 'idle');
  render().onCheck(); m.rt.calls[1](result); await settle();
  assert.equal(render().state.phase, 'done', 'an explicit tap in B still works');
  // A -> B -> A must not revive A's first request.
  start(); m.rt.region.value = B; render(); m.rt.region.value = 'morro-bay'; render();
  m.rt.calls[0](result); await settle();
  assert.equal(render().state.phase, 'idle');
  // Completion before the passive effects of the region change run.
  start(); m.rt.region.value = B; frame();
  m.rt.calls[0](result); await settle(); flush();
  assert.equal(render().state.phase, 'idle');
});

test('close_reopen_and_unmount_invalidate_pending_position', async () => {
  start(); m.rt.open.value = false; render();
  m.rt.calls[0](result); await settle();
  m.rt.open.value = true;
  assert.equal(render().state.phase, 'idle', 'reopening is idle until tapped');
  assert.equal(m.rt.calls.length, 1);
  start(); m.rt.calls[0](result); await settle();
  m.rt.open.value = false; render(); m.rt.open.value = true;
  assert.equal(render().state.phase, 'idle');
  start(); m.unmount(); m.rt.calls[0](result); await settle();
  assert.equal(frame().state.phase, 'reading', 'nothing published after unmount');
  assert.equal(m.rt.calls.length, 1);
});

test('same_region_rerender_does_not_restart_or_clear_check', async () => {
  start(); m.rt.calls[0](result); await settle();
  assert.equal(render().state.phase, 'done');
  const lists = m.rt.lists;
  m.rt.region.value = 'morro-bay';
  assert.equal(render().state.phase, 'done');
  assert.equal(m.rt.calls.length, 1);
  assert.equal(m.rt.lists, lists, 'no extra pack read');
});
