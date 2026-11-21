import assert from 'node:assert/strict';
import test from 'node:test';
import {validateWatchInput} from '../server/spot-watch-rules.ts';
import {formUnchanged, watchForm, watchFormBody} from '../web/spot-watch-form.ts';

const base = {layer: 'water-temp', op: 'between', a: '58', b: '64'};
const failure = (field, error) => ({ok: false, field, error});

// C4: check the actual emitted body at every successful call site, not a hand-built API request.
function assertAccepted(form, temp, body) {
  const result = watchFormBody(form, temp);
  assert.deepEqual(result, {ok: true, body});
  assert.deepEqual(validateWatchInput(result.body), {ok: true, watch: result.body});
}

test('C1: reject missing, unknown, padded and inherited layers before checking other fields', () => {
  for (const layer of ['', 'salinity', ' water-temp ', 'constructor', '__proto__']) {
    assert.deepEqual(watchFormBody({layer, op: '', a: '', b: ''}, 'F'), failure('layer', 'required'));
  }
});

test('C1: reject missing, unsupported and padded comparisons before parsing values', () => {
  for (const op of ['', '>', ' >= ']) {
    assert.deepEqual(watchFormBody({...base, op, a: '', b: ''}, 'F'), failure('op', 'required'));
  }
});

for (const [field, contract] of [['a', 'C2'], ['b', 'C3']]) {
  test(`${contract}: ${field} distinguishes required, malformed and overflowing decimals`, () => {
    const form = field === 'a' ? {...base, b: 'bogus'} : base;
    for (const text of ['', ' \t\n']) {
      assert.deepEqual(watchFormBody({...form, [field]: text}, 'F'), failure(field, 'required'));
    }
    // A loose Number or parseFloat call would accept some of these as numbers.
    for (const text of ['-', '+58', '−58', '.58', ',58', '58.', '58,', '5.8.0', '5,8,0', '5,8.0',
      '5.8,0', '5 8', '5\n8', '5_8', '0x3a', '5e1', 'NaN', 'Infinity', '58°F', '５８']) {
      assert.deepEqual(watchFormBody({...form, [field]: text}, 'F'), failure(field, 'not-a-number'), JSON.stringify(text));
    }
    assert.deepEqual(watchFormBody({...form, [field]: '9'.repeat(400)}, 'F'), failure(field, 'out-of-range'));
  });
}

// Endpoints use the stored ranges after conversion; contrast's displayed 5.56 C is already outside.
for (const [layer, temp, below, low, high, above, a, b] of [
  ['water-temp', 'F', '27.9', '28', '95', '95.1', 28, 95],
  ['water-temp', 'C', '-2,3', ' -2,2 ', '35', '35.1', 28, 95],
  ['sst-contrast', 'F', '-0.01', '0', '10', '10.01', 0, 10],
  ['sst-contrast', 'C', '-0.01', '0', '5.557', '5.56', 0, 10],
  ['chlorophyll', 'F', '0', '0.01', '100', '100.01', 0.01, 100],
  ['chlorophyll', 'C', '0', '0,01', '100', '100,01', 0.01, 100],
]) {
  test(`C2: ${layer} (${temp}) checks both range ends for either field`, () => {
    const form = {...base, layer, a: low, b: high};
    assertAccepted(form, temp, {layer, op: 'between', a, b});
    for (const text of [below, above]) {
      assert.deepEqual(watchFormBody({...form, a: text}, temp), failure('a', 'out-of-range'));
      assert.deepEqual(watchFormBody({...form, b: text}, temp), failure('b', 'out-of-range'));
    }
  });
}

test('C3: single thresholds ignore b rather than parsing or retaining it', () => {
  assertAccepted({...base, op: '>=', a: ' \t058.125 ', b: 'garbage'}, 'F',
    {layer: 'water-temp', op: '>=', a: 58.125, b: null});
  assertAccepted({...base, layer: 'sst-contrast', op: '<=', a: '-0', b: '5'}, 'F',
    {layer: 'sst-contrast', op: '<=', a: -0, b: null});
});

test('C3: check order after converting b, including bounds that round to the same number', () => {
  assert.deepEqual(watchFormBody({...base, a: '64', b: '58'}, 'F'), failure('b', 'order'));
  assert.deepEqual(watchFormBody({...base, a: '58.0', b: '58,0'}, 'F'), failure('b', 'order'));
  assert.deepEqual(watchFormBody({...base, a: '14.40', b: '14.41'}, 'C'), failure('b', 'order'));
  assert.deepEqual(watchFormBody({...base, layer: 'sst-contrast', a: '1.000', b: '1.001'}, 'C'), failure('b', 'order'));
});

test('C4: a converted decimal range validates unchanged in storage units', () => {
  assertAccepted({...base, layer: 'sst-contrast', a: ' 0,625 ', b: '\t1.25\n'}, 'C',
    {layer: 'sst-contrast', op: 'between', a: 1.13, b: 2.25});
});

test('C5: unchanged Celsius text does not resave 58 °F as 57.9 °F', () => {
  const watch = {layer: 'water-temp', op: '>=', a: 58, b: null};
  const shown = watchForm(watch, 'C');
  assert.deepEqual(shown, {layer: 'water-temp', op: '>=', a: '14.4', b: ''});
  assert.equal(formUnchanged(shown, watch, 'C'), true);
  assertAccepted(shown, 'C', {...watch, a: 57.9});
  assert.deepEqual(watchForm(watch, 'F'), {layer: 'water-temp', op: '>=', a: '58', b: ''});
});

test('C5: compare all four trimmed texts, not numeric equivalence', () => {
  const watch = {layer: 'sst-contrast', op: 'between', a: 0, b: 10};
  const shown = watchForm(watch, 'C');
  assert.deepEqual(shown, {layer: 'sst-contrast', op: 'between', a: '0', b: '5.56'});
  assert.equal(formUnchanged({layer: ' sst-contrast ', op: '\tbetween ', a: ' 0 ', b: '5.56\n'}, watch, 'C'), true);
  for (const edit of [{layer: 'water-temp'}, {op: '<='}, {a: '0.0'}, {b: '5,56'}]) {
    assert.equal(formUnchanged({...shown, ...edit}, watch, 'C'), false);
  }
});
