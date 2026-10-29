"""Run SC179 real API checks offline; retain unique, identity-bound evidence."""
from collections import Counter
import argparse
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

BASE = '67ff9bcf34257698a41585bc2ad163171dc68259'
REPO = Path(__file__).resolve().parents[1]
METHODS = ['test_regression', 'test_compatibility', 'test_negative_control', 'test_preservation']


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args):
    return subprocess.check_output(['git', '-C', str(REPO), *args], text=True).strip()


class RecordedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ids = []
        self.subcases = []

    def startTest(self, test):
        self.ids.append(test.id())
        super().startTest(test)

    def addSubTest(self, test, subtest, error):
        self.subcases.append({'id': subtest.id(), 'passed': error is None})
        super().addSubTest(test, subtest, error)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-manifest', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--baseline', action='store_true', help='Unchanged-product red probe plus compatibility')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix='invocation-', dir=args.out))
    stdout, stderr = io.StringIO(), io.StringIO()
    record = {'schema': 'sc179.result/v1', 'base': BASE, 'argv': [sys.executable, *sys.argv],
              'cwd': str(Path.cwd()), 'interpreter': sys.executable, 'prefix': sys.prefix,
              'baseline': args.baseline, 'status': 'FAIL', 'output': str(output)}
    exit_code = 1
    sys.dont_write_bytecode = True
    with redirect_stdout(stdout), redirect_stderr(stderr):
        try:
            manifest_bytes = args.source_manifest.read_bytes()
            manifest = json.loads(manifest_bytes)
            root = REPO.parent
            if manifest.get('schema') != 'agentorange.source-manifest/v1':
                raise ValueError('manifest schema')
            if Path(manifest['write_root']).resolve() != root or Path(manifest['repo']).resolve() != REPO:
                raise ValueError('manifest write-root/repo mismatch')
            if manifest['head'] != BASE or git('rev-parse', BASE) != BASE:
                raise ValueError('staging base mismatch')
            if (REPO/'.venv').resolve() != Path(manifest['runtime']['repo_venv']).resolve():
                raise ValueError('venv manifest mismatch')
            if Path(sys.prefix).resolve() != (REPO/'.venv').resolve():
                raise ValueError('runner interpreter mismatch')
            scan = Path(manifest['runtime']['credential_scan_python3'])
            if not scan.is_file():
                raise ValueError('scan interpreter unavailable')
            record.update(head=git('rev-parse', 'HEAD'), manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
                          spec_sha256=digest(root/'ACCEPTANCE-SPEC.json'),
                          tracked_status=git('status', '--short', '--untracked-files=no'))
            case_map = json.loads((root/'ACCEPTANCE-CASE-MAP.json').read_text())
            record['case_map_sha256'] = digest(root/'ACCEPTANCE-CASE-MAP.json')
            test_path = REPO/'tests/unit/test_sc179_restore_inventory_preflight.py'
            fixture_path = REPO/'tests/fixtures/sc179-restore-inventory-preflight/constructors.py'
            record['source_hashes'] = {str(p.relative_to(REPO)): digest(p) for p in
                [test_path, fixture_path, Path(__file__), REPO/'src/skippercast/seafloor/state_cache.py']}
            spec = importlib.util.spec_from_file_location('sc179_checks', test_path)
            tests = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(tests)
            tests.CASE_OUTPUT = output/'fixtures'
            cls = tests.RestoreInventoryPreflightTests
            if args.baseline:
                if record['head'] != BASE or digest(REPO/'src/skippercast/seafloor/state_cache.py') != '26bec67e5d8c499a7a31128a812c1ccaba4c3ce7f5f6a7935ecdd263eaac47e4':
                    raise ValueError('baseline requires unchanged pinned product')
                class BaselineProbe(cls):
                    def test_regression(self):
                        self.assert_rejected_without_effects([
                            self.f.row('reference/run.json'),
                            self.f.row('reference/cells.json', sha256='bad')])
                suite = unittest.TestSuite([BaselineProbe('test_regression'), cls('test_compatibility')])
            else:
                suite = unittest.TestSuite(cls(method) for method in METHODS)
            result = unittest.TextTestRunner(stream=stderr, verbosity=2, resultclass=RecordedResult).run(suite)
            record.update(test_ids=result.ids, tests_run=result.testsRun, subcases=result.subcases,
                          subcase_count=len(result.subcases), failures=[{'id': t.id(), 'traceback': text} for t, text in result.failures],
                          errors=[{'id': t.id(), 'traceback': text} for t, text in result.errors],
                          skips=[{'id': t.id(), 'reason': text} for t, text in result.skipped],
                          events=tests.EVENTS, event_count=len(tests.EVENTS), imported_origins=tests.ORIGINS,
                          negative_control=tests.NEGATIVE)
            if args.baseline:
                expected = (result.testsRun == 2 and len(result.failures) == 1 and not result.errors and
                            not result.skipped and 'metadata preflight side effects' in result.failures[0][1])
                record['status'] = 'EXPECTED_RED' if expected else 'FAIL'
            else:
                executed = {row['method'] for row in tests.EVENTS}
                expected_events = Counter((method, case) for method, cases in case_map['events'].items() for case in cases)
                actual_events = Counter((row['method'], row['case']) for row in tests.EVENTS)
                record['missing_events'] = list((expected_events - actual_events).elements())
                record['extra_events'] = list((actual_events - expected_events).elements())
                if (result.wasSuccessful() and result.testsRun == 4 and not result.skipped and
                        executed == set(METHODS) and len(tests.NEGATIVE) == 1 and
                        actual_events == expected_events and len(result.subcases) == case_map['expected_subcases']):
                    record['status'] = 'PASS_REVIEW_REQUIRED'
                    exit_code = 0
            record['fixture_hashes'] = tests.snapshot(output/'fixtures')
            if args.source_manifest.read_bytes() != manifest_bytes:
                raise ValueError('staging manifest changed during run')
        except Exception as error:
            exit_code = 1
            import traceback
            traceback.print_exc()
            record['fatal'] = type(error).__name__ + ': ' + str(error)
            record['status'] = 'FAIL'
    (output/'stdout.log').write_text(stdout.getvalue())
    (output/'stderr.log').write_text(stderr.getvalue())
    record['exit_code'] = exit_code
    record['log_sha256'] = {name: digest(output/name) for name in ('stdout.log', 'stderr.log')}
    (output/'result.json').write_text(json.dumps(record, indent=2) + '\n')
    print(stderr.getvalue(), end='')
    print(json.dumps({'status': record['status'], 'exit_code': exit_code,
                      'tests': record.get('tests_run'), 'subcases': record.get('subcase_count'),
                      'events': record.get('event_count'), 'output': str(output)}))
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
