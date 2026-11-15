// CI-PARITY-1: a pull request must run the same e2e projects as main.
// Since CI-2, main pushes ran E2E_WIDE=1 while pull requests did not, so main ran tests no pull
// request could run, and a fix pull request went green without running the test it fixed.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';

const workflow = readFileSync(fileURLToPath(new URL('../.github/workflows/ci.yml', import.meta.url)), 'utf8');

// The e2e job: from its key to the next job key (two-space indent), comment lines dropped.
const job = workflow.split(/^  e2e:\n/m)[1]?.split(/^  [a-z][\w-]*:\n/m)[0] ?? '';
const offenders = job.split('\n').filter(line => !/^\s*#/.test(line) && /\bE2E_\w+/.test(line) && /github\.event_name/.test(line));

test('ci.yml e2e job never sets an E2E_* variable from github.event_name', () => {
  assert.ok(job.includes('E2E_WIDE'), 'the e2e job was not found in ci.yml (key renamed?)');
  assert.deepEqual(offenders, [],
    'A pull request and main must run the same e2e projects. Setting an E2E_* variable from github.event_name lets main run ' +
    'tests a pull request cannot run, so a fix pull request goes green without running the test it fixes. Set it for every event.');
});
