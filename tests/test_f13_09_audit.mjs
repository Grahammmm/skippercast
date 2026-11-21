// F13-09: real Preact controls and tide selection, with only synthetic, in-memory responses.
import assert from 'node:assert/strict';
import test from 'node:test';
import {fileURLToPath} from 'node:url';
import {build} from 'esbuild';

const {outputFiles: [bundle]} = await build({
  stdin: {resolveDir: fileURLToPath(new URL('..', import.meta.url)), contents: `
    export {TideStationControl} from './web/brief/TideStationControl.tsx';
    export {tideSelection} from './web/tide-selection.ts';
    export {TIDE_DIRECTORY_URL, tideSavedKey} from './web/tide-stations.ts';
    export {PORTS_URL} from './web/ports.ts';
    export {h, render} from 'preact';
    export {act} from 'preact/test-utils';`},
  bundle: true, write: false, format: 'esm', platform: 'node', jsx: 'automatic', jsxImportSource: 'preact',
});
const moduleURL = `data:text/javascript;base64,${Buffer.from(bundle.contents).toString('base64')}`;

// Just enough DOM for Preact to render and dispatch its own event handlers.
class Element {
  constructor(name, data) {
    Object.assign(this, {localName: name, nodeType: data === undefined ? 1 : 3, data,
      childNodes: [], parentNode: null, attrs: {}, style: {}, listeners: {}});
    if (name === 'button') this.disabled = false;
    if (name === 'select' || name === 'option') this.value = '';
  }
  get firstChild() { return this.childNodes[0] ?? null; }
  get nextSibling() { return this.parentNode?.childNodes[this.parentNode.childNodes.indexOf(this) + 1] ?? null; }
  insertBefore(child, ref) {
    child.parentNode?.removeChild(child);
    this.childNodes.splice(ref ? this.childNodes.indexOf(ref) : this.childNodes.length, 0, child);
    child.parentNode = this;
  }
  removeChild(child) { this.childNodes.splice(this.childNodes.indexOf(child), 1); child.parentNode = null; }
  remove() { this.parentNode?.removeChild(this); }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  removeAttribute(key) { delete this.attrs[key]; }
  addEventListener(type, listener) { this.listeners[type] = listener; }
  removeEventListener(type) { delete this.listeners[type]; }
  dispatch(type) { this.listeners[type].call(this, {type, target: this, currentTarget: this}); }
}
const nodes = node => [node, ...node.childNodes.flatMap(nodes)];
const text = node => node.nodeType === 3 ? node.data : node.childNodes.map(text).join('');
const button = (root, label) => {
  const found = nodes(root).find(n => n.localName === 'button' && (n.attrs['aria-label'] ?? text(n)) === label);
  assert.ok(found, `Expected button: ${label}`);
  return found;
};

const A = '9000001', B = '9000002';
const region = {id: 'fixture', name: 'Fixture Region', bounds: [0, 0, 10, 10], station: '9000000'};
const stations = [
  {id: A, name: 'Station A', lat: 2, lng: 2, type: 'S'},
  {id: B, name: 'Station B', lat: 8, lng: 8, type: 'S'},
];
const ports = {schema_version: 1, ports: [{id: 'fixture-port', region: region.id, status: 'active',
  name: 'Fixture Port', match: [1, 1], forecast_point: 'fixture', forecast_name: 'Fixture Forecast'}]};
const nearest = 'Use nearest to port';
const nearestNotice = 'Nearest listed station to Fixture Port: Station A.';

