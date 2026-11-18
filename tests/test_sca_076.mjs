// SCA-076: the real admin views with a deferred, offline request sink, and
// the Worker's capability with synthetic sessions and no fleet data reads.
import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {build} from 'esbuild';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';
import {withSessions} from './fixtures/test-sessions.mjs';

const healthPath = '/api/admin/health';
const capability = '/api/admin/fleet/capability';
const queuePath = '/api/admin/reviews?status=open';
const fleetList = '/api/admin/fleet/reviews?status=open';
const checked_at = '2026-01-01T00:00:00.000Z';
const health = {enabled: true, checked_at};
const {outputFiles: [bundle]} = await build({
  stdin: {resolveDir: fileURLToPath(new URL('..', import.meta.url)), contents: `
    export {App} from './web/admin/app.tsx';
    export {ADMIN_COPY as copy} from './web/advisor/copy.ts';
    export {h, render} from 'preact';
    export {act} from 'preact/test-utils';`},
  bundle: true, write: false, format: 'esm', platform: 'node', jsx: 'automatic', jsxImportSource: 'preact',
});
const {App, copy, h, render, act} = await import(`data:text/javascript;base64,${Buffer.from(bundle.contents).toString('base64')}`);

// Minimal in-memory tree for Preact; no browser, network or clipboard.
class Element {
  constructor(name, data) {
    Object.assign(this, {localName: name, nodeName: name.toUpperCase(), nodeType: data === undefined ? 1 : 3,
      data, childNodes: [], parentNode: null, attrs: {}, style: {}});
  }
  get firstChild() { return this.childNodes[0] ?? null; }
  get nextSibling() { return this.parentNode?.childNodes[this.parentNode.childNodes.indexOf(this) + 1] ?? null; }
  insertBefore(child, ref) {
    child.parentNode?.removeChild(child);
    this.childNodes.splice(ref ? this.childNodes.indexOf(ref) : this.childNodes.length, 0, child);
    child.parentNode = this;
    return child;
  }
  removeChild(child) { this.childNodes.splice(this.childNodes.indexOf(child), 1); child.parentNode = null; }
  remove() { this.parentNode?.removeChild(this); }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  removeAttribute(key) { delete this.attrs[key]; }
  addEventListener() {}
  removeEventListener() {}
}
const nodes = node => [node, ...node.childNodes.flatMap(nodes)];
const text = node => node.nodeType === 3 ? node.data : node.childNodes.map(text).join('');
const flush = () => act(() => new Promise(resolve => setImmediate(resolve)));

async function mount(t, hash) {
  const root = new Element('div');
  const events = new EventTarget();
  const requests = [];
  const location = {hash};
  const bindings = {
    document: {createElement: name => new Element(name), createElementNS: (_, name) => new Element(name),
      createTextNode: data => new Element('#text', String(data))},
    location, addEventListener: events.addEventListener.bind(events), removeEventListener: events.removeEventListener.bind(events),
    fetch: (path, init) => new Promise(resolve => requests.push({path, method: init?.method ?? 'GET', resolve})),
  };
  const originals = Object.fromEntries(Object.keys(bindings).map(k => [k, Object.getOwnPropertyDescriptor(globalThis, k)]));
  for (const [key, value] of Object.entries(bindings)) Object.defineProperty(globalThis, key, {value, configurable: true, writable: true});
  t.after(async () => {
    await act(() => render(null, root));
    for (const [key, descriptor] of Object.entries(originals)) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else delete globalThis[key];
    }
  });
  await act(() => render(h(App), root));
  return {
    requests,
    respond: async (path, status, body) => {
      const req = requests.find(r => r.path === path && !r.done);
      assert.ok(req, `Expected ${path}; got ${requests.map(r => r.path).join(', ')}`);
      req.done = true;
      req.resolve(new Response(body === undefined ? null : JSON.stringify(body), {status}));
      await flush();
      await flush();
    },
    go: async hash => {
      await act(() => { location.hash = hash; events.dispatchEvent(new Event('hashchange')); });
      await flush();
    },
    body: () => text(root),
    links: () => nodes(root).filter(n => n.localName === 'a').map(n => n.attrs.href),
  };
}

