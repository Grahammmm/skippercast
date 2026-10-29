#!/usr/bin/env python3
"""Offline, isolated acceptance runner for the SC84 rollout batch-count card.

Usage: run_sc84_rollout_count.py --suite {regression,compatibility,negative-control}
       --source-manifest <operator SOURCE-MANIFEST.json> --out <output prefix>

Before any product or test module is imported this runner disables bytecode writes,
derives the repo/src import paths from its own location, creates a fresh unique run
directory below --out, redirects temporary files there, points
skippercast.paths.repo_root at a synthetic tree inside the run directory, and installs
a sys.addaudithook guard that refuses network connections, child processes and any
filesystem write outside the run directory. The guard is defense in depth for this
offline test, not a hostile-code sandbox.

Every invocation writes receipt.json, stdout.txt, stderr.txt and evidence.json in its
run directory. Counts come from execution. A skip, failure, error, guard denial or
missing evidence makes the exit status nonzero.
"""
import os
import sys

sys.dont_write_bytecode = True
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'

import argparse  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
from pathlib import Path  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
import unittest  # noqa: E402

SCRIPT = Path(__file__).resolve()
REPO = SCRIPT.parents[1]
CANDIDATE = REPO.parent
BASE = 'a1f648632e64561d82dcbeb20d9bda19f812560a'
MANIFEST_SCHEMA = 'agentorange.source-manifest/v1'
# The operator full-suite interpreter lives beside the candidates directory.
SCAN_PYTHON = CANDIDATE.parent.parent/'tools/venv-fullsuite/bin/python3'
FIXTURE_DIR = REPO/'tests/fixtures/sc84-rollout-count'
CHANGED = ('src/skippercast/seafloor/rollout.py', 'tests/gis/test_sc84_rollout_count.py',
           'tests/fixtures/sc84-rollout-count/fixture.json', 'tools/run_sc84_rollout_count.py')
ORIGINAL_SELECTOR = ('tests.gis.test_seafloor_rollout.RolloutTests.'
                     'test_plan_uses_reviewed_windows_without_counting_envelopes_as_coverage')
DENY_EVENTS = {'socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname', 'socket.sendto',
               'socket.sendmsg', 'socket.bind', 'subprocess.Popen', 'os.system', 'os.exec',
               'os.posix_spawn', 'os.spawn', 'os.fork', 'os.forkpty', 'os.startfile',
               'urllib.Request', 'http.client.connect', 'ftplib.connect', 'smtplib.connect'}
# Filesystem-changing audit events: (path argument index, dir_fd argument index or None).
PATH_EVENTS = {'os.remove': ((0, 1),), 'os.rmdir': ((0, 1),), 'os.mkdir': ((0, 2),),
               'os.rename': ((0, 2), (1, 3)), 'os.replace': ((0, 2), (1, 3)),
               'os.symlink': ((1, 2),), 'os.link': ((1, 3),), 'os.chmod': ((0, 2),),
               'os.chown': ((0, 3),), 'os.truncate': ((0, None),), 'os.utime': ((0, 3),),
               'shutil.rmtree': ((0, 1),), 'shutil.copyfile': ((1, None),), 'shutil.move': ((1, None),)}
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC


def digest_bytes(data):
    return hashlib.sha256(data).hexdigest()


def digest(path):
    return digest_bytes(Path(path).read_bytes())


def git_head(repo):
    """Resolve HEAD from the git directory without starting a child process."""
    git = repo/'.git'
    if git.is_file():
        git = (repo/git.read_text().split(':', 1)[1].strip()).resolve()
    head = (git/'HEAD').read_text().strip()
    if not head.startswith('ref: '):
        return head
    ref = head[5:]
    loose = git/ref
    if loose.is_file():
        return loose.read_text().strip()
    common = git/'commondir'
    root = (git/common.read_text().strip()).resolve() if common.is_file() else git
    if (root/ref).is_file():
        return (root/ref).read_text().strip()
    for line in (root/'packed-refs').read_text().splitlines():
        if line.endswith(' '+ref):
            return line.split()[0]
    raise ValueError('HEAD reference not found')


class Tee:
    def __init__(self, stream, path):
        self.stream, self.file = stream, open(path, 'w', encoding='utf-8')

    def write(self, text):
        self.stream.write(text)
        self.file.write(text)
        return len(text)

    def flush(self):
        self.stream.flush()
        self.file.flush()

    def close(self):
        self.file.close()


