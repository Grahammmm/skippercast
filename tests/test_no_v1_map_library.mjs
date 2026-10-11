// FE-61 (docs/plans/front-end/dev-plan.md): the v1 shell and its 2D map
// library are gone. No tracked file (or new, unignored one) loads, ships or
// names that library again, outside the dated history: docs/, research/ and
// CHANGELOG.md keep their records, and this test names it to search for it.
import test from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {existsSync, readFileSync, statSync} from 'node:fs';
import {join} from 'node:path';

const ROOT = new URL('..', import.meta.url).pathname;
const HISTORY = [/^docs\//, /^research\//, /^CHANGELOG\.md$/, /^tests\/test_no_v1_map_library\.mjs$/];
const NAME = new RegExp(['leaf', 'let'].join(''), 'i');

test('no file outside the dated history names the retired 2D map library', t => {
  let listed;
  try { listed = execFileSync('git', ['ls-files', '-z', '--cached', '--others', '--exclude-standard'], {cwd: ROOT, encoding: 'utf8', maxBuffer: 1 << 28}); } catch { t.skip('git is unavailable'); return; }
  const files = listed.split('\0').filter(Boolean).filter(path => !HISTORY.some(pattern => pattern.test(path)));
  assert.ok(files.length > 1000, `listed ${files.length} files`);
  const found = [];
  for (const path of files) {
    const full = join(ROOT, path);
    if (!existsSync(full) || !statSync(full).isFile()) continue;   // deleted in the working tree
    if (NAME.test(path)) { found.push(path); continue; }
    if (statSync(full).size > 32 << 20) continue;
    const data = readFileSync(full);
    if (data.includes(0)) continue;   // binary
    const text = data.toString('utf8');
    if (NAME.test(text)) found.push(`${path}:${text.split('\n').findIndex(line => NAME.test(line)) + 1}`);
  }
  assert.deepEqual(found, []);
});
