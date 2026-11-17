import assert from 'node:assert/strict';
import test from 'node:test';
import {parseResponse} from '../server/boat-lookup.ts';

// Synthetic Messages API answers only; no network.
const answer = extra => ({content: [{type: 'text', text: JSON.stringify({
  name: 'Test 23', loa_ft: 23.3, hull: 'deep-v', confidence: 'high', notes: 'Cuddy.', ...extra})}]});
const estimated = est => parseResponse(answer({estimated: est})).estimated;

test('estimated_rejects_inherited_names', () => {
  const names = ['constructor', 'toString', 'loa_ft', '__proto__', 'hasOwnProperty', 'displacement_lb'];
  assert.deepEqual(estimated(names), ['loa_ft', 'displacement_lb']);
});

test('estimated_invalid_names_do_not_consume_cap', () => {
  const junk = Array.from({length: 15}, (_, i) => (i % 2 ? 'constructor' : 'toString'));
  assert.deepEqual(estimated([...junk, 7, null, 'loa_ft', {}, 'displacement_lb']), ['loa_ft', 'displacement_lb']);
});

test('estimated_absent_or_nonarray_is_empty', () => {
  for (const est of [undefined, null, 'loa_ft', {loa_ft: true}]) {
    const r = parseResponse(answer({estimated: est}));
    assert.deepEqual(r.estimated, []);
    assert.equal(r.boat.loa_ft, 23.3);
  }
});

test('estimated_valid_control_preserves_answer', () => {
  const valid = Array.from({length: 14}, (_, i) => (i % 2 ? 'displacement_lb' : 'loa_ft'));
  const control = parseResponse(answer({estimated: valid}));
  assert.deepEqual(control.estimated, valid.slice(0, 12));
  const mixed = parseResponse(answer({estimated: ['constructor', ...valid, '__proto__']}));
  assert.deepEqual(mixed.estimated, control.estimated);
  assert.deepEqual(mixed.boat, control.boat);
  assert.equal(mixed.confidence, 'high');
  assert.equal(mixed.notes, 'Cuddy.');
  assert.deepEqual(mixed.sources, control.sources);
});
