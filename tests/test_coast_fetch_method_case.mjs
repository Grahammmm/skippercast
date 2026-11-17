import assert from 'node:assert/strict';
import test from 'node:test';
import { coastFetch } from '../packages/coast/src/transport.ts';

async function withStub(run) {
  const calls = [];
  const original = globalThis.fetch;
  globalThis.fetch = async (url, init) => { calls.push({ url, init }); return new Response('ok'); };
  try { await run(calls); } finally { globalThis.fetch = original; }
}

test('read_method_case_is_normalized', async () => {
  await withStub(async (calls) => {
    for (const [given, want] of [['get', 'GET'], ['gEt', 'GET'], ['head', 'HEAD'], ['HeAd', 'HEAD']]) {
      calls.length = 0;
      await coastFetch('/api/report', { method: given });
      assert.equal(calls.length, 1, given);
      assert.equal(calls[0].url, '/api/coast/report');
      assert.equal(calls[0].init.method, want);
    }
  });
});

test('writes_and_padded_methods_are_refused', async () => {
  await withStub(async (calls) => {
    for (const method of ['post', 'POST', 'PUT', 'DELETE', ' GET', 'GET ']) {
      assert.throws(() => coastFetch('/api/report', { method }), /read only/, method);
    }
    assert.equal(calls.length, 0);
  });
});

test('uppercase_default_and_safety_controls', async () => {
  await withStub(async (calls) => {
    await coastFetch('/api/report', { method: 'GET' });
    await coastFetch('/api/report', { method: 'HEAD' });
    await coastFetch('/api/report');
    assert.equal(calls.length, 3);
    assert.equal(calls[0].init.method, 'GET');
    assert.equal(calls[1].init.method, 'HEAD');
    assert.equal(calls[2].init.method, undefined);
    await coastFetch('/api/report', { method: 'get', credentials: 'include', redirect: 'follow' });
    assert.equal(calls[3].init.credentials, 'omit');
    assert.equal(calls[3].init.redirect, 'error');
    assert.throws(() => coastFetch('/api/secret', { method: 'get' }), /Unsupported/);
  });
});
