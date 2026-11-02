// SC1737-09: the landing's first step after a failed port list. PortInput adds "Try again" after the
// "unavailable" sentence only for an empty list with onRetry; LandingApp, mounted on a small fake DOM,
// offers it after a failed load, shows "Loading ports…" while a retry is in flight, and keeps only the
// newest attempt's answer. loadPorts already forgets a failure (web/ports.ts), so a retry fetches again.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';

const ROOT = new URL('..', import.meta.url).pathname;
// Landing.tsx's loadPorts goes through globalThis.__loadPorts when a test sets it (the attempt guard); otherwise the real one.
const stub = {name: 'ports-stub', setup(b) {
  b.onResolve({filter: /^\.\.\/ports\.ts$/}, a => a.importer.endsWith('Landing.tsx') ? {path: 'ports', namespace: 'stub'} : undefined);
  b.onLoad({filter: /.*/, namespace: 'stub'}, () => ({resolveDir: join(ROOT, 'web'), loader: 'ts', contents:
    "import {loadPorts as real} from './ports.ts'; export * from './ports.ts'; export const loadPorts = () => (globalThis.__loadPorts ?? real)();"}));
}};
const out = join(await mkdtemp(join(tmpdir(), 'port-retry-')), 'm.mjs');
await build({stdin: {resolveDir: ROOT, loader: 'ts', contents: `
  export {LandingApp} from './web/landing/Landing.tsx';
  export {PortInput} from './web/landing/PortInput.tsx';
  export {COPY, PORTS_URL} from './web/ports.ts';
  export {render as html} from 'preact-render-to-string';
  export {h, render} from 'preact';`},
bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: [stub]});
const {LandingApp, PortInput, COPY, PORTS_URL, html, h, render} = await import(pathToFileURL(out).href);

const UNAVAILABLE = 'Port choices are unavailable. Explore the coast instead.';
const port = (id, name) => ({id, name, region: id, status: 'active', forecast_point: id, forecast_name: name, match: [35, -120]});
const MORRO = [port('morro-bay', 'Morro Bay')];
const DIEGO = [port('san-diego', 'San Diego')];
const noop = () => {};
const base = {onChoose: noop, onExplore: noop, storage: null, cookies: null};
const settle = () => new Promise(r => setTimeout(r, 60));
const deferred = () => { let resolve, reject; const promise = new Promise((y, n) => { resolve = y; reject = n; }); return {promise, resolve, reject}; };

// A DOM just big enough for preact: nodes, text, attributes and one listener per event type.
class Node {
  constructor(type, name) { Object.assign(this, {nodeType: type, nodeName: name, childNodes: [], parentNode: null, on: {}, attrs: {}}); }
  get firstChild() { return this.childNodes[0] ?? null; }
  get nextSibling() { const i = this.parentNode?.childNodes.indexOf(this) ?? -1; return i < 0 ? null : this.parentNode.childNodes[i + 1] ?? null; }
  remove() { this.parentNode?.removeChild(this); }
  removeChild(c) { this.childNodes.splice(this.childNodes.indexOf(c), 1); c.parentNode = null; return c; }
  insertBefore(c, ref) { c.parentNode?.removeChild(c); const i = ref ? this.childNodes.indexOf(ref) : -1; this.childNodes.splice(i < 0 ? this.childNodes.length : i, 0, c); c.parentNode = this; return c; }
  appendChild(c) { return this.insertBefore(c, null); }
  setAttribute(k, v) { this.attrs[k] = String(v); } removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(t, f) { this.on[t] = f; } removeEventListener(t) { delete this.on[t]; }
  focus() {}
}
class El extends Node { constructor(name) { super(1, name.toUpperCase()); this.style = {}; this.localName = name; } }
class Text extends Node { constructor(t) { super(3, '#text'); this.data = String(t); } }
globalThis.document = {createElement: n => new El(n), createElementNS: (_, n) => new El(n), createTextNode: t => new Text(t)};
const text = n => n.nodeType === 3 ? n.data : n.childNodes.map(text).join('');
const find = (n, tag) => [...(n.localName === tag ? [n] : []), ...n.childNodes.flatMap(c => find(c, tag))];
const retries = root => find(root, 'button').filter(b => text(b).trim() === 'Try again');
// preact registers 'Click' here (no onclick property on these nodes); the event's type must match the registered name.
const fire = (el, type, extra = {}) => { const t = Object.keys(el.on).find(k => k.toLowerCase() === type); return el.on[t].call(el, {type: t, ...extra}); };
const rejections = [];
process.on('unhandledRejection', e => rejections.push(e));

