import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

const workflow = readFileSync(new URL('../.github/workflows/feed-freshness.yml', import.meta.url), 'utf8');
const step = workflow.match(/^      - name: Probe the rules card and alert once when it is blank\n(?:[^\n]+\n)*?        run: \|\n((?:          [^\n]*\n)+)/m);
assert.ok(step, 'expected a literal rules alarm shell step');

const stubs = String.raw`
PATH=/nonexistent
GITHUB_STEP_SUMMARY=summary
GITHUB_SERVER_URL=https://example.invalid
GITHUB_REPOSITORY=synthetic/repository
GITHUB_RUN_ID=1
FEEDS_PUBLIC_BASE=https://example.invalid
node() {
  printf 'probe %s\n' "$3" >>trace
  if [[ "$1" != scripts/rules_status_probe.mjs || "$2" != --region ]]; then exit 99; fi
  if [[ "$3" == "$missing" ]]; then printf 'missing status\n'; return 3; fi
  printf 'healthy\n'
}
gh() {
  case "$1:$2" in
    label:create) return 1 ;; # Existing label is not a delivery failure.
    issue:list|issue:create) printf '%s\n' "$2" >>trace ;;
    issue:edit|issue:close) printf '%s %s\n' "$2" "$3" >>trace ;;
    *) printf 'unexpected fake gh call\n' >&2; return 99 ;;
  esac
  if [[ "$2" == list && -n "$existing_ids" ]]; then printf '%s\n' "$existing_ids"; fi
  if [[ "$2" == "$failed" ]]; then return 19; fi
  if [[ "$2" == close ]]; then printf '%s\n' "$5"; fi
}
missing=$1
failed=$2
existing_ids=$3
`;

const regions = ['morro-bay', 'cambria-san-simeon', 'south-big-sur-san-simeon',
  'big-sur-coast', 'monterey-point-sur', 'point-arguello-conception'];

// The real step used to discard list and write errors, making an undelivered
// alarm look as successful as an advisory that reached its issue.
for (const [name, missing, failed, existing, actions] of [
  ['missing status, list fails', regions[3], 'list', '', ['list']],
  ['missing status, create fails', regions[3], 'create', '', ['list', 'create']],
  ['missing status, edit fails', regions[3], 'edit', '42', ['list', 'edit 42']],
  ['missing status, create succeeds', regions[3], '', '', ['list', 'create']],
  ['healthy, partial list fails', '', 'list', '42', ['list']],
  ['healthy, close fails', '', 'close', '42', ['list', 'close 42']],
  ['healthy, close succeeds', '', '', '42', ['list', 'close 42']],
]) {
  test(name, () => {
    const dir = mkdtempSync(join(tmpdir(), 'rules-alarm-'));
    try {
      const script = join(dir, 'rules.sh');
      writeFileSync(script, stubs + step[1]);
      const run = spawnSync('/bin/bash', ['--noprofile', '--norc', '-e', script, missing, failed, existing], {
        cwd: dir, encoding: 'utf8', env: {}, timeout: 5000,
      });
      assert.ifError(run.error);
      assert.equal(run.status, failed ? 1 : 0, run.stderr || run.stdout);
      const trace = readFileSync(join(dir, 'trace'), 'utf8').trimEnd().split('\n');
      assert.deepEqual(trace, [...regions.map((region) => `probe ${region}`), ...actions]);
      const summary = readFileSync(join(dir, 'summary'), 'utf8');
      if (missing) assert.ok(summary.includes(`${missing} (probe exit 3)\nmissing status`));
      if (failed) assert.match(run.stdout, new RegExp(`::error .*Issue delivery failed \\(gh issue ${failed}, exit 19\\)`));
      else assert.doesNotMatch(run.stdout, /::error/);
      assert.equal(run.stdout.includes('Recovered:'), !failed && actions.includes('close 42'));
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
}
