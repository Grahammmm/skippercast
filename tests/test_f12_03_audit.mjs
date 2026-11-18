// F12-03: exercise the real Rules view, API client and rule writer offline.
import assert from 'node:assert/strict';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import test from 'node:test';
import {build} from 'esbuild';
import {advisorDatabase} from './_advisor_d1.mjs';
// Synthetic stand-ins for the globals injected by the Worker build.
globalThis.REGIONS = {};
globalThis.DEPLOYMENT = {allowed_origins: []};
const {listRules, editRule} = await import('../server/advisor/admin/rules.ts');

// A minimal DOM, as in test_admin_contact_identity.mjs. No browser or fetch transport.
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
    child.parentNode = this;
  }
  appendChild(child) { this.insertBefore(child, null); }
  removeChild(child) { this.childNodes.splice(this.childNodes.indexOf(child), 1); child.parentNode = null; }
  remove() { this.parentNode?.removeChild(this); }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  removeAttribute(key) { delete this.attrs[key]; }
  addEventListener(type, fn) { this.on[type] = fn; }
  removeEventListener(type) { delete this.on[type]; }
}
const text = n => n.nodeType === 3 ? n.data : n.childNodes.map(text).join('');
const all = (n, pred) => [...(pred(n) ? [n] : []), ...n.childNodes.flatMap(child => all(child, pred))];

const dir = await mkdtemp(join(tmpdir(), 'admin-rule-review-'));
test.after(() => rm(dir, {recursive: true, force: true}));
const out = join(dir, 'component.mjs');
await build({stdin: {resolveDir: process.cwd(), loader: 'ts', contents: `
  export {RulesView} from './web/admin/rules.tsx';
  export {h, render} from 'preact';
  export {act} from 'preact/test-utils';`}, bundle: true, format: 'esm', platform: 'node',
  outfile: out, jsx: 'automatic', jsxImportSource: 'preact'});
const {RulesView, h, render, act} = await import(pathToFileURL(out).href);

test('a due rule shows its stored restrictions and source before an unchanged confirmation renews the review', async t => {
  const {sql, db} = advisorDatabase();
  t.after(() => sql.close());
  const now = Date.parse('2026-06-01T18:00:00Z');
  const initial = {
    id: 'a'.repeat(32), jurisdiction: 'california-central', region: '*', species_key: 'other', species_label: 'Synthetic fish',
    size_min_in: 12, size_max_in: 22, bag_limit: 2, bag_notes: 'Synthetic bag note',
    season_open: '05-01', season_close: '07-15', depth_limit_ft: 0,
    area_notes: 'Outside the synthetic boundary only', gear_notes: 'Synthetic single-hook restriction',
    source_name: 'Synthetic authority bulletin', source_url: 'https://rules.example.invalid/synthetic',
    status: 'review', reviewed_at: '2026-03-01T18:00:00.000Z', review_due: '2026-05-30',
    updated_by: 'synthetic-import', updated_at: '2026-03-01T18:00:00.000Z',
  };
  const keys = Object.keys(initial);
  sql.prepare(`INSERT INTO advisor_rules (${keys.join(',')}) VALUES (${keys.map(() => '?').join(',')})`).run(...Object.values(initial));
  const stored = () => ({...sql.prepare('SELECT * FROM advisor_rules WHERE id=?').get(initial.id)});
  const posts = [];
  const root = new Element('div');
  t.mock.method(globalThis, 'fetch', async (path, {method, body} = {}) => {
    if (path === '/api/admin/rules' && !method) return Response.json(await listRules(db, {}, now));
    assert.equal(path, `/api/admin/rules/${initial.id}`);
    assert.equal(method, 'POST');
    const fields = JSON.parse(body);
    posts.push(fields);
    const result = await editRule(db, initial.id, fields, 'synthetic-review', now);
    assert.equal(result.status, 'ok');
    return Response.json({rule: result.rule});
  });
  const originalDocument = globalThis.document;
  globalThis.document = {createElement: name => new Element(name), createElementNS: (_, name) => new Element(name),
    createTextNode: data => new Element('#text', String(data))};
  t.after(() => { render(null, root); globalThis.document = originalDocument; });
  const flush = () => act(() => new Promise(resolve => setImmediate(resolve)));
  const find = (within, name, label) => all(within, n => n.localName === name && text(n) === label)[0];
  const click = async button => {
    assert.ok(button && button.attrs.disabled === undefined, 'expected an available button');
    await act(() => button.on.click.call(button, {type: 'click', currentTarget: button}));
    await flush();
  };
  await act(() => render(h(RulesView, {jurisdiction: ''}), root));
  await flush();
  assert.ok(find(root, 'h1', 'Rules'));
  assert.equal(Boolean(find(root, 'button', 'Checked, no change')), false, 'a due rule cannot be confirmed before the restrictions are shown');
  assert.deepEqual(stored(), initial);

  const review = find(root, 'button', 'Review restrictions');
  await click(review);
  const view = all(root, n => n.attrs.id === review.attrs['aria-controls'])[0];
  assert.ok(view);
  for (const value of ['Depth limit (ft): 0', `Area notes: ${initial.area_notes}`, `Gear notes: ${initial.gear_notes}`]) {
    assert.ok(text(view).includes(value), `confirmation view is missing ${value}`);
  }
  assert.equal(find(view, 'a', initial.source_name)?.attrs.href, initial.source_url);
  assert.deepEqual(posts, [], 'opening the review does not write');
  assert.deepEqual(stored(), initial);

  await click(find(view, 'button', 'Checked, no change'));
  assert.deepEqual(posts, [{}], 'confirmation still sends exactly the unchanged edit');
  assert.deepEqual(stored(), {...initial, status: 'active', reviewed_at: '2026-06-01T18:00:00.000Z', review_due: '2026-07-15',
    updated_by: 'synthetic-review', updated_at: '2026-06-01T18:00:00.000Z'});
  assert.equal(Boolean(find(root, 'button', 'Checked, no change')), false, 'a newly active row is no longer due');
});
