#!/usr/bin/env python3
"""Offline, card-scoped SC158 acceptance runner.

Suites: regression (A1), compatibility (A2) and negative-control (A3) over
tests/unit/test_sc158_snapshot_diagnostic.py. Each invocation writes a new
run directory beneath --out. The parent process measures read-only git
identity and preflight, qualifies its finalization lifecycle with real
exit-hook late writers, then runs the suite in a guarded child process of this
same file. Network, child-process and model-client sentinels and a write guard
(run_root/child only) are installed in that child before product imports, and
skippercast.paths.repo_root is redirected to synthetic state before
skippercast.platform.contracts is imported. Only after the child has exited
and its pipes reached EOF (so its exit hooks have finished) does the parent
drain its own exit hooks and seal the child's raw stdout/stderr bytes into
stdout.txt, stderr.txt and receipt.json (plus receipt.json.sha256); it then
ends with an explicit status and runs no later writer.
"""
import sys

sys.dont_write_bytecode = True

import argparse  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
from pathlib import Path  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402
import unittest  # noqa: E402

BASE = '8a805820c30895f5f037e26af9079fd3dc015b0f'
BASE_SOURCE_SHA256 = '98a1de7d0b612e52fd5cf1925447a8dc4c78bd1a169503f77064ca82d8d0fc73'
PRODUCT = 'src/skippercast/seafloor/scoped.py'
TEST_FILE = 'tests/unit/test_sc158_snapshot_diagnostic.py'
TEST_MODULE = 'tests.unit.test_sc158_snapshot_diagnostic'
TEST_CLASS = 'SnapshotDiagnosticTests'
FIXTURE_DIR = 'tests/fixtures/sc158-snapshot-diagnostic'
SPEC_RELATIVE = ('plans', 'astra-refill-SC-15', 'FROZEN-SPECS.json')
BRIEF_RELATIVE = ('plans', 'astra-refill-SC-15', 'briefs', 'skippercast-SC158-SNAPSHOT-DIAGNOSTIC.brief')
SPEC_ROW = 'SC158-SNAPSHOT-DIAGNOSTIC'
SUITES = {
    'regression': ('test_positive_contract', 'test_rejects_malformed'),
    'compatibility': ('test_baseline_compatibility', 'test_isolation_and_discovery'),
    'negative-control': ('test_deciding_negative_control',),
}
REQUIRED_LOGS = ('stdout.txt', 'stderr.txt')
MODEL_CLIENTS = ('openai', 'anthropic', 'ollama', 'litellm', 'mistralai', 'cohere', 'google.generativeai')
CHILD_EVENTS = ('subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn', 'os.spawn', 'os.fork',
                'os.forkpty', 'pty.spawn', 'os.startfile')
# Audit event -> ((path argument index, dir_fd argument index or None), ...).
PATH_EVENTS = {'os.mkdir': ((0, 2),), 'os.symlink': ((1, 2),), 'os.link': ((1, 3),),
               'os.rename': ((0, 2), (1, 3)), 'os.remove': ((0, 1),), 'os.rmdir': ((0, 1),),
               'os.truncate': ((0, None),), 'os.chmod': ((0, 2),), 'os.chown': ((0, 3),),
               'os.utime': ((0, 3),), 'shutil.rmtree': ((0, 1),)}
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------- finalization
def seal_run(run_dir, receipt, logs):
    """Write the raw logs, then one receipt binding their full hashes and sizes.

    Never overwrites: an existing receipt raises FileExistsError, so old passing
    evidence cannot be resealed over changed logs.
    """
    run_dir = Path(run_dir)
    receipt_path = run_dir / 'receipt.json'
    if os.path.lexists(receipt_path) or os.path.lexists(run_dir / 'receipt.json.sha256'):
        raise FileExistsError('receipt already sealed for this run directory')
    present = [name for name in REQUIRED_LOGS if os.path.lexists(run_dir / name)]
    if present:
        raise FileExistsError('log already present before sealing: ' + ', '.join(present))
    bound = {}
    for name in REQUIRED_LOGS:
        data = logs.get(name, b'')
        data = data.encode('utf-8') if isinstance(data, str) else bytes(data)
        with open(run_dir / name, 'xb') as stream:
            stream.write(data)
        bound[name] = {'sha256': sha256_bytes(data), 'bytes': len(data)}
    sealed = dict(receipt, logs=bound)
    payload = (json.dumps(sealed, indent=2, sort_keys=True, ensure_ascii=False) + '\n').encode('utf-8')
    with open(receipt_path, 'xb') as stream:
        stream.write(payload)
    with open(run_dir / 'receipt.json.sha256', 'x', encoding='ascii') as stream:
        stream.write(sha256_bytes(payload) + '\n')
    return sealed


