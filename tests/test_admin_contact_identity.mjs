// RF0511-8: the admin contact view stays bound to the requested contact when
// navigation changes ids while an earlier request is still pending. Real
// ContactView + Preact, bundled in memory; only the DOM and fetch are fakes.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';

const dir = await mkdtemp(join(tmpdir(), 'admin-contact-'));
const out = join(dir, 'component.mjs');
await build({stdin: {resolveDir: process.cwd(), loader: 'ts', contents: `
  export {ContactView} from './web/admin/contact.tsx';
  export {ADMIN_COPY} from './web/advisor/copy.ts';
  export {h, render} from 'preact';
  export {act} from 'preact/test-utils';`}, bundle: true, format: 'esm', platform: 'node',
  outfile: out, jsx: 'automatic', jsxImportSource: 'preact', logLevel: 'silent'});
const {ContactView, ADMIN_COPY: COPY, h, render, act} = await import(pathToFileURL(out).href);
test.after(() => rm(dir, {recursive: true, force: true}));

class Element {
  constructor(name, data) {
    Object.assign(this, {localName: name, nodeName: name.toUpperCase(), nodeType: data === undefined ? 1 : 3,
      data, childNodes: [], parentNode: null, attrs: {}, on: {}, style: {}});
  }
  get firstChild() { return this.childNodes[0] ?? null; }
  get nextSibling() { return this.parentNode?.childNodes[this.parentNode.childNodes.indexOf(this) + 1] ?? null; }
  insertBefore(child, ref) {
    child.parentNode?.removeChild(child);
    this.childNodes.splice(ref ? this.childNodes.indexOf(ref) : this.childNodes.length, 0, child);
    child.parentNode = this; return child;
  }
  appendChild(child) { return this.insertBefore(child, null); }
  removeChild(child) { this.childNodes.splice(this.childNodes.indexOf(child), 1); child.parentNode = null; return child; }
  remove() { this.parentNode?.removeChild(this); }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  removeAttribute(key) { delete this.attrs[key]; }
  addEventListener(type, fn) { this.on[type] = fn; }
  removeEventListener(type) { delete this.on[type]; }
}
globalThis.document = {createElement: name => new Element(name), createElementNS: (_, name) => new Element(name),
  createTextNode: data => new Element('#text', String(data))};
const text = node => node.nodeType === 3 ? node.data : node.childNodes.map(text).join('');
const all = (node, pred) => [...(pred(node) ? [node] : []), ...node.childNodes.flatMap(n => all(n, pred))];

// Deferred synthetic fetch: every request waits until the test settles it.
let pending = [];
globalThis.fetch = (path, init = {}) => new Promise((resolve, reject) => {
  pending.push({path, method: init.method ?? 'GET', body: init.body, resolve, reject});
});
const respond = (req, status, body) => req.resolve({ok: status < 400, status, json: async () => body});
const find = (path, method = 'GET') => pending.find(r => r.path === path && r.method === method && !r.done);
const flush = () => act(() => new Promise(resolve => setImmediate(resolve)));   // let promise chains and effects run
const settle = async (req, status, body) => { req.done = true; respond(req, status, body); await flush(); };
const detail = (id, name, status = 'active') => ({
  contact: {id, display_name: name, status, role: 'skipper', channel: 'sms', language: 'en', source: null,
    home_port: null, created_at: 0, last_seen_at: 0, messages_today: 0},
  boats: [], export: `/api/admin/contacts/${id}/export`,
  messages: [{direction: 'in', created_at: 0, intent: null, status: 'done', body: `hello from ${name}`, media: 0}]});

async function mount(id) {
  pending = [];
  const root = new Element('div');
  const show = async next => { await act(() => render(h(ContactView, {id: next}), root)); await flush(); };
  await show(id); await flush();
  return {root, show,
    heading: () => text(all(root, n => n.localName === 'h1')[0]),
    body: () => text(root),
    button: () => all(root, n => n.localName === 'button')[0],
    exportHref: () => all(root, n => n.localName === 'a' && n.attrs.download !== undefined)[0]?.attrs.href,
    click: async () => { await act(() => { const b = all(root, n => n.localName === 'button')[0]; b.on.click.call(b, {type: 'click', currentTarget: b}); }); await flush(); }};
}

