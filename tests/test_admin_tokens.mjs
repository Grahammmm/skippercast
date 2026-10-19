// US-L3: every custom property the admin reads (web/admin/** and dist/advisor/admin.css)
// is declared in web/tokens.css. #705 moved the admin onto web/tokens.css and checked
// this by hand; v1-only names (--ink, --brand, --surface …) resolve to nothing and draw
// transparent backgrounds and missing strokes. scripts/check_tokens.mjs lints literals;
// this guards undefined names.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, readdirSync} from 'node:fs';
import {join, relative} from 'node:path';
import {fileURLToPath} from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const SOURCES = /\.(?:tsx?|css)$/;

/** Every custom property declared (`--name:`) in a stylesheet. */
function declared(css) {
  return new Set([...css.replace(/\/\*[\s\S]*?\*\//g, '').matchAll(/(--[a-z0-9-]+)\s*:/gi)].map(m => m[1]));
}
/** Every `var(--name)` read in a source, with its line, whose name is not declared. */
function undeclared(file, text, names) {
  return text.split('\n').flatMap((line, i) =>
    [...line.matchAll(/var\(\s*(--[a-z0-9-]+)/gi)].filter(m => !names.has(m[1])).map(m => `${file}:${i + 1} reads ${m[1]}, which web/tokens.css does not declare`));
}

function walk(dir) {
  return readdirSync(dir, {withFileTypes: true}).flatMap(e => (e.isDirectory() ? walk(join(dir, e.name)) : SOURCES.test(e.name) ? [join(dir, e.name)] : []));
}

const TOKENS = declared(readFileSync(join(ROOT, 'web/tokens.css'), 'utf8'));
const FILES = [...walk(join(ROOT, 'web/admin')), join(ROOT, 'dist/advisor/admin.css')];

test('the admin reads only custom properties web/tokens.css declares', () => {
  const reads = FILES.map(f => [relative(ROOT, f), readFileSync(f, 'utf8')]);
  assert.ok(reads.some(([f]) => f === 'web/admin/fleet-trip.tsx'), 'web/admin/fleet-trip.tsx is scanned');
  assert.ok(reads.reduce((n, [, t]) => n + (t.match(/var\(--/g)?.length ?? 0), 0) > 50, 'the scan finds the admin\'s var() reads');
  assert.deepEqual(reads.flatMap(([f, t]) => undeclared(f, t, TOKENS)), []);
});

test('a v1-only name is reported with its file and line', () => {
  assert.ok(TOKENS.has('--text') && TOKENS.has('--bg') && !TOKENS.has('--ink'));
  assert.deepEqual(undeclared('web/admin/x.tsx', "a\nstroke={'var(--ink)'} fill='var(--text, var(--surface))'", TOKENS), [
    'web/admin/x.tsx:2 reads --ink, which web/tokens.css does not declare',
    'web/admin/x.tsx:2 reads --surface, which web/tokens.css does not declare',
  ]);
});
