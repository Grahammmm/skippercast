"""Acceptance runner for SC34-TERRAIN-JSON (strict JSON in the terrain CLI metadata reader).

    python3 research/scripts/accept_sc34_terrain_json.py --suite {focused,contract,negative} --output DIR

Suites (literal pytest selectors, exact expected node sets or counts):
  focused   tests/unit/test_sc34_terrain_json.py (every case, A1 + A2 + A3)
  contract  research/tests/test_check_terrain_acceptance_dependencies.py::
                test_terrain_only_verify_raises_value_error_not_module_not_found
                test_terrain_only_cli_reports_the_dependency_as_a_hold
            tests/contract/test_research_boundary.py
            tests/contract/test_test_layout.py (layout rules the new test module must follow)
  negative  tests/unit/test_sc34_terrain_json.py::test_mutation_controls (A3)

Order of operations. Bytecode writing is turned off first. Read-only git
metadata is taken with argv lists (no shell). The import path is then set in
code to this staged repository (root and src/) plus the staged .venv
site-packages, and only when that venv's version matches this interpreter. .pth
files are not processed, so no editable install of another checkout is
activated. Network, model-client and process-spawn sentinels are installed and
self-tested before pytest or any project module is imported. tempfile and
pytest --basetemp point inside the new run directory.

Each run creates DIR/<utc>-<pid>-<token>/ exclusively (write-once) and writes
receipt.json, pytest-stdout.txt, pytest-stderr.txt and junit.xml there. Exit 0
only when pytest exits 0, the exact expected node set/count was collected and
passed, nothing was skipped/xfailed/errored, the module under test resolved
inside this repository, no sentinel fired, pinned inputs match and watched
inputs are unchanged. Otherwise exit 1 (2 for an unsafe --output). A pass is
REVIEW REQUIRED: not full CI, not the operator-owned full-suite run, and not
any source, scientific or live acceptance.
"""
import sys

sys.dont_write_bytecode = True  # before any other import

import argparse  # noqa: E402
import contextlib  # noqa: E402
import datetime  # noqa: E402
import hashlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
from pathlib import Path  # noqa: E402
import platform  # noqa: E402
import re  # noqa: E402
import secrets  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402

CARD = 'SC34-TERRAIN-JSON'
FROZEN_BASE = '59fca09b2cc7f5c81a4796902504e263d7f06960'  # source pins measured here
STAGED_BASE = '709b81ba7e09992f56d83fd4e7bae751ed824ec5'  # operator-staged head (SOURCE-MANIFEST.json)
REPO = Path(__file__).resolve().parents[2]
SRC = REPO / 'src'
VENV = REPO / '.venv'
VENV_SITE = VENV / 'lib' / f'python{sys.version_info[0]}.{sys.version_info[1]}' / 'site-packages'
NEW_TESTS = 'tests/unit/test_sc34_terrain_json.py'
COMPAT = 'research/tests/test_check_terrain_acceptance_dependencies.py'
COMPAT_IDS = [COMPAT + '::test_terrain_only_verify_raises_value_error_not_module_not_found',
              COMPAT + '::test_terrain_only_cli_reports_the_dependency_as_a_hold']
MUTATION_IDS = [NEW_TESTS + f'::test_mutation_controls[{case}]' for case in (
    'duplicate-top-level', 'duplicate-nested-array', 'duplicate-escaped', 'overflow-positive',
    'overflow-negative-nested', 'healthy-control')]
