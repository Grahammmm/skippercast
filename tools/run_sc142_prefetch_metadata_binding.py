"""Run only SC142 tests, retaining isolated, offline synthetic evidence."""
import sys
sys.dont_write_bytecode = True

import argparse
import ast
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import importlib.util
import inspect
import io
import json
from pathlib import Path
import subprocess
import time
import unittest
import uuid

REPO = Path(__file__).resolve().parents[1]
BASE = '8a805820c30895f5f037e26af9079fd3dc015b0f'
TEST = REPO / 'tests/unit/test_sc142_prefetch_metadata_binding.py'
PRODUCT = REPO / 'research/scripts/coast_mvp/prefetch_receipts_check.py'
FIXTURE = REPO / 'tests/fixtures/sc142-prefetch-metadata-binding/metadata.json'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args):
    # Only literal read-only identity argv, before the product boundary installs.
    result = subprocess.run(['git', '-C', str(REPO), *args], text=True, capture_output=True, check=True)
    return result.stdout.strip()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def preflight(manifest_path):
    manifest = json.loads(manifest_path.read_text())
    root = REPO.parent
    initial = json.loads((root / 'INITIAL-STAGE.json').read_text())
    spec = json.loads((root / 'ACCEPTANCE-SPEC.json').read_text())
    require(manifest['schema'] == 'agentorange.source-manifest/v1', 'manifest schema')
    require(manifest['write_root'] == str(root) and manifest['repo'] == str(REPO), 'candidate/repo identity')
    require(manifest['card'] == root.name, 'candidate card identity')
    require(manifest['head'] == BASE == initial['head'], 'admitted base identity')
    require(manifest['clean'] is True and all(initial['checks'].values()), 'initial clean stage proof')
    require(sha(manifest_path) == initial['manifest_sha256'] == spec['manifest_sha256'], 'manifest changed')
    require(Path(manifest['runtime']['repo_venv']) == (REPO / '.venv').resolve(), 'venv identity')
    require(Path(sys.executable).absolute() == REPO / '.venv/bin/python3', 'literal repo interpreter')
    scan = manifest['runtime']['credential_scan_python3']
    # Initial staging verified the brief's literal interpreter; the immutable
    # manifest hash above binds that proof without baking a box path into tools.
    require(initial['checks']['scan_runtime'] is True, 'scan interpreter proof')
    require(Path(scan).is_file(), 'scan runtime missing')
    require((REPO / '.venv/bin/python3').is_file(), 'repo runtime missing')
    head = git('rev-parse', 'HEAD')
    ancestry = subprocess.run(['git', '-C', str(REPO), 'merge-base', '--is-ancestor', BASE, head], capture_output=True)
    require(ancestry.returncode == 0, 'head not a descendant of base')
    parsed = ast.parse(PRODUCT.read_text())
    imports = sorted({(node.module if isinstance(node, ast.ImportFrom) else alias.name).split('.')[0]
                      for node in ast.walk(parsed) if isinstance(node, (ast.Import, ast.ImportFrom))
                      for alias in (node.names if isinstance(node, ast.Import) else [None])})
    require(set(imports) <= sys.stdlib_module_names | {'__future__'}, 'unexpected import closure')
    require(imports == initial['imports'], 'import closure changed')
    require(not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ('eval', 'exec', '__import__') for node in ast.walk(parsed)), 'dynamic import/code')
    return {'manifest_sha256': sha(manifest_path), 'acceptance_spec_sha256': sha(root / 'ACCEPTANCE-SPEC.json'),
            'initial_stage_sha256': sha(root / 'INITIAL-STAGE.json'), 'head': head, 'base': BASE,
            'status': git('status', '--porcelain=v1'), 'imports': imports,
            'read_only_source_closure': [str(PRODUCT.relative_to(REPO)), str(TEST.relative_to(REPO)), str(FIXTURE.relative_to(REPO))],
            'producer_vocabulary_only': 'src/skippercast/coastal/prefetch.py (read-only, not imported)',
            'data_closure': 'Only unique run root: inventory.json, reviewed-hosts.json, receipts/source/manifest.jsonl, payload/output sentinels',
            'ambient_product_data_roots': [], 'bound_external_data_defaults': [],
            'integration_owed': 'Full original repository integration/required CI on exact head; no upstream acceptance inferred.'}


class RecordedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.executed = []
        self.subtests = 0

    def startTest(self, test):
        self.executed.append(test.id())
        super().startTest(test)

    def addSubTest(self, test, subtest, outcome):
        self.subtests += 1
        super().addSubTest(test, subtest, outcome)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', required=True, choices=('preflight', 'regression', 'compatibility', 'negative-control', 'baseline'))
    parser.add_argument('--source-manifest', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    prefix = args.out.absolute()
    require(prefix.is_relative_to(REPO.parent / 'out'), 'output must be candidate-local outside repo')
    require(not any(p.is_symlink() for p in (prefix, *prefix.parents)), 'output symlink refused')
    prefix.mkdir(parents=True, exist_ok=True)
    run = prefix / uuid.uuid4().hex
    run.mkdir(exist_ok=False)
    started = time.monotonic()
    identity = preflight(args.source_manifest)
    source_files = [PRODUCT, TEST, FIXTURE, Path(__file__).resolve(), args.source_manifest,
                    REPO.parent / 'ACCEPTANCE-SPEC.json', REPO.parent / 'INITIAL-STAGE.json']
    before = {str(p): sha(p) for p in source_files}
    spec = importlib.util.spec_from_file_location('sc142_tests', TEST)
    require(spec is not None and spec.loader is not None, 'test loader')
    tests = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tests)
    tests.RUN_ROOT = run
    stdout, stderr = io.StringIO(), io.StringIO()
    details = {}
    with redirect_stdout(stdout), redirect_stderr(stderr):
        if args.suite == 'preflight':
            case = tests.Regression('test_exact_metadata')
            case.setUp()
            try:
                details['check_signature'] = str(inspect.signature(case.product.check))
                details['guards'] = ['scoped no non-stdlib/model imports', 'no network/DNS', 'no product child', 'synthetic data open confinement', 'opaque payload access trap', 'bytecode disabled']
                require(sys.dont_write_bytecode, 'bytecode guard')
                require(tuple(case.product.GATES) == tests.EXPECTED_GATES, 'gate ordering')
            finally:
                case.doCleanups()
            ok = True
        elif args.suite == 'negative-control':
            with tests.offline_boundary(run):
                controls = tests.negative_controls()
            details['controls'] = controls
            ok = len(controls) == 2 and all(c['mutant_detected'] and c['positive_passed'] for c in controls)
        else:
            loader = unittest.TestLoader()
            cls = tests.Regression if args.suite == 'regression' else tests.Compatibility
            if args.suite == 'baseline':
                suite = unittest.TestSuite(tests.Regression(name) for name in ('test_exact_metadata', 'test_wrong_segment', 'test_repeated_union_and_copy'))
            else:
                frozen = json.loads((REPO.parent / 'ACCEPTANCE-SPEC.json').read_text())
                expected = set(frozen['mapping']['A1' if args.suite == 'regression' else 'A2'])
                require(set(loader.getTestCaseNames(cls)) == expected, 'frozen test ID mismatch')
                suite = loader.loadTestsFromTestCase(cls)
            result = unittest.TextTestRunner(stream=stderr, verbosity=2, resultclass=RecordedResult).run(suite)
            details.update(tests_run=result.testsRun, executed_ids=result.executed, subtests=result.subtests,
                           failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped))
            ok = result.wasSuccessful() and not result.skipped and result.testsRun > 0
    after = {str(p): sha(p) for p in source_files}
    require(before == after, 'source or frozen input changed during invocation')
    (run / 'stdout.txt').write_text(stdout.getvalue())
    (run / 'stderr.txt').write_text(stderr.getvalue())
    report = {'schema': 'sc142.run/v1', 'suite': args.suite, 'argv': sys.orig_argv,
              'cwd': str(Path.cwd()), 'duration_seconds': time.monotonic() - started,
              'exit_code': 0 if ok else 1, 'run_root': str(run), 'identity': identity,
              'details': details, 'source_hashes_before': before, 'source_hashes_after': after,
              'stdout_sha256': sha(run / 'stdout.txt'), 'stderr_sha256': sha(run / 'stderr.txt'),
              'test_evidence': tests.EVIDENCE}
    (run / 'result.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(stderr.getvalue(), end='')
    print(json.dumps({'suite': args.suite, 'exit_code': report['exit_code'], 'details': details,
                      'result': str(run / 'result.json'), 'result_sha256': sha(run / 'result.json')}, indent=2))
    return report['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