test('late_contact_success_cannot_replace_current_identity', async () => {
  const v = await mount('A');
  await v.show('B');
  await settle(find('/api/admin/contacts/B'), 200, detail('B', 'Synthetic B'));
  await settle(find('/api/admin/contacts/A'), 200, detail('A', 'Synthetic A', 'blocked'));
  assert.ok(v.heading().endsWith(': Synthetic B'), v.heading());
  assert.ok(v.body().includes('hello from Synthetic B') && !v.body().includes('Synthetic A'));
  assert.equal(v.exportHref(), '/api/admin/contacts/B/export');
  assert.equal(v.button().on.click !== undefined && text(v.button()).trim(), COPY.block);
  await v.click();
  const posts = pending.filter(r => r.method === 'POST');
  assert.equal(posts.length, 1);
  assert.equal(posts[0].path, '/api/admin/contacts/B/block');
  assert.deepEqual(JSON.parse(posts[0].body), {blocked: true});
});

for (const status of [404, 500]) {
  test(`abandoned_missing_or_failed_contact_cannot_hide_current_detail (${status})`, async () => {
    const v = await mount('A');
    await v.show('B');
    await settle(find('/api/admin/contacts/B'), 200, detail('B', 'Synthetic B'));
    await settle(find('/api/admin/contacts/A'), status, {error: 'late failure'});
    assert.ok(v.heading().endsWith(': Synthetic B'));
    assert.ok(!v.body().includes(COPY.contactMissing) && !v.body().includes(COPY.loadFailed));
    assert.ok(v.button() && v.exportHref() === '/api/admin/contacts/B/export');
  });
}

test('id_change_clears_previous_detail_and_feedback_while_loading', async () => {
  const v = await mount('A');
  await settle(find('/api/admin/contacts/A'), 200, detail('A', 'Synthetic A'));
  await v.click();
  await settle(find('/api/admin/contacts/A/block', 'POST'), 200, {status: 'blocked'});
  assert.ok(v.body().includes(COPY.contactStatus.blocked));
  await v.show('B');
  assert.equal(v.heading(), COPY.contactHeading);
  assert.ok(!v.body().includes('Synthetic A') && !v.body().includes(COPY.contactStatus.blocked));
  assert.ok(v.body().includes(COPY.loading));
  assert.equal(v.button(), undefined);
  assert.equal(v.exportHref(), undefined);
  await settle(find('/api/admin/contacts/B'), 200, detail('B', 'Synthetic B'));
  assert.ok(v.heading().endsWith(': Synthetic B'));
  assert.equal(text(v.button()).trim(), COPY.block);
});

for (const outcome of ['success', 'rejection']) {
  test(`old_toggle_completion_is_scoped_to_old_contact (${outcome})`, async () => {
    const v = await mount('A');
    await settle(find('/api/admin/contacts/A'), 200, detail('A', 'Synthetic A'));
    await v.click();
    await v.show('B');
    await settle(find('/api/admin/contacts/B'), 200, detail('B', 'Synthetic B'));
    const before = v.body();
    const post = find('/api/admin/contacts/A/block', 'POST');
    if (outcome === 'success') await settle(post, 200, {status: 'blocked'});
    else await settle(post, 409, {error: 'old failure'});
    assert.equal(v.body(), before);
    assert.ok(v.heading().endsWith(': Synthetic B'));
    assert.equal(text(v.button()).trim(), COPY.block);
    assert.equal(v.button().attrs.disabled, undefined);
    assert.ok(!v.body().includes('old failure'));
  });
}

test('current_contact_controls_keep_existing_semantics', async () => {
  let v = await mount('A');
  assert.ok(v.body().includes(COPY.loading));
  await settle(find('/api/admin/contacts/A'), 404, {error: 'nope'});
  assert.ok(v.body().includes(COPY.contactMissing));
  v = await mount('A');
  await settle(find('/api/admin/contacts/A'), 500, {});
  assert.ok(v.body().includes(COPY.loadFailed));

  v = await mount('A');
  await settle(find('/api/admin/contacts/A'), 200, detail('A', 'Synthetic A'));
  await v.click(); await v.click();                       // duplicate click while busy
  assert.equal(pending.filter(r => r.method === 'POST').length, 1);
  await settle(find('/api/admin/contacts/A/block', 'POST'), 200, {status: 'blocked'});
  assert.equal(text(v.button()).trim(), COPY.unblock);    // returned status is respected
  assert.ok(v.body().includes(COPY.contactStatus.blocked));
  await v.click();
  assert.deepEqual(JSON.parse(find('/api/admin/contacts/A/block', 'POST').body), {blocked: false});
});
