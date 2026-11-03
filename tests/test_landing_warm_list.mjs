// RF1230-15: the landing's app warm-up (web/landing/warm.ts) keeps only real
// hashed asset file names, each once, first seen first, and at most WARM_MAX,
// so a damaged or oversized precache.json cannot ask for `/` or flood the
// landing with requests. Imports warm.ts by type stripping, as test_landing does.
import assert from 'node:assert/strict';
import test from 'node:test';
import {WARM_MAX, warmApp, warmList} from '../web/landing/warm.ts';

const REAL = ['/assets/app.1111111111.js', '/assets/app.2222222222.css', '/assets/inter-latin.3333.woff2'];
const fakeFetch = (body, asked) => async (url, init) => {
  asked.push([url, init?.priority ?? init?.cache]);
  return {ok: true, json: async () => body, blob: async () => new Blob([])};
};

test('a realistic precache list comes back unchanged, in order', () => {
  assert.deepEqual(warmList({warm: REAL}), REAL);
  assert.deepEqual(warmList({warm: ['/assets/app-Ab_9.js', '/assets/vendor.min.9f8e.js']}), ['/assets/app-Ab_9.js', '/assets/vendor.min.9f8e.js']);
});

test('dot segments and names without a real extension are dropped', () => {
  const bad = ['/assets/..', '/assets/.', '/assets/...', '/assets/app.', '/assets/.hidden', '/assets/noext', '/assets/a..js', '/assets/', '/assets/a.js/'];
  assert.deepEqual(warmList({warm: bad}), []);
  assert.deepEqual(warmList({warm: ['/assets/..', REAL[0], '/assets/.', REAL[1]]}), REAL.slice(0, 2), 'the real names around them stay');
});

test('a repeated path is kept once, at its first place', () => {
  assert.deepEqual(warmList({warm: ['/assets/a.js', '/assets/a.js', '/assets/a.js', '/assets/b.js']}), ['/assets/a.js', '/assets/b.js']);
  assert.deepEqual(warmList({warm: ['/assets/b.js', '/assets/a.js', '/assets/b.js']}), ['/assets/b.js', '/assets/a.js']);
});

test('the list is capped at WARM_MAX and warmApp fetches no more than that', async () => {
  assert.equal(WARM_MAX, 64);
  const many = Array.from({length: 200}, (_, i) => `/assets/chunk-${i}.abc${i}.js`);
  assert.deepEqual(warmList({warm: many}), many.slice(0, 64));
  // Repeats and refusals before the cap do not use up places.
  const mixed = ['/assets/..', ...Array(10).fill(many[0]), ...many];
  assert.deepEqual(warmList({warm: mixed}), many.slice(0, 64));
  const asked = [];
  const paths = await warmApp(fakeFetch({warm: many}, asked), {connection: {saveData: false}});
  assert.equal(asked.length, 65, 'precache.json plus 64 files');
  assert.deepEqual(asked[0], ['/precache.json', 'no-cache']);
  assert.deepEqual(paths, many.slice(0, 64));
  assert.ok(asked.slice(1).every(a => a[1] === 'low'));
});

test('the existing refusals still hold', () => {
  const warm = ['https://x/assets/a.js', '/assets/sub/a.js', '/other/a.js', 7, null, {}, ['/assets/a.js'], REAL[0]];
  assert.deepEqual(warmList({warm}), [REAL[0]]);
  for (const bad of [null, undefined, {}, {warm: '/assets/a.js'}, {warm: {0: '/assets/a.js'}}, {warm: null}]) assert.deepEqual(warmList(bad), [], String(bad));
});

test('Save-Data still means no fetch at all', async () => {
  const asked = [];
  assert.deepEqual(await warmApp(fakeFetch({warm: REAL}, asked), {connection: {saveData: true}}), []);
  assert.deepEqual(asked, []);
});