def verify_sealed(run_dir):
    """Problems with a sealed run directory; an empty list means every bound log verifies."""
    run_dir = Path(run_dir)
    problems = []
    try:
        payload = (run_dir / 'receipt.json').read_bytes()
        recorded = (run_dir / 'receipt.json.sha256').read_text(encoding='ascii').strip()
    except OSError:
        return ['missing receipt']
    if sha256_bytes(payload) != recorded:
        problems.append('changed receipt')
    try:
        logs = json.loads(payload).get('logs', {})
    except ValueError:
        return problems + ['unreadable receipt']
    for name in REQUIRED_LOGS:
        meta = logs.get(name)
        if not isinstance(meta, dict):
            problems.append(f'unbound log {name}')
            continue
        path = run_dir / name
        if not path.is_file() or path.is_symlink():
            problems.append(f'missing log {name}')
            continue
        data = path.read_bytes()
        if len(data) != meta.get('bytes') or sha256_bytes(data) != meta.get('sha256'):
            problems.append(f'changed log {name}')
    return problems


# ---------------------------------------------------------------- identity
def git(repo, *args, check=True):
    return subprocess.run(['git', '-C', str(repo), *args], check=check, capture_output=True)


def read_only_identity(repo):
    head = git(repo, 'rev-parse', 'HEAD').stdout.decode().strip()
    ancestor = git(repo, 'merge-base', '--is-ancestor', BASE, 'HEAD', check=False).returncode == 0
    tracked = git(repo, 'status', '--porcelain', '--untracked-files=no').stdout.decode()
    untracked = git(repo, 'status', '--porcelain', '--untracked-files=all').stdout.decode()
    base_source = sha256_bytes(git(repo, 'show', BASE + ':' + PRODUCT).stdout)
    return {'head': head, 'base': BASE, 'base_is_ancestor': ancestor,
            'tracked_clean': tracked == '', 'tracked_status': tracked.splitlines(),
            'untracked_status': untracked.splitlines(), 'base_source_sha256': base_source,
            'git_argv': ['rev-parse HEAD', 'merge-base --is-ancestor BASE HEAD',
                         'status --porcelain --untracked-files=no', 'status --porcelain --untracked-files=all',
                         'show BASE:' + PRODUCT]}


def preflight(repo, manifest_path, source):
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    checks = {
        'schema': manifest.get('schema') == 'agentorange.source-manifest/v1',
        'repo': manifest.get('repo') == str(repo),
        'write_root': manifest.get('write_root') == str(repo.parent),
        'base': manifest.get('head') == BASE,
        'staged_clean': manifest.get('clean') is True,
        'repo_venv': Path(manifest.get('runtime', {}).get('repo_venv', '/nonexistent')).resolve()
        == (repo / '.venv').resolve(),
        'credential_scan_python3': Path(manifest.get('runtime', {}).get('credential_scan_python3', '/nonexistent')).is_file(),
        'base_is_ancestor': source['base_is_ancestor'],
        'base_source_pin': source['base_source_sha256'] == BASE_SOURCE_SHA256,
        'test_file': (repo / TEST_FILE).is_file(),
    }
    failed = sorted(name for name, ok in checks.items() if not ok)
    if failed:
        raise RuntimeError('preflight failed: ' + ', '.join(failed))
    planning = Path(manifest['write_root']).parents[1]
    spec_path, brief_path = planning.joinpath(*SPEC_RELATIVE), planning.joinpath(*BRIEF_RELATIVE)
    spec = {'relative': '/'.join(SPEC_RELATIVE), 'sha256': None, 'row_sha256': None}
    if spec_path.is_file():
        spec['sha256'] = sha256_file(spec_path)
        rows = json.loads(spec_path.read_text(encoding='utf-8'))
        rows = rows.get('specs', rows.get('rows', [])) if isinstance(rows, dict) else rows
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict) and row.get('id') == SPEC_ROW:
                spec['row_sha256'] = sha256_bytes(json.dumps(row, sort_keys=True).encode('utf-8'))
    brief = {'relative': '/'.join(BRIEF_RELATIVE),
             'sha256': sha256_file(brief_path) if brief_path.is_file() else None}
    return {'manifest': {'path': str(manifest_path), 'sha256': sha256_bytes(manifest_bytes), 'checks': checks},
            'spec': spec, 'brief': brief, 'venv': str((repo / '.venv').resolve())}


