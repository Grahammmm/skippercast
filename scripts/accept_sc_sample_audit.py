"""SC-SAMPLE-AUDIT acceptance runner (offline, in-process, write-once run directories).

    python3 scripts/accept_sc_sample_audit.py --suite {focused,contract,negative} --output DIR

Runs the plain test functions of tests/unit/test_sc_sample_audit.py with the installed
python3 (no pytest needed) after installing DNS/socket/HTTP/subprocess/model sentinels,
redirecting temporary files into the unique run directory and tracing transitive imports.
Every run writes DIR/run-<utc>-<pid>/{receipt.json,log.txt}; existing runs are never
overwritten. Exit 0 only when every named assertion of the suite passed. Success is
REVIEW REQUIRED, not full CI, source qualification or semantic acceptance.
"""
import sys

sys.dont_write_bytecode = True  # before any project import

import argparse  # noqa: E402
import contextlib  # noqa: E402
import datetime  # noqa: E402
import hashlib  # noqa: E402
import importlib.util  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
from pathlib import Path  # noqa: E402
import stat  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
import tomllib  # noqa: E402
import traceback  # noqa: E402
import zlib  # noqa: E402

REPO = Path(__file__).resolve().parents[1]

BASE_COMMIT = '59fca09b2cc7f5c81a4796902504e263d7f06960'
SOURCE_PINS = {
    'skills/coast-campaign-shared/scripts/coast_sample.py':
        '328ea0069bef5e0bbb412cf031a5032ec925f8e52749cf4d644714f8e9c05924',
    'skills/coast-campaign-shared/scripts/coast_receipt_versions.py':
        '20a8c5809e65c7035f63b9576d266b18184a02ed93a781b8fc4c40b39ce5f0b7',
}
OWNED_FILES = [
    'scripts/coast_diagnostics/sample_coverage.py',
    'tests/unit/test_sc_sample_audit.py',
    'scripts/accept_sc_sample_audit.py',
    'docs/engineering/sc_sample_audit.md',
    'tests/fixtures/sc_sample_audit/focused_population.json',
]
TEST_FILE = REPO / 'tests' / 'unit' / 'test_sc_sample_audit.py'
SUITE_PREFIX = {'focused': 'test_a1_', 'contract': 'test_a2_', 'negative': 'test_a3_'}
FORBIDDEN_MODULES = ('openai', 'anthropic', 'ollama', 'requests', 'httpx', 'urllib3', 'aiohttp',
                     'skippercast.http', 'boto3', 'botocore')


class SentinelTripped(RuntimeError):
    pass


EVENTS = {'sentinel': [], 'write_outside_run': [], 'blocked_imports': []}
STATE = {'run_dir': None}


def _sentinel(name):
    def blocked(*args, **kwargs):
        EVENTS['sentinel'].append(name)
        raise SentinelTripped('offline sentinel: %s' % name)
    return blocked


def install_sentinels():
    import socket
    import subprocess
    import urllib.request
    import http.client
    for attr in ('create_connection', 'getaddrinfo', 'gethostbyname', 'gethostbyname_ex', 'create_server'):
        setattr(socket, attr, _sentinel('socket.' + attr))
    socket.socket.connect = _sentinel('socket.socket.connect')
    socket.socket.connect_ex = _sentinel('socket.socket.connect_ex')
    for attr in ('Popen', 'run', 'call', 'check_call', 'check_output', 'getoutput', 'getstatusoutput'):
        setattr(subprocess, attr, _sentinel('subprocess.' + attr))
    for attr in ('system', 'popen', 'fork', 'forkpty', 'posix_spawn', 'posix_spawnp', 'execv', 'execve',
                 'execvp', 'execvpe', 'execl', 'execle', 'execlp', 'execlpe', 'spawnv', 'spawnve',
                 'spawnvp', 'spawnvpe', 'spawnl', 'spawnle', 'spawnlp', 'spawnlpe'):
        if hasattr(os, attr):
            setattr(os, attr, _sentinel('os.' + attr))
    urllib.request.urlopen = _sentinel('urllib.request.urlopen')
    http.client.HTTPConnection.connect = _sentinel('http.client.HTTPConnection.connect')

    class ModelImportBlocker:
        def find_spec(self, name, path=None, target=None):
            if any(name == m or name.startswith(m + '.') for m in FORBIDDEN_MODULES):
                EVENTS['blocked_imports'].append(name)
                raise ImportError('offline sentinel: model/network module %s' % name)
            return None

    sys.meta_path.insert(0, ModelImportBlocker())

    write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC

    def hook(event, args):
        if event in ('socket.connect', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system',
                     'os.exec', 'os.posix_spawn', 'os.spawn', 'urllib.Request'):
            EVENTS['sentinel'].append('audit:' + event)
        elif event == 'open' and STATE['run_dir'] is not None:
            path, mode, flags = args
            writing = (isinstance(mode, str) and any(c in mode for c in 'wax+')) or \
                (isinstance(flags, int) and flags & write_flags)
            if writing and isinstance(path, (str, bytes, os.PathLike)):
                target = os.path.abspath(os.fsdecode(path))
                if not target.startswith(str(STATE['run_dir']) + os.sep):
                    EVENTS['write_outside_run'].append(target)

    sys.addaudithook(hook)


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _git_object(sha):
    loose = REPO / '.git' / 'objects' / sha[:2] / sha[2:]
    if not loose.is_file():
        return None
    return zlib.decompress(loose.read_bytes())