test('1-3: PortInput: Try again only for an empty list with onRetry; one click calls it once; without it, today\'s HTML', async () => {
  const without = html(h(PortInput, {...base, ports: []}));
  const withRetry = html(h(PortInput, {...base, ports: [], onRetry: noop}));
  assert.ok(without.includes(UNAVAILABLE) && !without.includes('Try again'), 'no onRetry: the sentence and no button');
  assert.match(withRetry, new RegExp(`${UNAVAILABLE.replace(/\./g, '\\.')}</p><button [^>]*>Try again</button>`), 'the button follows the sentence');
  assert.equal(withRetry.replace(/<button [^>]*>Try again<\/button>/, ''), without, 'the button is the only difference');
  assert.doesNotMatch(html(h(PortInput, {...base, ports: null, onRetry: noop})), /Try again/, 'not while loading');
  const root = new El('div');
  let calls = 0;
  render(h(PortInput, {...base, ports: [], onRetry: () => { calls++; }}), root);
  fire(retries(root)[0], 'click');
  assert.equal(calls, 1, 'one click, one retry');
  // A loaded list with a query that matches nothing: the empty-search sentence, never Try again.
  render(h(PortInput, {...base, ports: MORRO, onRetry: () => { calls++; }}), root);
  fire(find(root, 'input')[0], 'input', {currentTarget: {value: 'zzzz'}});
  await settle();
  assert.ok(text(root).includes(COPY.empty) && !text(root).includes(UNAVAILABLE));
  assert.equal(retries(root).length, 0, 'a loaded list never offers Try again');
  render(null, root);
});

test('4-5: LandingApp: a failed list offers Try again; a second failure keeps one button; a good retry loads the list', async () => {
  const answers = [() => new Response('', {status: 503}), () => { throw new TypeError('Failed to fetch'); }];
  const gate = deferred();
  answers.push(async () => { await gate.promise; return Response.json({schema_version: 1, ports: MORRO}); });
  const asked = [];
  globalThis.fetch = async url => { if (url !== PORTS_URL) return new Response('', {status: 404}); asked.push(url); return answers.shift()(); };
  const root = new El('div');
  render(h(LandingApp, {href: 'https://s.test/', navigate: noop, warm: async () => ({state: 'ready'})}), root);
  await settle();
  assert.ok(text(root).includes(UNAVAILABLE));
  assert.equal(retries(root).length, 1, 'the first failure offers Try again');
  fire(retries(root)[0], 'click');
  await settle();
  assert.equal(asked.length, 2, 'the retry fetched again');
  assert.equal(retries(root).length, 1, 'a second failure: still exactly one Try again');
  fire(retries(root)[0], 'click');
  await settle();
  assert.ok(text(root).includes('Loading ports…'), 'the retry in flight shows Loading ports…');
  assert.equal(retries(root).length, 0);
  gate.resolve();
  await settle();
  assert.equal(asked.length, 3);
  assert.ok(text(root).includes('Morro Bay') && !text(root).includes(UNAVAILABLE), 'the list loaded');
  assert.equal(retries(root).length, 0, 'no Try again once the list loaded');
  assert.equal(rejections.length, 0, 'no uncaught rejection');
  render(null, root);
});

test('6: an earlier attempt answering after the newest one never overwrites it', async () => {
  const attempts = [];
  globalThis.fetch = async () => new Response('', {status: 404});
  globalThis.__loadPorts = () => { const d = deferred(); attempts.push(d); return d.promise; };
  const root = new El('div');
  render(h(LandingApp, {href: 'https://s.test/', navigate: noop, warm: async () => ({state: 'ready'})}), root);
  await settle();
  attempts[0].reject(Error('offline'));
  await settle();
  const button = retries(root)[0];
  fire(button, 'click'); fire(button, 'click'); fire(button, 'click');
  assert.equal(attempts.length, 4, 'three quick clicks, three attempts');
  attempts[3].resolve(MORRO);
  await settle();
  attempts[2].reject(Error('late failure'));
  attempts[1].resolve(DIEGO);
  await settle();
  assert.ok(text(root).includes('Morro Bay') && !text(root).includes('San Diego'), 'the newest list stays');
  assert.equal(retries(root).length, 0, 'a late failure does not bring Try again back');
  assert.equal(rejections.length, 0);
  delete globalThis.__loadPorts;
  render(null, root);
});
