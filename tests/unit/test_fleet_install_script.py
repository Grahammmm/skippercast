"""The AIS listener's deployment keeps the shape CF-42 requires (design.md section 10).

Static checks on scripts/fleet/install_listener.sh, the unit template and
fleet-ais-listener.yml, then the script run end to end against a throwaway git
repository and a fake HOME, with `systemctl` and `journalctl` stubbed on PATH (no
systemd, no network, no pip download: the fake revision's `fleet` extra is empty).
"""
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest

from tests._support import ROOT

SCRIPT = ROOT / 'scripts' / 'fleet' / 'install_listener.sh'
UNIT = ROOT / 'scripts' / 'fleet' / 'skippercast-fleet-ais@.service'
WORKFLOW = ROOT / '.github' / 'workflows' / 'fleet-ais-listener.yml'
RUNBOOK = ROOT / 'docs' / 'operations' / 'runbooks' / 'fleet-ais-down.md'
KEY = 'synthetic0key0for0tests0only0f00d'
BASH = shutil.which('bash')
GIT = shutil.which('git')


def code_lines(text):
    """Script lines without comments (heredoc Python included; it never prints the key either)."""
    return [line for line in text.splitlines() if not line.lstrip().startswith('#')]


class InstallScriptStaticTests(unittest.TestCase):
    def setUp(self):
        self.text = SCRIPT.read_text(encoding='utf-8')

    @unittest.skipUnless(BASH, 'bash not installed')
    def test_bash_syntax(self):
        subprocess.run([BASH, '-n', str(SCRIPT)], check=True)

    def test_never_traces(self):
        code = '\n'.join(code_lines(self.text))
        self.assertNotRegex(code, r'set\s+-[a-wyz]*x|set\s+-o\s+xtrace|bash\s+-x')
        self.assertTrue(self.text.startswith('#!/usr/bin/env bash\n'))
        self.assertEqual(code_lines(self.text)[0], 'set +x', 'turn tracing off before anything reads the key')

    def test_secret_is_never_echoed(self):
        expansion = re.compile(r'\$\{?AISSTREAM_API_KEY')
        for line in code_lines(self.text):
            for segment in re.split(r'\|\||&&|;|\bthen\b|\belse\b', line):
                if re.match(r'\s*(echo|printf|note|die|print|cat)\b', segment):
                    self.assertNotRegex(segment, expansion, line)
        # The shell's only use of the value is a non-empty test; Python reads it from the environment.
        uses = [line.strip() for line in code_lines(self.text) if expansion.search(line)]
        self.assertEqual(uses, ['[ -n "${AISSTREAM_API_KEY:-}" ] || die "AISSTREAM_API_KEY is not set (owner step: add the repository secret)"'])
        self.assertIn('os.environ.get("AISSTREAM_API_KEY"', self.text)
        self.assertIn('0o600', self.text)

    def test_unit_template(self):
        unit = UNIT.read_text(encoding='utf-8')
        for line in ('EnvironmentFile=%h/.config/skippercast/fleet-ais.env',
                     'WorkingDirectory=%h/.local/share/skippercast/app/current',
                     'ExecStart=%h/.local/share/skippercast/app/current/.venv/bin/python -m skippercast.fleet.ais listen --region %i',
                     'Environment=PYTHONPATH=%h/.local/share/skippercast/app/current/src',
                     'Restart=always', 'RestartSec=10', 'MemoryMax=512M', 'WantedBy=default.target'):
            self.assertIn(f'\n{line}\n', unit)
        self.assertNotIn('AISSTREAM_API_KEY=', unit, 'the key lives only in the 0600 env file')


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text(encoding='utf-8')
        self.header = '\n'.join(line for line in self.text.split('\njobs:', 1)[0].splitlines()
                                if not line.lstrip().startswith('#'))

    def test_dispatch_only(self):
        self.assertRegex(self.header, r'\non:\n  workflow_dispatch:\n')
        for trigger in ('schedule:', 'push:', 'pull_request', 'workflow_run'):
            self.assertNotIn(trigger, self.header)

    def test_least_privilege_on_our_runner(self):
        self.assertIn('permissions: {}', self.header)
        grants = re.findall(r'^\s+([a-z-]+): (read|write)\b', self.text.split('\njobs:', 1)[1], re.M)
        self.assertEqual(grants, [('contents', 'read')])
        self.assertIn("if: vars.ENABLE_FLEET == 'true' && vars.DATA_RUNNER != '' && github.ref == 'refs/heads/main'",
                      self.text, 'only main: the key never reaches unreviewed code')
        self.assertEqual(re.findall(r'^\s*runs-on:\s*(.+?)\s*$', self.text, re.M),
                         ["${{ vars.DATA_RUNNER || 'ubuntu-latest' }}"])
        self.assertIn('persist-credentials: false', self.text)
        self.assertIn('cancel-in-progress: false', self.header)
        self.assertIn('  group: fleet-ais-listener\n', self.header)

    def test_secret_only_in_the_step_environment(self):
        self.assertEqual(self.text.count('secrets.'), 1)
        self.assertIn('          AISSTREAM_API_KEY: ${{ secrets.AISSTREAM_API_KEY }}\n', self.text)
        run = re.findall(r'^\s+run: (.+)$', self.text, re.M)
        self.assertEqual(run, ['bash scripts/fleet/install_listener.sh --region "$REGION"'])
        self.assertNotIn('${{ inputs.region }}', run[0], 'inputs reach the shell through env, not interpolation')


