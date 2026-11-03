// RF1100-2: a held review-queue key (auto-repeat) or a keyless event decides nothing.
import {test} from 'node:test';
import assert from 'node:assert/strict';

const {shortcutFor} = await import('../web/admin/keys.ts');

test('auto-repeated a/r/e presses map to no decision', () => {
  for (const key of ['a', 'r', 'e', 'A', 'R', 'E']) {
    assert.equal(shortcutFor({key, repeat: true}), null, key);
  }
});

test('first presses still map exactly as before', () => {
  assert.equal(shortcutFor({key: 'a', repeat: false}), 'approve');
  assert.equal(shortcutFor({key: 'a'}), 'approve');
  assert.equal(shortcutFor({key: 'R'}), 'reject');
  assert.equal(shortcutFor({key: 'R', shiftKey: true}), 'reject');
  assert.equal(shortcutFor({key: 'e', repeat: false}), 'edit');
});

test('a key that is not a string maps to no decision without throwing', () => {
  for (const event of [{key: undefined}, {key: 7}, {}, {key: null}, {key: ['a']}, {repeat: false}]) {
    assert.doesNotThrow(() => shortcutFor(event));
    assert.equal(shortcutFor(event), null, JSON.stringify(event));
  }
});

test('repeat with the existing refusal reasons still refuses', () => {
  assert.equal(shortcutFor({key: 'a', repeat: true, target: {tagName: 'textarea'}}), null);
  assert.equal(shortcutFor({key: 'a', repeat: true, ctrlKey: true}), null);
  assert.equal(shortcutFor({key: 'a', repeat: false, target: {tagName: 'INPUT'}}), null);
  assert.equal(shortcutFor({key: 'a', ctrlKey: true}), null);
});

test('other keys still map to nothing', () => {
  assert.equal(shortcutFor({key: 'Enter'}), null);
  assert.equal(shortcutFor({key: 'x'}), null);
  assert.equal(shortcutFor({key: ''}), null);
});

test('a truthy non-boolean repeat value does not block a first press', () => {
  // The guard is repeat === true (the native boolean); anything else is a first press.
  assert.equal(shortcutFor({key: 'a', repeat: 'yes'}), 'approve');
});
