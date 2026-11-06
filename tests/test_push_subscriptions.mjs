// SC1137-13: stopping notifications on one device stops only that device. The browser and fetch are mocked; no push is sent.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const alerts = await import('../web/alerts.ts');

/** A mock browser with one push subscription (or none) and a recorded call log; `fetchResult` is the server's answer. */
function world({endpoint = 'https://fcm.googleapis.com/fcm/send/laptop', subscribed = true, worker = true, unsubscribe = async () => true, answer = () => new Response(JSON.stringify({enabled: false}), {status: 200})} = {}) {
  const log = [];
  const subscription = subscribed ? {endpoint, async unsubscribe() { log.push('unsubscribe'); return unsubscribe(); }} : null;
  const nav = worker ? {serviceWorker: {async getRegistration(scope) { log.push(`getRegistration ${scope}`); return {pushManager: {async getSubscription() { log.push('getSubscription'); return subscription; }, async subscribe() { log.push('SUBSCRIBE'); }}}; }, async register() { log.push('REGISTER'); }}} : {};
  const fetchFn = async (url, init) => { log.push(`${init.method} ${url} ${init.body ?? ''}`); return answer(); };
  return {log, nav, fetchFn};
}
const refusal = (status, error) => () => new Response(JSON.stringify({error}), {status});
const offline = () => { throw new TypeError('Failed to fetch'); };
const requests = log => log.filter(l => /^(DELETE|POST|GET)/.test(l));

test('disable_device_sends_endpoint_before_unsubscribe', async () => {
  const w = world();
  assert.equal(await alerts.disablePush(w.fetchFn, w.nav), 'stopped');
  assert.deepEqual(w.log, ['getRegistration /sw.js', 'getSubscription', `DELETE /api/subscription {"endpoint":"https://fcm.googleapis.com/fcm/send/laptop"}`, 'unsubscribe']);
  assert.ok(!w.log.some(l => l === 'SUBSCRIBE' || l === 'REGISTER'), 'disabling never registers, subscribes or asks permission');
  // The phone is a different browser with its own endpoint: it sends its own, never the laptop's.
  const phone = world({endpoint: 'https://web.push.apple.com/phone'});
  await alerts.disablePush(phone.fetchFn, phone.nav);
  assert.deepEqual(requests(phone.log), ['DELETE /api/subscription {"endpoint":"https://web.push.apple.com/phone"}']);
});

test('disable_device_without_worker_or_subscription_sends_nothing', async () => {
  for (const [name, options] of [['no worker', {worker: false}], ['no subscription', {subscribed: false}]]) {
    const w = world(options);
    assert.equal(await alerts.disablePush(w.fetchFn, w.nav), 'none', name);
    assert.deepEqual(requests(w.log), [], `${name}: no server call`);
  }
});

test('disable_device_failures_keep_the_local_subscription_except_404', async () => {
  const missing = world({answer: refusal(404, 'Not found')});
  assert.equal(await alerts.disablePush(missing.fetchFn, missing.nav), 'stopped', 'a row the server no longer holds still lets this browser clean up');
  assert.ok(missing.log.includes('unsubscribe'));
  for (const [name, answer] of [['503', refusal(503, 'Service unavailable')], ['400', refusal(400, 'invalid endpoint')], ['offline', offline]]) {
    const w = world({answer});
    await assert.rejects(alerts.disablePush(w.fetchFn, w.nav), undefined, name);
    assert.ok(!w.log.includes('unsubscribe'), `${name}: the endpoint is kept for a retry`);
  }
  for (const [name, unsubscribe] of [['false', async () => false], ['rejected', async () => { throw Error('boom'); }]]) {
    const w = world({unsubscribe});
    assert.equal(await alerts.disablePush(w.fetchFn, w.nav), 'partial', name);
  }
});