def input_hashes(repo):
    names = [PRODUCT, TEST_FILE, 'tools/run_sc158_snapshot_diagnostic.py', 'catalog/seafloor-scope.json']
    names += sorted(str(path.relative_to(repo)) for path in (repo / FIXTURE_DIR).rglob('*') if path.is_file())
    return {name: sha256_file(repo / name) for name in names}


# ---------------------------------------------------------------- guards
class ModelClientBlocker:
    """Meta-path sentinel: no model client module can be imported in this process."""

    def find_spec(self, name, path=None, target=None):
        if any(name == blocked or name.startswith(blocked + '.') for blocked in MODEL_CLIENTS):
            raise ImportError('SC158 no-model sentinel refused import of ' + name)
        return None


def install_guards(run_root, refusals):
    run_root = run_root.resolve()

    def inside(target, dir_fd=None):
        if isinstance(target, int):
            return True
        name = os.fsdecode(target)
        if dir_fd is not None and not os.path.isabs(name):
            name = os.path.join(os.readlink(f'/proc/self/fd/{dir_fd}'), name)
        absolute = os.path.abspath(name)
        candidate = Path(os.path.realpath(os.path.dirname(absolute))) / os.path.basename(absolute)
        return candidate == run_root or run_root in candidate.parents

    def refuse(reason):
        refusals.append(reason)
        raise RuntimeError('SC158 offline guard refused ' + reason)

    def audit(event, args):
        if event.startswith('socket.') or event in ('urllib.Request', 'http.client.connect'):
            refuse('network:' + event)
        if event in CHILD_EVENTS or event.startswith(('os.exec', 'os.spawn')):
            refuse('child-execution:' + event)
        if event == 'open' and len(args) > 2 and isinstance(args[2], int) and args[2] & WRITE_FLAGS:
            if not inside(args[0]):
                refuse('write-outside-run-root:open')
        for index, fd_index in PATH_EVENTS.get(event, ()):
            if index >= len(args) or args[index] is None:
                continue
            dir_fd = args[fd_index] if fd_index is not None and fd_index < len(args) else None
            if not inside(args[index], dir_fd if isinstance(dir_fd, int) and dir_fd >= 0 else None):
                refuse('write-outside-run-root:' + event)

    sys.addaudithook(audit)
    sys.meta_path.insert(0, ModelClientBlocker())
    fixtures = run_root / 'fixtures'
    temporary = run_root / 'tmp'
    fixtures.mkdir()
    temporary.mkdir()
    os.environ['SC158_OUT_ROOT'] = str(fixtures)
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    import tempfile
    tempfile.tempdir = str(temporary)
    return {'audit_hook': True, 'model_client_blocker': list(MODEL_CLIENTS), 'fixture_root': str(fixtures),
            'tempdir': str(temporary)}


