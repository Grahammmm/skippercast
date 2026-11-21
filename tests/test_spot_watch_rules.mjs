import test from 'node:test';
import assert from 'node:assert/strict';
import {WATCH_LAYERS, WATCH_OPS, WATCH_RANGES, validateWatchInput} from '../server/spot-watch-rules.ts';

const watch = {layer: 'water-temp', op: '>=', a: 58};
const between = {...watch, op: 'between'};
const fail = (field, error) => ({ok: false, field, error});
const rangeError = 'Expected a finite number in the layer range.';

// Catch accidental changes to the wire vocabulary or to stored-unit limits.
test('C1: exported layers, comparisons and ranges match the roadmap', () => {
  assert.deepEqual(WATCH_LAYERS, ['water-temp', 'chlorophyll', 'sst-contrast']);
  assert.deepEqual(WATCH_OPS, ['>=', '<=', 'between']);
  assert.deepEqual(WATCH_RANGES, {'water-temp': [28, 95], chlorophyll: [0.01, 100], 'sst-contrast': [0, 10]});
});

// Catch permissive body checks that accept non-records or silently drop extra keys.
test('C2: rejects non-objects, arrays and unknown own keys at body', () => {
  for (const body of [null, undefined, 58, 'watch', true, Symbol(), 1n, () => {}, []]) {
    assert.deepEqual(validateWatchInput(body), fail('body', 'Expected a watch object.'));
  }
  for (const body of [{enabled: true}, {...watch, enabled: true}, {...watch, [Symbol()]: true},
    Object.defineProperty({...watch}, 'extra', {value: true})]) {
    assert.deepEqual(validateWatchInput(body), fail('body', 'Unexpected watch key.'));
  }
});

// Overlapping errors catch validation reordered by field, or a missing value being defaulted.
test('C2: reports the first failure in body, layer, op, a, b order', () => {
  const cases = [
    [{layer: 'forecast', op: '>', a: '58', b: false, extra: true}, fail('body', 'Unexpected watch key.')],
    [{layer: 'forecast', op: '>', a: '58', b: false}, fail('layer', 'Invalid watch layer.')],
    [{...watch, op: '>', a: '58', b: false}, fail('op', 'Invalid watch comparison.')],
    [{...between, a: '58', b: false}, fail('a', rangeError)],
    [{...between, b: false}, fail('b', rangeError)],
    [{}, fail('layer', 'Invalid watch layer.')],
    [{layer: watch.layer}, fail('op', 'Invalid watch comparison.')],
    [{layer: watch.layer, op: watch.op}, fail('a', rangeError)],
  ];
  for (const [body, expected] of cases) assert.deepEqual(validateWatchInput(body), expected);
});

// Catch exclusive limits, swapped layer ranges, or a range check applied only to a.
for (const [layer, min, max, below, above] of [
  ['water-temp', 28, 95, 27.99, 95.01],
  ['chlorophyll', 0.01, 100, 0.009, 100.01],
  ['sst-contrast', 0, 10, -0.01, 10.01],
]) {
  test(`C2: ${layer} accepts both inclusive ends and rejects values just outside`, () => {
    for (const a of [min, max]) {
      const body = {layer, op: '<=', a};
      assert.deepEqual(validateWatchInput(body), {ok: true, watch: {...body, b: null}});
    }
    const body = {layer, op: 'between', a: min, b: max};
    assert.deepEqual(validateWatchInput(body), {ok: true, watch: body});
    for (const invalid of [below, above]) {
      assert.deepEqual(validateWatchInput({...body, a: invalid}), fail('a', rangeError));
      assert.deepEqual(validateWatchInput({...body, b: invalid}), fail('b', rangeError));
    }
  });
}

// Catch coercion, NaN passing a negative-only bounds check, and defaulting a missing b.
test('C2: both thresholds require finite numbers without coercion', () => {
  for (const invalid of ['59', true, false, null, undefined, NaN, Infinity, -Infinity, 59n, new Number(59)]) {
    assert.deepEqual(validateWatchInput({...between, a: invalid, b: 60}), fail('a', rangeError));
    assert.deepEqual(validateWatchInput({...between, b: invalid}), fail('b', rangeError));
  }
  assert.deepEqual(validateWatchInput(between), fail('b', rangeError));
});

// Catch dropping a supplied second threshold, or treating an own undefined as absent.
test('C2: single-threshold comparisons accept only absent or null b and normalize it', () => {
  for (const op of ['>=', '<=']) {
    const body = {...watch, op};
    const expected = {ok: true, watch: {...body, b: null}};
    assert.deepEqual(validateWatchInput(body), expected);
    assert.deepEqual(validateWatchInput({...body, b: null}), expected);
    for (const b of [59, '59', false, undefined]) {
      assert.deepEqual(validateWatchInput({...body, b}), fail('b', 'Expected b to be absent or null.'));
    }
  }
});

// Catch an inclusive ordering check or a validator that silently swaps the endpoints.
test('C2: between rejects equal and reversed thresholds', () => {
  for (const b of [58, 57]) {
    assert.deepEqual(validateWatchInput({...between, b}), fail('b', 'Expected b to be greater than a.'));
  }
});

// Catch property reads that execute code, validate inherited data, or leak reflection errors.
test('C2: ignores inherited values and never throws on uninspectable input', () => {
  assert.deepEqual(validateWatchInput(Object.create(watch)), fail('layer', 'Invalid watch layer.'));
  const getter = Object.defineProperty({...watch}, 'a', {get() { assert.fail('must not read getter'); }});
  assert.deepEqual(validateWatchInput(getter), fail('a', rangeError));
  const {proxy, revoke} = Proxy.revocable(watch, {});
  revoke();
  assert.deepEqual(validateWatchInput(proxy), fail('body', 'Could not inspect watch input.'));
  const unreadableB = new Proxy(between, {
    getOwnPropertyDescriptor(target, key) {
      if (key === 'b') throw new Error('uninspectable b');
      return Reflect.getOwnPropertyDescriptor(target, key);
    },
  });
  assert.deepEqual(validateWatchInput(unreadableB), fail('b', 'Could not inspect watch input.'));
});
