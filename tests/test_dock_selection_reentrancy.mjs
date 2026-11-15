// RF1045-7: a dock observer that cancels or replaces the preview while request() publishes it must not
// leave (or overwrite) a trailing timeout. The real createDockSelection factory and real @preact/signals
// effects are bundled with esbuild; the scheduler is a manual asynchronous-style queue that counts timers
// created and outstanding, because a commit count alone cannot see an orphan timer (a stale callback is a no-op).
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';

const ROOT = new URL('..', import.meta.url).pathname;
const NOW = new Date('2026-11-14T12:00:00Z');
const AT1 = Date.parse('2026-11-14T13:00:00Z'), AT2 = Date.parse('2026-11-14T14:00:00Z'), AT3 = Date.parse('2026-11-14T15:00:00Z');

let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'dock-reentrancy-')), 'm.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: "export {createDockSelection} from './web/dock-selection.ts'; export {effect, signal} from '@preact/signals';"},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent',
  });
  mod = await import(pathToFileURL(out).href);
  return mod;
}

/** A controller with a manual scheduler; `created` counts every timer ever armed, `outstanding` those not yet cancelled or fired. */
async function rig({context = () => 'ctx', settledAt = NOW.getTime()} = {}) {
  const m = await load();
  const timers = new Map(), saved = [], commits = [];
  let next = 0, created = 0;
  const c = m.createDockSelection({
    context, doc: () => null, settled: () => ({index: 0, at: settledAt}),
    schedule: run => { created++; const id = ++next; timers.set(id, run); saved.push(run); return id; },
    cancel: id => { timers.delete(id); },
    commit: (_n, _z, at) => commits.push(at),
  });
  const fire = () => { for (const [id, run] of [...timers]) { timers.delete(id); run(); } };
  return {m, c, commits, saved, fire, created: () => created, outstanding: () => timers.size};
}

/** An effect that runs `act` once, the first time the controller reports a pending preview. */
const onPendingOnce = (m, c, act) => { let done = false; return m.effect(() => { if (c.pending.value && !done) { done = true; act(); } }); };

test('final_release_during_preview_publication_arms_nothing', async () => {
  const r = await rig();
  const release = r.c.retain();
  const dispose = onPendingOnce(r.m, r.c, release);
  try {
    assert.equal(r.c.request(NOW, 'UTC', AT1), true, 'the accepted request still reports acceptance');
    assert.equal(r.c.pending.value, false);
    assert.equal(r.created(), 0, 'no timer is armed after the final release');
    assert.equal(r.outstanding(), 0);
    r.fire();
    for (const run of r.saved) run();
    assert.deepEqual(r.commits, []);
  } finally { dispose(); release(); }
});

test('cancel_during_preview_publication_stays_cancelled', async () => {
  const r = await rig();
  const release = r.c.retain();
  const dispose = onPendingOnce(r.m, r.c, () => r.c.cancel());
  try {
    assert.equal(r.c.request(NOW, 'UTC', AT1), true);
    assert.equal(r.c.pending.value, false);
    assert.equal(r.created(), 0);
    assert.equal(r.outstanding(), 0);
    dispose();
    assert.equal(r.c.request(NOW, 'UTC', AT2), true, 'a later fresh request works normally');
    assert.equal(r.created(), 1);
    assert.equal(r.outstanding(), 1);
    r.fire();
    assert.deepEqual(r.commits, [AT2]);
    assert.equal(r.c.pending.value, false);
  } finally { dispose(); release(); }
});

