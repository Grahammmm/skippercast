import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';

const html = readFileSync(new URL('../dist/coverage.html', import.meta.url), 'utf8');
const fallback = html.match(/<noscript\b[^>]*>([\s\S]*?)<\/noscript>/i)?.[1] ?? '';

// Copy added to the JS-rendered map alone would leave the no-script reader uninformed.
test('English no-script copy distinguishes geographic extent from full depth coverage', () => {
  assert.match(fallback, /rectangles show the geographic extent/i);
  assert.match(fallback, /do not prove that depth data covers the entire area/i);
  assert.match(fallback, /without JavaScript, you cannot check the current status of seafloor relief data/i);
});

// A partial translation might leave the warning in English only or omit the language tag.
test('Spanish no-script copy gives the same limits in a Spanish-language paragraph', () => {
  const spanish = fallback.match(/<p\s+lang="es">([\s\S]*?)<\/p>/i)?.[1] ?? '';
  assert.match(spanish, /rectángulos muestran la extensión geográfica/i);
  assert.match(spanish, /no demuestran que haya datos de profundidad en toda el área/i);
  assert.match(spanish, /sin JavaScript, no se puede comprobar el estado actual de los datos de relieve/i);
});

// A Sources link generated only for a ready pointer would disappear without JS.
test('the static navigation retains a Sources link without relying on pointer status', () => {
  const nav = html.match(/<nav\b[^>]*>([\s\S]*?)<\/nav>/i)?.[1] ?? '';
  assert.match(nav, /<a\s[^>]*\bhref="\/sources"[^>]*>\s*Sources\s*<\/a>/i);
});
