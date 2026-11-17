// The optional limiter reports over-limit only for an explicit boolean
// success:false; malformed or unavailable results fail open.
import test from 'node:test';
import assert from 'node:assert/strict';
import {overLimit} from '../server/edge-cache.ts';

const modes = [['sync', r => r], ['promise', r => Promise.resolve(r)]];

function limiter(result, wrap) {
  const calls = [];
  const binding = {tag: 'self', limit(arg) { calls.push({self: this, arg}); return wrap(result); }};
  return {binding, calls};
}

test('limiter_malformed_success_fails_open', async () => {
  const malformed = [{}, {success: undefined}, {success: null}, {success: 0}, {success: ''},
    {success: NaN}, {success: 'false'}, {success: 'no'}, {success: 1}, {success: []}];
  for (const [mode, wrap] of modes) {
    for (const result of malformed) {
      const {binding} = limiter(result, wrap);
      assert.equal(await overLimit(binding, 'k'), false, `${mode} ${JSON.stringify(result)}`);
    }
  }
});

test('limiter_missing_result_fails_open', async () => {
  for (const [mode, wrap] of modes) {
    for (const result of [null, undefined, 0, 'x', true, false]) {
      const {binding} = limiter(result, wrap);
      assert.equal(await overLimit(binding, 'k'), false, `${mode} ${String(result)}`);
    }
  }
});

test('limiter_boolean_controls', async () => {
  for (const [mode, wrap] of modes) {
    const allowed = limiter({success: true}, wrap);
    assert.equal(await overLimit(allowed.binding, 'key-a'), false, mode);
    const denied = limiter({success: false, retry: 3, meta: {x: 1}}, wrap);
    assert.equal(await overLimit(denied.binding, 'key-b'), true, mode);
    for (const [c, key] of [[allowed, 'key-a'], [denied, 'key-b']]) {
      assert.equal(c.calls.length, 1);
      assert.equal(c.calls[0].self, c.binding);
      assert.deepEqual(c.calls[0].arg, {key});
    }
  }
});

test('limiter_unavailable_controls', async () => {
  assert.equal(await overLimit(undefined, 'k'), false);
  assert.equal(await overLimit({}, 'k'), false);
  assert.equal(await overLimit({limit: 'nope'}, 'k'), false);
  assert.equal(await overLimit({limit() { throw new Error('boom'); }}, 'k'), false);
  assert.equal(await overLimit({limit: () => Promise.reject(new Error('boom'))}, 'k'), false);
});
