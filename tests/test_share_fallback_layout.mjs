import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const css = readFileSync(new URL('../web/landing/port-input.css', import.meta.url), 'utf8');
const rule = selector => {
  const start = css.indexOf(`${selector} {`);
  assert.ok(start >= 0, selector);
  return css.slice(start, css.indexOf('}', start));
};
test('share disclosure and body reserve flow space; feedback and field stay bounded', () => {
  assert.match(rule('.app-share'), /flex-wrap: wrap/);
  assert.match(rule('.app-share'), /gap: var\(--space-1\)/);
  for (const selector of ['.app-share', '.app-share-status', '.app-share-popover', '.app-share-popover input']) {
    assert.match(rule(selector), /min-width: 0/);
    assert.match(rule(selector), /max-width: 100%/);
  }
  assert.match(rule('.app-share-popover'), /position: static/);
  assert.match(rule('.app-share-popover'), /flex-basis: 100%/);
  assert.match(rule('.app-share-popover > .ui-popover-body'), /position: static/);
  for (const selector of ['.app-share-popover > .ui-popover-body', '.app-share-popover input']) {
    assert.match(rule(selector), /box-sizing: border-box/);
    assert.match(rule(selector), /max-width: 100%/);
  }
  assert.match(rule('.app-share-status:empty'), /display: none/);
  assert.match(rule('.app-share-status'), /overflow-wrap: anywhere/);
  assert.doesNotMatch(css.slice(css.indexOf('/* BF-deep-links:'), css.indexOf('/* Measured model gaps')), /position: absolute|white-space: nowrap|z-index:|overflow: hidden/);
});
