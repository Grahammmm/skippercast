// SC1722-04: a coast product left in transport 'error' is asked again once per
// view load, once per page online event; invalid and expired are never retried.
import test, {mock} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {effect, signal} from '@preact/signals';
import {createCoastData} from '../web/coast-data.ts';
import {overviewReportContext} from '../web/overview-context.ts';

const json = path => JSON.parse(readFileSync(new URL(path, import.meta.url), 'utf8'));
const fixtures = {report: json('./fixtures/coast/report.json'), ocean: json('./fixtures/coast/ocean.json'), history: json('./fixtures/coast/history.json')};
const region = json('../dist/regions/morro-bay/region.json');
const GENERATED = Date.parse(fixtures.report.generatedAt);
const NOW = GENERATED + 3_600_000;

const MORRO = () => {
  const point = {latitude: 35.36, longitude: -120.94};
  return overviewReportContext(point, {...point, id: 'synthetic-selection', region: 'morro-bay'}, [region], 'boat', 'lingcod', new Date(NOW));
};
const respond = body => new Response(JSON.stringify(body), {headers: {'Content-Type': 'application/json'}});
const bad = () => new Response('no', {status: 503});

/** Replace global fetch with a recorder; `reply(path, init, n)` returns a Response, a promise, or throws. */
function bridge(reply) {
  const calls = [];
  const original = globalThis.fetch;
  globalThis.fetch = (path, init) => { calls.push(path.split('/').pop()); return Promise.resolve().then(() => reply(path.split('/').pop(), init, calls.length)); };
  return {calls, restore: () => { globalThis.fetch = original; }};
}
function setup(t, reply) {
  mock.timers.enable({apis: ['setTimeout', 'Date'], now: NOW});
  t.after(() => mock.timers.reset());
  const net = bridge(reply); t.after(net.restore);
  const events = new EventTarget();
  const client = createCoastData({clockEvents: events}); t.after(client.destroy);
  return {net, events, client};
}
const settle = () => new Promise(resolve => setImmediate(resolve));

for (const [label, failure] of [['HTTP 503', bad], ['thrown fetch', () => { throw new TypeError('offline'); }]]) {
  test(`error_remount_once: ${label} then a later load asks once and admits the reply`, async t => {
    let ok = false;
    const {net, client} = setup(t, name => ok ? respond(fixtures[name]) : failure());
    assert.ok(client.setPlace(MORRO()));
    await client.load('history');
    assert.equal(client.coastStatus.value.history, 'error');
    assert.equal(net.calls.length, 1);
    await settle();
    assert.equal(net.calls.length, 1, 'no request without a new trigger');
    ok = true;
    await client.load('history');
    assert.equal(net.calls.length, 2);
    assert.equal(client.coastStatus.value.history, 'ready');
    assert.ok(client.coastHistory.value);
    await client.load('history');
    assert.equal(net.calls.length, 2, 'ready is not asked again');
  });
}

test('online_wanted_error_only: one online event retries only wanted errors', async t => {
  let ok = false;
  const {net, events, client} = setup(t, name => name === 'ocean' || ok ? respond(fixtures[name]) : bad());
  client.setPlace(MORRO());
  await client.load('history', 'report', 'ocean');
  assert.deepEqual([...net.calls].sort(), ['history', 'ocean', 'report']);
  ok = true;
  net.calls.length = 0;
  events.dispatchEvent(new Event('online'));
  await settle();
  assert.deepEqual([...net.calls].sort(), ['history', 'report']);
  assert.equal(client.coastStatus.value.history, 'ready');
  events.dispatchEvent(new Event('online'));
  await settle();
  assert.equal(net.calls.length, 2, 'ready products are not asked again');
});

test('online during a pending retry joins it: two events and a load make one request', async t => {
  let release;
  let mode = 'fail';
  const {net, events, client} = setup(t, () => mode === 'fail' ? bad() : new Promise(resolve => { release = () => resolve(respond(fixtures.history)); }));
  client.setPlace(MORRO());
  await client.load('history');
  mode = 'hang';
  net.calls.length = 0;
  events.dispatchEvent(new Event('online'));
  events.dispatchEvent(new Event('online'));
  const joined = client.load('history');
  await settle();
  assert.equal(net.calls.length, 1);
  release(); await joined;
  assert.equal(client.coastStatus.value.history, 'ready');
});

test('a retry that fails again settles at error with no loop', async t => {
  const {net, events, client} = setup(t, bad);
  client.setPlace(MORRO());
  await client.load('history');
  events.dispatchEvent(new Event('online'));
  await settle(); await settle();
  assert.equal(net.calls.length, 2);
  assert.equal(client.coastStatus.value.history, 'error');
  await settle();
  assert.equal(net.calls.length, 2);
});

test('a reactive reader retries only when its own trigger changes, not when a read fails', async t => {
  const replies = [];
  const {net, client} = setup(t, () => new Promise(resolve => replies.push(resolve)));
  const visit = signal(0);
  let runs = 0;
  const stop = effect(() => {
    void visit.value;
    runs++;
    client.setPlace(MORRO());
    void client.load('report');
  });
  t.after(stop);
  await settle();
  assert.equal(net.calls.length, 1);
  replies.shift()(bad());
  await settle();
  assert.equal(client.coastStatus.value.report, 'error');
  assert.equal(runs, 1, 'transport state must not subscribe the reader effect');
  assert.equal(net.calls.length, 1, 'failure does not start an automatic retry');
  visit.value++;
  await settle();
  assert.equal(net.calls.length, 2, 'a real return retries once');
  replies.shift()(bad());
  await settle();
  assert.equal(runs, 2);
  assert.equal(client.coastStatus.value.report, 'error');
  assert.equal(net.calls.length, 2, 'the failed retry stays settled');
});

test('invalid_expired_stay_withheld: no retry on load or online', async t => {
  const wrongCounty = {...fixtures.history, countyId: 'elsewhere'};
  const {net, events, client} = setup(t, name => name === 'history' ? respond(wrongCounty) : respond({...fixtures.ocean, generatedAt: new Date(NOW - 10 * 86_400_000).toISOString()}));
  client.setPlace(MORRO());
  await client.load('history', 'ocean');
  const statuses = {...client.coastStatus.value};
  assert.equal(statuses.history, 'invalid');
  assert.equal(statuses.ocean, 'expired');
  net.calls.length = 0;
  await client.load('history', 'ocean');
  events.dispatchEvent(new Event('online'));
  await settle();
  assert.equal(net.calls.length, 0);
  assert.equal(client.coastStatus.value.history, 'invalid');
  assert.equal(client.coastStatus.value.ocean, 'expired');
});

test('place_abort_and_destroy: unbound and destroyed clients request nothing on online', async t => {
  const {net, events, client} = setup(t, bad);
  events.dispatchEvent(new Event('online'));
  await client.load('history');
  await settle();
  assert.equal(net.calls.length, 0, 'unbound');
  client.setPlace(MORRO());
  await client.load('history');
  assert.equal(net.calls.length, 1);
  client.setPlace(null);
  events.dispatchEvent(new Event('online'));
  await settle();
  assert.equal(net.calls.length, 1, 'unbound after place cleared');
  client.setPlace(MORRO());
  await settle();
  client.destroy();
  net.calls.length = 0;
  events.dispatchEvent(new Event('online'));
  await settle();
  assert.equal(net.calls.length, 0, 'destroyed');
});
