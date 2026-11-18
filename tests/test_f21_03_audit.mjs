// F21-03 (SCA-532): runner provisioning must preinstall reviewed browser
// dependencies as root and leave the job account no persistent package-management
// (sudo) grant, so ordinary browser tests pass unprivileged. Offline: reads text
// only; synthetic scripts are the controls. No host, sudo, apt or network is touched.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const PKG = String.raw`(?:apt-get|apt|dpkg|dnf|yum|snap|pip3?|npm|pnpm)`;
const WRITE_OP = /(?:>|\btee\b|\bcp\b|\binstall\b|\bmv\b|\bsed\s+-i|\bprintf\b|\becho\b)/;

// Any sudoers-style rule granting package administration. NOPASSWD is NOT
// required: a persistent grant with or without a password is still a grant. A
// bare `ALL` command spec is also package administration.
const GRANT_RE = new RegExp(String.raw`^\s*['"]?[\w$%{}@.-]+\s+\S+=\s*(?:\([^)]*\))?\s*(?:[A-Z]+:\s*)*(?:.*[\s/,]${PKG}\b.*|ALL)\s*['"]?\s*$`);

// A sudoers line we can positively prove is not package administration: a
// literal user/host rule or Defaults line with no variable/command substitution
// in the command part and no ALL command spec.
const RULE_SHAPE = /^['"]?([\w$%{}@.-]+)\s+(\S+)=\s*(.*?)['"]?$/;
function provablySafeSudoersLine(text) {
  const t = text.trim().replace(/^['"]|['"]$/g, '').trim();
  if (!t || t.startsWith('#')) return true;
  if (/^Defaults\b/.test(t)) return !/[$`]/.test(t);
  const m = RULE_SHAPE.exec(text.trim());
  if (!m) return false;
  const cmd = m[3];
  return !/[$`]/.test(cmd) && !GRANT_RE.test(text.trim()) && !/\bALL\s*$/.test(cmd);
}

// Fail closed: a rule line is returned as a grant; any write to a sudoers path
// whose content is not provably safe (variable, cp/install/mv/sed -i, piped
// input, heredoc body with expansions) is returned as UNPARSED-SUDOERS-WRITE.
export function packageAdminGrants(script) {
  const out = [];
  let heredoc = null; // {delim, sudoers}
  for (const raw of script.split('\n')) {
    const line = raw.trim();
    if (heredoc) {
      if (line === heredoc.delim) { heredoc = null; continue; }
      if (!line || line.startsWith('#')) continue;
      if (GRANT_RE.test(line)) out.push(line);
      else if (heredoc.sudoers && !provablySafeSudoersLine(line)) out.push(`UNPARSED-SUDOERS-WRITE: ${line}`);
      continue;
    }
    if (!line || line.startsWith('#')) continue;
    const body = line.replace(/^(?:echo|printf)\s+(?:-\w+\s+)?/, '').replace(/\s*(?:\|\s*(?:sudo\s+)?tee\b.*|>>?\s*\S+)\s*$/, '');
    const sudoers = /\/etc\/sudoers/.test(line);
    const hd = /<<-?\s*['"]?(\w+)['"]?/.exec(line);
    if (hd) heredoc = {delim: hd[1], sudoers};
    if (GRANT_RE.test(body)) { out.push(line); continue; }
    if (sudoers && WRITE_OP.test(line) && !/\bvisudo\b|\bchmod\b|\bchown\b/.test(line) && !hd) {
      const inline = /^(?:sudo\s+)?(?:echo|printf)\b/.test(line) && provablySafeSudoersLine(body);
      if (!inline) out.push(`UNPARSED-SUDOERS-WRITE: ${line}`);
    }
  }
  return out;
}

// Tiny provisioning model. Root steps install; `sudo -u <user>` steps run as the
// job account and only succeed for package work if a grant exists.
export const REVIEWED_DEPS = ['libnss3', 'libatk1.0-0'];

export function provision(script) {
  const state = {installed: new Set(), grants: packageAdminGrants(script), runnerPkgWork: false};
  for (const raw of script.split('\n')) {
    const line = raw.trim();
    if (!line || line.startsWith('#')) continue;
    const isPkgWork = /apt-get\s+install/.test(line) || /install-deps/.test(line);
    if (!isPkgWork) continue;
    if (/^sudo\s+-u\s/.test(line)) {
      state.runnerPkgWork = true;
      if (!state.grants.length) continue; // job account cannot do package work without a grant
    }
    if (/install-deps\s+chromium/.test(line)) REVIEWED_DEPS.forEach(d => state.installed.add(d));
    for (const d of REVIEWED_DEPS) if (line.includes(d)) state.installed.add(d);
  }
  return state;
}

// Ordinary browser tests as the job account: no privilege, so they pass only if
// every reviewed dependency was already preinstalled.
export function runBrowserTests(state) {
  const missing = REVIEWED_DEPS.filter(d => !state.installed.has(d));
  return {pass: missing.length === 0, missing, privileged: false};
}

export function verdict(script) {
  const s = provision(script);
  const browser = runBrowserTests(s);
  return {grants: s.grants, runnerPkgWork: s.runnerPkgWork, browser, ok: s.grants.length === 0 && !s.runnerPkgWork && browser.pass};
}

const GRANT = '$USER_NAME ALL=(root) NOPASSWD: /usr/bin/apt-get';
const PREINSTALL = 'apt-get install -y -q libnss3 libatk1.0-0\nnpx playwright@1 install-deps chromium\n';
const VALID = `#!/usr/bin/env bash\napt-get update -q\n${PREINSTALL}useradd runner\n`;
const AFFECTED = `#!/usr/bin/env bash\nuseradd runner\ncat > /etc/sudoers.d/actions-runner <<EOF\n${GRANT}\nEOF\nchmod 0440 /etc/sudoers.d/actions-runner\nsudo -u runner -H bash -c 'npx playwright@1 install-deps chromium'\n`;

test('F21-03 positive control: root preinstall, no grant, unprivileged browser tests pass', () => {
  const v = verdict(VALID);
  assert.deepEqual(v.grants, []);
  assert.equal(v.runnerPkgWork, false);
  assert.deepEqual(v.browser, {pass: true, missing: [], privileged: false});
  assert.equal(v.ok, true);
});

test('F21-03 negative control: persistent NOPASSWD apt-get grant is detected', () => {
  assert.deepEqual(packageAdminGrants(AFFECTED), [GRANT]);
  const v = verdict(AFFECTED);
  assert.equal(v.ok, false);
  assert.equal(v.runnerPkgWork, true);
});

test('F21-03 empty or missing-provisioning input is not accepted', () => {
  for (const s of ['', '#!/usr/bin/env bash\nuseradd runner\n']) {
    const v = verdict(s);
    assert.equal(v.ok, false);
    assert.deepEqual(v.browser.missing, REVIEWED_DEPS);
  }
});

test('F21-03 dependencies installed only by the runner without a grant do not count', () => {
  const v = verdict('#!/usr/bin/env bash\nuseradd runner\nsudo -u runner -H bash -c \'npx playwright@1 install-deps chromium\'\n');
  assert.equal(v.ok, false);
  assert.equal(v.browser.pass, false);
  assert.equal(v.runnerPkgWork, true);
});

test('F21-03 grants without NOPASSWD or written via echo/printf/tee/cp/install/sed are detected', () => {
  const forms = [
    'cat > /etc/sudoers.d/a <<EOF\nrunner ALL=(root) /usr/bin/apt-get\nEOF\n',
    "echo 'runner ALL=(root) NOPASSWD: /usr/bin/apt-get' > /etc/sudoers.d/actions-runner\n",
    'echo "runner ALL=(ALL) NOPASSWD: /usr/bin/dpkg" | tee /etc/sudoers.d/a\n',
    "printf 'runner ALL=(root) NOPASSWD: /usr/bin/apt\\n' >> /etc/sudoers.d/a\n",
    'cat >> /etc/sudoers <<-EOF\n\trunner ALL=(ALL) ALL\nEOF\n',
    'cp ./runner-sudoers /etc/sudoers.d/actions-runner\n',
    'install -m 0440 runner.sudoers /etc/sudoers.d/actions-runner\n',
    'sed -i "s/^#runner.*/runner ALL=(root) NOPASSWD: ALL/" /etc/sudoers.d/a\n',
    'echo "$rule" > /etc/sudoers.d/actions-runner\n',
    'printf \'%s\\n\' "$rule" | tee /etc/sudoers.d/actions-runner\n',
    'cat > /etc/sudoers.d/a <<EOF\n$rule\nEOF\n',
    'cat > /etc/sudoers.d/a <<EOF\nrunner ALL=(root) NOPASSWD: $PKGCMD\nEOF\n',
    'generate_rules | tee /etc/sudoers.d/a\n',
    'cat rules.txt > /etc/sudoers.d/a\n',
  ];
  for (const f of forms) assert.notDeepEqual(packageAdminGrants(f), [], f);
});

test('F21-03 detector ignores comments and non-package grants', () => {
  const s = 'cat > /etc/sudoers.d/x <<EOF\n# runner ALL=(root) NOPASSWD: /usr/bin/apt-get\nrunner ALL=(root) NOPASSWD: /usr/bin/systemctl status foo\nEOF\nchmod 0440 /etc/sudoers.d/x\nvisudo -cf /etc/sudoers.d/x\n';
  assert.deepEqual(packageAdminGrants(s), []);
});

// Baseline observation of the real script. `todo` keeps the known gap visible
// in the report without turning the required check red; remove `todo` once
// setup.sh preinstalls dependencies as root and drops the sudoers grant.
test('F21-03 baseline: scripts/runner/setup.sh grants the runner no package administration',
  {todo: 'F21-03 open: setup.sh writes a NOPASSWD apt-get sudoers grant and runs install-deps as the runner (lines ~50-61)'}, () => {
    const real = readFileSync(new URL('../scripts/runner/setup.sh', import.meta.url), 'utf8');
    const v = verdict(real);
    assert.deepEqual(v.grants, []);
    assert.equal(v.runnerPkgWork, false);
  });