def redirect_repo_root(repo, run_root):
    if any(name == 'skippercast' or name.startswith('skippercast.') for name in sys.modules):
        raise RuntimeError('skippercast was imported before the repo_root redirect')
    synthetic = run_root / 'synthetic-repo'
    (synthetic / 'catalog').mkdir(parents=True)
    shutil.copyfile(repo / 'catalog' / 'seafloor-scope.json', synthetic / 'catalog' / 'seafloor-scope.json')
    sys.path.insert(0, str(repo))
    sys.path.insert(0, str(repo / 'src'))
    import skippercast.paths as paths
    if not Path(paths.__file__).resolve().is_relative_to((repo / 'src').resolve()):
        raise RuntimeError('skippercast.paths did not resolve to this checkout')
    paths.repo_root = lambda: synthetic
    from skippercast.platform import contracts
    if contracts.REPO != synthetic:
        raise RuntimeError('contracts.REPO was not redirected to synthetic state')
    return str(synthetic)


# ---------------------------------------------------------------- execution
class RecordingResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.subtests = {}

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        case = subtest.params.get('case', subtest._subDescription())
        outcome = 'pass' if err is None else ('fail' if issubclass(err[0], test.failureException) else 'error')
        self.subtests.setdefault(test.id(), {})[case] = outcome


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def run_suite(repo, suite_name, stream):
    loader = unittest.TestLoader()
    discovered = loader.discover(str(repo / 'tests' / 'unit'), pattern=Path(TEST_FILE).name,
                                 top_level_dir=str(repo))
    collected = [test for test in flatten(discovered)]
    failures_to_load = [test.id() for test in collected if test.id().startswith('unittest.loader')]
    module = sys.modules.get(TEST_MODULE)
    if failures_to_load or module is None:
        raise RuntimeError('card test module failed to load: ' + ', '.join(failures_to_load))
    if not Path(module.__file__).resolve() == (repo / TEST_FILE).resolve():
        raise RuntimeError('card test module resolved outside this checkout')
    wanted = {f'{TEST_MODULE}.{TEST_CLASS}.{name}' for name in SUITES[suite_name]}
    collected_ids = sorted(test.id() for test in collected)
    every_required = {f'{TEST_MODULE}.{TEST_CLASS}.{name}' for name in module.REQUIRED_TESTS}
    selected = unittest.TestSuite(test for test in collected if test.id() in wanted)
    selected_ids = sorted(test.id() for test in flatten(selected))  # suites drop tests after running
    runner = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=RecordingResult)
    result = runner.run(selected)
    missing_cases = {}
    for name in SUITES[suite_name]:
        test_id = f'{TEST_MODULE}.{TEST_CLASS}.{name}'
        observed = result.subtests.get(test_id, {})
        absent = [case for case in module.SUBTEST_CASES[name] if observed.get(case) != 'pass']
        if absent:
            missing_cases[name] = absent
    return module, result, {
        'collected_ids': collected_ids,
        'required_collected': sorted(every_required - set(collected_ids)) == [],
        'selected_ids': selected_ids,
        'expected_ids': sorted(wanted),
        'tests_run': result.testsRun,
        'failures': len(result.failures),
        'errors': len(result.errors),
        'skipped': len(result.skipped),
        'expected_failures': len(result.expectedFailures),
        'unexpected_successes': len(result.unexpectedSuccesses),
        'subtests': result.subtests,
        'subtest_case_count': sum(len(cases) for cases in result.subtests.values()),
        'missing_or_failed_cases': missing_cases,
        'failure_details': [text for _, text in result.failures + result.errors],
    }


def module_origins(repo):
    src = (repo / 'src').resolve()
    origins, outside = {}, []
    for name, module in sorted(sys.modules.items()):
        origin = getattr(module, '__file__', None)
        if origin and (name.split('.')[0] in ('skippercast', 'pyproj', 'shapely', 'tests')):
            origins[name] = origin
            if name.split('.')[0] == 'skippercast' and not Path(origin).resolve().is_relative_to(src):
                outside.append(name)
    return origins, outside



# ---------------------------------------------------------------- supervised lifecycle
CHILD_DIR = 'child'
CHILD_RESULT = 'child-result.json'
QUALIFICATION_ENV = 'SC158_FINALIZATION_QUALIFICATION'
LATE_LINE = 'SC158 synthetic exit-hook late writer\n'
PROBE_MODES = ('late-stream', 'late-file')


