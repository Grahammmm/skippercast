// Contract: a seafloor manifest read that stalls (headers or body) ends after
// 15 s as 'unavailable' and admits nothing, instead of leaving the habitat
// layer "checking" forever. Believable bug: no deadline, or a body deadline
// that is cleared once headers arrive, or an abort recast as 'updating'.
import test from 'node:test';
import assert from 'node:assert/strict';
import { loadManifest, MANIFEST_TIMEOUT_MS } from '../dist/seafloor-data.js';

const NOW = Date.parse('2026-09-29T20:00:00Z');
const READY = { status: 'ready', region: 'morro-bay', expires_at: '2026-10-30T00:00:00+00:00', archive_sha256: 'a'.repeat(64) };

// Never settles until the request's signal aborts, then rejects like fetch/body do.
const abortAware = (signal) => new Promise((_, reject) => {
  signal.addEventListener('abort', () => reject(signal.reason), { once: true });
});

// Run a read under a fake clock; resolves to {result, settledAt} where settledAt
// is the fake-clock tick at which loadManifest returned (null if still pending).
async function run(fetchImpl, mock) {
  mock.timers.enable({ apis: ['setTimeout'] });
  let result;
  const pending = loadManifest('morro-bay', fetchImpl, NOW).then((r) => { result = r; });
  const flush = () => new Promise((resolve) => setImmediate(resolve));
  await flush();
  mock.timers.tick(MANIFEST_TIMEOUT_MS - 1);
  await flush();
  const settledEarly = result !== undefined;
  mock.timers.tick(1);
  await pending;
  return { result, settledEarly };
}

test('deadline is the Chart manifest read\'s 15 seconds', () => {
  assert.equal(MANIFEST_TIMEOUT_MS, 15_000);
});

test('stalled headers: unavailable at 15 s, not before, nothing admitted', async (t) => {
  let signal;
  const { result, settledEarly } = await run(async (url, opts) => { signal = opts.signal; return abortAware(opts.signal); }, t.mock);
  assert.equal(settledEarly, false, 'still pending at 14999 ms');
  assert.equal(result.state, 'unavailable');
  assert.equal(result.manifest, undefined, 'no manifest admitted');
  assert.notEqual(result.state, 'ready');
  assert.equal(signal.aborted, true, 'a real abort signal was raised');
});

test('stalled 200 body: the deadline outlives header receipt and ends unavailable', async (t) => {
  const { result, settledEarly } = await run(async (url, opts) => ({
    ok: true, status: 200, json: () => abortAware(opts.signal),
  }), t.mock);
  assert.equal(settledEarly, false);
  assert.equal(result.state, 'unavailable');
  assert.equal(result.manifest, undefined);
});

test('stalled 503 body: aborted read is unavailable, not recast as updating', async (t) => {
  const { result, settledEarly } = await run(async (url, opts) => ({
    ok: false, status: 503, json: () => abortAware(opts.signal),
  }), t.mock);
  assert.equal(settledEarly, false);
  assert.equal(result.state, 'unavailable');
  assert.notEqual(result.state, 'updating');
});

test('a fetch that ignores the signal still ends unavailable at 15 s', async (t) => {
  const { result } = await run(() => new Promise(() => {}), t.mock);
  assert.equal(result.state, 'unavailable');
});

test('controls: ready, 404, and 503 with bad JSON before the deadline keep today\'s outcomes', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const ready = await loadManifest('morro-bay', async () => ({ ok: true, status: 200, json: async () => READY }), NOW);
  assert.equal(ready.state, 'ready');
  assert.equal(ready.manifest.archive_sha256, READY.archive_sha256);
  const none = await loadManifest('morro-bay', async () => ({ ok: false, status: 404, json: async () => ({}) }), NOW);
  assert.equal(none.state, 'unavailable');
  assert.equal(none.published, false, 'a 404 still means never published');
  const busy = await loadManifest('morro-bay', async () => ({ ok: false, status: 503, json: async () => { throw new Error('text'); } }), NOW);
  assert.equal(busy.state, 'updating');
  const held = await loadManifest('morro-bay', async () => ({ ok: true, status: 200, json: async () => ({ ...READY, status: 'held' }) }), NOW);
  assert.equal(held.state, 'held');
  const expired = await loadManifest('morro-bay', async () => ({ ok: true, status: 200, json: async () => ({ ...READY, expires_at: '2026-09-29T19:59:59Z' }) }), NOW);
  assert.equal(expired.state, 'expired');
});

test('early completion leaves no pending deadline timer', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  let signal;
  await loadManifest('morro-bay', async (url, opts) => { signal = opts.signal; return { ok: true, status: 200, json: async () => READY }; }, NOW);
  t.mock.timers.tick(MANIFEST_TIMEOUT_MS * 2);
  assert.equal(signal.aborted, false, 'timer was cleared when the read finished');
});
