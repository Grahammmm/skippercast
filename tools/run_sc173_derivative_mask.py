"""Run SC173 focused acceptance with a pinned stage and retained evidence."""
import argparse
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import cast
import unittest

BASE = '67ff9bcf34257698a41585bc2ad163171dc68259'
REPO = Path(__file__).resolve().parents[1]
ROOT = REPO.parent
PRODUCT = 'src/skippercast/seafloor/terrain.py'
TESTS = 'tests/gis/test_sc173_derivative_mask.py'
SCOPED = [PRODUCT, TESTS,
          'tests/fixtures/sc173-derivative-mask/constructors.py',
          'tests/fixtures/sc173-derivative-mask/pinned_terrain.py.txt', 'tools/run_sc173_derivative_mask.py']


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args):
    return subprocess.run(['git', '-C', str(REPO), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


class RecordingResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.actual_ids = []

    def startTest(self, test):
        self.actual_ids.append(test.id())
        super().startTest(test)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-manifest', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--baseline', action='store_true', help='Retain pre-change red regression plus valid compatibility')
    args = parser.parse_args()
    manifest_path = args.source_manifest.resolve()
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('schema') != 'agentorange.source-manifest/v1':
        raise ValueError('Invalid stage schema')
    if manifest_path != ROOT / 'SOURCE-MANIFEST.json' or Path(manifest['write_root']).resolve() != ROOT:
        raise ValueError('Invalid stage write root')
    if Path(manifest['repo']).resolve() != REPO or manifest['head'] != BASE:
        raise ValueError('Moved stage repo/base')
    if Path(manifest['runtime']['repo_venv']).resolve() != (REPO / '.venv').resolve():
        raise ValueError('Wrong resolved repo venv')
    if Path(sys.prefix).resolve() != (REPO / '.venv').resolve():
        raise ValueError('Wrong runner interpreter')
    expected_scan = ROOT.parents[1] / 'tools/venv-fullsuite/bin/python3'
    if Path(manifest['runtime']['credential_scan_python3']) != expected_scan or not expected_scan.is_file():
        raise ValueError('Wrong credential scan interpreter')
    head = git('rev-parse', 'HEAD')
    if git('rev-parse', f'{BASE}^{{tree}}') != manifest['tree']:
        raise ValueError('Moved staged tree pin')
    git('merge-base', '--is-ancestor', BASE, head)
    if args.baseline and head != BASE:
        raise ValueError('Baseline mode requires unchanged staged head')
    if args.baseline and digest(REPO / PRODUCT) != 'd93d8a65a350927451eff74ccf0c38cd1c9a6bad811417c42374b61e02ce44e7':
        raise ValueError('Baseline product bytes changed')
    spec_path = ROOT / 'ACCEPTANCE-SPEC.json'
    spec = json.loads(spec_path.read_text())
    if spec['base'] != BASE:
        raise ValueError('Moved acceptance pin')
    if not args.out.resolve().is_relative_to(ROOT / 'out'):
        raise ValueError('Runner output must stay under candidate/out')
    args.out.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix='invocation-', dir=args.out))
    receipt = {
        'schema': 'sc173.result/v1', 'mode': 'baseline-red' if args.baseline else 'acceptance',
        'argv': [sys.executable, *sys.argv], 'cwd': str(Path.cwd()),
        'interpreter': sys.executable, 'resolved_prefix': str(Path(sys.prefix).resolve()),
        'base': BASE, 'head': head, 'staging_manifest_sha256': digest(manifest_path),
        'brief_spec_sha256': digest(spec_path),
        'scoped_file_sha256': {name: digest(REPO / name) for name in SCOPED},
        'credential_scan_argv': [str(expected_scan), str(REPO / 'scripts/check_repository.py')],
        'tracked_tree_status': git('status', '--porcelain', '--untracked-files=no'),
    }
    stdout, stderr = io.StringIO(), io.StringIO()
    old_bytecode = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        # The test imports ROOT from tests._support; the runner may set sys.path itself.
        if str(REPO) not in sys.path:
            sys.path.insert(0, str(REPO))
        location = importlib.util.spec_from_file_location('sc173_tests', REPO / TESTS)
        if location is None or location.loader is None:
            raise ValueError('Missing test loader')
        module = importlib.util.module_from_spec(location)
        location.loader.exec_module(module)
        if spec['requirements'] != module.METHOD_CASES:
            raise ValueError('Frozen requirements/test mapping differs')
        module.DerivativeMaskTests.evidence_root = str(output)
        names = ['test_regression', 'test_compatibility'] if args.baseline else list(module.METHOD_CASES)
        suite = unittest.TestSuite(module.DerivativeMaskTests(name) for name in names)
        if suite.countTestCases() != len(names) or not names:
            raise ValueError('Empty or incomplete required collection')
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = cast(RecordingResult, unittest.TextTestRunner(
                stream=stderr, verbosity=2, resultclass=RecordingResult).run(suite))
        records = module.DerivativeMaskTests.records
        expected = {(name, case) for name in names for case in module.METHOD_CASES[name]}
        actual = [(record['method'], record['case']) for record in records]
        complete = len(actual) == len(set(actual)) and set(actual) == expected
        passed = result.wasSuccessful() and not result.skipped and result.testsRun == len(names) and complete
        if not args.baseline and receipt['tracked_tree_status']:
            passed = False
        receipt.update(
            tests_run=result.testsRun, actual_ids=result.actual_ids, subcases=records,
            subcase_count=len(records), complete_subcases=complete,
            failures=[{'id': test.id(), 'traceback': text} for test, text in result.failures],
            errors=[{'id': test.id(), 'traceback': text} for test, text in result.errors],
            skips=[{'id': test.id(), 'reason': reason} for test, reason in result.skipped],
            imported_module_origins=module.DerivativeMaskTests.origins,
            baseline_module_sha256=digest(module.DerivativeMaskTests.baseline_path),
            fixture_sha256={str(path.relative_to(REPO)): digest(path) for path in
                            (REPO / 'tests/fixtures/sc173-derivative-mask').iterdir() if path.is_file()},
            negative_control='detected_and_restored' if any(
                record['case'] == 'broken_gate_same_assertion' and record['status'] == 'passed'
                for record in records) else 'not_qualified',
            passed=passed, exit=0 if passed else 1,
        )
    except Exception as exc:
        import traceback
        traceback.print_exc(file=stderr)
        receipt.update(passed=False, exit=1, preflight_or_harness_error=f'{type(exc).__name__}: {exc}')
    finally:
        sys.dont_write_bytecode = old_bytecode
    (output / 'stdout.log').write_text(stdout.getvalue())
    (output / 'stderr.log').write_text(stderr.getvalue())
    receipt['raw_logs'] = {name: digest(output / name) for name in ('stdout.log', 'stderr.log')}
    # No evidence writer remains after this receipt. Never update prior invocation files.
    (output / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(stderr.getvalue(), file=sys.stderr, end='')
    print(f"SC173 result: {output / 'result.json'}")
    print(f"Methods={receipt.get('tests_run', 0)} subcases={receipt.get('subcase_count', 0)} exit={receipt['exit']}")
    return receipt['exit']


if __name__ == '__main__':
    raise SystemExit(main())
