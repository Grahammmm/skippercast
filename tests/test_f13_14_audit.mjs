// F13-14: the phone account-trigger CSS block was pasted twice, so an edit to the first copy was silently masked by the second.
// Contract: web/app/app.css carries exactly one copy of the block (the collapsed trigger, its expanded colour, the visually hidden
// name, and the stacking raise while the panel is open). A believable regression is a merge or paste that brings the duplicate back.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';

const css = readFileSync(new URL('../web/app/app.css', import.meta.url), 'utf8');
const SELECTORS = [
  '.app-account[data-top] > .app-account-top-trigger {',
  '.app-account[data-top] > .app-account-top-trigger[aria-expanded="true"] {',
  '.app-account[data-top] > .app-account-top-trigger > .app-account-label {',
  '.app-top:has(.app-account[data-top] .app-account-panel:not([hidden])) {',
];
const COMMENT = '/* UXFIX-10: the phone\'s top-card account entry (data-top)';
const count = (source, needle) => source.split(needle).length - 1;
const copies = source => [COMMENT, ...SELECTORS].map(needle => count(source, needle));
const exactlyOne = source => copies(source).every(n => n === 1);

test('one copy of the phone account-trigger block remains', () => {
  assert.deepEqual(copies(css), [1, 1, 1, 1, 1], 'the comment and each of the four selectors appear once');
});

test('the remaining block keeps the trigger, hidden name and open-panel stacking declarations', () => {
  const rule = selector => css.slice(css.indexOf(selector)).split('\n', 1)[0];
  assert.match(rule(SELECTORS[0]), /min-inline-size: calc\(var\(--touch-min\) \+ 0\.5px\).*box-shadow: var\(--elev-2\)/);
  assert.match(rule(SELECTORS[1]), /background: var\(--panel-2\)/);
  assert.match(rule(SELECTORS[2]), /width: 1px; height: 1px;.*clip-path: inset\(50%\)/);
  assert.match(rule(SELECTORS[3]), /z-index: var\(--z-modal\)/);
});

test('negative control: the two-copy source is rejected, the one-copy source accepted', () => {
  const start = css.indexOf(COMMENT);
  const block = css.slice(start, css.indexOf('\n', css.indexOf(SELECTORS[3], start)) + 1);
  assert.equal(block.split('\n').filter(Boolean).length, 5, 'the block is the five comment and rule lines');
  const tile = css.indexOf('/* UXFIX-09:');
  const twoCopies = css.slice(0, tile) + block + css.slice(tile);
  assert.deepEqual(copies(twoCopies), [2, 2, 2, 2, 2]);
  assert.equal(exactlyOne(twoCopies), false);
  assert.equal(exactlyOne(css), true);
});
