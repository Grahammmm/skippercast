// Source contract only: browser clipping and focus are covered in e2e.
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import assert from 'node:assert/strict';
const css = readFileSync(new URL('../web/app/app.css', import.meta.url), 'utf8');
const block = css.split('/* RF1935-4:')[1].split('/* end RF1935-4 */')[0];
const activation = '.app-mobile:has(.app-sheet .app-target-search:focus)';
const rules = [...block.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^[^]*?\*\//, '').matchAll(/([^{}]+)\{([^{}]*)\}/g)].map(m => [m[1].trim(), m[2]]);
test('focus is confined to the actual mobile sheet target, never other inputs or focus-within', () => {
  assert.equal(rules.length, 4);
  for (const [selector] of rules) assert.ok(selector.startsWith(activation));
  assert.ok(!block.includes(':focus-within'));
  assert.ok(!block.includes('@media'));
});
test('editing releases both chrome reservations but preserves safe insets and removes tab stops', () => {
  assert.match(rules[0][1], /--app-tabs:\s*env\(safe-area-inset-bottom, 0px\)/);
  assert.match(rules[0][1], /--app-strip:\s*env\(safe-area-inset-top, 0px\)/);
  assert.equal(rules[1][0], `${activation} .app-tabs`);
  assert.match(rules[1][1], /display:\s*none/);
});
test('all detents use an unanimated editing sheet and unclipped shrinking scroll body', () => {
  assert.equal(rules[2][0], `${activation} .app-sheet`);
  assert.match(rules[2][1], /transform:\s*translateY\(0\)/);
  assert.match(rules[2][1], /transition:\s*none/);
  // Five class/pseudo-class components beat ordinary two-component detent rules,
  // without rewriting the stored detent or primitive Sheet contract.
  assert.ok(css.indexOf('/* RF1935-4:') > css.lastIndexOf('.app-sheet[data-detent="full"]'));
  assert.equal(rules[3][0], `${activation} .app-sheet .ui-sheet-body`);
  assert.match(rules[3][1], /min-height:\s*0/);
  assert.match(rules[3][1], /overflow:\s*auto/);
  assert.doesNotMatch(block, /(?:color|background|opacity|padding|z-index)\s*:/);
});
