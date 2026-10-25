"""Offline acceptance runner for SC-CATALOG-ROWS (unique literal catalog row identities).

    python3 research/scripts/accept_sc_catalog_rows.py --suite focused|contract|negative --output DIR

focused   tests/unit/test_sc_catalog_rows.py (A1 positive, A2 failure, A3 controls)
contract  tests/unit/test_coastal_live_discovery.py + tests/contract/test_research_boundary.py
          (the original compatibility files, unchanged, collected in full)
negative  tests/unit/test_sc_catalog_rows.py -k test_a3_ plus a runner-level replay of the
          last-wins double: the duplicate regression must fail with pytest's DID NOT RAISE
          and the real gate / unique-row positive controls must pass.

The repository is derived from this file. Bytecode writing is disabled and the
staged ``src`` and repository root are put on sys.path in code before any
project import; an audit sentinel refuses sockets, subprocesses and model-client
imports for the whole run. The installed pytest API runs literal test files with
plugin autoload disabled, the cache provider off and ``--basetemp`` inside the
run directory. A missing pytest/jsonschema is INPUT_UNAVAILABLE (exit 3), never a
skip.

Each invocation writes a NEW directory DIR/<utc>-<pid>-<token>/ containing
receipt.json, stdout.txt and stderr.txt (created exclusively, never overwritten).
Exit 0 only when pytest exits 0, the collected count equals the frozen expected
count, every test passed (no skip/xfail), no sentinel fired, every project module
came from this staged checkout and the hashed inputs are byte-identical before and
after. A pass is REVIEW REQUIRED: not full CI, source qualification or semantic
acceptance.
"""
import sys

sys.dont_write_bytecode = True  # before any project import

import argparse  # noqa: E402
import contextlib  # noqa: E402
import datetime  # noqa: E402
import hashlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import platform  # noqa: E402
import secrets  # noqa: E402
import time  # noqa: E402
import traceback  # noqa: E402
from pathlib import Path  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / 'src'
NEW_TESTS = 'tests/unit/test_sc_catalog_rows.py'
SUITES = {
    'focused': ([NEW_TESTS], None),
    'contract': (['tests/unit/test_coastal_live_discovery.py', 'tests/contract/test_research_boundary.py'], None),
    'negative': ([NEW_TESTS], 'test_a3_'),
}
EXPECTED = {'focused': 60, 'contract': 15, 'negative': 4}
NEGATIVE_REQUIRED = ('test_a3_real_gate_positive_control',
                     'test_a3_last_wins_double_makes_duplicate_regression_fail',
                     'test_a3_last_wins_double_keeps_unique_controls_green',
                     'test_a3_double_replaces_only_the_row_gate')
HASHED = ('research/scripts/accept_sc_catalog_rows.py', 'src/skippercast/coastal/live_discovery.py',
          NEW_TESTS, 'tests/unit/test_coastal_live_discovery.py', 'tests/contract/test_research_boundary.py',
          'tests/_support.py', 'tests/conftest.py', 'conftest.py', 'pyproject.toml',
          'skills/skippercast-discover-coastal-sources/scripts/discover.py',
          'tests/fixtures/sc_catalog_rows/duplicate-conflicting.json', 'tests/fixtures/sc_catalog_rows/unique.json',
          'docs/engineering/sc_catalog_rows.md')
BLOCKED_EVENTS = frozenset({
    'socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname', 'socket.gethostbyaddr', 'socket.bind',
    'socket.sendto', 'socket.sendmsg', 'urllib.Request', 'http.client.connect', 'subprocess.Popen', 'os.system',
    'os.exec', 'os.posix_spawn', 'os.spawn', 'os.fork', 'os.forkpty', 'pty.spawn', 'webbrowser.open'})
MODEL_MODULES = ('openai', 'anthropic', 'ollama', 'litellm', 'google.generativeai')
SENTINEL = []


def _sentinel(event, args):
    name = str(args[0]) if event == 'import' and args else ''
    if event in BLOCKED_EVENTS or any(name == m or name.startswith(m + '.') for m in MODEL_MODULES):
        SENTINEL.append(dict(event=event, detail=repr(args)[:300]))
        raise RuntimeError(f'SC-CATALOG-ROWS acceptance sentinel refused {event}')


def utc():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')