def git_identity():
    """Read HEAD without git/subprocess; verify BASE_COMMIT is HEAD or a loose-commit ancestor."""
    git = REPO / '.git'
    head = (git / 'HEAD').read_text(encoding='ascii').strip()
    ref = None
    if head.startswith('ref: '):
        ref = head[5:]
        ref_path = git / ref
        if ref_path.is_file():
            head = ref_path.read_text(encoding='ascii').strip()
        else:
            head = None
            for line in (git / 'packed-refs').read_text(encoding='ascii').splitlines():
                if line.endswith(' ' + ref):
                    head = line.split()[0]
    chain, sha = [], head
    while sha and sha != BASE_COMMIT and len(chain) < 64:
        chain.append(sha)
        body = _git_object(sha)
        if body is None or not body.startswith(b'commit '):
            sha = None
            break
        parents = [ln.split()[1].decode() for ln in body.split(b'\n\n', 1)[0].split(b'\n')
                   if ln.startswith(b'parent ')]
        sha = parents[0] if len(parents) == 1 else None
    return {'head': head, 'ref': ref, 'base': BASE_COMMIT, 'commits_above_base': chain,
            'base_verified': sha == BASE_COMMIT}


def _safe_components(output):
    """Supplied output components without lexical normalization; '..' is refused outright."""
    text = os.fspath(output)
    if not isinstance(text, str) or not text or '\x00' in text:
        raise SystemExit('REFUSED output path is not a usable string: %r' % (text,))
    if not os.path.isabs(text):
        text = os.path.join(os.getcwd(), text)  # getcwd is reported physically
    parts = [part for part in text.split(os.sep) if part not in ('', '.')]
    if '..' in parts:
        raise SystemExit('REFUSED output path contains "..": %s' % text)
    if not parts:
        raise SystemExit('REFUSED output path is the filesystem root')
    return parts


def _real_directory(path):
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(info.st_mode):
        raise SystemExit('REFUSED output path component is a symlink: %s' % path)
    if not stat.S_ISDIR(info.st_mode):
        raise SystemExit('REFUSED output path component is not a directory: %s' % path)
    return info


def make_run_dir(output):
    """Validate every existing ancestor before creating anything, then create one level at a time."""
    parts = _safe_components(output)
    paths, current = [], Path(os.sep)
    for part in parts:
        current = current / part
        paths.append(current)
    missing_from = len(paths)
    for position, path in enumerate(paths):  # first pass: no creation at all
        if _real_directory(path) is None:
            missing_from = position
            break
    for path in paths[missing_from:]:
        try:
            os.mkdir(path, 0o755)
        except FileExistsError:
            pass
        if _real_directory(path) is None:
            raise SystemExit('REFUSED output path component vanished: %s' % path)
    root = paths[-1]
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    for attempt in range(100):
        suffix = '' if attempt == 0 else '-%d' % attempt
        run_dir = root / ('run-%s-%d%s' % (stamp, os.getpid(), suffix))
        try:
            os.mkdir(run_dir, 0o755)
        except FileExistsError:
            continue
        os.mkdir(run_dir / 'tmp', 0o755)
        return run_dir
    raise SystemExit('REFUSED could not create a unique run directory under %s' % root)


def write_once(path, text):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        stream.write(text)


