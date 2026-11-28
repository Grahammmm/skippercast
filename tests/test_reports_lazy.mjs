import assert from 'node:assert/strict';
import {readFile, stat} from 'node:fs/promises';
import test from 'node:test';
import {fileURLToPath} from 'node:url';
import {build} from 'esbuild';

const root = new URL('../', import.meta.url);
const built = new URL('dist/client/', root);
const read = url => readFile(url, 'utf8');

// Catch an eager import or a dropped/misplaced branch in either shell.
for (const [shell, container] of [['Desktop', 'app-page'], ['Mobile', 'app-mobile-page']]) {
  test(`C1: ${shell} renders one shared LazyReports under the Reports Guard`, async () => {
    const source = await read(new URL(`web/app/${shell}.tsx`, root));
    const imports = [...source.matchAll(/^\s*import\s+(?:[^;'"()]*?\sfrom\s+)?['"]([^'"]+)['"]/gm)].map(m => m[1]);
    assert.deepEqual(imports.filter(path => /\/(?:Lazy)?Reports\.tsx$/.test(path)), ['./views/LazyReports.tsx']);
    assert.deepEqual(source.match(/<LazyReports\b[^>]*>/g), ['<LazyReports now={now} />']);
    assert.match(source, new RegExp(`<div class="${container}">(?:(?!</div>)[^])*?<Guard name="reports"><LazyReports now=\{now\} /></Guard>`));
  });
}

const {outputFiles: [bundle]} = await build({
  stdin: {resolveDir: fileURLToPath(root), contents: `
    export {createLazyReports} from './web/app/views/LazyReports.tsx';
    export {Guard} from './web/ui/Guard.tsx';
    export {h, render} from 'preact';
    export {act} from 'preact/test-utils';
  `},
  bundle: true, write: false, format: 'esm', platform: 'node',
  jsx: 'automatic', jsxImportSource: 'preact', loader: {'.css': 'empty'},
  // Only the injected loader is called in these tests; do not bundle the real page.
  external: ['./Reports.tsx'],
});
const {createLazyReports, Guard, h, render, act} = await import(`data:text/javascript;base64,${Buffer.from(bundle.contents).toString('base64')}`);

// Minimal DOM for real Preact mounts, unmounts and signal-driven updates.
class Element {
  constructor(localName, data) {
    Object.assign(this, {localName, data, nodeType: data === undefined ? 1 : 3, parentNode: null, childNodes: [], attrs: {}});
  }
  get firstChild() { return this.childNodes[0] ?? null; }
  get nextSibling() { return this.parentNode?.childNodes[this.parentNode.childNodes.indexOf(this) + 1] ?? null; }
  insertBefore(child, ref) {
    child.remove();
    this.childNodes.splice(ref ? this.childNodes.indexOf(ref) : this.childNodes.length, 0, child);
    child.parentNode = this;
    return child;
  }
  appendChild(child) { return this.insertBefore(child, null); }
  remove() {
    if (!this.parentNode) return;
    this.parentNode.childNodes.splice(this.parentNode.childNodes.indexOf(this), 1);
    this.parentNode = null;
  }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  removeAttribute(name) { delete this.attrs[name]; }
  addEventListener(type, listener) { (this.listeners ??= {})[type] = listener; }
  removeEventListener(type) { delete this.listeners?.[type]; }
}

function mountFixture(t) {
  const host = new Element('div');
  const document = globalThis.document;
  globalThis.document = {
    createElement: tag => new Element(tag),
    createElementNS: (_, tag) => new Element(tag),
    createTextNode: data => new Element('#text', String(data)),
  };
  const draw = vnode => act(() => render(vnode, host));
  t.after(async () => {
    try { await draw(null); }
    finally { globalThis.document = document; }
  });
  const tree = ({localName, attrs, childNodes, data}) => data ?? [localName, attrs, childNodes.map(tree)];
  return {draw, output: () => host.childNodes.map(tree), clickRetry: () => {
    const button = host.childNodes[0].childNodes[1];
    return act(() => button.listeners.click.call(button, {type: 'click', target: button}));
  }};
}

const pending = [['article', {class: 'app-reports'}, []]];
const NOW = new Date('2026-11-21T19:00:00Z');
const NEXT = new Date('2026-11-21T20:00:00Z');
const FixtureReports = ({now}) => h('article', {class: 'app-reports'}, now.toISOString());

test('C2: a pending import survives unmount and remount; the live mount receives now', async t => {
  const {draw, output} = mountFixture(t);
  const {promise, resolve} = Promise.withResolvers();
  const load = t.mock.fn(() => promise);
  const Lazy = createLazyReports(load);
  assert.equal(load.mock.callCount(), 0);
  await draw(h(Lazy, {now: NOW}));
  assert.deepEqual(output(), pending);
  assert.equal(load.mock.callCount(), 1);
  await draw(null);
  assert.deepEqual(output(), []);
  await draw(h(Lazy, {now: NEXT}));
  assert.deepEqual(output(), pending);
  assert.equal(load.mock.callCount(), 1);
  await act(async () => resolve({Reports: FixtureReports}));
  assert.deepEqual(output(), [['article', {class: 'app-reports'}, ['2026-11-21T20:00:00.000Z']]]);

  await t.test('C4: reopening after resolution reuses the view without a loading frame', async () => {
    await draw(null);
    await draw(h(Lazy, {now: NOW}));
    assert.deepEqual(output(), [['article', {class: 'app-reports'}, ['2026-11-21T19:00:00.000Z']]]);
    assert.equal(load.mock.callCount(), 1);
  });
});

test('C2: a rejected import reaches the existing Guard with the original error', async t => {
  const {draw, output} = mountFixture(t);
  const {promise, reject} = Promise.withResolvers();
  const Lazy = createLazyReports(() => promise);
  const error = new Error('fixture import failure');
  const log = t.mock.method(console, 'error', () => {});
  await draw(h(Guard, {name: 'reports'}, h(Lazy, {now: NOW})));
  assert.deepEqual(output(), pending);
  await act(async () => reject(error));
  assert.deepEqual(log.mock.calls.map(call => call.arguments), [['[guard]', 'reports', error]]);
  assert.equal(log.mock.calls[0].arguments[2], error);
  assert.deepEqual(output(), [['div', {class: 'ui-guard', role: 'status', 'data-guard': 'reports'}, [
    ['p', {}, ['This part could not load. The rest of the page still works.']], ['button', {type: 'button'}, ['Try again']],
  ]]]);
});

test('a Guard retry reloads a rejected Reports import and renders the recovered view', async t => {
  const {draw, output, clickRetry} = mountFixture(t);
  const first = Promise.withResolvers();
  const second = Promise.withResolvers();
  let attempts = 0;
  const load = t.mock.fn(() => ++attempts === 1 ? first.promise : second.promise);
  const Lazy = createLazyReports(load);
  t.mock.method(console, 'error', () => {});
  await draw(h(Guard, {name: 'reports'}, h(Lazy, {now: NOW})));
  await act(async () => first.reject(new Error('transient chunk error')));
  assert.equal(output()[0][1]['data-guard'], 'reports');
  await clickRetry();
  assert.equal(load.mock.callCount(), 2);
  assert.deepEqual(output(), pending);
  await act(async () => second.resolve({Reports: FixtureReports}));
  assert.deepEqual(output(), [['article', {class: 'app-reports'}, ['2026-11-21T19:00:00.000Z']]]);
});

test('C3: the built app reaches Reports dynamically, not in its startup imports closure', async t => {
  let text;
  try { text = await read(new URL('.vite/manifest.json', built)); }
  catch (error) {
    if (error.code !== 'ENOENT') throw error;
    t.skip('dist/client/.vite/manifest.json is absent; run pnpm build to verify the split');
    return;
  }
  const manifest = JSON.parse(text);
  const reports = '../web/app/views/Reports.tsx';
  const shell = '../web/app/main.tsx';
  const entry = 'app.html';
  function walk(start, edges) {
    const seen = new Set();
    const stack = [...start];
    while (stack.length) {
      const key = stack.pop();
      if (seen.has(key)) continue;
      seen.add(key);
      assert.ok(manifest[key], `missing manifest entry: ${key}`);
      stack.push(...edges(manifest[key]));
    }
    return [...seen];
  }
  // Like check_perf_budget.py: the bootstrap's mandatory shell counts as startup
  // even when it is a dynamic import. Optional routes do not.
  const startup = walk([entry, ...(manifest[entry].dynamicImports ?? []).filter(key => key === shell)], chunk => chunk.imports ?? []);
  const app = walk([entry], chunk => [...(chunk.imports ?? []), ...(chunk.dynamicImports ?? [])]);
  assert.equal(app.some(key => (manifest[key].dynamicImports ?? []).includes(reports)), true);
  assert.equal(manifest[reports].isDynamicEntry, true);
  assert.deepEqual(startup.filter(key => manifest[key].file === manifest[reports].file), []);
  assert.deepEqual(app.flatMap(key => (manifest[key].imports ?? []).filter(target => target === reports)), []);

  await t.test('C5: the new optional chunk is still subject to the existing single-file ceiling', async () => {
    const {budgets} = JSON.parse(await read(new URL('scripts/perf-budget.json', root)));
    const {size} = await stat(new URL(manifest[reports].file, built));
    const limit = budgets.largest_built_file.max_bytes;
    assert.equal(size <= limit, true, `Reports chunk is ${size} bytes, over the ${limit}-byte ceiling`);
  });
});
