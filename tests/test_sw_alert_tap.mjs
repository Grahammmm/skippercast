// SC1537-05: a trip-alert notification tap opens the v2 map's saved-trip
// alerts dialog ('#alerts', web/account.ts followAlertsHash), never '/#forecast'.
// dist/sw.js is loaded unchanged in node:vm, as tests/test_sw.mjs does.
import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';

const SOURCE = readFileSync(new URL('../dist/sw.js', import.meta.url), 'utf8');
const ORIGIN = 'https://skippercast.test';

function loadWorker(windows = []) {
  const listeners = {}, shown = [], opened = [], navigated = [], focused = [];
  const clients = {
    matchAll: async () => windows.map(url => ({url, navigate: async to => { navigated.push(to); }, focus: async () => { focused.push(url); }})),
    openWindow: async url => { opened.push(url); }, claim: async () => {}, get: async () => undefined,
  };
  const self = {location: new URL(ORIGIN + '/sw.js'), navigator: {}, clients,
    addEventListener: (type, fn) => { (listeners[type] ||= []).push(fn); },
    registration: {showNotification: async (title, options) => { shown.push([title, options]); }}};
  const context = vm.createContext({self, clients, caches: {}, fetch: async () => { throw new TypeError('offline'); }, console: {warn() {}, log() {}},
    URL, Request, Response, Headers, Map, Set, Promise, Date, Math, Number, String, JSON, Error, TypeError, Array, TextDecoder, Uint8Array, setTimeout, clearTimeout});
  vm.runInContext(SOURCE, context, {filename: 'sw.js'});
  return {context, listeners, shown, opened, navigated, focused};
}

async function run(listener, event) {
  const waits = [];
  listener({...event, waitUntil: p => waits.push(p)});
  await Promise.all(waits);
}
const click = worker => run(worker.listeners.notificationclick[0], {notification: {close() {}}});

test('alertsTarget keeps an open map window and its region, and replaces any old hash', () => {
  const {alertsTarget} = loadWorker().context;
  assert.equal(alertsTarget('https://o/map?region=central-coast', 'https://o'), '/map?region=central-coast#alerts');
  assert.equal(alertsTarget('https://o/map?region=x#trip', 'https://o'), '/map?region=x#alerts');
  assert.equal(alertsTarget('https://o/map#alerts', 'https://o'), '/map#alerts');
});

test('alertsTarget sends the landing page, other pages, other origins and no window to /map#alerts', () => {
  const {alertsTarget} = loadWorker().context;
  for (const url of ['https://o/', 'https://o/about', 'https://o/map/x', 'https://o/mapx?region=x', 'https://evil.test/map?region=x', 'http://o/map?region=x', null, '', 'not a url']) {
    assert.equal(alertsTarget(url, 'https://o'), '/map#alerts', String(url));
  }
});

test('a push stores /map#alerts even when the server payload still says /#forecast', async () => {
  const worker = loadWorker();
  await run(worker.listeners.push[0], {data: {json: () => ({eventId: 'e1', body: 'Wind rising', title: 'Trip', url: '/#forecast'})}});
  assert.equal(worker.shown.length, 1);
  assert.equal(worker.shown[0][1].data.url, '/map#alerts');
  assert.equal(worker.shown[0][1].tag, 'e1');
  assert.ok(!SOURCE.includes('#forecast'), 'the worker never navigates to #forecast');
});

test('a push without an event id or body still shows nothing', async () => {
  const worker = loadWorker();
  await run(worker.listeners.push[0], {data: {json: () => ({body: 'x', url: '/#forecast'})}});
  await run(worker.listeners.push[0], {data: {json: () => ({eventId: 'e1'})}});
  await run(worker.listeners.push[0], {data: {json: () => { throw new SyntaxError('bad'); }}});
  assert.equal(worker.shown.length, 0);
});

test('a tap navigates the open map window to its region with #alerts, then focuses it', async () => {
  const worker = loadWorker([ORIGIN + '/map?region=morro-bay#trip']);
  await click(worker);
  assert.deepEqual(worker.navigated, ['/map?region=morro-bay#alerts']);
  assert.equal(worker.focused.length, 1);
  assert.equal(worker.opened.length, 0);
});

test('a tap from the landing page navigates that window to /map#alerts', async () => {
  const worker = loadWorker(['https://evil.test/map?region=x', ORIGIN + '/']);
  await click(worker);
  assert.deepEqual(worker.navigated, ['/map#alerts']);
  assert.deepEqual(worker.focused, [ORIGIN + '/']);
  assert.equal(worker.opened.length, 0);
});

test('a tap with no same-origin window opens /map#alerts once', async () => {
  for (const windows of [[], ['https://evil.test/map?region=x']]) {
    const worker = loadWorker(windows);
    await click(worker);
    assert.deepEqual(worker.opened, ['/map#alerts']);
    assert.equal(worker.navigated.length, 0);
  }
});
