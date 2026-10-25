"""SC126 acceptance runner: offline unittest of the verified_file digest-declaration preflight.

Usage:
    python3 tools/run_sc126_asset_hash_preflight.py --phase candidate|baseline
        --source-manifest SOURCE-MANIFEST.json --out OUT_ROOT

Paths come from this file and the arguments. The runner puts this checkout's
src/ and root first on sys.path (the linked .venv has an editable install of a
different checkout), refuses network and subprocess entry points before the
product is imported, runs the four required test methods in process, and
writes result.json under a new unique child of --out. It never launches the
product CLI, downloads, or touches cache/live data.

Phases:
    baseline   io.py must still equal the pinned base blob. Expected: every
               regression subcase FAILS (as an assertion failure, not an error),
               every compatibility subcase passes.
    candidate  tracked tree clean, HEAD descends from the base, only admitted
               paths changed; all four methods and every subcase pass and the
               negative control proves detection plus a restored positive.
Exit 0 only when the phase expectation holds. Machine validity is REVIEW
REQUIRED, not scientific, source or shipping acceptance.
"""
import sys

sys.dont_write_bytecode = True

import argparse  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
import hashlib  # noqa: E402
import io as stdio  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
from pathlib import Path  # noqa: E402
import platform  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
PRODUCT = 'src/skippercast/seafloor/io.py'
TEST_FILE = 'tests/unit/test_sc126_asset_hash_preflight.py'
RUNNER = 'tools/run_sc126_asset_hash_preflight.py'
FIXTURES = 'tests/fixtures/sc126-asset-hash-preflight'
ALLOWED = {PRODUCT, TEST_FILE, RUNNER}
MODULE = 'tests.unit.test_sc126_asset_hash_preflight'
CASE = 'AssetHashPreflightTest'
METHODS = ('test_regression', 'test_compatibility', 'test_negative_control', 'test_preservation')
REGRESSION_CASES = (
    'null', 'bool_true', 'bool_false', 'integer', 'bytes_hex', 'bytearray_hex', 'list', 'dict',
    'object', 'empty', 'short_63', 'long_65', 'long_128', 'nonhex_last_g', 'nonhex_all_z',
    'hex_prefix_0x', 'non_ascii_digits', 'fullwidth_hex', 'leading_space', 'trailing_space',
    'internal_space', 'tab', 'trailing_newline', 'trailing_crlf', 'newline_in_64')
EXPECTED_SUBCASES = {
    'test_regression': sorted(f'case={c} fetch={f}' for c in REGRESSION_CASES for f in (True, False)),
    'test_compatibility': sorted(
        [f'case={c} fetch={f}' for c in ('lowercase', 'uppercase', 'mixed_case') for f in (True, False)]
        + [f'case={c}' for c in ('mismatch_lower', 'mismatch_upper', 'cache_miss_lower', 'cache_miss_upper')]),
    'test_negative_control': [],
    'test_preservation': sorted(f'case={c}' for c in (
        'accepted_cached_lower', 'accepted_cached_upper_fetch', 'rejected_list_container',
        'rejected_dict_container', 'rejected_existing_cache_short', 'rejected_missing_fetch')),
}


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def git(*args):
    done = subprocess.run(['git', '-C', str(REPO), *args], capture_output=True, check=False)
    return done.returncode, done.stdout.decode('utf-8', 'replace'), done.stderr.decode('utf-8', 'replace')


def input_hashes():
    names = [PRODUCT, TEST_FILE, RUNNER] + sorted(
        p.relative_to(REPO).as_posix() for p in (REPO / FIXTURES).rglob('*') if p.is_file())
    return {name: sha256_bytes((REPO / name).read_bytes()) for name in names}


def check_manifest(path, problems):
    try:
        manifest = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        problems.append(f'source manifest unreadable: {type(error).__name__}')
        return {}
    if manifest.get('schema') != 'agentorange.source-manifest/v1':
        problems.append('source manifest schema is not agentorange.source-manifest/v1')
    if Path(str(manifest.get('repo', ''))).resolve() != REPO:
        problems.append('source manifest repo is not this checkout')
    if Path(str(manifest.get('write_root', ''))).resolve() != REPO.parent:
        problems.append('source manifest write_root is not the parent of this checkout')
    head = manifest.get('head')
    if not (isinstance(head, str) and len(head) == 40 and all(c in '0123456789abcdef' for c in head)):
        problems.append('source manifest head is not a full commit id')
    if manifest.get('clean') is not True or not isinstance(manifest.get('runtime'), dict):
        problems.append('source manifest clean/runtime fields missing')
    return manifest


