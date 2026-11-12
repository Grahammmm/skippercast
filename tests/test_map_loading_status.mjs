// RF2115-5: the Chart's loading status is one live node that follows the visit-wide first-idle signal
// (web/map-ready.ts) and the language; it never restarts once settled. Real Preact on a minimal mounted DOM.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {preparedRendererPlugins} from './helpers/esbuild-url.mjs';

const dir = await mkdtemp(join(tmpdir(), 'map-loading-'));
const out = join(dir, 'component.mjs');
await build({stdin: {resolveDir: process.cwd(), loader: 'ts', contents: `
  export {PresentationToggle} from './web/app/MapStage.tsx';
  export {mapFirstIdle} from './web/map-ready.ts';
  export {chartFailed} from './web/map/chart.ts';
  export {setLanguage} from './web/i18n.ts';
  export * as state from './web/state.ts';
  export {h, render} from 'preact';
  export {act} from 'preact/test-utils';`}, bundle: true, format: 'esm', platform: 'node',
outfile: out, jsx: 'automatic', jsxImportSource: 'preact', logLevel: 'silent', plugins: preparedRendererPlugins});
const {PresentationToggle, mapFirstIdle, chartFailed, setLanguage, state, h, render, act} = await import(pathToFileURL(out).href);
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
    const index = ref ? this.childNodes.indexOf(ref) : this.childNodes.length;
    this.childNodes.splice(index, 0, child); child.parentNode = this; return child;
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
const find = (node, p) => [...(p(node) ? [node] : []), ...node.childNodes.flatMap(n => find(n, p))];
const none = {getItem: () => null, setItem() {}};
const memory = () => { const m = new Map(); return {getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v))}; };

async function withMount(url, body) {
  const idle = mapFirstIdle.peek(), failed = chartFailed.peek();
  state.configureStore({v2: true, storage: memory()});
  state.syncFromURL(url);
  const root = new Element('div');
  const node = () => find(root, n => n.attrs?.['data-chart-loading-status'] !== undefined)[0];
  try { await act(() => render(h(PresentationToggle, {}), root)); await body({root, node}); }
  finally { await act(() => render(null, root)); mapFirstIdle.value = idle; chartFailed.value = failed; setLanguage('en', {storage: none, doc: null}); }
}
const CHART = 'https://s.test/map?region=morro-bay&presentation=chart';

test('pending: one polite atomic status with the English text; settling empties the same node; it never returns', async () => {
  await withMount(CHART, async ({node}) => {
    await act(() => { mapFirstIdle.value = false; chartFailed.value = false; });
    const live = node();
    assert.equal(text(live), 'Loading the map…');
    assert.equal(live.attrs.role, 'status'); assert.equal(live.attrs['aria-live'], 'polite'); assert.equal(live.attrs['aria-atomic'], 'true');
    await act(() => { mapFirstIdle.value = true; });
    assert.equal(node(), live, 'same live node'); assert.equal(text(live), '');
    await act(() => { chartFailed.value = false; state.syncFromURL('https://s.test/map?region=morro-bay&presentation=2d'); });
    await act(() => { state.syncFromURL(CHART); });
    assert.equal(text(node()), '', 'a second Chart visit after first idle does not restart the cue');
  });
});
test('language change while pending rewrites the same node in Spanish', async () => {
  await withMount(CHART, async ({node}) => {
    await act(() => { mapFirstIdle.value = false; chartFailed.value = false; });
    const live = node();
    await act(() => setLanguage('es', {storage: none, doc: null}));
    assert.equal(node(), live); assert.equal(text(live), 'Cargando el mapa…');
  });
});
test('failure clears the cue; terrain hides it and switching to Chart shows it only while unresolved', async () => {
  await withMount(CHART, async ({node}) => {
    await act(() => { mapFirstIdle.value = false; chartFailed.value = true; });
    assert.equal(text(node()), '', 'failed Chart is not loading');
    await act(() => { chartFailed.value = false; state.syncFromURL('https://s.test/map?region=morro-bay&presentation=2d'); });
    assert.equal(text(node()), '', 'terrain shown: nothing spoken');
    await act(() => { state.syncFromURL(CHART); });
    assert.equal(text(node()), 'Loading the map…');
  });
});