test('disable_all_sends_explicit_scope', async () => {
  const w = world();
  assert.equal(await alerts.disableAllPush(w.fetchFn, w.nav), 'stopped');
  assert.deepEqual(requests(w.log), ['DELETE /api/subscription {"all":true}']);
  assert.ok(w.log.indexOf('unsubscribe') > w.log.findIndex(l => l.startsWith('DELETE')), 'local cleanup follows the server');
  // No worker or subscription here: the account-wide request is still sent, and nothing is claimed about this browser.
  for (const options of [{worker: false}, {subscribed: false}]) {
    const bare = world(options);
    assert.equal(await alerts.disableAllPush(bare.fetchFn, bare.nav), 'stopped');
    assert.deepEqual(requests(bare.log), ['DELETE /api/subscription {"all":true}']);
    assert.ok(!bare.log.includes('unsubscribe'));
  }
  for (const [name, answer] of [['503', refusal(503, 'Service unavailable')], ['offline', offline]]) {
    const failed = world({answer});
    await assert.rejects(alerts.disableAllPush(failed.fetchFn, failed.nav), undefined, name);
    assert.ok(!failed.log.includes('unsubscribe'), `${name}: nothing is unsubscribed locally`);
  }
  const partial = world({unsubscribe: async () => false});
  assert.equal(await alerts.disableAllPush(partial.fetchFn, partial.nav), 'partial');
});

for (const lookup of ['getRegistration', 'getSubscription']) {
  test(`disable_all_stops_server_before_rejected_${lookup}_and_reports_partial_cleanup`, async () => {
    const calls = [];
    const fail = async () => { calls.push(lookup); throw Error('Local lookup failed'); };
    const nav = {serviceWorker: {getRegistration: lookup === 'getRegistration' ? fail : async () => {
      calls.push('getRegistration');
      return {pushManager: {getSubscription: fail}};
    }}};
    const fetchFn = async (url, init) => {
      calls.push('DELETE');
      assert.equal(url, '/api/subscription');
      assert.equal(init.method, 'DELETE');
      assert.deepEqual(JSON.parse(init.body), {all: true});
      return Response.json({enabled: false});
    };
    assert.equal(await alerts.stopNotifications('all', fetchFn, nav), 'The server stopped notifications, but this browser could not unsubscribe. Try again.');
    assert.deepEqual(calls, lookup === 'getRegistration' ? ['DELETE', lookup] : ['DELETE', 'getRegistration', lookup]);
  });
}

test('sheet_stop_actions_are_distinct', async () => {
  const device = world(), all = world(), none = world({subscribed: false}), partial = world({unsubscribe: async () => false}), failed = world({answer: refusal(503, 'Service unavailable')});
  assert.equal(await alerts.stopNotifications('device', device.fetchFn, device.nav), 'Notifications stopped on this device. Other devices were not changed. Saved assessments remain available here.');
  assert.equal(await alerts.stopNotifications('all', all.fetchFn, all.nav), 'Notifications stopped on all devices. Saved assessments remain available here.');
  assert.equal(await alerts.stopNotifications('device', none.fetchFn, none.nav), 'No notifications are enabled on this device. Other devices were not changed.');
  assert.equal(await alerts.stopNotifications('device', partial.fetchFn, partial.nav), 'The server stopped notifications, but this browser could not unsubscribe. Try again.');
  assert.deepEqual(requests(device.log), ['DELETE /api/subscription {"endpoint":"https://fcm.googleapis.com/fcm/send/laptop"}']);
  assert.deepEqual(requests(all.log), ['DELETE /api/subscription {"all":true}']);
  await assert.rejects(alerts.stopNotifications('device', failed.fetchFn, failed.nav), /Service unavailable/, 'the server error reaches the sheet');
  // The sheet (Preact, not importable here) wires exactly these two labelled actions, both disabled while either runs.
  const sheet = readFileSync(new URL('../web/app/TripAlerts.tsx', import.meta.url), 'utf8');
  const strings = JSON.parse(readFileSync(new URL('../catalog/app/strings.json', import.meta.url), 'utf8')).strings;
  assert.ok(sheet.includes("'alerts.stopDevice'") && sheet.includes("'alerts.stopAll'"));
  assert.equal(strings['alerts.stopDevice'].en, 'Stop notifications on this device');
  assert.equal(strings['alerts.stopAll'].en, 'Stop on all devices');
  assert.ok(sheet.includes('disabled={stopping}') && sheet.includes('stopNotificationsId(scope)'));
  assert.ok(!sheet.includes('disablePush'), 'the sheet no longer calls the old account-wide stop');
});