for (const scenario of [
  {name: 'saved B in another layout wins over the late nearest A', action: 'Use Station B', other: true, active: B},
  {name: 'adding B wins over the late nearest A', action: 'Add current station', draft: B, active: B, notice: 'Station B saved and active.'},
  {name: 'removing A is not undone by the late nearest A', action: 'Remove Station A', initial: A, active: null, notice: 'Station A removed from saved stations.'},
  {name: 'choosing the region default wins over the late nearest A', draft: '', initial: B, active: null},
  {name: 'a current nearest request still activates A and announces it', active: A, notice: nearestNotice},
]) {
  test(scenario.name, async t => {
    // Fresh singleton and directory cache for each scenario, shared by its two mounted layouts.
    const {TideStationControl, tideSelection, TIDE_DIRECTORY_URL, tideSavedKey, PORTS_URL, h, render, act} =
      await import(`${moduleURL}#${encodeURIComponent(scenario.name)}`);
    const flush = () => act(() => new Promise(setImmediate));
    const roots = [new Element('div'), new Element('div')];
    const saved = scenario.action === 'Add current station' ? [A] : [A, B];
    const key = tideSavedKey(region.id);
    const storage = new Map([[key, JSON.stringify({saved, active: scenario.initial ?? null})]]);
    const {promise: pendingPorts, resolve: releasePorts} = Promise.withResolvers();
    const requests = [];
    const globals = {
      document: {createElement: name => new Element(name), createElementNS: (_, name) => new Element(name), createTextNode: data => new Element('#text', String(data))},
      localStorage: {getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value)},
      fetch: async url => {
        requests.push(url);
        if (url === PORTS_URL) return pendingPorts;
        if (url === TIDE_DIRECTORY_URL) return Response.json({stations});
        const parsed = new URL(url);
        assert.equal(parsed.pathname, '/api/prod/datagetter');
        assert.ok([A, B].includes(parsed.searchParams.get('station')));
        return Response.json({predictions: [{t: '2026-01-01 12:00', v: '2', type: 'H'}]});
      },
    };
    const previous = Object.fromEntries(Object.keys(globals).map(k => [k, Object.getOwnPropertyDescriptor(globalThis, k)]));
    for (const [key, value] of Object.entries(globals)) Object.defineProperty(globalThis, key, {value, configurable: true, writable: true});
    t.after(async () => {
      await act(() => roots.forEach(root => render(null, root)));
      for (const [key, descriptor] of Object.entries(previous)) {
        if (descriptor) Object.defineProperty(globalThis, key, descriptor);
        else delete globalThis[key];
      }
    });
    tideSelection.configure(region);
    await flush();
    await act(() => roots.forEach(root => render(h(TideStationControl), root)));
    const initialLabel = stations.find(s => s.id === scenario.initial)?.name ?? region.name;
    const click = (root, label) => act(() => button(root, label).dispatch('click'));
    for (const root of roots) await click(root, `Tide station: ${initialLabel}`);
    const [requesting, other] = roots;
    const manual = scenario.other ? other : requesting;
    await click(requesting, nearest);
    assert.ok(requests.includes(PORTS_URL) && button(requesting, nearest).disabled, 'nearest is waiting for ports');
    if (scenario.draft !== undefined) {
      const select = nodes(manual).find(n => n.localName === 'select');
      await act(() => { select.value = scenario.draft; select.dispatch('change'); });
    }
    if (scenario.action) await click(manual, scenario.action);
    if (scenario.action || scenario.draft !== undefined) {
      assert.equal(tideSelection.choice.peek(), scenario.active, 'manual action took effect before ports resolved');
    }
    releasePorts(Response.json(ports));
    await flush();
    assert.equal(button(requesting, nearest).disabled, false, 'nearest has settled');
    const statuses = roots.flatMap(root => nodes(root).filter(n => n.attrs.role === 'status').map(text));
    assert.deepEqual({active: tideSelection.choice.peek(), statuses}, {
      active: scenario.active, statuses: scenario.notice ? [scenario.notice] : [],
    });
    const expectedSaved = scenario.action === 'Remove Station A' ? [B] : [A, B];
    assert.deepEqual(JSON.parse(storage.get(key)), {saved: expectedSaved, active: scenario.active});
    if (scenario.active) assert.equal(tideSelection.reading.peek()?.station.id, scenario.active);
  });
}