SUITES = {
    'focused': dict(args=[NEW_TESTS], expected=117, expected_ids=None, required_ids=MUTATION_IDS),
    'contract': dict(args=[*COMPAT_IDS, 'tests/contract/test_research_boundary.py',
                           'tests/contract/test_test_layout.py'],
                     expected=None, expected_ids=None, required_ids=COMPAT_IDS),
    'negative': dict(args=[NEW_TESTS + '::test_mutation_controls'], expected=6, expected_ids=MUTATION_IDS,
                     required_ids=MUTATION_IDS),
}
# Frozen contract-suite node set (two compatibility selectors + both contract modules).
SUITES['contract']['expected_ids'] = [*COMPAT_IDS, *(
    'tests/contract/test_research_boundary.py::ResearchBoundaryTest::' + name for name in (
        'test_app_and_worker_do_not_load_receipts', 'test_new_research_scripts_do_not_land_in_scripts',
        'test_product_python_never_imports_research', 'test_product_scripts_never_run_research',
        'test_product_workflows_run_no_research', 'test_research_scripts_compile',
        'test_research_workflows_publish_nothing', 'test_web_and_worker_never_import_research')),
    *('tests/contract/test_test_layout.py::LayoutTest::' + name for name in (
        'test_every_layer_is_a_package', 'test_every_module_is_in_a_layer',
        'test_gis_imports_only_in_gis_directories', 'test_gis_package_list_matches_the_survey_requirements',
        'test_no_path_hacks_or_file_relative_roots', 'test_node_test_modules_match_the_standard_suite_glob',
        'test_product_tests_never_read_the_real_clock',
        'test_shared_survey_packages_are_pinned_the_same_in_the_test_extra'))]
# Baseline identities of inputs this card must not change.
PINNED = {
    COMPAT: '2bf6b16c79fb2ef0bc47ec55960eb6668a045a7f05edd7a4f31cab8ac0c07ecd',
    'tests/contract/test_research_boundary.py': None,  # filled from git at FROZEN_BASE below
    'tests/contract/test_test_layout.py': None,
    'tests/_support.py': None,
    'tests/conftest.py': None,
    'research/tests/conftest.py': None,
    'pyproject.toml': None,
}
BASE_TERRAIN_ONLY_SHA256 = '1600b4b7a37dd04f281e43ea4f233a4e3dfbfc4237d486883744530e14d977d9'
OWNED = {'src/skippercast/coastal/render/terrain_only.py', NEW_TESTS, 'research/scripts/accept_sc34_terrain_json.py',
         'docs/engineering/sc34_terrain_json.md', 'tests/fixtures/sc34_terrain_json/style-producer.json',
         'tests/fixtures/sc34_terrain_json/acceptance-reference.json', 'tests/fixtures/sc34_terrain_json/README.md'}
WATCHED = sorted({*OWNED, *PINNED})
REQUIRED_PACKAGES = ('pytest', 'jsonschema')
MODEL_IMPORTS = ('openai', 'anthropic', 'ollama', 'google.generativeai', 'litellm')
HOME_CAPTURE = re.compile(r'(?m)^[A-Za-z_][A-Za-z0-9_]*\s*=.*(Path\.home\(\)|expanduser\(|os\.environ)')


def now():
    return datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat()


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256(path):
    path = Path(path)
    if not path.is_file():
        return None
    return sha256_bytes(path.read_bytes())