def git_identity(base, phase, problems):
    record = {}
    code, out, _ = git('rev-parse', 'HEAD')
    record['head'] = out.strip() if code == 0 else None
    code, out, _ = git('status', '--porcelain', '--untracked-files=all')
    record['status_porcelain'] = out.splitlines()
    code, out, _ = git('merge-base', '--is-ancestor', base, 'HEAD')
    record['base_is_ancestor'] = code == 0
    code, out, _ = git('diff', '--name-only', base, 'HEAD')
    record['committed_changes'] = out.splitlines()
    code, out, _ = git('show', f'{base}:{PRODUCT}')
    base_product = out.encode('utf-8') if code == 0 else None
    record['base_product_sha256'] = sha256_bytes(base_product) if base_product is not None else None
    record['work_product_sha256'] = sha256_bytes((REPO / PRODUCT).read_bytes())
    if not record['base_is_ancestor']:
        problems.append('pinned base is not an ancestor of HEAD')
    if phase == 'baseline':
        if record['work_product_sha256'] != record['base_product_sha256']:
            problems.append('baseline phase requires io.py equal to the pinned base blob')
    else:
        if record['status_porcelain']:
            problems.append('candidate phase requires a clean tree')
        extra = [n for n in record['committed_changes'] if n not in ALLOWED and not n.startswith(FIXTURES + '/')]
        if extra:
            problems.append(f'changes outside the admitted paths: {extra}')
    return record


class Sentinel:
    """Process-level refusal of network and subprocess entry points, installed before product import.

    A cold product import binds some of these as defaults (http.Session resolver),
    so restore() also rebinds every captured default/global back to the original.
    """

    def __init__(self):
        import socket
        self.calls, self.saved, self.refusers, self.rebound = {}, [], {}, []
        self.loaded = set(sys.modules)
        for owner, name in ((socket.socket, 'connect'), (socket, 'create_connection'),
                            (socket, 'getaddrinfo'), (subprocess, 'Popen'), (os, 'system')):
            label = f'{owner.__name__}.{name}'
            self.saved.append((owner, name, getattr(owner, name)))
            self.calls[label] = 0
            refuser = self._refuser(label)
            self.refusers[id(refuser)] = (refuser, getattr(owner, name))
            setattr(owner, name, refuser)

    def _refuser(self, label):
        def refused(*args, **kwargs):
            self.calls[label] += 1
            raise RuntimeError(f'sc126 runner refused {label}')
        return refused

    def _lookup(self, value):
        entry = self.refusers.get(id(value))
        return (True, entry[1]) if entry is not None and entry[0] is value else (False, None)

    def scanned(self):
        return {n for n in sys.modules if n not in self.loaded or n.split('.')[0] == 'skippercast'}

    def restore(self):
        for owner, name, value in reversed(self.saved):
            setattr(owner, name, value)
        tests = sys.modules.get(MODULE)
        if tests is not None:
            self.rebound = tests.import_captures(self.scanned(), self._lookup, apply=True)


def isolation_probe(originals, sentinel):
    """After restore: entry points, captured defaults and the http.Session resolver are original."""
    import socket
    from unittest import mock
    tests = sys.modules.get(MODULE)
    http = sys.modules.get('skippercast.http')
    record: dict = dict(entry_points_restored=all(getattr(o, n) is v for o, n, v in originals),
                        sentinel_rebound=sentinel.rebound)

    def leftover(value):
        return (isinstance(value, mock.NonCallableMock) or sentinel._lookup(value)[0], None)
    record['leftover_doubles'] = (tests.import_captures(sentinel.scanned(), leftover)
                                  if tests is not None else None)
    record['session_resolver_default_is_original_getaddrinfo'] = (
        http is not None and http.Session.__init__.__kwdefaults__['resolver'] is socket.getaddrinfo
        and socket.getaddrinfo is next(v for o, n, v in originals if n == 'getaddrinfo'))
    record['ok'] = (record['entry_points_restored'] and record['leftover_doubles'] == []
                    and record['session_resolver_default_is_original_getaddrinfo'])
    return record


