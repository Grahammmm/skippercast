// RF1240-15: canonicalJson matches Python's canonical_json (fleet/ops.py):
// json.dumps(v, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).
import test from 'node:test';
import assert from 'node:assert/strict';
import {canonicalJson, valueKey, factId} from '../server/fleet/ids.ts';

const notFinite = {name: 'TypeError', message: 'canonicalJson: number is not finite'};
const notJson = {name: 'TypeError', message: 'canonicalJson: not a JSON value'};

test('keys above U+FFFF sort by code point, as Python sort_keys', () => {
  // Pinned from Python json.dumps({'😀': 2, '｡': 1}, sort_keys=True, separators=(',', ':'), ensure_ascii=False).
  assert.equal(canonicalJson({'😀': 2, '｡': 1}), '{"｡":1,"😀":2}');
  assert.equal(canonicalJson({'｡': 1, '😀': 2}), '{"｡":1,"😀":2}');
  assert.equal(canonicalJson({v: [{'😀': 2, '｡': 1}], w: {'😀': {'𐀀': 1, '\ue000': 2}, '｡': null}}),
    '{"v":[{"｡":1,"😀":2}],"w":{"｡":null,"😀":{"\ue000":2,"𐀀":1}}}');
});

test('a key that is a prefix of another sorts first; equal-prefix astral keys compare on the next point', () => {
  assert.equal(canonicalJson({'😀a': 1, '😀': 2, '😀😀': 3, '😀｡': 4}), '{"😀":2,"😀a":1,"😀｡":4,"😀😀":3}');
});

test('ASCII and BMP keys give the same text as before', () => {
  assert.equal(canonicalJson({b: 1, a: 2, é: 3}), '{"a":2,"b":1,"é":3}');
  assert.equal(canonicalJson({b: [2, {d: 1, c: 'é'}], a: null}), '{"a":null,"b":[2,{"c":"é","d":1}]}');
});

test('the same fact gets one id whatever the key insertion order', async () => {
  const a = await valueKey({'😀': 2, '｡': 1}), b = await valueKey({'｡': 1, '😀': 2});
  assert.equal(a, b);
  assert.equal(await factId('v', 'f', 's', 'u', a), await factId('v', 'f', 's', 'u', b));
});

for (const bad of [NaN, Infinity, -Infinity]) {
  test(`${bad} throws at top level, in an array and as an object value`, () => {
    assert.throws(() => canonicalJson(bad), notFinite);
    assert.throws(() => canonicalJson([1, bad]), notFinite);
    assert.throws(() => canonicalJson({a: 1, b: bad}), notFinite);
    assert.throws(() => canonicalJson({a: [{b: bad}]}), notFinite);
  });
}

test('undefined throws at top level, as an array item, as an object value and as an array hole', () => {
  assert.throws(() => canonicalJson(undefined), notJson);
  assert.throws(() => canonicalJson([1, undefined]), notJson);
  assert.throws(() => canonicalJson([undefined]), notJson);
  assert.throws(() => canonicalJson({a: undefined}), notJson);
  assert.throws(() => canonicalJson({a: {b: [undefined]}}), notJson);
  assert.throws(() => canonicalJson([1, , 2]), notJson); // eslint-disable-line no-sparse-arrays
});

test('functions, symbols and bigints throw', () => {
  assert.throws(() => canonicalJson(() => 1), notJson);
  assert.throws(() => canonicalJson({a: Symbol('s')}), notJson);
  assert.throws(() => canonicalJson([10n]), notJson);
});

test('null still prints null; -0, fractions and empty containers are unchanged', () => {
  assert.equal(canonicalJson(null), 'null');
  assert.equal(canonicalJson({a: null}), '{"a":null}');
  assert.equal(canonicalJson([null]), '[null]');
  assert.equal(canonicalJson(-0), '0');
  assert.equal(canonicalJson(1.5), '1.5');
  assert.equal(canonicalJson([]), '[]');
  assert.equal(canonicalJson({}), '{}');
});

test('valueKey rejects a value Python refuses and never resolves to an id', async () => {
  await assert.rejects(valueKey({a: NaN}), notFinite);
  await assert.rejects(valueKey({a: Infinity}), notFinite);
  await assert.rejects(valueKey({a: undefined}), notJson);
  assert.match(await valueKey({a: 1}), /^[0-9a-f]{16}$/);
});
