import test from 'node:test';
import assert from 'node:assert/strict';
import { verdict, run } from '../scripts/check_coast_report_source.mjs';

const ALL = 'report=skippercast, nearshore=skippercast, water-quality=skippercast';

function harness(opts = {}) {
  const o = [], e = [], calls = [];
  const deps = {
    out: (s) => o.push(s), err: (s) => e.push(s), calls, o, e,
    fetchImpl: async (url, init) => {
      calls.push({ url, init });
      if (opts.reject) throw new Error('boom');
      let cancelled = 0;
      return {
        status: opts.status ?? 200,
        headers: { get: (k) => (k === 'x-coast-upstream' ? opts.header ?? null : null) },
        body: { cancel: async () => { deps.cancelled = ++cancelled; } },
      };
    },
    readFile: (p) => { if (opts.file === undefined) throw new Error('ENOENT'); return opts.file; },
  };
  return deps;
}

test('all skippercast passes, fish=unavailable note does not fail', () => {
  assert.equal(verdict(ALL).ok, true);
  assert.equal(verdict('report=skippercast, fish=unavailable').ok, true);
});

test('report=fish (stale) fails naming the report', () => {
  const v = verdict('report=fish (stale), nearshore=skippercast');
  assert.equal(v.ok, false);
  assert.ok(v.failures.includes('report=fish (stale)'));
});

test('header absent fails as header missing', async () => {
  assert.deepEqual(verdict(null).failures, ['header missing']);
  assert.deepEqual(verdict('').failures, ['header missing']);
  const h = harness({});
  assert.equal(await run([], h), 1);
  assert.equal(h.o.at(-1), 'FAIL: header missing');
});

test('nearshore=fish only fails: no report entry', () => {
  const v = verdict('nearshore=fish (stale)');
  assert.equal(v.ok, false);
  assert.ok(v.failures.includes('report entry missing'));
  assert.ok(v.failures.includes('nearshore=fish (stale)'));
});

test('run: PASS exit 0 with one GET, no cookies, body cancelled', async () => {
  const h = harness({ header: ALL });
  assert.equal(await run([], h), 0);
  assert.equal(h.o.at(-1), 'PASS');
  assert.equal(h.calls.length, 1);
  const { init } = h.calls[0];
  assert.equal(init.method, 'GET');
  assert.equal(init.credentials, 'omit');
  assert.equal(init.redirect, 'manual');
  assert.ok(init.signal instanceof AbortSignal);
  assert.ok(!Object.keys(init.headers).some((k) => /cookie|authorization/i.test(k)));
  assert.equal(h.cancelled, 1);
});

test('network error and non-200 exit 2 with no verdict line', async () => {
  for (const opts of [{ reject: true }, { status: 503 }]) {
    const h = harness(opts);
    assert.equal(await run([], h), 2);
    assert.match(h.e.join('\n'), /could not read the report/);
    assert.ok(!h.o.some((l) => /^(PASS|FAIL)/.test(l)));
  }
});

test('--from-file reads a folded CRLF header; bad file and flag exit 2', async () => {
  const h = harness({ file: 'HTTP/2 200\r\nX-Coast-Upstream: report=skippercast,\r\n nearshore=skippercast\r\n\r\n' });
  assert.equal(await run(['--from-file', 'x'], h), 0);
  assert.equal(h.calls.length, 0);
  assert.equal(await run(['--from-file', 'x'], harness({})), 2);
  assert.equal(await run(['--nope'], harness({})), 2);
});
