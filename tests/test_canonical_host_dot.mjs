// RF1240-18: a trailing host dot and a www. prefix both fold to the bare host in one 301.
import test from 'node:test';
import assert from 'node:assert/strict';

const {canonicalRedirect} = await import('../server/middleware/canonical.ts');

const loc = (href) => canonicalRedirect(new URL(href))?.headers.get('Location') ?? null;

test('a trailing host dot redirects to the bare host with path and query kept', () => {
  assert.equal(loc('https://skippercast.com./a?b=1'), 'https://skippercast.com/a?b=1');
});

test('www. plus a trailing dot is one 301 straight to the bare host', () => {
  const target = loc('https://www.skippercast.com./x');
  assert.equal(target, 'https://skippercast.com/x');
  assert.equal(canonicalRedirect(new URL(target)), null, 'the target is served, no second hop');
});

test('www. alone still redirects and drops the hash (unchanged behaviour)', () => {
  assert.equal(loc('https://www.skippercast.com/x#h'), 'https://skippercast.com/x');
});

test('bare, undotted hosts are served as is', () => {
  for (const href of ['https://skippercast.com/', 'http://localhost:8787/', 'http://127.0.0.1/', 'https://skippercast.com/a?b=1#h']) {
    assert.equal(canonicalRedirect(new URL(href)), null, href);
  }
});

test('a dotted localhost keeps its scheme and port', () => {
  assert.equal(loc('http://localhost.:8787/p'), 'http://localhost:8787/p');
});

test('hostname www. folds to www, never to an empty host', () => {
  const target = loc('http://www./p');
  assert.equal(target, 'http://www/p');
  assert.equal(canonicalRedirect(new URL(target)), null);
});

test('only one trailing dot is folded per hop and no fold yields an empty host', () => {
  assert.equal(loc('https://skippercast.com../a'), 'https://skippercast.com./a');
  for (const href of ['http://www/p', 'http://wwwx./p']) {
    const target = loc(href);
    assert.ok(target === null || new URL(target).hostname.length > 0, href);
  }
});

test('response headers equal today: 301, Cache-Control, no body', async () => {
  for (const href of ['https://skippercast.com./x', 'https://www.skippercast.com/x']) {
    const res = canonicalRedirect(new URL(href));
    assert.equal(res.status, 301);
    assert.equal(res.headers.get('Cache-Control'), 'public, max-age=3600');
    assert.equal(res.body, null);
    assert.equal(await res.text(), '');
  }
});
