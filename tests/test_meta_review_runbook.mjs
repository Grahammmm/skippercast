import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import assert from 'node:assert/strict';

const read = path => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
const doc = read('docs/operations/runbooks/advisor-meta-app-review.md');
const env = read('server/env.ts');
const source = [
  'server/routes/advisor.ts', 'server/advisor/social/meta.ts',
  'server/advisor/social/inbox.ts', 'server/advisor/social/publish.ts',
  'server/advisor/admin/health.ts', 'server/advisor/channels/instagram.ts',
  'scripts/advisor/meta-token.mjs',
].map(read).join('\n');
const meta = read('server/advisor/social/meta.ts');

// Check actual property accesses and declarations, not stale mentions in comments.
function check(runbook, declarations, code, metaCode) {
  const names = new Set([...runbook.matchAll(/`(META_[A-Z0-9_]+)`/g)].map(m => m[1]));
  assert.ok(names.size, 'runbook contains no quoted META_* names');
  const declared = new Set([...declarations.matchAll(/^\s*(META_[A-Z0-9_]+)\?:/gm)].map(m => m[1]));
  const activeCode = code.replace(/^\s*\/\/.*$/gm, '');
  const used = new Set([...activeCode.matchAll(/\benv\.(META_[A-Z0-9_]+)\b/g)].map(m => m[1]));
  for (const name of names) {
    assert.ok(declared.has(name), `runbook variable ${name} missing from Env`);
    assert.ok(used.has(name), `runbook variable ${name} missing from code accesses`);
  }
  const quotes = [...runbook.matchAll(/subscribed_fields=([a-z_]+(?:,[a-z_]+)*)/g)];
  assert.ok(quotes.length, 'runbook contains no subscribed_fields values');
  const actual = metaCode.match(/^export const SUBSCRIBED_FIELDS = ['"]([^'"]+)['"]/m);
  assert.ok(actual, 'code has no SUBSCRIBED_FIELDS constant');
  const fields = new Set(actual[1].split(','));
  for (const [, list] of quotes) for (const field of list.split(',')) {
    assert.ok(fields.has(field), `runbook subscribed field ${field} missing from code`);
  }
  return [...declared].filter(name => !names.has(name)).sort();
}

test('runbook Meta names and subscribed fields match code', t => {
  const undocumented = check(doc, env, source, meta);
  t.diagnostic(`Code Env variables not in runbook: ${undocumented.join(', ') || '(none)'}`);
});

test('a renamed code variable fails and names the missing variable', () => {
  const renamed = 'META_VERIFY_TOKEN_RENAMED';
  assert.throws(() => check(doc, env.replaceAll('META_VERIFY_TOKEN', renamed),
    source.replaceAll('META_VERIFY_TOKEN', renamed), meta), /META_VERIFY_TOKEN missing/);
});

test('a renamed subscribed field fails with the missing field', () => {
  assert.throws(() => check(doc, env, source,
    meta.replace("SUBSCRIBED_FIELDS = 'messages,comments'", "SUBSCRIBED_FIELDS = 'messages,renamed'")),
  /subscribed field comments missing/);
});

test('undocumented code variables are reported', () => {
  assert.ok(check(doc, env + '\n  META_NEW_SECRET?: string;', source, meta).includes('META_NEW_SECRET'));
});

test('empty extraction never passes', () => {
  assert.throws(() => check('no variables here', env, source, meta), /no quoted META_\* names/);
  assert.throws(() => check('`META_APP_ID`', env, source, meta), /no subscribed_fields values/);
});