def git(*args):
    """Read-only git metadata, taken BEFORE sentinels are installed (argv list, no shell)."""
    try:
        done = subprocess.run(['git', '-C', str(REPO), *args], capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as error:
        return dict(argv=['git', *args], error=type(error).__name__, stdout_bytes=b'')
    return dict(argv=['git', *args], exit=done.returncode, stdout=done.stdout.decode('utf-8', 'replace'),
                stderr=done.stderr.decode('utf-8', 'replace'), stdout_bytes=done.stdout)


def public(result):
    return {key: value for key, value in result.items() if key != 'stdout_bytes'}


class RunRootRefused(Exception):
    pass


def open_output_root(output):
    """Open --output from / one component at a time with O_NOFOLLOW, creating missing parts."""
    text = os.fspath(output)
    absolute = text if os.path.isabs(text) else os.path.join(os.getcwd(), text)
    if '\0' in text or absolute != os.path.normpath(absolute) or absolute.startswith('//'):
        raise RunRootRefused(f'--output must be a normalized path: {text!r}')
    parts = absolute.split('/')[1:]
    if not parts or not all(parts):
        raise RunRootRefused(f'--output must name a directory below /: {text!r}')
    if Path(absolute).resolve().is_relative_to(REPO.resolve()) or Path(absolute).is_relative_to(REPO):
        raise RunRootRefused('--output must be outside the repository')
    no_follow = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts:
            try:
                new = os.open(part, no_follow, dir_fd=fd)
            except FileNotFoundError:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                new = os.open(part, no_follow, dir_fd=fd)
            except OSError as error:
                raise RunRootRefused(f'refused --output at {part!r}: symlink or non-directory ({error.strerror})') \
                    from None
            os.close(fd)
            fd = new
        return fd, absolute
    except BaseException:
        os.close(fd)
        raise


def new_run_dir(output):
    root_fd, absolute = open_output_root(output)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    name = f'{stamp}-{os.getpid()}-{secrets.token_hex(4)}'
    try:
        os.mkdir(name, 0o700, dir_fd=root_fd)  # exclusive: an existing name is refused
        run_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
    except OSError as error:
        raise RunRootRefused(f'cannot create run directory {name}: {error.strerror}') from None
    finally:
        os.close(root_fd)
    run_dir = Path(absolute) / name
    if os.path.realpath(run_dir) != str(run_dir):
        os.close(run_fd)
        raise RunRootRefused(f'run directory path is not canonical: {run_dir}')
    return run_dir, run_fd


def write_once(run_fd, name, data):
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=run_fd)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(data)


def resolve_dependencies():
    """Import path from this staged repository only; never install or activate anything."""
    info = dict(repo_on_path=[str(REPO), str(SRC)], venv_site=None, pth_files_processed=False)
    cfg = VENV / 'pyvenv.cfg'
    if VENV_SITE.is_dir() and cfg.is_file():
        version = None
        for line in cfg.read_text().splitlines():
            key, _, value = line.partition('=')
            if key.strip() == 'version':
                version = value.strip()
        current = '.'.join(map(str, sys.version_info[:3]))
        info.update(venv_version=version, venv_is_symlink=VENV.is_symlink(), venv_resolved=str(VENV.resolve()))
        if version == current:
            sys.path.insert(0, str(VENV_SITE))
            info['venv_site'] = str(VENV_SITE)
        else:
            info['venv_refused'] = f'staged venv {version} does not match interpreter {current}'
    script_dir = str(Path(__file__).resolve().parent)
    sys.path[:] = [p for p in sys.path if p not in ('', script_dir)]
    for entry in (str(SRC), str(REPO)):
        while entry in sys.path:
            sys.path.remove(entry)
        sys.path.insert(0, entry)
    import importlib.metadata
    import importlib.util
    found, missing = {}, []
    for name in REQUIRED_PACKAGES:
        spec = importlib.util.find_spec(name)
        if spec is None:
            missing.append(name)
            continue
        try:
            version = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            version = None
        found[name] = dict(version=version, origin=spec.origin)
    info.update(packages=found, missing=missing, sys_path=list(sys.path))
    return info


FIRED = []


def _refuse(*args, **kwargs):
    FIRED.append(repr(args)[:200])
    raise RuntimeError(f'{CARD} acceptance sentinel: network/process call refused')


def install_sentinels():
    """Regression controls, not a hostile-code sandbox."""
    import http.client
    import socket
    import urllib.request
    installed = []
    for owner, name in ((socket.socket, 'connect'), (socket.socket, 'connect_ex'), (socket, 'create_connection'),
                        (socket, 'getaddrinfo'), (socket, 'gethostbyname'), (urllib.request, 'urlopen'),
                        (http.client.HTTPConnection, 'connect'), (subprocess, 'Popen'), (subprocess, 'run'),
                        (os, 'system'), (os, 'posix_spawn'), (os, 'posix_spawnp'), (os, 'execv'),
                        (os, 'execve'), (os, 'fork')):
        if hasattr(owner, name):
            setattr(owner, name, _refuse)
            installed.append(f'{getattr(owner, "__name__", owner)}.{name}')

    def audit(event, args):
        if event == 'import' and args and args[0] in MODEL_IMPORTS:
            FIRED.append('model-import ' + str(args[0]))
            raise RuntimeError(f'{CARD} acceptance sentinel: model client import refused')
    sys.addaudithook(audit)
    installed.append('audit:model-client-imports')
    return installed


