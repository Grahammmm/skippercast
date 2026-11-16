// RF0015-16: an obsolete dock settlement callback must not erase the replacement timer's cancellation handle.
// The real createDockSelection factory is bundled with esbuild; the scheduler is a manual asynchronous-style
// queue that records created timers, active handles and cancellations. Saved callbacks may be replayed
// after cancellation, independently of the active queue.
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
  const out = join(await mkdtemp(join(tmpdir(), 'dock-stale-handle-')), 'm.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: "export {createDockSelection} from './web/dock-selection.ts';"},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent',
  });
  mod = await import(pathToFileURL(out).href);
  return mod;
}

async function rig() {
  const m = await load();
  const timers = new Map(), saved = [], commits = [], cancelled = [];
  let next = 0;
  const c = m.createDockSelection({
    context: () => 'ctx', doc: () => null, settled: () => ({index: 0, at: NOW.getTime()}),
    schedule: run => { const id = ++next; timers.set(id, run); saved.push({id, run}); return id; },
    cancel: id => { cancelled.push(id); timers.delete(id); },
    commit: (_n, _z, at) => commits.push(at),
  });
  const fire = id => { const run = timers.get(id); timers.delete(id); run(); };
  return {c, commits, saved, cancelled, timers, fire};
}

test('obsolete_then_cancel', async () => {
  const r = await rig();
  const release = r.c.retain();
  try {
    r.c.request(NOW, 'UTC', AT1);
    r.c.request(NOW, 'UTC', AT2);
    const [a, b] = r.saved;
    assert.deepEqual([...r.timers.keys()], [b.id]);
    a.run();
    assert.deepEqual(r.commits, []);
    assert.equal(r.c.pending.value, true);
    assert.deepEqual([...r.timers.keys()], [b.id]);
    r.c.cancel();
    assert.ok(r.cancelled.includes(b.id), 'the replacement timer is cancelled by its exact handle');
    assert.equal(r.timers.size, 0);
    assert.equal(r.c.pending.value, false);
  } finally { release(); }
});

test('obsolete_then_final_release', async () => {
  const r = await rig();
  const release = r.c.retain();
  r.c.request(NOW, 'UTC', AT1);
  r.c.request(NOW, 'UTC', AT2);
  const [a, b] = r.saved;
  a.run();
  release();
  assert.ok(r.cancelled.includes(b.id));
  assert.equal(r.timers.size, 0);
  assert.equal(r.c.pending.value, false);
  release();
  assert.equal(r.timers.size, 0);
  assert.deepEqual(r.commits, []);
});

test('obsolete_then_replacement', async () => {
  const r = await rig();
  const release = r.c.retain();
  try {
    r.c.request(NOW, 'UTC', AT1);
    r.c.request(NOW, 'UTC', AT2);
    const [a, b] = r.saved;
    a.run();
    r.c.request(NOW, 'UTC', AT3);
    const cc = r.saved[2];
    assert.ok(r.cancelled.includes(b.id), 'B is cancelled, not orphaned');
    assert.deepEqual([...r.timers.keys()], [cc.id]);
    r.fire(cc.id);
    assert.deepEqual(r.commits, [AT3]);
    assert.equal(r.timers.size, 0);
  } finally { release(); }
});

test('obsolete_does_not_steal_settlement', async () => {
  const r = await rig();
  const release = r.c.retain();
  try {
    r.c.request(NOW, 'UTC', AT1);
    r.c.request(NOW, 'UTC', AT2);
    const [a, b] = r.saved;
    a.run();
    r.fire(b.id);
    assert.deepEqual(r.commits, [AT2]);
    assert.equal(r.c.pending.value, false);
    assert.equal(r.timers.size, 0);
    a.run(); b.run();
    assert.deepEqual(r.commits, [AT2]);
  } finally { release(); }
});

test('normal_cancel_and_settle_controls', async () => {
  const r = await rig();
  const release = r.c.retain();
  try {
    r.c.request(NOW, 'UTC', AT1);
    r.c.cancel();
    assert.deepEqual(r.cancelled, [r.saved[0].id]);
    assert.equal(r.timers.size, 0);
    r.c.request(NOW, 'UTC', AT2);
    r.fire(r.saved[1].id);
    assert.deepEqual(r.commits, [AT2]);
  } finally { release(); }
});