def sha256_file(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def input_hashes():
    return {name: sha256_file(REPO / name) for name in HASHED}


def git_head():
    """Read HEAD from files (subprocess is sentinel-blocked)."""
    try:
        git = REPO / '.git'
        if git.is_file():
            git = (REPO / git.read_text().split(':', 1)[1].strip()).resolve()
        head = (git / 'HEAD').read_text().strip()
        if not head.startswith('ref: '):
            return head
        ref = head[5:]
        if (git / ref).is_file():
            return (git / ref).read_text().strip()
        for line in (git / 'packed-refs').read_text().splitlines():
            if line.endswith(' ' + ref):
                return line.split()[0]
    except (OSError, IndexError):
        pass
    return None


def new_run_dir(output):
    output = Path(os.path.abspath(output))
    for ancestor in (output, *output.parents):
        if ancestor.is_symlink():
            raise SystemExit(f'refused: --output path contains a symlink: {ancestor}')
    output.mkdir(parents=True, exist_ok=True)
    run = output / f'{utc()}-{os.getpid()}-{secrets.token_hex(4)}'
    run.mkdir(mode=0o755)  # exclusive: FileExistsError if it somehow exists
    return run


def write_once(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(data)


class Recorder:
    """pytest plugin: per-test outcomes, collection count and deselection."""

    def __init__(self):
        self.collected, self.deselected, self.results, self.errors = [], 0, {}, []

    def pytest_collection_finish(self, session):
        # After -k deselection: the items that will actually run.
        self.collected = [item.nodeid for item in session.items]

    def pytest_deselected(self, items):
        self.deselected += len(items)

    def pytest_collectreport(self, report):
        if report.failed:
            self.errors.append(dict(nodeid=report.nodeid, longrepr=str(report.longrepr)[:4000]))

    def pytest_runtest_logreport(self, report):
        entry = self.results.setdefault(report.nodeid, dict(outcome='passed'))
        if report.when == 'call' and hasattr(report, 'wasxfail'):
            entry['outcome'] = 'xfail'
        elif report.skipped:
            entry['outcome'] = 'skipped'
        elif report.failed:
            entry['outcome'] = 'failed' if report.when == 'call' else f'error-{report.when}'
            entry['longrepr'] = str(report.longrepr)[:4000]


def module_origins():
    origins, outside = {}, []
    for name, module in sorted(sys.modules.items()):
        if name == 'skippercast' or name.startswith(('skippercast.', 'tests', 'coastal_bounded_discover')):
            origin = getattr(module, '__file__', None)
            origins[name] = origin
            if origin and not Path(origin).resolve().is_relative_to(REPO):
                outside.append(f'{name}: {origin}')
    return origins, outside


def replay_negative():
    """Runner-level replay of the A3 mutation with the test module's own helpers."""
    test_module = sys.modules.get('tests.unit.test_sc_catalog_rows')
    if test_module is None:
        return dict(ok=False, reason='test module not imported by pytest')
    import pytest
    ld = test_module.ld
    document = test_module.load(test_module.DUPLICATE_FIXTURE)
    real = ld._candidates
    result = dict(module=test_module.__file__, target=ld.__file__)
    try:
        test_module.assert_duplicate_rejected(document, 'synthetic:bravo', 2)
        test_module.assert_unique_diff()
        result['real_gate_positive'] = 'passed'
    except BaseException as exc:  # noqa: BLE001 - recorded as a failed control
        result['real_gate_positive'] = f'{type(exc).__name__}: {exc}'[:500]
    ld._candidates = test_module.last_wins_double
    try:
        try:
            test_module.assert_duplicate_rejected(document, 'synthetic:bravo', 2)
            result['mutation'] = 'NOT DETECTED: duplicate regression passed under last-wins double'
        except pytest.fail.Exception as exc:
            result['mutation'] = f'Failed: {exc}'[:500]
            result['mutation_detected'] = 'DID NOT RAISE' in str(exc)
        except BaseException as exc:  # noqa: BLE001 - an unrelated exception is NOT detection
            result['mutation'] = f'UNRELATED {type(exc).__name__}: {exc}'[:500]
            result['mutation_detected'] = False
        try:
            test_module.assert_unique_diff()
            result['unique_control_under_double'] = 'passed'
        except BaseException as exc:  # noqa: BLE001
            result['unique_control_under_double'] = f'{type(exc).__name__}: {exc}'[:500]
    finally:
        ld._candidates = real
    result['restored'] = ld._candidates is real
    result['ok'] = (result.get('real_gate_positive') == 'passed' and result.get('mutation_detected') is True
                    and result.get('unique_control_under_double') == 'passed' and result['restored'])
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--suite', choices=sorted(SUITES), required=True)
    parser.add_argument('--output', required=True, help='parent directory; each run makes a new child')
    args = parser.parse_args(argv)
    started, mono = utc(), time.monotonic()
    original_cwd = os.getcwd()
    run = new_run_dir(args.output)
    receipt = dict(schema='sc-catalog-rows-acceptance-v1', suite=args.suite, argv=list(sys.argv),
                   orig_argv=list(getattr(sys, 'orig_argv', [])), cwd=original_cwd, repo=str(REPO),
                   head=git_head(), started_utc=started, run_dir=str(run),
                   interpreter=dict(executable=sys.executable, realpath=os.path.realpath(sys.executable),
                                    version=sys.version, prefix=sys.prefix, base_prefix=sys.base_prefix,
                                    platform=platform.platform()),
                   status='REVIEW REQUIRED', full_ci='not run here (operator-owned)',
                   full_discovery='operator-run')
    before = input_hashes()
    receipt['inputs_before'] = before
    out, err = io.StringIO(), io.StringIO()
    failures = []
    exit_code = 1
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
    sys.path[:0] = [str(SRC), str(REPO)]
    sys.addaudithook(_sentinel)
    try:
        try:
            import pytest
            import jsonschema  # noqa: F401 - required by the original live-run tests (discover.finalize)
        except ImportError as exc:
            receipt['input_unavailable'] = f'{type(exc).__name__}: {exc}'
            failures.append(f'INPUT_UNAVAILABLE: {exc}')
            exit_code = 3
        else:
            from importlib import metadata
            receipt['interpreter']['packages'] = {
                name: metadata.version(name) for name in ('pytest', 'jsonschema')}
            receipt['interpreter']['pytest_file'] = pytest.__file__
            files, keyword = SUITES[args.suite]
            for name in files:
                if not (REPO / name).is_file():
                    failures.append(f'missing test file {name}')
            pytest_args = [*files, '-q', '-rA', '-p', 'no:cacheprovider', '--rootdir', str(REPO),
                           '-c', str(REPO / 'pyproject.toml'), '--basetemp', str(run / 'pytest-tmp')]
            if keyword:
                pytest_args += ['-k', keyword]
            receipt['pytest_args'] = pytest_args
            recorder = Recorder()
            os.chdir(REPO)
            try:
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = pytest.main(pytest_args, plugins=[recorder])
            finally:
                os.chdir(original_cwd)
            receipt['pytest_exit'] = int(code)
            counts = {}
            for entry in recorder.results.values():
                counts[entry['outcome']] = counts.get(entry['outcome'], 0) + 1
            receipt.update(collected=len(recorder.collected), deselected=recorder.deselected, counts=counts,
                           results=recorder.results, collection_errors=recorder.errors,
                           expected_collected=EXPECTED[args.suite])
            if int(code) != 0:
                failures.append(f'pytest exit {int(code)}')
            if len(recorder.collected) != EXPECTED[args.suite]:
                failures.append(f'collected {len(recorder.collected)} != expected {EXPECTED[args.suite]}')
            if counts.get('passed', 0) != len(recorder.collected) or set(counts) - {'passed'}:
                failures.append(f'non-passing outcomes: {counts}')
            if recorder.errors:
                failures.append('collection errors')
            if args.suite == 'negative':
                ran = {nodeid.rsplit('::', 1)[-1] for nodeid in recorder.results}
                missing = [name for name in NEGATIVE_REQUIRED if name not in ran]
                if missing:
                    failures.append(f'negative controls not run: {missing}')
                replay = replay_negative()
                receipt['negative_replay'] = replay
                if not replay.get('ok'):
                    failures.append('runner-level negative replay did not detect the mutation cleanly')
            origins, outside = module_origins()
            receipt['module_origins'] = origins
            receipt['imports_outside_repo'] = outside
            if outside:
                failures.append(f'project modules imported outside the staged checkout: {outside}')
            target = origins.get('skippercast.coastal.live_discovery')
            if target is None or Path(target).resolve() != (SRC / 'skippercast/coastal/live_discovery.py'):
                failures.append(f'live_discovery not imported from the staged src: {target}')
            if not failures:
                exit_code = 0
    except BaseException as exc:  # noqa: BLE001 - recorded, never a pass
        failures.append(f'runner error: {type(exc).__name__}: {exc}')
        err.write(traceback.format_exc())
        exit_code = exit_code if exit_code == 3 else 1
    after = input_hashes()
    receipt['inputs_after'] = after
    if after != before:
        failures.append('hashed inputs changed during the run')
        exit_code = 1
    if SENTINEL:
        failures.append(f'sentinel fired: {SENTINEL}')
        exit_code = 1
    receipt.update(sentinel_hits=SENTINEL, failures=failures, exit=exit_code, finished_utc=utc(),
                   runtime_seconds=round(time.monotonic() - mono, 3))
    stdout_bytes, stderr_bytes = out.getvalue().encode(), err.getvalue().encode()
    receipt['stdout_sha256'] = hashlib.sha256(stdout_bytes).hexdigest()
    receipt['stderr_sha256'] = hashlib.sha256(stderr_bytes).hexdigest()
    write_once(run / 'stdout.txt', stdout_bytes)
    write_once(run / 'stderr.txt', stderr_bytes)
    write_once(run / 'receipt.json', (json.dumps(receipt, indent=2, sort_keys=True) + '\n').encode())
    sys.stdout.write(out.getvalue())
    sys.stderr.write(err.getvalue())
    verdict = 'PASS (REVIEW REQUIRED)' if exit_code == 0 else ('INPUT_UNAVAILABLE' if exit_code == 3 else 'FAIL')
    print(f'SC-CATALOG-ROWS {args.suite}: {verdict}; collected={receipt.get("collected")} '
          f'counts={receipt.get("counts")} failures={failures}')
    print(f'receipt: {run / "receipt.json"} sha256={sha256_file(run / "receipt.json")}')
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
