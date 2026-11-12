// S4-48: build-time Git provenance for /api/health (scripts/build-revision.mjs).
import test from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {mkdtempSync, writeFileSync, readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {build} from 'esbuild';
import {readBuildRevision} from '../scripts/build-revision.mjs';

const git = (cwd, ...args) => execFileSync('git', ['-c', 'user.name=t', '-c', 'user.email=t@example.com', '-c', 'commit.gpgsign=false', ...args], {cwd, encoding: 'utf8'}).trim();
const NULLS = {revision: null, revision_dirty: null};
function repo() {
  const dir = mkdtempSync(join(tmpdir(), 'rev-'));
  git(dir, 'init', '-q'); writeFileSync(join(dir, '.gitignore'), 'out.txt\n'); writeFileSync(join(dir, 'a.txt'), 'a\n');
  git(dir, 'add', '.'); git(dir, 'commit', '-q', '-m', 'init');
  return dir;
}

test('clean checkout reports the full commit; a linked worktree works', () => {
  const dir = repo(), head = git(dir, 'rev-parse', 'HEAD');
  assert.match(head, /^[0-9a-f]{40}$/);
  assert.deepEqual(readBuildRevision(dir), {revision: head, revision_dirty: false});
  const linked = join(mkdtempSync(join(tmpdir(), 'rev-wt-')), 'wt');
  git(dir, 'worktree', 'add', '-q', '--detach', linked);
  assert.deepEqual(readBuildRevision(linked), {revision: head, revision_dirty: false});
});

test('tracked edits mark dirty; untracked and ignored files do not', () => {
  const dir = repo(), head = git(dir, 'rev-parse', 'HEAD');
  writeFileSync(join(dir, 'new.txt'), 'x'); writeFileSync(join(dir, 'out.txt'), 'x');
  assert.deepEqual(readBuildRevision(dir), {revision: head, revision_dirty: false});
  writeFileSync(join(dir, 'a.txt'), 'changed\n');
  assert.deepEqual(readBuildRevision(dir), {revision: head, revision_dirty: true});
  git(dir, 'add', 'a.txt');
  assert.deepEqual(readBuildRevision(dir), {revision: head, revision_dirty: true});
});

test('unknown revision is null, never a build hash', () => {
  assert.deepEqual(readBuildRevision(mkdtempSync(join(tmpdir(), 'norepo-'))), NULLS);
  const unborn = mkdtempSync(join(tmpdir(), 'unborn-')); git(unborn, 'init', '-q');
  assert.deepEqual(readBuildRevision(unborn), NULLS);
  const calls = [], ok = 'b'.repeat(40);
  const fake = outputs => (cmd, args, options) => { calls.push([cmd, args, options]); const out = outputs.shift(); if (out instanceof Error) throw out; return out; };
  for (const outputs of [[Error('ENOENT git not found at /secret/path')], ['abc123\n'], ['B'.repeat(40) + '\n'], [ok + '\n', Error('status failed')],
    [Object.assign(Error('ETIMEDOUT'), {code: 'ETIMEDOUT'})]]) assert.deepEqual(readBuildRevision('/root', fake(outputs)), NULLS);
  calls.length = 0;
  assert.deepEqual(readBuildRevision('/root', fake([ok + '\n', ' M a.txt\n'])), {revision: ok, revision_dirty: true});
  assert.deepEqual(calls.map(c => c[0]), ['git', 'git']);
  assert.deepEqual(calls.map(c => c[1]), [['rev-parse', '--verify', 'HEAD'], ['status', '--porcelain', '--untracked-files=no']]);
  for (const [, , o] of calls) assert.deepEqual([o.cwd, o.encoding, o.timeout, o.maxBuffer], ['/root', 'utf8', 2000, 65536]);
});

test('the metadata survives the Worker bundle without runtime Git or env reads; build is untouched', async () => {
  const bundle = async revision => {
    const result = await build({entryPoints: [new URL('../server/routes/public.ts', import.meta.url).pathname], bundle: true, write: false, format: 'esm', platform: 'browser', target: 'es2022',
      define: {BUILD_ID: '"hash-1"', BUILD_REVISION: JSON.stringify(revision), REGIONS: '{}', DEPLOYMENT: '{}', SHELLS: '{}', ADVISOR_ASSETS: '{}', NOT_FOUND_HTML: '""'}, logLevel: 'silent'});
    const dir = mkdtempSync(join(tmpdir(), 'bundle-')), file = join(dir, 'p.mjs');
    writeFileSync(file, result.outputFiles[0].text);
    assert.doesNotMatch(result.outputFiles[0].text, /child_process/);
    const {publicApi} = await import(file);
    return (await publicApi.request('/api/health')).json();
  };
  const one = await bundle({revision: 'c'.repeat(40), revision_dirty: false}), two = await bundle({revision: 'd'.repeat(40), revision_dirty: true});
  assert.deepEqual([one.build, one.revision, one.revision_dirty], ['hash-1', 'c'.repeat(40), false]);
  assert.deepEqual([two.build, two.revision, two.revision_dirty], ['hash-1', 'd'.repeat(40), true]);
  const worker = readFileSync(new URL('../scripts/build-worker.mjs', import.meta.url), 'utf8');
  assert.match(worker, /readBuildRevision\(/); assert.match(worker, /BUILD_REVISION:JSON\.stringify\(buildRevision\)/);
});
