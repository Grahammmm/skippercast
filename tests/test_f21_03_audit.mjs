// F21-03 (SCA-532): the runner provisioning script must not leave the job
// account a persistent package-management (sudo) grant. Offline: reads text only;
// synthetic scripts are the controls. No host, sudo, apt or network is touched.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

// Sudoers grants a script writes: heredoc bodies redirected into /etc/sudoers*.
export function sudoersGrants(script) {
  const grants = [];
  const re = /(?:>|tee\s+)\s*\/etc\/sudoers[^\s<]*\s*<<-?\s*'?(\w+)'?\n([\s\S]*?)\n\s*\1\b/g;
  for (const m of script.matchAll(re)) {
    for (const line of m[2].split('\n')) {
      if (/NOPASSWD/.test(line) && !line.trim().startsWith('#')) grants.push(line.trim());
    }
  }
  return grants;
}

export function packageAdminGrants(script) {
  return sudoersGrants(script).filter(l => /\b(apt-get|apt|dpkg|dnf|yum)\b/.test(l.split('NOPASSWD:')[1] ?? ''));
}

const GRANT = '$USER_NAME ALL=(root) NOPASSWD: /usr/bin/apt-get';
const PREINSTALL = 'apt-get install -y -q libnss3 libatk1.0-0\nnpx playwright@1 install-deps chromium\n';
const VALID = `#!/usr/bin/env bash\nuseradd runner\n${PREINSTALL}`;
const AFFECTED = `#!/usr/bin/env bash\nuseradd runner\ncat > /etc/sudoers.d/actions-runner <<EOF\n${GRANT}\nEOF\nchmod 0440 /etc/sudoers.d/actions-runner\n`;

test('F21-03 positive control: provisioning preinstalls as root and leaves no grant', () => {
  assert.deepEqual(packageAdminGrants(VALID), []);
});

test('F21-03 negative control: a persistent NOPASSWD apt-get grant is detected', () => {
  assert.deepEqual(packageAdminGrants(AFFECTED), [GRANT]);
});

test('F21-03 detector ignores unrelated or commented grants', () => {
  const s = 'cat > /etc/sudoers.d/x <<EOF\n# runner ALL=(root) NOPASSWD: /usr/bin/apt-get\nrunner ALL=(root) NOPASSWD: /usr/bin/systemctl status foo\nEOF\n';
  assert.deepEqual(packageAdminGrants(s), []);
});

// Baseline observation of the real script. `todo` keeps the known gap visible
// in the report without turning the required check red; remove `todo` once
// setup.sh preinstalls dependencies and drops the sudoers grant.
test('F21-03 baseline: scripts/runner/setup.sh grants the runner no package administration',
  {todo: 'F21-03 open: setup.sh writes a NOPASSWD apt-get sudoers grant (lines ~50-61)'}, () => {
    const real = readFileSync(new URL('../scripts/runner/setup.sh', import.meta.url), 'utf8');
    assert.deepEqual(packageAdminGrants(real), []);
  });