class SelfHostedTriggerTests(unittest.TestCase):
    """docs/operations/runners.md: no pull request reaches a workflow that can run on our runners."""

    def test_no_pull_request_trigger_on_runner_workflows(self):
        checked, wrong = [], []
        for path in sorted((ROOT / '.github' / 'workflows').glob('*.y*ml')):
            text = path.read_text(encoding='utf-8')
            if not re.search(r'vars\.(DATA_RUNNER|SEAFLOOR_RUNNER)', text):
                continue
            checked.append(path.name)
            header = '\n'.join(line for line in text.split('\njobs:', 1)[0].splitlines()
                                if not line.lstrip().startswith('#'))
            on = re.search(r'\non:\n((?:[ \t].*\n?)*)', header + '\n')
            triggers = re.findall(r'^  ([a-z_]+):', on.group(1), re.M) if on else ['<unparsed>']
            for trigger in triggers:
                if trigger not in ('schedule', 'workflow_dispatch', 'workflow_run', 'push'):
                    wrong.append(f'{path.name}: {trigger}')
            if 'push' in triggers and not re.search(r'^  push:\n    branches: \[main\]\n', on.group(1), re.M):
                wrong.append(f'{path.name}: push not limited to main')
        self.assertIn('fleet-ais-listener.yml', checked)
        self.assertEqual(wrong, [])


class RunbookTests(unittest.TestCase):
    def test_covers_restart_logs_rollback_and_owner_steps(self):
        text = RUNBOOK.read_text(encoding='utf-8')
        for needle in ('systemctl --user restart skippercast-fleet-ais@CA', 'journalctl --user -u skippercast-fleet-ais@CA',
                       '--rollback', 'loginctl enable-linger', 'AISSTREAM_API_KEY', 'stream.aisstream.io',
                       'heartbeat.json'):
            self.assertIn(needle, text)
        self.assertNotRegex(text, r'gh workflow run[^\n`]*--ref', 'the workflow runs only from main')


STUB_SYSTEMCTL = r'''#!/usr/bin/env bash
echo "systemctl $*" >> "$STUB_LOG"
[ "${STUB_NO_MANAGER:-}" = 1 ] && [ "$*" = "--user show-environment" ] && exit 1
if [ "$1 $2" = "--user restart" ]; then
  region=${3#skippercast-fleet-ais@}; region=${region%.service}
  sha=$(sed -n 's/^SKIPPERCAST_GIT_SHA=//p' "$HOME/.config/skippercast/fleet-ais.env")
  var=$(sed -n 's/^SKIPPERCAST_FLEET_VAR=//p' "$HOME/.config/skippercast/fleet-ais.env")
  mkdir -p "$var/$region/ais"
  # The script compares the heartbeat with its own wall clock, as the real listener's would be.
  now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  python3 - "$var/$region/ais/heartbeat.json" "$sha" "${STUB_MESSAGES:-1}" "$now" <<'PY'
import json, sys
path, sha, messages, now = sys.argv[1], sys.argv[2], sys.argv[3] == "1", sys.argv[4]
json.dump({"schema_version": 1, "git_sha": sha, "started_at": now, "written_at": now, "connected": messages,
           "last_message_at": now if messages else None, "messages_per_min": 12.0 if messages else 0.0,
           "last_error": None}, open(path, "w"))
PY
fi
exit 0
'''