def write_child_result(child_root, result):
    with open(Path(child_root) / CHILD_RESULT, 'x', encoding='utf-8') as stream:
        stream.write(json.dumps(result, indent=2, sort_keys=True, default=str) + '\n')


def drain_exit_writers():
    """Run (and clear) every exit hook registered in this process, then flush, before sealing."""
    import atexit
    atexit._run_exitfuncs()
    sys.stdout.flush()
    sys.stderr.flush()


def supervise(run_root, argv, env=None):
    """Run one child process to completion; return its raw output and result file.

    subprocess.run returns only after the child has exited and both pipes reached
    EOF, so every exit hook of the child has finished and its stream writes are in
    the raw bytes. The child may write only beneath run_root/child; any other new
    top-level entry (for example a late writer creating stderr.txt) is reported.
    """
    run_root = Path(run_root)
    before = set(os.listdir(run_root))
    done = subprocess.run(argv, capture_output=True, env=env)
    unexpected = sorted(set(os.listdir(run_root)) - before - {CHILD_DIR})
    result_path = run_root / CHILD_DIR / CHILD_RESULT
    child_result, result_sha = None, None
    if result_path.is_file() and not result_path.is_symlink():
        payload = result_path.read_bytes()
        result_sha = sha256_bytes(payload)
        try:
            child_result = json.loads(payload)
        except ValueError:
            child_result = None
    return {'argv': list(argv), 'returncode': done.returncode, 'stdout': done.stdout, 'stderr': done.stderr,
            'unexpected_entries': unexpected, 'child_result': child_result, 'child_result_sha256': result_sha}


def finalize(run_root, receipt, outcome, extra_gates=None, before_seal=None):
    """Decide from the completed child, then seal its raw output once; return (exit_code, summary).

    A late writer that already created a log, or a seal that does not verify,
    yields a nonzero FAIL; an existing receipt is never resealed.
    """
    child = outcome['child_result'] if isinstance(outcome['child_result'], dict) else {}
    child_gates = child.get('gates') if isinstance(child.get('gates'), dict) else {}
    gates = {
        'child_exit_zero': outcome['returncode'] == 0,
        'child_result_present': outcome['child_result_sha256'] is not None,
        'child_reported_pass': child.get('status') == 'PASS',
        'child_gates_all_true': bool(child_gates) and all(child_gates.values()),
        'no_unexpected_run_root_entries': outcome['unexpected_entries'] == [],
    }
    gates.update(extra_gates or {})
    status = 'PASS' if all(gates.values()) else 'FAIL'
    sealed = dict(receipt, child={'argv': outcome['argv'], 'exit_code': outcome['returncode'],
                                  'result_sha256': outcome['child_result_sha256'],
                                  'unexpected_entries': outcome['unexpected_entries']},
                  child_result=outcome['child_result'], final_gates=gates, status=status,
                  exit_code=0 if status == 'PASS' else 1)
    if before_seal is not None:
        before_seal()
    try:
        seal_run(run_root, sealed, {'stdout.txt': outcome['stdout'], 'stderr.txt': outcome['stderr']})
        problems = verify_sealed(run_root)
    except FileExistsError as exc:
        problems = ['unsealable: ' + str(exc)]
    exit_code = sealed['exit_code'] if not problems else 1
    return exit_code, {'status': status if not problems else 'FAIL', 'exit_code': exit_code,
                       'run_root': str(run_root), 'seal_problems': problems, 'gates': gates}