def sentinel_self_test():
    """Prove the sentinels refuse before any I/O; these stubs never reach the network or a process."""
    import socket
    results = {}
    for label, call in (('getaddrinfo', lambda: socket.getaddrinfo('sentinel.invalid', 9)),
                        ('subprocess.run', lambda: subprocess.run(['true'])),
                        ('os.system', lambda: os.system('true'))):
        try:
            call()
            results[label] = 'NOT REFUSED'
        except RuntimeError as error:
            results[label] = 'refused' if 'sentinel' in str(error) else 'other:' + str(error)
    FIRED.clear()  # self-test refusals are expected; later ones are violations
    return results


class Outcomes:
    """pytest plugin recording every collected node and its outcome."""

    def __init__(self):
        self.collected, self.reports, self.collect_errors = [], {}, []

    def pytest_collection_modifyitems(self, items):
        self.collected = [item.nodeid for item in items]

    def pytest_collectreport(self, report):
        if report.failed:
            self.collect_errors.append(dict(nodeid=report.nodeid, longrepr=str(report.longrepr)))

    def pytest_runtest_logreport(self, report):
        entry = self.reports.setdefault(report.nodeid, dict(outcome='passed', phases={}))
        state = ('xfailed' if report.skipped else 'xpassed') if hasattr(report, 'wasxfail') else report.outcome
        entry['phases'][report.when] = state
        if state == 'passed':
            return
        if report.when == 'call':
            if entry['outcome'] == 'passed':
                entry['outcome'] = state
        elif state == 'failed':
            entry['outcome'] = 'error'
        elif entry['outcome'] == 'passed':
            entry['outcome'] = state


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--suite', required=True, choices=sorted(SUITES))
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    started = time.monotonic()
    try:
        run_dir, run_fd = new_run_dir(args.output)
    except (RunRootRefused, OSError) as error:
        print(f'REFUSED: {error}', file=sys.stderr)
        return 2
    suite = SUITES[args.suite]
    failures = []
    receipt = dict(
        card=CARD, suite=args.suite, label='REVIEW REQUIRED',
        scope='scoped card acceptance only; not full CI (full discovery = operator-run), '
              'not source, scientific or live acceptance',
        runner=str(Path(__file__).resolve()), argv=list(getattr(sys, 'orig_argv', [sys.executable, *sys.argv])),
        cwd=os.getcwd(), python=sys.executable, python_version=sys.version, platform=platform.platform(),
        repo=str(REPO), run_dir=str(run_dir), started_at=now(), frozen_base=FROZEN_BASE, staged_base=STAGED_BASE,
        dont_write_bytecode=sys.dont_write_bytecode, pytest_selectors_literal=suite['args'],
        expected_count=suite['expected'], expected_ids=suite['expected_ids'])
    head = git('rev-parse', 'HEAD')
    status = git('status', '--porcelain=v1', '--untracked-files=all')
    changed = git('diff', '--name-only', STAGED_BASE)
    receipt['git'] = dict(head=public(head), status=public(status), changed_since_staged_base=public(changed),
                          frozen_base_is_ancestor=public(git('merge-base', '--is-ancestor', FROZEN_BASE, 'HEAD')),
                          staged_base_is_ancestor=public(git('merge-base', '--is-ancestor', STAGED_BASE, 'HEAD')),
                          base_terrain_only_sha256=sha256_bytes(git('show', f'{FROZEN_BASE}:src/skippercast/coastal/'
                                                                         'render/terrain_only.py')['stdout_bytes']))
    if receipt['git']['base_terrain_only_sha256'] != BASE_TERRAIN_ONLY_SHA256:
        failures.append('frozen-base terrain_only.py hash does not match the source pin')
    for name in list(PINNED):
        if PINNED[name] is None:
            PINNED[name] = sha256_bytes(git('show', f'{FROZEN_BASE}:{name}')['stdout_bytes'])
    touched = set(changed.get('stdout', '').split())
    for line in status.get('stdout', '').splitlines():
        if line.startswith('?? '):
            touched.add(line[3:].strip())
    out_of_scope = sorted(p for p in touched if p not in OWNED and p != '.venv')
    receipt['scope'] = dict(touched_since_staged_base=sorted(touched), out_of_scope=out_of_scope)
    if out_of_scope:
        failures.append(f'files outside the owned scope changed: {out_of_scope}')
    receipt['hashes_before'] = before = {name: sha256(REPO / name) for name in WATCHED}
    receipt['pinned'] = {name: dict(expected=value, actual=before[name]) for name, value in PINNED.items()}
    failures += [f'pinned input changed: {n}' for n, row in receipt['pinned'].items() if row['expected'] != row['actual']]
    receipt['fixture_hashes'] = {p.name: sha256(p) for p in sorted((REPO / 'tests/fixtures/sc34_terrain_json').glob('*'))}

    preloaded = sorted(m for m in sys.modules if m.split('.')[0] in ('skippercast', 'tests', 'research', 'pytest'))
    receipt['project_modules_before_sentinels'] = preloaded
    if preloaded:
        failures.append(f'project modules imported before sentinels: {preloaded}')
    receipt['dependencies'] = deps = resolve_dependencies()
    if deps['missing']:
        failures.append('INPUT_UNAVAILABLE: missing ' + ', '.join(deps['missing']))
    receipt['sentinels'] = install_sentinels()
    receipt['sentinel_self_test'] = self_test = sentinel_self_test()
    if any(value != 'refused' for value in self_test.values()):
        failures.append(f'sentinel self-test failed: {self_test}')
    tmp_root = run_dir / 'tmp'
    tmp_root.mkdir()
    tempfile.tempdir = str(tmp_root)
    os.environ['TMPDIR'] = str(tmp_root)
    receipt['path_substitutions'] = dict(tempfile_tempdir=str(tmp_root), TMPDIR=str(tmp_root),
                                         pytest_basetemp=str(run_dir / 'pytest-tmp'),
                                         note='path plumbing only; no logic, threshold, schema or assertion change')

    stdout_buffer, stderr_buffer = io.StringIO(), io.StringIO()
    outcomes = Outcomes()
    exit_code = None
    modules_before = set(sys.modules)
    if not failures:
        import pytest
        pytest_argv = [*(str(REPO / arg) for arg in suite['args']), '-p', 'no:cacheprovider',
                       '-p', 'no:hypothesispytest', '-rA', '-v',
                       '--basetemp', str(run_dir / 'pytest-tmp'), '--junitxml', str(run_dir / 'junit.xml'),
                       '--rootdir', str(REPO), '-c', str(REPO / 'pyproject.toml')]
        receipt['pytest_argv'] = pytest_argv
        # Raw pytest output goes to the run directory only; the console gets the verdict summary.
        with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
            exit_code = int(pytest.main(pytest_argv, plugins=[outcomes]))
        from skippercast.coastal.render import terrain_only
        receipt['module_under_test'] = module_file = str(Path(terrain_only.__file__).resolve())
        if not Path(module_file).is_relative_to(SRC.resolve()):
            failures.append(f'module under test resolved outside this repository: {module_file}')
    imported = {}
    captures = []
    for name in sorted(set(sys.modules) - modules_before):
        path = getattr(sys.modules.get(name), '__file__', None)
        imported[name] = path
        if name.split('.')[0] == 'skippercast' and path and not Path(path).resolve().is_relative_to(SRC.resolve()):
            failures.append(f'foreign skippercast import: {name} {path}')
        if path and name.split('.')[0] in ('skippercast', 'research', 'tests') and path.endswith('.py'):
            if name != 'research.scripts.accept_sc34_terrain_json' and HOME_CAPTURE.search(Path(path).read_text()):
                captures.append(name)
    receipt['imported_modules'] = imported
    receipt['module_level_home_or_env_captures'] = captures
    if captures:
        failures.append(f'imported project modules capture home/environment paths at import: {captures}')
    receipt['sentinel_violations'] = list(FIRED)
    if FIRED:
        failures.append(f'{len(FIRED)} sentinel refusals during the run')
    receipt['pytest_exit'] = exit_code
    receipt['collected'] = outcomes.collected
    receipt['collect_errors'] = outcomes.collect_errors
    receipt['results'] = outcomes.reports
    counts = {}
    for entry in outcomes.reports.values():
        counts[entry['outcome']] = counts.get(entry['outcome'], 0) + 1
    receipt['counts'] = dict(collected=len(outcomes.collected), **counts)
    if exit_code is not None:
        expected = suite['expected'] if suite['expected'] is not None else len(suite['expected_ids'])
        if exit_code != 0:
            failures.append(f'pytest exit {exit_code}')
        if len(outcomes.collected) != expected:
            failures.append(f'collected {len(outcomes.collected)} tests, expected exactly {expected}')
        if suite['expected_ids'] is not None and sorted(outcomes.collected) != sorted(suite['expected_ids']):
            failures.append('collected node set differs from the frozen expected IDs')
        missing_required = sorted(set(suite['required_ids']) - set(outcomes.collected))
        if missing_required:
            failures.append(f'required node IDs not collected: {missing_required}')
        if outcomes.collect_errors:
            failures.append(f'{len(outcomes.collect_errors)} collection errors')
        not_passed = sorted(node for node, entry in outcomes.reports.items() if entry['outcome'] != 'passed')
        if not_passed:
            failures.append(f'{len(not_passed)} tests not passed (failed/error/skipped/xfailed): {not_passed}')
        if sorted(set(outcomes.collected) - set(outcomes.reports)):
            failures.append('collected tests without a report')
        if counts.get('passed', 0) != expected:
            failures.append(f'passed {counts.get("passed", 0)}, expected exactly {expected}')
    receipt['hashes_after'] = after = {name: sha256(REPO / name) for name in WATCHED}
    drift = sorted(name for name in WATCHED if before[name] != after[name])
    if drift:
        failures.append(f'watched inputs changed during the run: {drift}')
    stdout_bytes, stderr_bytes = stdout_buffer.getvalue().encode(), stderr_buffer.getvalue().encode()
    write_once(run_fd, 'pytest-stdout.txt', stdout_bytes)
    write_once(run_fd, 'pytest-stderr.txt', stderr_bytes)
    receipt['raw_output_sha256'] = {'pytest-stdout.txt': sha256_bytes(stdout_bytes),
                                    'pytest-stderr.txt': sha256_bytes(stderr_bytes),
                                    'junit.xml': sha256(run_dir / 'junit.xml')}
    receipt['failures'] = failures
    receipt['verdict'] = 'PASS_REVIEW_REQUIRED' if not failures else 'FAIL'
    receipt['exit_code'] = 0 if not failures else 1
    receipt['finished_at'] = now()
    receipt['runtime_seconds'] = round(time.monotonic() - started, 3)
    data = (json.dumps(receipt, indent=2, sort_keys=True) + '\n').encode()
    write_once(run_fd, 'receipt.json', data)
    os.close(run_fd)
    print(f'{CARD} suite={args.suite} verdict={receipt["verdict"]} collected={len(outcomes.collected)} '
          f'counts={receipt["counts"]} pytest_exit={exit_code}')
    for failure in failures:
        print(f'FAILURE: {failure[:400]}', file=sys.stderr)
    print(f'receipt {run_dir / "receipt.json"} sha256 {sha256_bytes(data)}')
    return receipt['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
