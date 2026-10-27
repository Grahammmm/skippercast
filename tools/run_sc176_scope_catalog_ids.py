"""Offline SC176 acceptance runner; product APIs run only inside scoped tests."""
import argparse
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

BASE = '67ff9bcf34257698a41585bc2ad163171dc68259'
SOURCE_HASH = '83ed78d86b8245a2073849ba94cece3770e25e9ba81de75aff5f3bbb157bb718'
REPO = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args):
    return subprocess.check_output(['git', '-C', str(REPO), *args], text=True).strip()


class RecordingResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ids = []
        self.subcases = []

    def startTest(self, test):
        self.ids.append(test.id())
        super().startTest(test)

    def addSubTest(self, test, subtest, err):
        self.subcases.append({'id': subtest.id(), 'method': test._testMethodName,
                              'case': subtest.params.get('case'), 'passed': err is None})
        super().addSubTest(test, subtest, err)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-manifest', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--phase', choices=('baseline', 'candidate'), default='candidate')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix='sc176-', dir=args.out))
    record = {'schema': 'sc176.result/v1', 'phase': args.phase, 'argv': [sys.executable, *sys.argv],
              'cwd': str(Path.cwd()), 'interpreter': sys.executable, 'base': BASE,
              'status': 'FAIL', 'output': str(out), 'author_runtime': {
                  'model': 'gpt-6.1-sol', 'provider': 'openai-codex', 'run_id': 2118}}
    stdout_path = out / 'stdout.log'; stderr_path = out / 'stderr.log'
    exit_code = 1
    try:
        with stdout_path.open('w') as stdout, stderr_path.open('w') as stderr, \
                redirect_stdout(stdout), redirect_stderr(stderr):
            sys.dont_write_bytecode = True
            manifest = json.loads(args.source_manifest.read_text())
            spec_path = REPO.parent / 'ACCEPTANCE-SPEC.json'
            spec = json.loads(spec_path.read_text())
            record.update(head=git('rev-parse', 'HEAD'),
                          staging_manifest_sha256=digest(args.source_manifest),
                          acceptance_spec_sha256=digest(spec_path),
                          tracked_status=git('status', '--porcelain', '--untracked-files=no'))
            if manifest['schema'] != 'agentorange.source-manifest/v1':
                raise RuntimeError('Wrong staging schema')
            if (Path(manifest['write_root']).resolve() != REPO.parent.resolve()
                    or Path(manifest['repo']).resolve() != REPO.resolve()
                    or manifest['head'] != BASE or spec['base'] != BASE):
                raise RuntimeError('Staged identity or pinned base moved')
            venv = (REPO / '.venv').resolve()
            if (venv != Path(manifest['runtime']['repo_venv']).resolve()
                    or Path(sys.prefix).resolve() != venv
                    or Path(sys.executable).parent.parent.resolve() != venv):
                raise RuntimeError('Wrong repository interpreter')
            scanner = Path(manifest['runtime']['credential_scan_python3'])
            if scanner != REPO.parent.parent.parent / 'tools/venv-fullsuite/bin/python3':
                raise RuntimeError('Literal credential scan interpreter mismatch')
            if not scanner.is_file():
                raise RuntimeError('Missing operator scanner interpreter')
            base_source = subprocess.check_output([
                'git', '-C', str(REPO), 'show', BASE + ':src/skippercast/seafloor/source_scope.py'])
            if hashlib.sha256(base_source).hexdigest() != SOURCE_HASH:
                raise RuntimeError('Pinned complete source hash mismatch')
            if args.phase == 'baseline' and (record['head'] != BASE or
                    digest(REPO / 'src/skippercast/seafloor/source_scope.py') != SOURCE_HASH):
                raise RuntimeError('Baseline product bytes changed')
            test_path = REPO / 'tests/unit/test_sc176_scope_catalog_ids.py'
            loader = importlib.util.spec_from_file_location('test_sc176_scope_catalog_ids', test_path)
            if loader is None or loader.loader is None:
                raise RuntimeError('Missing regression test')
            module = importlib.util.module_from_spec(loader)
            loader.loader.exec_module(module)
            if spec['methods'] != module.REQUIRED_CASES:
                raise RuntimeError('Frozen requirements mapping differs from test collection')
            # Hash the inspected full import closure before any product import.
            closure = {str(Path('src/skippercast') / name): digest(REPO / 'src/skippercast' / name)
                       for name in module.fixture.CLOSURE}
            record['closure_sha256'] = closure
            record['authored_code_sha256'] = {
                str(path.relative_to(REPO)): digest(path)
                for path in (Path(__file__), test_path,
                             REPO / 'tests/fixtures/sc176-scope-catalog-ids/constructors.py')}
            record['fixture_sha256'] = {
                str(path.relative_to(REPO)): digest(path)
                for path in sorted((REPO / 'tests/fixtures/sc176-scope-catalog-ids').rglob('*'))
                if path.is_file() and '__pycache__' not in path.parts}
            module.fixture.OUTPUT_PREFIX = out / 'synthetic'
            suite = unittest.defaultTestLoader.loadTestsFromTestCase(module.ScopeCatalogIDsTests)
            if suite.countTestCases() != len(spec['methods']):
                raise RuntimeError('Empty or incomplete required method collection')
            result = unittest.TextTestRunner(stream=stderr, verbosity=2,
                                            resultclass=RecordingResult).run(suite)
            klass = module.ScopeCatalogIDsTests
            expected = {(method, case) for method, cases in spec['methods'].items() for case in cases}
            actual = {(case['method'], case['case']) for case in result.subcases}
            completed = {tuple(item) for item in klass.completed}
            record.update(tests_run=result.testsRun, test_ids=result.ids,
                          subcases=result.subcases, subcase_count=len(result.subcases),
                          passed_subcases=sum(case['passed'] for case in result.subcases),
                          failures=[{'id': test.id(), 'traceback': text} for test, text in result.failures],
                          errors=[{'id': test.id(), 'traceback': text} for test, text in result.errors],
                          skips=[{'id': test.id(), 'reason': why} for test, why in result.skipped],
                          missing_subcases=sorted(expected - actual),
                          uncompleted_subcases=sorted(expected - completed),
                          module_origins=klass.module_origins, run_roots=klass.run_roots,
                          negative_control=klass.negative_outcomes)
            passed = (result.wasSuccessful() and not result.skipped and result.testsRun == 4
                      and actual == expected and completed == expected
                      and len(result.subcases) == len(expected) and bool(klass.negative_outcomes))
            record['final_tracked_status'] = git('status', '--porcelain', '--untracked-files=no')
            stable = (digest(args.source_manifest) == record['staging_manifest_sha256']
                      and digest(spec_path) == record['acceptance_spec_sha256']
                      and git('rev-parse', 'HEAD') == record['head']
                      and all(digest(REPO / name) == value for name, value in closure.items())
                      and all(digest(REPO / name) == value
                              for name, value in record['authored_code_sha256'].items()))
            passed = passed and stable and not record['final_tracked_status']
            record['inputs_unchanged'] = stable
            record['status'] = 'PASS_REVIEW_REQUIRED' if passed else 'FAIL'
            exit_code = 0 if passed else 1
            print(json.dumps({'status': record['status'], 'tests_run': result.testsRun,
                              'subcase_count': len(result.subcases),
                              'passed_subcases': record['passed_subcases'], 'head': record['head']}))
    except Exception as error:
        import traceback
        with stderr_path.open('a') as stderr:
            traceback.print_exc(file=stderr)
        record['exception'] = type(error).__name__ + ': ' + str(error)
    # All raw-log writers are closed before hashes are sealed.
    record['raw_logs'] = {path.name: digest(path) for path in (stdout_path, stderr_path)}
    record['exit_code'] = exit_code
    (out / 'result.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    print(str(out / 'result.json'))
    print(record['status'])
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