const requestedFleetData = ui => ui.requests.filter(r => r.path.startsWith('/api/admin/fleet/') && r.path !== capability);

test('advisor queue mounts and loads while fleet is unresolved; fleet list loads only after navigation', async t => {
  const ui = await mount(t, '#queue');
  await ui.respond(healthPath, 200, health);
  assert.ok(ui.body().includes(copy.queueHeading), 'queue must mount before fleet answers');
  await ui.respond(queuePath, 200, {items: [], next: null});
  assert.ok(ui.body().includes(copy.empty));
  assert.deepEqual(requestedFleetData(ui), []);
  assert.ok(!ui.links().includes('#fleet-review'));

  await ui.respond(capability, 204);
  assert.deepEqual(requestedFleetData(ui), []);
  assert.ok(ui.links().includes('#fleet-review'));
  await ui.go('#fleet-review');
  assert.deepEqual(requestedFleetData(ui).map(r => [r.method, r.path]), [['GET', fleetList]]);
});

test('disabled fleet deep link never mounts its view, including while capability is pending', async t => {
  const ui = await mount(t, '#fleet-review');
  await ui.respond(healthPath, 200, health);
  assert.ok(ui.body().includes(copy.loading));
  assert.deepEqual(requestedFleetData(ui), []);
  await ui.respond(capability, 404);
  assert.ok(ui.body().includes(copy.queueHeading));
  assert.ok(!ui.links().includes('#fleet-review'));
  assert.deepEqual(requestedFleetData(ui), []);
});

for (const statuses of [[401, 401], [404, 404], [403, 204], [500, 404], [200, 404]]) {
  test(`unconfirmed admin stays closed (health ${statuses[0]}, fleet ${statuses[1]})`, async t => {
    const ui = await mount(t, '#queue');
    await ui.respond(healthPath, statuses[0], {}); // a generic success body is not a Health result either
    await ui.respond(capability, statuses[1]);
    assert.ok(ui.body().includes(copy.signedOut));
    assert.deepEqual(ui.links(), ['/']);
    assert.ok(!ui.requests.some(r => r.path === queuePath));
    assert.deepEqual(requestedFleetData(ui), []);
  });
}

test('a confirmed fleet deep link does not wait for advisor health', async t => {
  const ui = await mount(t, '#fleet-review');
  await ui.respond(capability, 204);
  assert.ok(ui.links().includes('#fleet-review'));
  assert.deepEqual(requestedFleetData(ui).map(r => r.path), [fleetList]);
  assert.ok(!ui.requests.some(r => r.path === queuePath));
});

test('Worker capability returns no data and inherits the fleet flag, session and admin checks', {skip: sqliteUnavailable ?? false}, async () => {
  globalThis.REGIONS = {};
  globalThis.DEPLOYMENT = JSON.parse(readFileSync(new URL('../deployments/production.json', import.meta.url)));
  globalThis.SHELLS = {};
  globalThis.BUILD_ID = 'test';
  const {default: deployed} = await import('../server/index.ts');
  const worker = withSessions(deployed);
  const {sql, db} = advisorDatabase();
  try {
    sql.prepare("INSERT INTO users(id,created_at,role) VALUES(?,?,'admin')").run('test-admin', checked_at);
    const queries = [];
    const DB = {...db, prepare(query) { queries.push(query); return db.prepare(query); }};
    const request = (enabled, owner) => worker.fetch(new Request(`https://skippercast.com${capability}`, {
      headers: owner ? {'x-test-owner': owner} : {},
    }), {DB, ASSETS: {fetch() { throw new Error('Unexpected asset read'); }}, FLEET_ENABLED: String(enabled)});
    const response = await request(true, 'test-admin');
    assert.equal(response.status, 204);
    assert.equal(await response.text(), '');
    assert.equal(response.headers.get('cache-control'), 'private, no-store');
    assert.equal((await request(true, null)).status, 401);
    assert.equal((await request(true, 'test-nonadmin')).status, 404);
    assert.equal((await request(false, 'test-admin')).status, 404);
    assert.ok(!queries.some(query => /\bfleet_/i.test(query)), 'capability must not query fleet tables');
  } finally {
    sql.close();
  }
});