def load_test_module():
    name = 'sc_sample_audit_acceptance_tests'
    spec = importlib.util.spec_from_file_location(name, TEST_FILE)
    if spec is None or spec.loader is None:
        raise SystemExit('test module not loadable: %s' % TEST_FILE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def run_test(module, name):
    fn = getattr(module, name)
    out, err = io.StringIO(), io.StringIO()
    started = time.monotonic()
    record = {'name': name}
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            fn()
        record['outcome'] = 'passed'
    except BaseException as error:  # record every failure class, including sentinel trips
        record['outcome'] = 'failed'
        record['error_type'] = type(error).__name__
        record['error_reason'] = getattr(error, 'reason', None)
        record['error'] = str(error)[:2000]
        record['traceback'] = traceback.format_exc()[-4000:]
    record['seconds'] = round(time.monotonic() - started, 4)
    record['stdout'] = out.getvalue()[-4000:]
    record['stderr'] = err.getvalue()[-4000:]
    return record


def mutation_controls(module):
    """In-memory callable doubles that omit the zero-selected group; never a child interpreter."""
    audit = module.audit
    original_build, original_check = audit._build_groups, audit._check_complete

    def omit_zero_selected(document, decoded):
        rows = original_build(document, decoded)
        return [r for r in rows if not (r['eligible_count'] > 0 and r['selected_count'] == 0)]

    def no_completeness_gate(groups, document, decoded):
        return {f: sum(r[f + '_count'] for r in groups) for f in audit.GROUP_FIELDS}

    controls = []

    def control(label, expect, tests):
        for name in tests:
            record = run_test(module, name)
            record['control'] = label
            record['expected'] = expect
            ok = record['outcome'] == 'passed' if expect['outcome'] == 'passed' else (
                record['outcome'] == 'failed' and record.get('error_type') == expect['error_type']
                and record.get('error_reason') == expect.get('error_reason')
                and expect.get('message', '') in record.get('error', ''))
            record['control_ok'] = bool(ok)
            controls.append(record)

    targets = ['test_a1_zero_selected_group_visible', 'test_a1_report_is_complete']
    control('positive-before', {'outcome': 'passed'}, targets)
    try:
        audit._build_groups = omit_zero_selected
        control('omit-zero-selected-group/internal-gate',
                {'outcome': 'failed', 'error_type': 'SampleAuditInvalid', 'error_reason': 'report_incomplete'},
                targets)
        audit._check_complete = no_completeness_gate
        control('omit-zero-selected-group/internal-gate-disabled/test-assertion',
                {'outcome': 'failed', 'error_type': 'AssertionError', 'error_reason': None,
                 'message': 'must not be omitted'}, ['test_a1_zero_selected_group_visible'])
        control('omit-zero-selected-group/internal-gate-disabled/completeness-assertion',
                {'outcome': 'failed', 'error_type': 'AssertionError', 'error_reason': None,
                 'message': 'report incomplete'}, ['test_a1_report_is_complete'])
    finally:
        audit._build_groups, audit._check_complete = original_build, original_check
    control('positive-after-restore', {'outcome': 'passed'}, targets)

    # Isolated control for the trusted sample-hash check (rule-29 disposition, option A).
    original_hash_check = audit.check_sample_hash
    hash_target = ['test_a3_cli_sample_hash_mismatch_invalid_before_parse_or_write']
    control('sample-hash/positive-before', {'outcome': 'passed'}, hash_target)
    try:
        audit.check_sample_hash = lambda raw, expected: audit.hashlib.sha256(raw).hexdigest()
        control('sample-hash/comparison-disabled',
                {'outcome': 'failed', 'error_type': 'AssertionError', 'error_reason': None,
                 'message': 'hash mismatch must be INVALID'}, hash_target)
    finally:
        audit.check_sample_hash = original_hash_check
    control('sample-hash/positive-after-restore', {'outcome': 'passed'}, hash_target)
    return controls


def collection_check():
    """Static proof the new test file sits under pyproject testpaths/python_files."""
    config = tomllib.loads((REPO / 'pyproject.toml').read_text(encoding='utf-8'))['tool']['pytest']['ini_options']
    rel = TEST_FILE.relative_to(REPO)
    in_paths = any(rel.parts[0] == p for p in config['testpaths'])
    matches = any(Path(rel.name).match(pattern) for pattern in config['python_files'])
    return {'testpaths': config['testpaths'], 'python_files': config['python_files'],
            'file': str(rel), 'in_testpaths': in_paths, 'matches_python_files': matches,
            'ok': bool(in_paths and matches)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--suite', required=True, choices=sorted(SUITE_PREFIX))
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    sys.path.insert(0, str(REPO))  # this staged repository only; never a shared checkout
    run_dir = make_run_dir(args.output)
    log_lines = []

    def log(line):
        log_lines.append(line)
        print(line)

    install_sentinels()
    tempfile.tempdir = str(run_dir / 'tmp')
    STATE['run_dir'] = run_dir

    failures = []
    pins = {}
    for rel, expected in SOURCE_PINS.items():
        actual = sha256_file(REPO / rel)
        pins[rel] = {'expected': expected, 'actual': actual, 'ok': actual == expected}
        if actual != expected:
            failures.append('source pin mismatch: ' + rel)
    identity = git_identity()
    if not identity['base_verified']:
        failures.append('base commit not verified as HEAD ancestor')
    modules_before = set(sys.modules)
    module = load_test_module()
    imported = sorted(set(sys.modules) - modules_before)
    bad_imports = [m for m in imported if any(m == f or m.startswith(f + '.') for f in FORBIDDEN_MODULES)]
    if bad_imports:
        failures.append('forbidden transitive imports: %s' % bad_imports)

    names = sorted(n for n in vars(module) if n.startswith(SUITE_PREFIX[args.suite]) and callable(getattr(module, n)))
    all_tests = sorted(n for n in vars(module) if n.startswith('test_'))
    unrowed = [n for n in all_tests if not any(n.startswith(p) for p in SUITE_PREFIX.values())]
    if unrowed:
        failures.append('tests outside acceptance rows: %s' % unrowed)
    if not names:
        failures.append('no tests collected for suite')
    results = [run_test(module, name) for name in names]
    for record in results:
        log('%s %s' % (record['outcome'].upper(), record['name']))
        if record['outcome'] != 'passed':
            failures.append('test failed: ' + record['name'])
            log(record.get('traceback', ''))
    extra = {}
    if args.suite == 'contract':
        extra['collection'] = collection_check()
        log('COLLECTION %s' % json.dumps(extra['collection'], sort_keys=True))
        if not extra['collection']['ok']:
            failures.append('test file not discoverable by pyproject settings')
    if args.suite == 'negative':
        controls = mutation_controls(module)
        extra['mutation_controls'] = controls
        for record in controls:
            log('CONTROL %s %s %s -> %s%s' % ('OK' if record['control_ok'] else 'BAD', record['control'],
                                             record['name'], record['outcome'],
                                             ' (%s %s)' % (record.get('error_type'), record.get('error_reason'))
                                             if record['outcome'] == 'failed' else ''))
            if not record['control_ok']:
                failures.append('mutation control unexpected: %s %s' % (record['control'], record['name']))
    STATE['run_dir'] = None
    if EVENTS['sentinel']:
        failures.append('sentinel tripped: %s' % EVENTS['sentinel'])
    if EVENTS['write_outside_run']:
        failures.append('write outside run dir: %s' % EVENTS['write_outside_run'][:10])
    if EVENTS['blocked_imports']:
        failures.append('blocked imports attempted: %s' % EVENTS['blocked_imports'])

    passed = sum(1 for r in results if r['outcome'] == 'passed')
    failed = len(results) - passed
    status = 0 if not failures else 1
    receipt = {
        'card': 'SC-SAMPLE-AUDIT', 'suite': args.suite, 'argv': [sys.executable] + sys.argv,
        'cwd': os.getcwd(), 'python': sys.version, 'executable': sys.executable,
        'dont_write_bytecode': sys.dont_write_bytecode, 'run_dir': str(run_dir),
        'git': identity, 'source_pins': pins,
        'code_hashes': {rel: sha256_file(REPO / rel) for rel in OWNED_FILES if (REPO / rel).is_file()},
        'tests_collected': len(results), 'passed': passed, 'failed': failed, 'skipped': 0,
        'unexpected_skips': 0, 'results': results, 'transitive_imports': imported,
        'events': EVENTS, 'failures': failures, 'exit': status,
        'verdict': 'PASS_REVIEW_REQUIRED' if status == 0 else 'FAIL',
        'note': 'Local scoped success is REVIEW REQUIRED, not full CI, source qualification or semantic acceptance.',
        **extra,
    }
    log('SUITE %s collected=%d passed=%d failed=%d skipped=0 failures=%d exit=%d' % (
        args.suite, len(results), passed, failed, len(failures), status))
    for failure in failures:
        log('FAILURE ' + failure)
    log('RUN_DIR ' + str(run_dir))
    write_once(run_dir / 'receipt.json', json.dumps(receipt, sort_keys=True, indent=1, allow_nan=False) + '\n')
    write_once(run_dir / 'log.txt', '\n'.join(log_lines) + '\n')
    return status


if __name__ == '__main__':
    sys.exit(main())
