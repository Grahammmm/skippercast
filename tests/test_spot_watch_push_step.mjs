import test from 'node:test';
import assert from 'node:assert/strict';
import { watchPushStep, watchSaveSteps } from '../web/spot-watch-push-step.ts';

const env = {
  serviceWorker: true, pushManager: true, publicKey: 'fixture-key',
  permission: 'granted', subscribed: true,
};

// A denied permission or a stale subscription must not mask missing prerequisites.
for (const [missing, facts] of [
  ['service worker', { serviceWorker: false }],
  ['PushManager', { pushManager: false }],
  ['public key (empty)', { publicKey: '' }],
  ['public key (null)', { publicKey: null }],
  ['public key (undefined)', { publicKey: undefined }],
]) {
  test(`C1: missing ${missing} is unsupported even with denied permission`, () => {
    assert.equal(watchPushStep({ ...env, ...facts, permission: 'denied' }), 'unsupported');
  });
}

test('C1: a granted subscription cannot bypass missing push support', () => {
  assert.equal(watchPushStep({ ...env, pushManager: false }), 'unsupported');
});

// Checking the subscription alone would misclassify denied, default, or unknown permission.
for (const [permission, subscribed, expected] of [
  ['denied', true, 'blocked'],
  ['granted', true, 'ready'],
  ['granted', false, 'enable'],
  ['default', false, 'enable'],
  ['default', true, 'enable'],
  ['unexpected', true, 'unsupported'],
]) {
  test(`C1: ${permission} permission with subscribed=${subscribed} gives ${expected}`, () => {
    assert.equal(watchPushStep({ ...env, permission, subscribed }), expected);
  });
}

// Catch dropped or reordered saves, wrong follow-up actions, and shared mutable arrays.
for (const [step, expected] of [
  ['ready', ['save']],
  ['enable', ['save', 'enable-push']],
  ['blocked', ['save', 'note-blocked']],
  ['unsupported', ['save', 'note-unsupported']],
]) {
  test(`C2: ${step} returns the full save-first sequence in a fresh array`, () => {
    const first = watchSaveSteps(step);
    const second = watchSaveSteps(step);
    assert.deepEqual(first, expected);
    assert.deepEqual(second, expected);
    assert.notStrictEqual(first, second);
  });
}
