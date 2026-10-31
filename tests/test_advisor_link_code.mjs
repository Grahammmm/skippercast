// RF1300-8: offer_text_link's 6-digit web link code. Without a test source it
// redraws 32-bit words at or above LINK_CODE_LIMIT (no modulo bias) and gives up
// after 16 draws from a broken source; an injected `random` outside [0, 1)
// throws instead of being clamped to 000000/999999.
import test from 'node:test';
import assert from 'node:assert/strict';

const {linkCode, LINK_CODE_LIMIT} = await import('../server/advisor/tools/offer_text_link.ts');

/** A word source that yields `values` in turn (the last one repeats) and counts its calls. */
const words = (...values) => {
  const source = () => values[Math.min(source.calls++, values.length - 1)];
  source.calls = 0;
  return source;
};

test('the limit is the largest multiple of 10^6 below 2^32', () => {
  assert.equal(LINK_CODE_LIMIT, Math.floor(2 ** 32 / 1e6) * 1e6);
  assert.equal(LINK_CODE_LIMIT % 1e6, 0);
  assert.ok(LINK_CODE_LIMIT < 2 ** 32 && LINK_CODE_LIMIT + 1e6 > 2 ** 32);
});

test('words at or above the limit are redrawn', () => {
  const word = words(4_294_967_295, 4_294_000_000, 123);
  assert.equal(linkCode(undefined, word), '000123');
  assert.equal(word.calls, 3);
});

test('a word just below the limit is used on the first draw', () => {
  const word = words(4_293_999_999);
  assert.equal(linkCode(undefined, word), '999999');
  assert.equal(word.calls, 1);
  const zero = words(0);
  assert.equal(linkCode(undefined, zero), '000000');
  assert.equal(zero.calls, 1);
});

test('a broken word source fails after 16 draws instead of looping or biasing', () => {
  const word = words(4_294_967_295);
  assert.throws(() => linkCode(undefined, word), {name: 'Error', message: 'link code source failed'});
  assert.equal(word.calls, 16);
  const late = words(...Array(15).fill(LINK_CODE_LIMIT), 42);
  assert.equal(linkCode(undefined, late), '000042', 'the 16th draw still counts');
  assert.equal(late.calls, 16);
});

test('an injected random outside [0, 1) is refused, not clamped', () => {
  for (const bad of [NaN, Infinity, -Infinity, -0.1, 1, 1.5]) {
    assert.throws(() => linkCode(() => bad), {name: 'RangeError', message: 'link code random source out of range'}, String(bad));
  }
  const word = words(7);
  assert.throws(() => linkCode(() => NaN, word), RangeError);
  assert.equal(word.calls, 0, 'a broken test source never falls back to the CSPRNG');
});

test('the pinned injected values are unchanged', () => {
  assert.equal(linkCode(() => 0.123456), '123456');
  assert.equal(linkCode(() => 0), '000000');
  assert.equal(linkCode(() => 0.9999999), '999999');
});

test('the default source gives six digits', () => {
  for (let i = 0; i < 200; i++) assert.match(linkCode(), /^\d{6}$/);
});