class Guard:
    """Audit-hook policy: writes only below run_root; no network or child process."""

    def __init__(self, run_root):
        self.run_root = Path(run_root).resolve()
        self.active = False
        self.denied, self.writes, self.reads, self.relative_reads = [], [], [], []

    @staticmethod
    def _path(args, index, dir_fd_index=None):
        """Absolute real path of a path argument, honoring a dir_fd; None for a bare descriptor."""
        value = args[index] if index < len(args) else None
        if isinstance(value, int) or value is None:
            return None
        path = os.fsdecode(value)
        dir_fd = args[dir_fd_index] if dir_fd_index is not None and dir_fd_index < len(args) else None
        if isinstance(dir_fd, int) and not os.path.isabs(path):
            path = os.path.join(os.readlink(f'/proc/self/fd/{dir_fd}'), path)
        return Path(os.path.realpath(os.path.abspath(path)))

    def _inside(self, path):
        return path == self.run_root or path.is_relative_to(self.run_root)

    @staticmethod
    def _writing(args):
        mode, flags = args[1], args[2] or 0
        return (isinstance(mode, str) and any(c in mode for c in 'wax+')) or bool(flags & WRITE_FLAGS)

    def decide(self, event, args):
        """Return None to allow, or a reason string to deny. Performs no I/O beyond path resolution."""
        if event in DENY_EVENTS:
            return 'network or child process refused'
        if event == 'open':
            path = self._path(args, 0)
            if path is not None and self._writing(args) and not self._inside(path):
                return 'write outside run root refused'
            return None
        for index, dir_fd in PATH_EVENTS.get(event, ()):
            path = self._path(args, index, dir_fd)
            if path is not None and not self._inside(path):
                return 'filesystem change outside run root refused'
        return None

    def hook(self, event, args):
        if not self.active:
            return
        reason = self.decide(event, args)
        if reason:
            self.denied.append({'event': event, 'reason': reason})
            raise PermissionError(f'SC84 guard: {reason} ({event})')
        if event == 'open':
            raw = args[0]
            if isinstance(raw, (str, bytes)) and not os.path.isabs(os.fsdecode(raw)) and not self._writing(args):
                # The open event carries no dir_fd; descriptor-relative traversal (shutil.rmtree of
                # a temporary tree) cannot be resolved here, so it is recorded separately.
                self.relative_reads.append(os.fsdecode(raw))
                return
            path = self._path(args, 0)
            if path is not None:
                (self.writes if self._writing(args) else self.reads).append(path)
        else:
            for index, dir_fd in PATH_EVENTS.get(event, ()):
                path = self._path(args, index, dir_fd)
                if path is not None:
                    self.writes.append(path)