test('nested_request_owns_only_one_timer', async () => {
  const r = await rig();
  const release = r.c.retain();
  const dispose = onPendingOnce(r.m, r.c, () => assert.equal(r.c.request(NOW, 'UTC', AT2), true));
  try {
    assert.equal(r.c.request(NOW, 'UTC', AT1), true);
    assert.equal(r.c.pending.value, true, 'the nested preview is the live one');
    assert.equal(r.created(), 1, 'only the nested generation armed a timer');
    assert.equal(r.outstanding(), 1);
    // Cancelling afterwards removes that exact timer: the outer call did not overwrite its handle.
    r.c.cancel();
    assert.equal(r.outstanding(), 0);
    for (const run of r.saved) run();
    assert.deepEqual(r.commits, [], 'an obsolete callback commits nothing');
    // Without the cancel, the nested timer settles once, on the nested hour.
    assert.equal(r.c.request(NOW, 'UTC', AT3), true);
    r.fire();
    assert.deepEqual(r.commits, [AT3]);
  } finally { dispose(); release(); }
});

test('nested_request_settles_once_on_its_own_hour', async () => {
  const r = await rig();
  const release = r.c.retain();
  const dispose = onPendingOnce(r.m, r.c, () => r.c.request(NOW, 'UTC', AT2));
  try {
    r.c.request(NOW, 'UTC', AT1);
    r.fire();
    for (const run of r.saved) run();
    assert.deepEqual(r.commits, [AT2]);
    assert.equal(r.created(), 1);
  } finally { dispose(); release(); }
});

test('context_change_during_publication_cannot_resurrect_work', async () => {
  const m = await load();
  const ctx = m.signal('a');
  const r = await rig({context: () => ctx.value});
  const release = r.c.retain();
  const dispose = onPendingOnce(m, r.c, () => { ctx.value = 'b'; });
  try {
    assert.equal(r.c.request(NOW, 'UTC', AT1), true);
    assert.equal(r.c.pending.value, false);
    assert.equal(r.created(), 0, 'no orphan timer for the invalidated context');
    assert.equal(r.outstanding(), 0);
    r.fire();
    assert.deepEqual(r.commits, []);
    dispose();
    assert.equal(r.c.request(NOW, 'UTC', AT1), true, 'a new request in the new context');
    assert.equal(r.created(), 1);
    r.fire();
    assert.deepEqual(r.commits, [AT1], 'settles once');
  } finally { dispose(); release(); }
});

test('nonfinal_release_and_normal_burst_keep_debounce', async () => {
  const r = await rig();
  const keep = r.c.retain(), drop = r.c.retain();
  const dispose = onPendingOnce(r.m, r.c, drop);
  try {
    assert.equal(r.c.request(NOW, 'UTC', AT1), true);
    assert.equal(r.c.pending.value, true, 'one holder remains, so the preview lives');
    assert.equal(r.created(), 1);
    assert.equal(r.outstanding(), 1);
    r.fire();
    assert.deepEqual(r.commits, [AT1]);
    // A burst keeps one trailing timer; the same hour and an invalid hour change nothing.
    assert.equal(r.c.request(NOW, 'UTC', AT1), true);
    assert.equal(r.c.request(NOW, 'UTC', AT2), true);
    assert.equal(r.c.request(NOW, 'UTC', AT2), true);
    assert.equal(r.c.request(NOW, 'UTC', AT3), true);
    assert.equal(r.c.request(NOW, 'UTC', AT3 + 1), false);
    assert.equal(r.outstanding(), 1);
    r.fire();
    assert.deepEqual(r.commits, [AT1, AT3], 'the burst commits its last hour once');
  } finally { dispose(); keep(); drop(); }
  keep();
  assert.equal(r.c.pending.value, false, 'release is idempotent');
});

test('return_to_settled_cancels_the_timer', async () => {
  const r = await rig({settledAt: AT1});
  const release = r.c.retain();
  try {
    r.c.request(NOW, 'UTC', AT2);
    assert.equal(r.outstanding(), 1);
    assert.equal(r.c.request(NOW, 'UTC', AT1), true);
    assert.equal(r.c.pending.value, false);
    assert.equal(r.outstanding(), 0);
    r.fire();
    assert.deepEqual(r.commits, []);
  } finally { release(); }
});
