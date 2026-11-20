// F12-13: exercise the real PostsView, calendar and action callbacks without a browser or network.
import assert from 'node:assert/strict';
import test from 'node:test';
import {fileURLToPath} from 'node:url';
import {build} from 'esbuild';

const {outputFiles: [bundle]} = await build({
  stdin: {resolveDir: fileURLToPath(new URL('..', import.meta.url)), contents: `
    export {PostsView} from './web/admin/posts.tsx';
    export {ADMIN_COPY as copy} from './web/advisor/copy.ts';
    export {h, render} from 'preact';
    export {act} from 'preact/test-utils';`},
  bundle: true, format: 'esm', platform: 'node', write: false, jsx: 'automatic', jsxImportSource: 'preact',
});
const {PostsView, copy, h, render, act} = await import(`data:text/javascript;base64,${Buffer.from(bundle.contents).toString('base64')}`);

class Element {
  constructor(localName, data) {
    Object.assign(this, {localName, data, nodeType: data === undefined ? 1 : 3,
      childNodes: [], parentNode: null, attrs: {}, listeners: {}, value: ''});
  }
  get firstChild() { return this.childNodes[0] ?? null; }
  get nextSibling() { return this.parentNode?.childNodes[this.parentNode.childNodes.indexOf(this) + 1] ?? null; }
  insertBefore(child, ref) {
    if (child === ref) return;
    child.remove();
    this.childNodes.splice(ref ? this.childNodes.indexOf(ref) : this.childNodes.length, 0, child);
    child.parentNode = this;
  }
  removeChild(child) { this.childNodes.splice(this.childNodes.indexOf(child), 1); child.parentNode = null; }
  remove() { this.parentNode?.removeChild(this); }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  removeAttribute(key) { delete this.attrs[key]; }
  addEventListener(type, fn) { this.listeners[type] = fn; }
  removeEventListener(type) { delete this.listeners[type]; }
  fire(type) { return act(() => this.listeners[type].call(this, {type, currentTarget: this, preventDefault() {}})); }
}

const nodes = node => [node, ...node.childNodes.flatMap(nodes)];
const text = node => node.data ?? node.childNodes.map(text).join('');
const calendar = '/api/admin/posts/calendar';
const post = (id, status, extra) => ({id, status, kind: 'photo', region: 'fixture', caption: id,
  caption_stats: {length: id.length, hashtags: 0, mentions: 0}, media: [], targets: [], collaborators: [], user_tags: [],
  created_at: '2026-11-16T12:00:00Z', updated_at: '2026-11-16T12:00:00Z', scheduled_for: null, ...extra});

// Before the fix, the initial drafts response and Load more each trigger an extra calendar GET.
// Removing invalidation altogether would instead miss the approval and schedule controls below.
test('calendar reads on week navigation and successful mutations, not on draft pagination', async t => {
  const root = new Element('div');
  t.mock.method(globalThis, 'fetch', (url, init) => {
    requests.push({url, init});
    const reply = replies.get(url);
    if (!reply) throw new Error(`unexpected request: ${url}`);
    return Promise.resolve(reply());
  });
  globalThis.document = {createElement: name => new Element(name), createElementNS: (_, name) => new Element(name),
    createTextNode: data => new Element('#text', String(data)), getElementById: () => null};
  globalThis.requestAnimationFrame = callback => queueMicrotask(callback);
  t.after(async () => { await act(() => render(null, root)); delete globalThis.document; delete globalThis.requestAnimationFrame; });
  const requests = [];
  const reads = () => requests.filter(r => r.url.startsWith(calendar)).map(r => r.url);
  const json = (body, status = 200) => new Response(JSON.stringify(body), {status});
  const week = (start, end) => ({start, end, tz: 'UTC', days: []});
  let approved = false;
  let scheduleOk = false;
  const schedule = '/api/admin/posts/approved/schedule';
  const nextWeek = `${calendar}?start=2026-11-23`;
  const replies = new Map([
    [calendar, () => json(week('2026-11-16', '2026-11-22'))],
    [nextWeek, () => json(week('2026-11-23', '2026-11-29'))],
    ['/api/admin/posts?status=draft', () => json(approved ? {posts: [], next: null} :
      {posts: [post('first draft', 'draft', {review_id: 'fixture-review'})], next: 'fixture-page'})],
    ['/api/admin/posts?status=draft&cursor=fixture-page', () => json({posts: [post('second draft', 'draft')], next: null})],
    ['/api/admin/reviews/fixture-review', () => { approved = true; return json({review: {status: 'approved'}}); }],
    ['/api/admin/posts?status=approved', () => json({posts: [post('approved', 'approved', {scheduled_for: '2026-11-20T12:00:00Z'})], next: null})],
    [schedule, () => scheduleOk ? json({post: post('approved', 'approved')}) : json({error: 'fixture failure'}, 500)],
  ]);
  const button = label => nodes(root).find(n => n.localName === 'button' && text(n) === label);
  const settle = () => act(() => new Promise(resolve => setImmediate(resolve)));
  await act(() => render(h(PostsView, {}), root));
  await settle();
  await button(copy.more).fire('click');
  await settle();
  assert.match(text(root), /first draft/);
  assert.match(text(root), /second draft/);
  assert.deepEqual(reads(), [calendar], 'mount and Load more use one calendar read');

  await button(copy.approve).fire('click');
  await settle();
  assert.match(text(root), /No posts match/);
  assert.deepEqual(reads(), [calendar, calendar], 'approval and its list reload together read the calendar once');

  const filter = nodes(root).find(n => n.localName === 'select');
  filter.value = 'approved';
  await filter.fire('change');
  await settle();
  assert.deepEqual(reads(), [calendar, calendar], 'changing the list filter does not refresh the calendar');
  await button(copy.scheduleClear).fire('click');
  await settle();
  assert.ok(nodes(root).some(n => n.attrs.role === 'alert'));
  assert.deepEqual(reads(), [calendar, calendar], 'failed schedule change does not refresh');
  scheduleOk = true;
  await button(copy.scheduleClear).fire('click');
  await settle();
  assert.equal(requests.filter(r => r.url === schedule).length, 2);
  assert.equal(button(copy.scheduleClear), undefined, 'the cleared schedule rendered');
  assert.deepEqual(reads(), [calendar, calendar, calendar], 'successful schedule change refreshes once');

  await button(copy.calendarNext).fire('click');
  await settle();
  assert.deepEqual(reads(), [calendar, calendar, calendar, nextWeek], 'week navigation still reads the selected week');
});
