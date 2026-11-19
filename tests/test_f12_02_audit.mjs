// F12-02: exercise the real PostEditor submit boundary; no server or transport.
import assert from 'node:assert/strict';
import test from 'node:test';
import {fileURLToPath} from 'node:url';
import {build} from 'esbuild';

process.env.TZ = 'America/Los_Angeles';
const {outputFiles: [bundle]} = await build({
  stdin: {resolveDir: fileURLToPath(new URL('..', import.meta.url)), contents: `
    export {PostEditor} from './web/admin/post-card.tsx';
    export {h, render} from 'preact';
    export {act} from 'preact/test-utils';`},
  bundle: true, format: 'esm', platform: 'node', write: false, jsx: 'automatic', jsxImportSource: 'preact',
});
const {PostEditor, h, render, act} = await import(`data:text/javascript;base64,${Buffer.from(bundle.contents).toString('base64')}`);

class Element {
  constructor(name, data) {
    Object.assign(this, {localName: name, nodeType: data === undefined ? 1 : 3, data,
      childNodes: [], parentNode: null, attrs: {}, listeners: {}, value: ''});
  }
  get firstChild() { return this.childNodes[0] ?? null; }
  get nextSibling() { return this.parentNode?.childNodes[this.parentNode.childNodes.indexOf(this) + 1] ?? null; }
  insertBefore(child, ref) {
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
  focus() {}
  fire(type) { return act(() => this.listeners[type].call(this, {type, currentTarget: this, preventDefault() {}})); }
}

globalThis.document = {
  createElementNS: (_, name) => new Element(name),
  createElement: name => new Element(name),
  createTextNode: data => new Element('#text', String(data)),
};
const nodes = node => [node, ...node.childNodes.flatMap(nodes)];
const text = node => node.data ?? node.childNodes.map(text).join('');

async function editor(scheduled_for = null) {
  const root = new Element('div');
  const decisions = [];
  const post = {kind: 'photo', caption: 'Original caption', targets: ['instagram'], allowed_targets: ['instagram'],
    collaborators: [], user_tags: [], scheduled_for};
  await act(() => render(h(PostEditor, {post, idBase: 'draft', busy: false,
    onSubmit: async body => { decisions.push(body); render(null, root); }}), root));
  const byId = id => nodes(root).find(n => n.attrs.id === id);
  const input = async (id, value) => {
    const field = byId(id);
    field.value = value;
    await field.fire('input');
  };
  return {root, decisions, byId, input, save: () => root.firstChild.fire('submit')};
}

for (const editCaption of [false, true]) {
  test(`Los Angeles 02:30 spring gap keeps the draft open (${editCaption ? 'caption edited' : 'schedule only'})`, async () => {
    const v = await editor();
    if (editCaption) await v.input('draft-caption', 'Revised caption');
    await v.input('draft-schedule', '2026-03-08T02:30');
    await v.save();

    assert.deepEqual(v.decisions, [], 'invalid schedule must not send approve or edit');
    assert.equal(v.root.firstChild.localName, 'form');
    const schedule = v.byId('draft-schedule');
    assert.equal(schedule.value, '2026-03-08T02:30');
    assert.equal(schedule.attrs['aria-invalid'], 'true');
    const error = v.byId(schedule.attrs['aria-describedby']);
    assert.equal(error?.attrs.role, 'alert');
    assert.ok(text(error).trim(), 'schedule error has visible text');

    if (editCaption) {
      assert.equal(v.byId('draft-caption').value, 'Revised caption');
      await v.input('draft-schedule', '2026-03-08T03:30');
      assert.notEqual(schedule.attrs['aria-invalid'], 'true');
      assert.ok(!nodes(v.root).some(n => n.attrs.role === 'alert'));
      await v.save();
      assert.deepEqual(v.decisions, [{decision: 'edit', patch: {caption: 'Revised caption', scheduled_for: '2026-03-08T10:30:00.000Z'}}]);
    }
  });
}

test('deliberately clearing a saved schedule sends an explicit null', async () => {
  const v = await editor('2026-03-08T10:30:00.000Z');
  assert.equal(v.byId('draft-schedule').value, '2026-03-08T03:30');
  await v.input('draft-schedule', '');
  await v.save();
  assert.deepEqual(v.decisions, [{decision: 'edit', patch: {scheduled_for: null}}]);
});
