"""Bounded SC175 full-API acceptance runner; never an operational source CLI."""
import argparse
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import traceback
import unittest
from unittest.mock import patch

BASE = '67ff9bcf34257698a41585bc2ad163171dc68259'
BASE_MANIFEST_SHA256 = '9b694cde93fe9a9bdd08b85f5bc558b3cbcf3dd96085dfce4d3c78ff048385f5'
METHODS = ('test_regression', 'test_compatibility', 'test_negative_control', 'test_preservation')
REQUIRED_SUBCASE_COUNTS = {'test_regression': 66, 'test_compatibility': 70,
                           'test_negative_control': 30, 'test_preservation': 30}
REPO = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args):
    result = subprocess.run(['git', '-C', str(REPO), *args], capture_output=True, check=True)
    return result.stdout.decode().strip()


class RecordingResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ids, self.subcases = [], []

    def startTest(self, test):
        self.ids.append(test.id())
        super().startTest(test)

    def addSubTest(self, test, subtest, err):
        self.subcases.append({'method': test._testMethodName, 'id': subtest.id(),
                              'params': {key: repr(value) for key, value in subtest.params.items()},
                              'outcome': 'pass' if err is None else 'fail'})
        super().addSubTest(test, subtest, err)


def preflight(manifest_path):
    stage = json.loads(manifest_path.read_text())
    if stage.get('schema') != 'agentorange.source-manifest/v1':
        raise ValueError('Wrong staging schema')
    if Path(stage['repo']).resolve() != REPO or Path(stage['write_root']).resolve() != REPO.parent:
        raise ValueError('Wrong staging repo/write_root')
    if stage['head'] != BASE or git('rev-parse', BASE) != BASE:
        raise ValueError('Moved staged base')
    if git('rev-parse', BASE + '^{tree}') != stage['tree']:
        raise ValueError('Wrong staged tree')
    baseline = subprocess.run(['git', '-C', str(REPO), 'show', BASE + ':src/skippercast/seafloor/manifest.py'],
                              check=True, capture_output=True).stdout
    if hashlib.sha256(baseline).hexdigest() != BASE_MANIFEST_SHA256:
        raise ValueError('Wrong pinned source hash')
    git('merge-base', '--is-ancestor', BASE, 'HEAD')
    runtime = stage['runtime']
    if (REPO / '.venv').resolve() != Path(runtime['repo_venv']).resolve():
        raise ValueError('Wrong staged venv link')
    if Path(sys.prefix).resolve() != Path(runtime['repo_venv']).resolve():
        raise ValueError('Wrong running interpreter venv')
    if not Path(runtime['credential_scan_python3']).is_file():
        raise ValueError('Missing literal scan interpreter')
    for relative in ('src/skippercast/__init__.py', 'src/skippercast/paths.py',
                     'src/skippercast/util/__init__.py', 'src/skippercast/util/time.py',
                     'src/skippercast/platform/__init__.py', 'src/skippercast/platform/contracts.py',
                     'src/skippercast/seafloor/__init__.py', 'src/skippercast/seafloor/manifest.py',
                     'src/skippercast/seafloor/rights.py'):
        if not (REPO / relative).is_file():
            raise ValueError('Incomplete statically inspected product closure: ' + relative)
    return stage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-manifest', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix='run-', dir=args.out))
    report = {'schema': 'sc175.result/v1', 'base': BASE, 'argv': [sys.executable, *sys.argv],
              'cwd': str(Path.cwd()), 'interpreter': sys.executable, 'runtime_prefix': sys.prefix,
              'status': 'FAIL', 'run': str(run)}
    old_bytecode = sys.dont_write_bytecode
    old_path = sys.path[:]
    exit_code = 1
    with (run / 'stdout.log').open('w') as stdout, (run / 'stderr.log').open('w') as stderr:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                sys.dont_write_bytecode = True
                stage = preflight(args.source_manifest)
                report.update(head=git('rev-parse', 'HEAD'),
                    staging_manifest_sha256=digest(args.source_manifest),
                    spec_sha256=digest(REPO.parent / 'ACCEPTANCE-SPEC.json'),
                    brief_sha256=digest(REPO.parent / 'ADMITTED-BRIEF.txt'),
                    fixture_hashes={str(p.relative_to(REPO)): digest(p) for p in sorted(
                        (REPO / 'tests/fixtures/sc175-qualification-copy').rglob('*')) if p.is_file()},
                    runtime=stage['runtime'])
                file = REPO / 'tests/unit/test_sc175_qualification_copy.py'
                # Bootstrap standalone runner imports; tests use shared ROOT and
                # the normal source path rather than managing their own paths.
                sys.path[:0] = [str(REPO), str(REPO / 'src')]
                spec = importlib.util.spec_from_file_location('sc175_tests', file)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                suite = unittest.TestSuite(module.QualificationCopyTests(name) for name in METHODS)
                fixture_root = run / 'synthetic'
                fixture_root.mkdir()
                with patch.object(tempfile, 'tempdir', str(fixture_root)):
                    result = unittest.TextTestRunner(stream=stderr, verbosity=2,
                                                    resultclass=RecordingResult).run(suite)
                report.update(tests_run=result.testsRun, test_ids=result.ids, subcases=result.subcases,
                    failures=[{'id': test.id(), 'traceback': text} for test, text in result.failures],
                    errors=[{'id': test.id(), 'traceback': text} for test, text in result.errors],
                    skips=[{'id': test.id(), 'reason': why} for test, why in result.skipped],
                    imported_module_origins=module.IMPORTED_ORIGINS)
                required_shapes = set(json.loads((REPO.parent / 'ACCEPTANCE-SPEC.json').read_text())['required_shapes'])
                coverage_errors = []
                for name in METHODS:
                    cases = [case for case in result.subcases if case['method'] == name]
                    actual_shapes = {case['params'].get('shape') for case in cases}
                    if not cases or not {repr(shape) for shape in required_shapes} <= actual_shapes:
                        coverage_errors.append('Missing subcases/shapes: ' + name)
                report['coverage_errors'] = coverage_errors
                report['subcase_counts'] = {name: sum(case['method'] == name for case in result.subcases) for name in METHODS}
                report['negative_control'] = {key: sum(case['method'] == 'test_negative_control'
                    and case['params'].get('case') == repr(value) and case['outcome'] == 'pass'
                    for case in result.subcases) for key, value in
                    [('alias_detections', 'alias-detected'), ('restored_isolation_positives', 'genuine-restored-isolation')]}
                expected_ids = {'sc175_tests.QualificationCopyTests.' + name for name in METHODS}
                if (result.wasSuccessful() and not result.skipped and result.testsRun == len(METHODS)
                        and set(result.ids) == expected_ids and not coverage_errors
                        and report['subcase_counts'] == REQUIRED_SUBCASE_COUNTS
                        and report['negative_control'] == {'alias_detections': 12, 'restored_isolation_positives': 12}
                        and len(module.IMPORTED_ORIGINS) >= 9):
                    report['status'] = 'PASS_REVIEW_REQUIRED'
                    exit_code = 0
                report['product_sha256'] = digest(REPO / 'src/skippercast/seafloor/manifest.py')
                if report['staging_manifest_sha256'] != digest(args.source_manifest):
                    raise ValueError('Staging manifest changed during run')
            except Exception:
                report['exception'] = traceback.format_exc()
                traceback.print_exc()
                report['status'] = 'FAIL'
                exit_code = 1
            finally:
                sys.dont_write_bytecode = old_bytecode
                sys.path[:] = old_path
    report['log_hashes'] = {name: digest(run / name) for name in ('stdout.log', 'stderr.log')}
    report['exit_code'] = exit_code
    (run / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'result': str(run / 'result.json'), 'status': report['status'],
                      'tests': report.get('tests_run'), 'subcase_counts': report.get('subcase_counts'),
                      'failures': len(report.get('failures', [])), 'errors': len(report.get('errors', [])),
                      'skips': len(report.get('skips', [])), 'negative_control': report.get('negative_control')}, indent=2))
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
