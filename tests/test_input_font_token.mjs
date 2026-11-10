import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
const read = path => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');

test('one shared font-size-only rule and exact input token preserve authored widths and viewport zoom', () => {
  assert.match(read('web/tokens.css'), /--text-input:\s*16px;/);
  const rules = [...read('web/ui/ui.css').matchAll(/input,\s*select,\s*textarea\s*\{([^}]+)\}/g)];
  assert.equal(rules.length, 1);
  assert.equal(rules[0][1].trim(), 'font-size: var(--text-input) !important;');
  for (const path of ['web/landing/landing.css', 'web/landing/port-input.css', 'web/app/account.css', 'web/app/trip.css']) {
    const baseline = execFileSync('git', ['show', `origin/main:${path}`], {encoding: 'utf8'});
    // Other component constraints remain unchanged.
    assert.ok(read(path) === baseline, `${path}: component constraints unchanged`);
  }
  assert.match(read('web/app/app.css'), /\.app-target-search\s*\{[^}]*width:\s*133px;/);
  for (const path of ['dist/app.html', 'dist/landing.html']) {
    assert.doesNotMatch(read(path), /maximum-scale|user-scalable\s*=\s*no/);
  }
});
