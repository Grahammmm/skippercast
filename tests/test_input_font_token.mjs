import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const read = path => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
// Reads only the checked-out tree: a shallow CI checkout has no origin/main to diff against.
const block = (css, selector) => {
  const start = css.indexOf(selector);
  assert.notEqual(start, -1, `${selector}: rule present`);
  return css.slice(css.indexOf('{', start) + 1, css.indexOf('}', start));
};

test('one shared font-size-only rule and exact input token preserve authored widths and viewport zoom', () => {
  assert.match(read('web/tokens.css'), /--text-input:\s*16px;/);
  const rules = [...read('web/ui/ui.css').matchAll(/input,\s*select,\s*textarea\s*\{([^}]+)\}/g)];
  assert.equal(rules.length, 1);
  assert.equal(rules[0][1].trim(), 'font-size: var(--text-input) !important;');
  // Component width constraints stay as authored (the shared rule changes font-size only).
  assert.match(block(read('web/landing/landing.css'), '.landing .port-input {'), /max-width:\s*none;/);
  const port = read('web/landing/port-input.css');
  assert.match(block(port, '.port-input {'), /max-width:\s*520px;/);
  assert.match(block(port, '.port-input input {'), /flex:\s*1;\s*min-width:\s*0;/);
  assert.match(block(port, '.app-share-popover input {'), /width:\s*min\(320px,\s*80vw\);/);
  const account = read('web/app/account.css');
  assert.match(block(account, '.boat-query-row input {'), /flex:\s*1;/);
  assert.match(account, /\.home-port-card :is\(input, select\), \.app-alerts :is\(input, select\) \{ width: 100%; \}/);
  assert.match(read('web/app/trip.css'), /\.app-trip :is\(input:not\(\[type="checkbox"\]\), select\) \{ width: 100%; \}/);
  assert.match(read('web/app/app.css'), /\.app-target-search\s*\{[^}]*width:\s*133px;/);
  for (const path of ['dist/app.html', 'dist/landing.html']) {
    assert.doesNotMatch(read(path), /maximum-scale|user-scalable\s*=\s*no/);
  }
});
