// RF1239-4: detectLanguage's short-text Spanish marker (¿ ¡ ñ) reads the same
// NFC, lower-cased text as the word counts, so an upper-case Ñ or a decomposed
// n + U+0303 counts like ñ. The other rules (es >= 1, en === 0) still apply.
import test from 'node:test';
import assert from 'node:assert/strict';

const {detectLanguage} = await import('../server/advisor/intents.ts');

test('upper-case Ñ counts as the Spanish marker', () => {
  assert.equal(detectLanguage('MAÑANA PESCA'), 'es');
});

test('a decomposed ñ (n + U+0303) counts as the Spanish marker', () => {
  assert.equal(detectLanguage('man\u0303ana pesca'), 'es');
  assert.equal(detectLanguage('MAN\u0303ANA PESCA'), 'es');
});

test('upper-case accented word plus ¿ or ¡ is Spanish', () => {
  assert.equal(detectLanguage('¿QUÉ PICA?'), 'es');
  assert.equal(detectLanguage('¡HOLA PESCADORES!'), 'es');
});

test('the marker does not override an English word (en === 0 still required)', () => {
  assert.equal(detectLanguage('Ñ hello'), null);
  assert.equal(detectLanguage('MAÑANA hello'), null);
  assert.equal(detectLanguage('man\u0303ana today'), null);
});

test('the marker alone, without a Spanish word, is not Spanish (es >= 1 still required)', () => {
  assert.equal(detectLanguage('ÑÑÑ'), null);
  assert.equal(detectLanguage('N\u0303 PESCA'), null);
  assert.equal(detectLanguage('¿¡'), null);
});

test('a Spanish word without any marker is still not enough', () => {
  assert.equal(detectLanguage('HOY PESCA'), null);
});

test('English detection is unchanged', () => {
  assert.equal(detectLanguage('what is biting today'), 'en');
  assert.equal(detectLanguage('WHAT IS BITING TODAY'), 'en');
});

test('three-word Spanish detection is unchanged', () => {
  assert.equal(detectLanguage('qué hay en la bahía'), 'es');
});

test('non-string input gives null and does not throw', () => {
  for (const value of [undefined, null, 42]) {
    assert.doesNotThrow(() => detectLanguage(value));
    assert.equal(detectLanguage(value), null, String(value));
  }
});