class Recorder(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.tests, self.subtests = {}, []

    def _method(self, test):
        return test.id().rsplit('.', 1)[-1]

    def startTest(self, test):
        super().startTest(test)
        self.tests[self._method(test)] = 'running'

    def addSuccess(self, test):
        super().addSuccess(test)
        self.tests[self._method(test)] = 'pass'

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.tests[self._method(test)] = 'fail'

    def addError(self, test, err):
        super().addError(test, err)
        self.tests[self._method(test)] = 'error'

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.tests[self._method(test)] = 'skip'

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self.tests[self._method(test)] = 'expected_failure'

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self.tests[self._method(test)] = 'unexpected_success'

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        params = ' '.join(f'{k}={v}' for k, v in sorted(subtest.params.items()))
        if err is None:
            outcome, detail = 'pass', None
        else:
            outcome = 'fail' if issubclass(err[0], test.failureException) else 'error'
            detail = f'{err[0].__name__}: {err[1]}'
        self.subtests.append(dict(id=subtest.id(), method=self._method(test), params=params,
                                  outcome=outcome, detail=detail))


def run_tests():
    module = __import__(MODULE, fromlist=['*'])
    suite = unittest.TestSuite(getattr(module, CASE)(name) for name in METHODS)
    recorder = Recorder()
    suite.run(recorder)
    io_module = sys.modules.get('skippercast.seafloor.io')
    for method in recorder.tests:   # a method whose only failures were subtests ends 'running'
        if recorder.tests[method] == 'running':
            failed = any(s['method'] == method and s['outcome'] != 'pass' for s in recorder.subtests)
            recorder.tests[method] = 'fail_in_subtests' if failed else 'pass'
    origins = {name: getattr(sys.modules.get(name), '__file__', None)
               for name in ('skippercast', 'skippercast.seafloor.io', 'skippercast.http', MODULE)}
    return recorder, dict(module.NEGATIVE_CONTROL_EVIDENCE), origins, io_module


def isolated_pass(label):
    """One guarded in-process suite run followed by restore and the peer isolation probe."""
    preimported = 'skippercast.http' in sys.modules
    sentinel = Sentinel()
    try:
        outcome = run_tests()
    finally:
        sentinel.restore()
    probe = isolation_probe(sentinel.saved, sentinel)
    tests = sys.modules.get(MODULE)
    probe.update(label=label, http_preimported=preimported,
                 test_cleanup_rebound=list(getattr(tests, 'ISOLATION_EVIDENCE', [])),
                 sentinel_calls=dict(sentinel.calls))
    if tests is not None:
        tests.ISOLATION_EVIDENCE.clear()
    return outcome, sentinel, probe


def judge(phase, recorder, evidence, origins, problems):
    for name, origin in origins.items():
        if origin is None or not Path(origin).resolve().is_relative_to(REPO):
            problems.append(f'{name} was not imported from this checkout')
    by_method = {}
    for row in recorder.subtests:
        by_method.setdefault(row['method'], {})[row['params']] = row['outcome']
    if recorder.skipped or recorder.expectedFailures or recorder.unexpectedSuccesses:
        problems.append('skips or expected-failure markers are not admitted')
    if recorder.testsRun != len(METHODS):
        problems.append(f'testsRun {recorder.testsRun} != {len(METHODS)}')
    for method, expected in EXPECTED_SUBCASES.items():
        actual = sorted(by_method.get(method, {}))
        if actual != expected:
            problems.append(f'{method} subcases differ from the frozen list')
    if phase == 'candidate':
        if recorder.failures or recorder.errors:
            problems.append('failures or errors in candidate phase')
        for method in METHODS:
            if recorder.tests.get(method) != 'pass':
                problems.append(f'{method} did not pass')
        if any(row['outcome'] != 'pass' for row in recorder.subtests):
            problems.append('a subcase did not pass')
        if not (evidence.get('detected_first_destination_access') is True
                and evidence.get('inner_failure_class') == 'DestinationAccessed'
                and evidence.get('hashes_while_disabled') == 0
                and evidence.get('restored_positive_passed') is True
                and evidence.get('restored_deciding_passed') is True):
            problems.append('negative control did not prove detection and a restored positive')
    else:
        regression = by_method.get('test_regression', {})
        if not regression or any(v != 'fail' for v in regression.values()):
            problems.append('baseline: every regression subcase must fail as an assertion failure')
        compatibility = by_method.get('test_compatibility', {})
        if not compatibility or any(v != 'pass' for v in compatibility.values()):
            problems.append('baseline: every compatibility subcase must pass')
    return by_method


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--phase', choices=('baseline', 'candidate'), required=True)
    parser.add_argument('--source-manifest', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    started = datetime.now(timezone.utc)
    out = Path(args.out).resolve() / f'{args.phase}-{started.strftime("%Y%m%dT%H%M%S%fZ")}-{os.getpid()}'
    out.mkdir(parents=True, exist_ok=False)
    scratch = out / 'tmp'
    scratch.mkdir()
    problems = []
    manifest = check_manifest(args.source_manifest, problems)
    base = manifest.get('head', '')
    identity = git_identity(base, args.phase, problems) if base else {}
    hashes_before = input_hashes()
    for entry in (str(REPO), str(REPO / 'src')):
        if entry in sys.path:
            sys.path.remove(entry)
        sys.path.insert(0, entry)
    tempfile.tempdir = str(scratch)
    log = stdio.StringIO()
    (recorder, evidence, origins, io_module), sentinel, cold = isolated_pass('cold_import')
    (repeat, _, _, _), repeat_sentinel, warm = isolated_pass('preimported')
    for test, trace in recorder.failures + recorder.errors:
        log.write(f'== {test.id()}\n{trace}\n')
    for test, trace in repeat.failures + repeat.errors:
        log.write(f'== preimported {test.id()}\n{trace}\n')
    by_method = judge(args.phase, recorder, evidence, origins, problems)
    isolation = dict(cold_import=cold, preimported=warm,
                     preimported_tests_run=repeat.testsRun, preimported_failures=len(repeat.failures),
                     preimported_errors=len(repeat.errors), preimported_skipped=len(repeat.skipped),
                     preimported_subtests=len(repeat.subtests),
                     preimported_subtests_passed=sum(1 for s in repeat.subtests if s['outcome'] == 'pass'))
    if cold['http_preimported'] or not warm['http_preimported']:
        problems.append('isolation: expected a cold first pass and a preimported second pass')
    if not (cold['ok'] and warm['ok']):
        problems.append('isolation: a sentinel/double stayed bound after restore')
    if args.phase == 'candidate':
        if not any(row['rebound'] for row in cold['test_cleanup_rebound']):
            problems.append('isolation: cold pass did not exercise the import-capture rebind')
        if (repeat.testsRun != len(METHODS) or repeat.failures or repeat.errors or repeat.skipped
                or isolation['preimported_subtests_passed'] != len(recorder.subtests)):
            problems.append('isolation: preimported second pass did not fully pass')
    if any(sentinel.calls.values()) or any(repeat_sentinel.calls.values()):
        problems.append(f'runner sentinel saw unapproved activity: {sentinel.calls} {repeat_sentinel.calls}')
    hashes_after = input_hashes()
    if hashes_after != hashes_before:
        problems.append('inputs changed during the run')
    leftovers = sorted(p.relative_to(scratch).as_posix() for p in scratch.rglob('*'))
    if leftovers:
        problems.append('test temporary files were left behind')
    (out / 'failures.log').write_text(log.getvalue(), encoding='utf-8')
    result = dict(
        schema='skippercast.sc126-asset-hash-preflight.result/v1',
        phase=args.phase, verdict='PASS_REVIEW_REQUIRED' if not problems else 'FAIL',
        problems=problems, started_utc=started.isoformat(),
        finished_utc=datetime.now(timezone.utc).isoformat(),
        argv=sys.argv, cwd=os.getcwd(), interpreter=sys.executable, python=platform.python_version(),
        dont_write_bytecode=sys.dont_write_bytecode, module_origins=origins,
        source_manifest=dict(path=str(Path(args.source_manifest).resolve()),
                             sha256=sha256_bytes(Path(args.source_manifest).read_bytes())),
        base=base, git=identity, input_sha256=hashes_after,
        helper_present=hasattr(io_module, '_require_asset_sha256_declaration') if io_module else None,
        tests_run=recorder.testsRun, failures=len(recorder.failures), errors=len(recorder.errors),
        skipped=len(recorder.skipped), methods=recorder.tests,
        subtest_count=len(recorder.subtests),
        subtest_outcomes={m: {o: sum(1 for v in rows.values() if v == o) for o in sorted(set(rows.values()))}
                          for m, rows in by_method.items()},
        subtests=recorder.subtests, negative_control=evidence, sentinel_calls=sentinel.calls,
        isolation=isolation,
        output_root=str(out), failures_log_sha256=sha256_bytes((out / 'failures.log').read_bytes()))
    (out / 'result.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(f'SC126 {args.phase}: {result["verdict"]}; tests_run={recorder.testsRun} '
          f'failures={len(recorder.failures)} errors={len(recorder.errors)} skipped={len(recorder.skipped)} '
          f'subtests={len(recorder.subtests)} outcomes={json.dumps(result["subtest_outcomes"], sort_keys=True)}')
    print(f'methods={json.dumps(recorder.tests, sort_keys=True)}')
    print(f'negative_control={json.dumps(evidence, sort_keys=True)}')
    print(f'isolation cold_import ok={cold["ok"]} preimported ok={warm["ok"]} '
          f'test_cleanup_rebound={json.dumps(cold["test_cleanup_rebound"])} '
          f'sentinel_rebound={json.dumps(cold["sentinel_rebound"])} '
          f'preimported tests_run={repeat.testsRun} subtests_passed={isolation["preimported_subtests_passed"]}')
    print(f'head={identity.get("head")} base={base}')
    print(f'result={out / "result.json"} sha256={sha256_bytes((out / "result.json").read_bytes())}')
    for problem in problems:
        print(f'PROBLEM: {problem}', file=sys.stderr)
    return 0 if not problems else 1


if __name__ == '__main__':
    raise SystemExit(main())
