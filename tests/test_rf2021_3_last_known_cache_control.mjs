// RF2021-3: a response whose Cache-Control says private or no-store, in any letter
// casing, is never kept as a public last-known copy. Synthetic cache and bodies only.
import test from 'node:test';
import assert from 'node:assert/strict';
const {keepLastKnown, lastKnown} = await import('../server/cost-ceiling.ts');

/** Records what production attempts to store; it does not reject directives itself. */
async function withCache(fn) {
  const puts = [], original = globalThis.caches;
  const store = {
    async put(request, response) { puts.push({url: request.url, status: response.status, body: await response.text(), headers: new Headers(response.headers)}); },
    async match(request) { const p = puts.find(e => e.url === request.url); return p ? new Response(p.body, {status: p.status, headers: p.headers}) : undefined; },
  };
  globalThis.caches = {default: store, async open() { return store; }};
  try { return await fn(puts); } finally { globalThis.caches = original; }
}
const req = () => new Request('https://example.test/api/feed.json');
const reply = (headers, init = {}) => new Response('synthetic body', {status: 200, headers, ...init});

test('last_known_refuses_case_insensitive_private_and_no_store', () => withCache(async puts => {
  for (const directive of ['Private', 'PRIVATE', 'No-Store', 'NO-STORE']) {
    await keepLastKnown(req(), reply({'Cache-Control': directive}), undefined, 1_000);
  }
  assert.equal(puts.length, 0);
  assert.equal(await lastKnown(req()), null);
}));

test('last_known_refuses_mixed_directive_lists', () => withCache(async puts => {
  for (const directive of ['max-age=60, pRiVaTe', 'public, nO-sToRe, max-age=0', 'private', 'no-store']) {
    await keepLastKnown(req(), reply({'Cache-Control': directive}), undefined, 1_000);
  }
  assert.equal(puts.length, 0);
}));

test('last_known_set_cookie_remains_refused', () => withCache(async puts => {
  await keepLastKnown(req(), reply({'Cache-Control': 'public, max-age=60', 'Set-Cookie': 's=1'}), undefined, 1_000);
  assert.equal(puts.length, 0);
}));

test('last_known_public_control_replays_unchanged', () => withCache(async puts => {
  for (const headers of [{'Cache-Control': 'public, max-age=60'}, {}]) {
    puts.length = 0;
    await keepLastKnown(req(), reply(headers), undefined, 1_000);
    assert.equal(puts.length, 1);
    const hit = await lastKnown(req());
    assert.equal(hit.status, 200);
    assert.equal(await hit.text(), 'synthetic body');
    assert.equal(hit.headers.get('Cache-Control'), 'no-store');
    assert.equal(hit.headers.get('X-SC-Degraded'), 'cost-ceiling');
  }
  puts.length = 0;
  await keepLastKnown(req(), reply({}, {status: 404}), undefined, 1_000);
  await keepLastKnown(req(), new Response(null, {status: 200}), undefined, 1_000);
  assert.equal(puts.length, 0);
}));
