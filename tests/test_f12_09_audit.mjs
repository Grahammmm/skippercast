import assert from 'node:assert/strict';
import test from 'node:test';
import {build} from 'esbuild';

// Mount the real admin views and their API client. Only the DOM and transport are fakes.
const {outputFiles: [bundle]} = await build({stdin: {resolveDir: process.cwd(), contents: `
  export {Queue, focusReview} from './web/admin/queue.tsx';
  export {Skippers} from './web/admin/skippers.tsx';
  export {ApiError, getQueue, getFleetEnabled} from './web/admin/api.ts';
  export {ADMIN_COPY as COPY} from './web/advisor/copy.ts';
  export {h, render} from 'preact';
  export {act} from 'preact/test-utils';
`}, bundle: true, write: false, format: 'esm', platform: 'node', jsx: 'automatic', jsxImportSource: 'preact'});
const {Queue, Skippers, focusReview, ApiError, getQueue, getFleetEnabled, COPY, h, render, act} =
  await import(`data:text/javascript;base64,${Buffer.from(bundle.contents).toString('base64')}`);

class Element {
  constructor(name, data) {
    Object.assign(this, {localName: name, nodeType: data === undefined ? 1 : 3, data,
      childNodes: [], parentNode: null, attrs: {}, handlers: {}});
  }
  get firstChild() { return this.childNodes[0] ?? null; }
  get nextSibling() { return this.parentNode?.childNodes[this.parentNode.childNodes.indexOf(this) + 1] ?? null; }
  get textContent() { return this.data ?? this.childNodes.map(node => node.textContent).join(''); }
  insertBefore(child, ref) {
    child.remove();
    this.childNodes.splice(ref ? this.childNodes.indexOf(ref) : this.childNodes.length, 0, child);
    child.parentNode = this;
    return child;
  }
  appendChild(child) { return this.insertBefore(child, null); }
  removeChild(child) { this.childNodes.splice(this.childNodes.indexOf(child), 1); child.parentNode = null; return child; }
  remove() { this.parentNode?.removeChild(this); }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  removeAttribute(key) { delete this.attrs[key]; }
  addEventListener(type, listener) { this.handlers[type] = listener; }
  removeEventListener(type) { delete this.handlers[type]; }
}
const find = (node, predicate) => predicate(node) ? node : node.childNodes.map(child => find(child, predicate)).find(Boolean);
const flush = () => act(() => new Promise(resolve => setImmediate(resolve)));
const queuePath = '/api/admin/reviews?status=open';
const nonJson = () => new Response('unreadable response', {status: 200});

// A permissive JSON fallback or unfinished page validation must not reach ready state.
test('Queue renders empty only for a valid empty page', async t => {
  t.mock.method(globalThis, 'fetch', () => { throw new Error('unexpected fetch'); });
  const fetchMock = globalThis.fetch.mock;
  globalThis.document = {
    createElement: name => new Element(name), createElementNS: (_, name) => new Element(name),
    createTextNode: data => new Element('#text', String(data)),
  };
  t.after(() => { delete globalThis.document; });
  const review = {id: 'example-review', ref_id: 'example-item', kind: 'rule', status: 'open', reason: 'synthetic',
    opened_at: '2026-01-01T00:00:00Z', decided_at: null, note: null, detail: null};
  const responseCases = [
    ['valid empty', Response.json({items: [], next: null}), false],
    ['malformed JSON', nonJson(), true],
    ['missing items', Response.json({next: null}), true],
    ['items not an array', Response.json({items: {}, next: null}), true],
    ['missing next', Response.json({items: []}), true],
    ['invalid next', Response.json({items: [], next: 7}), true],
    ['invalid item', Response.json({items: [{...review, id: null}], next: null}), true],
    ['non-2xx', Response.json({items: [], next: null, error: 'Synthetic conflict'}, {status: 409}), true],
  ];
  for (const [name, response, failed] of responseCases) {
    await t.test(name, async () => {
      const root = new Element('div');
      fetchMock.resetCalls();
      fetchMock.mockImplementation(async (path, init) => {
        assert.equal(path, queuePath);
        assert.equal(init.method ?? 'GET', 'GET');
        return response;
      });
      try {
        await act(() => render(h(Queue), root));
        await flush();
        assert.equal(root.textContent.includes(COPY.empty), !failed);
        assert.equal(find(root, node => node.attrs.role === 'alert')?.textContent, failed ? COPY.loadFailed : undefined);
        assert.equal(fetchMock.callCount(), 1);
      } finally { render(null, root); }
    });
  }
  await t.test('structured and unreadable non-2xx preserve status', async () => {
    for (const [response, status, message] of [
      [Response.json({error: 'Synthetic conflict'}, {status: 409}), 409, 'Synthetic conflict'],
      [new Response('unreadable response', {status: 502}), 502, 'HTTP 502'],
    ]) {
      fetchMock.mockImplementation(async () => response);
      await assert.rejects(getQueue('open', ''), err => err instanceof ApiError && err.status === status && err.message === message);
    }
  });
  await t.test('an unreadable decision acknowledgement does not retry or remove the review', async () => {
    const root = new Element('div');
    fetchMock.resetCalls();
    fetchMock.mockImplementation(async (path, init) => {
      if (path === queuePath && !init.method) return Response.json({items: [review], next: 'synthetic-next'});
      assert.equal(path, `/api/admin/reviews/${review.id}`);
      if (!init.method) return Response.json({review});
      assert.equal(init.method, 'POST');
      assert.deepEqual(JSON.parse(init.body), {decision: 'approve'});
      return nonJson();
    });
    try {
      await act(() => render(h(Queue), root));
      await flush();
      assert.ok(find(root, node => node.localName === 'button' && node.textContent === COPY.more));
      const expand = find(root, node => node.localName === 'button' && node.textContent === 'Details');
      assert.equal(fetchMock.callCount(), 1, 'closed summaries do not fetch any detail');
      await act(() => expand.handlers.click.call(expand, {type: 'click'}));
      await flush();
      const button = find(root, node => node.localName === 'button' && node.textContent === COPY.done);
      await act(() => button.handlers.click.call(button, {type: 'click'}));
      await flush();
      assert.ok(find(root, node => node.attrs.role === 'alert')?.textContent.includes('did not confirm'));
      assert.ok(find(root, node => node.localName === 'article'));
      assert.equal(fetchMock.callCount(), 3); // list, explicit expansion, user-initiated write
    } finally { render(null, root); }
  });
  await t.test('Fleet capability still requires 204, not a 200 JSON response', async () => {
    fetchMock.mockImplementation(async () => new Response(null, {status: 204}));
    assert.equal(await getFleetEnabled(), true);
    fetchMock.mockImplementation(async () => Response.json({enabled: true}));
    assert.equal(await getFleetEnabled(), false);
  });
});