def qualify_finalization(root):
    """Exercise the genuine supervise/finalize lifecycle with real exit-hook late writers.

    late-stream: a guarded child's exit hook writes to stderr after its result is
    written; the sealed stderr.txt must contain that line and verify (positive).
    late-file: an unguarded child's exit hook appends to the parent's stderr.txt
    path; finalization must reject nonzero and never seal a PASS (negative).
    """
    root = Path(root)
    root.mkdir(parents=True)
    modes = {}
    for mode in PROBE_MODES:
        probe_root = root / mode
        probe_root.mkdir()
        argv = [sys.executable, str(Path(__file__).resolve()), '--finalization-probe', mode,
                '--child-run-root', str(probe_root)]
        outcome = supervise(probe_root, argv)
        code, summary = finalize(probe_root, {'schema': 'sc158.finalization-probe/v1', 'mode': mode}, outcome)
        late = LATE_LINE.encode('utf-8')
        sealed_log = probe_root / 'stderr.txt'
        sealed_has_late = sealed_log.is_file() and late in sealed_log.read_bytes()
        record = {'argv': argv, 'exit_code': code, 'status': summary['status'],
                  'seal_problems': summary['seal_problems'], 'unexpected_entries': outcome['unexpected_entries'],
                  'child_exit_code': outcome['returncode'], 'late_line_in_raw_stderr': late in outcome['stderr'],
                  'late_line_in_sealed_stderr': sealed_has_late, 'probe_root': str(probe_root)}
        if mode == 'late-stream':
            record['passed'] = (code == 0 and summary['status'] == 'PASS' and summary['seal_problems'] == []
                                and record['late_line_in_raw_stderr'] and sealed_has_late)
        else:
            record['passed'] = (code != 0 and summary['status'] == 'FAIL'
                                and 'stderr.txt' in outcome['unexpected_entries']
                                and not (probe_root / 'receipt.json').exists())
        modes[mode] = record
    return {'passed': all(item['passed'] for item in modes.values()), 'modes': modes}


def probe_main(mode, run_root):
    """A finalization probe child: write its result, then let a real exit hook write late."""
    import atexit
    run_root = Path(run_root).resolve()
    child_root = run_root / CHILD_DIR
    child_root.mkdir()
    refusals = []
    if mode == 'late-stream':
        install_guards(child_root, refusals)

        def late_writer():
            sys.stderr.write(LATE_LINE)
            sys.stderr.flush()
    else:
        def late_writer():
            with open(run_root / 'stderr.txt', 'a', encoding='utf-8') as stream:
                stream.write(LATE_LINE)
    atexit.register(late_writer)
    write_child_result(child_root, {'status': 'PASS', 'mode': mode, 'gates': {'probe_completed': True},
                                    'guard_refusals': refusals})
    print('SC158 finalization probe ' + mode + ' wrote its result before exit hooks')
    return 0


def child_main(args, repo):
    """The guarded test process: sentinels before product imports, writes only under run_root/child."""
    run_root = Path(args.child_run_root).resolve()
    child_root = run_root / CHILD_DIR
    child_root.mkdir()
    refusals = []
    result = {'schema': 'sc158.child-result/v1', 'suite': args.suite, 'status': 'FAIL', 'pid': os.getpid()}
    try:
        result['guards'] = install_guards(child_root, refusals)
        result['synthetic_repo_root'] = redirect_repo_root(repo, child_root)
        module, _, tests = run_suite(repo, args.suite, sys.stderr)
        result['tests'] = tests
        result['module_origins'], outside = module_origins(repo)
        gates = {
            'all_required_methods_collected': tests['required_collected'],
            'selected_matches_expected': tests['selected_ids'] == tests['expected_ids'],
            'tests_run_matches': tests['tests_run'] == len(SUITES[args.suite]),
            'no_failures_or_errors': tests['failures'] == 0 and tests['errors'] == 0,
            'no_skips': tests['skipped'] == 0 and tests['expected_failures'] == 0
            and tests['unexpected_successes'] == 0,
            'every_required_case_passed': tests['missing_or_failed_cases'] == {},
            'product_modules_from_checkout': outside == [],
            'no_guard_refusals': refusals == [],
        }
        if args.suite == 'negative-control':
            evidence = list(module.NEGATIVE_EVIDENCE)
            result['negative_control'] = evidence
            gates['mutant_detected'] = any(item.get('detected') for item in evidence)
            gates['positive_passed_after_restore'] = any(item.get('passed') for item in evidence)
        result['gates'] = gates
        if all(gates.values()):
            result['status'] = 'PASS'
    except Exception as exc:  # recorded, never swallowed into a pass
        result['exception'] = repr(exc)
    result['guard_refusals'] = list(refusals)
    write_child_result(child_root, result)
    print(json.dumps({'child_status': result['status'], 'suite': args.suite,
                      'tests_run': result.get('tests', {}).get('tests_run'),
                      'subtest_cases': result.get('tests', {}).get('subtest_case_count')}, sort_keys=True))
    return 0 if result['status'] == 'PASS' else 1