STUB_JOURNALCTL = '#!/usr/bin/env bash\necho "journalctl $*" >> "$STUB_LOG"\necho "stub journal line"\n'

FAKE_CONFIG = '''"""Stand-in for skippercast.fleet.config in the throwaway revision."""
from skippercast.paths import repo_root


def load_region(ident):
    import os
    if "AISSTREAM_API_KEY" in os.environ:
        raise SystemExit("the build step saw the aisstream key")
    if not (repo_root() / "regions" / ident / "fleet.json").is_file():
        raise SystemExit(f"no fleet.json for {ident}")
'''

FAKE_PATHS = '''import os
import pathlib


def repo_root():
    return pathlib.Path(os.path.realpath(__file__)).parents[2]
'''


@unittest.skipUnless(BASH and GIT and os.name == 'posix', 'needs bash, git and a POSIX system')
class InstallScriptRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='fleet-install-'))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = self.tmp / 'home'
        self.home.mkdir()
        self.repo = self.tmp / 'repo'
        self.bin = self.tmp / 'bin'
        self.bin.mkdir()
        self.log = self.tmp / 'stub.log'
        for name, body in (('systemctl', STUB_SYSTEMCTL), ('journalctl', STUB_JOURNALCTL)):
            path = self.bin / name
            path.write_text(body, encoding='utf-8')
            path.chmod(0o755)
        files = {
            'pyproject.toml': '[project]\nname = "skippercast"\ndependencies = []\n\n'
                              '[project.optional-dependencies]\nfleet = []\n',
            'src/skippercast/__init__.py': '',
            'src/skippercast/paths.py': FAKE_PATHS,
            'src/skippercast/fleet/__init__.py': '',
            'src/skippercast/fleet/config.py': FAKE_CONFIG,
            'regions/CA/fleet.json': '{}\n',
            'research/not-deployed.txt': 'left out of the revision copy\n',
        }
        for rel, body in files.items():
            (self.repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / rel).write_text(body, encoding='utf-8')
        (self.repo / 'scripts/fleet').mkdir(parents=True)
        shutil.copy2(SCRIPT, self.repo / 'scripts/fleet/install_listener.sh')
        shutil.copy2(UNIT, self.repo / 'scripts/fleet' / UNIT.name)
        self.git('init', '-q')
        self.shas = [self.commit('first')]

    def git(self, *args):
        return subprocess.run([GIT, '-C', str(self.repo), '-c', 'user.name=t', '-c', 'user.email=t@example.invalid',
                               '-c', 'commit.gpgsign=false', *args],
                              check=True, capture_output=True, text=True).stdout.strip()

    def commit(self, message):
        (self.repo / 'src/skippercast/revision.txt').write_text(message, encoding='utf-8')
        self.git('add', '-A')
        self.git('commit', '-q', '-m', message)
        return self.git('rev-parse', 'HEAD')

    def run_script(self, *args, key=KEY, trace=False, **env):
        environ = {'PATH': f'{self.bin}{os.pathsep}{os.environ.get("PATH", "")}', 'HOME': str(self.home),
                   'STUB_LOG': str(self.log), 'XDG_RUNTIME_DIR': str(self.tmp), 'PYTHON': sys.executable,
                   'HEARTBEAT_TIMEOUT': '2', 'HEARTBEAT_POLL': '0.2', 'LANG': 'C.UTF-8', **env}
        if key is not None:
            environ['AISSTREAM_API_KEY'] = key
        command = [BASH, *(['-x'] if trace else []), str(self.repo / 'scripts/fleet/install_listener.sh'), *args]
        result = subprocess.run(command, env=environ, capture_output=True, text=True, timeout=120)
        self.assertNotIn(KEY, result.stdout + result.stderr, 'the aisstream key reached the output')
        return result

    @property
    def app(self):
        return self.home / '.local/share/skippercast/app'

    @property
    def env_file(self):
        return self.home / '.config/skippercast/fleet-ais.env'

    def env_values(self):
        return dict(line.split('=', 1) for line in self.env_file.read_text(encoding='utf-8').splitlines())

    def test_install_writes_a_private_env_file_and_starts_the_unit(self):
        result = self.run_script('--region', 'CA', trace=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        sha = self.shas[0]
        self.assertEqual(stat.S_IMODE(self.env_file.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.env_file.parent.stat().st_mode), 0o700)
        self.assertEqual(self.env_values(), {
            'AISSTREAM_API_KEY': KEY, 'SKIPPERCAST_GIT_SHA': sha,
            'SKIPPERCAST_FLEET_VAR': str(self.home / '.local/share/skippercast/fleet')})
        self.assertEqual(os.readlink(self.app / 'current'), sha)
        revision = self.app / sha
        self.assertTrue((revision / '.complete').is_file())
        self.assertTrue((revision / '.venv/bin/python').exists())
        self.assertFalse((revision / 'research').exists(), 'only the listener paths are copied')
        self.assertEqual((self.home / '.config/systemd/user' / UNIT.name).read_text(encoding='utf-8'),
                         UNIT.read_text(encoding='utf-8'))
        calls = self.log.read_text(encoding='utf-8').splitlines()
        self.assertEqual(calls, ['systemctl --user show-environment', 'systemctl --user daemon-reload',
                                 'systemctl --user enable skippercast-fleet-ais@CA.service',
                                 'systemctl --user restart skippercast-fleet-ais@CA.service'])
        self.assertIn('skippercast-fleet-ais@CA.service is running', result.stdout)

    def test_fails_when_the_heartbeat_shows_no_messages(self):
        result = self.run_script('--region', 'CA', STUB_MESSAGES='0')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('shows no aisstream messages', result.stderr)
        self.assertIn('journalctl --user -u skippercast-fleet-ais@CA.service', self.log.read_text(encoding='utf-8'))
        self.assertIn('--rollback', result.stderr)

    def test_refuses_without_a_key_or_a_user_manager(self):
        result = self.run_script('--region', 'CA', key=None)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('AISSTREAM_API_KEY is not set', result.stderr)
        self.assertFalse(self.env_file.exists())
        result = self.run_script('--region', 'CA', STUB_NO_MANAGER='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('loginctl enable-linger', result.stderr)
        self.assertFalse(self.app.exists())

    def test_rejects_a_malformed_key_without_showing_it(self):
        result = self.run_script('--region', 'CA', key=f'{KEY} "x"')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('value not shown', result.stderr)
        self.assertNotIn('"x"', result.stdout + result.stderr)

    def test_rollback_to_the_previous_revision_keeps_the_key(self):
        self.assertEqual(self.run_script('--region', 'CA').returncode, 0)
        self.shas.append(self.commit('second'))
        self.assertEqual(self.run_script('--region', 'CA').returncode, 0)
        self.assertEqual(os.readlink(self.app / 'current'), self.shas[1])
        self.assertEqual(os.readlink(self.app / 'previous'), self.shas[0])

        result = self.run_script('--region', 'CA', '--rollback', key=None)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(os.readlink(self.app / 'current'), self.shas[0])
        self.assertEqual(os.readlink(self.app / 'previous'), self.shas[1])
        self.assertEqual(self.env_values()['SKIPPERCAST_GIT_SHA'], self.shas[0])
        self.assertEqual(self.env_values()['AISSTREAM_API_KEY'], KEY)
        self.assertEqual(stat.S_IMODE(self.env_file.stat().st_mode), 0o600)

        store = self.env_values()['SKIPPERCAST_FLEET_VAR']
        result = self.run_script('--region', 'CA', '--rollback', self.shas[1], key=None,
                                 SKIPPERCAST_FLEET_VAR=str(self.tmp / 'some-other-store'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(os.readlink(self.app / 'current'), self.shas[1])
        self.assertEqual(self.env_values()['SKIPPERCAST_FLEET_VAR'], store, 'a rollback keeps the running store')
        self.assertFalse((self.tmp / 'some-other-store').exists())
        missing = 'f' * 40
        result = self.run_script('--region', 'CA', '--rollback', missing, key=None)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('is not kept', result.stderr)

    def test_keeps_only_recent_revisions(self):
        for age, name in enumerate(('second', 'third', 'fourth')):
            self.assertEqual(self.run_script('--region', 'CA', KEEP_REVISIONS='3').returncode, 0)
            stamp = 1_000_000 + age   # builds in one second would tie; order them explicitly
            os.utime(self.app / self.git('rev-parse', 'HEAD'), (stamp, stamp))
            self.shas.append(self.commit(name))
        self.assertEqual(self.run_script('--region', 'CA', KEEP_REVISIONS='3').returncode, 0)
        kept = sorted(p.name for p in self.app.iterdir() if re.fullmatch(r'[0-9a-f]{40}', p.name))
        self.assertEqual(kept, sorted(self.shas[1:]))


if __name__ == '__main__':
    unittest.main()
