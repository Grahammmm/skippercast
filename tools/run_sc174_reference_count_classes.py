"""Retained SC174 acceptance evidence. No source acquisition or operational CLI."""
import argparse
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import traceback
import unittest
from unittest.mock import patch

BASE = '67ff9bcf34257698a41585bc2ad163171dc68259'
REPO = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


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
        self.subcases.append({'id': subtest.id(), 'passed': err is None,
                              'error': None if err is None else str(err[1])})
        super().addSubTest(test, subtest, err)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-manifest', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--baseline', action='store_true')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix='run-', dir=args.out))
    report = {'schema': 'sc174.result/v1', 'argv': sys.argv, 'cwd': str(Path.cwd()),
              'interpreter': sys.executable, 'base': BASE, 'baseline': args.baseline,
              'status': 'FAILED', 'exit': 1}
    result = None
    code = 1
    with (out / 'stdout.log').open('w') as stdout, (out / 'stderr.log').open('w') as stderr:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                manifest = json.loads(args.source_manifest.read_text())
                if manifest.get('schema') != 'agentorange.source-manifest/v1':
                    raise ValueError('Manifest schema mismatch')
                if Path(manifest['repo']).resolve() != REPO or Path(manifest['write_root']).resolve() != REPO.parent:
                    raise ValueError('Manifest repository/write-root mismatch')
                if manifest['head'] != BASE or git('rev-parse', f'{BASE}^{{tree}}') != manifest['tree']:
                    raise ValueError('Manifest staged source pin mismatch')
                if (REPO / '.venv').resolve() != Path(manifest['runtime']['repo_venv']).resolve():
                    raise ValueError('Manifest venv identity mismatch')
                if Path(sys.prefix).resolve() != Path(manifest['runtime']['repo_venv']).resolve():
                    raise ValueError('Wrong runtime; no interpreter substitution')
                scanner = Path(manifest['runtime']['credential_scan_python3'])
                if scanner != REPO.parent.parent.parent / 'tools/venv-fullsuite/bin/python3' or not scanner.is_file():
                    raise ValueError('Literal credential scan runtime unavailable/mismatched')
                spec_path = REPO.parent / 'ACCEPTANCE-SPEC.json'
                spec = json.loads(spec_path.read_text())
                report.update(head=git('rev-parse', 'HEAD'),
                              manifest_sha256=digest(args.source_manifest),
                              spec_sha256=digest(spec_path),
                              status_before=git('status', '--porcelain'),
                              fixture_sha256={p.name: digest(p) for p in sorted((REPO / 'tests/fixtures/sc174-reference-count-classes').glob('*')) if p.is_file()},
                              source_sha256=digest(REPO / 'src/skippercast/seafloor/grid.py'))
                if args.baseline and (report['head'] != BASE or report['source_sha256'] != '0b4ff703febcf919b78d5becb64cd475a2a9adabfa0bcc49440fcaf187a97089'):
                    raise ValueError('Red baseline requires unchanged pinned product bytes')
                path = REPO / 'tests/unit/test_sc174_reference_count_classes.py'
                report['authored_file_sha256'] = {str(p.relative_to(REPO)): digest(p) for p in (
                    path, Path(__file__), REPO / 'src/skippercast/seafloor/grid.py')}
                # Test module itself has no import-time product execution or writes.
                module_spec = importlib.util.spec_from_file_location('sc174_tests', path)
                if module_spec is None or module_spec.loader is None:
                    raise ValueError('Test module unavailable')
                module = importlib.util.module_from_spec(module_spec)
                with patch.object(sys, 'dont_write_bytecode', True):
                    module_spec.loader.exec_module(module)
                    names = spec['baseline']['methods'] if args.baseline else list(module.METHODS)
                    if not args.baseline and set(names) != set(spec['methods']):
                        raise ValueError('Required methods missing from collection')
                    suite = unittest.TestSuite(module.ReferenceCountClassesTests(name) for name in names)
                    if suite.countTestCases() != len(names) or not names:
                        raise ValueError('Empty/incomplete test collection')
                    with patch.dict(os.environ, {'SC174_OUTPUT_ROOT': str(out / 'synthetic-invocations')}):
                        result = unittest.TextTestRunner(stream=stderr, verbosity=2, resultclass=RecordingResult).run(suite)
                report.update(tests_run=result.testsRun, ids=result.ids, subcases=result.subcases,
                              failures=[{'id': t.id(), 'traceback': text} for t, text in result.failures],
                              errors=[{'id': t.id(), 'traceback': text} for t, text in result.errors],
                              skips=[{'id': t.id(), 'reason': reason} for t, reason in result.skipped],
                              origins=module.ReferenceCountClassesTests.origins,
                              test_evidence_root=str(module.ReferenceCountClassesTests.run_root))
                report['dependency_runtime'] = {
                    name: {'origin': getattr(sys.modules.get(name), '__file__', None),
                           'version': getattr(sys.modules.get(name), '__version__', None)}
                    for name in ('numpy', 'rasterio', 'pyproj', 'shapely', 'shapefile')}
                expected = {(method, case) for method in names for case in spec['methods'][method]}
                actual = {(row['method'], row['case']) for row in module.ReferenceCountClassesTests.records}
                complete = expected == actual and len(result.subcases) == len(expected)
                report['subcases_complete'] = complete
                report['subcase_count'] = len(result.subcases)
                report['negative_control_detected'] = (not args.baseline and any(
                    row['passed'] and "same-regression-detects-bypass" in row['id'] for row in result.subcases))
                if args.baseline:
                    report['deciding_red_reproduced'] = bool(complete and not result.errors and not result.skipped
                        and result.failures and all('test_regression' in t.id() and 'ValueError not raised' in text
                                                   for t, text in result.failures)
                        and all(row['passed'] for row in result.subcases if 'test_compatibility' in row['id']))
                    # An observed red stays red, never converted to acceptance PASS.
                    report['status'] = 'EXPECTED_RED' if report['deciding_red_reproduced'] else 'FAILED'
                elif result.wasSuccessful() and not result.skipped and complete and report['negative_control_detected']:
                    code = 0
                    report['status'] = 'REVIEW_REQUIRED'
                if digest(args.source_manifest) != report['manifest_sha256'] or digest(spec_path) != report['spec_sha256']:
                    raise ValueError('Frozen input changed during run')
            except Exception:
                traceback.print_exc()
                code = 1
                report['status'] = 'FAILED'
    # All log writers have closed before sealing. This result is never rewritten.
    report['exit'] = code
    report['log_sha256'] = {p.name: digest(p) for p in (out / 'stdout.log', out / 'stderr.log')}
    (out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'output': str(out), 'status': report['status'], 'exit': code,
                      'tests': report.get('tests_run'), 'subcases': report.get('subcase_count')}))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