def parent_main(args, repo):
    """Measure identity, qualify finalization, run the guarded child, then seal its raw output."""
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    run_root = out / f'run-{time.time_ns()}-{os.getpid()}'
    run_root.mkdir()
    started = datetime.now(timezone.utc)
    clock = time.monotonic()
    manifest = Path(args.source_manifest).resolve()
    receipt = {'schema': 'sc158.acceptance-receipt/v2', 'suite': args.suite, 'argv': list(sys.argv),
               'cwd': os.getcwd(), 'interpreter': sys.executable, 'python': sys.version,
               'repo': str(repo), 'run_root': str(run_root), 'started_utc': started.isoformat()}
    try:
        receipt['source'] = read_only_identity(repo)
        receipt.update(preflight(repo, manifest, receipt['source']))
        receipt['inputs'] = input_hashes(repo)
        receipt['candidate_source_sha256'] = receipt['inputs'][PRODUCT]
        qualification = qualify_finalization(run_root / 'finalization-qualification')
        receipt['finalization_qualification'] = qualification
        qualification_path = run_root / 'finalization-qualification.json'
        with open(qualification_path, 'x', encoding='utf-8') as stream:
            stream.write(json.dumps(qualification, indent=2, sort_keys=True) + '\n')
        receipt['finalization_qualification_sha256'] = sha256_file(qualification_path)
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        env[QUALIFICATION_ENV] = str(qualification_path)
        argv = [sys.executable, str(Path(__file__).resolve()), '--suite', args.suite,
                '--source-manifest', str(manifest), '--out', str(out), '--child-run-root', str(run_root)]
        outcome = supervise(run_root, argv, env)
        receipt['source_after'] = read_only_identity(repo)
        extra = {'finalization_qualified': qualification['passed'],
                 'tracked_clean_before': receipt['source']['tracked_clean'],
                 'head_unchanged': receipt['source_after']['head'] == receipt['source']['head'],
                 'tracked_clean_after': receipt['source_after']['tracked_clean']}
    except Exception as exc:  # recorded, never swallowed into a pass
        receipt['exception'] = repr(exc)
        outcome = {'argv': [], 'returncode': None, 'stdout': b'', 'stderr': repr(exc).encode('utf-8'),
                   'unexpected_entries': [], 'child_result': None, 'child_result_sha256': None}
        extra = {'parent_completed': False}
    receipt['finished_utc'] = datetime.now(timezone.utc).isoformat()
    receipt['elapsed_seconds'] = round(time.monotonic() - clock, 6)
    code, summary = finalize(run_root, receipt, outcome, extra, before_seal=drain_exit_writers)
    child = outcome['child_result'] if isinstance(outcome['child_result'], dict) else {}
    summary.update({'suite': args.suite, 'head': receipt.get('source', {}).get('head'),
                    'tests_run': child.get('tests', {}).get('tests_run'),
                    'subtest_cases': child.get('tests', {}).get('subtest_case_count'),
                    'child_gates': child.get('gates'), 'exception': receipt.get('exception')})
    print(json.dumps(summary, indent=2, sort_keys=True))
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--suite', choices=sorted(SUITES))
    parser.add_argument('--source-manifest')
    parser.add_argument('--out')
    parser.add_argument('--child-run-root', help=argparse.SUPPRESS)
    parser.add_argument('--finalization-probe', choices=PROBE_MODES, help=argparse.SUPPRESS)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    if args.finalization_probe:
        if not args.child_run_root:
            parser.error('--finalization-probe needs --child-run-root')
        return probe_main(args.finalization_probe, args.child_run_root)
    if not (args.suite and args.source_manifest and args.out):
        parser.error('--suite, --source-manifest and --out are required')
    if args.child_run_root:
        return child_main(args, repo)
    code = parent_main(args, repo)
    # The seal is final: flush, then end without running any later exit-hook writer.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


if __name__ == '__main__':
    raise SystemExit(main())
