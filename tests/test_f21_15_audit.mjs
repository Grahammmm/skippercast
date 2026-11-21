// F21-15: a same-HEAD retry must exclude dirty bytes without losing the lease.
// Exercise the publisher with real staging and a simulated remote ref, not a push.
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {fileURLToPath} from 'node:url';


const publisher = fileURLToPath(new URL('../scripts/publish_branch_snapshot.sh', import.meta.url));
const ref = 'refs/fixture/remote';
// Only local object/index operations reach Git. The simulated origin is a
// separate local ref updated with a compare-and-swap, never a Git transport.
const shim = `git() {
  if [ "$1" = ls-remote ] && [ "$#" = 3 ] && [ "$2" = origin ] && [ "$3" = refs/heads/data ]; then
    printf '%s\\t%s\\n' "$(command git rev-parse '${ref}')" "$3"
    return
  fi
  if [ "$1" = -C ] && [ "$2" = "$PWD" ]; then
    shift 2
    case "$1" in
      rev-parse|status|add|write-tree|commit-tree|reset) command git "$@"; return ;;
      push)
        [ "$#" = 5 ] && [ "$2" = -q ] && [ "$4" = origin ] || return 99
        [ "$(printf '%s' "$3" | cut -d: -f1)" = --force-with-lease=refs/heads/data ] || return 99
        [ "$(printf '%s' "$5" | cut -d: -f2)" = refs/heads/data ] || return 99
        command git update-ref '${ref}' "$(printf '%s' "$5" | cut -d: -f1)" "$(printf '%s' "$3" | cut -d: -f2)"
        return ;;
    esac
  fi
  printf '%s\\n' 'unexpected git operation in offline fixture' >&2
  return 99
}
source "$@"
`;

test('F21-15: dirty same-HEAD loads refuse before a retry can stage leftovers', t => {
  const dir = realpathSync(mkdtempSync(join(tmpdir(), 'sca-594-')));
  t.after(() => rmSync(dir, {recursive: true, force: true}));
  const cwd = join(dir, 'stage');
  mkdirSync(cwd);
  const env = {PATH: process.env.PATH, HOME: dir, GIT_CONFIG_NOSYSTEM: '1', GIT_CONFIG_GLOBAL: '/dev/null',
    GIT_ALLOW_PROTOCOL: '', GIT_AUTHOR_NAME: 'Fixture', GIT_AUTHOR_EMAIL: 'fixture@example.invalid',
    GIT_COMMITTER_NAME: 'Fixture', GIT_COMMITTER_EMAIL: 'fixture@example.invalid'};
  const run = (exe, ...args) => spawnSync(exe, args, {cwd, env, encoding: 'utf8', timeout: 5000});
  const git = (...args) => {
    const result = run('git', ...args);
    assert.equal(result.status, 0, result.error?.message ?? result.stderr);
    return result.stdout.trimEnd();
  };
  const wrapper = join(dir, 'shim.sh');
  writeFileSync(wrapper, shim);
  git('init', '-q', '--initial-branch=fixture');
  const write = (name, text) => writeFileSync(join(cwd, name), text);
  write('latest.json', 'original\n');
  write('stable.txt', 'published bytes\n');
  git('add', '-A');
  git('commit', '-qm', 'seed published bytes');
  const base = git('rev-parse', 'HEAD');
  git('update-ref', ref, base);
  const call = (...args) => run('bash', wrapper, publisher, ...args);
  const load = () => call('--load', 'data', cwd);
  const initial = load();
  assert.equal(initial.status, 0, initial.error?.message ?? initial.stderr);
  const assertRefused = () => {
    const result = load();
    assert.equal(result.status, 1, result.error?.message ?? result.stderr);
    assert.match(result.stderr, /dirty/);
    assert.equal(git('rev-parse', ref), base, 'refusal leaves published bytes alone');
    assert.equal(git('rev-parse', 'HEAD'), base, 'refusal leaves local HEAD alone');
  };
  // Check each kind of residue alone so neither can hide a missed dirty check.
  write('sentinel.txt', 'failed attempt\n');
  assertRefused();
  assert.equal(readFileSync(join(cwd, 'sentinel.txt'), 'utf8'), 'failed attempt\n');
  // Only the fixture owner removes its known leftovers before retrying.
  rmSync(join(cwd, 'sentinel.txt'));
  write('stable.txt', 'failed attempt tracked change\n');
  assertRefused();
  assert.equal(readFileSync(join(cwd, 'stable.txt'), 'utf8'), 'failed attempt tracked change\n');
  write('stable.txt', 'published bytes\n');
  const clean = load();
  assert.equal(clean.status, 0, clean.error?.message ?? clean.stderr);
  write('latest.json', 'retry\n');
  const retry = call('data', cwd, 'retry');
  assert.equal(retry.status, 0, retry.error?.message ?? retry.stderr);
  const accepted = git('rev-parse', ref);
  const snapshot = git('ls-tree', '-r', '--name-only', accepted).split('\n');
  const stable = git('show', `${accepted}:stable.txt`);
  assert.equal(git('show', `${accepted}:latest.json`), 'retry');

  const concurrent = git('commit-tree', `${accepted}^{tree}`, '-m', 'competing snapshot');
  git('update-ref', ref, concurrent, accepted);
  write('latest.json', 'stale writer\n');
  const stale = call('data', cwd, 'stale');
  assert.equal(stale.status, 1, stale.error?.message ?? stale.stderr);
  assert.match(stale.stderr, /not overwritten/);
  assert.equal(git('rev-parse', ref), concurrent, 'lease preserves the competing snapshot');
  assert.equal(git('rev-parse', 'HEAD'), accepted, 'refused publication leaves local HEAD unchanged');
  assert.deepEqual({snapshot, stable}, {snapshot: ['latest.json', 'stable.txt'], stable: 'published bytes'},
    'failed-attempt sentinel and tracked edit must not enter the retry snapshot');
});
