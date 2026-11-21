import test from 'node:test';
import assert from 'node:assert/strict';
import {
  readCalibrationChoice, storedCalibrationChoice, validateCalibrationChoice,
} from '../server/comfort-calibration-choice.ts';

const eighty = 'x'.repeat(80);
const eightyWithPair = 'x'.repeat(78) + '\u{1F30A}';
const eightyOneWithPair = 'x' + eightyWithPair;
const unreadable = () => { throw new TypeError('unreadable fixture'); };

// A permissive object test would admit arrays, instances or inherited choices.
test('C1: reject bodies that are not plain objects', () => {
  const inputs = [null, undefined, true, 1, 'off', Symbol(), () => {},
    Object.assign([], {choice: 'off'}), new Date(0), Object.create({choice: 'off'})];
  for (const input of inputs) {
    assert.deepEqual(validateCalibrationChoice(input), {ok: false, field: 'body', error: 'not-object'});
  }
});

// Reading unknown bodies must not propagate accessor or inspection failures.
test('C1: unreadable bodies return not-object', () => {
  const revoked = Proxy.revocable({}, {});
  revoked.revoke();
  for (const input of [{get choice() { return unreadable(); }},
    {choice: 'off', get boat() { return unreadable(); }}, revoked.proxy]) {
    assert.deepEqual(validateCalibrationChoice(input), {ok: false, field: 'body', error: 'not-object'});
  }
});

// Object.keys alone would overlook symbol or non-enumerable own keys.
test('C1: reject every kind of unexpected own key', () => {
  for (const input of [{choice: 'off', extra: true}, {choice: 'off', [Symbol()]: null},
    Object.defineProperty({choice: 'off'}, 'extra', {value: null})]) {
    assert.deepEqual(validateCalibrationChoice(input), {ok: false, field: 'body', error: 'unexpected-key'});
  }
});

// The write boundary must not default, coerce or normalize the choice.
test('C1: require an explicit auto or off choice', () => {
  for (const input of [{}, ...[undefined, null, true, 1, '', 'Off', ' off ', ['off']].map(choice => ({choice}))]) {
    assert.deepEqual(validateCalibrationChoice(input), {ok: false, field: 'choice', error: 'bad-choice'});
  }
});

// An optional boat is not an arbitrary nullable or string-coercible value.
test('C1: reject a supplied boat of the wrong type', () => {
  for (const boat of [undefined, false, 7, ['Pilot'], {}, new String('Pilot')]) {
    assert.deepEqual(validateCalibrationChoice({choice: 'off', boat}), {ok: false, field: 'boat', error: 'bad-boat'});
  }
});

// Save one canonical absence; keep the interior spelling and permit plain dictionaries.
test('C1: accept both choices and normalize absent and padded boat names', () => {
  for (const input of [{choice: 'auto'}, {choice: 'auto', boat: null},
    {choice: 'auto', boat: ''}, {choice: 'auto', boat: ' \t\n '}]) {
    assert.deepEqual(validateCalibrationChoice(input), {ok: true, choice: 'auto', boat: null});
  }
  const input = Object.assign(Object.create(null), {choice: 'off', boat: '\t Pilot  One \n'});
  assert.deepEqual(validateCalibrationChoice(input), {ok: true, choice: 'off', boat: 'Pilot  One'});
});

// Counting before trim, counting code points or slicing would change this boundary.
test('C1: enforce the inclusive 80 UTF-16 unit limit after trimming without truncation', () => {
  for (const boat of [eighty, eightyWithPair]) {
    assert.deepEqual(validateCalibrationChoice({choice: 'off', boat: ` ${boat}\t`}), {ok: true, choice: 'off', boat});
  }
  for (const boat of [eighty + 'x', eightyOneWithPair]) {
    assert.deepEqual(validateCalibrationChoice({choice: 'off', boat: ` ${boat} `}), {ok: false, field: 'boat', error: 'bad-boat'});
  }
});

// Reusing the strict writer wholesale would reset a valid legacy choice with extra keys.
test('C2: read stored text and objects, ignoring unrelated keys', () => {
  assert.deepEqual(readCalibrationChoice('{"choice":"off","boat":" Pilot ","legacy":true}'), {choice: 'off', boat: 'Pilot'});
  assert.deepEqual(readCalibrationChoice({choice: 'auto', boat: ` ${eightyWithPair} `}), {choice: 'auto', boat: eightyWithPair});
});

// Stored corruption or a missing choice must not retain even an otherwise valid boat.
test('C2: default to auto and no boat when the record or choice is unreadable or invalid', () => {
  const revoked = Proxy.revocable({}, {});
  revoked.revoke();
  for (const input of ['{', '"off"', 'null', '[]', '17', null, undefined, false, [],
    {boat: 'Pilot'}, {choice: 'on', boat: 'Pilot'}, {choice: null, boat: 'Pilot'},
    Object.create({choice: 'off'}), {get choice() { return unreadable(); }}, revoked.proxy]) {
    assert.deepEqual(readCalibrationChoice(input), {choice: 'auto', boat: null});
  }
});

// Bad boat data must neither truncate into another name nor turn an opt-out back on.
test('C2: preserve off when only the boat is absent, blank, invalid or unreadable', () => {
  for (const input of [{choice: 'off'}, ...[null, ' \t ', undefined, 42, eightyOneWithPair].map(boat => ({choice: 'off', boat})),
    {choice: 'off', get boat() { return unreadable(); }}, '{"choice":"off","boat":false}']) {
    assert.deepEqual(readCalibrationChoice(input), {choice: 'off', boat: null});
  }
});

// Serializing the input directly could leak extra keys, or depend on its key order.
test('C3: write exactly choice then boat, including explicit null and escaped text', () => {
  assert.deepEqual(storedCalibrationChoice({boat: null, choice: 'auto', extra: true}), '{"choice":"auto","boat":null}');
  assert.deepEqual(storedCalibrationChoice({boat: 'The "Pilot"', choice: 'off'}), '{"choice":"off","boat":"The \\"Pilot\\""}');
});

// Storage must preserve every canonical choice/boat combination, including at the boundary.
test('C3: round-trip normalized values for both choices', () => {
  for (const choice of ['auto', 'off']) {
    for (const boat of [null, 'The "Pilot"', 'A\nB', eighty, eightyWithPair]) {
      const value = {choice, boat};
      assert.deepEqual(readCalibrationChoice(storedCalibrationChoice(value)), value);
    }
  }
});
