// RF1951-12: a boundary loader that throws synchronously is "no boundaries", exactly like one that rejects.
import assert from 'node:assert/strict';
import test from 'node:test';
import {checkPosition} from '../web/position-check.ts';

const good = cb => cb({coords: {latitude: 35, longitude: -120, accuracy: 5}});
const geo = {getCurrentPosition: good};
const failing = code => ({getCurrentPosition: (_ok, err) => err({code})});
const FIX = {latitude: 35, longitude: -120, accuracyM: 5};

test('sync_loader_throw_keeps_valid_fix', async () => {
  const r = await checkPosition(() => { throw new Error('synthetic loader failure'); }, geo);
  assert.deepEqual(r, {located: {ok: true, fix: FIX}, reading: {kind: 'no-boundaries'}});
});

test('sync_loader_throw_preserves_location_refusal', async () => {
  const boom = () => { throw new Error('synthetic loader failure'); };
  assert.deepEqual(await checkPosition(boom, failing(1)), {located: {ok: false, reason: 'denied'}});
  assert.deepEqual(await checkPosition(boom, null), {located: {ok: false, reason: 'unsupported'}});
});

test('async_and_concurrent_controls', async () => {
  const rejected = await checkPosition(() => Promise.reject(new Error('x')), geo);
  assert.equal(rejected.reading.kind, 'no-boundaries');
  const nul = await checkPosition(async () => null, geo);
  assert.equal(nul.reading.kind, 'no-boundaries');

  // A deferred loader starts at once; a good fix waits for it.
  let started = 0, release;
  const deferred = () => { started++; return new Promise(res => { release = res; }); };
  let done = false;
  const pending = checkPosition(deferred, geo).then(r => { done = true; return r; });
  assert.equal(started, 1);
  await new Promise(r => setTimeout(r, 10));
  assert.equal(done, false);
  release(null);
  assert.equal((await pending).reading.kind, 'no-boundaries');

  // A failed fix returns before a pending loader resolves.
  const refused = await checkPosition(() => new Promise(() => {}), failing(1));
  assert.deepEqual(refused, {located: {ok: false, reason: 'denied'}});
});
