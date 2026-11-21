import test from 'node:test';
import assert from 'node:assert/strict';
import {mergeWatchPatch} from '../server/spot-watch-patch.ts';

const current = Object.freeze({layer: 'water-temp', op: '>=', a: 58, b: null, enabled: true});
const between = Object.freeze({...current, op: 'between', b: 64});
const success = (watch, resetState) => ({ok: true, watch, resetState});
const fail = (field, error) => ({ok: false, field, error});
const rangeError = 'Expected a finite number in the layer range.';

// Reject non-records even when they appear to carry a valid edit.
test('C1: rejects non-plain patch bodies', () => {
  for (const patch of [null, undefined, 'watch', 58, true, () => {},
    Object.assign([], {a: 59}), Object.assign(new Date(0), {a: 59}), Object.create({a: 59})]) {
    assert.deepEqual(mergeWatchPatch(current, patch), fail('body', 'Expected a plain watch patch object.'));
  }
});

// An empty edit is not a successful no-op.
test('C1: rejects an empty patch', () => {
  assert.deepEqual(mergeWatchPatch(current, {}), fail('body', 'Expected at least one watch patch key.'));
});

// Enumerable-only key scans would miss the hidden extra key.
test('C1: rejects unknown own keys instead of silently dropping them', () => {
  for (const patch of [{a: 59, extra: true}, {a: 59, [Symbol()]: true},
    Object.defineProperty({a: 59}, 'extra', {value: true})]) {
    assert.deepEqual(mergeWatchPatch(current, patch), fail('body', 'Unexpected watch patch key.'));
  }
});

// Reading the getter or ignoring the setter could turn an accessor into an edit.
test('C1: rejects accessor keys without invoking them', () => {
  let reads = 0;
  const getter = {get a() { reads++; return 59; }};
  const setter = {set enabled(_value) { assert.fail('must not call a setter'); }};
  for (const patch of [getter, setter]) {
    assert.deepEqual(mergeWatchPatch(current, patch), fail('body', 'Expected own data properties in the watch patch.'));
  }
  assert.equal(reads, 0);
});

// A proxy can list a key it cannot describe; it must not become an implicit no-op.
test('C1: rejects a key without an own descriptor', () => {
  const patch = new Proxy({}, {ownKeys: () => ['a']});
  assert.deepEqual(mergeWatchPatch(current, patch), fail('body', 'Expected own data properties in the watch patch.'));
});

// Reading only enumerable entries, or assuming a prototype, would lose a valid edit.
test('C1: accepts a non-enumerable own data key on a null-prototype record', () => {
  const patch = Object.defineProperty(Object.create(null), 'a', {value: 59});
  assert.deepEqual(mergeWatchPatch(current, patch), success({...current, a: 59}, true));
});

// When the comparator changes, only an omitted b is cleared automatically.
test('C2: between to >= clears omitted b but still validates explicit b', () => {
  for (const patch of [{op: '>='}, {op: '>=', b: null}]) {
    assert.deepEqual(mergeWatchPatch(between, patch), success(current, true));
  }
  for (const b of [64, undefined]) {
    assert.deepEqual(mergeWatchPatch(between, {op: '>=', b}), fail('b', 'Expected b to be absent or null.'));
  }
});

// A new interval needs a valid upper bound; do not synthesize one or accept a reversed interval.
test('C2: >= to between requires a supplied b above the merged a', () => {
  assert.deepEqual(mergeWatchPatch(current, {op: 'between'}), fail('b', rangeError));
  assert.deepEqual(mergeWatchPatch(current, {op: 'between', a: 64, b: 64}), fail('b', 'Expected b to be greater than a.'));
  assert.deepEqual(mergeWatchPatch(current, {op: 'between', b: 64}), success(between, true));
});

// Validating only supplied keys would miss the inherited a after changing its layer.
test('C2: validates the merged condition and preserves field errors', () => {
  for (const [patch, expected] of [
    [{layer: 'forecast'}, fail('layer', 'Invalid watch layer.')],
    [{op: '>'}, fail('op', 'Invalid watch comparison.')],
    [{layer: 'sst-contrast'}, fail('a', rangeError)],
    [{a: undefined}, fail('a', rangeError)],
  ]) {
    assert.deepEqual(mergeWatchPatch(current, patch), expected);
  }
});

// A truthiness check or defaulting explicit undefined would accept a non-boolean toggle.
test('C2: rejects non-boolean enabled values', () => {
  for (const enabled of ['false', 0, null, undefined]) {
    assert.deepEqual(mergeWatchPatch(current, {enabled}), fail('enabled', 'Expected a boolean.'));
  }
});

// Isolate each field so an omitted comparison cannot hide behind another condition change.
for (const [field, base, value] of [
  ['layer', current, 'chlorophyll'], ['op', current, '<='], ['a', between, 59], ['b', between, 65],
]) {
  test(`C3: changing only ${field} resets state`, () => {
    const patch = Object.freeze({[field]: value});
    assert.deepEqual(mergeWatchPatch(base, patch), success({...base, [field]: value}, true));
  });
}

// Do not reset based on the mere presence of an edited field or on a pause/resume.
test('C3: enabled-only and unchanged conditions preserve state', () => {
  const paused = {...between, enabled: false};
  assert.deepEqual(mergeWatchPatch(between, {enabled: false}), success(paused, false));
  assert.deepEqual(mergeWatchPatch(paused, {enabled: true}), success(between, false));
  assert.deepEqual(mergeWatchPatch(between, {a: 58}), success(between, false));
});

// Frozen inputs expose attempts to clear b or overlay the patch by mutating either object.
test('C3: returns a separate merged watch without mutating either input', () => {
  const patch = Object.freeze({op: '>=', enabled: false});
  const result = mergeWatchPatch(between, patch);
  assert.deepEqual(result, success({...current, enabled: false}, true));
  assert.notEqual(result.watch, between);
  assert.deepEqual(between, {...current, op: 'between', b: 64});
  assert.deepEqual(patch, {op: '>=', enabled: false});
});

// Exceptions from structural inspection must not escape to the caller.
test('C3: a revoked patch proxy returns a body error', () => {
  const {proxy, revoke} = Proxy.revocable({a: 59}, {});
  revoke();
  assert.deepEqual(mergeWatchPatch(current, proxy), fail('body', 'Could not inspect watch patch.'));
});
