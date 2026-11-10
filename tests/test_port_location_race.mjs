import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';

const dir = await mkdtemp(join(tmpdir(), 'port-location-'));
const out = join(dir, 'component.mjs');
await build({stdin: {resolveDir: process.cwd(), loader: 'ts', contents: `
  export {PortInput} from './web/landing/PortInput.tsx';
  export {language, prepareCatalogue} from './web/landing/i18n.ts';
  export {portCopy} from './web/landing/copy.ts';
  export {h, render} from 'preact';
  export {act} from 'preact/test-utils';`}, bundle: true, format: 'esm', platform: 'node',
  outfile: out, jsx: 'automatic', jsxImportSource: 'preact', logLevel: 'silent'});
const {PortInput, h, render, act, language, portCopy, prepareCatalogue} = await import(pathToFileURL(out).href);
await prepareCatalogue('es');
test.after(() => rm(dir, {recursive: true, force: true}));

// Minimal mounted DOM, with real Preact event dispatch and observable focus.
class Element {
  constructor(name, data) {
    Object.assign(this, {localName: name, nodeName: name.toUpperCase(), nodeType: data === undefined ? 1 : 3,
      data, childNodes: [], parentNode: null, attrs: {}, on: {}, style: {}, value: ''});
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
  focus() { document.activeElement = this; }
}
globalThis.document = {createElement: name => new Element(name), createElementNS: (_, name) => new Element(name),
  createTextNode: data => new Element('#text', String(data)), activeElement: null};
const text = node => node.nodeType === 3 ? node.data : node.childNodes.map(text).join('');
const all = (node, predicate) => [...(predicate(node) ? [node] : []), ...node.childNodes.flatMap(n => all(n, predicate))];
const fire = (node, type) => {
  const key = Object.keys(node.on).find(k => k.toLowerCase() === type);
  node.on[key].call(node, {type: key, currentTarget: node, preventDefault() {}});
};
const port = (id, name, match) => ({id, name, match, region: id, status: 'active', forecast_point: id, forecast_name: name});
const north = port('north-fixture', 'North fixture', [35, -120]);
const south = port('south-fixture', 'South fixture', [34, -120]);
const ports = [north, south];
const geo = () => ({calls: [], getCurrentPosition(ok, fail) { this.calls.push({ok, fail}); }});
const answer = (g, i, outcome) => ['failure', 'denied'].includes(outcome) ? g.calls[i].fail({code: outcome === 'denied' ? 1 : 3}) :
  g.calls[i].ok({coords: {latitude: outcome === 'none' ? 0 : outcome === 'south' ? 34 : 35, longitude: outcome === 'none' ? 0 : -120}});
function mount(extra = {}) {
  const root = new Element('div'), chosen = [], explored = [];
  let props = {ports, geolocation: geo(), storage: null, cookies: null,
    onChoose: p => chosen.push(p), onExplore: () => explored.push(true), ...extra};
  const update = async patch => { props = {...props, ...patch}; await act(() => render(h(PortInput, props), root)); };
  const input = () => all(root, n => n.localName === 'input')[0];
  const button = label => all(root, n => n.localName === 'button' && text(n).trim() === label)[0];
  const click = async label => act(() => fire(button(label), 'click'));
  const type = async value => act(() => { input().value = value; fire(input(), 'input'); });
  const submit = async () => act(() => fire(all(root, n => n.localName === 'form')[0], 'submit'));
  const snapshot = () => ({query: input().value,
    ids: all(root, n => n.attrs['data-port']).map(n => n.attrs['data-port']).join(','),
    feedback: text(all(root, n => n.attrs.role === 'status')[0]), focus: document.activeElement});
  return {root, chosen, explored, update, input, click, type, submit, snapshot,
    get geolocation() { return props.geolocation; },
    resolve: async (i, outcome) => act(() => answer(props.geolocation, i, outcome)),
    unmount: async () => act(() => render(null, root))};
}

for (const outcome of ['north', 'failure', 'denied', 'none', 'unsupported']) {
  test(`manual query supersedes pending ${outcome}`, async () => {
    const m = mount(outcome === 'unsupported' ? {geolocation: null} : {}); await m.update({});
    // Invalidate synchronously, even before an immediately resolved unsupported answer resumes.
    await act(() => { fire(all(m.root, n => n.localName === 'button' && text(n) === 'Use my location')[0], 'click');
      m.input().value = 'South'; fire(m.input(), 'input'); });
    const outside = new Element('button'); outside.focus(); const before = m.snapshot();
    if (outcome !== 'unsupported') await m.resolve(0, outcome);
    assert.equal(m.snapshot().query, 'South'); assert.equal(m.snapshot().ids, south.id);
    assert.equal(m.snapshot().feedback, before.feedback); assert.ok(document.activeElement === outside, 'obsolete answer preserves outside focus');
    await m.submit(); assert.equal(m.chosen.length, 1); assert.equal(m.chosen[0], south);
    await m.unmount();
  });
}
for (const old of ['north', 'failure', 'denied', 'none']) for (const order of ['old-first', 'new-first']) {
  test(`latest attempt wins: ${old}, ${order}`, async () => {
    const m = mount(); await m.update({}); await m.click('Use my location'); await m.click('Use my location');
    const outside = new Element('button'); outside.focus();
    if (order === 'old-first') {
      const before = m.snapshot(); await m.resolve(0, old);
      assert.equal(m.snapshot().feedback, before.feedback); assert.equal(m.snapshot().ids, before.ids);
    }
    await m.resolve(1, 'south'); const before = m.snapshot();
    if (order === 'new-first') await m.resolve(0, old);
    assert.equal(m.snapshot().ids, south.id); assert.equal(m.snapshot().feedback, before.feedback);
    assert.ok(document.activeElement === outside, 'obsolete answer preserves outside focus'); assert.equal(m.chosen.length, 0);
    // A duplicate device callback cannot publish a second result.
    await m.resolve(1, 'north'); assert.equal(m.snapshot().ids, south.id);
    await m.unmount();
  });
}
test('current failure, none, unsupported and explicit retry retain ordinary controls', async () => {
  const m = mount(); await m.update({}); await m.type('South'); await m.click('Use my location');
  await m.resolve(0, 'failure'); assert.equal(m.snapshot().query, 'South');
  assert.match(m.snapshot().feedback, /timed out/); assert.ok(document.activeElement === m.input(), 'current failure focuses search');
  await m.click('Use my location'); await m.resolve(1, 'none'); assert.match(m.snapshot().feedback, /No listed port/);
  await m.update({geolocation: null}); await m.click('Use my location'); assert.equal(m.snapshot().feedback, 'Location is unavailable. Search for a port instead.');
  await m.update({geolocation: geo()}); await m.click('Use my location'); await m.resolve(0, 'north');
  assert.equal(m.snapshot().query, ''); assert.equal(m.snapshot().ids, north.id); assert.equal(m.chosen.length, 0);
  await m.submit(); assert.equal(m.chosen[0], north); await m.unmount();
});
for (const boundary of ['option', 'submit', 'explore', 'unmount', 'ports', 'geolocation', 'empty', 'loading']) {
  for (const outcome of ['north', 'failure', 'denied']) test(`${boundary} discards late ${outcome}`, async () => {
    const m = mount(); await m.update({}); await m.type('South'); await m.click('Use my location');
    const old = m.geolocation;
    if (boundary === 'option') await act(() => fire(all(m.root, n => n.attrs['data-port'] === south.id)[0], 'click'));
    else if (boundary === 'submit') await m.submit();
    else if (boundary === 'explore') await m.click('Explore the coast');
    else if (boundary === 'unmount') { await m.unmount(); await m.update({}); }
    else await m.update(boundary === 'geolocation' ? {geolocation: geo()} :
      {ports: boundary === 'empty' ? [] : boundary === 'loading' ? null : [south]});
    const outside = new Element('button'); outside.focus(); const before = m.snapshot();
    await act(() => answer(old, 0, outcome));
    assert.equal(m.snapshot().query, before.query); assert.equal(m.snapshot().ids, before.ids);
    assert.equal(m.snapshot().feedback, before.feedback); assert.ok(document.activeElement === outside, 'obsolete answer preserves outside focus');
    assert.equal(m.chosen.length, ['option', 'submit'].includes(boundary) ? 1 : 0);
    if (m.chosen.length) assert.equal(m.chosen[0], south);
    assert.equal(m.explored.length, boundary === 'explore' ? 1 : 0); await m.unmount();
  });
}
test('locate waits for directory; replacement and fresh instances have independent attempts', async () => {
  const m = mount({ports: null, locate: true}); await m.update({}); assert.equal(m.geolocation.calls.length, 0);
  await m.update({ports}); assert.equal(m.geolocation.calls.length, 1);
  const old = m.geolocation; await m.update({ports: [south]}); assert.equal(old.calls.length, 2);
  await m.resolve(1, 'south'); await m.resolve(0, 'north'); assert.equal(m.snapshot().ids, south.id);
  await m.unmount();
  const fresh = mount(); await fresh.update({}); await fresh.type('South'); await fresh.submit();
  assert.equal(fresh.chosen[0], south); assert.equal(fresh.geolocation.calls.length, 0); await fresh.unmount();
});

const status = m => all(m.root, n => n.attrs.role === 'status')[0];
const errorIcon = m => all(status(m), n => n.localName === 'svg');
for (const lang of ['en', 'es']) for (const [code, reason] of [[1, 'denied'], [2, 'unavailable'], [3, 'timedOut'], [99, 'unavailable'], [undefined, 'unavailable']]) {
  test(`mounted location reason ${code} in ${lang}: stable polite region, no raw text, retry clears icon`, async () => {
    language.value = lang;
    const m = mount();
    try {
      await m.update({}); const region = status(m);
      assert.equal(text(region), ''); assert.equal(errorIcon(m).length, 0);
      assert.equal(region.attrs['aria-live'], 'polite'); assert.equal(region.attrs['aria-atomic'], 'true');
      await m.type('South'); await m.click(lang === 'en' ? 'Use my location' : 'Usar mi ubicación');
      await act(async () => { m.geolocation.calls[0].fail({code, message: 'synthetic provider detail'}); });
      assert.equal(status(m), region); assert.equal(text(region), portCopy(lang)[reason]);
      assert.equal(m.snapshot().query, 'South'); assert.equal(m.snapshot().ids, south.id);
      assert.ok(document.activeElement === m.input()); assert.ok(region.attrs.class.includes('port-input-feedback--error'));
      assert.equal(errorIcon(m).length, 1); assert.equal(errorIcon(m)[0].attrs['aria-hidden'], 'true');
      assert.equal(all(region, n => n.localName === 'title' || n.attrs.role === 'alert').length, 0);
      assert.equal(text(m.root).includes('synthetic provider detail'), false);
      await m.click(lang === 'en' ? 'Use my location' : 'Usar mi ubicación');
      assert.equal(errorIcon(m).length, 0); assert.equal(m.geolocation.calls.length, 2);
      await m.resolve(1, 'north'); assert.equal(errorIcon(m).length, 0);
      assert.equal(text(region), portCopy(lang).found(north)); assert.equal(m.chosen.length, 0);
    } finally { await m.unmount(); language.value = 'en'; }
  });
}
test('pending and retained feedback follows current language without another lookup', async () => {
  const m = mount(); await m.update({});
  try {
    await m.click('Use my location');
    await act(() => { language.value = 'es'; });
    assert.equal(m.snapshot().feedback, portCopy('es').finding);
    await m.resolve(0, 'denied'); assert.equal(m.snapshot().feedback, portCopy('es').denied);
    await act(() => { language.value = 'en'; });
    assert.equal(m.snapshot().feedback, portCopy('en').denied); assert.equal(m.geolocation.calls.length, 1);
    await m.click('Use my location'); await m.resolve(1, 'north');
    await act(() => { language.value = 'es'; });
    assert.equal(m.snapshot().feedback, portCopy('es').found(north));
    await m.type('South'); assert.equal(m.snapshot().feedback, ''); assert.equal(errorIcon(m).length, 0);
    await m.submit(); assert.equal(m.chosen[0], south);
  } finally { await m.unmount(); language.value = 'en'; }
});