for (const consent of ['revoked', 'given']) {
  // Contract: fresh consent wins over the list snapshot, but private detail is discarded on collapse.
  test(`Skippers uses detail consent (${consent}) without retaining the detail`, async t => {
    const id = 'example-boat';
    const path = `/api/admin/boats/${id}`;
    const at = '2026-01-01T00:00:00Z';
    const summary = {id, slug: id, name: 'Example Boat', port: 'Example Port', status: 'verified', created_at: at,
      consent: 'given', consent_photos_at: at, consent_revoked_at: null, crew_count: 0};
    const note = 'Synthetic detail-only note';
    const fetch = t.mock.method(globalThis, 'fetch', async url => {
      if (url === '/api/admin/boats') return Response.json({boats: [summary], next: null});
      assert.equal(url, path);
      return Response.json({boat: {...summary, consent, consent_revoked_at: consent === 'revoked' ? at : null,
        owner: null, crew: [], consent_note: {note, at}}});
    });
    globalThis.document = {
      createElement: name => new Element(name), createElementNS: (_, name) => new Element(name),
      createTextNode: data => new Element('#text', String(data)),
    };
    const root = new Element('div');
    const shownConsent = () => find(root, node => node.localName === 'dt' && node.textContent === COPY.consent)?.nextSibling?.textContent;
    const toggle = () => act(() => {
      const button = find(root, node => node.localName === 'button' && node.textContent === 'Details');
      button.handlers.click.call(button, {type: 'click'});
    });
    try {
      await act(() => render(h(Skippers), root));
      await flush();
      assert.equal(shownConsent(), COPY.consentState.given);
      assert.equal(fetch.mock.callCount(), 1);
      await toggle();
      await flush();
      assert.ok(root.textContent.includes(note));
      assert.equal(shownConsent(), COPY.consentState[consent]);
      await toggle();
      assert.ok(!root.textContent.includes(note));
      await toggle();
      await flush();
      assert.deepEqual(fetch.mock.calls.map(call => call.arguments[0]), ['/api/admin/boats', path, path]);
      assert.ok(root.textContent.includes(note));
    } finally { render(null, root); delete globalThis.document; }
  });
}

// Contract: after a decision, focus lands where the A/E/R handler lives. Bug caught: focusing only the outer
// list item leaves an already-expanded next review without keyboard shortcuts (they are on the nested card).
test('focusReview focuses the expanded ReviewCard, else the list item, else the heading', () => {
  const focused = [];
  const el = name => ({focus: () => focused.push(name)});
  const expanded = {...el('item-1'), querySelector: selector => { assert.equal(selector, 'article.admin-card'); return el('card-1'); }};
  const collapsed = {...el('item-2'), querySelector: () => null};
  const doc = {getElementById: id => ({'review-1': expanded, 'review-2': collapsed, 'queue-heading': el('heading')})[id] ?? null};
  focusReview(doc, '1');
  focusReview(doc, '2');
  focusReview(doc, undefined);
  assert.deepEqual(focused, ['card-1', 'item-2', 'heading']);
});