class RecordingResult(unittest.TextTestResult):
    def __init__(self, *args, classes=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.classes = classes or {}
        self.records, self.subtests, self.failed_parents = [], [], set()

    def _record(self, test, outcome, detail=None):
        method = test.id().rsplit('.', 1)[-1]
        self.records.append({'id': test.id(), 'assertion_class': self.classes.get(method, 'unclassified'),
                             'outcome': outcome, **({'detail': detail} if detail else {})})

    def addSuccess(self, test):
        super().addSuccess(test)
        self._record(test, 'pass')

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._record(test, 'fail', self._exc_info_to_string(err, test)[-2000:])

    def addError(self, test, err):
        super().addError(test, err)
        self._record(test, 'error', self._exc_info_to_string(err, test)[-2000:])

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._record(test, 'skip', reason)

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self._record(test, 'expected-failure')

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self._record(test, 'unexpected-success')

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is None:
            outcome = 'pass'
        elif issubclass(err[0], test.failureException):
            outcome = 'fail'
        else:
            outcome = 'error'
        self.subtests.append({'id': subtest.id(), 'outcome': outcome,
                              **({'exception': err[0].__name__, 'message': str(err[1])[:500]} if err else {})})
        if err is not None and test.id() not in self.failed_parents:
            # unittest reports no addSuccess/addFailure for a test whose subtest failed.
            self.failed_parents.add(test.id())
            self._record(test, outcome, f'subtest {subtest.id()}: '+self._exc_info_to_string(err, test)[-2000:])


def run_tests(tests, classes, label):
    print(f'== {label}')
    suite = unittest.TestSuite(tests)
    runner = unittest.TextTestRunner(stream=sys.stdout, verbosity=2,
                                     resultclass=lambda *a, **k: RecordingResult(*a, classes=classes, **k))
    result = runner.run(suite)
    return {'label': label, 'tests_run': result.testsRun, 'failures': len(result.failures),
            'errors': len(result.errors), 'skips': len(result.skipped),
            'expected_failures': len(result.expectedFailures),
            'unexpected_successes': len(result.unexpectedSuccesses),
            'successful': result.wasSuccessful() and not result.skipped,
            'tests': result.records, 'subtests': result.subtests}


def check(isolation, name, condition, detail=None):
    isolation.append({'assertion': name, 'outcome': 'pass' if condition else 'fail',
                      **({'detail': detail} if detail is not None else {})})


def preflight_manifest(path):
    manifest = json.loads(Path(path).read_text())
    runtime = manifest.get('runtime') or {}
    problems = []
    if manifest.get('schema') != MANIFEST_SCHEMA:
        problems.append('schema')
    if manifest.get('write_root') != str(CANDIDATE):
        problems.append('write_root')
    if manifest.get('repo') != str(REPO):
        problems.append('repo')
    if manifest.get('head') != BASE:
        problems.append('head')
    venv = REPO/'.venv'
    if not runtime.get('repo_venv') or os.path.realpath(venv) != os.path.realpath(runtime['repo_venv']):
        problems.append('runtime.repo_venv')
    if runtime.get('credential_scan_python3') != str(SCAN_PYTHON):
        problems.append('runtime.credential_scan_python3')
    return manifest, problems


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--suite', choices=('regression', 'compatibility', 'negative-control'), required=True)
    parser.add_argument('--source-manifest', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()

    manifest_path = Path(args.source_manifest).resolve()
    manifest, problems = preflight_manifest(manifest_path)
    if problems:
        print('source manifest preflight failed: '+', '.join(problems), file=sys.stderr)
        return 2
    manifest_sha = digest(manifest_path)

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    run_root = out/f'run-{time.time_ns()}-{os.getpid()}'
    run_root.mkdir(exist_ok=False)
    tmp = run_root/'tmp'
    tmp.mkdir()
    synthetic = run_root/'synthetic-repo'
    synthetic.mkdir()
    for name in ('TMPDIR', 'TEMP', 'TMP'):
        os.environ[name] = str(tmp)
    tempfile.tempdir = str(tmp)
    removed_env = sorted(k for k in ('SKIPPERCAST_SOURCE_SCOPE', 'SKIPPERCAST_ROOT') if k in os.environ)
    for name in removed_env:
        del os.environ[name]

    stdout, stderr = Tee(sys.stdout, run_root/'stdout.txt'), Tee(sys.stderr, run_root/'stderr.txt')
    sys.stdout, sys.stderr = stdout, stderr
    isolation = []
    receipt = {'card': 'skippercast-sc84-rollout-count', 'suite': args.suite, 'argv': sys.argv,
               'cwd': os.getcwd(), 'interpreter': sys.executable, 'python_version': sys.version,
               'admitted_base': BASE, 'head': git_head(REPO), 'source_manifest': str(manifest_path),
               'source_manifest_sha256': manifest_sha, 'run_root': str(run_root),
               'tmpdir': str(tmp), 'removed_environment': removed_env,
               'fixture_root_redirection': {'skippercast.paths.repo_root': str(synthetic),
                                            'tempfile.tempdir': str(tmp)},
               'review_status': 'REVIEW REQUIRED: machine-valid output is not semantic acceptance'}
    exit_code = 1
    try:
        check(isolation, 'candidate-root binding', CANDIDATE == Path(manifest['write_root'])
              and REPO == Path(manifest['repo']), str(CANDIDATE))
        check(isolation, 'unique output root', run_root.parent == out and run_root.is_dir()
              and not run_root.is_relative_to(REPO/'tests/fixtures'), str(run_root))
        fixture_before = {p.relative_to(REPO).as_posix(): digest(p) for p in sorted(FIXTURE_DIR.rglob('*')) if p.is_file()}
        changed_before = {name: digest(REPO/name) for name in CHANGED}
        sentinel_path = FIXTURE_DIR/'fixture.json'
        sentinel_before = digest(sentinel_path) if sentinel_path.is_file() else None
        receipt['sentinel'] = {'path': sentinel_path.relative_to(REPO).as_posix(), 'sha256_before': sentinel_before}

        # Guards precede every product/test import.
        product_preloaded = sorted(m for m in sys.modules if m == 'skippercast' or m.startswith(('skippercast.', 'tests.')))
        guard = Guard(run_root)
        sys.addaudithook(guard.hook)
        guard.active = True
        check(isolation, 'pre-import guard installed before product imports', not product_preloaded, product_preloaded)
        allowed_probe = guard.decide('open', (str(synthetic/'probe.json'), 'w', 0))
        # The denied event names the authored, read-only fixture.json (outside run_root). It is only
        # passed to Guard.decide; no real write or open of it is attempted. Its bytes are hashed
        # before the event and again after every test, and the two hashes must match.
        denied_target = sentinel_path
        denied_probe = guard.decide('open', (str(denied_target), 'w', 0))
        network_probe = guard.decide('socket.connect', (None, ('192.0.2.1', 9)))
        child_probe = guard.decide('subprocess.Popen', ('true', ['true'], None, None))
        check(isolation, 'allowed synthetic path event', allowed_probe is None, str(synthetic/'probe.json'))
        check(isolation, 'inert denied sentinel event', denied_probe is not None and sentinel_before is not None
              and not denied_target.is_relative_to(run_root),
              {'target': str(denied_target), 'decision': denied_probe, 'sha256_before': sentinel_before})
        check(isolation, 'inert network and child events denied', network_probe is not None and child_probe is not None,
              {'network': network_probe, 'child': child_probe})

        sys.path[:0] = [str(REPO/'src'), str(REPO)]
        from skippercast import paths
        paths.repo_root = lambda: synthetic
        from skippercast.platform import contracts
        from skippercast.seafloor import rollout
        check(isolation, 'repo_root redirected before contracts import', contracts.REPO == synthetic
              and rollout.plan.__defaults__[0] == synthetic, str(contracts.REPO))
        check(isolation, 'product imported from candidate src',
              Path(rollout.__file__).resolve() == (REPO/'src/skippercast/seafloor/rollout.py').resolve(), rollout.__file__)
        from tests.gis import test_sc84_rollout_count as cases
        classes = dict(cases.ASSERTION_CLASSES)
        load = unittest.defaultTestLoader

        runs, negative = [], None
        if args.suite == 'regression':
            runs.append(run_tests(load.loadTestsFromTestCase(cases.RolloutCountTests), classes, 'regression'))
        elif args.suite == 'compatibility':
            classes['test_plan_uses_reviewed_windows_without_counting_envelopes_as_coverage'] = 'compatibility-original'
            runs.append(run_tests([load.loadTestsFromName(ORIGINAL_SELECTOR)], classes, 'original-selector'))
            runs.append(run_tests(load.loadTestsFromTestCase(cases.CompatibilityTests), classes, 'compatibility'))
        else:
            deciding = 'test_bool_count_refused_before_ledger_read'
            control = 'test_one_count_selects_top_reach'
            original = rollout._require_count
            rollout._require_count = lambda max_new: None  # old interval-only check, in memory only
            try:
                mutant = run_tests([cases.RolloutCountTests(deciding)], classes, 'mutant-deciding')
                mutant_control = run_tests([cases.RolloutCountTests(control)], classes, 'mutant-control')
            finally:
                rollout._require_count = original
            restored = run_tests([cases.RolloutCountTests(deciding), cases.RolloutCountTests(control)],
                                 classes, 'restored')
            deciding_failures = [s for s in mutant['subtests'] if s['outcome'] != 'pass']
            mutant_detected = (mutant['tests_run'] == 1 and mutant['errors'] == 0
                               and mutant['failures'] == len(deciding_failures) == 2
                               and all(s['outcome'] == 'fail' and s['exception'] == 'AssertionError'
                                       and 'ValueError not raised' in s['message']
                                       for s in deciding_failures))
            positive_passed = mutant_control['successful'] and mutant_control['tests_run'] == 1 and restored['successful']
            negative = {'mutation': 'rollout._require_count replaced in memory by a no-op; the '
                                    'interval-only bound in plan is the old behavior',
                        'restored_identity': rollout._require_count is original,
                        'mutant_detected': mutant_detected, 'positive_passed': positive_passed,
                        'deciding_failures': deciding_failures}
            runs += [restored]
            receipt['negative_control'] = negative
            receipt['mutant_runs'] = [mutant, mutant_control]
            check(isolation, 'negative control detected mutant and restored control passed',
                  mutant_detected and positive_passed and negative['restored_identity'])

        guard.active = False
        fixture_after = {p.relative_to(REPO).as_posix(): digest(p) for p in sorted(FIXTURE_DIR.rglob('*')) if p.is_file()}
        evidence = list(cases.EVIDENCE)
        check(isolation, 'unchanged authored fixture bytes', fixture_before == fixture_after and bool(fixture_after), fixture_after)
        sentinel_after = digest(sentinel_path) if sentinel_path.is_file() else None
        receipt['sentinel']['sha256_after'] = sentinel_after
        check(isolation, 'denied sentinel bytes preserved before and after', sentinel_before is not None
              and sentinel_after == sentinel_before,
              {'path': str(sentinel_path), 'sha256_before': sentinel_before, 'sha256_after': sentinel_after})
        check(isolation, 'changed source files unchanged during run',
              changed_before == {name: digest(REPO/name) for name in CHANGED})
        check(isolation, 'synthetic trees unchanged by every test', bool(evidence)
              and all(e['tree_unchanged'] and e['fixture_before'] == e['fixture_after'] for e in evidence))
        outside_writes = sorted({str(w) for w in guard.writes if not w.is_relative_to(run_root)})
        check(isolation, 'all writes inside run root', not outside_writes, outside_writes)
        repo_real = Path(os.path.realpath(REPO))
        data_reads = sorted({str(r) for r in guard.reads if r.is_relative_to(repo_real)
                             and r.suffix not in ('.py', '.pyc')})
        stray_reads = [r for r in data_reads if not Path(r).is_relative_to(FIXTURE_DIR)]
        check(isolation, 'repository data reads limited to authored fixture', not stray_reads,
              {'fixture_reads': data_reads, 'stray': stray_reads})
        relative = sorted(set(guard.relative_reads))
        check(isolation, 'descriptor-relative reads are single path components', all(
              name and os.sep not in name and name not in ('.', '..') for name in relative), relative)
        synthetic_reads = sorted({str(r) for r in guard.reads if r.is_relative_to(run_root)})
        check(isolation, 'fixture reads observed inside synthetic tree', bool(synthetic_reads), len(synthetic_reads))
        check(isolation, 'no unexpected guard denial', not guard.denied, guard.denied)

        tests_run = sum(r['tests_run'] for r in runs)
        receipt.update({'runs': runs, 'tests_run': tests_run,
                        'failures': sum(r['failures'] for r in runs), 'errors': sum(r['errors'] for r in runs),
                        'skips': sum(r['skips'] for r in runs), 'isolation': isolation,
                        'fixture_hashes': fixture_after, 'changed_file_hashes': changed_before,
                        'write_count': len(guard.writes), 'read_count': len(guard.reads)})
        (run_root/'evidence.json').write_text(json.dumps(evidence, indent=2)+'\n')
        ok = (tests_run > 0 and all(r['successful'] for r in runs)
              and all(i['outcome'] == 'pass' for i in isolation))
        if negative is not None:
            ok = ok and negative['mutant_detected'] and negative['positive_passed']
        exit_code = 0 if ok else 1
    except Exception as error:  # recorded, never treated as success
        import traceback
        traceback.print_exc()
        receipt['exception'] = f'{type(error).__name__}: {error}'
        receipt['isolation'] = isolation
        exit_code = 1
    finally:
        receipt['exit'] = exit_code
        print(f'SC84 {args.suite}: exit {exit_code}; run root {run_root}')
        sys.stdout, sys.stderr = stdout.stream, stderr.stream
        stdout.close()
        stderr.close()
        receipt['output_sha256'] = {name: digest(run_root/name) for name in ('stdout.txt', 'stderr.txt')}
        if (run_root/'evidence.json').exists():
            receipt['output_sha256']['evidence.json'] = digest(run_root/'evidence.json')
        data = (json.dumps(receipt, indent=2)+'\n').encode()
        (run_root/'receipt.json').write_bytes(data)
        (run_root/'receipt.sha256').write_text(digest_bytes(data)+'  receipt.json\n')
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
